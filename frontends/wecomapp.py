import asyncio, os, select, sys, threading, time, traceback
from collections import deque
from datetime import datetime
from typing import Any, Callable, Dict, Optional, TypedDict


class TurnContext(TypedDict, total=False):
    """Hook callback receives agent locals() — these are the keys we rely on."""
    exit_reason: Optional[str]
    response: Any
    summary: Optional[str]
    tool_calls: Optional[list]
    turn: int


TurnHookFn = Callable[[TurnContext], None]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent
from chatapp_common import (AgentChatMixin, FILE_HINT, build_done_text, clean_reply,
                            ensure_single_instance, extract_files, public_access,
                            redirect_log, require_runtime, split_text, strip_files)
from llmcore import mykeys

try:
    from wecom_aibot_sdk import WSClient, generate_req_id
except Exception:
    print("Please install wecom_aibot_sdk: pip install wecom_aibot_sdk")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────
BOT_ID    = str(mykeys.get("wecom_bot_id", "") or "").strip()
SECRET    = str(mykeys.get("wecom_secret", "") or "").strip()
WELCOME   = str(mykeys.get("wecom_welcome_message", "") or "").strip()
ALLOWED   = {str(x).strip() for x in mykeys.get("wecom_allowed_users", []) if str(x).strip()}
PORT      = 19531                # single-instance lock port
TEMP_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp")
MEDIA_DIR = os.path.join(TEMP_DIR, "media")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}


# ── Helpers ─────────────────────────────────────────────────────────
def _ts():
    return datetime.now().strftime("%H:%M:%S")

def _tprint(*a, **kw):
    kw.setdefault("file", sys.__stdout__)
    print(*a, **kw)
    if hasattr(sys.__stdout__, "flush"):
        sys.__stdout__.flush()

def _fmt_tool(tc):
    name = tc.get("tool_name", "?")
    args = {k: v for k, v in (tc.get("args") or {}).items() if not k.startswith("_")}
    return f"{name}({str(args)[:120]})"

# ── WeComApp ────────────────────────────────────────────────────────
class WeComApp(AgentChatMixin):
    label, source, split_limit = "WeCom", "wecom", 1200  # split_limit: wecom single-msg char cap

    def __init__(self, agent):
        self.agent = agent
        if not hasattr(agent, '_turn_end_hooks'):
            agent._turn_end_hooks = {}
        super().__init__(agent, {})
        self._allowed = ALLOWED
        self.client = None
        self.chat_frames = {}       # chat_id → latest frame (for reply)
        self._seen = deque(maxlen=1000)
        self._stats = {"received": 0, "completed": 0}

    # ── hook management ──────────────────────────────────────────────
    def _register_hook(self, key: str, fn: TurnHookFn) -> None:
        """Register a turn-end callback on the agent."""
        self.agent._turn_end_hooks[key] = fn

    def _unregister_hook(self, key: str) -> None:
        """Remove a turn-end callback."""
        self.agent._turn_end_hooks.pop(key, None)

    # ── frame accept: dedup → auth → register ───────────────────────
    def _accept(self, frame):
        """Parse incoming frame. Returns (body, sender_id, chat_id) or None."""
        body = frame.body if hasattr(frame, "body") else frame.get("body", frame) if isinstance(frame, dict) else {}
        msg_id = body.get("msgid") or f"{body.get('chatid', '')}_{body.get('sendertime', '')}_{id(frame)}"
        if msg_id in self._seen:
            return None
        self._seen.append(msg_id)
        sender_id = str((body.get("from") or {}).get("userid", "") or "unknown")
        chat_id = str(body.get("chatid", "") or sender_id)
        if not public_access(ALLOWED) and sender_id not in ALLOWED:
            print(f"[WeCom] unauthorized: {sender_id}")
            return None
        self.chat_frames[chat_id] = frame
        self._stats["received"] += 1
        return body, sender_id, chat_id

    async def _save_media(self, url, aes_key, default_name):
        """Download encrypted media → save to MEDIA_DIR → return local path."""
        os.makedirs(MEDIA_DIR, exist_ok=True)
        result = await self.client.download_file(url, aes_key or None)
        buf = result["buffer"]
        fname = result.get("filename") or default_name
        path = os.path.join(MEDIA_DIR, fname)
        with open(path, "wb") as f:
            f.write(buf)
        _tprint(f"[{_ts()}] 💾 Saved: {path} ({len(buf)} bytes)")
        return path

    # ── send ────────────────────────────────────────────────────────
    async def send_text(self, chat_id, content, **_):
        if not self.client or chat_id not in self.chat_frames:
            return
        frame = self.chat_frames[chat_id]
        for part in split_text(content, self.split_limit):
            await self.client.reply_stream(frame, generate_req_id("stream"), part, finish=True)

    async def send_media(self, chat_id, file_path):
        if not self.client or not os.path.isfile(file_path):
            return
        ext = os.path.splitext(file_path)[1].lower()
        media_type = "image" if ext in IMAGE_EXTS else "file"
        with open(file_path, "rb") as f:
            data = f.read()
        try:
            result = await self.client.upload_media(data, type=media_type, filename=os.path.basename(file_path))
            frame = self.chat_frames.get(chat_id)
            if frame:
                await self.client.reply_media(frame, media_type, result["media_id"])
            else:
                await self.client.send_media_message(chat_id, media_type, result["media_id"])
            _tprint(f"[{_ts()}] 📤 Sent {media_type}: {os.path.basename(file_path)}")
        except Exception as e:
            print(f"[WeCom] send_media error: {e}")
            await self.send_text(chat_id, f"📎 {os.path.basename(file_path)}（发送失败: {e}）")

    async def send_done(self, chat_id, raw_text):
        """Send final result: text + extracted file attachments."""
        files = extract_files(raw_text)
        if not files:
            return await self.send_text(chat_id, build_done_text(raw_text))
        clean = clean_reply(strip_files(raw_text))
        if clean and clean != "...":
            await self.send_text(chat_id, clean)
        for fp in files:
            if not os.path.isabs(fp) and not os.path.isfile(fp):
                resolved = os.path.join(TEMP_DIR, fp)
                if os.path.isfile(resolved):
                    fp = resolved
            await self.send_media(chat_id, fp)

    # ── agent execution (single-channel via turn hook) ──────────────
    async def run_agent(self, chat_id, text, **_):
        state = {"running": True}
        self.user_tasks[chat_id] = state
        done_event = threading.Event()
        result = {}
        loop = asyncio.get_running_loop()
        hook_key = f"wecom_{chat_id}"  # namespace: wecom_ + chat_id, matches _turn_end_hooks convention

        def _on_turn(ctx):
            """Turn-end callback injected into agent. ctx = locals() from ga.py."""
            try:
                if ctx.get("exit_reason"):
                    resp = ctx.get("response")
                    result["raw"] = resp.content if hasattr(resp, "content") else str(resp)
                    result["summary"] = ctx.get("summary")
                    done_event.set()
                    return
                summary = ctx.get("summary")
                if not summary:
                    return
                turn = ctx.get("turn", "?")
                tools = ctx.get("tool_calls") or []
                parts = [f"⏳ Turn {turn}: {summary}"]
                if tools:
                    parts.append(f"🛠 {', '.join(_fmt_tool(tc) for tc in tools[:3])}")
                _tprint(f"[{_ts()}] {parts[0]}")
                asyncio.run_coroutine_threadsafe(self.send_text(chat_id, "\n".join(parts)), loop)
            except Exception as e:
                print(f"[WeCom hook] {e}")
                traceback.print_exc()

        try:
            await self.send_text(chat_id, "🤔 思考中...")
            self._register_hook(hook_key, _on_turn)
            self.agent.put_task(f"{FILE_HINT}\n\n{text}", source=self.source)

            # Wait for: hook signals done / user stops / agent crashes
            t0 = time.time()
            while state["running"] and not done_event.is_set():
                await asyncio.sleep(1)
                elapsed = time.time() - t0
                if elapsed > 10 and not self.agent.is_running:
                    await asyncio.sleep(3)  # grace period for hook delivery
                    if not done_event.is_set():
                        break

            if result.get("raw") is not None:
                self._stats["completed"] += 1
                await self.send_done(chat_id, result["raw"])
                label = result.get("summary") or f'{len(result["raw"])} 字'
                _tprint(f"[{_ts()}] ✅ Done ({chat_id}) — {label}")
            elif not state["running"]:
                _tprint(f"[{_ts()}] ⏹️ 停止 ({chat_id})")
                await self.send_text(chat_id, "⏹️ 已停止")
            else:
                _tprint(f"[{_ts()}] ⚠️ 异常退出 ({chat_id})")
                await self.send_text(chat_id, "⚠️ Agent 异常退出，请重试")
        except Exception as e:
            traceback.print_exc()
            await self.send_text(chat_id, f"❌ 错误: {e}")
        finally:
            self._unregister_hook(hook_key)
            self.user_tasks.pop(chat_id, None)

    # ── message handlers ────────────────────────────────────────────
    async def on_text(self, frame):
        parsed = self._accept(frame)
        if not parsed:
            return
        body, sender_id, chat_id = parsed
        content = str((body.get("text", {}) or {}).get("content", "") or "").strip()
        if not content:
            return
        _tprint(f"[{_ts()}] 📩 {sender_id}: {content}")
        if content.startswith("/"):
            _tprint(f"[{_ts()}] 🔧 命令 {content} from {sender_id}")
            return await self.handle_command(chat_id, content)
        asyncio.create_task(self.run_agent(chat_id, content))

    async def _on_media(self, frame, key, icon):
        """Common handler for image/file messages."""
        parsed = self._accept(frame)
        if not parsed:
            return
        body, sender_id, chat_id = parsed
        info = body.get(key) or {}
        url = info.get("url", "")
        if not url:
            return
        fname = info.get("file_name") or info.get("filename") or ""
        msgid = body.get("msgid", "x")[:16]
        default = f"img_{msgid}.jpg" if key == "image" else (fname or f"file_{msgid}")
        try:
            _tprint(f"[{_ts()}] {icon} {key.title()} from {sender_id}" + (f": {fname}" if fname else ""))
            path = await self._save_media(url, info.get("aeskey", ""), default)
            label = "一张图片" if key == "image" else f"文件 {os.path.basename(path)}"
            asyncio.create_task(self.run_agent(chat_id, f"[用户发送了{label}，已保存到: {path}]"))
        except Exception as e:
            print(f"[WeCom] on_{key} error: {e}")
            await self.send_text(chat_id, f"❌ {key}处理失败: {e}")

    async def on_image(self, frame):
        await self._on_media(frame, "image", "🖼️")

    async def on_file(self, frame):
        await self._on_media(frame, "file", "📎")

    # ── lifecycle ───────────────────────────────────────────────────
    async def on_enter_chat(self, frame):
        if WELCOME and self.client:
            try:
                await self.client.reply_welcome(frame, {"msgtype": "text", "text": {"content": WELCOME}})
            except Exception as e:
                print(f"[WeCom] welcome error: {e}")

    async def on_connected(self, *_):     _tprint("[WeCom] connected")
    async def on_authenticated(self, *_): _tprint("[WeCom] authenticated, 等待消息中...\n")
    async def on_disconnected(self, *_):  _tprint("[WeCom] disconnected")
    async def on_error(self, frame):     _tprint(f"[WeCom] error: {frame}")

    # ── Terminal CLI (runs in background thread) ─────────────────────
    def _terminal_loop(self):
        """Blocking CLI loop — run in a daemon thread."""
        while True:
            try:
                if not select.select([sys.stdin], [], [], 1.0)[0]:
                    continue
                cmd = sys.stdin.readline().strip().lower()
            except Exception:
                break
            if not cmd:
                continue
            if cmd == "help":
                _tprint("  status        — 查看状态")
                _tprint("  stop [user]   — 停止任务（多任务时需指定 user）")
                _tprint("  exit          — 退出进程")
            elif cmd == "status":
                _tprint(f"[{_ts()}] 📊 收到 {self._stats['received']} 条 | 完成 {self._stats['completed']} 条 | 活跃 {len(self.user_tasks)}")
                for uid, st in self.user_tasks.items():
                    _tprint(f"  ├ {uid}: running={st.get('running')}")
                _tprint(f"  Agent running: {self.agent.is_running} | 允许: {self._allowed or '全部'}")
            elif cmd.startswith("stop"):
                parts = cmd.split(None, 1)
                tasks = self.user_tasks
                if not tasks:
                    _tprint("  没有活跃任务")
                elif len(parts) > 1:
                    uid = parts[1]
                    if uid in tasks:
                        tasks[uid]["running"] = False
                        _tprint(f"  ⏹️ 已停止 {uid}")
                    else:
                        _tprint(f"  未找到: {uid}")
                elif len(tasks) == 1:
                    uid = next(iter(tasks))
                    tasks[uid]["running"] = False
                    _tprint(f"  ⏹️ 已停止 {uid}")
                else:
                    _tprint("  多个任务，请指定: stop <user_id>")
                    for uid in tasks:
                        _tprint(f"  ├ {uid}")
            elif cmd == "exit":
                _tprint(f"[{_ts()}] 👋 退出...")
                os._exit(0)
            else:
                _tprint("  可用命令: help | status | stop | exit")

    async def start(self, client=None):
        self.client = client or WSClient(BOT_ID, SECRET, reconnect_interval=1000,
                                         max_reconnect_attempts=-1, heartbeat_interval=30000)
        for ev, fn in {
            "connected": self.on_connected, "authenticated": self.on_authenticated,
            "disconnected": self.on_disconnected, "error": self.on_error,
            "message.text": self.on_text, "message.image": self.on_image,
            "message.file": self.on_file, "event.enter_chat": self.on_enter_chat,
        }.items():
            self.client.on(ev, fn)
        _tprint("[WeCom] starting ...")
        await self.client.connect()
        while True:
            await asyncio.sleep(1)


# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent = GeneraticAgent(); agent.verbose = False
    _LOCK = ensure_single_instance(PORT, "WeCom")
    require_runtime(agent, "WeCom", wecom_bot_id=BOT_ID, wecom_secret=SECRET)
    redirect_log(__file__, "wecomapp.log", "WeCom", ALLOWED)
    _tprint("\n═══════════════════════════════════════════")
    _tprint("  企业微信 Agent  (长连接模式)")
    _tprint(f"  端口锁: {PORT} | 允许用户: {ALLOWED or '全部'}")
    _tprint("═══════════════════════════════════════════")
    _tprint("  终端命令:  help | status | stop | exit")

    app = WeComApp(agent)
    threading.Thread(target=agent.run, daemon=True).start()
    threading.Thread(target=app._terminal_loop, daemon=True).start()
    asyncio.run(app.start())