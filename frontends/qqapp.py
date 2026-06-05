import asyncio, os, re, sys, threading, time, uuid
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp')
_INBOX_DIR = os.path.join(_TEMP_DIR, 'qq_inbox')  # 入站附件独立存放，便于清理
_INBOX_TTL = 86400  # 入站附件保留秒数，超过自动清理
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
# 缓冲区：用户发来的附件先暂存，等用户发文字指令再合并触发模型
# {chat_id: [(kind_label, 'temp/qq_inbox/xxx'), ...]}
PENDING = {}
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


def _is_inbound(path):
    """判断路径是否落在入站目录 temp/qq_inbox/ 内（兼容相对/绝对路径）。"""
    try:
        ap = os.path.abspath(path)
        base = os.path.abspath(_INBOX_DIR)
        return os.path.commonpath([ap, base]) == base
    except (ValueError, OSError):
        return False


def _cleanup_inbox():
    """清理 temp/qq_inbox/ 下超过 TTL 的旧附件。"""
    now = time.time()
    try:
        for name in os.listdir(_INBOX_DIR):
            p = os.path.join(_INBOX_DIR, name)
            try:
                if now - os.path.getmtime(p) > _INBOX_TTL:
                    os.remove(p)
            except OSError:
                pass
    except FileNotFoundError:
        pass


async def _download_attachments(data):
    """下载消息附件到 temp/qq_inbox/，返回 [(kind_label, 'temp/qq_inbox/xxx'), ...]。失败的跳过。"""
    atts = getattr(data, "attachments", None) or []
    if not atts:
        return []
    import aiohttp
    os.makedirs(_INBOX_DIR, exist_ok=True)
    _cleanup_inbox()
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
            fpath = os.path.join(_INBOX_DIR, fname)
            try:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    body = await resp.read()
                with open(fpath, "wb") as f:
                    f.write(body)
                saved.append((kind, f"temp/qq_inbox/{fname}"))
                print(f"[QQ] downloaded {kind} -> temp/qq_inbox/{fname} ({len(body)} bytes)")
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
    stream_turns = True  # 逐 turn 实时心跳：每个 turn 跑完即推送该 turn 日志

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
        files = [p for p in extract_files(raw_text)
                 if os.path.exists(p) and not _is_inbound(p)]
        body = strip_files(clean_reply(raw_text))
        if body and body != "...":
            await self.send_text(chat_id, body, msg_id=msg_id, is_group=is_group)
        for path in files:
            await self._send_file(chat_id, path, msg_id=msg_id, is_group=is_group)

    async def send_done_files(self, chat_id, raw_text, *, msg_id=None, is_group=False):
        # 流式逐 turn 模式收尾：turn 日志已实时推送完毕，这里只补发生成的文件，
        # 不再重复汇总全部 turn 文本。
        files = [p for p in extract_files(raw_text)
                 if os.path.exists(p) and not _is_inbound(p)]
        for path in files:
            await self._send_file(chat_id, path, msg_id=msg_id, is_group=is_group)

    async def _send_file(self, chat_id, path, *, msg_id=None, is_group=False):
        """QQ 富媒体出站：本地文件 -> 公网URL -> 腾讯反向拉取。

        腾讯反向拉取对文件体积有上限（实测 1MB 文档可发，2.9MB pdf / 11.5MB docx
        会被拒，报 "download file error"）。原生富媒体发送失败时，降级为把公网下载
        链接作为文本发出——该链接经 cloudflared 隧道直连本地文件服务，不受腾讯体积
        限制，用户可在 TTL（默认 1 小时）内手动下载。"""
        name = os.path.basename(path)
        file_type = _qq_file_type(path)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        url = None
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
            print(f"[QQ] send_file ok ({name}, type={file_type}, {size}B) via {url}")
        except Exception as e:
            print(f"[QQ] send_file failed ({name}, {size}B): {e}")
            if url:
                # 降级：原生富媒体被腾讯拒收（多见于大文件），改发公网下载链接
                mb = size / 1024 / 1024
                tip = (f"📎 文件「{name}」（{mb:.1f}MB）超出 QQ 直传体积限制，"
                       f"已转为下载链接（1 小时内有效）：\n{url}")
                await self.send_text(chat_id, tip, msg_id=msg_id, is_group=is_group)
                print(f"[QQ] send_file degraded to link ({name}) via {url}")
            else:
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
                if content.strip().lower() == "/clearfiles":
                    pend = PENDING.pop(chat_id, [])
                    if pend:
                        kinds = "、".join(sorted({k for k, _ in pend}))
                        tip = f"🗑️ 已撤销缓存的 {len(pend)} 个附件（{kinds}）。"
                    else:
                        tip = "📭 当前没有缓存的附件。"
                    return await self.send_text(chat_id, tip, msg_id=msg_id, is_group=is_group)
                return await self.handle_command(chat_id, content, msg_id=msg_id, is_group=is_group)
            # 1) 先把本条消息的附件存入缓冲（不立即触发模型）
            if attachments:
                PENDING.setdefault(chat_id, []).extend(attachments)
            # 2) 并发保护：该会话已有任务在跑，拒绝新指令，提示可 /stop 中断
            if chat_id in USER_TASKS:
                if attachments:
                    pend = PENDING.get(chat_id, [])
                    kinds = "、".join(sorted({k for k, _ in pend}))
                    tip = (f"📥 已收到本条 {len(attachments)} 个附件并缓存，当前共缓存 {len(pend)} 个（{kinds}），无需重发。"
                           f"\n⏳ 但当前正在处理上一条指令，附件会在你下达新指令时一并带上。"
                           f"发送 /stop 可中断当前任务后立即下达，发送 /clearfiles 可撤销已缓存的附件。")
                else:
                    tip = "⏳ 正在处理上一条指令。发送 /stop 可中断后再下达新指令。"
                return await self.send_text(chat_id, tip, msg_id=msg_id, is_group=is_group)
            # 3) 只有附件、没有文字指令 → 回执并等待文字
            if not content:
                pend = PENDING.get(chat_id, [])
                if pend:
                    kinds = "、".join(sorted({k for k, _ in pend}))
                    return await self.send_text(
                        chat_id,
                        f"📥 已收到 {len(pend)} 个附件（{kinds}），已缓存。请发送文字说明要做什么，我再开始处理。"
                        f"\n发送 /clearfiles 可撤销已缓存的附件。",
                        msg_id=msg_id, is_group=is_group)
                return
            # 4) 有文字指令 → 合并缓冲的附件一起触发，清空缓冲
            buffered = PENDING.pop(chat_id, [])
            prompt = _build_prompt(content, buffered)
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
