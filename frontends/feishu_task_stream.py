import json
import os
import re
import threading
import time

from frontends.feishu_cards import build_progress_card, build_status_card, build_task_workspace_card
from frontends.feishu_post import (
    build_post_payload,
    derive_operational_card_title,
    derive_post_title,
    should_send_operational_card,
    should_send_post,
)


WORKSPACE_CARD_ENABLED = os.environ.get("GA_FEISHU_TASK_WORKSPACE_CARD", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
WORKSPACE_MAX_STEPS = int(os.environ.get("GA_FEISHU_WORKSPACE_MAX_STEPS", "8") or "8")
WORKSPACE_FINAL_CHARS = int(os.environ.get("GA_FEISHU_WORKSPACE_FINAL_CHARS", "8500") or "8500")
WORKSPACE_PROGRESS_AFTER_TURNS = int(os.environ.get("GA_FEISHU_WORKSPACE_PROGRESS_AFTER_TURNS", "2") or "2")
WORKSPACE_PROGRESS_AFTER_SEC = float(os.environ.get("GA_FEISHU_WORKSPACE_PROGRESS_AFTER_SEC", "8") or "8")

_CASUAL_FINAL_MAX_CHARS = int(os.environ.get("GA_FEISHU_CASUAL_FINAL_MAX_CHARS", "180") or "180")
_STRUCTURED_FINAL_RE = re.compile(
    r"(^|\n)\s*(#{1,6}\s+|[-*]\s+|\d+[.、]\s+|```|>\s+)|"
    r"(任务\s*\d+\s*[:：]|Tool Calls|Outputs?|结论|报告|汇报|状态|PID|文件位置|使用方法)",
    re.IGNORECASE,
)


def split_message(text, limit=7000):
    text = str(text or "")
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def natural_group_final(text):
    text = str(text or "").strip()
    text = re.sub(
        r"^\s*(?:\*\*)?(?:✅\s*)?(?:结论|最终结论|完成|已完成)(?:\*\*)?\s*[:：]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^\s*[-=]{3,}\s*", "", text)
    return text.strip() or "_(无文本输出)_"


def should_send_plain_final(text, *, turn_count=0, group_compact=False):
    raw = str(text or "").strip()
    visible = natural_group_final(raw)
    if not visible or len(visible) > _CASUAL_FINAL_MAX_CHARS:
        return False
    if turn_count:
        return False
    if should_send_operational_card(raw) or should_send_post(raw):
        return False
    if _STRUCTURED_FINAL_RE.search(raw):
        return False
    if group_compact:
        return True
    return "\n" not in visible


def fmt_tool_call(tc, max_args=240):
    name = tc.get("tool_name", "?")
    args = {k: v for k, v in (tc.get("args") or {}).items() if not str(k).startswith("_")}
    arg_text = json.dumps(args, ensure_ascii=False, default=str)
    if len(arg_text) > max_args:
        arg_text = arg_text[:max_args] + "..."
    return f"- `{name}`({arg_text})"


def _clip_line(text, *, limit=520):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _path_tail(path):
    text = str(path or "").strip()
    if not text:
        return ""
    parts = re.split(r"[/\\]", text)
    return parts[-1] or text


def _human_tool_action(tc):
    name = str(tc.get("tool_name") or "?")
    args = tc.get("args") or {}
    if name in {"file_read", "read_file"}:
        return f"读取 `{_path_tail(args.get('path') or args.get('file_path')) or '文件'}`"
    if name in {"file_patch", "apply_patch", "edit_file"}:
        return f"更新 `{_path_tail(args.get('path') or args.get('file_path')) or '文件'}`"
    if name in {"file_write", "write_file"}:
        return f"写入 `{_path_tail(args.get('path') or args.get('file_path')) or '文件'}`"
    if name in {"code_run", "execute_code", "run_command"}:
        script = args.get("script") or args.get("code") or args.get("cmd") or ""
        return f"运行命令/脚本：{_clip_line(script, limit=120)}"
    if name == "delegate_task":
        tasks = args.get("tasks") or []
        return f"并行调研 {len(tasks)} 个子任务" if isinstance(tasks, list) else "启动并行调研"
    if name in {"learning_pipeline", "learning_asset_update"}:
        return "沉淀学习资产"
    if name in {"cognitive_dream", "cognitive_store", "cognitive_retrieval"}:
        return "读取或更新认知记忆"
    return f"调用 `{name}`"


def _extract_result_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("summary", "msg", "message", "output", "stdout", "stderr", "error", "content", "final", "result"):
            item = value.get(key)
            if item:
                if isinstance(item, (dict, list)):
                    return json.dumps(item, ensure_ascii=False, default=str)
                return str(item)
        status = value.get("status")
        if status:
            return f"状态={status}"
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, list):
        if not value:
            return ""
        snippets = [_extract_result_text(item) for item in value[:3]]
        return "；".join(s for s in snippets if s)
    return str(value)


def _human_tool_result(result):
    text = _extract_result_text(result)
    text = re.sub(r"<summary>[\s\S]*?</summary>", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```[\s\S]{900,}?```", "[长代码块已省略]", text)
    text = re.sub(r"\{\\?\"[^\\n]{900,}", "[结构化输出已省略]", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    useful = []
    for line in lines:
        if line.startswith("[Info] Final response"):
            continue
        if line.startswith("[Action]") or line.startswith("[Status]") or line.startswith("[Warn]"):
            useful.append(_clip_line(line, limit=360))
            continue
        if len(line) < 220 or any(
            token in line for token in ("已", "完成", "失败", "错误", "保存", "路径", "写入", "读取")
        ):
            useful.append(_clip_line(line, limit=360))
        if len(useful) >= 3:
            break
    return "\n".join(f"- {item}" for item in useful[:3])


def _strip_list_prefix(text):
    return re.sub(r"^\s*[-*]\s*", "", str(text or "")).strip()


def build_visible_self_talk(summary, tool_calls=None, tool_results=None, content=""):
    summary = _clip_line(summary, limit=180)
    actions = [_human_tool_action(tc) for tc in (tool_calls or [])[:2]]
    result_lines = []
    for result in tool_results or []:
        text = _human_tool_result(result)
        if not text:
            continue
        for line in text.splitlines():
            clean = _strip_list_prefix(line)
            if clean:
                result_lines.append(clean)
            if len(result_lines) >= 2:
                break
        if len(result_lines) >= 2:
            break
    visible_content = _clip_line(content, limit=220)
    has_visible = visible_content and visible_content != "..."
    finished = "；".join(actions) if actions else summary or "整理当前信息"
    result = "；".join(result_lines)
    if not result:
        result = visible_content if has_visible else "本轮暂无可见产物，已更新阶段判断。"
    if actions:
        next_step = "基于这些结果继续推进下一轮。"
    elif has_visible:
        next_step = "等待用户反馈或按当前输出继续展开。"
    else:
        next_step = "继续补齐证据后再给结论。"

    lines = [
        f"- 本轮完成：{finished}",
        f"- 当前结果：{result}",
        f"- 下一步：{next_step}",
    ]
    return "### 小结\n" + "\n".join(lines)


def humanize_step_summary(summary, tool_calls=None):
    summary = re.sub(r"\s+", " ", str(summary or "")).strip()
    match = re.match(r"调用工具\s*([A-Za-z_][\w.-]*)\s*,?\s*args:\s*(.+)$", summary)
    if match:
        name = match.group(1)
        args_text = match.group(2)
        if tool_calls:
            return _human_tool_action(tool_calls[0])
        if name in {"file_read", "read_file"}:
            path_match = re.search(r"'path': '([^']+)'|\"path\": \"([^\"]+)\"", args_text)
            return f"读取 `{_path_tail((path_match.group(1) or path_match.group(2)) if path_match else '') or '文件'}`"
        if name in {"file_patch", "apply_patch", "edit_file"}:
            path_match = re.search(r"'path': '([^']+)'|\"path\": \"([^\"]+)\"", args_text)
            return f"更新 `{_path_tail((path_match.group(1) or path_match.group(2)) if path_match else '') or '文件'}`"
        if name == "delegate_task":
            return "并行调研多个子任务"
        return f"调用 `{name}`"
    return _clip_line(summary, limit=120)


def build_step_detail(resp, tool_calls, display_text, *, tool_results=None, include_raw_thinking=False, detail_limit=6000):
    parts = []
    thinking = (getattr(resp, "thinking", "") or "").strip() if resp else ""
    content = display_text((getattr(resp, "content", "") or "")).strip() if resp else ""
    turn_title = humanize_step_summary("", tool_calls) if tool_calls else ""
    turn_summary = build_visible_self_talk(
        turn_title,
        tool_calls,
        tool_results=tool_results,
        content=content,
    )
    if include_raw_thinking and thinking:
        parts.append(f"### 原始思考\n{thinking}")
    if turn_title:
        parts.append(f"### 本轮完成\n{turn_title}")
    if tool_calls:
        raw_trace = os.environ.get("GA_FEISHU_RAW_TOOL_TRACE", "").lower() in {"1", "true", "yes"}
        if raw_trace:
            parts.append("### 执行动作\n" + "\n".join(fmt_tool_call(tc) for tc in tool_calls))
        else:
            lines = []
            for tc in tool_calls:
                name = str(tc.get("tool_name") or "?")
                lines.append(f"- `{name}`: {_human_tool_action(tc)}")
            parts.append("### 执行动作\n" + "\n".join(lines))
    result_lines = []
    for result in tool_results or []:
        line = _human_tool_result(result)
        if line:
            result_lines.append(line)
        if len(result_lines) >= 3:
            break
    if result_lines:
        parts.append("### 产物/证据\n" + "\n".join(result_lines))
    if content and content != "...":
        parts.append(f"### 可见输出\n{content}")
    parts.append(turn_summary)
    detail = "\n\n".join(parts).strip() or "_(无可见输出)_"
    if len(detail) > detail_limit:
        detail = detail[:detail_limit] + f"\n\n...(已截断, 共 {len(detail)} 字符)"
    return detail


class FeishuTaskStream:
    def __init__(
        self,
        receive_id,
        rid_type,
        *,
        send_raw,
        patch_card,
        display_text,
        detail_limit=6000,
        final_chunk_limit=7000,
        status_tail=5,
        quiet=False,
        group_compact=False,
        group_progress_after_sec=12,
        send_initial_status=True,
        reply_to=None,
        send_reply=None,
        workspace_card=WORKSPACE_CARD_ENABLED,
        workspace_max_steps=WORKSPACE_MAX_STEPS,
        workspace_final_chars=WORKSPACE_FINAL_CHARS,
        workspace_progress_after_turns=WORKSPACE_PROGRESS_AFTER_TURNS,
        workspace_progress_after_sec=None,
    ):
        self.rid = receive_id
        self.rtype = rid_type
        self._send_raw = send_raw
        self._patch_card = patch_card
        self._display_text = display_text
        self.detail_limit = detail_limit
        self.final_chunk_limit = final_chunk_limit
        self.status_tail = status_tail
        self.status = "🤔 思考中..."
        self.msg_id = None
        self.started_at = time.time()
        self.turn_count = 0
        self.step_summaries = []
        self.final_message_ids = []
        self.quiet = quiet
        self.group_compact = group_compact
        self.group_progress_after_sec = group_progress_after_sec
        self.send_initial_status = send_initial_status
        self.reply_to = reply_to
        self._send_reply = send_reply
        self.workspace_card = bool(workspace_card and not quiet)
        self.workspace_max_steps = workspace_max_steps
        self.workspace_final_chars = workspace_final_chars
        self.workspace_progress_after_turns = max(1, int(workspace_progress_after_turns or 1))
        if workspace_progress_after_sec is None:
            workspace_progress_after_sec = group_progress_after_sec if group_compact else WORKSPACE_PROGRESS_AFTER_SEC
        self.workspace_progress_after_sec = max(0.0, float(workspace_progress_after_sec or 0.0))
        self.steps = []
        self._lock = threading.RLock()
        self._terminal = False

    def _send_message(self, payload, msg_type="interactive"):
        if self.reply_to and self._send_reply:
            return self._send_reply(self.reply_to, payload, msg_type)
        return self._send_raw(self.rid, payload, msg_type, self.rtype)

    def _send_text_fallback(self, text):
        msg_id = self._send_message(
            json.dumps({"text": str(text or "_(无文本输出)_")}, ensure_ascii=False),
            "text",
        )
        if msg_id:
            self.final_message_ids.append(msg_id)
        return msg_id

    def _send_plain_chunks(self, text, *, limit=3500):
        sent = 0
        for chunk in split_message(str(text or "_(无文本输出)_"), min(self.final_chunk_limit, limit)):
            msg_id = self._send_message(
                json.dumps({"text": chunk}, ensure_ascii=False),
                "text",
            )
            if msg_id:
                self.final_message_ids.append(msg_id)
                sent += 1
        return sent

    def _send_post_chunks(self, text, *, title="结论"):
        sent = 0
        chunks = split_message(str(text or "_(无文本输出)_"), self.final_chunk_limit)
        total = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            chunk_title = title if total == 1 else f"{title} ({idx}/{total})"
            msg_id = self._send_message(build_post_payload(chunk, title=chunk_title), "post")
            if msg_id:
                self.final_message_ids.append(msg_id)
                sent += 1
        return sent

    def _final_should_post(self, text):
        return should_send_operational_card(text) or should_send_post(text)

    def _final_post_title(self, text, *, fallback="结论"):
        if should_send_operational_card(text):
            return derive_operational_card_title(text)
        return derive_post_title(text, fallback=fallback)

    def _status_card(self):
        elapsed = int(time.time() - self.started_at)
        return build_status_card(
            self.status,
            elapsed=elapsed,
            turn_count=self.turn_count,
            step_summaries=self.step_summaries[-self.status_tail:],
        )

    def _push_status(self):
        payload = self._status_card()
        if self.msg_id:
            ok = self._patch_card(self.msg_id, payload)
            if ok:
                return
        self.msg_id = self._send_raw(self.rid, payload, "interactive", self.rtype)

    def _workspace_card(self, final_text=""):
        elapsed = int(time.time() - self.started_at)
        return build_task_workspace_card(
            status=self.status,
            steps=self.steps,
            final_text=final_text,
            elapsed=elapsed,
            turn_count=self.turn_count,
            max_steps=self.workspace_max_steps,
        )

    def _push_workspace(self, final_text=""):
        payload = self._workspace_card(final_text=final_text)
        if self.msg_id:
            ok = self._patch_card(self.msg_id, payload)
            if ok:
                return self.msg_id
        self.msg_id = self._send_message(payload, "interactive")
        return self.msg_id

    def _should_show_workspace(self):
        if self.msg_id:
            return True
        if self.turn_count >= self.workspace_progress_after_turns:
            return True
        return (time.time() - self.started_at) >= self.workspace_progress_after_sec

    def start(self):
        with self._lock:
            if self._terminal or self.quiet or self.group_compact or not self.send_initial_status:
                return
            if self.workspace_card:
                self._push_workspace()
            else:
                self._push_status()

    def pulse(self, status):
        with self._lock:
            if self._terminal or self.quiet:
                return
            self.status = status
            if self.workspace_card:
                self._push_workspace()
            elif not self.group_compact:
                self._push_status()

    def step(self, summary, detail=""):
        with self._lock:
            if self._terminal:
                return
            self.turn_count += 1
            summary = re.sub(r"\s+", " ", str(summary or f"第 {self.turn_count} 轮")).strip()
            if len(summary) > 120:
                summary = summary[:117] + "..."
            self.step_summaries.append((self.turn_count, summary))
            self.status = f"⏳ 工作中 · 第 {self.turn_count} 轮"
            self.steps.append((self.turn_count, summary, str(detail or "_(无输出)_")))

            if self.quiet:
                return
            if self.workspace_card:
                if self._should_show_workspace():
                    self._push_workspace()
                return
            if self.group_compact:
                elapsed = time.time() - self.started_at
                if elapsed < self.group_progress_after_sec and self.turn_count <= 1:
                    return
                detail = str(detail or "")
                tool_lines = []
                for line in detail.splitlines():
                    if line.strip().startswith("- `"):
                        tool_lines.append(line.strip())
                    if len(tool_lines) >= 3:
                        break
                lines = [f"**进展 · 第 {self.turn_count} 轮**", summary]
                if tool_lines:
                    lines.append("")
                    lines.extend(tool_lines)
                content = "\n".join(lines)
                for chunk in split_message(content, min(self.final_chunk_limit, 3500)):
                    self._send_message(
                        build_progress_card(self.turn_count, summary, chunk, compact=True),
                        "interactive",
                    )
                return

            detail = str(detail or "_(无输出)_")
            if len(detail) > self.detail_limit:
                detail = detail[:self.detail_limit] + f"\n\n...(已截断, 共 {len(detail)} 字符)"
            content = f"**摘要**: {summary}\n\n{detail}"
            for chunk in split_message(content, self.final_chunk_limit):
                self._send_message(
                    build_progress_card(self.turn_count, summary, chunk),
                    "interactive",
                )
            self._push_status()

    def done(self, text):
        with self._lock:
            self._terminal = True
            visible = self._display_text(text)
            if visible == "...":
                visible = "_(无文本输出)_"
            print(
                f"[feishu-task-stream] final: chars={len(visible)} turns={self.turn_count} "
                f"group_compact={self.group_compact} workspace={self.workspace_card}",
                flush=True,
            )
            if should_send_plain_final(visible, turn_count=self.turn_count, group_compact=self.group_compact):
                msg_id = self._send_message(
                    json.dumps({"text": natural_group_final(visible)}, ensure_ascii=False),
                    "text",
                )
                if msg_id:
                    self.final_message_ids.append(msg_id)
                else:
                    self._send_text_fallback(natural_group_final(visible))
                self.status = "✅ 已完成"
                return
            if self.workspace_card and self.msg_id:
                visible = natural_group_final(visible) if self.group_compact else visible
                if len(visible) <= self.workspace_final_chars:
                    self.status = "✅ 已完成"
                    final_should_post = self._final_should_post(visible)
                    final_text = "结论已通过富文本消息发送。" if final_should_post else visible
                    if not self._push_workspace(final_text=final_text) and not self.group_compact:
                        self._send_text_fallback(visible)
                    if final_should_post:
                        if not self._send_post_chunks(visible, title=self._final_post_title(visible)):
                            self._send_text_fallback(visible)
                    elif self.group_compact:
                        self._send_plain_chunks(visible)
                    if self.group_compact:
                        self.status = "✅ 已完成"
                    return
                self.status = "✅ 已完成 · 结论另发"
                if not self._push_workspace(final_text="结论内容较长，已拆成后续消息发送。"):
                    print("[feishu-task-stream] workspace card send failed before final chunks", flush=True)
                if self.group_compact:
                    if not self._send_post_chunks(visible, title=self._final_post_title(visible)):
                        self._send_text_fallback(visible)
                    return
                if not self._send_post_chunks(visible, title=self._final_post_title(visible)):
                    self._send_text_fallback(visible)
                return
            if self.group_compact:
                visible = natural_group_final(visible)
                operational_card = should_send_operational_card(visible)
                use_post = operational_card or should_send_post(visible)
                chunks = split_message(visible, self.final_chunk_limit if use_post else min(self.final_chunk_limit, 3500))
                card_title = (
                    derive_operational_card_title(visible)
                    if operational_card
                    else derive_post_title(visible, fallback="已完成")
                )
                total = len(chunks)
                for idx, chunk in enumerate(chunks, 1):
                    if use_post:
                        title = card_title if total == 1 else f"{card_title} ({idx}/{total})"
                        msg_id = self._send_message(
                            build_post_payload(chunk, title=title),
                            "post",
                        )
                        if msg_id:
                            self.final_message_ids.append(msg_id)
                        continue
                    msg_id = self._send_message(
                        json.dumps({"text": chunk}, ensure_ascii=False),
                        "text",
                    )
                    if msg_id:
                        self.final_message_ids.append(msg_id)
                if not self.final_message_ids:
                    self._send_text_fallback(visible)
                self.status = "✅ 已完成"
                return
            title = "结论" if self.quiet else self._final_post_title(visible, fallback="已完成")
            self._send_post_chunks(visible, title=title)
            if not self.final_message_ids:
                self._send_text_fallback(visible)
            self.status = "✅ 已完成 · 结论已发送"
            if not self.quiet:
                self._push_status()

    def fail(self, msg):
        with self._lock:
            self._terminal = True
            if self.workspace_card and self.msg_id:
                self.status = f"❌ {msg}"
                self._push_workspace()
                return
            if self.quiet or self.group_compact:
                self._send_message(
                    json.dumps({"text": f"出错了：{msg}"}, ensure_ascii=False),
                    "text",
                )
                return
            self.status = f"❌ {msg}"
            self._push_status()

    def cancel(self, msg="已停止当前任务"):
        with self._lock:
            self._terminal = True
            if self.workspace_card and self.msg_id:
                self.status = f"⏹️ {msg}"
                self._push_workspace()
                return
            if self.quiet or self.group_compact:
                self._send_message(
                    json.dumps({"text": str(msg or "已停止当前任务")}, ensure_ascii=False),
                    "text",
                )
                return
            self.status = f"⏹️ {msg}"
            self._push_status()
