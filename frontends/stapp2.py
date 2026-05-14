import os, sys
import html
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
try: sys.stdout.reconfigure(errors='replace')
except: pass
try: sys.stderr.reconfigure(errors='replace')
except: pass
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
try:
    from streamlit import iframe as _st_iframe  # 1.56+
    _embed_html = lambda html, **kw: _st_iframe(html, **{k: max(v, 1) if isinstance(v, int) else v for k, v in kw.items()})
except (ImportError, AttributeError):
    from streamlit.components.v1 import html as _embed_html  # ≤1.55
import time, json, re, threading, queue
from datetime import datetime
from agentmain import GeneraticAgent

# ─── 新增：文件上传 / 粘贴 / 桌面宠物所需额外导入 ─────────────────────────
import base64, subprocess
from urllib.request import urlopen
from urllib.parse import quote
from io import BytesIO

st.set_page_config(page_title="Cowork", layout="wide")

# ─── 新增：脚本所在目录（用于定位资源文件和桌面宠物脚本） ─────────────────
script_dir = os.path.dirname(os.path.abspath(__file__))

# ─── 新增：国际化支持（GA_LANG 环境变量，默认中文） ───────────────────────
LANG = os.environ.get('GA_LANG', 'zh')
if LANG not in ('zh', 'en'): LANG = 'zh'
I18N = {
    'zh': {'force_stop': '强行停止任务', 'reinject_tools': '重新注入System Prompt', 'desktop_pet': '🐱 桌面宠物'},
    'en': {'force_stop': 'Force Stop',   'reinject_tools': 'Reinject Tools',         'desktop_pet': '🐱 Desktop Pet'},
}
def T(key): return I18N.get(LANG, I18N['zh']).get(key, key)

# ─── Anthropic Light Theme CSS（完整版，来自 old 版，保持不变） ──────────
ANTHROPIC_CSS = """
<style>
/* ===== Root variables ===== */
:root {
    --anthropic-primary: #D4A27F;
    --anthropic-primary-hover: #C4895F;
    --anthropic-bg: #FAF9F6;
    --anthropic-bg-secondary: #EEECE2;
    --anthropic-code-bg: #F4F1EB;
    --anthropic-text: #1A1714;
    --anthropic-text-secondary: #6B6560;
    --anthropic-border: #D5CEC5;
    --anthropic-sidebar-bg: #F0EDE4;
    --anthropic-accent: #CC785C;
    --anthropic-success: #5A8A5E;
    --anthropic-warning: #C4885A;
    --anthropic-error: #C45A5A;
    --anthropic-info: #5A7A8A;
    --anthropic-font: 'Source Sans Pro', sans-serif;
    --anthropic-mono: 'Source Code Pro', monospace;
}

/* ===== Global ===== */
body, [data-testid="stAppViewContainer"] {
    background-color: var(--anthropic-bg) !important;
    color: var(--anthropic-text) !important;
}

.stApp {
    background-color: var(--anthropic-bg) !important;
}

/* ===== Header / Top bar ===== */
[data-testid="stHeader"], header[data-testid="stHeader"] {
    background-color: var(--anthropic-bg) !important;
    border-bottom: 1px solid var(--anthropic-border) !important;
}
/* Hide default Streamlit toolbar buttons (deploy, hamburger, etc.) */
[data-testid="stToolbar"] {
    visibility: hidden !important;
}
[data-testid="stDecoration"],
#MainMenu {
    display: none !important;
    visibility: hidden !important;
}
/* Restore sidebar expand button (lives inside stToolbar) */
[data-testid="stExpandSidebarButton"],
[data-testid="stExpandSidebarButton"] * {
    visibility: visible !important;
}
/* Only restore ancestor divs that contain the sidebar button */
[data-testid="stToolbar"] div:has([data-testid="stExpandSidebarButton"]) {
    visibility: visible !important;
}
/* Make top-left settings/sidebar toggle darker and easier to see */
button[data-testid="stExpandSidebarButton"] {
    visibility: visible !important;
    background: #F4F1EA !important;
    background-color: #F4F1EA !important;
    border: none !important;
    color: #3B2F2A !important;
    border-radius: 10px !important;
    box-shadow: none !important;
}
button[data-testid="stExpandSidebarButton"]:hover {
    background: #EAE4D9 !important;
    background-color: #EAE4D9 !important;
    border-color: transparent !important;
}
button[data-testid="stExpandSidebarButton"],
button[data-testid="stExpandSidebarButton"] *,
button[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {
    color: #3B2F2A !important;
    fill: #3B2F2A !important;
    stroke: #3B2F2A !important;
}
/* Hide other toolbar buttons (deploy, etc.) */
button[kind="header"] {
    visibility: hidden !important;
}

/* ===== Sidebar ===== */
[data-testid="stSidebar"], section[data-testid="stSidebar"] {
    background-color: var(--anthropic-sidebar-bg) !important;
    border-right: 1px solid var(--anthropic-border) !important;
}

[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {
    color: var(--anthropic-text) !important;
}

[data-testid="stSidebar"] hr {
    border-color: var(--anthropic-border) !important;
}

/* ===== Sidebar Selectbox ===== */
[data-testid="stSidebar"] [data-testid="stSelectbox"] {
    width: fit-content !important;
    max-width: 100% !important;
}

[data-testid="stSidebar"] [data-testid="stSelectbox"] > div {
    width: fit-content !important;
    max-width: 100% !important;
}

[data-testid="stSidebar"] [data-testid="stSelectbox"] label,
[data-testid="stSidebar"] .stSelectbox label {
    color: var(--anthropic-text-secondary) !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] {
    width: fit-content !important;
    max-width: 100% !important;
    display: inline-block !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] > div {
    width: fit-content !important;
    max-width: 100% !important;
    background: #F7F3EC !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 12px !important;
    min-height: 42px !important;
    padding-right: 1.6rem !important;
    position: relative !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] > div:hover,
[data-testid="stSidebar"] [data-baseweb="select"] > div:focus-within {
    background: #EFE9DE !important;
    border: none !important;
    box-shadow: none !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] input,
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div {
    color: var(--anthropic-text) !important;
}

[data-testid="stSidebar"] [data-baseweb="select"] span {
    white-space: nowrap !important;
}

[data-baseweb="popover"],
[data-baseweb="menu"],
[data-baseweb="popover"] > div,
[data-baseweb="popover"] [role="presentation"],
[data-baseweb="popover"] ul,
[data-baseweb="popover"] li,
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [role="option"] {
    background: #F7F3EC !important;
    color: var(--anthropic-text) !important;
}

[role="listbox"] {
    background: #F7F3EC !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 14px !important;
    box-shadow: 0 10px 30px rgba(58, 47, 42, 0.12) !important;
    padding: 0.35rem !important;
    color: var(--anthropic-text) !important;
}

[role="option"] {
    color: var(--anthropic-text) !important;
    background: transparent !important;
    border-radius: 10px !important;
}

[role="option"]:hover,
[role="option"][aria-selected="true"] {
    background: #EFE9DE !important;
    color: var(--anthropic-text) !important;
}

/* ===== Title ===== */
h1, .stTitle, [data-testid="stHeading"] h1 {
    color: var(--anthropic-text) !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
}

/* ===== Agent name input fixed in header bar ===== */
[data-testid="stTextInput"] {
    position: fixed !important;
    top: 0 !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    z-index: 999999 !important;
    height: 60px !important;
    display: flex !important;
    align-items: center !important;
    margin: 0 !important;
    padding: 0 !important;
}
/* Hide the empty container left behind */
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] > [data-testid="stElementContainer"]:first-child {
    height: 0 !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
}
[data-testid="stTextInput"] > div {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
    position: relative !important;
}
[data-testid="stTextInput"] > label {
    display: none !important;
}
[data-testid="stTextInput"] input[type="text"] {
    font-size: 1.6rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em !important;
    color: var(--anthropic-text) !important;
    background-color: var(--anthropic-bg) !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 0.3rem 1.8rem 0.3rem 0.5rem !important;
    box-shadow: none !important;
    width: 320px !important;
    text-align: center !important;
    transition: all 0.2s ease !important;
    cursor: default !important;
    caret-color: #1a1714 !important;
}
[data-testid="stTextInput"] input[type="text"]:hover {
    background-color: var(--anthropic-bg-secondary) !important;
    border-radius: 6px !important;
}
[data-testid="stTextInput"] input[type="text"]:focus {
    background-color: var(--anthropic-bg-secondary) !important;
    border-radius: 6px !important;
    box-shadow: none !important;
    cursor: text !important;
    caret-color: #1a1714 !important;
}
/* Edit pencil icon - visible by default, semi-transparent on focus */
[data-testid="stTextInput"] > div::after {
    content: '✎' !important;
    position: absolute !important;
    right: 8px !important;
    top: 50% !important;
    transform: translateY(-50%) !important;
    font-size: 0.9rem !important;
    color: var(--anthropic-text-secondary) !important;
    pointer-events: none !important;
    opacity: 0.6 !important;
    transition: opacity 0.2s ease !important;
}
[data-testid="stTextInput"] > div:hover::after {
    opacity: 0.85 !important;
}
[data-testid="stTextInput"] > div:focus-within::after {
    opacity: 0 !important;
}

h2, h3, h4, h5, h6 {
    color: var(--anthropic-text) !important;
    font-weight: 500 !important;
}

/* ===== Buttons ===== */
.stButton > button {
    background-color: var(--anthropic-bg-secondary) !important;
    color: var(--anthropic-text) !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 8px !important;
    padding: 0.4rem 1rem !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}

.stButton > button:hover {
    background-color: var(--anthropic-primary) !important;
    color: white !important;
    border-color: var(--anthropic-primary) !important;
}

.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background-color: var(--anthropic-primary) !important;
    color: white !important;
    border-color: var(--anthropic-primary) !important;
}

.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    background-color: var(--anthropic-primary-hover) !important;
    border-color: var(--anthropic-primary-hover) !important;
}

/* ===== Chat input ===== */
[data-testid="stChatInput"],
[data-testid="stChatInput"] > div {
    background-color: var(--anthropic-bg) !important;
    border-color: var(--anthropic-border) !important;
}

[data-testid="stChatInput"] {
    margin-bottom: 12px !important;
}

[data-testid="stChatInput"] textarea,
[data-testid="stChatInputTextArea"] {
    color: var(--anthropic-text) !important;
    background-color: var(--anthropic-bg) !important;
    caret-color: #1A1714 !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: var(--anthropic-text-secondary) !important;
    opacity: 0.7 !important;
}

/* Chat input container border */
[data-testid="stChatInput"] > div {
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 12px !important;
    min-height: 60px !important;
    padding: 0.35rem 0.45rem 0.35rem 0.8rem !important;
    align-items: center !important;
    gap: 0.5rem !important;
    transition: none !important;
    animation: none !important;
}

[data-testid="stChatInput"] > div:focus-within {
    border-color: var(--anthropic-primary) !important;
    box-shadow: 0 0 0 2px rgba(212, 162, 127, 0.2) !important;
}

[data-testid="stChatInput"] textarea,
[data-testid="stChatInputTextArea"] {
    min-height: 1.5rem !important;
    padding: 0.35rem 0 !important;
    line-height: 1.5 !important;
    transition: none !important;
    animation: none !important;
}

/* Chat send button */
[data-testid="stChatInput"] button,
[data-testid="stChatInputSubmitButton"] {
    background-color: var(--anthropic-primary) !important;
    color: white !important;
    border-radius: 12px !important;
    width: 60px !important;
    height: 60px !important;
    min-width: 60px !important;
    min-height: 60px !important;
    padding: 0 !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-shrink: 0 !important;
    transition: none !important;
    animation: none !important;
}

[data-testid="stChatInput"] button svg,
[data-testid="stChatInputSubmitButton"] svg,
[data-testid="stChatInput"] button [data-testid="stIconMaterial"],
[data-testid="stChatInputSubmitButton"] [data-testid="stIconMaterial"] {
    width: 1.25rem !important;
    height: 1.25rem !important;
    font-size: 1.25rem !important;
}

[data-testid="stChatInput"] button:hover {
    background-color: var(--anthropic-primary-hover) !important;
}

/* Stop streaming button - fixed at bottom center, above chat input */
.stop-btn-anchor {
    display: none !important;
}

/* Collapse the wrapper so it doesn't push chat bubbles */
[data-testid="stElementContainer"]:has(.stop-btn-anchor) {
    height: 0 !important;
    min-height: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: visible !important;
}

[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) {
    position: fixed !important;
    bottom: 5.75rem !important;
    left: 50% !important;
    transform: translateX(-50%) !important;
    z-index: 1000 !important;
    width: auto !important;
    background: transparent !important;
    pointer-events: none !important;
    gap: 0 !important;
}

[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) > * {
    pointer-events: auto !important;
}

[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) [data-testid="stButton"] {
    margin: 0 !important;
}

[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) [data-testid="stButton"] > button {
    border-radius: 999px !important;
    padding: 0.35rem 1.1rem !important;
    min-height: 2rem !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    line-height: 1 !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12) !important;
    white-space: nowrap !important;
}

[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) [data-testid="stButton"] > button[kind="primary"],
[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) [data-testid="stButton"] > button[data-testid="stBaseButton-primary"] {
    background-color: rgba(212, 162, 127, 0.95) !important;
    border-color: rgba(212, 162, 127, 0.95) !important;
}

[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) [data-testid="stButton"] > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 3px 12px rgba(0,0,0,0.15) !important;
}

/* ===== Chat messages ===== */
[data-testid="stChatMessage"] {
    background-color: var(--anthropic-bg) !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 1rem 1.2rem !important;
    margin-bottom: 0.5rem !important;
}

/* Assistant messages - clean white like Anthropic */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
    background-color: var(--anthropic-bg) !important;
}

/* User messages - subtle bordered box */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background-color: var(--anthropic-bg) !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 12px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
}

/* Chat message text */
[data-testid="stChatMessage"] p,
[data-testid="stChatMessage"] .stMarkdown {
    color: var(--anthropic-text) !important;
    line-height: 1.6 !important;
}

/* Message timestamp */
.msg-timestamp {
    text-align: left;
    font-size: 0.73rem;
    color: var(--anthropic-text-secondary);
    margin-top: -0.3rem;
    margin-bottom: 0.2rem;
    opacity: 0.55;
    font-family: var(--anthropic-mono);
    letter-spacing: 0.02em;
}

/* ===== Chat avatars ===== */
[data-testid="stChatMessageAvatarContainer"] {
    width: 36px !important;
    height: 36px !important;
}
[data-testid="stChatMessageAvatarContainer"] > div,
[data-testid*="stChatMessageAvatar"],
[data-testid*="chatAvatar"] {
    width: 36px !important;
    height: 36px !important;
    border-radius: 50% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    overflow: hidden !important;
}

/* User avatar - warm brown gradient */
[data-testid*="stChatMessageAvatar"]:has(svg),
[data-testid*="chatAvatar"][data-testid*="user"],
[data-testid*="stChatMessageAvatar"][data-testid*="User"],
[data-testid*="stChatMessageAvatar"][data-testid*="user"] {
    background: linear-gradient(145deg, #D8B08A 0%, #B98259 100%) !important;
    border: 1px solid rgba(150, 102, 67, 0.22) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.34), 0 2px 6px rgba(104, 76, 54, 0.10) !important;
}
/* Assistant avatar - cream gradient */
[data-testid*="chatAvatar"][data-testid*="assistant"],
[data-testid*="stChatMessageAvatar"][data-testid*="Assistant"],
[data-testid*="stChatMessageAvatar"][data-testid*="assistant"],
[data-testid="stChatMessageAvatarContainer"] > div {
    background: linear-gradient(145deg, #F6F1E9 0%, #E5D7C7 100%) !important;
    border: 1px solid rgba(187, 165, 141, 0.50) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.72), 0 2px 6px rgba(104, 76, 54, 0.08) !important;
}

/* ===== Inline code (not inside pre/code blocks) ===== */
:not(pre) > code {
    background-color: var(--anthropic-code-bg) !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 4px !important;
    padding: 0.15em 0.4em !important;
    font-size: 0.9em !important;
    color: var(--anthropic-text) !important;
}

/* ===== Code blocks (pre) ===== */
pre, .stCodeBlock, .stCodeBlock pre {
    background-color: var(--anthropic-code-bg) !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 8px !important;
}

/* Code inside pre blocks: no extra border/background */
pre code,
.stCodeBlock code,
[data-testid="stChatMessage"] pre code,
[data-testid="stChatMessage"] .stCodeBlock code {
    background-color: transparent !important;
    border: none !important;
    padding: 0 !important;
    font-size: inherit !important;
    color: var(--anthropic-text) !important;
}

/* ===== Toast / Alerts ===== */
[data-testid="stToast"] {
    background-color: var(--anthropic-bg-secondary) !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 8px !important;
    color: var(--anthropic-text) !important;
}

/* ===== Captions ===== */
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--anthropic-text-secondary) !important;
}

/* ===== Divider ===== */
[data-testid="stHorizontalBlock"] hr,
hr {
    border-color: var(--anthropic-border) !important;
}

/* ===== Scrollbar ===== */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: var(--anthropic-bg);
}
::-webkit-scrollbar-thumb {
    background: var(--anthropic-border);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--anthropic-text-secondary);
}

/* ===== Links ===== */
a {
    color: var(--anthropic-accent) !important;
}
a:hover {
    color: var(--anthropic-primary-hover) !important;
}

/* ===== Error/Warning/Info/Success ===== */
[data-testid="stAlert"] {
    border-radius: 8px !important;
}

/* ===== Bottom padding for chat ===== */
[data-testid="stBottomBlockContainer"] {
    background-color: var(--anthropic-bg) !important;
}

/* ===== Gear icon to open sidebar ===== */
#sidebar-gear-toggle {
    position: fixed !important;
    top: 12px !important;
    left: 12px !important;
    z-index: 999999 !important;
    width: 36px !important;
    height: 36px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 1.3rem !important;
    color: var(--anthropic-text-secondary) !important;
    background: var(--anthropic-bg-secondary) !important;
    border: 1px solid var(--anthropic-border) !important;
    border-radius: 8px !important;
    cursor: pointer !important;
    transition: all 0.2s ease !important;
    opacity: 0.7 !important;
    user-select: none !important;
}
#sidebar-gear-toggle:hover {
    opacity: 1 !important;
    color: var(--anthropic-primary) !important;
    border-color: var(--anthropic-primary) !important;
    transform: rotate(30deg) !important;
}
/* Hide gear when sidebar is open */
body:has([data-testid="stSidebar"][aria-expanded="true"]) #sidebar-gear-toggle {
    display: none !important;
}
</style>
"""

# ─── 新增：文件上传区域样式 ──────────────────────────────────────────────
FILE_UPLOAD_CSS = """
<style>
/* 直接隐藏拖放说明区，不动外层 div，避免 overflow 截断按钮 */
div[data-testid="stFileUploaderDropzoneInstructions"] {
    display: none !important;
}

/* section 去掉边框和内边距，仅做弹性容器居中按钮 */
div[data-testid="stFileUploader"] section {
    padding: 0 !important;
    border: none !important;
    background: transparent !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    min-height: 0 !important;
}

/* Browse files 按钮直接给定 48×48，不使用绝对定位 */
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

/* + 号绘制在按钮中央 */
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

/* 上传+输入行：禁止换行，上传列固定宽度，输入列填满剩余空间 */
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

# ─── 新增：粘贴 / 删除信号输入框隐藏（覆盖 ANTHROPIC_CSS 中的定位规则） ──
# stTextInput 的 header 定位规则来自 ANTHROPIC_CSS，这里专门针对信号输入框覆盖
PASTE_HIDDEN_INPUT_CSS = """
<style>
/* 隐藏粘贴/删除信号输入框及其 Streamlit 包装容器 */
div[data-testid="stTextInput"]:has(input[placeholder="__paste_image_signal__"]),
div[data-testid="stTextInput"]:has(input[placeholder="__delete_file_signal__"]) {
    position: fixed !important;
    left: -99999px !important;
    top: -99999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
    z-index: -1 !important;
}
/* 同时折叠 Streamlit 外层容器，避免占据布局空间 */
div[data-testid="stElementContainer"]:has(input[placeholder="__paste_image_signal__"]),
div[data-testid="stElementContainer"]:has(input[placeholder="__delete_file_signal__"]) {
    height: 0 !important;
    min-height: 0 !important;
    overflow: hidden !important;
    margin: 0 !important;
    padding: 0 !important;
}
</style>
"""

# ─── Selectbox 宽度修正 JS（来自 old 版，保持不变） ──────────────────────
ANTHROPIC_SELECTBOX_SCRIPT = """
<div></div>
<script>
(function() {
    const hostWin = window.parent;
    const doc = hostWin.document;
    const LABEL_TEXT = '备用链路';
    const EXTRA_WIDTH = 56;
    const TIMER_KEY = '__anthropicSelectboxFixedWidthTimer';
    const FONT_LABELS = {
        '100': '标准（100%）',
        '112.5': '偏大（112.5%）',
        '125': '更大（125%）',
        '137.5': '超大（137.5%）'
    };

    function measureTextWidth(text, sourceEl) {
        const canvas = hostWin.__anthropicSelectboxMeasureCanvas || (hostWin.__anthropicSelectboxMeasureCanvas = doc.createElement('canvas'));
        const ctx = canvas.getContext('2d');
        const style = sourceEl ? hostWin.getComputedStyle(sourceEl) : null;
        const font = style ? `${style.fontWeight} ${style.fontSize} ${style.fontFamily}` : '400 14px sans-serif';
        ctx.font = font;
        return Math.ceil(ctx.measureText(text || '').width);
    }

    function ensureSidebarSettingsTitle() {
        const sidebar = doc.querySelector('[data-testid="stSidebar"]');
        if (!sidebar) return;
        const collapseBtn = sidebar.querySelector('button[kind="header"], [data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"]');
        if (!collapseBtn || !collapseBtn.parentElement) return;
        let title = doc.getElementById('custom-sidebar-settings-title');
        if (!title) {
            title = doc.createElement('span');
            title.id = 'custom-sidebar-settings-title';
            title.textContent = '设置';
            title.style.cssText = 'font-size:14px;font-weight:600;color:rgb(38,39,48);margin-right:8px;line-height:1;display:inline-flex;align-items:center;white-space:nowrap;';
        }
        if (collapseBtn.previousElementSibling !== title) {
            collapseBtn.parentElement.insertBefore(title, collapseBtn);
        }
    }

    function applyLiveFontPreview() {
        const sidebar = doc.querySelector('[data-testid="stSidebar"]');
        if (!sidebar) return;
        const sliderLabel = Array.from(sidebar.querySelectorAll('label, p')).find((el) => el.textContent && el.textContent.trim() === '字体大小');
        if (!sliderLabel) return;
        const container = sliderLabel.closest('[data-testid="stWidgetLabel"]')?.parentElement?.parentElement || sliderLabel.closest('[data-testid="stSlider"]') || sliderLabel.closest('div');
        if (!container) return;
        const input = container.querySelector('input[type="range"]');
        if (!input) return;
        const caption = container.querySelector('[data-testid="stCaptionContainer"] p, p');

        const updateFont = () => {
            const raw = parseFloat(input.value);
            if (!Number.isFinite(raw)) return;
            doc.documentElement.style.setProperty('font-size', raw + '%', 'important');
            if (caption) {
                const key = String(raw % 1 === 0 ? raw.toFixed(0) : raw);
                caption.textContent = FONT_LABELS[key] || `${raw.toFixed(1)}%`;
            }
        };

        if (input.dataset.liveFontBound !== '1') {
            input.addEventListener('input', updateFont);
            input.addEventListener('change', updateFont);
            input.dataset.liveFontBound = '1';
        }
        updateFont();
    }

    function applyFixedWidth() {
        const sidebar = doc.querySelector('[data-testid="stSidebar"]');
        if (!sidebar) return;
        const boxes = sidebar.querySelectorAll('[data-testid="stSelectbox"]');
        boxes.forEach((box) => {
            const labelNode = box.querySelector('label [data-testid="stMarkdownContainer"] p, label p');
            if (!labelNode || labelNode.textContent.trim() !== LABEL_TEXT) return;
            const selectRoot = box.querySelector('[data-baseweb="select"]');
            const trigger = selectRoot && selectRoot.firstElementChild;
            const maxLabelNode = box.querySelector('[data-testid="sidebar-llm-max-label"]');
            const text = ((maxLabelNode && maxLabelNode.textContent) || '').trim();
            if (!selectRoot || !trigger || !text) return;

            const textWidth = measureTextWidth(text, trigger);
            const targetWidth = Math.min(sidebar.clientWidth - 32, Math.max(96, textWidth + EXTRA_WIDTH));
            const valueWrap = trigger.firstElementChild;
            const arrowWrap = valueWrap && valueWrap.nextElementSibling;
            const valueNode = valueWrap && valueWrap.querySelector('[value]');

            box.style.setProperty('width', targetWidth + 'px', 'important');
            box.style.setProperty('max-width', targetWidth + 'px', 'important');
            box.style.setProperty('flex', '0 0 ' + targetWidth + 'px', 'important');

            selectRoot.style.setProperty('width', targetWidth + 'px', 'important');
            selectRoot.style.setProperty('min-width', targetWidth + 'px', 'important');
            selectRoot.style.setProperty('max-width', targetWidth + 'px', 'important');

            trigger.style.setProperty('width', targetWidth + 'px', 'important');
            trigger.style.setProperty('min-width', targetWidth + 'px', 'important');
            trigger.style.setProperty('max-width', targetWidth + 'px', 'important');
            trigger.style.setProperty('padding-right', '0px', 'important');
            trigger.style.setProperty('justify-content', 'flex-start', 'important');
            trigger.style.setProperty('box-sizing', 'border-box', 'important');

            if (valueWrap) {
                valueWrap.style.setProperty('flex', '1 1 auto', 'important');
                valueWrap.style.setProperty('min-width', '0px', 'important');
                valueWrap.style.setProperty('max-width', 'calc(100% - 24px)', 'important');
                valueWrap.style.setProperty('padding-right', '4px', 'important');
            }
            if (valueNode) {
                valueNode.style.setProperty('max-width', '100%', 'important');
            }
            if (arrowWrap) {
                arrowWrap.style.setProperty('margin-left', 'auto', 'important');
                arrowWrap.style.setProperty('padding-right', '0px', 'important');
                arrowWrap.style.setProperty('width', '24px', 'important');
                arrowWrap.style.setProperty('min-width', '24px', 'important');
                arrowWrap.style.setProperty('display', 'flex', 'important');
                arrowWrap.style.setProperty('justify-content', 'flex-end', 'important');
                arrowWrap.style.setProperty('align-items', 'center', 'important');
                arrowWrap.style.setProperty('overflow', 'visible', 'important');
            }
        });
        ensureSidebarSettingsTitle();
        applyLiveFontPreview();
    }

    if (hostWin[TIMER_KEY]) {
        hostWin.clearInterval(hostWin[TIMER_KEY]);
    }
    hostWin[TIMER_KEY] = hostWin.setInterval(applyFixedWidth, 300);
    hostWin.setTimeout(applyFixedWidth, 60);
    hostWin.setTimeout(applyFixedWidth, 300);
    hostWin.setTimeout(applyFixedWidth, 1000);
    applyFixedWidth();
})();
</script>
"""

# ─── 核心工具函数（来自 old 版，保持不变） ───────────────────────────────

@st.cache_resource
def init():
    agent = GeneraticAgent()
    if agent.llmclient is None:
        st.error("⚠️ 未配置任何可用的 LLM 接口，请在 mykey.py 中添加 sider_cookie 或 oai_apikey+oai_apibase 等信息后重启。")
        st.stop()
    else:
        threading.Thread(target=agent.run, daemon=True).start()
    return agent


def build_dynamic_font_css(scale_percent: float) -> str:
    root_percent = max(100.0, min(200.0, float(scale_percent)))
    rem_scale = root_percent / 100.0
    return f"""
<style id="dynamic-font-scale-style">
:root, html, body, [data-testid="stAppViewContainer"], .stApp {{
    font-size: {root_percent:.1f}% !important;
}}
body, [data-testid="stAppViewContainer"], .stApp {{
    --app-font-scale: {rem_scale:.3f};
}}
[data-testid="stAppViewContainer"], .stApp, .stApp p, .stApp li, .stApp label,
.stApp div[data-testid="stMarkdownContainer"], .stApp textarea, .stApp input,
.stApp button, .stApp [data-testid="stChatMessageContent"], .stApp .stCaption {{
    font-size: calc(1rem * var(--app-font-scale, 1)) !important;
}}
</style>
"""


def build_dynamic_font_update_script(scale_percent: float) -> str:
    css = json.dumps(build_dynamic_font_css(scale_percent))
    return f"""
<script>
(() => {{
    const cssText = {css};
    const parser = new DOMParser();
    const parsed = parser.parseFromString(cssText, 'text/html');
    const nextStyle = parsed.querySelector('#dynamic-font-scale-style');
    if (!nextStyle) return;
    const hostDoc = window.parent && window.parent.document ? window.parent.document : document;
    const existing = hostDoc.querySelector('#dynamic-font-scale-style');
    if (existing) {{
        existing.textContent = nextStyle.textContent;
    }} else {{
        hostDoc.head.appendChild(nextStyle);
    }}
}})();
</script>
"""


def build_header_agent_badge_script() -> str:
    return """
<script>
(() => {
    const hostWin = window.parent || window;
    const hostDoc = hostWin.document || document;
    const BADGE_ID = 'generic-agent-header-badge';
    const STYLE_ID = 'generic-agent-header-badge-style';

    const ensureStyle = () => {
        if (hostDoc.getElementById(STYLE_ID)) return;
        const style = hostDoc.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
            #${BADGE_ID} {
                position: absolute;
                left: 50%;
                top: 50%;
                transform: translate(-50%, -50%);
                display: inline-flex;
                align-items: center;
                justify-content: center;
                white-space: nowrap;
                font-size: 2.75rem;
                font-weight: 600;
                line-height: 1.2;
                color: #000000;
                padding: 0;
                border-radius: 0;
                background: transparent;
                border: none;
                box-shadow: none;
                pointer-events: none;
                z-index: 20;
            }
        `;
        hostDoc.head.appendChild(style);
    };

    const findHeaderRoot = () => {
        const candidates = [
            'header[data-testid="stHeader"]',
            '[data-testid="stHeader"]',
            'header',
        ];
        for (const selector of candidates) {
            const root = hostDoc.querySelector(selector);
            if (root) return root;
        }
        return null;
    };

    const ensureBadge = () => {
        ensureStyle();
        const headerRoot = findHeaderRoot();
        if (!headerRoot) return;
        headerRoot.style.position = 'relative';

        let badge = hostDoc.getElementById(BADGE_ID);
        if (!badge) {
            badge = hostDoc.createElement('div');
            badge.id = BADGE_ID;
            badge.textContent = 'Generic Agent';
        }
        if (badge.parentElement !== headerRoot) {
            headerRoot.appendChild(badge);
        }

        const titleEl = hostDoc.querySelector('h1');
        if (titleEl) {
            const titleStyle = hostWin.getComputedStyle(titleEl);
            badge.style.fontSize = titleStyle.fontSize;
            badge.style.fontWeight = titleStyle.fontWeight;
            badge.style.lineHeight = titleStyle.lineHeight;
            badge.style.fontFamily = titleStyle.fontFamily;
            badge.style.letterSpacing = titleStyle.letterSpacing;
            badge.style.color = '#000000';
        }
    };

    if (hostWin.__genericAgentHeaderBadgeTimer) {
        hostWin.clearInterval(hostWin.__genericAgentHeaderBadgeTimer);
    }
    hostWin.__genericAgentHeaderBadgeTimer = hostWin.setInterval(ensureBadge, 500);
    hostWin.setTimeout(ensureBadge, 80);
    hostWin.setTimeout(ensureBadge, 400);
    ensureBadge();
})();
</script>
"""

# ─── 新增：文件管理工具函数 ──────────────────────────────────────────────

def save_uploaded_file(file_dict: dict) -> str:
    """保存上传的文件到 temp/uploaded/ 目录，返回绝对路径。"""
    os.makedirs("temp/uploaded", exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._\-一-龥]", "_", file_dict['name'])
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    saved_path = os.path.join("temp", "uploaded", f"{timestamp}_{safe_name}")
    try:
        with open(saved_path, "wb") as f:
            f.write(file_dict['content'])
        return os.path.abspath(saved_path)
    except Exception as e:
        print(f"[ERROR] Failed to save {file_dict['name']}: {e}")
        return ""


def generate_thumbnail(file_dict: dict, size=(80, 80)) -> str:
    """生成文件缩略图，返回 base64 data URI（图片）或 emoji 图标（其他类型）。"""
    if file_dict['type'].startswith('image/'):
        try:
            from PIL import Image
            img = Image.open(BytesIO(file_dict['content']))
            img.thumbnail(size, Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format='PNG')
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f"data:image/png;base64,{b64}"
        except Exception as e:
            print(f"[ERROR] Thumbnail generation failed: {e}")
            return "📷"
    ext = os.path.splitext(file_dict['name'])[1].lower()
    icon_map = {
        '.pdf': '📄', '.txt': '📝', '.md': '📝', '.doc': '📄', '.docx': '📄',
        '.xls': '📊', '.xlsx': '📊', '.csv': '📊',
        '.zip': '📦', '.rar': '📦', '.7z': '📦',
        '.py': '🐍', '.js': '📜', '.json': '📋', '.xml': '📋',
        '.mp3': '🎵', '.wav': '🎵', '.mp4': '🎬', '.avi': '🎬',
    }
    return icon_map.get(ext, '📎')


def build_prompt_with_files(prompt: str, files: list) -> tuple:
    """构建包含文件附件信息的提示，返回 (agent_prompt, display_prompt)。"""
    if not files:
        return prompt, prompt

    attachment_info = ["\n\n[用户上传附件 — 文件已保存到本地磁盘，可用 file_read 工具读取]"]
    for f in files:
        saved_path = save_uploaded_file(f)
        if not saved_path:
            continue
        if f['type'].startswith('image/'):
            b64 = base64.b64encode(f['content']).decode()
            attachment_info.append(
                f"\n- [图片附件] {f['name']} ({f['size']} bytes)"
                f"\n  磁盘路径: {saved_path}"
                f"\n  data:{f['type']};base64,{b64[:100]}...(truncated)"
            )
        elif f['name'].endswith(('.txt', '.md', '.py', '.json', '.log', '.csv', '.yaml', '.yml', '.js', '.ts', '.sql')):
            try:
                text = f['content'].decode('utf-8', errors='replace')
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


def render_file_thumbnails():
    """渲染已上传文件的缩略图，删除按钮通过 JS 写入隐藏信号输入框触发 rerun。"""
    files = st.session_state.uploaded_files
    if not files:
        return

    cards_html = []
    for idx, f in enumerate(files):
        thumb = generate_thumbnail(f)
        safe_name = f['name'].replace('&', '&amp;').replace('"', '&quot;').replace("'", '&#39;').replace('<', '&lt;')
        name_display = safe_name[:18]

        if thumb.startswith('data:image'):
            inner = f'<img src="{thumb}" style="width:100%;height:100%;object-fit:cover;display:block;">'
        else:
            inner = (
                f'<div style="width:100%;height:100%;display:flex;'
                f'align-items:center;justify-content:center;font-size:30px;">'
                f'{thumb}</div>'
            )

        card = (
            f'<div style="position:relative;width:72px;flex-shrink:0;margin-top:6px;">'
            f'  <div style="width:72px;height:72px;border-radius:8px;overflow:hidden;'
            f'              border:1px solid #d5cec5;background:#eeece2;">'
            f'    {inner}'
            f'  </div>'
            f'  <div style="font-size:9px;color:#6b7280;text-align:center;margin-top:3px;'
            f'              white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
            f'              max-width:72px;" title="{safe_name}">{name_display}</div>'
            f'  <div onclick="deleteFile({idx})"'
            f'       style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;'
            f'              border-radius:50%;background:#9ca3af;color:white;font-size:13px;'
            f'              font-weight:bold;display:flex;align-items:center;'
            f'              justify-content:center;cursor:pointer;line-height:1;'
            f'              user-select:none;"'
            f'       onmouseover="this.style.background=\'#ef4444\'"'
            f'       onmouseout="this.style.background=\'#9ca3af\'">&#215;</div>'
            f'</div>'
        )
        cards_html.append(card)

    n_rows = max(1, (len(files) + 7) // 8)
    iframe_height = n_rows * 100 + 10

    full_html = (
        '<!DOCTYPE html><html><head><style>'
        'html,body{margin:0;padding:0;background:transparent;overflow:hidden;}'
        '</style></head><body>'
        '<div style="display:flex;gap:10px;flex-wrap:wrap;'
        'padding:6px 6px 4px 2px;align-items:flex-start;">'
        + ''.join(cards_html)
        + '</div>'
        '<script>'
        'function deleteFile(idx){'
        '  try{'
        '    var hw=window.parent;'
        '    var hd=hw.document;'
        '    var inp=hd.querySelector(\'input[placeholder="__delete_file_signal__"]\');'
        '    if(!inp)return;'
        '    var s=Object.getOwnPropertyDescriptor(hw.HTMLInputElement.prototype,"value").set;'
        '    s.call(inp,String(idx));'
        '    inp.dispatchEvent(new Event("input",{bubbles:true}));'
        '    setTimeout(function(){'
        '      inp.dispatchEvent(new Event("blur",{bubbles:false}));'
        '      inp.dispatchEvent(new Event("focusout",{bubbles:true}));'
        '    },100);'
        '  }catch(e){console.error("deleteFile:",e);}'
        '}'
        '</script>'
        '</body></html>'
    )
    _embed_html(full_html, height=iframe_height)


@st.dialog("文件预览", width="large")
def preview_file_dialog():
    """文件预览模态对话框。"""
    idx = st.session_state.preview_file_idx
    if idx is None or idx >= len(st.session_state.uploaded_files):
        return
    f = st.session_state.uploaded_files[idx]
    st.subheader(f"📎 {f['name']}")
    st.caption(f"类型: {f['type']} | 大小: {f['size']:,} bytes")
    if f['type'].startswith('image/'):
        st.image(f['content'], use_container_width=True)
    elif f['name'].endswith(('.txt', '.md', '.py', '.json', '.log', '.csv', '.yaml', '.yml', '.js', '.ts', '.sql')):
        try:
            text = f['content'].decode('utf-8', errors='replace')
            st.code(text[:5000], language=None)
            if len(text) > 5000:
                st.info("内容已截断至前 5000 字符")
        except Exception as e:
            st.error(f"无法显示文件内容: {e}")
    else:
        st.info("此文件类型不支持预览")
        st.json({"文件名": f['name'], "类型": f['type'], "大小": f"{f['size']:,} bytes"})
    if st.button("关闭", use_container_width=True):
        st.session_state.preview_file_idx = None
        st.rerun()


# ─── 新增：粘贴监听脚本（捕获剪贴板图片，写入隐藏信号输入框触发 rerun） ──
def build_paste_listener_script() -> str:
    return """
<script>
(function() {
    var hostWin = window.parent || window;
    var hostDoc = hostWin.document || document;

    // 幂等：只安装一次粘贴监听
    if (hostWin.__pasteImageListenerInstalled__) return;
    hostWin.__pasteImageListenerInstalled__ = true;

    hostDoc.addEventListener('paste', function(e) {
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        for (var i = 0; i < items.length; i++) {
            var item = items[i];
            if (item.type && item.type.startsWith('image/')) {
                var blob = item.getAsFile();
                if (!blob) continue;
                (function(b) {
                    var reader = new FileReader();
                    reader.onload = function(ev) {
                        var b64 = ev.target.result;
                        var input = hostDoc.querySelector(
                            'input[placeholder="__paste_image_signal__"]'
                        );
                        if (!input) return;
                        var setter = Object.getOwnPropertyDescriptor(
                            hostWin.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(input, b64);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        setTimeout(function() {
                            input.dispatchEvent(new Event('blur', { bubbles: false }));
                            input.dispatchEvent(new Event('focusout', { bubbles: true }));
                        }, 100);
                    };
                    reader.readAsDataURL(b);
                })(blob);
                break;
            }
        }
    });
})();
</script>
"""

# ─── 应用初始化 ──────────────────────────────────────────────────────────

agent = init()

def init_session_state():
    for key, value in {
        # 原有状态变量（来自 old 版）
        'agent_name': 'GenericAgent', 'streaming': False, 'stopping': False, 'display_queue': None,
        'partial_response': '', 'reply_ts': '', 'current_prompt': '', 'selected_llm_idx': agent.llm_no,
        'autonomous_enabled': False, 'messages': [],
        # 新增：文件上传状态
        'uploaded_files': [],       # [{'name', 'type', 'size', 'content'}, ...]
        'file_uploader_key': 0,     # 用于重置 file_uploader widget
        'preview_file_idx': None,   # 当前预览的文件索引
    }.items(): st.session_state.setdefault(key, value)

init_session_state()

# 注入主题 CSS 和脚本（来自 old 版，全部恢复）
st.markdown(ANTHROPIC_CSS, unsafe_allow_html=True)
st.markdown(build_dynamic_font_css(110.0), unsafe_allow_html=True)
_embed_html(ANTHROPIC_SELECTBOX_SCRIPT, height=0, width=0)
_embed_html(build_header_agent_badge_script(), height=0, width=0)
# 新增：文件上传 & 粘贴支持的 CSS 和脚本
st.markdown(FILE_UPLOAD_CSS, unsafe_allow_html=True)
st.markdown(PASTE_HIDDEN_INPUT_CSS, unsafe_allow_html=True)
_embed_html(build_paste_listener_script(), height=0, width=0)

st.session_state.agent_name = 'Generic Agent'
with st.chat_message("assistant"):
    st.markdown(f'<div class="msg-timestamp">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>', unsafe_allow_html=True)
    st.write("欢迎使用GenericAgent~")


# ─── 侧边栏（基于 old 版，新增额外功能按钮） ─────────────────────────────
@st.fragment
def render_sidebar():
    llm_options, current_idx = agent.list_llms(), agent.llm_no
    st.session_state.selected_llm_idx = current_idx
    llm_labels = {idx: f"{idx}: {(name or '').strip()}" for idx, name, _ in llm_options}
    st.caption(f"当前使用的LLM为：{current_idx}: {agent.get_llm_name()}", help="可在下方选择链路")
    st.markdown(f'<div data-testid="sidebar-llm-max-label" style="display:none">{html.escape(max(llm_labels.values(), key=len, default=""))}</div>', unsafe_allow_html=True)
    selected_idx = st.selectbox("选择链路：", [idx for idx, _, _ in llm_options], index=next((i for i, (idx, _, _) in enumerate(llm_options) if idx == current_idx), 0), format_func=llm_labels.get, key="sidebar_llm_select")
    if selected_idx != current_idx:
        agent.next_llm(selected_idx)
        st.session_state.selected_llm_idx = selected_idx
        st.toast(f"已切换到备用链路：{llm_labels[selected_idx]}")
        st.rerun()
    st.divider()
    # 重注入 System Prompt（来自 old 版，新增：额外加载 tool_usable_history.json）
    if st.button(T('reinject_tools')):
        agent.llmclient.last_tools = ''
        try:
            hist_path = os.path.join(script_dir, '..', 'assets', 'tool_usable_history.json')
            with open(hist_path, 'r', encoding='utf-8') as f_:
                tool_hist = json.load(f_)
            agent.llmclient.backend.history.extend(tool_hist)
        except Exception:
            pass
        st.toast("下次将重新注入System Prompt")
    # 新增：强行停止任务（不依赖 streaming 状态，随时可用）
    if st.button(T('force_stop')):
        agent.abort()
        st.toast("Stop signal sent")
        st.rerun()
    # 新增：桌面宠物启动按钮
    if st.button(T('desktop_pet')):
        kwargs = {'creationflags': 0x08} if sys.platform == 'win32' else {}
        pet_script = os.path.join(script_dir, 'desktop_pet_v2.pyw')
        if not os.path.exists(pet_script):
            pet_script = os.path.join(script_dir, 'desktop_pet.pyw')
        subprocess.Popen([sys.executable, pet_script], **kwargs)
        # 注入回调：agent 每个 turn 结束后通知桌面宠物显示状态
        def _pet_req(q):
            def _do():
                try: urlopen(f'http://127.0.0.1:41983/?{q}', timeout=2)
                except Exception: pass
            threading.Thread(target=_do, daemon=True).start()
        agent._pet_req = _pet_req
        if not hasattr(agent, '_turn_end_hooks'):
            agent._turn_end_hooks = {}
        def _pet_hook(ctx):
            parts = [f"Turn {ctx.get('turn', '?')}"]
            if ctx.get('summary'): parts.append(ctx['summary'])
            if ctx.get('exit_reason'): parts.append('DONE')
            _pet_req(f'msg={quote(chr(10).join(parts))}')
            if ctx.get('exit_reason'): _pet_req('state=idle')
        agent._turn_end_hooks['pet'] = _pet_hook
        st.toast("Desktop pet started")
    # 新增：自主行动控制（仅中文模式显示）
    if LANG == 'zh':
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

with st.sidebar: render_sidebar()


# ─── Agent 任务控制（来自 old 版，保持不变） ─────────────────────────────

def start_agent_task(prompt):
    st.session_state.display_queue = agent.put_task(prompt, source="user")
    st.session_state.streaming, st.session_state.stopping, st.session_state.partial_response = True, False, ''
    st.session_state.reply_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.current_prompt = prompt


def poll_agent_output(max_items=20):
    q = st.session_state.display_queue
    if q is None:
        st.session_state.streaming = False
        return False
    done = False
    for _ in range(max_items):
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if 'next' in item: st.session_state.partial_response = item['next']
        if 'done' in item:
            st.session_state.partial_response = item['done']
            done = True
            break
    if done: st.session_state.streaming = st.session_state.stopping = False; st.session_state.display_queue = None
    return done


def _get_response_segments(text):
    return [p for p in re.split(r'(?=\*\*LLM Running \(Turn \d+\) \.\.\.\*\*)', text) if p.strip()] or [text]


# render_message：新增 intermediate 参数，用于将多轮推理中间段折叠为 expander
# old 版调用时不传此参数，行为与 old 版完全相同
def render_message(role, content, ts='', unsafe_allow_html=True, intermediate=False):
    with st.chat_message(role):
        if ts: st.markdown(f'<div class="msg-timestamp">{ts}</div>', unsafe_allow_html=True)
        if intermediate:
            # 中间推理轮次：用 expander 折叠，标签显示 "Turn N · 推理过程"
            m = re.match(r'^\*\*LLM Running \(Turn (\d+)\)', content.strip())
            label = f"Turn {m.group(1)} · 推理过程" if m else "推理过程"
            with st.expander(label, expanded=False):
                st.markdown(content, unsafe_allow_html=unsafe_allow_html)
        else:
            st.markdown(content, unsafe_allow_html=unsafe_allow_html)


# finish_streaming_message：新增 intermediate 标记，用于历史消息回放时折叠中间段
def finish_streaming_message():
    reply_ts = st.session_state.reply_ts
    segments = _get_response_segments(st.session_state.partial_response)
    for i, seg in enumerate(segments):
        # 非最后一段且格式匹配，才标记为中间推理轮次
        is_intermediate = (i < len(segments) - 1) and bool(
            re.match(r'^\*\*LLM Running \(Turn \d+\)', seg.strip())
        )
        st.session_state.messages.append({
            "role": "assistant",
            "content": seg,
            "time": reply_ts,
            "intermediate": is_intermediate,
        })
    st.session_state.last_reply_time = int(time.time())
    st.session_state.partial_response = st.session_state.reply_ts = st.session_state.current_prompt = ''


def render_streaming_area():
    if not st.session_state.streaming: return
    with st.container():
        st.markdown('<span class="stop-btn-anchor"></span>', unsafe_allow_html=True)
        if st.button("⏹️ 停止生成", type="primary"):
            agent.abort(); st.session_state.stopping = True; st.toast("已发送停止信号"); st.rerun()
    reply_ts = st.session_state.reply_ts
    with st.empty().container():
        segments = _get_response_segments(st.session_state.partial_response)
        for i, seg in enumerate(segments):
            is_last = (i == len(segments) - 1)
            is_intermediate = (not is_last) and bool(
                re.match(r'^\*\*LLM Running \(Turn \d+\)', seg.strip())
            )
            render_message(
                "assistant",
                seg + ("" if not is_last else "▌"),
                ts=reply_ts,
                unsafe_allow_html=False,
                intermediate=is_intermediate,
            )
    if poll_agent_output(): finish_streaming_message()
    else: time.sleep(0.2)
    st.rerun()


# ─── 主流程 ──────────────────────────────────────────────────────────────

# 历史消息渲染（来自 old 版，新增 intermediate 参数传递）
for msg in st.session_state.messages:
    render_message(msg["role"], msg["content"], ts=msg.get("time", ""),
                   unsafe_allow_html=True, intermediate=msg.get("intermediate", False))

if st.session_state.streaming: render_streaming_area()

# ─── 新增：粘贴图片处理（隐藏信号输入框 + 解码逻辑） ─────────────────────
_paste_val = st.session_state.get("paste_image_signal", "")
if _paste_val and _paste_val.startswith("data:image"):
    try:
        _header, _b64str = _paste_val.split(",", 1)
        _mime = _header.split(":")[1].split(";")[0]
        _ext = _mime.split("/")[1]
        _content = base64.b64decode(_b64str)
        if len(_content) <= 10 * 1024 * 1024:
            _fname = f"pasted_{datetime.now().strftime('%H%M%S%f')[:12]}.{_ext}"
            st.session_state.uploaded_files.append({
                'name': _fname, 'type': _mime,
                'size': len(_content), 'content': _content,
            })
    except Exception:
        pass
    st.session_state.paste_image_signal = ""
    st.rerun()

st.text_input("paste_signal", value="", key="paste_image_signal",
              label_visibility="collapsed", placeholder="__paste_image_signal__")

# ─── 新增：删除文件信号处理 ───────────────────────────────────────────────
_del_val = st.session_state.get("delete_file_signal", "")
if _del_val and _del_val.isdigit():
    idx = int(_del_val)
    if 0 <= idx < len(st.session_state.uploaded_files):
        st.session_state.uploaded_files.pop(idx)
    st.session_state.delete_file_signal = ""
    st.rerun()

st.text_input("delete_signal", value="", key="delete_file_signal",
              label_visibility="collapsed", placeholder="__delete_file_signal__")

# ─── 新增：文件缩略图 + 输入区域布局 [文件上传按钮 | 聊天输入框] ──────────
render_file_thumbnails()
col_upload, col_input = st.columns([0.08, 0.92])

with col_upload:
    uploaded_files = st.file_uploader(
        "上传文件", accept_multiple_files=True, label_visibility="collapsed",
        key=f"file_uploader_{st.session_state.file_uploader_key}",
        help="点击上传图片、文档等文件",
    )
    if uploaded_files:
        for uf in uploaded_files:
            if any(f['name'] == uf.name for f in st.session_state.uploaded_files):
                continue
            content = uf.read()
            if len(content) > 10 * 1024 * 1024:
                st.warning(f"文件 {uf.name} 超过 10MB，已跳过")
                continue
            st.session_state.uploaded_files.append({
                'name': uf.name,
                'type': uf.type if uf.type else 'application/octet-stream',
                'size': len(content), 'content': content,
            })
        st.session_state.file_uploader_key += 1
        st.rerun()

with col_input:
    prompt = st.chat_input("请输入指令", disabled=st.session_state.streaming)

# 消息发送（来自 old 版，新增文件附件构建和发送后清空逻辑）
if prompt:
    files = st.session_state.uploaded_files
    agent_prompt, display_prompt = build_prompt_with_files(prompt, files)
    st.session_state.messages.append({
        "role": "user", "content": display_prompt,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    start_agent_task(agent_prompt)
    # 新增：发送后清空已上传文件列表
    st.session_state.uploaded_files.clear()
    st.session_state.file_uploader_key += 1
    st.rerun()
