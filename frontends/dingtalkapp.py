import asyncio, json, os, sys, threading, time
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent
from chatapp_common import AgentChatMixin, ensure_single_instance, public_access, redirect_log, require_runtime, split_text
from llmcore import mykeys

try:
    from dingtalk_stream import AckMessage, CallbackHandler, Credential, DingTalkStreamClient
    from dingtalk_stream.chatbot import ChatbotMessage
except Exception:
    print("Please install dingtalk-stream to use DingTalk: pip install dingtalk-stream")
    sys.exit(1)

agent = GeneraticAgent(); agent.verbose = False
CLIENT_ID = str(mykeys.get("dingtalk_client_id", "") or "").strip()
CLIENT_SECRET = str(mykeys.get("dingtalk_client_secret", "") or "").strip()
ALLOWED = {str(x).strip() for x in mykeys.get("dingtalk_allowed_users", []) if str(x).strip()}
USER_TASKS = {}


class DingTalkApp(AgentChatMixin):
    label, source, split_limit = "DingTalk", "dingtalk", 1800

    def __init__(self):
        super().__init__(agent, USER_TASKS)
        self.client, self.access_token, self.token_expiry, self.background_tasks = None, None, 0, set()

    async def _get_access_token(self):
        if self.access_token and time.time() < self.token_expiry:
            return self.access_token

        def _fetch():
            resp = requests.post("https://api.dingtalk.com/v1.0/oauth2/accessToken", json={"appKey": CLIENT_ID, "appSecret": CLIENT_SECRET}, timeout=20)
            resp.raise_for_status()
            return resp.json()

        try:
            data = await asyncio.to_thread(_fetch)
            self.access_token = data.get("accessToken")
            self.token_expiry = time.time() + int(data.get("expireIn", 7200)) - 60
            return self.access_token
        except Exception as e:
            print(f"[DingTalk] token error: {e}")
            return None

    async def _send_batch_message(self, chat_id, msg_key, msg_param):
        token = await self._get_access_token()
        if not token:
            return False
        headers = {"x-acs-dingtalk-access-token": token}
        if chat_id.startswith("group:"):
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            payload = {"robotCode": CLIENT_ID, "openConversationId": chat_id[6:], "msgKey": msg_key, "msgParam": json.dumps(msg_param, ensure_ascii=False)}
        else:
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            payload = {"robotCode": CLIENT_ID, "userIds": [chat_id], "msgKey": msg_key, "msgParam": json.dumps(msg_param, ensure_ascii=False)}

        def _post():
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            body = resp.text
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {body[:300]}")
            result = resp.json() if "json" in resp.headers.get("content-type", "") else {}
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                raise RuntimeError(f"API errcode={errcode}: {body[:300]}")
            return True

        try:
            return await asyncio.to_thread(_post)
        except Exception as e:
            print(f"[DingTalk] send error: {e}")
            return False

    async def send_text(self, chat_id, content):
        for part in split_text(content, self.split_limit):
            await self._send_batch_message(chat_id, "sampleMarkdown", {"text": part, "title": "Agent Reply"})

    async def on_message(self, content, sender_id, sender_name, conversation_type=None, conversation_id=None):
        try:
            if not content:
                return
            if not public_access(ALLOWED) and sender_id not in ALLOWED:
                print(f"[DingTalk] unauthorized user: {sender_id}")
                return
            is_group = conversation_type == "2" and conversation_id
            chat_id = f"group:{conversation_id}" if is_group else sender_id
            print(f"[DingTalk] message from {sender_name} ({sender_id}): {content}")
            if content.startswith("/"):
                return await self.handle_command(chat_id, content)
            task = asyncio.create_task(self.run_agent(chat_id, content))
            self.background_tasks.add(task)
            task.add_done_callback(self.background_tasks.discard)
        except Exception:
            import traceback
            print("[DingTalk] handle_message error")
            traceback.print_exc()

    async def start(self):
        self.client = DingTalkStreamClient(Credential(CLIENT_ID, CLIENT_SECRET))
        self.client.register_callback_handler(ChatbotMessage.TOPIC, _DingTalkHandler(self))
        print("[DingTalk] bot starting...")
        while True:
            try:
                await self.client.start()
            except Exception as e:
                print(f"[DingTalk] stream error: {e}")
            print("[DingTalk] reconnect in 5s...")
            await asyncio.sleep(5)


class _DingTalkHandler(CallbackHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    async def process(self, message):
        try:
            chatbot_msg = ChatbotMessage.from_dict(message.data)
            text = getattr(getattr(chatbot_msg, "text", None), "content", "") or ""
            extensions = getattr(chatbot_msg, "extensions", None) or {}
            recognition = ((extensions.get("content") or {}).get("recognition") or "").strip() if isinstance(extensions, dict) else ""
            if not (text := text.strip()):
                text = recognition or str((message.data.get("text", {}) or {}).get("content", "") or "").strip()
            sender_id = str(getattr(chatbot_msg, "sender_staff_id", None) or getattr(chatbot_msg, "sender_id", None) or "unknown")
            sender_name = getattr(chatbot_msg, "sender_nick", None) or "Unknown"
            await self.app.on_message(text, sender_id, sender_name, message.data.get("conversationType"), message.data.get("conversationId") or message.data.get("openConversationId"))
        except Exception as e:
            print(f"[DingTalk] callback error: {e}")
        return AckMessage.STATUS_OK, "OK"


if __name__ == "__main__":
    _LOCK_SOCK = ensure_single_instance(19530, "DingTalk")
    require_runtime(agent, "DingTalk", dingtalk_client_id=CLIENT_ID, dingtalk_client_secret=CLIENT_SECRET)
    redirect_log(__file__, "dingtalkapp.log", "DingTalk", ALLOWED)
    threading.Thread(target=agent.run, daemon=True).start()
    asyncio.run(DingTalkApp().start())
