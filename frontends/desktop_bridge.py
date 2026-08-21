#!/usr/bin/env python3
"""
GenericAgent Web2 Bridge.

Clear split:
1) AgentManager: owns GenericAgent instances, sessions and histories.
2) Transport: HTTP is the command/data channel; WebSocket only pushes small
   session-state notifications.

HTTP API:
  GET    /status
  GET    /config
  POST   /config
  GET    /model-profiles  (+ POST / PUT / DELETE by id)
  GET    /sessions
  POST   /session/new
  GET    /session/{sid}
  DELETE /session/{sid}
  POST   /session/{sid}/prompt
  GET    /session/{sid}/messages?after=0&limit=200
  POST   /session/{sid}/cancel
  POST   /services/start        body: {"id":"frontends/qqapp.py"}
  POST   /services/stop         body: {"id":"frontends/qqapp.py"}
  GET    /services/logs?id=frontends/qqapp.py&tail=200
  GET    /services/panel
  GET    /services/mykey
  POST   /services/mykey       body: {"content":"..."}
  POST   /services/stop-extras   stop conductor + scheduler (127.0.0.1 only)
  POST   /services/start-extras  start conductor + scheduler (127.0.0.1 only)
  POST   /services/bridge/exit    stop managed services, then exit bridge (127.0.0.1 only)

WS API (state sync):
  GET /ws -> on connect sends services.snapshot; service.changed on updates
  {"type":"services.snapshot","services":[...]}
  {"type":"service.changed","service":{...}}
"""
from __future__ import annotations

import asyncio, atexit, contextlib, copy, importlib, json, os, re, shutil, subprocess, sys
from collections import Counter, deque
import threading, time, traceback, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from aiohttp import web, WSMsgType

APP_DIR = Path(__file__).resolve().parent

# ─── Bridge self-log ring buffer ───
import datetime as _dt, io as _io

_bridge_log: deque = deque(maxlen=500)


def bridge_print(*args, **kwargs):
    """Print to stderr AND capture into bridge ring buffer (timestamped)."""
    kwargs.pop("file", None)
    buf = _io.StringIO()
    print(*args, file=buf, **kwargs)
    text = buf.getvalue().rstrip("\n")
    ts = _dt.datetime.now().strftime("%H:%M:%S")
    for line in text.split("\n"):
        _bridge_log.append(f"[{ts}] {line}")
    print(*args, file=sys.stderr, **kwargs)


def _ga_root_override() -> Optional[Path]:
    """Resolve an external core while keeping this bundled bridge as the executable surface."""
    value = ""
    for index, argument in enumerate(sys.argv):
        if argument == "--ga-root" and index + 1 < len(sys.argv):
            value = sys.argv[index + 1]
        elif argument.startswith("--ga-root="):
            value = argument.split("=", 1)[1]
    if not value:
        value = os.environ.get("GA_ROOT", "")
    value = (value or "").strip()
    if not value:
        return None
    root = Path(value).expanduser().resolve()
    return root if (root / "agentmain.py").exists() else None


def find_default_ga_root() -> Path:
    override = _ga_root_override()
    if override is not None:
        return override
    candidates = [
        APP_DIR / "..",
        APP_DIR / ".." / "..",
        APP_DIR / ".." / "GenericAgent",
        APP_DIR / ".." / ".." / "GenericAgent",
    ]
    for p in candidates:
        root = p.resolve()
        if (root / "agentmain.py").exists():
            return root
    return APP_DIR.parent.parent.resolve()


DEFAULT_GA_ROOT = find_default_ga_root()

_FINAL_INFO_RE = re.compile(r'\n*`{5}\n*\[Info\] Final response to user\.\n*`{5}\s*$')


def strip_final_info_marker(text: Any) -> str:
    return _FINAL_INFO_RE.sub('', str(text or ''))


def normalize_final_turn_segs(full: str, outputs: Any) -> Optional[List[str]]:
    if not outputs or not isinstance(outputs, (list, tuple)):
        return None
    segs = [strip_final_info_marker(s) for s in outputs]
    full_text = strip_final_info_marker(full)
    if not segs:
        return None
    joined = "".join(segs)
    if full_text.strip() == joined.strip():
        return segs
    if joined and full_text.startswith(joined):
        suffix = full_text[len(joined):]
        if suffix.strip():
            segs[-1] = segs[-1] + suffix
        return segs
    return None


# ─── Empty-turn microcopy (i18n) ───

_EMPTY_TURN_MICROCOPY = {
    "zh": '⚠️ 这一轮结束了，但没有产出可见回复。你可以发送"继续"重试。',
    "en": '⚠️ This turn ended without a visible response. You can send "continue" to retry.',
}


def _get_ui_lang() -> str:
    try:
        p = Path.home() / ".ga_desktop_settings.json"
        doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        lang = doc.get("lang") if isinstance(doc, dict) else None
        return lang if isinstance(lang, str) and lang in _EMPTY_TURN_MICROCOPY else "zh"
    except Exception:
        return "zh"


def empty_turn_fallback() -> str:
    lang = _get_ui_lang()
    return _EMPTY_TURN_MICROCOPY.get(lang, _EMPTY_TURN_MICROCOPY["zh"])


# ─── Test-only control plane ────────────────────────────────────────────────

_E2E_CONTROL_LOCK = threading.Lock()
_E2E_NEXT_TURN: Optional[str] = None


def _e2e_control_token() -> Optional[str]:
    if os.environ.get("GA_E2E") != "1":
        return None
    token = os.environ.get("GA_E2E_CONTROL_TOKEN", "").strip()
    return token or None


def _set_e2e_next_turn(mode: str) -> None:
    if mode != "empty":
        raise ValueError("mode must be empty")
    global _E2E_NEXT_TURN
    with _E2E_CONTROL_LOCK:
        _E2E_NEXT_TURN = mode


def _consume_e2e_next_turn() -> Optional[str]:
    global _E2E_NEXT_TURN
    with _E2E_CONTROL_LOCK:
        mode = _E2E_NEXT_TURN
        _E2E_NEXT_TURN = None
        return mode


for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Agent management layer
# ---------------------------------------------------------------------------

@dataclass
class Session:
    id: str
    title: str = "New chat"
    cwd: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: List[dict] = field(default_factory=list)
    msg_seq: int = 0
    partial: Optional[dict] = None
    status: str = "idle"  # idle|running|error|cancelled
    agent: Any = None
    thread: Optional[threading.Thread] = None
    cancel_requested: bool = False
    active_turn_id: str = ""
    last_error: str = ""
    pinned: bool = False
    untitled: bool = True
    plan_scan_baseline: int = 0
    plan_path: str = ""
    llm_history: Optional[List[dict]] = None
    # 该会话绑定的模型下标(mykey.py 配置块顺序,== agent.llmclients 下标)。
    # None = 未绑定,发消息时回退到全局默认 ui.llmNo,保持旧会话平滑迁移。
    llm_no: Optional[int] = None
    # 当前正在执行的 turn 使用的模型。仅运行期存在，不写入 session JSON。
    running_llm_no: Optional[int] = None
    running_model: Optional[str] = None


def _is_desktop_session_id(session_id: Any) -> bool:
    """Keep internal TUI/Conductor worker artifacts out of Desktop sessions."""
    return bool(session_id) and not str(session_id).startswith("tui_")


def _load_plan_baseline(item: dict, msgs: list) -> int:
    """Persisted per-session baseline (tuiapp_v2: set on /continue, not on preset text)."""
    base = int(item.get("plan_scan_baseline", 0) or 0)
    if base >= len(msgs):
        return 0
    return max(0, base)


def _sanitize_desktop_plan_path(session_id: str, plan_path: str) -> str:
    """Keep only real plan-mode paths; never invent a placeholder path on load."""
    import plan_state
    p = (plan_path or "").strip()
    if not p:
        return ""
    if plan_state.is_plan_mode_path(p):
        return p.lstrip("./\\")
    return ""


class AgentManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.ga_root = str(DEFAULT_GA_ROOT)
        self.config: Dict[str, Any] = {}
        self.sessions: Dict[str, Session] = {}
        self.active_session_id: Optional[str] = None
        self._sessions_dir = Path(self.ga_root) / "temp" / "desktop_sessions"
        # Legacy monolithic store; migrated into _sessions_dir on first load, then retired.
        self._sessions_file = Path(self.ga_root) / "temp" / "desktop_sessions.json"
        self._load_sessions()

    @property
    def mykey_path(self) -> str:
        return str(Path(self.ga_root) / "mykey.py")

    def _session_dict(self, s: "Session") -> dict:
        llm_hist = None
        if s.agent and hasattr(s.agent, 'llmclient'):
            try: llm_hist = s.agent.llmclient.backend.history
            except Exception: pass
        if llm_hist is None:
            llm_hist = s.llm_history
        return {"id": s.id, "title": s.title, "cwd": s.cwd,
                "created_at": s.created_at, "updated_at": s.updated_at,
                "messages": s.messages, "msg_seq": s.msg_seq,
                "pinned": s.pinned, "untitled": s.untitled,
                "plan_scan_baseline": s.plan_scan_baseline,
                "plan_path": s.plan_path or "",
                "llm_no": s.llm_no,
                "llm_history": llm_hist}

    def _session_file(self, sid: str) -> Path:
        return self._sessions_dir / f"{sid}.json"

    def _persist_session(self, s: "Session"):
        """Write a single session file. Cost is O(one session), independent of how many
        sessions exist — this is the fix for the monolithic-file scaling problem."""
        try:
            self._sessions_dir.mkdir(parents=True, exist_ok=True)
            with self.lock:
                data = self._session_dict(s)
                data["messages"] = copy.deepcopy(data["messages"])
                if data.get("llm_history"):
                    data["llm_history"] = copy.deepcopy(data["llm_history"])
            tmp = self._sessions_dir / f"{s.id}.json.tmp"
            tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
            os.replace(tmp, self._session_file(s.id))
        except Exception as e:
            bridge_print(f"[bridge] persist session {s.id} failed: {e}")

    def _delete_session_file(self, sid: str):
        try:
            f = self._session_file(sid)
            if f.exists():
                f.unlink()
        except Exception as e:
            bridge_print(f"[bridge] delete session file {sid} failed: {e}")

    def _persist(self):
        """Write every session (one file each). Used for bulk ops (import) / full flush."""
        with self.lock:
            sessions = list(self.sessions.values())
        for s in sessions:
            self._persist_session(s)

    def _session_from_item(self, item: dict) -> "Session":
        msgs = item.get("messages", [])
        return Session(id=item["id"], title=item.get("title", "New chat"),
                       cwd=item.get("cwd", self.ga_root),
                       created_at=item.get("created_at", time.time()),
                       updated_at=item.get("updated_at", time.time()),
                       messages=msgs,
                       msg_seq=item.get("msg_seq", 0),
                       pinned=item.get("pinned", False),
                       untitled=item.get("untitled", True),
                       plan_scan_baseline=_load_plan_baseline(item, msgs),
                       plan_path=_sanitize_desktop_plan_path(item["id"], item.get("plan_path") or ""),
                       status="idle", agent=None,
                       llm_history=item.get("llm_history"),
                       llm_no=item.get("llm_no"))

    def _load_sessions(self):
        # New format: one file per session under temp/desktop_sessions/.
        try:
            if self._sessions_dir.is_dir():
                for f in self._sessions_dir.glob("*.json"):
                    try:
                        item = json.loads(f.read_text(encoding="utf-8"))
                        if not _is_desktop_session_id(item.get("id")):
                            continue
                        sess = self._session_from_item(item)
                        self.sessions[sess.id] = sess
                    except Exception as e:
                        bridge_print(f"[bridge] load session {f.name} failed: {e}")
        except Exception as e:
            bridge_print(f"[bridge] load sessions dir failed: {e}")

        # One-time migration from the legacy monolithic desktop_sessions.json.
        try:
            if self._sessions_file.exists():
                arr = json.loads(self._sessions_file.read_text(encoding="utf-8"))
                for item in arr:
                    if (not isinstance(item, dict)
                            or not _is_desktop_session_id(item.get("id"))
                            or item.get("id") in self.sessions):
                        continue
                    try:
                        sess = self._session_from_item(item)
                        self.sessions[sess.id] = sess
                        self._persist_session(sess)
                    except Exception as e:
                        bridge_print(f"[bridge] migrate session failed: {e}")
                # Retire the legacy file so we do not migrate again next launch.
                with contextlib.suppress(Exception):
                    self._sessions_file.rename(
                        self._sessions_file.parent / (self._sessions_file.name + ".migrated"))
        except Exception as e:
            bridge_print(f"[bridge] migrate sessions failed: {e}")

        if self.sessions:
            self.active_session_id = max(self.sessions.values(), key=lambda s: s.updated_at).id

    def import_sessions(self, source_dir: str) -> dict:
        """把 source 的桌面会话合并进当前列表(按 id 去重)。

        兼容两种源格式:新版 temp/desktop_sessions/<id>.json,以及旧版单文件
        temp/desktop_sessions.json(含已退休的 .migrated)。只落盘新增的会话。
        """
        src = Path(source_dir).expanduser().resolve()
        items: List[dict] = []
        found = False

        # New per-session format.
        src_dir = src / "temp" / "desktop_sessions"
        if src_dir.is_dir():
            for f in src_dir.glob("*.json"):
                try:
                    items.append(json.loads(f.read_text(encoding="utf-8")))
                    found = True
                except Exception:
                    continue

        # Legacy monolithic format (live or already retired).
        for legacy in (src / "temp" / "desktop_sessions.json",
                       src / "temp" / "desktop_sessions.json.migrated"):
            if legacy.is_file():
                found = True
                try:
                    arr = json.loads(legacy.read_text(encoding="utf-8"))
                    if isinstance(arr, list):
                        items.extend(x for x in arr if isinstance(x, dict))
                except Exception:
                    continue

        if not found:
            return {"sessionsAdded": 0, "sessionsSkipped": 0, "sessionsFileFound": False}

        added = 0
        skipped = 0
        new_sessions: List["Session"] = []
        with self.lock:
            for item in items:
                sid = item.get("id")
                if not _is_desktop_session_id(sid) or sid in self.sessions:
                    skipped += 1
                    continue
                sess = self._session_from_item(item)
                self.sessions[sid] = sess
                new_sessions.append(sess)
                added += 1
        for sess in new_sessions:
            self._persist_session(sess)
        return {"sessionsAdded": added, "sessionsSkipped": skipped, "sessionsFileFound": True}

    def _mykey_file(self) -> Path:
        p = Path(self.ga_root) / "mykey.py"
        if not p.exists():
            tpl = Path(self.ga_root) / "mykey_template.py"
            p.write_text(tpl.read_text(encoding="utf-8") if tpl.exists() else "", encoding="utf-8")
        return p

    @staticmethod
    def _next_native_var(text: str, protocol: str) -> str:
        # 协议必选(由前端下拉强制),不再用 apibase 兜底瞎猜
        proto = str(protocol or "").strip().lower()
        if proto == "claude":
            prefix = "native_claude_config"
        elif proto in ("oai", "openai"):
            prefix = "native_oai_config"
        else:
            raise ValueError("protocol is required: choose 'oai' or 'claude'")
        nums = [0]
        if re.search(rf"^{prefix}\s*=", text, re.M):
            nums.append(0)
        nums.extend(int(m.group(1)) for m in re.finditer(rf"^{prefix}(\d+)\s*=", text, re.M))
        n = max(nums) + 1
        return prefix if n == 1 and not re.search(rf"^{prefix}\s*=", text, re.M) else f"{prefix}{n}"

    @staticmethod
    def _format_py_dict(d: dict) -> str:
        lines = [f"    '{k}': {json.dumps(v, ensure_ascii=False)}," if isinstance(v, str) else f"    '{k}': {v}," for k, v in d.items()]
        return "{\n" + "\n".join(lines) + "\n}"

    def _invalidate_mykey_cache(self) -> None:
        self.ensure_ga_import_path()
        sys.modules.pop("mykey", None)
        with contextlib.suppress(Exception):
            import llmcore
            llmcore._mykey_mtime = None

    def _profile_keys(self) -> List[str]:
        self.ensure_ga_import_path()
        from llmcore import reload_mykeys
        return [k for k in reload_mykeys()[0] if any(x in k for x in ("api", "config", "cookie"))]

    def _profile_at(self, profile_id: int) -> tuple[str, dict]:
        keys = self._profile_keys()
        if profile_id < 0 or profile_id >= len(keys):
            raise ValueError("profile not found")
        var = keys[profile_id]
        if "mixin" in var:
            raise ValueError("mixin profiles not supported here")
        from llmcore import reload_mykeys
        cfg = reload_mykeys()[0].get(var)
        if not isinstance(cfg, dict):
            raise ValueError("profile not editable")
        return var, dict(cfg)

    @staticmethod
    def _find_var_block_span(text: str, var_name: str) -> Optional[tuple[int, int]]:
        m = re.search(rf"^{re.escape(var_name)}\s*=\s*\{{", text, re.M)
        if not m:
            return None
        start, i, depth = m.start(), m.end() - 1, 0
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(text) and text[end] in "\r\n":
                        end += 1
                    return start, end
            i += 1
        return None

    def _patch_var_block(self, text: str, var: str, cfg: Optional[dict] = None) -> str:
        if not (span := self._find_var_block_span(text, var)):
            raise ValueError(f"config block not found: {var}")
        s, e = span
        if cfg is None:
            return text[:s].rstrip() + "\n" + text[e:].lstrip("\n")
        return text[:s] + f"{var} = {self._format_py_dict(cfg)}\n" + text[e:]

    def _build_cfg(self, data: dict, existing: Optional[dict] = None, *, require_key: bool = True) -> dict:
        apibase, model = str(data.get("apibase") or "").strip(), str(data.get("model") or "").strip()
        if not apibase or not model:
            raise ValueError("apibase and model are required")
        apikey = str(data.get("apikey") or "").strip() or str((existing or {}).get("apikey") or "").strip()
        if require_key and not apikey:
            raise ValueError("apikey is required")
        # 从 existing 起步：保留表单未覆盖的高级字段（proxy / temperature / api_mode /
        # reasoning_effort / fake_cc_system_prompt / thinking_type …），避免 GUI 编辑时丢失
        cfg: Dict[str, Any] = dict(existing or {})
        cfg.update({"apikey": apikey, "apibase": apibase, "model": model})
        if "name" in data:
            name = str(data.get("name") or "").strip()
            if name:
                cfg["name"] = name
            else:
                cfg.pop("name", None)
        for k in ("max_retries", "connect_timeout", "read_timeout"):
            if data.get(k) is not None and str(data.get(k)).strip() != "":
                cfg[k] = int(data[k])
        # 流式开关：默认 True 不写（保持 mykey 干净），仅显式非流式才落 'stream': False
        if "stream" in data:
            s = data["stream"]
            stream = s if isinstance(s, bool) else str(s).strip().lower() not in ("false", "0", "no", "off")
            if stream:
                cfg.pop("stream", None)
            else:
                cfg["stream"] = False
        return cfg

    def _save_mykey_text(self, text: str) -> list:
        self._mykey_file().write_text(text, encoding="utf-8")
        self._invalidate_mykey_cache()
        self._reload_live_agents()
        return self.list_model_profiles()

    def _reload_live_agents(self) -> None:
        """mykey.py 改动后，强制所有活着的会话 agent 重建 LLM session，让新 key/模型
        立即生效（无需重启）。重建保留对话 history（agentmain 内部用 oldhistory 接回）。

        纯 bridge 侧实现，不改 agentmain：每次调 agent.load_llm_sessions() 前，把
        llmcore 的全局 mtime 标志清空（与 _invalidate_mykey_cache 同一手法），使其内部
        reload_mykeys() 报告 changed=True、从而真正重建——否则刷新模型列表等路径会先
        消费掉变更标志，常驻 agent 的 load_llm_sessions 会因 changed=False 跳过重建。"""
        self.ensure_ga_import_path()
        try:
            import llmcore
        except Exception:
            return
        with self.lock:
            agents = [s.agent for s in self.sessions.values() if getattr(s, "agent", None) is not None]
        for agent in agents:
            fn = getattr(agent, "load_llm_sessions", None)
            if not callable(fn):
                continue
            try:
                llmcore._mykey_mtime = None   # 让本次 reload_mykeys() 视为“已变更”，触发真正重建
                fn()
            except Exception as e:
                bridge_print(f"[bridge] reload live agent failed: {e}")

    def add_model_profile(self, data: dict) -> dict:
        cfg = self._build_cfg(data)
        text = self._mykey_file().read_text(encoding="utf-8")
        var = self._next_native_var(text, data.get("protocol", ""))
        profiles = self._save_mykey_text(text.rstrip() + f"\n{var} = {self._format_py_dict(cfg)}\n")
        return {"varName": var, "profileId": profiles[-1]["id"] if profiles else 0, "profiles": profiles}

    def get_model_profile(self, profile_id: int) -> dict:
        var, cfg = self._profile_at(profile_id)
        ks = ("model", "apibase", "apikey", "name", "max_retries", "connect_timeout", "read_timeout")
        out = {"id": profile_id, "varName": var, **{k: cfg.get(k, d) for k, d in zip(ks, ("", "", "", "", 5, 15, 300))}}
        out["stream"] = cfg.get("stream", True)
        return out

    def update_model_profile(self, profile_id: int, data: dict) -> dict:
        var, existing = self._profile_at(profile_id)
        text = self._mykey_file().read_text(encoding="utf-8")
        profiles = self._save_mykey_text(self._patch_var_block(text, var, self._build_cfg(data, existing, require_key=False)))
        return {"varName": var, "profileId": profile_id, "profiles": profiles}

    def delete_model_profile(self, profile_id: int) -> dict:
        if len(self._profile_keys()) <= 1:
            raise ValueError("cannot delete the last profile")
        var, cfg = self._profile_at(profile_id)
        text = self._patch_var_block(self._mykey_file().read_text(encoding="utf-8"), var).rstrip() + "\n"
        # 顺手把它从聚合渠道里摘掉，避免 llm_nos 残留指向已删除的模型（会让 Mixin 构建失败）
        name = str(cfg.get("name") or cfg.get("model") or "").strip()
        keys, mk = self._mykey_vars()
        mvar, mcfg = self._mixin_entry(keys, mk)
        if mcfg and mvar is not None and name in [str(m) for m in (mcfg.get("llm_nos") or [])]:
            mcfg = {**mcfg, "llm_nos": [str(m) for m in (mcfg.get("llm_nos") or []) if str(m) != name]}
            if self._find_var_block_span(text, mvar):
                text = self._patch_var_block(text, mvar, mcfg)
        profiles = self._save_mykey_text(text)
        return {"profileId": profile_id, "profiles": profiles}

    def ensure_ga_import_path(self) -> Path:
        root = Path(self.ga_root).resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return root

    def make_agent(self, sess: Session):
        root = self.ensure_ga_import_path()
        try: import cost_tracker; cost_tracker.install()
        except Exception: pass
        old_cwd = os.getcwd()
        try:
            os.chdir(sess.cwd or str(root))
            agentmain = importlib.import_module("agentmain")
            GA = getattr(agentmain, "GenericAgent")
            agent = GA()
            agent.inc_out = True
            agent.verbose = True
            threading.Thread(target=agent.run, daemon=True, name=f"GA-{sess.id}").start()
            return agent
        finally:
            with contextlib.suppress(Exception):
                os.chdir(old_cwd)

    @staticmethod
    def _base_display_name(var: str, cfg: Optional[dict]) -> str:
        c = cfg or {}
        return str(c.get("name") or c.get("model") or var)

    def _mykey_vars(self):
        """(keys, mk)：mykey 里的模型变量名（按定义顺序，与 agentmain.llmclients 索引
        一一对齐）和原始 dict。过滤规则与 _profile_keys / load_llm_sessions 完全一致，
        因此 id == llmclients 下标，前端选中 llmNo 能正确激活对应 client。"""
        self._mykey_file()   # 确保 mykey.py 存在（首次从模板生成空配置），否则全新安装时
                             # reload_mykeys 找不到 mykey 会返回空，空聚合渠道就不显示了
        self.ensure_ga_import_path()
        from llmcore import reload_mykeys
        mk = reload_mykeys()[0]
        keys = [k for k in mk if any(x in k for x in ("api", "config", "cookie"))]
        return keys, mk

    def _mixin_entry(self, keys, mk):
        """返回 (mixin_var, mixin_cfg_dict) 或 (None, None)。单一主聚合渠道，只取第一个。"""
        for k in keys:
            if "mixin" in k and isinstance(mk.get(k), dict):
                return k, dict(mk[k])
        return None, None

    def list_model_profiles(self):
        """直接读 mykey.py 结构（不依赖能否成功构建出 client），这样空聚合渠道、
        未填 key 的模型也能如实展示。聚合渠道(kind=mixin)带 members；基本模型
        (kind=native)带 inMixin/group。"""
        try:
            keys, mk = self._mykey_vars()
        except Exception as e:
            bridge_print(f"get model profiles failed: {e}")
            return []
        # A profile can be referenced by any mixin channel, not only the first one.
        # Keep each mixin row's own members for display, but mark native profiles as
        # inMixin when they appear in any mixin.
        all_mixin_members: set[str] = set()
        for k in keys:
            cfg = mk.get(k) if isinstance(mk.get(k), dict) else {}
            if "mixin" in k:
                all_mixin_members.update(str(m) for m in (cfg.get("llm_nos") or []))
        active = self.config.get("llmNo", 0)
        out = []
        for i, k in enumerate(keys):
            cfg = mk.get(k) if isinstance(mk.get(k), dict) else {}
            if "mixin" in k:
                members = [str(m) for m in (cfg.get("llm_nos") or [])]
                out.append({"id": i, "varName": k, "kind": "mixin", "name": "",
                            "members": members, "active": i == active})
            else:
                name = self._base_display_name(k, cfg)
                out.append({"id": i, "varName": k, "kind": "native", "name": name,
                            "model": cfg.get("model", ""),
                            "group": "native" if "native" in k else "std",
                            "inMixin": name in all_mixin_members, "active": i == active})
        return out

    def add_to_mixin(self, profile_id: int) -> dict:
        """把一个基本模型加入主聚合渠道：把它的 name 追加进 mixin_config['llm_nos']。
        坑1：校验 Native 一致性（聚合内必须全 Native 或全非 Native）。
        坑2：加入前若该模型没有显式 name，先把 name 写进它的配置块（保证引用稳定）。"""
        var, cfg = self._profile_at(profile_id)   # 对 mixin 会抛错（只接受 native）
        name = str(cfg.get("name") or cfg.get("model") or "").strip()
        if not name:
            raise ValueError("this model needs a name or model before joining the channel")
        keys, mk = self._mykey_vars()
        mvar, mcfg = self._mixin_entry(keys, mk)
        new_is_native = "native" in var
        name2var = {self._base_display_name(k, mk.get(k) if isinstance(mk.get(k), dict) else {}): k
                    for k in keys if "mixin" not in k}
        existing = [str(m) for m in (mcfg.get("llm_nos") or [])] if mcfg else []
        for m in existing:
            mv = name2var.get(m)
            if mv is not None and ("native" in mv) != new_is_native:
                raise ValueError("aggregation channel requires all-Native or all-non-Native models")
        text = self._mykey_file().read_text(encoding="utf-8")
        if not cfg.get("name"):
            text = self._patch_var_block(text, var, {**cfg, "name": name})
        if mcfg is None:
            mcfg, mvar, existing = {"llm_nos": [], "max_retries": 10, "base_delay": 0.5}, "mixin_config", []
        if name not in existing:
            existing.append(name)
        mcfg = {**mcfg, "llm_nos": existing}
        if self._find_var_block_span(text, mvar):
            text = self._patch_var_block(text, mvar, mcfg)
        else:
            text = text.rstrip() + f"\n{mvar} = {self._format_py_dict(mcfg)}\n"
        return {"profiles": self._save_mykey_text(text)}

    def remove_from_mixin(self, profile_id: int) -> dict:
        """把一个基本模型移出主聚合渠道。"""
        var, cfg = self._profile_at(profile_id)
        name = str(cfg.get("name") or cfg.get("model") or "").strip()
        keys, mk = self._mykey_vars()
        mvar, mcfg = self._mixin_entry(keys, mk)
        if not mcfg or mvar is None:
            return {"profiles": self.list_model_profiles()}
        members = [str(m) for m in (mcfg.get("llm_nos") or []) if str(m) != name]
        mcfg = {**mcfg, "llm_nos": members}
        text = self._patch_var_block(self._mykey_file().read_text(encoding="utf-8"), mvar, mcfg)
        return {"profiles": self._save_mykey_text(text)}

    def reorder_mixin(self, members: list) -> dict:
        """按前端拖拽后的顺序重写主渠道组 llm_nos。只接受当前成员的重排，不增删。"""
        keys, mk = self._mykey_vars()
        mvar, mcfg = self._mixin_entry(keys, mk)
        if not mcfg or mvar is None:
            raise ValueError("mixin channel not found")
        old = [str(m) for m in (mcfg.get("llm_nos") or [])]
        new = [str(m) for m in (members or [])]
        if len(new) != len(old) or Counter(new) != Counter(old):
            raise ValueError("reorder must contain the same channel members")
        if new == old:
            return {"profiles": self.list_model_profiles()}
        mcfg = {**mcfg, "llm_nos": new}
        text = self._patch_var_block(self._mykey_file().read_text(encoding="utf-8"), mvar, mcfg)
        return {"profiles": self._save_mykey_text(text)}

    @staticmethod
    def _live_model(sess: Session) -> Optional[dict]:
        """该会话 agent 当前真正在用的模型(渠道组会随故障转移变化)。
        agent 还没建(没跑过 turn)时返回静态绑定信息,前端据 llmNo 回显选择器。
        llmNo: 始终以 sess.llm_no 为权威(用户选择),agent.llm_no 在初始化窗口可能滞后。"""
        ag = getattr(sess, "agent", None)
        if ag is None:
            return {"current": None, "isMixin": False, "llmNo": sess.llm_no,
                    "runningLlmNo": sess.running_llm_no, "runningModel": sess.running_model}
        try:
            back = ag.llmclient.backend
            live_no = sess.llm_no if sess.llm_no is not None else getattr(ag, "llm_no", 0)
            if "Mixin" in type(back).__name__:
                return {"current": back.current_name, "isMixin": True, "llmNo": live_no,
                        "runningLlmNo": sess.running_llm_no, "runningModel": sess.running_model}
            return {"current": back.name, "isMixin": False, "llmNo": live_no,
                    "runningLlmNo": sess.running_llm_no, "runningModel": sess.running_model}
        except Exception:
            return {"current": None, "isMixin": False, "llmNo": sess.llm_no,
                    "runningLlmNo": sess.running_llm_no, "runningModel": sess.running_model}

    def snapshot(self, sess: Session, include_messages: bool = True) -> dict:
        out = {
            "sessionId": sess.id,
            "id": sess.id,
            "title": sess.title,
            "cwd": sess.cwd,
            "status": sess.status,
            "createdAt": sess.created_at,
            "updatedAt": sess.updated_at,
            "lastError": sess.last_error,
            "msgSeq": sess.msg_seq,
            "pinned": sess.pinned,
            "untitled": sess.untitled,
            "model": self._live_model(sess),
        }
        if include_messages:
            out["messages"] = list(sess.messages)
            out["partial"] = dict(sess.partial) if sess.partial else None
        return out

    def add_message(self, sess: Session, role: str, content: str, **extra) -> dict:
        sess.msg_seq += 1
        msg = {"id": sess.msg_seq, "role": role, "content": content, "ts": time.time()}
        msg.update(extra)
        sess.messages.append(msg)
        sess.updated_at = time.time()
        if role == "user" and content.strip() and sess.title == "New chat":
            sess.title = content.strip().replace("\n", " ")[:40]
        self._persist_session(sess)
        return msg

    def create_session(self, cwd: Optional[str] = None) -> Session:
        sid = "sess-" + uuid.uuid4().hex[:12]
        sess = Session(id=sid, cwd=str(cwd or self.ga_root), llm_no=_global_default_llm_no())
        with self.lock:
            self.sessions[sid] = sess
            self.active_session_id = sid
        emit_session_state(sess, "created")
        self._persist_session(sess)
        return sess

    def get_session(self, sid: str) -> Session:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            return sess

    def delete_session(self, sid: str) -> dict:
        with self.lock:
            sess = self.sessions.pop(sid, None)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            if self.active_session_id == sid:
                self.active_session_id = next(iter(self.sessions), None)
            if sess.agent and hasattr(sess.agent, "abort"):
                with contextlib.suppress(Exception):
                    sess.agent.abort()
        emit_session_state(sess, "closed")
        self._delete_session_file(sid)
        _purge_session_uploads(sid)
        return {"ok": True, "sessionId": sid}

    def submit_prompt(self, sid: str, prompt: Any, images: Optional[list] = None, display: Optional[str] = None, files_meta: Optional[list] = None, image_metas: Optional[list] = None) -> dict:
        prompt, image_ids = normalize_prompt(prompt, images)
        # Build agent_prompt with file paths prepended (agent sees paths, UI sees clean text)
        agent_prompt = prompt
        if files_meta:
            paths = [m["path"] for m in files_meta if m.get("path")]
            if paths:
                agent_prompt = " ".join(paths) + "\n" + prompt
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            if sess.status == "running":
                raise web.HTTPConflict(text=json.dumps({"error": "session is already running"}, ensure_ascii=False), content_type="application/json")
            extra = {}
            if image_ids:
                extra["image_ids"] = image_ids
            if isinstance(display, str) and display.strip() and display != prompt:
                extra["display"] = display
            if files_meta:
                extra["files"] = files_meta
            if image_metas:
                extra["images"] = image_metas
            user_msg = self.add_message(sess, "user", prompt, **extra)
            turn_id = uuid.uuid4().hex
            sess.status = "running"
            sess.cancel_requested = False
            sess.active_turn_id = turn_id
            sess.last_error = ""
            sess.partial = {"id": sess.msg_seq + 1, "role": "assistant", "content": "", "ts": time.time(), "partial": True,
                            "curr_turn": 0, "turn_segs": []}  # turn_segs[i]=第i轮全文(权威结构化,前端按轮渲染);content保留双轮兜底
            image_paths = [m["path"] for m in (image_metas or []) if m.get("path")]
            t = threading.Thread(
                target=self.run_agent_turn,
                args=(sess, agent_prompt, image_paths or None, turn_id),
                daemon=True,
                name=f"Turn-{sid}",
            )
            sess.thread = t
            t.start()
            seq = sess.msg_seq
        emit_session_state(sess, "running")
        return {"ok": True, "sessionId": sid, "accepted": True, "userMessageId": user_msg["id"], "seq": seq}

    @staticmethod
    def _patch_chat_for_images(client, image_paths):
        """Monkey-patch backend.ask to inject base64 image blocks on the first LLM call."""
        import base64 as b64, mimetypes
        try:
            from llmcore import NativeToolClient
        except ImportError:
            return
        if not isinstance(client, NativeToolClient):
            return
        backend = client.backend
        original_ask = backend.ask

        _VISION_MIMES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}

        def patched_ask(msg):
            try:
                del backend.ask
            except AttributeError:
                backend.ask = original_ask
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                for p in image_paths:
                    try:
                        mime = mimetypes.guess_type(p)[0] or 'image/png'
                        if mime not in _VISION_MIMES:
                            # Unsupported image format (e.g. SVG) — inject as text path reference
                            msg["content"].append({"type": "text", "text": f"[attached file: {p}]"})
                            continue
                        with open(p, 'rb') as f:
                            raw = f.read()
                        data = b64.b64encode(raw).decode()
                        msg["content"].append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
                    except Exception:
                        pass
            resp = yield from original_ask(msg)
            return resp

        backend.ask = patched_ask

    def run_agent_turn(
        self,
        sess: Session,
        prompt: str,
        images: Optional[list] = None,
        turn_id: str = "",
    ):
        def turn_state() -> tuple[bool, bool]:
            with self.lock:
                return sess.active_turn_id == turn_id, sess.cancel_requested

        try:
            is_current, _ = turn_state()
            if not is_current:
                return
            if _consume_e2e_next_turn() == "empty":
                with self.lock:
                    if sess.active_turn_id != turn_id:
                        return
                    sess.partial = None
                    self.add_message(sess, "assistant", empty_turn_fallback())
                    sess.running_llm_no = None
                    sess.running_model = None
                    sess.status = "idle"
                    sess.active_turn_id = ""
                    sess.last_error = ""
                emit_session_state(sess, "idle")
                return
            if sess.agent is None:
                sess.agent = self.make_agent(sess)
                if sess.llm_history:
                    try:
                        sess.agent.llmclient.backend.history = sess.llm_history
                    except Exception:
                        pass
            agent = sess.agent
            # 模型取会话绑定 sess.llm_no,未绑定回退全局默认。切换走 set_session_model。
            no = sess.llm_no if sess.llm_no is not None else _global_default_llm_no()
            if no is not None and hasattr(agent, "next_llm"):
                with contextlib.suppress(Exception):
                    agent.next_llm(int(no))
            with self.lock:
                sess.running_llm_no = getattr(agent, "llm_no", no)
                try:
                    running_backend = agent.llmclient.backend
                    sess.running_model = str(
                        getattr(running_backend, "current_name", None)
                        or getattr(running_backend, "name", None)
                        or getattr(running_backend, "model", None)
                        or ""
                    ) or None
                except Exception:
                    sess.running_model = None
            if images:
                self._patch_chat_for_images(agent.llmclient, images)
            full = ""
            done_outputs = None  # done时agent给的全量轮文本(turn_resps.copy())
            if hasattr(agent, "put_task"):
                display_q = agent.put_task(prompt, images=images or [])
                pieces = []
                import queue as _queue
                while True:
                    is_current, is_cancelled = turn_state()
                    if not is_current:
                        return
                    if is_cancelled:
                        break
                    try:
                        item = display_q.get(timeout=1.0)
                    except _queue.Empty:
                        continue
                    if isinstance(item, dict):
                        if item.get("next"):
                            text = str(item["next"])
                            pieces.append(text)
                            with self.lock:
                                if sess.partial is not None and sess.active_turn_id == turn_id:
                                    sess.partial["content"] = "".join(pieces) if getattr(agent, "inc_out", False) else text
                                    sess.partial["ts"] = time.time()
                                    sess.updated_at = time.time()
                                    # 轨道2: bridge 归一化为前端直接可渲染的 0 基 turn_segs；outputs=turn_resps[-2:]
                                    _t = int(item.get("turn", 0) or 0)
                                    _outs = item.get("outputs") or []
                                    _idx = max(0, _t - 1)
                                    sess.partial["curr_turn"] = _idx
                                    _segs = sess.partial["turn_segs"]
                                    while len(_segs) <= _idx:
                                        _segs.append("")
                                    if _outs:
                                        _segs[_idx] = str(_outs[-1])
                                        if len(_outs) >= 2 and _idx >= 1:
                                            _segs[_idx - 1] = str(_outs[-2])
                                    # Push partial to frontend via WS for real-time streaming
                                    hub.emit({"type": "partial-update", "sessionId": sess.id,
                                              "content": sess.partial["content"],
                                              "turn_segs": list(_segs), "curr_turn": _idx})
                        if "done" in item:
                            full = strip_final_info_marker(item.get("done") or "")
                            done_outputs = normalize_final_turn_segs(full, item.get("outputs"))  # done时=turn_resps.copy()全量轮
                            if done_outputs:
                                with self.lock:
                                    if sess.partial is not None and sess.active_turn_id == turn_id:
                                        sess.partial["content"] = full
                                        sess.partial["ts"] = time.time()
                                        sess.partial["updatedAt"] = sess.partial["ts"] if "updatedAt" in sess.partial else sess.partial.get("updatedAt")
                                        sess.partial["curr_turn"] = max(0, len(done_outputs) - 1)
                                        sess.partial["turn_segs"] = list(done_outputs)
                                        sess.updated_at = time.time()
                            break
                    else:
                        pieces.append(str(item))
                if not full and pieces:
                    full = pieces[-1] if not getattr(agent, "inc_out", False) else "".join(pieces)
            else:
                full = "GenericAgent object has no put_task method"
            is_current, is_cancelled = turn_state()
            if not is_current:
                return
            if not full:
                full = empty_turn_fallback()
            if is_cancelled:
                with self.lock:
                    sess.partial = None
                    sess.running_llm_no = None
                    sess.running_model = None
                    if sess.active_turn_id == turn_id:
                        sess.active_turn_id = ""
                    # Ensure status stays cancelled (don't overwrite)
                    if sess.status != "cancelled":
                        sess.status = "cancelled"
                    sess.updated_at = time.time()
                emit_session_state(sess, "cancelled")
                return
            with self.lock:
                if sess.active_turn_id != turn_id:
                    return
                sess.partial = None
                full = strip_final_info_marker(full)
                import plan_state
                plan_state.sync_plan_path_from_text(sess, full, sess.cwd or self.ga_root)
                # 轨道2: 落库时带结构化全量轮(权威turn_segs),前端按轮渲染;content保留兜底
                _final_segs = normalize_final_turn_segs(full, done_outputs)
                if _final_segs:
                    self.add_message(sess, "assistant", full, turn_segs=_final_segs)
                else:
                    self.add_message(sess, "assistant", full)
                try: sess.llm_history = json.loads(json.dumps(agent.llmclient.backend.history, ensure_ascii=False, default=str))
                except Exception: pass
                sess.running_llm_no = None
                sess.running_model = None
                sess.status = "idle"
                sess.active_turn_id = ""
                sess.last_error = ""
            emit_session_state(sess, "idle")
        except Exception as e:
            tb = traceback.format_exc()
            with self.lock:
                if sess.active_turn_id != turn_id:
                    return
                sess.partial = None
                sess.running_llm_no = None
                sess.running_model = None
                sess.status = "error"
                sess.active_turn_id = ""
                sess.last_error = str(e)
                self.add_message(sess, "error", str(e))
            bridge_print(f"[turn] error: {e}")
            print(tb, file=sys.stderr)
            emit_session_state(sess, "error")

    def messages(self, sid: str, after: int = 0, limit: int = 200) -> dict:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            msgs = [m for m in sess.messages if int(m.get("id", 0)) > after]
            if limit > 0:
                msgs = msgs[-limit:]
            import plan_state
            return {
                "sessionId": sid,
                "status": sess.status,
                "messages": msgs,
                "partial": dict(sess.partial) if sess.partial else None,
                "plan": plan_state.desktop_plan_payload_from_session(sess, self.ga_root),
                "msgSeq": sess.msg_seq,
                "updatedAt": sess.updated_at,
                "lastError": sess.last_error,
                "model": self._live_model(sess),
            }

    def plan_snapshot(self, sid: str) -> dict:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            import plan_state
            return {
                "sessionId": sid,
                "plan": plan_state.desktop_plan_payload_from_session(sess, self.ga_root),
            }

    def cancel(self, sid: str) -> dict:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            sess.cancel_requested = True
            if sess.agent and hasattr(sess.agent, "abort"):
                with contextlib.suppress(Exception):
                    sess.agent.abort()
            partial_text = ""
            if sess.partial:
                partial_text = (sess.partial.get("content") or "").strip()
            if partial_text:
                self.add_message(sess, "assistant", partial_text, stopped=True)
            sess.status = "cancelled"
            sess.active_turn_id = ""
            sess.partial = None
            sess.updated_at = time.time()
        emit_session_state(sess, "cancelled")
        return {"ok": True, "sessionId": sid}

    def restore_context(self, sid: str) -> dict:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            if sess.agent is not None:
                return {"ok": True, "sessionId": sid, "restored": False, "reason": "agent already alive"}
        agent = self.make_agent(sess)
        # 恢复 agent 时按会话绑定 seed 模型(未绑定则全局默认),保持显示/使用一致。
        no = sess.llm_no if sess.llm_no is not None else _global_default_llm_no()
        if no is not None and hasattr(agent, "next_llm"):
            with contextlib.suppress(Exception):
                agent.next_llm(int(no))
        if sess.llm_history:
            try:
                agent.llmclient.backend.history = sess.llm_history
            except Exception as e:
                bridge_print(f"[bridge] restore llm_history failed: {e}")
        else:
            history = []
            for m in sess.messages:
                role = m.get("role")
                content = m.get("content", "")
                if role == "user":
                    history.append({"role": "user", "content": [{"type": "text", "text": content}]})
                elif role == "assistant":
                    history.append({"role": "assistant", "content": [{"type": "text", "text": content}]})
            if history:
                try:
                    agent.llmclient.backend.history = history
                except Exception as e:
                    bridge_print(f"[bridge] inject history failed: {e}")
        with self.lock:
            sess.agent = agent
            sess.status = "idle"
        return {"ok": True, "sessionId": sid, "restored": True, "messageCount": len(sess.llm_history or sess.messages)}

    def set_session_model(self, sid: str, llm_no: int) -> dict:
        """Bind a model to a session.

        An idle agent switches immediately. A running turn keeps its captured client;
        the new binding is applied at the start of the next turn.
        """
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            sess.llm_no = int(llm_no)
            if (sess.status != "running" and sess.agent is not None
                    and hasattr(sess.agent, "next_llm")):
                with contextlib.suppress(Exception):
                    sess.agent.next_llm(int(llm_no))
            sess.updated_at = time.time()
        self._persist_session(sess)
        return {"ok": True, "sessionId": sid, "llmNo": sess.llm_no, "model": self._live_model(sess)}


import base64


def normalize_prompt(prompt: Any, images: Optional[list] = None):
    """Flatten a prompt (str or content-part list) to plain text.

    Image/file attachments are handled by the frontend, which inlines the
    uploaded file path into the prompt text (see expandFilePlaceholders) and
    sends path-only metadata via files/imageMetas — so no per-prompt image
    persistence happens here. The `images` arg is accepted for backward compat
    and ignored; the returned image-id list is always empty.
    """
    if isinstance(prompt, list):
        text_parts = []
        for part in prompt:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                text_parts.append(str(part.get("text") or part.get("content") or ""))
        prompt = "\n".join([p for p in text_parts if p])

    return str(prompt or ""), []


manager = AgentManager()

# Initialize per-call token ledger
try:
    import cost_tracker
    cost_tracker.init_ledger(manager.ga_root)
except Exception:
    pass


# ---------------------------------------------------------------------------
# Transport layer: WS state push
# ---------------------------------------------------------------------------

class WsHub:
    def __init__(self):
        self.websockets: Set[web.WebSocketResponse] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def emit(self, obj: dict):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast(obj), self.loop)

    async def _broadcast(self, obj: dict):
        data = json.dumps(obj, ensure_ascii=False, default=str)
        dead = set()
        for ws in list(self.websockets):
            try:
                await ws.send_str(data)
            except Exception:
                dead.add(ws)
        self.websockets.difference_update(dead)


hub = WsHub()


# ---------------------------------------------------------------------------
# Service management (hub.pyw core + WS notify)
# ---------------------------------------------------------------------------

_SKIP = frozenset({"goal_mode.py", "chatapp_common.py", "tuiapp.py", "qtapp.py"})
BRIDGE_ID = "__bridge__"

_SERVICE_KEYS: Dict[str, tuple] = {
    "frontends/qqapp.py": ("qq_app_id", "qq_app_secret"),
    "frontends/dcapp.py": ("discord_bot_token",),
    "frontends/dingtalkapp.py": ("dingtalk_client_id", "dingtalk_client_secret"),
    "frontends/fsapp.py": ("fs_app_id", "fs_app_secret"),
    "frontends/tgapp.py": ("tg_bot_token",),
    "frontends/wecomapp.py": ("wecom_bot_id", "wecom_secret"),
}


def _load_mykeys(ga_root: Path) -> dict:
    if not (ga_root / "mykey.py").exists():
        return {}
    root = str(ga_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    import mykey as mk
    importlib.reload(mk)
    return {k: v for k, v in vars(mk).items() if not k.startswith("_")}


def discover_im_services(ga_root: Path) -> List[dict]:
    out: List[dict] = []
    d = ga_root / "frontends"
    if not d.is_dir():
        return out
    for f in sorted(os.listdir(d)):
        if "app" not in f or not f.endswith(".py") or f in _SKIP or "stapp" in f or "tuiapp" in f:
            continue
        rel = f"frontends/{f}"
        out.append({"id": rel, "cmd": [sys.executable, str(d / f)]})
    return out


def discover_extra_services(ga_root: Path) -> List[dict]:
    out: List[dict] = []
    sched = ga_root / "reflect" / "scheduler.py"
    if sched.is_file():
        out.append({
            "id": "reflect/scheduler.py",
            "cmd": [sys.executable, "agentmain.py", "--reflect", "reflect/scheduler.py"],
        })
    # conductor 跟 scheduler 一样,bridge 启动时自动拉起。--no-browser 是关键:
    # conductor.py 默认会用 webbrowser.open 在用户浏览器弹一个 8900 端口 UI,
    # 桌面版自启时不需要这个独立 UI(用户从「指挥家」页直接访问)。
    # The desktop conductor evolves with this bridge. Keep both package-owned and inject the
    # external core through GA_ROOT instead of executing arbitrary UI glue from that checkout.
    conductor = APP_DIR / "conductor.py"
    if conductor.is_file():
        out.append({
            "id": "frontends/conductor.py",
            "cmd": [sys.executable, str(conductor), "--no-browser"],
            "port": 8900,
        })
    return out


def _port_alive(port: Optional[int]) -> bool:
    """Check if something is listening on localhost:port."""
    if not port:
        return False
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _mem_mb(pid: Optional[int]) -> Optional[int]:
    if not pid:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(counters), counters.cb)
        ctypes.windll.kernel32.CloseHandle(h)
        return round(counters.WorkingSetSize / 1024 / 1024) if ok else None
    status = Path(f"/proc/{pid}/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024)
    return None


def _cpu_pct(pid: Optional[int]) -> Optional[float]:
    if not pid:
        return None
    try:
        import psutil
        return round(psutil.Process(pid).cpu_percent(0) or 0, 1)
    except Exception:
        return None


_ERROR_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"errno 48|address already in use", re.I), "transient", "err.portBusy"),
    (re.compile(r"Exception in thread conductor", re.I), "fatal", "err.conductorCrash"),
    (re.compile(r"ModuleNotFoundError|ImportError", re.I), "fatal", "err.missingModule"),
    (re.compile(r"ConnectionRefusedError|Connection refused", re.I), "warning", "err.connRefused"),
    (re.compile(r"TimeoutError|timed out", re.I), "warning", "err.timeout"),
]


def _classify_log_error(line: str) -> tuple[str, str] | None:
    """Classify a log line by severity. Returns (severity, i18n_key) or None."""
    for pattern, severity, key in _ERROR_PATTERNS:
        if pattern.search(line):
            return (severity, key)
    return None


class ServiceManager:
    """hub.pyw ServiceManager + HTTP/WS glue."""

    def __init__(self, ga_root: str, emit_fn):
        self.ga_root = Path(ga_root)
        self.procs: Dict[str, subprocess.Popen] = {}
        self.buffers: Dict[str, deque] = {}
        self._emit = emit_fn
        im = discover_im_services(self.ga_root)
        extra = discover_extra_services(self.ga_root)
        self._im_catalog = {s["id"]: s for s in im}
        self._catalog = {**self._im_catalog, **{s["id"]: s for s in extra}}
        self._stopping: Set[str] = set()

    def _is_configured(self, sid: str) -> bool:
        keys = _SERVICE_KEYS.get(sid)
        if not keys:
            return True
        mykeys = _load_mykeys(self.ga_root)
        return all(str(mykeys.get(k) or "").strip() for k in keys)

    def _scan_errors(self, sid: str, n: int = 20) -> dict:
        """Scan last N buffer lines, classify by severity.
        Returns {"fatal": (line, key) | None, "warning": (line, key) | None}.
        Transient errors (e.g. port-busy retry) are discarded.
        """
        buf = self.buffers.get(sid)
        if not buf:
            return {"fatal": None, "warning": None}
        lines = [ln.strip() for ln in list(buf)[-n:] if ln.strip()]
        if not lines:
            return {"fatal": None, "warning": None}
        result: dict = {"fatal": None, "warning": None}
        for line in lines:
            classified = _classify_log_error(line)
            if classified is None:
                continue
            severity, key = classified
            if severity == "fatal":
                result["fatal"] = (line[:300], key)
            elif severity == "warning":
                result["warning"] = (line[:300], key)
        return result

    def _log_tail(self, sid: str, n: int = 3) -> str:
        """Legacy: return last fatal error line for lastError field."""
        scan = self._scan_errors(sid, n=20)
        if scan["fatal"]:
            return scan["fatal"][0]
        buf = self.buffers.get(sid)
        if not buf:
            return ""
        lines = [ln.strip() for ln in list(buf)[-n:] if ln.strip()]
        return lines[-1][:300] if lines else ""

    def _state(self, sid: str, *, err: str = "") -> dict:
        proc = self.procs.get(sid)
        running = proc is not None and proc.poll() is None
        status = "running" if running else "offline"
        last_error = err
        error_key = ""
        last_warning = ""
        warning_key = ""
        scan = self._scan_errors(sid)
        catalog_port = self._catalog.get(sid, {}).get("port")
        if proc is not None and proc.poll() is not None:
            if sid in self._stopping:
                status, last_error = "offline", ""
            elif _port_alive(catalog_port):
                status, running = "running", True
            else:
                status = "error"
                if scan["fatal"]:
                    last_error = scan["fatal"][0]
                    error_key = scan["fatal"][1]
                elif err:
                    last_error = err
                else:
                    last_error = f"exit code {proc.returncode}"
        elif not running and not err and _port_alive(catalog_port):
            status, running = "running", True
        elif running:
            if scan["warning"]:
                last_warning = scan["warning"][0]
                warning_key = scan["warning"][1]
        elif err:
            status, running = "error", False
            last_error = err
            if scan["fatal"]:
                error_key = scan["fatal"][1]
        return {
            "id": sid,
            "status": status,
            "running": running,
            "pid": proc.pid if running else None,
            "lastError": last_error,
            "errorKey": error_key,
            "lastWarning": last_warning,
            "warningKey": warning_key,
        }

    def list_state(self) -> List[dict]:
        return [self._state(sid) for sid in sorted(self._im_catalog)]

    def _bridge_state(self) -> dict:
        pid = os.getpid()
        port = int(os.environ.get("BRIDGE_PORT", "14168"))
        return {
            "id": BRIDGE_ID,
            "name": f"bridge (:{port})",
            "status": "running",
            "running": True,
            "pid": pid,
            "memMb": _mem_mb(pid),
            "cpuPct": _cpu_pct(pid),
            "managed": False,
            "lastError": "",
        }

    def list_panel_state(self) -> List[dict]:
        out = [self._bridge_state()]
        for sid in sorted(self._catalog, key=lambda s: (s in self._im_catalog, s)):
            item = self._state(sid)
            item["name"] = sid
            item["memMb"] = _mem_mb(item.get("pid"))
            item["cpuPct"] = _cpu_pct(item.get("pid"))
            item["managed"] = True
            out.append(item)
        return out

    def _notify(self, sid: str, *, err: str = "") -> None:
        self._emit({"type": "service.changed", "service": self._state(sid, err=err)})

    def _wait_started(self, proc: subprocess.Popen, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.1)

    def _reader(self, sid: str, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            buf = self.buffers.get(sid)
            if buf is not None:
                buf.append(line)
        self._notify(sid)

    def start_service(self, sid: str) -> dict:
        svc = self._catalog.get(sid)
        if not svc:
            raise KeyError(sid)
        proc = self.procs.get(sid)
        if proc is not None and proc.poll() is None:
            return {"ok": True, "service": self._state(sid)}
        if not self._is_configured(sid):
            keys = ", ".join(_SERVICE_KEYS.get(sid, ()))
            err = f"not configured in mykey.py ({keys})"
            self._notify(sid, err=err)
            return {"ok": False, "error": "not_configured", "service": self._state(sid, err=err)}
        self.buffers[sid] = deque(maxlen=500)
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "GA_ROOT": str(self.ga_root),
        }
        kw: Dict[str, Any] = dict(
            cwd=str(self.ga_root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
        )
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(svc["cmd"], **kw)
        self.procs[sid] = proc
        threading.Thread(target=self._reader, args=(sid, proc), daemon=True).start()
        self._wait_started(proc)
        item = self._state(sid)
        self._notify(sid)
        if item["status"] == "error":
            return {"ok": False, "error": item["lastError"] or "start_failed", "service": item}
        return {"ok": True, "service": item}

    def autostart_extras(self) -> None:
        """Auto-start non-IM services on bridge boot. Currently:
          - reflect/scheduler.py (drives L4 archive cron every 12h).
        IM services stay manual (need explicit mykey.py config + user opt-in)."""
        for sid in sorted(set(self._catalog) - set(self._im_catalog)):
            try:
                res = self.start_service(sid)
                tag = "ok" if res.get("ok") else f"fail: {res.get('error')}"
            except Exception as e:
                tag = f"exception {type(e).__name__}: {e}"
            bridge_print(f"[autostart] {sid}: {tag}")

    def stop_all_extras(self) -> None:
        for sid in sorted(set(self._catalog) - set(self._im_catalog)):
            with contextlib.suppress(Exception):
                self.stop_service(sid)

    def _extra_is_broken(self, sid: str) -> bool:
        """判断一个 extra 是否「已经坏掉、需要重启才能恢复」:
          - 进程异常退出(非用户主动停)→ 坏(覆盖 scheduler 那种进程级崩溃);
          - 进程还活着,但捕获日志里出现 `Exception in thread conductor-agent`
            → 内部 agent 线程已崩死,uvicorn 还在跑但再也处理不了任务 → 坏。
        健康运行中的进程返回 False:它会在下个任务靠自身 mtime 热重载读到新 mykey,
        不该被打断。每次 start_service 都会换新缓冲,故缓冲里的崩溃签名只反映当前进程。"""
        proc = self.procs.get(sid)
        if proc is None:
            return False                       # 没起过 / 用户主动停掉 → 不复活
        if proc.poll() is not None:
            return sid not in self._stopping   # 意外退出 = 坏
        buf = self.buffers.get(sid)
        return bool(buf) and any("Exception in thread conductor-agent" in ln for ln in buf)

    def restart_broken_extras(self) -> None:
        """mykey 被整体重写(导入密钥/编辑渠道配置)后,只重启「已经坏掉」的
        conductor/scheduler。健康运行中的进程不动——它们会在下个任务靠自身 mtime
        热重载新 key,强行重启反而会打断正在跑的任务。"""
        for sid in sorted(set(self._catalog) - set(self._im_catalog)):
            if not self._extra_is_broken(sid):
                continue
            with contextlib.suppress(Exception):
                self.stop_service(sid)
            try:
                res = self.start_service(sid)
                tag = "ok" if res.get("ok") else f"fail: {res.get('error')}"
            except Exception as e:
                tag = f"exception {type(e).__name__}: {e}"
            bridge_print(f"[restart-broken] {sid}: {tag}")

    def stop_service(self, sid: str) -> dict:
        if sid not in self._catalog:
            raise KeyError(sid)
        self._stopping.add(sid)
        proc = self.procs.get(sid)
        if proc and proc.poll() is None:
            proc.terminate()
            proc.wait()
        self.procs.pop(sid, None)
        self._stopping.discard(sid)
        item = self._state(sid)
        self._notify(sid)
        return {"ok": True, "service": item}

    def read_logs(self, sid: str, tail: int = 200) -> dict:
        if sid == BRIDGE_ID:
            tail = max(1, min(int(tail or 200), 2000))
            lines = list(_bridge_log)[-tail:]
            if not lines:
                lines = [f"GenericAgent bridge pid={os.getpid()}"]
            return {"ok": True, "lines": lines}
        if sid not in self._catalog:
            raise KeyError(sid)
        tail = max(1, min(int(tail or 200), 2000))
        buf = self.buffers.get(sid)
        lines = [ln.rstrip("\n") for ln in list(buf or [])[-tail:]]
        return {"ok": True, "lines": lines}


services = ServiceManager(str(DEFAULT_GA_ROOT), hub.emit)


def _bridge_shutdown_services() -> None:
    with contextlib.suppress(Exception):
        services.stop_all_extras()


atexit.register(_bridge_shutdown_services)


def emit_session_state(sess: Session, state_name: str):
    if state_name != "created":
        title = (sess.title or sess.id)[:20]
        bridge_print(f"[session] {title}: {state_name}")
    hub.emit({
        "type": "session-state",
        "sessionId": sess.id,
        "state": state_name,
        "status": sess.status,
        "seq": sess.msg_seq,
        "updatedAt": sess.updated_at,
        "title": sess.title,
    })


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    hub.websockets.add(ws)
    await ws.send_str(json.dumps({
        "type": "bridge-ready",
        "gaRoot": manager.ga_root,
        "mykeyPath": manager.mykey_path,
        "http": True,
        "wsEventsOnly": True,
    }, ensure_ascii=False))
    await ws.send_str(json.dumps({
        "type": "services.snapshot",
        "services": services.list_state(),
    }, ensure_ascii=False, default=str))
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            # WS is intentionally not a data/command channel anymore.
            with contextlib.suppress(Exception):
                data = json.loads(msg.data)
                if data.get("action") == "ping":
                    await ws.send_str(json.dumps({"type": "pong", "ts": time.time()}, ensure_ascii=False))
    hub.websockets.discard(ws)
    return ws


# ---------------------------------------------------------------------------
# Transport layer: HTTP command/data API
# ---------------------------------------------------------------------------

def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=cors_headers())
    resp = await handler(request)
    for k, v in cors_headers().items():
        resp.headers[k] = v
    return resp


def json_ok(data: dict, status: int = 200):
    return web.json_response(data, status=status, headers=cors_headers(), dumps=lambda x: json.dumps(x, ensure_ascii=False, default=str))


async def read_json(request) -> dict:
    if request.can_read_body:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


async def status_handler(request):
    return json_ok({
        "ok": True,
        "running": True,
        "ready": True,
        "gaRoot": manager.ga_root,
        "mykeyPath": manager.mykey_path,
        "sessionCount": len(manager.sessions),
        "activeSessionId": manager.active_session_id,
        "ws": "/ws",
        "transport": {"http": True, "wsEventsOnly": True},
    })


_SETTINGS = Path.home() / ".ga_desktop_settings.json"
_UI_KEYS = ("lang", "theme", "appearance", "plain", "llmNo", "fontSize")


def _settings_doc() -> dict:
    try:
        doc = json.loads(_SETTINGS.read_text(encoding="utf-8")) if _SETTINGS.is_file() else {}
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _write_settings_doc(doc: dict) -> None:
    _SETTINGS.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _desktop_ui() -> dict:
    ui = _settings_doc().get("ui")
    return dict(ui) if isinstance(ui, dict) else {}


def _conductor_settings() -> dict:
    conductor = _settings_doc().get("conductor")
    return dict(conductor) if isinstance(conductor, dict) else {}


def _global_default_llm_no() -> int:
    """全局默认模型下标。会话未绑定(sess.llm_no is None)时回退到它。"""
    no = _desktop_ui().get("llmNo")
    try:
        return int(no) if no is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_model_no(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_conductor_model_state(doc: dict, profile_count: int) -> dict:
    """Resolve persisted Conductor config without relying on modulo selection."""
    count = max(0, int(profile_count or 0))
    conductor = doc.get("conductor") if isinstance(doc, dict) else None
    ui = doc.get("ui") if isinstance(doc, dict) else None
    raw_configured = conductor.get("llmNo") if isinstance(conductor, dict) else None
    configured = _parse_model_no(raw_configured)
    ui_default = _parse_model_no(ui.get("llmNo")) if isinstance(ui, dict) else None

    if count <= 0:
        return {"configured": configured, "effective": None, "fallbackReason": "no_models"}
    if configured is not None and 0 <= configured < count:
        return {"configured": configured, "effective": configured, "fallbackReason": None}
    if ui_default is not None and 0 <= ui_default < count:
        reason = "invalid_configured" if raw_configured is not None else "ui_default"
        return {"configured": configured, "effective": ui_default, "fallbackReason": reason}
    return {"configured": configured, "effective": 0, "fallbackReason": "first_available"}


async def get_config_handler(request):
    profiles = manager.list_model_profiles()
    active = next((p["id"] for p in profiles if p.get("active")), manager.config.get("llmNo", 0))
    cfg = dict(manager.config)
    if "llmNo" not in cfg:
        cfg["llmNo"] = active
    cfg.update(_desktop_ui())
    cfg["conductor"] = _conductor_settings()
    return json_ok({"gaRoot": manager.ga_root, "mykeyPath": manager.mykey_path, "config": cfg})


async def save_config_handler(request):
    data = await read_json(request)
    cfg = data.get("config", data)
    if isinstance(cfg, dict):
        patch = {k: cfg[k] for k in _UI_KEYS if k in cfg}
        if patch:
            try:
                doc = _settings_doc()
                ui = doc["ui"] if isinstance(doc.get("ui"), dict) else {}
                ui.update(patch)
                doc["ui"] = ui
                _write_settings_doc(doc)
            except Exception as e:
                bridge_print(f"[bridge] save ui prefs failed: {e}")
        manager.config.update(cfg)
    return json_ok({"ok": True, "gaRoot": manager.ga_root, "mykeyPath": manager.mykey_path, "config": manager.config})


async def model_profiles_handler(request):
    try:
        pid = request.match_info.get("id")
        if pid is not None:
            profile_id = int(pid)
            if request.method == "GET":
                return json_ok({"profile": manager.get_model_profile(profile_id)})
            if request.method == "PUT":
                return json_ok({"ok": True, **manager.update_model_profile(profile_id, await read_json(request))})
            if request.method == "DELETE":
                return json_ok({"ok": True, **manager.delete_model_profile(profile_id)})
            return json_ok({"ok": False, "error": "method not allowed"}, status=405)
        if request.method == "POST":
            return json_ok({"ok": True, **manager.add_model_profile(await read_json(request))})
        return json_ok({"profiles": manager.list_model_profiles()})
    except ValueError as e:
        return json_ok({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)}, status=500)


async def mixin_handler(request):
    """聚合渠道成员管理：POST 加入 / DELETE 移出 主聚合渠道。"""
    try:
        profile_id = int(request.match_info.get("id"))
        if request.method == "POST":
            return json_ok({"ok": True, **manager.add_to_mixin(profile_id)})
        if request.method == "DELETE":
            return json_ok({"ok": True, **manager.remove_from_mixin(profile_id)})
        return json_ok({"ok": False, "error": "method not allowed"}, status=405)
    except ValueError as e:
        return json_ok({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)}, status=500)


async def mixin_order_handler(request):
    """渠道组成员拖拽排序：PUT {members:[name,...]}。"""
    try:
        data = await read_json(request)
        return json_ok({"ok": True, **manager.reorder_mixin(data.get("members") or [])})
    except ValueError as e:
        return json_ok({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)}, status=500)


async def list_sessions_handler(request):
    with manager.lock:
        sessions = [manager.snapshot(s, include_messages=False)
                    for s in manager.sessions.values() if _is_desktop_session_id(s.id)]
    return json_ok({"sessions": sessions, "activeSessionId": manager.active_session_id})


async def new_session_handler(request):
    data = await read_json(request)
    sess = manager.create_session(cwd=data.get("cwd") or data.get("path"))
    return json_ok({"ok": True, "sessionId": sess.id, "session": manager.snapshot(sess)}, status=201)


async def get_session_handler(request):
    sid = request.match_info["sid"]
    sess = manager.get_session(sid)
    return json_ok({"sessionId": sid, "session": manager.snapshot(sess), "messages": list(sess.messages), "partial": sess.partial})


async def delete_session_handler(request):
    sid = request.match_info["sid"]
    return json_ok(manager.delete_session(sid))


async def patch_session_handler(request):
    sid = request.match_info["sid"]
    sess = manager.get_session(sid)
    data = await read_json(request)
    if "title" in data:
        sess.title = data["title"]
        sess.untitled = False
    if "pinned" in data:
        sess.pinned = bool(data["pinned"])
    if "untitled" in data:
        sess.untitled = bool(data["untitled"])
    if "plan_scan_baseline" in data:
        sess.plan_scan_baseline = int(data["plan_scan_baseline"])
    sess.updated_at = time.time()
    manager._persist_session(sess)
    return json_ok({"ok": True, "session": manager.snapshot(sess, include_messages=False)})


async def prompt_handler(request):
    sid = request.match_info["sid"]
    data = await read_json(request)
    prompt = data.get("prompt", data.get("content", data.get("message", "")))
    images = data.get("images") or []
    display = data.get("display")
    files_meta = data.get("files") or []        # 非图片附件 [{name, path}]
    image_metas = data.get("imageMetas") or []   # 图片附件 [{name, path}]（不含 dataUrl）
    # 模型不再随 prompt 携带:切换模型走 POST /session/{sid}/model 这一唯一入口,
    # 发消息只使用会话已绑定的 sess.llm_no(未绑定则回退全局默认)。
    return json_ok(manager.submit_prompt(sid, prompt, images, display=display,
                                          files_meta=files_meta, image_metas=image_metas))


async def messages_handler(request):
    sid = request.match_info["sid"]
    after = int(request.query.get("after") or request.query.get("afterId") or 0)
    limit = int(request.query.get("limit") or 200)
    return json_ok(manager.messages(sid, after=after, limit=limit))


async def cancel_handler(request):
    sid = request.match_info["sid"]
    return json_ok(manager.cancel(sid))


async def restore_handler(request):
    sid = request.match_info["sid"]
    return json_ok(manager.restore_context(sid))


async def session_model_handler(request):
    sid = request.match_info["sid"]
    data = await read_json(request)
    no = data.get("llmNo", data.get("llm_no"))
    if no is None:
        return json_ok({"ok": False, "error": "missing llmNo"}, status=400)
    try:
        return json_ok(manager.set_session_model(sid, int(no)))
    except (TypeError, ValueError):
        return json_ok({"ok": False, "error": "invalid llmNo"}, status=400)


async def plan_handler(request):
    sid = request.match_info["sid"]
    return json_ok(manager.plan_snapshot(sid))


async def path_open_handler(request):
    data = await read_json(request)
    kind = data.get("kind", "")
    mode = data.get("mode", "open")
    if kind == "mykey":
        target = Path(manager.ga_root) / "mykey.py"
        if not target.exists():
            template = Path(manager.ga_root) / "mykey_template.py"
            target = template if template.exists() else target
    elif kind == "mykeyTemplate":
        target = Path(manager.ga_root) / "mykey_template.py"
    elif kind == "upload":
        raw = Path(data.get("path") or "")
        try:
            resolved = raw.resolve()
            upload_root = _WEB_UPLOAD_DIR.resolve()
            resolved.relative_to(upload_root)
        except (ValueError, OSError):
            return json_ok({"ok": False, "error": "path not in upload dir"}, status=403)
        target = resolved
    else:
        target = Path(data.get("path") or data.get("target") or manager.ga_root)
    target = target.resolve()
    if not target.exists():
        return json_ok({"ok": False, "error": f"File not found: {target}"}, status=404)
    try:
        if mode == "reveal":
            _reveal_path_in_file_manager(target)
        elif kind == "upload":
            _open_path_default(target)  # 用户文件用系统默认程序(open 动词),避免 edit 动词 fallback 记事本
        else:
            _open_path_in_editor(target)  # mykey 等配置文件仍用编辑器(edit 动词)
    except OSError as e:
        return json_ok({"ok": False, "error": str(e), "path": str(target)}, status=500)
    return json_ok({"ok": True, "path": str(target)})


# File attachments live under GA's own temp dir (gitignored), NOT the OS temp
# dir, so they survive bridge restarts. Instead of wiping everything on startup,
# we keep files for UPLOAD_RETENTION_DAYS and only sweep stale ones.
_WEB_UPLOAD_DIR = Path(DEFAULT_GA_ROOT) / "temp" / "desktop_uploads"
_WEB_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_RETENTION_DAYS = 30


def _safe_session_dir(sid: str) -> str:
    """Sanitize a session id into a safe single-level folder name."""
    s = re.sub(r"[^A-Za-z0-9_-]", "", str(sid or ""))
    return s or "_misc"


def _session_upload_dir(sid: str) -> Path:
    """Per-session upload subdir under desktop_uploads/, created on demand."""
    d = _WEB_UPLOAD_DIR / _safe_session_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _purge_session_uploads(sid: str) -> None:
    """Best-effort: drop a session's whole upload subdir when the session is deleted."""
    import shutil
    with contextlib.suppress(Exception):
        shutil.rmtree(_WEB_UPLOAD_DIR / _safe_session_dir(sid), ignore_errors=True)


def _sweep_stale_uploads(retention_days: int = UPLOAD_RETENTION_DAYS) -> None:
    """Best-effort: delete uploaded files older than retention_days (by mtime),
    then drop empty session subdirs. Replaces the old wholesale rmtree-on-startup
    so attachments persist across restarts while temp storage can't grow forever."""
    cutoff = time.time() - retention_days * 86400
    try:
        for f in _WEB_UPLOAD_DIR.rglob("*"):
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass
        for d in _WEB_UPLOAD_DIR.iterdir():
            try:
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass
    except OSError:
        pass


_sweep_stale_uploads()


async def upload_handler(request):
    """Save a file uploaded by the web client and return its absolute path.
    Body: {name: "<original filename>", dataUrl: "data:<mime>;base64,<...>", sid: "<session id>"}
    Files are grouped per session under desktop_uploads/<sid>/ so deleting a
    session can purge its attachments. Missing sid falls back to a _misc bucket.
    Returns: {ok: true, path: "<abs path>"}
    """
    try:
        data = await request.json()
        if not isinstance(data, dict):
            data = {}
    except web.HTTPRequestEntityTooLarge:
        return json_ok({"ok": False, "error": "file too large for bridge body limit"})
    except Exception as e:
        return json_ok({"ok": False, "error": f"invalid request: {e}"})
    name = (data.get("name") or "file").strip().replace("/", "_").replace("\\", "_")
    data_url = data.get("dataUrl") or ""
    if "," in data_url:
        b64 = data_url.split(",", 1)[1]
    else:
        b64 = data_url
    try:
        blob = base64.b64decode(b64)
    except Exception as e:
        return json_ok({"ok": False, "error": f"decode failed: {e}"})
    if not blob:
        return json_ok({"ok": False, "error": "empty file"})
    safe_name = name or "file"
    fpath = _session_upload_dir(data.get("sid") or "") / f"{uuid.uuid4().hex[:12]}__{safe_name}"
    fpath.write_bytes(blob)
    return json_ok({"ok": True, "path": str(fpath)})


async def upload_delete_handler(request):
    """Delete a previously-uploaded file. Path must live under _WEB_UPLOAD_DIR."""
    data = await read_json(request)
    raw = data.get("path") or ""
    try:
        target = Path(raw).resolve()
        upload_root = _WEB_UPLOAD_DIR.resolve()
        if upload_root not in target.parents:
            return json_ok({"ok": False, "error": "path outside upload dir"})
        if target.exists():
            target.unlink()
        return json_ok({"ok": True})
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)})


async def upload_raw_handler(request):
    """Stream an uploaded file. inline by default (browser preview / <img>),
    ?download=1 forces a download. Path must live under _WEB_UPLOAD_DIR
    (whitelist — prevents path traversal). Works for remote browsers too,
    so it covers both 'preview after refresh' and 'download from remote'."""
    import mimetypes
    from urllib.parse import quote
    raw = request.query.get("path", "")
    try:
        target = Path(raw).resolve()
        target.relative_to(_WEB_UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return web.Response(status=403, text="path not in upload dir")
    if not target.is_file():
        return web.Response(status=404, text="file not found")
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    disp = "attachment" if request.query.get("download") in ("1", "true") else "inline"
    orig_name = target.name.split("__", 1)[-1]  # 去掉 <uuid>__ 前缀，还原原始文件名
    return web.Response(
        body=target.read_bytes(),
        content_type=ctype,
        headers={
            "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(orig_name)}",
            "Cache-Control": "no-cache",
        },
    )


def _open_path_in_editor(target: Path) -> None:
    """Open a file in the user's editor; Windows .py often has no default association."""
    import platform
    path = str(target.resolve())
    if platform.system() == "Windows":
        try:
            os.startfile(path, "edit")
            return
        except OSError:
            pass
        for cmd in (["notepad.exe", path], ["cursor.cmd", path], ["code.cmd", path], ["cursor", path], ["code", path]):
            try:
                subprocess.Popen(cmd, close_fds=True)
                return
            except (FileNotFoundError, OSError):
                continue
        raise OSError(f"No editor available to open: {path}")
    if platform.system() == "Darwin":
        subprocess.Popen(["open", path])
        return
    subprocess.Popen(["xdg-open", path])


def _reveal_path_in_file_manager(target: Path) -> None:
    """Open the system file manager and select/highlight the target file."""
    import platform
    path = str(target.resolve())
    if platform.system() == "Windows":
        subprocess.Popen(["explorer", "/select,", path])
        return
    if platform.system() == "Darwin":
        subprocess.Popen(["open", "-R", path])
        return
    # Linux: no universal "select file" command; fall back to opening parent dir
    subprocess.Popen(["xdg-open", str(target.parent)])


def _open_path_default(target: Path) -> None:
    """Open a file with the OS default app (default 'open' verb).

    For user uploads. Unlike _open_path_in_editor (which uses Windows' 'edit'
    verb and falls back to Notepad), this respects each file type's registered
    default app — PDF viewer, Word, archive tool, etc. — so binaries like pdf
    or docx no longer land in Notepad as garbage."""
    import platform
    path = str(target.resolve())
    if platform.system() == "Windows":
        os.startfile(path)  # default "open" verb = double-click behavior
        return
    if platform.system() == "Darwin":
        subprocess.Popen(["open", path])
        return
    subprocess.Popen(["xdg-open", path])


def _mykey_file() -> Path:
    root = Path(manager.ga_root)
    target = root / "mykey.py"
    if not target.is_file():
        template = root / "mykey_template.py"
        if template.is_file():
            target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target


async def mykey_get_handler(request):
    target = _mykey_file()
    content = target.read_text(encoding="utf-8") if target.is_file() else ""
    return json_ok({"content": content, "path": str(target)})


async def mykey_save_handler(request):
    data = await read_json(request)
    content = data.get("content")
    if content is None:
        return json_ok({"ok": False, "error": "missing_content"}, status=400)
    try:
        profiles = manager._save_mykey_text(str(content))
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)}, status=400)
    # 导入/整体重写 mykey 后,只有「已崩坏」的 conductor/scheduler 才重启(死了才救);
    # 健康运行中的进程不打断,它们会在下个任务靠自身 mtime 热重载读到新 key。
    services.restart_broken_extras()
    return json_ok({"ok": True, "path": str(manager._mykey_file()), "profiles": profiles})


def _import_memory_from(source_dir: str, ga_root: str) -> dict:
    """把 source_dir 的 memory/ 与 temp/model_responses/ 导入到 ga_root。

    memory/: 先整体备份现有 ga_root/memory 到 temp/memory_import_backup_<ts>/,再覆盖同名文件、补齐新文件。
    temp/model_responses/: 文件名带 pid/logid 天然唯一,只拷目标端不存在的,已存在的跳过。
    """
    src = Path(source_dir).expanduser().resolve()
    dst_root = Path(ga_root).resolve()
    if not src.is_dir():
        raise ValueError(f"source is not a directory: {src}")
    if src == dst_root:
        raise ValueError("source is the same as current GA root")

    src_mem = src / "memory"
    src_resp = src / "temp" / "model_responses"
    if not src_mem.is_dir() and not src_resp.is_dir():
        raise ValueError("not a GA directory (no memory/ or temp/model_responses/)")

    memory_copied = 0
    responses_copied = 0
    responses_skipped = 0
    backup_dir = ""

    # --- memory/: 备份后覆盖 ---
    if src_mem.is_dir():
        dst_mem = dst_root / "memory"
        if dst_mem.is_dir() and any(dst_mem.iterdir()):
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup_root = dst_root / "temp" / f"memory_import_backup_{ts}"
            backup_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(dst_mem, backup_root / "memory")
            backup_dir = str(backup_root)
        dst_mem.mkdir(parents=True, exist_ok=True)
        for item in src_mem.rglob("*"):
            rel = item.relative_to(src_mem)
            target = dst_mem / rel
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                memory_copied += 1

    # --- temp/model_responses/: 补齐缺失 ---
    if src_resp.is_dir():
        dst_resp = dst_root / "temp" / "model_responses"
        dst_resp.mkdir(parents=True, exist_ok=True)
        for item in src_resp.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(src_resp)
            target = dst_resp / rel
            if target.exists():
                responses_skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            responses_copied += 1

    return {
        "ok": True,
        "memoryCopied": memory_copied,
        "responsesCopied": responses_copied,
        "responsesSkipped": responses_skipped,
        "backupDir": backup_dir,
    }


async def memory_import_handler(request):
    data = await read_json(request)
    source_dir = (data.get("sourceDir") or "").strip()
    if not source_dir:
        return json_ok({"ok": False, "error": "missing_sourceDir"}, status=400)
    try:
        result = _import_memory_from(source_dir, manager.ga_root)
        result.update(manager.import_sessions(source_dir))
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)}, status=400)
    return json_ok(result)


async def conductor_model_get_handler(request):
    state = _resolve_conductor_model_state(_settings_doc(), len(manager.list_model_profiles()))
    return json_ok({"model": state})


async def conductor_model_save_handler(request):
    data = await read_json(request)
    try:
        llm_no = int(data.get("llmNo"))
    except (TypeError, ValueError):
        return json_ok({"ok": False, "error": "invalid_llmNo"}, status=400)
    profile_count = len(manager.list_model_profiles())
    if llm_no < 0 or llm_no >= profile_count:
        return json_ok({"ok": False, "error": "model_out_of_range"}, status=400)
    try:
        doc = _settings_doc()
        conductor = doc["conductor"] if isinstance(doc.get("conductor"), dict) else {}
        conductor["llmNo"] = llm_no
        doc["conductor"] = conductor
        _write_settings_doc(doc)
    except Exception as e:
        return json_ok({"ok": False, "error": str(e)}, status=500)
    state = _resolve_conductor_model_state(doc, profile_count)
    return json_ok({"ok": True, "model": state})


async def service_start_handler(request):
    body = await read_json(request)
    sid = body.get("id") or request.query.get("id")
    if not sid:
        return json_ok({"ok": False, "error": "missing_id"}, status=400)
    result = services.start_service(sid)
    if not result.get("ok"):
        return json_ok(result, status=400)
    return json_ok(result)


async def service_stop_handler(request):
    body = await read_json(request)
    sid = body.get("id") or request.query.get("id")
    if not sid:
        return json_ok({"ok": False, "error": "missing_id"}, status=400)
    return json_ok(services.stop_service(sid))


async def service_logs_handler(request):
    sid = request.query.get("id")
    if not sid:
        return json_ok({"ok": False, "error": "missing_id"}, status=400)
    tail = int(request.query.get("tail") or 200)
    return json_ok(services.read_logs(sid, tail=tail))


async def service_panel_handler(request):
    return json_ok({"services": services.list_panel_state()})


def _is_local_peer(peer: str) -> bool:
    p = (peer or "").strip()
    return p in ("127.0.0.1", "::1") or p.startswith("::ffff:127.0.0.1")


async def stop_extras_handler(request):
    if not _is_local_peer(request.remote or ""):
        return json_ok({"ok": False, "error": "forbidden"}, status=403)
    services.stop_all_extras()
    return json_ok({"ok": True})


async def start_extras_handler(request):
    if not _is_local_peer(request.remote or ""):
        return json_ok({"ok": False, "error": "forbidden"}, status=403)
    services.autostart_extras()
    return json_ok({"ok": True})


async def identity_handler(request):
    return json_ok({"ga_root": str(DEFAULT_GA_ROOT), "app_dir": str(APP_DIR), "pid": os.getpid(),
                    "build_id": os.environ.get("GA_BUILD_ID", "")})


def _exit_bridge() -> None:
    with contextlib.suppress(Exception):
        services.stop_all_extras()
    threading.Timer(0.4, lambda: os._exit(0)).start()


async def bridge_exit_handler(request):
    if not _is_local_peer(request.remote or ""):
        return json_ok({"ok": False, "error": "forbidden"}, status=403)
    _exit_bridge()
    return json_ok({"ok": True})


async def e2e_next_turn_handler(request):
    token = _e2e_control_token()
    if token is None:
        raise web.HTTPNotFound()
    if not _is_local_peer(request.remote or ""):
        return json_ok({"ok": False, "error": "forbidden"}, status=403)
    if request.headers.get("X-GA-E2E-Token", "") != token:
        return json_ok({"ok": False, "error": "forbidden"}, status=403)
    try:
        body = await request.json()
        _set_e2e_next_turn(str(body.get("mode", "")))
    except (ValueError, TypeError, json.JSONDecodeError):
        return json_ok({"ok": False, "error": "mode must be empty"}, status=400)
    return json_ok({"ok": True, "mode": "empty"})


async def token_stats_handler(request):
    try:
        sys.path.insert(0, str(APP_DIR)) if str(APP_DIR) not in sys.path else None
        import cost_tracker
        trackers = cost_tracker.all_trackers()
        records = []
        for k, v in trackers.items():
            model = ''
            sid = k.replace('GA-', '')
            with manager.lock:
                sess = manager.sessions.get(sid)
            if sess and sess.agent:
                try: model = sess.agent.get_llm_name(model=True) or ''
                except Exception: pass
            records.append({"thread": k, "input": v.input, "output": v.output,
                            "cacheCreate": v.cache_create, "cacheRead": v.cache_read, "model": model})
    except Exception:
        records = []
    return json_ok({"records": records})


async def get_token_history_handler(request):
    try:
        import cost_tracker
        data = cost_tracker.aggregate_ledger()
        # Enrich session titles from manager
        for entry in data.get("history", []):
            sid = entry.get("sessionId", "")
            with manager.lock:
                sess = manager.sessions.get(sid)
            if sess and sess.title:
                entry["title"] = sess.title
            if not entry.get("model") and sess and sess.agent:
                try:
                    entry["model"] = sess.agent.get_llm_name(model=True) or ""
                except Exception:
                    pass
        return json_ok(data)
    except Exception:
        return json_ok({"history": [], "snap": {}})


async def subscription_portal_handler(request):
    manager.ensure_ga_import_path()
    try:
        import agentmain as am
    except Exception:
        am = None
    sp = getattr(am, "start_subscription_portal", None) if am else None
    if request.method == "GET":
        return json_ok({"available": bool(sp)})
    if not sp:
        return json_ok({"ok": False, "available": False}, status=404)
    sp()
    return json_ok({"ok": True})


def create_app():
    app = web.Application(middlewares=[cors_middleware], client_max_size=500 * 1024 * 1024)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/status", status_handler)
    app.router.add_get("/config", get_config_handler)
    app.router.add_post("/config", save_config_handler)
    app.router.add_get("/model-profiles", model_profiles_handler)
    app.router.add_post("/model-profiles", model_profiles_handler)
    app.router.add_put("/model-profiles/mixin/order", mixin_order_handler)
    app.router.add_post("/model-profiles/{id}/mixin", mixin_handler)
    app.router.add_delete("/model-profiles/{id}/mixin", mixin_handler)
    app.router.add_get("/model-profiles/{id}", model_profiles_handler)
    app.router.add_put("/model-profiles/{id}", model_profiles_handler)
    app.router.add_delete("/model-profiles/{id}", model_profiles_handler)
    app.router.add_get("/sessions", list_sessions_handler)
    app.router.add_post("/session/new", new_session_handler)
    app.router.add_get("/session/{sid}", get_session_handler)
    app.router.add_delete("/session/{sid}", delete_session_handler)
    app.router.add_patch("/session/{sid}", patch_session_handler)
    app.router.add_post("/session/{sid}/prompt", prompt_handler)
    app.router.add_get("/session/{sid}/messages", messages_handler)
    app.router.add_get("/session/{sid}/plan", plan_handler)
    app.router.add_post("/session/{sid}/cancel", cancel_handler)
    app.router.add_post("/session/{sid}/restore", restore_handler)
    app.router.add_post("/session/{sid}/model", session_model_handler)
    app.router.add_post("/path/open", path_open_handler)
    app.router.add_post("/upload", upload_handler)
    app.router.add_delete("/upload", upload_delete_handler)
    app.router.add_get("/upload/raw", upload_raw_handler)
    app.router.add_get("/token-stats", token_stats_handler)
    app.router.add_get("/token-history", get_token_history_handler)
    app.router.add_get("/subscription-portal", subscription_portal_handler)
    app.router.add_post("/subscription-portal", subscription_portal_handler)
    app.router.add_post("/services/start", service_start_handler)
    app.router.add_post("/services/stop", service_stop_handler)
    app.router.add_get("/services/logs", service_logs_handler)
    app.router.add_get("/services/panel", service_panel_handler)
    app.router.add_get("/services/mykey", mykey_get_handler)
    app.router.add_post("/services/mykey", mykey_save_handler)
    app.router.add_post("/memory/import", memory_import_handler)
    app.router.add_get("/services/conductor/model", conductor_model_get_handler)
    app.router.add_post("/services/conductor/model", conductor_model_save_handler)
    app.router.add_post("/services/stop-extras", stop_extras_handler)
    app.router.add_post("/services/start-extras", start_extras_handler)
    app.router.add_get("/services/identity", identity_handler)
    app.router.add_post("/services/bridge/exit", bridge_exit_handler)
    if _e2e_control_token() is not None:
        app.router.add_post("/__e2e__/next-turn", e2e_next_turn_handler)

    # Serve static frontend (desktop/static/)
    static_dir = APP_DIR / "desktop" / "static"

    async def index_handler(request):
        return web.FileResponse(
            static_dir / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    app.router.add_get("/", index_handler)
    app.router.add_static("/", static_dir, show_index=False)

    async def on_startup(app):
        hub.loop = asyncio.get_running_loop()
        services.autostart_extras()

    async def on_shutdown(app):
        services.stop_all_extras()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "14168"))
    bridge_print(f"GenericAgent Web2 bridge: http://{host}:{port}  ws://{host}:{port}/ws")
    web.run_app(create_app(), host=host, port=port, print=None)
