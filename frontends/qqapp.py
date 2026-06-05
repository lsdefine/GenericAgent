import asyncio, os, re, sys, threading, time, uuid
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp')
from agentmain import GeneraticAgent
from chatapp_common import AgentChatMixin, ensure_single_instance, public_access, redirect_log, require_runtime, split_text, extract_files, strip_files, clean_reply
from llmcore import mykeys
import puburl

try:
    import botpy
    from botpy.message import C2CMessage, GroupMessage
except Exception:
    print("Please install qq-botpy to use QQ module: pip install qq-botpy")
    sys.exit(1)

agent = GeneraticAgent(); agent.verbose = False
APP_ID = str(mykeys.get("qq_app_id", "") or "").strip()
APP_SECRET = str(mykeys.get("qq_app_secret", "") or "").strip()
ALLOWED = {str(x).strip() for x in mykeys.get("qq_allowed_users", []) if str(x).strip()}
PROCESSED_IDS, USER_TASKS = deque(maxlen=1000), {}
SEQ_LOCK, MSG_SEQ = threading.Lock(), 1


def _next_msg_seq():
    global MSG_SEQ
    with SEQ_LOCK:
        MSG_SEQ += 1
        return MSG_SEQ


# QQ 出站富媒体类型：1=图片 2=视频 3=语音 4=文件（按后缀判定）
_EXT_FILE_TYPE = {
    ".jpg": 1, ".jpeg": 1, ".png": 1, ".gif": 1, ".bmp": 1, ".webp": 1,
    ".mp4": 2, ".mov": 2, ".avi": 2, ".mkv": 2,
    ".silk": 3, ".amr": 3, ".mp3": 3, ".wav": 3, ".m4a": 3,
}


def _qq_file_type(path):
    return _EXT_FILE_TYPE.get(os.path.splitext(path)[1].lower(), 4)


# QQ 附件 content_type: 1=图片 2=视频 3=语音 4=文件；不同消息类型字段可能不全，按后缀/url 兜底
def _guess_ext(att, kind):
    fn = getattr(att, "filename", "") or ""
    ext = os.path.splitext(fn)[1]
    if ext:
        return ext
    url = (getattr(att, "url", "") or "").split("?")[0]
    ext = os.path.splitext(url)[1]
    if ext:
        return ext
    ct = getattr(att, "content_type", None)
    name = str(ct).lower() if ct is not None else ""
    for key, e in (("image", ".jpg"), ("voice", ".silk"), ("audio", ".silk"), ("video", ".mp4")):
        if key in name:
            return e
    return {1: ".jpg", 2: ".mp4", 3: ".silk", 4: ".dat"}.get(ct, ".dat")


def _kind_label(att):
    ct = getattr(att, "content_type", None)
    name = str(ct).lower() if ct is not None else ""
    if ct == 1 or "image" in name:
        return "图片"
    if ct == 2 or "video" in name:
        return "视频"
    if ct == 3 or "voice" in name or "audio" in name:
        return "语音"
    return "文件"


async def _download_attachments(data):
    """下载消息附件到 temp/，返回 [(kind_label, 'temp/xxx'), ...]。失败的跳过。"""
    atts = getattr(data, "attachments", None) or []
    if not atts:
        return []
    import aiohttp
    os.makedirs(_TEMP_DIR, exist_ok=True)
    saved = []
    async with aiohttp.ClientSession() as sess:
        for att in atts:
            url = getattr(att, "url", "") or ""
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("http://"):
                url = "https://" + url[len("http://"):]
            kind = _kind_label(att)
            ext = _guess_ext(att, kind)
            fname = f"qq_{uuid.uuid4().hex[:12]}{ext}"
            fpath = os.path.join(_TEMP_DIR, fname)
            try:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    body = await resp.read()
                with open(fpath, "wb") as f:
                    f.write(body)
                saved.append((kind, f"temp/{fname}"))
                print(f"[QQ] downloaded {kind} -> temp/{fname} ({len(body)} bytes)")
            except Exception as e:
                print(f"[QQ] download failed {url}: {e}")
    return saved


def _build_prompt(text, attachments):
    """把文本与附件路径合并成给 agent 的 prompt。"""
    if not attachments:
        return text
    lines = []
    for kind, path in attachments:
        if kind == "语音":
            lines.append(f"[TIPS] 收到{kind}文件 {path}（QQ 语音通常为 silk 编码，需先转码再处理）")
        elif kind == "图片":
            lines.append(f"[TIPS] 收到{kind} {path}（可用 vision 查看）")
        else:
            lines.append(f"[TIPS] 收到{kind} {path}")
    head = "\n".join(lines)
    if text:
        return f"{head}\n{text}"
    return f"{head}\n请查看后等待下一步指令。"



def _build_intents():
    try:
        return botpy.Intents(public_messages=True, direct_message=True)
    except Exception:
        intents = botpy.Intents.none() if hasattr(botpy.Intents, "none") else botpy.Intents()
        for attr in ("public_messages", "public_guild_messages", "direct_message", "direct_messages", "c2c_message", "c2c_messages", "group_at_message", "group_at_messages"):
            if hasattr(intents, attr):
                try:
                    setattr(intents, attr, True)
                except Exception:
                    pass
        return intents


def _make_bot_class(app):
    class QQBot(botpy.Client):
        def __init__(self):
            super().__init__(intents=_build_intents(), ext_handlers=False)

        async def on_ready(self):
            print(f"[QQ] bot ready: {getattr(getattr(self, 'robot', None), 'name', 'QQBot')}")

        async def on_c2c_message_create(self, message: C2CMessage):
            await app.on_message(message, is_group=False)

        async def on_group_at_message_create(self, message: GroupMessage):
            await app.on_message(message, is_group=True)

        async def on_direct_message_create(self, message):
            await app.on_message(message, is_group=False)

    return QQBot


class QQApp(AgentChatMixin):
    label, source, split_limit = "QQ", "qq", 1500

    def __init__(self):
        super().__init__(agent, USER_TASKS)
        self.client = None

    async def send_text(self, chat_id, content, *, msg_id=None, is_group=False):
        if not self.client:
            return
        api = self.client.api.post_group_message if is_group else self.client.api.post_c2c_message
        key = "group_openid" if is_group else "openid"
        for part in split_text(content, self.split_limit):
            seq = _next_msg_seq()
            try:
                await api(**{key: chat_id, "msg_type": 2, "markdown": {"content": part}, "msg_id": msg_id, "msg_seq": seq})
            except Exception:
                await api(**{key: chat_id, "msg_type": 0, "content": part, "msg_id": msg_id, "msg_seq": seq})

    async def send_done(self, chat_id, raw_text, *, msg_id=None, is_group=False):
        # 先发清理后的文本（去掉 [FILE:] 标记），再把文件作为富媒体发出
        files = [p for p in extract_files(raw_text) if os.path.exists(p)]
        body = strip_files(clean_reply(raw_text))
        if body and body != "...":
            await self.send_text(chat_id, body, msg_id=msg_id, is_group=is_group)
        for path in files:
            await self._send_file(chat_id, path, msg_id=msg_id, is_group=is_group)

    async def _send_file(self, chat_id, path, *, msg_id=None, is_group=False):
        """QQ 富媒体出站：本地文件 -> 公网URL -> 腾讯反向拉取。失败则降级为文本提示。"""
        name = os.path.basename(path)
        file_type = _qq_file_type(path)
        try:
            url = await asyncio.to_thread(puburl.publish, path)
            if not url:
                raise RuntimeError("无法生成公网URL（隧道未就绪）")
            upload = self.client.api.post_group_file if is_group else self.client.api.post_c2c_file
            send = self.client.api.post_group_message if is_group else self.client.api.post_c2c_message
            key = "group_openid" if is_group else "openid"
            media = await upload(**{key: chat_id, "file_type": file_type, "url": url})
            await send(**{key: chat_id, "msg_type": 7, "media": media,
                          "msg_id": msg_id, "msg_seq": _next_msg_seq()})
            print(f"[QQ] send_file ok ({name}, type={file_type}) via {url}")
        except Exception as e:
            print(f"[QQ] send_file failed ({name}): {e}")
            await self.send_text(chat_id, f"⚠️ 文件「{name}」发送失败：{e}", msg_id=msg_id, is_group=is_group)

    async def on_message(self, data, is_group=False):
        try:
            msg_id = getattr(data, "id", None)
            if msg_id in PROCESSED_IDS:
                return
            PROCESSED_IDS.append(msg_id)
            content = (getattr(data, "content", "") or "").strip()
            attachments = await _download_attachments(data)
            if not content and not attachments:
                return
            author = getattr(data, "author", None)
            user_id = str(getattr(author, "member_openid" if is_group else "user_openid", "") or getattr(author, "id", "") or "unknown")
            chat_id = str(getattr(data, "group_openid", "") or user_id) if is_group else user_id
            if not public_access(ALLOWED) and user_id not in ALLOWED:
                print(f"[QQ] unauthorized user: {user_id}")
                return
            print(f"[QQ] message from {user_id} ({'group' if is_group else 'c2c'}): {content!r} +{len(attachments)} attach")
            if content.startswith("/"):
                return await self.handle_command(chat_id, content, msg_id=msg_id, is_group=is_group)
            prompt = _build_prompt(content, attachments)
            asyncio.create_task(self.run_agent(chat_id, prompt, msg_id=msg_id, is_group=is_group))
        except Exception:
            import traceback
            print("[QQ] handle_message error")
            traceback.print_exc()

    async def start(self):
        self.client = _make_bot_class(self)()
        delay, max_delay = 5, 300
        while True:
            started_at = time.monotonic()
            try:
                print(f"[QQ] bot starting... {time.strftime('%m-%d %H:%M')}")
                await self.client.start(appid=APP_ID, secret=APP_SECRET)
            except Exception as e:
                print(f"[QQ] bot error: {e}")
            if time.monotonic() - started_at >= 60:
                delay = 5
            print(f"[QQ] reconnect in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


if __name__ == "__main__":
    _LOCK_SOCK = ensure_single_instance(19528, "QQ")
    require_runtime(agent, "QQ", qq_app_id=APP_ID, qq_app_secret=APP_SECRET)
    redirect_log(__file__, "qqapp.log", "QQ", ALLOWED)
    threading.Thread(target=agent.run, daemon=True).start()
    asyncio.run(QQApp().start())
