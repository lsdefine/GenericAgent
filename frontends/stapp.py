import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from urllib.parse import quote
from urllib.request import urlopen

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass
try:
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

script_dir = os.path.dirname(__file__)
repo_dir = os.path.abspath(os.path.join(script_dir, ".."))
if repo_dir not in sys.path:
    sys.path.append(repo_dir)
if script_dir not in sys.path:
    sys.path.append(script_dir)

import streamlit as st

from shared_runtime import get_shared_runtime

st.set_page_config(page_title="Cowork", layout="wide", initial_sidebar_state="expanded")

service, agent = get_shared_runtime()
if agent.llmclient is None:
    st.error("No LLM routes are available. Configure mykey.py or import structured routes first.")
    st.stop()

st.markdown(
    """
    <style>
    :root {
        --chat-bg: #09111f;
        --chat-card: rgba(15, 23, 42, 0.88);
        --chat-line: rgba(148, 163, 184, 0.16);
        --chat-text: #e5eefc;
        --chat-muted: #9aacbf;
        --chat-accent: #60a5fa;
        --chat-ok: #22c55e;
        --chat-error: #ef4444;
    }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background:
            radial-gradient(circle at top right, rgba(96, 165, 250, 0.12), transparent 28%),
            linear-gradient(180deg, #07101f 0%, #0b1020 100%);
        color: var(--chat-text);
    }
    .block-container {
        max-width: 1320px;
        padding-top: 1.2rem;
        padding-bottom: 1.5rem;
    }
    [data-testid="stSidebar"] {
        background: rgba(9, 14, 28, 0.88);
        border-right: 1px solid var(--chat-line);
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 18px;
        border-color: var(--chat-line);
        background: linear-gradient(180deg, rgba(17, 24, 39, 0.92), rgba(15, 23, 42, 0.86));
    }
    div[data-testid="stButton"] > button,
    div[data-testid="stFormSubmitButton"] > button {
        border-radius: 14px;
    }
    .ga-chat-hero {
        border: 1px solid var(--chat-line);
        border-radius: 24px;
        background: linear-gradient(135deg, rgba(17, 24, 39, 0.94), rgba(30, 41, 59, 0.88));
        padding: 1rem 1.1rem;
        margin-bottom: 1rem;
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.24);
    }
    .ga-chat-title {
        margin: 0;
        font-size: 1.3rem;
        font-weight: 700;
        letter-spacing: -0.03em;
        color: #f8fbff;
    }
    .ga-chat-subtitle {
        margin: 0.3rem 0 0 0;
        color: var(--chat-muted);
        font-size: 0.92rem;
    }
    .ga-chat-chip {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        border-radius: 999px;
        padding: 0.22rem 0.66rem;
        font-size: 0.76rem;
        font-weight: 600;
        margin-right: 0.35rem;
        margin-top: 0.35rem;
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.08);
        color: #eef4ff;
    }
    .ga-chat-chip.ok { background: rgba(34, 197, 94, 0.16); color: #b4efca; }
    .ga-chat-chip.blue { background: rgba(96, 165, 250, 0.18); color: #cfe1ff; }
    .ga-chat-chip.error { background: rgba(239, 68, 68, 0.16); color: #fecaca; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "autonomous_enabled" not in st.session_state:
    st.session_state.autonomous_enabled = False
if "messages" not in st.session_state:
    st.session_state.messages = []


def get_snapshot():
    return service.get_ui_snapshot(agent)


def route_label(route):
    if route["kind"] == "single":
        provider = (route["provider"] or {}).get("name") or "No provider"
        return f"{route['name']} | {provider}"
    members = " -> ".join(member["name"] for member in route["members"]) or "No members"
    return f"{route['name']} | {members}"


def activate_route(route_id):
    try:
        agent.set_active_route(route_id)
        st.toast(f"Switched route to {route_id}")
        st.rerun()
    except Exception as exc:
        st.error(str(exc))


def render_route_banner():
    snapshot = get_snapshot()
    active = snapshot["active_route_summary"]
    routes = snapshot["routes"]
    route_ids = [route["id"] for route in routes]
    if not route_ids:
        return
    active_route_id = snapshot["active_route_id"] if snapshot["active_route_id"] in route_ids else route_ids[0]
    route_error = active.get("last_error_message") or "No recent error"
    st.markdown(
        f"""
        <div class="ga-chat-hero">
          <p class="ga-chat-title">{active.get('route_name') or 'No active route'}</p>
          <p class="ga-chat-subtitle">{active.get('provider_name') or 'No provider'} | {active.get('model') or 'No model'} | {active.get('backend_class') or 'No backend'}</p>
          <span class="ga-chat-chip blue">{active.get('route_kind') or 'unknown'}</span>
          <span class="ga-chat-chip {'ok' if active.get('native_tools') else ''}">{'native tools' if active.get('native_tools') else 'text tools'}</span>
          <span class="ga-chat-chip">{active.get('active_member_name') or 'no active member'}</span>
          <span class="ga-chat-chip {'error' if active.get('last_error_kind') else 'ok'}">{active.get('last_error_kind') or 'healthy'}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([2.2, 1.1, 1.1, 1.3])
    selected_route = cols[0].selectbox(
        "Route",
        options=route_ids,
        index=route_ids.index(active_route_id),
        format_func=lambda rid: route_label(snapshot["routes_by_id"][rid]),
        key="chat_route_banner_select",
    )
    if selected_route != active_route_id:
        activate_route(selected_route)
    cols[1].caption(f"API Mode: {active.get('api_mode') or 'n/a'}")
    cols[1].caption(f"Active Member: {active.get('active_member_name') or 'n/a'}")
    cols[2].caption(f"Last OK: {active.get('last_ok_at') or 'n/a'}")
    cols[2].caption(f"Last Error: {active.get('last_error_at') or 'n/a'}")
    if hasattr(st, "page_link"):
        cols[3].page_link("pages/1_GA_Switch_Admin.py", label="Open GA Switch Admin", icon="🧭")
    cols[3].caption(route_error[:120])


@st.fragment
def render_sidebar():
    snapshot = get_snapshot()
    active = snapshot["active_route_summary"]
    route_ids = [route["id"] for route in snapshot["routes"]]
    st.caption(f"Current route: {active.get('route_name') or 'n/a'}")
    if route_ids:
        selected_route = st.selectbox(
            "Switch route",
            options=route_ids,
            index=route_ids.index(snapshot["active_route_id"]) if snapshot["active_route_id"] in route_ids else 0,
            format_func=lambda rid: route_label(snapshot["routes_by_id"][rid]),
            key="chat_route_sidebar_select",
        )
        if selected_route != snapshot["active_route_id"]:
            activate_route(selected_route)
    st.caption(f"Provider: {active.get('provider_name') or 'n/a'}")
    st.caption(f"Model: {active.get('model') or 'n/a'}")
    st.caption(f"Backend: {active.get('backend_class') or 'n/a'}")
    st.caption(f"Active member: {active.get('active_member_name') or 'n/a'}")
    if active.get("last_error_message"):
        st.warning(active["last_error_message"][:160])
    if hasattr(st, "page_link"):
        st.page_link("pages/1_GA_Switch_Admin.py", label="Open GA Switch Admin", icon="🧭")
    if st.button("Abort current task", use_container_width=True):
        agent.abort()
        st.toast("Abort signal sent")
        st.rerun()
    if st.button("Re-inject tool schema", use_container_width=True):
        if hasattr(agent.llmclient, "last_tools"):
            agent.llmclient.last_tools = ""
        try:
            hist_path = os.path.join(script_dir, "..", "assets", "tool_usable_history.json")
            with open(hist_path, "r", encoding="utf-8") as f:
                tool_hist = json.load(f)
            agent.llmclient.backend.history.extend(tool_hist)
            st.toast(f"Injected {len(tool_hist)} tool history entries")
        except Exception as exc:
            st.toast(f"Tool history injection failed: {exc}")
    if st.button("Desktop pet", use_container_width=True):
        kwargs = {"creationflags": 0x08} if sys.platform == "win32" else {}
        pet_script = os.path.join(script_dir, "desktop_pet_v2.pyw")
        if not os.path.exists(pet_script):
            pet_script = os.path.join(script_dir, "desktop_pet.pyw")
        subprocess.Popen([sys.executable, pet_script], **kwargs)

        def pet_request(query):
            def _do():
                try:
                    urlopen(f"http://127.0.0.1:41983/?{query}", timeout=2)
                except Exception:
                    pass

            threading.Thread(target=_do, daemon=True).start()

        agent._pet_req = pet_request
        if not hasattr(agent, "_turn_end_hooks"):
            agent._turn_end_hooks = {}

        def pet_hook(ctx):
            parts = [f"Turn {ctx.get('turn', '?')}"]
            if ctx.get("summary"):
                parts.append(ctx["summary"])
            if ctx.get("exit_reason"):
                parts.append("Task completed")
            pet_request(f"msg={quote(chr(10).join(parts))}")
            if ctx.get("exit_reason"):
                pet_request("state=idle")

        agent._turn_end_hooks["pet"] = pet_hook
        st.toast("Desktop pet started")
    st.divider()
    if st.button("Start autonomous idle mode", use_container_width=True):
        st.session_state.last_reply_time = int(time.time()) - 1800
        st.toast("Idle timer moved back by 1800 seconds")
        st.rerun()
    if st.session_state.autonomous_enabled:
        if st.button("Disable autonomous mode", use_container_width=True):
            st.session_state.autonomous_enabled = False
            st.toast("Autonomous mode disabled")
            st.rerun()
        st.caption("Autonomous mode will trigger after 30 minutes of inactivity.")
    else:
        if st.button("Enable autonomous mode", type="primary", use_container_width=True):
            st.session_state.autonomous_enabled = True
            st.toast("Autonomous mode enabled")
            st.rerun()
        st.caption("Autonomous mode is currently disabled.")


with st.sidebar:
    render_sidebar()

st.title("Cowork")
render_route_banner()


def fold_turns(text):
    parts = re.split(r"(\**LLM Running \(Turn \d+\) \.\.\.\*\**)", text)
    if len(parts) < 4:
        return [{"type": "text", "content": text}]
    segments = []
    if parts[0].strip():
        segments.append({"type": "text", "content": parts[0]})
    turns = []
    for idx in range(1, len(parts), 2):
        marker = parts[idx]
        content = parts[idx + 1] if idx + 1 < len(parts) else ""
        turns.append((marker, content))
    for idx, (marker, content) in enumerate(turns):
        if idx < len(turns) - 1:
            content_no_think = re.sub(r"```.*?```|<thinking>.*?</thinking>", "", content, flags=re.DOTALL)
            matches = re.findall(r"<summary>\s*((?:(?!<summary>).)*?)\s*</summary>", content_no_think, re.DOTALL)
            if matches:
                title = matches[0].strip().split("\n")[0]
                if len(title) > 50:
                    title = title[:50] + "..."
            else:
                title = marker.strip("*")
            segments.append({"type": "fold", "title": title, "content": content})
        else:
            segments.append({"type": "text", "content": marker + content})
    return segments


def render_segments(segments, suffix=""):
    for segment in segments:
        if segment["type"] == "fold":
            with st.expander(segment["title"], expanded=False):
                st.markdown(segment["content"])
        else:
            st.markdown(segment["content"] + suffix)


def agent_backend_stream(prompt):
    display_queue = agent.put_task(prompt, source="user")
    response = ""
    try:
        while True:
            try:
                item = display_queue.get(timeout=1)
            except queue.Empty:
                yield response
                continue
            if "next" in item:
                response = item["next"]
                yield response
            if "done" in item:
                yield item["done"]
                break
    finally:
        agent.abort()


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        slot = st.empty()
        with slot.container():
            if msg["role"] == "assistant":
                render_segments(fold_turns(msg["content"]))
            else:
                st.markdown(msg["content"])

try:
    from streamlit import iframe as _st_iframe

    _embed_html = lambda html, **kw: _st_iframe(html, **{k: max(v, 1) if isinstance(v, int) else v for k, v in kw.items()})
except (ImportError, AttributeError):
    from streamlit.components.v1 import html as _embed_html

_js_scroll_fix = (
    "!function(){var p=window.parent;if(p.__sfx)return;p.__sfx=1;"
    "var d=p.document;setInterval(function(){"
    "var m=d.querySelector('section.main');if(!m)return;"
    "var b=m.querySelector('.block-container');if(!b)return;"
    "if(m.scrollHeight>b.scrollHeight+150){m.style.overflow='hidden';void m.offsetHeight;m.style.overflow=''}"
    "},3000)}()"
)
_js_ime_fix = (
    ""
    if os.name == "nt"
    else "!function(){if(window.parent.__imeFix)return;window.parent.__imeFix=1;"
    "var d=window.parent.document,c=0;"
    "d.addEventListener('compositionstart',()=>c=1,!0);"
    "d.addEventListener('compositionend',()=>c=0,!0);"
    "function f(){d.querySelectorAll('textarea[data-testid=stChatInputTextArea]').forEach(function(t){"
    "if(t.__imeFix)return;t.__imeFix=1;t.addEventListener('keydown',function(e){"
    "if(e.key==='Enter'&&!e.shiftKey&&(e.isComposing||c||e.keyCode===229)){e.stopImmediatePropagation();e.preventDefault();}"
    "},!0);});}"
    "f();new MutationObserver(f).observe(d.body,{childList:1,subtree:1})}()"
)
_embed_html(f"<script>{_js_scroll_fix};{_js_ime_fix}</script>", height=0)

if prompt := st.chat_input("Any task?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    if hasattr(agent, "_pet_req") and not prompt.startswith("/"):
        agent._pet_req("state=walk")
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        frozen = 0
        live = st.empty()
        response = ""
        cursor = " ▍"
        for response in agent_backend_stream(prompt):
            segments = fold_turns(response)
            completed = max(0, len(segments) - 1)
            while frozen < completed:
                with live.container():
                    render_segments([segments[frozen]])
                live = st.empty()
                frozen += 1
            with live.container():
                render_segments([segments[-1]], suffix=cursor)
        segments = fold_turns(response)
        for idx in range(frozen, len(segments)):
            with live.container():
                render_segments([segments[idx]])
            if idx < len(segments) - 1:
                live = st.empty()
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.session_state.last_reply_time = int(time.time())

if st.session_state.autonomous_enabled:
    st.markdown(
        f"""<div id="last-reply-time" style="display:none">{st.session_state.get('last_reply_time', int(time.time()))}</div>""",
        unsafe_allow_html=True,
    )
