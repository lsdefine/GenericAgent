"""
stapp2_extensions — UI enhancements for stapp2 (vs upstream GenericAgent/frontends/stapp2.py)

Attachments, paste-to-upload, sidebar controls, compact uploader layout.
stapp2_extensions — stapp2 增强模块（附件、粘贴上传、侧栏扩展、紧凑上传布局）

Code review map | 审查对照
────────────────────────────────────────────────────────────
Module A  i18n & paths          — GA_LANG sidebar labels
Module B  inject CSS/JS         — file uploader layout, paste/delete hidden inputs
Module C  attachments           — upload, paste image, thumbnails, prompt building
Module D  sidebar extras        — force stop, desktop pet, reinject history, autonomy
Module E  chat input row        — [upload | chat_input] + send-with-attachments
Module F  turn UI (in stapp2)   — intermediate segment expanders (see stapp2.py)
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import quote
from urllib.request import urlopen

import streamlit as st

# ── Module A: i18n & paths | 国际化与路径 ─────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
PLACEHOLDER_PASTE = "__paste_image_signal__"
PLACEHOLDER_DELETE = "__delete_file_signal__"
TEXT_FILE_SUFFIXES = (
    ".txt", ".md", ".py", ".json", ".log", ".csv", ".yaml", ".yml", ".js", ".ts", ".sql",
)

_I18N = {
    "zh": {
        "force_stop": "强行停止任务",
        "reinject_tools": "重新注入System Prompt",
        "desktop_pet": "🐱 桌面宠物",
    },
    "en": {
        "force_stop": "Force Stop",
        "reinject_tools": "Reinject Tools",
        "desktop_pet": "🐱 Desktop Pet",
    },
}


def get_lang() -> str:
    lang = os.environ.get("GA_LANG", "zh")
    return lang if lang in ("zh", "en") else "zh"


def t(key: str) -> str:
    lang = get_lang()
    return _I18N.get(lang, _I18N["zh"]).get(key, key)


EXTENSION_SESSION_DEFAULTS = {
    "uploaded_files": [],       # list[{name, type, size, content}]
    "file_uploader_key": 0,
    "preview_file_idx": None,
}


def register_extension_session_state() -> None:
    """Register extension session_state keys | 注册扩展模块专用 session 键"""
    for key, value in EXTENSION_SESSION_DEFAULTS.items():
        st.session_state.setdefault(key, value)


# ── Module B: inject CSS/JS | 注入样式与脚本 ─────────────────────────────

FILE_UPLOAD_CSS = """
<style>
/* Compact uploader: hide dropzone text, 48×48 “+” button | 紧凑上传：隐藏拖放文案，48×48 加号按钮 */
div[data-testid="stFileUploaderDropzoneInstructions"] {
    display: none !important;
}
div[data-testid="stFileUploader"] section {
    padding: 0 !important;
    border: none !important;
    background: transparent !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    min-height: 0 !important;
}
div[data-testid="stFileUploader"] section button {
    width: 48px !important;
    height: 48px !important;
    min-width: 48px !important;
    flex-shrink: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    border-radius: 12px !important;
    background: var(--anthropic-bg-secondary) !important;
    border: 1px solid var(--anthropic-border) !important;
    color: transparent !important;
    font-size: 0 !important;
    position: relative !important;
    cursor: pointer !important;
    transition: background 0.2s ease, border-color 0.2s ease !important;
    box-sizing: border-box !important;
}
div[data-testid="stFileUploader"] section button::before {
    content: '+';
    font-size: 28px;
    font-weight: 300;
    line-height: 1;
    color: var(--anthropic-text-secondary);
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    pointer-events: none;
}
div[data-testid="stFileUploader"] section button:hover {
    background: var(--anthropic-primary) !important;
    border-color: var(--anthropic-primary) !important;
}
div[data-testid="stFileUploader"] section button:hover::before {
    color: white;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) {
    flex-wrap: nowrap !important;
    align-items: flex-end !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) > *:first-child {
    flex: 0 0 54px !important;
    min-width: 54px !important;
    max-width: 54px !important;
}
[data-testid="stHorizontalBlock"]:has([data-testid="stFileUploader"]) > *:last-child {
    flex: 1 1 0 !important;
    min-width: 0 !important;
}
</style>
"""

# Off-screen signal inputs for paste/delete (Streamlit widget bridge)
# 屏幕外信号输入框：粘贴/删除附件时由 JS 写入以触发 rerun
PASTE_HIDDEN_INPUT_CSS = f"""
<style>
div[data-testid="stTextInput"]:has(input[placeholder="{PLACEHOLDER_PASTE}"]),
div[data-testid="stTextInput"]:has(input[placeholder="{PLACEHOLDER_DELETE}"]) {{
    position: fixed !important;
    left: -99999px !important;
    top: -99999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    z-index: -1 !important;
}}
div[data-testid="stElementContainer"]:has(input[placeholder="{PLACEHOLDER_PASTE}"]),
div[data-testid="stElementContainer"]:has(input[placeholder="{PLACEHOLDER_DELETE}"]) {{
    height: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
}}
</style>
"""


def build_paste_listener_script() -> str:
    """Clipboard image → hidden text_input → session_state | 剪贴板图片写入隐藏输入框"""
    return f"""
<script>
(function() {{
    var hostWin = window.parent || window;
    var hostDoc = hostWin.document || document;
    if (hostWin.__pasteImageListenerInstalled__) return;
    hostWin.__pasteImageListenerInstalled__ = true;
    hostDoc.addEventListener('paste', function(e) {{
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (var i = 0; i < items.length; i++) {{
            var item = items[i];
            if (item.type && item.type.startsWith('image/')) {{
                var blob = item.getAsFile();
                if (!blob) continue;
                (function(b) {{
                    var reader = new FileReader();
                    reader.onload = function(ev) {{
                        var b64 = ev.target.result;
                        var input = hostDoc.querySelector(
                            'input[placeholder="{PLACEHOLDER_PASTE}"]'
                        );
                        if (!input) return;
                        var setter = Object.getOwnPropertyDescriptor(
                            hostWin.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(input, b64);
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        setTimeout(function() {{
                            input.dispatchEvent(new Event('blur', {{ bubbles: false }}));
                            input.dispatchEvent(new Event('focusout', {{ bubbles: true }}));
                        }}, 100);
                    }};
                    reader.readAsDataURL(b);
                }})(blob);
                break;
            }}
        }}
    }});
}})();
</script>
"""


def _embed_html(html: str, **kwargs) -> None:
    try:
        from streamlit import iframe as st_iframe

        st_iframe(html, **{k: max(v, 1) if isinstance(v, int) else v for k, v in kwargs.items()})
    except (ImportError, AttributeError):
        from streamlit.components.v1 import html as components_html

        components_html(html, **kwargs)


def inject_extension_assets() -> None:
    """Inject extension CSS/JS after upstream theme | 在上游主题之后注入扩展样式与脚本"""
    st.markdown(FILE_UPLOAD_CSS, unsafe_allow_html=True)
    st.markdown(PASTE_HIDDEN_INPUT_CSS, unsafe_allow_html=True)
    _embed_html(build_paste_listener_script(), height=0, width=0)


# ── Module C: attachments | 附件处理 ─────────────────────────────────────

def save_uploaded_file(file_dict: dict) -> str:
    """Save to temp/uploaded/, return absolute path | 保存到 temp/uploaded/ 并返回绝对路径"""
    os.makedirs("temp/uploaded", exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._\-一-龥]", "_", file_dict["name"])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    saved_path = os.path.join("temp", "uploaded", f"{timestamp}_{safe_name}")
    try:
        with open(saved_path, "wb") as f:
            f.write(file_dict["content"])
        return os.path.abspath(saved_path)
    except Exception as e:
        print(f"[ERROR] Failed to save {file_dict['name']}: {e}")
        return ""


def generate_thumbnail(file_dict: dict, size=(80, 80)) -> str:
    """Thumbnail as data URI or emoji | 缩略图：图片为 data URI，其它为 emoji"""
    if file_dict["type"].startswith("image/"):
        try:
            from PIL import Image

            img = Image.open(BytesIO(file_dict["content"]))
            img.thumbnail(size, Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/png;base64,{b64}"
        except Exception as e:
            print(f"[ERROR] Thumbnail generation failed: {e}")
            return "📷"
    ext = os.path.splitext(file_dict["name"])[1].lower()
    icon_map = {
        ".pdf": "📄", ".txt": "📝", ".md": "📝", ".doc": "📄", ".docx": "📄",
        ".xls": "📊", ".xlsx": "📊", ".csv": "📊",
        ".zip": "📦", ".rar": "📦", ".7z": "📦",
        ".py": "🐍", ".js": "📜", ".json": "📋", ".xml": "📋",
        ".mp3": "🎵", ".wav": "🎵", ".mp4": "🎬", ".avi": "🎬",
    }
    return icon_map.get(ext, "📎")


def build_prompt_with_files(prompt: str, files: list) -> tuple[str, str]:
    """Return (agent_prompt, display_prompt) | 返回 (发给 Agent 的 prompt, 界面展示用 prompt)"""
    if not files:
        return prompt, prompt

    attachment_info = ["\n\n[用户上传附件 — 文件已保存到本地磁盘，可用 file_read 工具读取]"]
    for f in files:
        saved_path = save_uploaded_file(f)
        if not saved_path:
            continue
        if f["type"].startswith("image/"):
            b64 = base64.b64encode(f["content"]).decode()
            attachment_info.append(
                f"\n- [图片附件] {f['name']} ({f['size']} bytes)"
                f"\n  磁盘路径: {saved_path}"
                f"\n  data:{f['type']};base64,{b64[:100]}...(truncated)"
            )
        elif f["name"].endswith(TEXT_FILE_SUFFIXES):
            try:
                text = f["content"].decode("utf-8", errors="replace")
                max_chars = 6000
                attachment_info.append(
                    f"\n--- 文本文件: {f['name']} ({f['size']} bytes) ---"
                    f"\n磁盘路径: {saved_path}"
                    f"\n{text[:max_chars]}"
                    + ("\n[内容已截断，请用 file_read 读取完整内容]" if len(text) > max_chars else "")
                )
            except Exception:
                attachment_info.append(f"\n- 文件: {f['name']} (无法解码为文本)\n  磁盘路径: {saved_path}")
        else:
            attachment_info.append(f"\n- 文件: {f['name']} ({f['size']} bytes)\n  磁盘路径: {saved_path}")

    agent_prompt = prompt + "\n".join(attachment_info)
    display_prompt = f"{prompt}\n\n📎 附件: {', '.join(f['name'] for f in files)}"
    return agent_prompt, display_prompt


def render_file_thumbnails() -> None:
    """Thumbnail strip with JS delete bridge | 缩略图条，删除经 JS 写入隐藏输入框"""
    files = st.session_state.uploaded_files
    if not files:
        return

    cards_html = []
    for idx, f in enumerate(files):
        thumb = generate_thumbnail(f)
        safe_name = (
            f["name"].replace("&", "&amp;").replace('"', "&quot;")
            .replace("'", "&#39;").replace("<", "&lt;")
        )
        name_display = safe_name[:18]
        if thumb.startswith("data:image"):
            inner = f'<img src="{thumb}" style="width:100%;height:100%;object-fit:cover;display:block;">'
        else:
            inner = (
                f'<div style="width:100%;height:100%;display:flex;'
                f'align-items:center;justify-content:center;font-size:30px;">{thumb}</div>'
            )
        card = (
            f'<div style="position:relative;width:72px;flex-shrink:0;margin-top:6px;">'
            f'  <div style="width:72px;height:72px;border-radius:8px;overflow:hidden;'
            f'              border:1px solid #d5cec5;background:#eeece2;">{inner}</div>'
            f'  <div style="font-size:9px;color:#6b7280;text-align:center;margin-top:3px;'
            f'              white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'              max-width:72px;" title="{safe_name}">{name_display}</div>'
            f'  <div onclick="deleteFile({idx})"'
            f'       style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;'
            f'              border-radius:50%;background:#9ca3af;color:white;font-size:13px;'
            f'              font-weight:bold;display:flex;align-items:center;'
            f'              justify-content:center;cursor:pointer;line-height:1;"'
            f'       onmouseover="this.style.background=\'#ef4444\'"'
            f'       onmouseout="this.style.background=\'#9ca3af\'">&#215;</div></div>'
        )
        cards_html.append(card)

    n_rows = max(1, (len(files) + 7) // 8)
    iframe_height = n_rows * 100 + 10
    full_html = (
        "<!DOCTYPE html><html><head><style>"
        "html,body{margin:0;padding:0;background:transparent;overflow:hidden;}"
        "</style></head><body>"
        '<div style="display:flex;gap:10px;flex-wrap:wrap;'
        'padding:6px 6px 4px 2px;align-items:flex-start;">'
        + "".join(cards_html)
        + "</div><script>"
        "function deleteFile(idx){"
        "  try{"
        "    var hw=window.parent;var hd=hw.document;"
        f'    var inp=hd.querySelector(\'input[placeholder="{PLACEHOLDER_DELETE}"]\');'
        "    if(!inp)return;"
        '    var s=Object.getOwnPropertyDescriptor(hw.HTMLInputElement.prototype,"value").set;'
        '    s.call(inp,String(idx));'
        '    inp.dispatchEvent(new Event("input",{bubbles:true}));'
        "    setTimeout(function(){"
        '      inp.dispatchEvent(new Event("blur",{bubbles:false}));'
        '      inp.dispatchEvent(new Event("focusout",{bubbles:true}));'
        "    },100);"
        '  }catch(e){console.error("deleteFile:",e);}'
        "}"
        "</script></body></html>"
    )
    _embed_html(full_html, height=iframe_height)


@st.dialog("文件预览", width="large")
def preview_file_dialog() -> None:
    """File preview modal | 文件预览对话框"""
    idx = st.session_state.preview_file_idx
    if idx is None or idx >= len(st.session_state.uploaded_files):
        return
    f = st.session_state.uploaded_files[idx]
    st.subheader(f"📎 {f['name']}")
    st.caption(f"类型: {f['type']} | 大小: {f['size']:,} bytes")
    if f["type"].startswith("image/"):
        st.image(f["content"], use_container_width=True)
    elif f["name"].endswith(TEXT_FILE_SUFFIXES):
        try:
            text = f["content"].decode("utf-8", errors="replace")
            st.code(text[:5000], language=None)
            if len(text) > 5000:
                st.info("内容已截断至前 5000 字符")
        except Exception as e:
            st.error(f"无法显示文件内容: {e}")
    else:
        st.info("此文件类型不支持预览")
        st.json({"文件名": f["name"], "类型": f["type"], "大小": f"{f['size']:,} bytes"})
    if st.button("关闭", use_container_width=True):
        st.session_state.preview_file_idx = None
        st.rerun()


def process_paste_signal() -> bool:
    """Decode clipboard image from hidden input; return True if rerun needed"""
    val = st.session_state.get("paste_image_signal", "")
    if not val or not val.startswith("data:image"):
        return False
    try:
        header, b64str = val.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        ext = mime.split("/")[1]
        content = base64.b64decode(b64str)
        if len(content) <= MAX_ATTACHMENT_BYTES:
            fname = f"pasted_{datetime.now().strftime('%H%M%S%f')[:12]}.{ext}"
            st.session_state.uploaded_files.append({
                "name": fname, "type": mime, "size": len(content), "content": content,
            })
    except Exception:
        pass
    st.session_state.paste_image_signal = ""
    return True


def process_delete_signal() -> bool:
    """Remove attachment by index from hidden input; return True if rerun needed"""
    val = st.session_state.get("delete_file_signal", "")
    if not val or not val.isdigit():
        return False
    idx = int(val)
    if 0 <= idx < len(st.session_state.uploaded_files):
        st.session_state.uploaded_files.pop(idx)
    st.session_state.delete_file_signal = ""
    return True


def render_signal_inputs() -> None:
    """Hidden Streamlit inputs for JS bridges | 供 JS 桥接用的隐藏输入框"""
    st.text_input(
        "paste_signal", value="", key="paste_image_signal",
        label_visibility="collapsed", placeholder=PLACEHOLDER_PASTE,
    )
    st.text_input(
        "delete_signal", value="", key="delete_file_signal",
        label_visibility="collapsed", placeholder=PLACEHOLDER_DELETE,
    )


def render_attachment_input_row(*, streaming: bool):
    """
    Layout: thumbnails + [file_uploader | chat_input]
    布局：缩略图 + [上传按钮 | 聊天输入框]
    Returns prompt string or None.
    """
    render_file_thumbnails()
    col_upload, col_input = st.columns([0.08, 0.92])
    with col_upload:
        uploaded = st.file_uploader(
            "上传文件", accept_multiple_files=True, label_visibility="collapsed",
            key=f"file_uploader_{st.session_state.file_uploader_key}",
            help="点击上传图片、文档等文件",
        )
        if uploaded:
            for uf in uploaded:
                if any(f["name"] == uf.name for f in st.session_state.uploaded_files):
                    continue
                content = uf.read()
                if len(content) > MAX_ATTACHMENT_BYTES:
                    st.warning(f"文件 {uf.name} 超过 10MB，已跳过")
                    continue
                st.session_state.uploaded_files.append({
                    "name": uf.name,
                    "type": uf.type or "application/octet-stream",
                    "size": len(content),
                    "content": content,
                })
            st.session_state.file_uploader_key += 1
            st.rerun()
    with col_input:
        return st.chat_input("请输入指令", disabled=streaming)


def handle_user_submit(prompt: str, *, start_task) -> None:
    """Append message, send to agent with attachments, clear uploads | 发送并清空附件"""
    files = st.session_state.uploaded_files
    agent_prompt, display_prompt = build_prompt_with_files(prompt, files)
    st.session_state.messages.append({
        "role": "user",
        "content": display_prompt,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    start_task(agent_prompt)
    st.session_state.uploaded_files.clear()
    st.session_state.file_uploader_key += 1
    st.rerun()


# ── Module D: sidebar extras | 侧边栏扩展 ─────────────────────────────────

def render_sidebar_extras(agent) -> None:
    """Extra sidebar controls | 扩展侧栏控件（强停、宠物、重注入等）"""
    lang = get_lang()
    if st.button(t("reinject_tools")):
        agent.llmclient.last_tools = ""
        try:
            hist_path = os.path.join(SCRIPT_DIR, "..", "assets", "tool_usable_history.json")
            with open(hist_path, encoding="utf-8") as f:
                agent.llmclient.backend.history.extend(json.load(f))
        except Exception:
            pass
        st.toast("下次将重新注入System Prompt")

    if st.button(t("force_stop")):
        agent.abort()
        st.toast("Stop signal sent")
        st.rerun()

    if st.button(t("desktop_pet")):
        kwargs = {"creationflags": 0x08} if sys.platform == "win32" else {}
        pet_script = os.path.join(SCRIPT_DIR, "desktop_pet_v2.pyw")
        if not os.path.exists(pet_script):
            pet_script = os.path.join(SCRIPT_DIR, "desktop_pet.pyw")
        subprocess.Popen([sys.executable, pet_script], **kwargs)

        def _pet_req(q: str) -> None:
            def _do() -> None:
                try:
                    urlopen(f"http://127.0.0.1:41983/?{q}", timeout=2)
                except Exception:
                    pass
            threading.Thread(target=_do, daemon=True).start()

        agent._pet_req = _pet_req
        if not hasattr(agent, "_turn_end_hooks"):
            agent._turn_end_hooks = {}

        def _pet_hook(ctx: dict) -> None:
            parts = [f"Turn {ctx.get('turn', '?')}"]
            if ctx.get("summary"):
                parts.append(ctx["summary"])
            if ctx.get("exit_reason"):
                parts.append("DONE")
            _pet_req(f"msg={quote(chr(10).join(parts))}")
            if ctx.get("exit_reason"):
                _pet_req("state=idle")

        agent._turn_end_hooks["pet"] = _pet_hook
        st.toast("Desktop pet started")

    if lang == "zh":
        st.divider()
        if st.button("开始空闲自主行动"):
            st.session_state.last_reply_time = int(time.time()) - 1800
            st.toast("已将上次回复时间设为1800秒前")
            st.rerun()
        if st.session_state.autonomous_enabled:
            if st.button("⏸️ 禁止自主行动"):
                st.session_state.autonomous_enabled = False
                st.toast("⏸️ 已禁止自主行动")
                st.rerun()
            st.caption("🟢 自主行动运行中，会在你离开它30分钟后自动进行")
        else:
            if st.button("▶️ 允许自主行动", type="primary"):
                st.session_state.autonomous_enabled = True
                st.toast("✅ 已允许自主行动")
                st.rerun()
            st.caption("🔴 自主行动已停止")
