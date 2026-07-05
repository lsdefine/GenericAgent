#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Topic summary adapter for Rust WeChat multi-chat (channel 2).

Watches each group target's shadow jsonl. When a group is (or was recently)
in high-frequency mode and has been idle for >= idle_minutes, summarize the
buffered messages from Shen Xinghui's perspective and inject the summary
into the xinghui agent_context backend_history so it appears on the clawbot
session timeline.

Modes:
    daemon  - long-running loop, default interval 30s
    once    - scan every group once, summarize any ready buffer
    group <target_id> - force summarize this group now (ignore idle gate)

No Rust restart required.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GA_ROOT = PLUGIN_ROOT.parents[1]
LOCAL_FRONTENDS_DIR = GA_ROOT / "plugins" / "local_frontends"
sys.path.insert(0, str(GA_ROOT))
sys.path.insert(0, str(LOCAL_FRONTENDS_DIR))
try:
    from session_history import visible_dialog_only as _visible_dialog_only
except Exception:
    _visible_dialog_only = None
try:
    from prompt_config import format_prompt, get_prompt_config, get_agent_display_name
except Exception:
    def format_prompt(_key, default='', **kwargs):
        out = str(default or '')
        for k, v in kwargs.items():
            out = out.replace('{{' + k + '}}', str(v))
        return out
    def get_prompt_config(_path, default=None):
        return default
    def get_agent_display_name(default='assistant'):
        return default

_POLLUTION_MARKERS = (
    "<summary", "</summary>", "🛠️", "### [WORKING MEMORY]",
    "<earlier_context>", "</earlier_context>", "<history>", "</history>",
    "<key_info>", "</key_info>", "Current turn:", "[PLANNING]",
    "[ACTIONS]", "[DANGER]", "If you need to show files to user",
)


WECHAT_PLATFORM_MARKER = "【.微信线上平台.】"


def _clean_context_text(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if _visible_dialog_only is not None:
        try:
            text = _visible_dialog_only(text).strip()
        except Exception:
            text = str(value or '').strip()
    # Defense-in-depth: wechat_context is side awareness, not a place to keep
    # agent-shell transcripts.  If sanitizer cannot fully recover visible text,
    # drop this context item instead of leaking wrappers into xinghui:main.
    if any(marker in text for marker in _POLLUTION_MARKERS):
        return ''
    return text


def _with_wechat_platform_marker(text):
    text = str(text or '').strip()
    if not text:
        return ''
    if WECHAT_PLATFORM_MARKER in text:
        return text
    return f"{WECHAT_PLATFORM_MARKER}{text}"

CONFIG_PATH = PLUGIN_ROOT / "config" / "config.json"
STATE_PATH = PLUGIN_ROOT / "runtime" / "state.json"
SHADOW_DIR = PLUGIN_ROOT / "shadow"
SUMMARY_STATE_PATH = PLUGIN_ROOT / "runtime" / "topic_summary_state.json"
LOCAL_FRONTENDS_STATE_DIR = GA_ROOT / "plugins" / "local_frontends" / "runtime" / "state"
WECHAT_SESSION_STATE_PATH = LOCAL_FRONTENDS_STATE_DIR / "wechat_session_state.json"
LEGACY_WECHAT_SESSION_STATE_PATH = GA_ROOT / "temp" / "wechat_session_state.json"  # diagnostics/symlink compatibility only
AGENT_CONTEXT_PATH = GA_ROOT / "temp" / "agent_context_xinghui.json"  # legacy, kept for diagnostics only


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_state():
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_summary_state():
    if not SUMMARY_STATE_PATH.exists():
        return {}
    try:
        with SUMMARY_STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_ts(val):
    """Accept float epoch, int epoch, or ISO-8601 string; return float epoch."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except Exception:
        pass
    # ISO8601 with tz, e.g. 2026-05-10T15:12:32.368575776+08:00
    try:
        # python fromisoformat doesn't handle ns precision; trim
        import re
        s2 = re.sub(r"(\.\d{6})\d+", r"\1", s)
        return dt.datetime.fromisoformat(s2).timestamp()
    except Exception:
        return 0.0


def save_summary_state(data):
    SUMMARY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SUMMARY_STATE_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(SUMMARY_STATE_PATH)


def read_shadow_after(target_id, after_ts):
    """Return shadow records newer than after_ts."""
    path = SHADOW_DIR / f"{target_id}.jsonl"
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = parse_ts(rec.get("ts"))
            if ts <= after_ts:
                continue
            out.append(rec)
    return out


def _is_shenxinghui_display_name(sender):
    """Return True for display names that may collide with the bot persona name.

    Identity must still be determined only by record role/is_self.  This helper is
    only for rendering peer messages with an explicit non-self label so the
    summary model will not treat a same-nickname group member as "me".
    """
    s = str(sender or "").strip().lower()
    if not s:
        return False
    aliases = tuple(get_prompt_config('identity.agent_aliases', ['assistant', 'bot']) or [])
    return any(a.lower() in s for a in aliases)


def format_buffer_for_prompt(records, title):
    """Render buffered records as plain readable chat log."""
    lines = []
    for rec in records:
        ts = parse_ts(rec.get("ts"))
        hm = dt.datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "--:--"
        role = str(rec.get("role") or "")
        text = str(rec.get("text") or "").strip()
        if not text:
            continue
        meta = rec.get("meta") or {}
        sender = str(meta.get("sender") or "").strip()
        if role == "self":
            who = format_prompt('rust_topic_summary.self_label', '我({{agent_name}})', agent_name=get_agent_display_name('assistant'))  # only role=self/is_self means the bot itself
        elif _is_shenxinghui_display_name(sender):
            who = format_prompt('rust_topic_summary.nonself_collision_label', '群友{{sender}}(非我/不是{{agent_name}}本人)', sender=sender, agent_name=get_agent_display_name('assistant'))
        else:
            who = sender or "某人"  # 某人
        lines.append(f"[{hm}] {who}: {text}")
    return "\n".join(lines)


def time_window(records):
    if not records:
        return "", ""
    ts0 = parse_ts(records[0].get("ts"))
    ts1 = parse_ts(records[-1].get("ts"))
    fmt = "%H:%M"
    s0 = dt.datetime.fromtimestamp(ts0).strftime(fmt) if ts0 else "--:--"
    s1 = dt.datetime.fromtimestamp(ts1).strftime(fmt) if ts1 else "--:--"
    return s0, s1


def build_summary_prompt(title, user_aliases, chat_log):
    user_hint = ""
    if user_aliases:
        joined = "、".join(user_aliases)
        user_hint = format_prompt(
            'rust_topic_summary.user_hint',
            '特殊关系对象别名：{{joined}}。若话题涉及此人，要记录其说了什么、别人如何回应、你当时如何回应；不要泛泛抒情，不要编造未出现的状态。\n',
            joined=joined,
        )
    agent_name = get_agent_display_name('assistant')
    self_label = format_prompt('rust_topic_summary.self_label', '我({{agent_name}})', agent_name=agent_name)
    return format_prompt(
        'rust_topic_summary.summary_prompt',
        '下面是微信群聊《{{title}}》中一段高频对话。请以当前主会话视角，把这段内容整理成可注入 session 的时间线。\n{{user_hint}}---对话记录---\n{{chat_log}}\n---END---',
        title=title,
        user_hint=user_hint,
        chat_log=chat_log,
        agent_name=agent_name,
        self_label=self_label,
    )


def call_main_model(prompt, agent_cfg, target_id, session_key):
    """Invoke GeneraticAgent to produce the summary text."""
    from agentmain import GeneraticAgent

    agent = GeneraticAgent()
    agent.llm_no = int(agent_cfg.get("llm_no") or 0)
    agent.next_llm(agent.llm_no)
    try:
        agent.llmclient.backend.stream = False
    except Exception:
        pass
    agent.verbose = False
    agent.inc_out = False
    agent.task_dir = str(PLUGIN_ROOT / "temp")

    out_q = queue.Queue()
    worker = threading.Thread(target=agent.run, daemon=True)
    worker.start()
    wrapped = (
        f"[\u5fae\u4fe1\u591a\u804a\u6458\u8981\u4efb\u52a1 | session={session_key} | target={target_id}]\n"
        f"{prompt}"
    )
    source = f"wechat_multi_timeline:{target_id}"
    agent.task_queue.put({"query": wrapped, "source": source, "output": out_q})

    timeout_s = int(agent_cfg.get("summary_timeout_s") or 120)
    final = ""
    try:
        while True:
            item = out_q.get(timeout=timeout_s)
            if "done" in item:
                final = item.get("done") or ""
                break
    finally:
        try:
            agent.abort()
        except Exception:
            pass
    return (final or "").strip()


def inject_into_agent_context(summary_text, title, ts_start, ts_end):
    """Append Shen Xinghui POV high-frequency group timeline into session wechat_context.

    This must never write into backend_history. backend_history is reserved for
    visible clawbot/private dialogue; group awareness is runtime context.
    """
    if not summary_text:
        return False
    WECHAT_SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now().isoformat(timespec="seconds")
    clean_summary = _clean_context_text(summary_text)
    if not clean_summary:
        return False
    content = _with_wechat_platform_marker(f"[{ts_start}-{ts_end}｜{title}] {clean_summary}")
    new_entry = {
        "role": "system",
        "content": content,
        "text": content,
        "ts": now,
        "ts_sort": f"{dt.date.today().isoformat()} {ts_start}",
        "source": "wechat_multi_chat_rust_group_timeline",
        "kind": "group_timeline",
        "wechat_title": title,
        "ts_start": ts_start,
        "ts_end": ts_end,
    }

    mode = "r+" if WECHAT_SESSION_STATE_PATH.exists() else "w+"
    with WECHAT_SESSION_STATE_PATH.open(mode, encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            raw = f.read().strip()
            if not raw:
                all_data = {}
            else:
                try:
                    all_data = json.loads(raw)
                    if not isinstance(all_data, dict):
                        all_data = {}
                except Exception:
                    all_data = {}
            sess = all_data.get("xinghui:main")
            if not isinstance(sess, dict):
                sess = {"backend_history": [], "wechat_context": []}
            sess.setdefault("backend_history", [])
            ctx = sess.get("wechat_context")
            if not isinstance(ctx, list):
                ctx = []
            cleaned = []
            for e in ctx:
                if not isinstance(e, dict):
                    continue
                old_kind = "group" + "_" + "summary"
                old_source = "wechat_multi_chat_rust" + "_topic" + "_summary"
                if e.get("kind") == old_kind or e.get("source") == old_source:
                    continue
                # Keep historical wechat_context only if its visible payload can be
                # cleaned.  This removes post-upgrade agent-shell/tool transcripts
                # that were accidentally summarized into group awareness.
                raw_content = e.get("content", e.get("text", ""))
                clean_content = _clean_context_text(raw_content)
                if not clean_content:
                    continue
                clean_content = _with_wechat_platform_marker(clean_content)
                e = dict(e)
                e["content"] = clean_content
                e["text"] = clean_content
                cleaned.append(e)
            cleaned.append(new_entry)
            max_items = int(os.environ.get("WECHAT_SESSION_WECHAT_CONTEXT_MAX", os.environ.get("WECHAT_SESSION_HISTORY_MAX", "400")))
            if max_items > 0:
                cleaned = cleaned[-max_items:]
            sess["wechat_context"] = cleaned
            sess["last_update"] = now
            sess["last_source"] = "wechat_multi_chat_rust_group_timeline"
            sess["agent_context_file"] = str(WECHAT_SESSION_STATE_PATH)
            sess["legacy_context_file"] = str(AGENT_CONTEXT_PATH)
            all_data["xinghui:main"] = sess
            f.seek(0)
            f.truncate()
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    return True


def process_target(target, summary_state, cfg, force=False, dry_run=False):
    """Summarize one target if ready. Returns a status dict."""
    target_id = target.get("id")
    title = target.get("wechat_title") or target.get("name") or target_id
    kind = target.get("kind") or "group"
    if kind != "group":
        return {"target": target_id, "action": "skip", "reason": "not group"}
    if not target.get("enable", True):
        return {"target": target_id, "action": "skip", "reason": "disabled"}

    ts_cfg = cfg.get("topic_summary", {}) or {}
    idle_minutes = float(ts_cfg.get("idle_minutes") or 2)
    min_msgs = int(ts_cfg.get("min_messages") or 2)

    cursor = (summary_state.get(target_id) or {}).get("last_summary_ts") or 0.0
    records = read_shadow_after(target_id, cursor)
    if not records:
        return {"target": target_id, "action": "skip", "reason": "no new records"}

    peer_records = [r for r in records if (r.get("role") or "") != "self"]
    if len(peer_records) < min_msgs and not force:
        return {"target": target_id, "action": "skip", "reason": f"only {len(peer_records)} peer msgs"}

    last_peer_ts = 0.0
    for r in peer_records:
        ts = parse_ts(r.get("ts"))
        if ts > last_peer_ts:
            last_peer_ts = ts
    now = time.time()
    if not force and (now - last_peer_ts) < idle_minutes * 60:
        wait_left = idle_minutes * 60 - (now - last_peer_ts)
        return {"target": target_id, "action": "skip", "reason": f"still active, wait {int(wait_left)}s"}

    chat_log = format_buffer_for_prompt(records, title)
    if not chat_log.strip():
        return {"target": target_id, "action": "skip", "reason": "empty chat log"}

    user_aliases = list(target.get("user_aliases") or cfg.get("user_aliases") or [])
    prompt = build_summary_prompt(title, user_aliases, chat_log)

    agent_cfg = cfg.get("agent") or {}
    session_key = target.get("session_key") or agent_cfg.get("session_key") or "xinghui:main"
    if os.environ.get("TOPIC_SUMMARY_DRY_RUN") == "1":
        summary_text = f"[DRY_RUN] 群「{title}」共 {len(records)} 条消息的占位摘要"
    else:
        try:
            summary_text = call_main_model(prompt, agent_cfg, target_id, session_key)
        except Exception as e:
            return {"target": target_id, "action": "error", "reason": f"llm call failed: {e!r}"}

    summary_text = (summary_text or "").strip()
    if summary_text.startswith("```") and summary_text.endswith("```"):
        lines = summary_text.splitlines()
        if len(lines) >= 3:
            summary_text = "\n".join(lines[1:-1]).strip()

    if not summary_text:
        return {"target": target_id, "action": "skip", "reason": "empty timeline from model"}

    ts_start, ts_end = time_window(records)
    ok = inject_into_agent_context(summary_text, title, ts_start, ts_end)
    if not ok:
        return {"target": target_id, "action": "error", "reason": "inject failed"}

    new_cursor = (parse_ts(records[-1].get("ts")) or last_peer_ts or now)
    summary_state[target_id] = {
        "last_summary_ts": new_cursor,
        "last_run_at": now,
        "last_window": f"{ts_start}-{ts_end}",
        "last_msg_count": len(records),
    }
    return {
        "target": target_id,
        "action": "timeline_injected",
        "window": f"{ts_start}-{ts_end}",
        "messages": len(records),
        "chars": len(summary_text),
    }


def scan_once(force_target_id=None):
    cfg = load_config()
    state = load_state()
    summary_state = load_summary_state()
    results = []

    targets = cfg.get("targets") or []
    for target in targets:
        target_id = target.get("id")
        if force_target_id and target_id != force_target_id:
            continue
        if not force_target_id:
            t_state = (state.get("targets") or {}).get(target_id) or {}
            mode = t_state.get("mode") or "low"
            last_high_ts = parse_ts(t_state.get("last_high_ts"))
            recently_high = (time.time() - last_high_ts) <= 30 * 60 if last_high_ts else False
            if mode != "high" and not recently_high:
                continue
        res = process_target(target, summary_state, cfg, force=bool(force_target_id))
        results.append(res)

    save_summary_state(summary_state)
    return results


def run_daemon(interval_s=30):
    print(f"[topic_summary] daemon started, interval={interval_s}s", flush=True)
    while True:
        try:
            results = scan_once()
            if results:
                for r in results:
                    if r.get("action") in ("timeline_injected", "error"):
                        print(f"[topic_summary] {json.dumps(r, ensure_ascii=False)}", flush=True)
        except Exception as e:
            print(f"[topic_summary] scan error: {e!r}", flush=True)
        time.sleep(interval_s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="once", choices=["once", "daemon", "group"])
    ap.add_argument("target_id", nargs="?", default=None)
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args()

    if args.mode == "daemon":
        run_daemon(args.interval)
    elif args.mode == "group":
        if not args.target_id:
            print(json.dumps({"error": "group mode needs target_id"}), flush=True)
            sys.exit(2)
        results = scan_once(force_target_id=args.target_id)
        print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    else:
        results = scan_once()
        print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
