import asyncio, os, sys, threading
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent
from chatapp_common import AgentChatMixin, ensure_single_instance, public_access, redirect_log, require_runtime, split_text
from llmcore import mykeys

try:
    from wecom_aibot_sdk import WSClient, generate_req_id
except Exception:
    print("Please install wecom_aibot_sdk to use WeCom: pip install wecom_aibot_sdk")
    sys.exit(1)

agent = GeneraticAgent(); agent.verbose = False
BOT_ID = str(mykeys.get("wecom_bot_id", "") or "").strip()
SECRET = str(mykeys.get("wecom_secret", "") or "").strip()
WELCOME = str(mykeys.get("wecom_welcome_message", "") or "").strip()
ALLOWED = {str(x).strip() for x in mykeys.get("wecom_allowed_users", []) if str(x).strip()}
PROCESSED_IDS, USER_TASKS = deque(maxlen=1000), {}


class WeComApp(AgentChatMixin):
    label, source, split_limit = "WeCom", "wecom", 1200

    def __init__(self):
        super().__init__(agent, USER_TASKS)
        self.client, self.chat_frames = None, {}

    async def send_text(self, chat_id, content):
        if not self.client or chat_id not in self.chat_frames:
            if chat_id not in self.chat_frames:
                print(f"[WeCom] no frame found for chat: {chat_id}")
            return
        frame = self.chat_frames[chat_id]
        for part in split_text(content, self.split_limit):
            await self.client.reply_stream(frame, generate_req_id("stream"), part, finish=True)

    async def on_text(self, frame):
        try:
            body = frame.body if hasattr(frame, "body") else frame.get("body", frame) if isinstance(frame, dict) else {}
            if not isinstance(body, dict):
                return
            msg_id = body.get("msgid") or f"{body.get('chatid', '')}_{body.get('sendertime', '')}"
            if msg_id in PROCESSED_IDS:
                return
            PROCESSED_IDS.append(msg_id)
            from_info = body.get("from", {}) if isinstance(body.get("from", {}), dict) else {}
            sender_id = str(from_info.get("userid", "") or "unknown")
            chat_id = str(body.get("chatid", "") or sender_id)
            content = str((body.get("text", {}) or {}).get("content", "") or "").strip()
            if not content:
                return
            if not public_access(ALLOWED) and sender_id not in ALLOWED:
                print(f"[WeCom] unauthorized user: {sender_id}")
                return
            self.chat_frames[chat_id] = frame
            print(f"[WeCom] message from {sender_id}: {content}")
            if content.startswith("/"):
                return await self.handle_command(chat_id, content)
            asyncio.create_task(self.run_agent(chat_id, content))
        except Exception:
            import traceback
            print("[WeCom] handle_message error")
            traceback.print_exc()

    async def on_enter_chat(self, frame):
        if WELCOME and self.client:
            try:
                await self.client.reply_welcome(frame, {"msgtype": "text", "text": {"content": WELCOME}})
            except Exception as e:
                print(f"[WeCom] welcome error: {e}")

    async def on_connected(self):
        print("[WeCom] connected")

    async def on_authenticated(self):
        print("[WeCom] authenticated")

    async def on_disconnected(self, reason=""):
        print(f"[WeCom] disconnected: {reason}")

    async def on_error(self, error=None):
        print(f"[WeCom] error: {error}")

    async def start(self):
        self.client = WSClient(BOT_ID, SECRET, reconnect_interval=1000, max_reconnect_attempts=-1, heartbeat_interval=30000)
        for event, handler in {
            "connected": self.on_connected,
            "authenticated": self.on_authenticated,
            "disconnected": self.on_disconnected,
            "error": self.on_error,
            "message.text": self.on_text,
            "event.enter_chat": self.on_enter_chat,
        }.items():
            self.client.on(event, handler)
        print("[WeCom] bot starting...")
        await self.client.connect()
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    _LOCK_SOCK = ensure_single_instance(19529, "WeCom")
    require_runtime(agent, "WeCom", wecom_bot_id=BOT_ID, wecom_secret=SECRET)
    redirect_log(__file__, "wecomapp.log", "WeCom", ALLOWED)
    threading.Thread(target=agent.run, daemon=True).start()
    asyncio.run(WeComApp().start())
