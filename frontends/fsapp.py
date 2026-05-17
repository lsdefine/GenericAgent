import glob, json, os, queue as Q, re, sys, threading, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)
from agentmain import GeneraticAgent, GenericAgentRuntime
from frontends.chatapp_common import format_restore
from frontends.continue_cmd import handle_frontend_command as handle_continue_frontend, reset_conversation
from llmcore import mykeys

import traceback
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

_TAG_PATS = [r"<" + t + r">.*?</" + t + r">" for t in ("thinking", "summary", "tool_use", "file_content")]
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
_AUDIO_EXTS = {".opus", ".mp3", ".wav", ".m4a", ".aac"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_FILE_TYPE_MAP = {
    ".opus": "opus",
    ".mp4": "mp4",
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "doc",
    ".xls": "xls",
    ".xlsx": "xls",
    ".ppt": "ppt",
    ".pptx": "ppt",
}
_MSG_TYPE_MAP = {"image": "[image]", "audio": "[audio]", "file": "[file]", "media": "[media]", "sticker": "[sticker]"}

TEMP_DIR = os.path.join(PROJECT_ROOT, "temp")
MEDIA_DIR = os.path.join(TEMP_DIR, "feishu_media")
os.makedirs(MEDIA_DIR, exist_ok=True)


_TRUNC_TAIL = 300  # 截断兜底时保留原文尾部字符数


def _clean(text):
    for pat in _TAG_PATS:
        text = re.sub(pat, "", text or "", flags=re.DOTALL)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_files(text):
    return re.findall(r"\[FILE:([^\]]+)\]", text or "")


def _strip_files(text):
    return re.sub(r"\[FILE:[^\]]+\]", "", text or "").strip()


def _display_text(text):
    cleaned = _strip_files(_clean(text))
    if cleaned:
        return cleaned
    tail = (text or "").strip()[-_TRUNC_TAIL:]
    return "（无文本输出）" + (f"\n…{tail}" if tail else "")


def _to_allowed_set(value):
    if value is None:
        return set()
    if isinstance(value, str):
        value = [value]
    return {str(x).strip() for x in value if str(x).strip()}


def _parse_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _extract_share_card_content(content_json, msg_type):
    parts = []
    if msg_type == "share_chat":
        parts.append(f"[shared chat: {content_json.get('chat_id', '')}]")
    elif msg_type == "share_user":
        parts.append(f"[shared user: {content_json.get('user_id', '')}]")
    elif msg_type == "interactive":
        parts.extend(_extract_interactive_content(content_json))
    elif msg_type == "share_calendar_event":
        parts.append(f"[shared calendar event: {content_json.get('event_key', '')}]")
    elif msg_type == "system":
        parts.append("[system message]")
    elif msg_type == "merge_forward":
        parts.append("[merged forward messages]")
    return "\n".join([p for p in parts if p]).strip() or f"[{msg_type}]"


def _extract_interactive_content(content):
    parts = []
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            return [content] if content.strip() else []
    if not isinstance(content, dict):
        return parts
    title = content.get("title")
    if isinstance(title, dict):
        title_text = title.get("content", "") or title.get("text", "")
        if title_text:
            parts.append(f"title: {title_text}")
    elif isinstance(title, str) and title:
        parts.append(f"title: {title}")
    elements = content.get("elements", [])
    if isinstance(elements, list):
        for row in elements:
            if isinstance(row, dict):
                parts.extend(_extract_element_content(row))
            elif isinstance(row, list):
                for el in row:
                    parts.extend(_extract_element_content(el))
    card = content.get("card", {})
    if card:
        parts.extend(_extract_interactive_content(card))
    header = content.get("header", {})
    if isinstance(header, dict):
        header_title = header.get("title", {})
        if isinstance(header_title, dict):
            header_text = header_title.get("content", "") or header_title.get("text", "")
            if header_text:
                parts.append(f"title: {header_text}")
    return [p for p in parts if p]


def _extract_element_content(element):
    parts = []
    if not isinstance(element, dict):
        return parts
    tag = element.get("tag", "")
    if tag in ("markdown", "lark_md"):
        content = element.get("content", "")
        if content:
            parts.append(content)
    elif tag == "div":
        text = element.get("text", {})
        if isinstance(text, dict):
            text_content = text.get("content", "") or text.get("text", "")
            if text_content:
                parts.append(text_content)
        elif isinstance(text, str) and text:
            parts.append(text)
        for field in element.get("fields", []) or []:
            if isinstance(field, dict):
                field_text = field.get("text", {})
                if isinstance(field_text, dict):
                    content = field_text.get("content", "") or field_text.get("text", "")
                    if content:
                        parts.append(content)
    elif tag == "a":
        href = element.get("href", "")
        text = element.get("text", "")
        if href:
            parts.append(f"link: {href}")
        if text:
            parts.append(text)
    elif tag == "button":
        text = element.get("text", {})
        if isinstance(text, dict):
            content = text.get("content", "") or text.get("text", "")
            if content:
                parts.append(content)
        url = element.get("url", "") or (element.get("multi_url", {}) or {}).get("url", "")
        if url:
            parts.append(f"link: {url}")
    elif tag == "img":
        alt = element.get("alt", {})
        if isinstance(alt, dict):
            parts.append(alt.get("content", "[image]") or "[image]")
        else:
            parts.append("[image]")
    for child in element.get("elements", []) or []:
        parts.extend(_extract_element_content(child))
    for col in element.get("columns", []) or []:
        for child in (col.get("elements", []) if isinstance(col, dict) else []):
            parts.extend(_extract_element_content(child))
    return parts


def _extract_post_content(content_json):
    def _parse_block(block):
        if not isinstance(block, dict) or not isinstance(block.get("content"), list):
            return None, []
        texts, images = [], []
        if block.get("title"):
            texts.append(block.get("title"))
        for row in block["content"]:
            if not isinstance(row, list):
                continue
            for el in row:
                if not isinstance(el, dict):
                    continue
                tag = el.get("tag")
                if tag in ("text", "a"):
                    texts.append(el.get("text", ""))
                elif tag == "at":
                    texts.append(f"@{el.get('user_name', 'user')}")
                elif tag == "img" and el.get("image_key"):
                    images.append(el["image_key"])
        text = " ".join([t for t in texts if t]).strip()
        return text or None, images

    root = content_json
    if isinstance(root, dict) and isinstance(root.get("post"), dict):
        root = root["post"]
    if not isinstance(root, dict):
        return "", []
    if "content" in root:
        text, imgs = _parse_block(root)
        if text or imgs:
            return text or "", imgs
    for key in ("zh_cn", "en_us", "ja_jp"):
        if key in root:
            text, imgs = _parse_block(root[key])
            if text or imgs:
                return text or "", imgs
    for val in root.values():
        if isinstance(val, dict):
            text, imgs = _parse_block(val)
            if text or imgs:
                return text or "", imgs
    return "", []


APP_ID = str(mykeys.get("fs_app_id", "") or "").strip()
APP_SECRET = str(mykeys.get("fs_app_secret", "") or "").strip()
ALLOWED_USERS = _to_allowed_set(mykeys.get("fs_allowed_users", []))
PUBLIC_ACCESS = not ALLOWED_USERS or "*" in ALLOWED_USERS
AGENT_TIMEOUT_SEC = 900

runtime = GenericAgentRuntime()
client, user_tasks = None, {}
session_aliases = {}
session_lock = threading.RLock()


def _msg_attr(message, name, default=None):
    value = getattr(message, name, default)
    return value if value not in (None, "") else default


def _message_thread_ids(message):
    ids = []
    for name in ("root_id", "parent_id", "thread_id", "message_id"):
        value = _msg_attr(message, name)
        if value and value not in ids:
            ids.append(value)
    return ids


def _session_key(chat_id, message_id):
    return f"{chat_id or 'direct'}:{message_id}"


def resolve_feishu_session(open_id, chat_id, message):
    with session_lock:
        for mid in _message_thread_ids(message):
            sid = session_aliases.get(_session_key(chat_id, mid))
            if sid:
                return runtime.get_or_create(sid, metadata={"open_id": open_id, "chat_id": chat_id}), False
        root = _msg_attr(message, "root_id") or _msg_attr(message, "parent_id") or message.message_id
        sid = _session_key(chat_id, root)
        sess = runtime.get_or_create(sid, metadata={"open_id": open_id, "chat_id": chat_id, "root_message_id": root})
        for mid in _message_thread_ids(message):
            session_aliases[_session_key(chat_id, mid)] = sid
        session_aliases[_session_key(chat_id, root)] = sid
        return sess, True


def _session_reply_anchor(session, fallback=None):
    return session.metadata.get("root_message_id") or session.metadata.get("card_message_id") or fallback


def bind_feishu_session_message(session, message_id):
    if not message_id:
        return
    chat_id = session.metadata.get("chat_id")
    with session_lock:
        session_aliases[_session_key(chat_id, message_id)] = session.session_id
        session.metadata["card_message_id"] = message_id


def create_client():
    return lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).log_level(lark.LogLevel.INFO).build()


def _card_raw(elements):
    return json.dumps({
        "schema": "2.0",
        "config": {"streaming_mode": False, "width_mode": "fill"},
        "body": {"elements": elements},
    }, ensure_ascii=False)


def _card(text):
    return _card_raw([{"tag": "markdown", "content": text}])


def _send_raw(receive_id, payload, msg_type, rtype):
    try:
        body = CreateMessageRequest.builder().receive_id_type(rtype).request_body(
            CreateMessageRequestBody.builder().receive_id(receive_id).msg_type(msg_type).content(payload).build()
        ).build()
        r = client.im.v1.message.create(body)
        if r.success():
            return r.data.message_id if r.data else None
        print(f"发送失败: {r.code}, {r.msg}")
    except Exception as e:
        print(f"[ERROR] _send_raw 网络异常: {e}")
    return None



def _reply_raw(message_id, payload, msg_type, reply_in_thread=True):
    if not message_id:
        return None
    try:
        body = ReplyMessageRequest.builder().message_id(message_id).request_body(
            ReplyMessageRequestBody.builder()
            .msg_type(msg_type)
            .content(payload)
            .reply_in_thread(reply_in_thread)
            .build()
        ).build()
        r = client.im.v1.message.reply(body)
        if r.success():
            return r.data.message_id if r.data else None
        print(f"reply failed: {r.code}, {r.msg}")
    except Exception as e:
        print(f"[ERROR] _reply_raw network error: {e}")
    return None


def _patch_card(message_id, card_json):
    return _patch_card_result(message_id, card_json)[0]


def _patch_card_result(message_id, card_json):
    try:
        body = PatchMessageRequest.builder().message_id(message_id).request_body(
            PatchMessageRequestBody.builder().content(card_json).build()
        ).build()
        r = client.im.v1.message.patch(body)
        if not r.success():
            print(f"[ERROR] patch_card 失败: {r.code}, {r.msg}")
        msg = f"{getattr(r, 'code', '')} {getattr(r, 'msg', '')}".lower()
        return r.success(), ("230099" in msg or "11310" in msg or "element exceeds the limit" in msg)
    except Exception as e:
        print(f"[ERROR] _patch_card 网络异常: {e}")
        return False, False


def send_message(receive_id, content, msg_type="text", use_card=False, receive_id_type="open_id"):
    if use_card:
        return _send_raw(receive_id, _card(content), "interactive", receive_id_type)
    if msg_type == "text":
        return _send_raw(receive_id, json.dumps({"text": content}, ensure_ascii=False), "text", receive_id_type)
    return _send_raw(receive_id, content, msg_type, receive_id_type)


def _reply_text(message_id, content):
    return _reply_raw(message_id, json.dumps({"text": content}, ensure_ascii=False), "text", reply_in_thread=True)


def update_message(message_id, content):
    return _patch_card(message_id, _card(content))


def _upload_image_sync(file_path):
    try:
        with open(file_path, "rb") as f:
            request = CreateImageRequest.builder().request_body(
                CreateImageRequestBody.builder().image_type("message").image(f).build()
            ).build()
            response = client.im.v1.image.create(request)
            if response.success():
                return response.data.image_key
            print(f"[ERROR] upload image failed: {response.code}, {response.msg}")
    except Exception as e:
        print(f"[ERROR] upload image failed {file_path}: {e}")
    return None


def _upload_file_sync(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    file_type = _FILE_TYPE_MAP.get(ext, "stream")
    file_name = os.path.basename(file_path)
    try:
        with open(file_path, "rb") as f:
            request = CreateFileRequest.builder().request_body(
                CreateFileRequestBody.builder().file_type(file_type).file_name(file_name).file(f).build()
            ).build()
            response = client.im.v1.file.create(request)
            if response.success():
                return response.data.file_key
            print(f"[ERROR] upload file failed: {response.code}, {response.msg}")
    except Exception as e:
        print(f"[ERROR] upload file failed {file_path}: {e}")
    return None


def _download_image_sync(message_id, image_key):
    try:
        request = GetMessageResourceRequest.builder().message_id(message_id).file_key(image_key).type("image").build()
        response = client.im.v1.message_resource.get(request)
        if response.success():
            data = response.file.read() if hasattr(response.file, "read") else response.file
            return data, response.file_name
        print(f"[ERROR] download image failed: {response.code}, {response.msg}")
    except Exception as e:
        print(f"[ERROR] download image failed {image_key}: {e}")
    return None, None


def _download_file_sync(message_id, file_key, resource_type="file"):
    if resource_type == "audio":
        resource_type = "file"
    try:
        request = GetMessageResourceRequest.builder().message_id(message_id).file_key(file_key).type(resource_type).build()
        response = client.im.v1.message_resource.get(request)
        if response.success():
            data = response.file.read() if hasattr(response.file, "read") else response.file
            return data, response.file_name
        print(f"[ERROR] download {resource_type} failed: {response.code}, {response.msg}")
    except Exception as e:
        print(f"[ERROR] download {resource_type} failed {file_key}: {e}")
    return None, None


def _download_and_save_media(msg_type, content_json, message_id):
    data, filename = None, None
    if msg_type == "image":
        image_key = content_json.get("image_key")
        if image_key and message_id:
            data, filename = _download_image_sync(message_id, image_key)
            if not filename:
                filename = f"{image_key[:16]}.jpg"
    elif msg_type in ("audio", "file", "media"):
        file_key = content_json.get("file_key")
        if file_key and message_id:
            data, filename = _download_file_sync(message_id, file_key, msg_type)
            if not filename:
                filename = file_key[:16]
            if msg_type == "audio" and filename and not filename.endswith(".opus"):
                filename = f"{filename}.opus"
    if data and filename:
        file_path = os.path.join(MEDIA_DIR, os.path.basename(filename))
        with open(file_path, "wb") as f:
            f.write(data)
        return file_path, filename
    return None, None


def _describe_media(msg_type, file_path, filename):
    if msg_type == "image":
        return f"[image: {filename}]\n[Image: source: {file_path}]"
    if msg_type == "audio":
        return f"[audio: {filename}]\n[File: source: {file_path}]"
    if msg_type in ("file", "media"):
        return f"[{msg_type}: {filename}]\n[File: source: {file_path}]"
    return f"[{msg_type}]\n[File: source: {file_path}]"


def _send_local_file(receive_id, file_path, receive_id_type="open_id"):
    if not os.path.isfile(file_path):
        send_message(receive_id, f"⚠️ 文件不存在: {file_path}", receive_id_type=receive_id_type)
        return False
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _IMAGE_EXTS:
        image_key = _upload_image_sync(file_path)
        if image_key:
            send_message(receive_id, json.dumps({"image_key": image_key}, ensure_ascii=False), msg_type="image", receive_id_type=receive_id_type)
            return True
    else:
        file_key = _upload_file_sync(file_path)
        if file_key:
            msg_type = "media" if ext in _AUDIO_EXTS or ext in _VIDEO_EXTS else "file"
            send_message(receive_id, json.dumps({"file_key": file_key}, ensure_ascii=False), msg_type=msg_type, receive_id_type=receive_id_type)
            return True
    send_message(receive_id, f"⚠️ 文件发送失败: {os.path.basename(file_path)}", receive_id_type=receive_id_type)
    return False


def _send_generated_files(receive_id, raw_text, receive_id_type="open_id"):
    for file_path in _extract_files(raw_text):
        _send_local_file(receive_id, file_path, receive_id_type)


def _build_user_message(message):
    msg_type = message.message_type
    message_id = message.message_id
    content_json = _parse_json(message.content)
    parts, image_paths = [], []
    if msg_type == "text":
        text = str(content_json.get("text", "") or "").strip()
        if text:
            parts.append(text)
    elif msg_type == "post":
        text, image_keys = _extract_post_content(content_json)
        if text:
            parts.append(text)
        for image_key in image_keys:
            file_path, filename = _download_and_save_media("image", {"image_key": image_key}, message_id)
            if file_path and filename:
                parts.append(_describe_media("image", file_path, filename))
                image_paths.append(file_path)
            else:
                parts.append("[image: download failed]")
    elif msg_type in ("image", "audio", "file", "media"):
        file_path, filename = _download_and_save_media(msg_type, content_json, message_id)
        if file_path and filename:
            parts.append(_describe_media(msg_type, file_path, filename))
            if msg_type == "image":
                image_paths.append(file_path)
        else:
            parts.append(f"[{msg_type}: download failed]")
    elif msg_type in ("share_chat", "share_user", "interactive", "share_calendar_event", "system", "merge_forward"):
        parts.append(_extract_share_card_content(content_json, msg_type))
    else:
        parts.append(_MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))
    return "\n".join([p for p in parts if p]).strip(), image_paths


def _fmt_tool_call(tc):
    name = tc.get('tool_name', '?')
    args = {k: v for k, v in (tc.get('args') or {}).items() if not k.startswith('_')}
    return f"- `{name}`({json.dumps(args, ensure_ascii=False)[:200]})"


def _build_step_detail(resp, tool_calls):
    """从 LLM response + tool_calls 组装单步展开详情（纯函数）。"""
    parts = []
    thinking = (getattr(resp, 'thinking', '') or '').strip() if resp else ''
    if thinking:
        parts.append(f"### 💭 Thinking\n{thinking}")
    if tool_calls:
        parts.append("### 🛠 Tool Calls\n" + "\n".join(_fmt_tool_call(tc) for tc in tool_calls))
    content = _display_text((getattr(resp, 'content', '') or '')).strip() if resp else ''
    if content and content != '...':
        parts.append(f"### 📝 Output\n{content}")
    return "\n\n".join(parts)


def _section_title(text, index):
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    first = re.sub(r"^[#>*`\s-]+", "", first).strip()
    first = re.sub(r"^\d+[.)?]\s*", "", first).strip()
    return (first[:80] if first else f"Section {index}")


def _split_card_sections(text, limit=6000):
    text = (text or "").strip()
    if not text:
        return [("Result", "_(empty)_")]
    heading_re = re.compile(r"(?m)^(#{1,4}\s+.+|\*\*[^*]{2,100}\*\*\s*)$")
    matches = list(heading_re.finditer(text))
    sections = []
    if matches:
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[match.start():end].strip()
            title = re.sub(r"^[#\s]+", "", match.group(1)).strip(" *")
            sections.append((title or f"Section {i + 1}", chunk))
    else:
        paragraphs = re.split(r"\n\s*\n", text)
        current, current_len = [], 0
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if current and current_len + len(para) + 2 > limit:
                body = "\n\n".join(current)
                sections.append((_section_title(body, len(sections) + 1), body))
                current, current_len = [para], len(para)
            else:
                current.append(para)
                current_len += len(para) + 2
        if current:
            body = "\n\n".join(current)
            sections.append((_section_title(body, len(sections) + 1), body))
    expanded = []
    for title, body in sections or [("Result", text)]:
        body = body.strip()
        if len(body) <= limit:
            expanded.append((title, body))
            continue
        for offset in range(0, len(body), limit):
            expanded.append((f"{title} ({offset // limit + 1})", body[offset:offset + limit]))
    return expanded or [("Result", text)]


class _TaskCard:
    """飞书任务卡片：单卡片持续 patch；每步一个独立折叠面板（header 显示 summary，展开看详情）。"""
    _DETAIL_LIMIT = 8000
    _FINAL_LIMIT = 6000

    def __init__(self, receive_id, rid_type, reply_to_message_id=None):
        self.rid, self.rtype = receive_id, rid_type
        self.reply_to_message_id = reply_to_message_id
        self.steps = []          # [(summary, detail), ...]
        self.status = "🤔 思考中..."
        self.final = None
        self.msg_id = None
        self.page_no = 1
        self.turn_no = 0
        self.turn_base = 1
        self.note = None

    def _panel(self, title, content, limit=None):
        content = content or "_(empty)_"
        limit = limit or self._DETAIL_LIMIT
        if len(content) > limit:
            content = content[:limit] + f"\n\n... truncated, total {len(content)} chars"
        return {
            "tag": "collapsible_panel", "expanded": False,
            "header": {"title": {"tag": "plain_text", "content": (title or "Section")[:120]}},
            "elements": [{"tag": "markdown", "content": content}],
        }

    def _step_panel(self, idx, summary, detail):
        return self._panel(f"Turn {idx} - {summary}", detail or "_(empty)_", self._DETAIL_LIMIT)

    def _final_panels(self):
        sections = _split_card_sections(self.final or "_(empty)_", self._FINAL_LIMIT)
        return [self._panel(title, body, self._FINAL_LIMIT) for title, body in sections]

    def _build(self):
        header = f"**{self.status}**"
        if self.page_no > 1:
            header += f"\n\n📄 工作卡片 {self.page_no}"
        els = [{"tag": "markdown", "content": header}]
        if self.note:
            els.append({"tag": "markdown", "content": self.note})
        for i, (s, d) in enumerate(self.steps, self.turn_base):
            els.append(self._step_panel(i, s, d))
        if self.final:
            els.append({"tag": "hr"})
            els.extend(self._final_panels())
        return _card_raw(els)

    def _push(self):
        card = self._build()
        if self.msg_id:
            return _patch_card_result(self.msg_id, card)
        if self.reply_to_message_id:
            self.msg_id = _reply_raw(self.reply_to_message_id, card, "interactive", reply_in_thread=True)
            if self.msg_id:
                return True, False
            self.reply_to_message_id = None
        self.msg_id = _send_raw(self.rid, card, "interactive", self.rtype)
        return bool(self.msg_id), False

    def _rollover(self):
        self.page_no += 1
        self.msg_id = None
        self.final = None
        self.note = "⚠️ 上一张工作卡片达到飞书限制，本页继续展示后续进展。"

    # ── 公开接口 ──

    def start(self):
        self._push()

    def step(self, summary, detail=""):
        self.turn_no += 1
        step = (summary, detail)
        self.steps.append(step)
        self.status = f"⏳ 工作中 · Turn {self.turn_no}"
        ok, limit = self._push()
        if limit:
            self.steps.pop()
            self._rollover()
            self.turn_base = self.turn_no
            self.steps = [step]
            self._push()

    def done(self, text):
        self.status = "\u2705 \u5df2\u5b8c\u6210"
        self.final = text or "_(\u65e0\u6587\u672c\u8f93\u51fa)_"
        ok, limit = self._push()
        if limit:
            self._rollover()
            self.steps = []
            self.turn_base = self.turn_no + 1
            self.final = text or "_(\u65e0\u6587\u672c\u8f93\u51fa)_"
            self._push()

    def fail(self, msg):
        self.status = f"❌ {msg}"
        self._push()


def _make_task_hook(card, done_event, on_final):
    """飞书任务 hook：每轮 patch 卡片状态；结束触发 on_final(raw) 处理附件。"""
    def hook(ctx):
        try:
            if ctx.get('exit_reason'):
                resp = ctx.get('response')
                raw = resp.content if hasattr(resp, 'content') else str(resp)
                card.done(_display_text(raw))
                on_final(raw)
                done_event.set()
            elif ctx.get('summary'):
                detail = _build_step_detail(ctx.get('response'), ctx.get('tool_calls') or [])
                card.step(ctx['summary'], detail)
        except Exception as e:
            print(f"[fs hook] error: {e}")
    return hook


def handle_message(data):
    event, message, sender = data.event, data.event.message, data.event.sender
    open_id = sender.sender_id.open_id
    chat_id = message.chat_id
    if not PUBLIC_ACCESS and open_id not in ALLOWED_USERS:
        print(f"\u672a\u6388\u6743\u7528\u6237: {open_id}")
        return
    session, is_new_session = resolve_feishu_session(open_id, chat_id, message)
    user_input, image_paths = _build_user_message(message)
    if not user_input:
        target = chat_id or open_id
        target_type = "chat_id" if chat_id else "open_id"
        send_message(target, f"\u26a0\ufe0f \u6682\u4e0d\u652f\u6301\u5904\u7406\u6b64\u7c7b\u98de\u4e66\u6d88\u606f\uff1a{message.message_type}", receive_id_type=target_type)
        return
    print(f"received message [{open_id}] session={session.session_id} ({message.message_type}, {len(image_paths)} images): {user_input[:200]}")
    if message.message_type == "text" and user_input.startswith("/"):
        return handle_command(open_id, user_input, chat_id, session=session)

    reply_anchor = _session_reply_anchor(session, message.message_id)
    task_item = {"user_input": user_input, "image_paths": image_paths, "message_id": message.message_id, "reply_to_message_id": reply_anchor}
    with session_lock:
        active_task = user_tasks.get(session.session_id)
        if active_task:
            active_task["queue"].put(task_item)
            active_task["queued"] = active_task.get("queued", 0) + 1
            _reply_text(_session_reply_anchor(session, message.message_id), "\u5df2\u653e\u5165\u672c\u8bdd\u9898\u961f\u5217\uff0c\u5f53\u524d\u4efb\u52a1\u5b8c\u6210\u540e\u4f1a\u7ee7\u7eed\u5904\u7406\u3002")
            return
        task_state = {"running": True, "queued": 0, "queue": Q.Queue()}
        user_tasks[session.session_id] = task_state

    def run_agent():
        receive_id = chat_id or open_id
        rid_type = "chat_id" if chat_id else "open_id"
        hook_key = f"fs_{session.session_id}"
        on_final = lambda raw: _send_generated_files(receive_id, raw, receive_id_type=rid_type)
        agent = session.agent
        current = task_item
        try:
            while current:
                done_event = threading.Event()
                reply_to_message_id = current.get("reply_to_message_id") or _session_reply_anchor(session, current.get("message_id"))
                card = _TaskCard(receive_id, rid_type, reply_to_message_id=reply_to_message_id)
                card.start()
                bind_feishu_session_message(session, card.msg_id)
                if not hasattr(agent, '_turn_end_hooks'):
                    agent._turn_end_hooks = {}
                agent._turn_end_hooks[hook_key] = _make_task_hook(card, done_event, on_final)
                try:
                    session.put_task(current["user_input"], source="feishu", images=current.get("image_paths") or [])
                    start_time = time.time()
                    while not done_event.wait(timeout=3):
                        if not task_state.get("running", True):
                            agent.abort()
                            card.fail("\u5df2\u505c\u6b62")
                            break
                        if time.time() - start_time > AGENT_TIMEOUT_SEC:
                            task_state["running"] = False
                            agent.abort()
                            card.fail("\u4efb\u52a1\u8d85\u65f6")
                            break
                except Exception as e:
                    traceback.print_exc()
                    card.fail(f"\u9519\u8bef: {e}")
                finally:
                    agent._turn_end_hooks.pop(hook_key, None)

                with session_lock:
                    if not task_state.get("running", True):
                        user_tasks.pop(session.session_id, None)
                        return
                    try:
                        current = task_state["queue"].get_nowait()
                        task_state["queue"].task_done()
                        task_state["queued"] = max(0, task_state.get("queued", 1) - 1)
                    except Q.Empty:
                        user_tasks.pop(session.session_id, None)
                        return
        finally:
            with session_lock:
                if user_tasks.get(session.session_id) is task_state:
                    user_tasks.pop(session.session_id, None)

    threading.Thread(target=run_agent, daemon=True).start()


def handle_command(open_id, cmd, chat_id=None, session=None):
    def _send_cmd_response(content):
        if chat_id:
            send_message(chat_id, content, receive_id_type="chat_id")
        else:
            send_message(open_id, content)
    parts = (cmd or "").split()
    op = (parts[0] if parts else "").lower()
    agent = session.agent if session is not None else None
    if op == "/stop":
        if session is not None:
            user_tasks.setdefault(session.session_id, {})["running"] = False
            agent.abort()
        _send_cmd_response("正在停止...")
    elif op == "/new":
        if agent is None:
            return _send_cmd_response("No active session")
        _send_cmd_response(reset_conversation(agent))
    elif op == "/help":
        _send_cmd_response("命令列表:\n/stop - 停止当前任务\n/status - 查看状态\n/llm - 查看当前模型列表\n/llm [n] - 切换到第 n 个模型\n/restore - 恢复上次对话历史\n/continue - 列出可恢复会话\n/continue [n] - 恢复第 n 个会话\n/new - 开启新对话并清空当前上下文\n/help - 显示帮助")
    elif op == "/status":
        llm = agent.get_llm_name() if agent.llmclient else "未配置"
        _send_cmd_response(f"状态: {'🔴 运行中' if agent.is_running else '🟢 空闲'}\nLLM: [{agent.llm_no}] {llm}")
    elif op == "/llm":
        if agent is None or not agent.llmclient:
            return _send_cmd_response("❌ 当前没有可用的 LLM 配置")
        if len(parts) > 1:
            try:
                agent.next_llm(int(parts[1]))
                return _send_cmd_response(f"✅ 已切换到 [{agent.llm_no}] {agent.get_llm_name()}")
            except Exception:
                return _send_cmd_response(f"用法: /llm <0-{len(agent.list_llms()) - 1}>")
        lines = [f"{'→' if cur else '  '} [{i}] {name}" for i, name, cur in agent.list_llms()]
        _send_cmd_response("LLMs:\n" + "\n".join(lines))
    elif op == "/restore":
        if agent is None:
            return _send_cmd_response("No active session")
        try:
            restored_info, err = format_restore()
            if err:
                return _send_cmd_response(err.replace("❌ ", ""))
            restored, fname, count = restored_info
            agent.history.extend(restored)
            agent.abort()
            _send_cmd_response(f"已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)")
        except Exception as e:
            _send_cmd_response(f"恢复失败: {e}")
    elif op == "/continue" or cmd.startswith("/continue"):
        if agent is None:
            return _send_cmd_response("No active session")
        _send_cmd_response(handle_continue_frontend(agent, cmd))
    else:
        _send_cmd_response(f"未知命令: {cmd}")


def main():
    global client
    if not APP_ID or not APP_SECRET:
        print("错误: 请在 mykey.py 或 mykey.json 中配置 fs_app_id 和 fs_app_secret")
        sys.exit(1)
    client = create_client()
    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(handle_message).build()
    print("=" * 50 + "\n飞书 Agent 已启动（长连接模式）\n" + f"App ID: {APP_ID}\n等待消息...\n" + "=" * 50)
    retry_delay = 5
    while True:
        try:
            cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler, log_level=lark.LogLevel.INFO)
            cli.start()
        except Exception as e:
            print(f"[WARN] 飞书长连接断开或启动失败: {e}")
        print(f"[INFO] {retry_delay}s 后重连...")
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 120)
        # 重连时刷新 client
        try:
            client = create_client()
        except Exception:
            pass


if __name__ == "__main__":
    main()
