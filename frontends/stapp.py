import os, sys, subprocess
from urllib.request import urlopen
from urllib.parse import quote
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
try: sys.stdout.reconfigure(errors='replace')
except: pass
try: sys.stderr.reconfigure(errors='replace')
except: pass
script_dir = os.path.dirname(__file__)
sys.path.append(os.path.abspath(os.path.join(script_dir, '..')))
sys.path.append(os.path.abspath(script_dir))

import streamlit as st
import time, json, re, threading, queue
from agentmain import GeneraticAgent
import chatapp_common  # activate /continue command (monkey patches GeneraticAgent)
from continue_cmd import handle_frontend_command, reset_conversation, list_sessions, extract_ui_messages
from btw_cmd import handle_frontend_command as btw_handle_frontend

st.set_page_config(page_title="Cowork", layout="wide")

LANG = os.environ.get('GA_LANG', 'zh')
if LANG not in ('zh', 'en'): LANG = 'zh'
I18N = {
    'zh': {
        'force_stop': '强行停止任务',
        'reinject_tools': '重新注入工具',
        'desktop_pet': '🐱 桌面宠物',
    },
    'en': {
        'force_stop': 'Force Stop',
        'reinject_tools': 'Reinject Tools',
        'desktop_pet': '🐱 Desktop Pet',
    },
}
def T(key): return I18N.get(LANG, I18N['zh']).get(key, key)

@st.cache_resource
def init():
    agent = GeneraticAgent()
    if agent.llmclient is None:
        st.error("⚠️ Please set mykey.py!")
        st.stop()
    else: threading.Thread(target=agent.run, daemon=True).start()
    return agent

agent = init()

st.title("🖥️ Cowork")

st.session_state.setdefault('autonomous_enabled', False)

@st.fragment
def render_sidebar():
    st.session_state.setdefault('autonomous_enabled', False)
    llm_options = agent.list_llms()
    current_idx = agent.llm_no
    llm_labels = {idx: f"{idx}: {(name or '').strip()}" for idx, name, _ in llm_options}
    st.caption(f"LLM Core: {llm_labels.get(current_idx, str(current_idx))}")
    selected_idx = st.selectbox("LLM", [idx for idx, _, _ in llm_options], index=next((i for i, (idx, _, _) in enumerate(llm_options) if idx == current_idx), 0), format_func=llm_labels.get, label_visibility="collapsed", key="sidebar_llm_select")
    if selected_idx != current_idx:
        agent.next_llm(selected_idx); st.rerun(scope="fragment")
    if st.button(T('force_stop')):
        agent.abort(); st.toast("Stop signal sended"); st.rerun()
    if st.button(T('reinject_tools')):
        agent.llmclient.last_tools = ''
        try:
            hist_path = os.path.join(script_dir, '..', 'assets', 'tool_usable_history.json')
            with open(hist_path, 'r', encoding='utf-8') as f: tool_hist = json.load(f)
            agent.llmclient.backend.history.extend(tool_hist)
            st.toast(f"Tools injected")
        except Exception as e: st.toast(f"Injected tools failed: {e}")
    if st.button(T('desktop_pet')):
        kwargs = {'creationflags': 0x08} if sys.platform == 'win32' else {}
        pet_script = os.path.join(script_dir, 'desktop_pet_v2.pyw')
        if not os.path.exists(pet_script): pet_script = os.path.join(script_dir, 'desktop_pet.pyw')
        subprocess.Popen([sys.executable, pet_script], **kwargs)
        def _pet_req(q):
            def _do():
                try: urlopen(f'http://127.0.0.1:41983/?{q}', timeout=2)
                except Exception: pass
            threading.Thread(target=_do, daemon=True).start()
        agent._pet_req = _pet_req
        if not hasattr(agent, '_turn_end_hooks'): agent._turn_end_hooks = {}
        def _pet_hook(ctx):
            parts = [f"Turn {ctx.get('turn','?')}"]
            if ctx.get('summary'): parts.append(ctx['summary'])
            if ctx.get('exit_reason'): parts.append('DONE')
            _pet_req(f'msg={quote(chr(10).join(parts))}')
            if ctx.get('exit_reason'): _pet_req('state=idle')
        agent._turn_end_hooks['pet'] = _pet_hook
        st.toast("Desktop pet started")
    
    if LANG == 'zh':
        st.divider()
        if st.button("开始空闲自主行动"):
            st.session_state.last_reply_time = int(time.time()) - 1800
            st.toast("已将上次回复时间设为1800秒前"); st.rerun()
        if st.session_state.autonomous_enabled:
            if st.button("⏸️ 禁止自主行动"):
                st.session_state.autonomous_enabled = False
                st.toast("⏸️ 已禁止自主行动"); st.rerun()
            st.caption("🟢 自主行动运行中，会在你离开它30分钟后自动进行")
        else:
            if st.button("▶️ 允许自主行动", type="primary"):
                st.session_state.autonomous_enabled = True
                st.toast("✅ 已允许自主行动"); st.rerun()
            st.caption("🔴 自主行动已停止")
with st.sidebar: render_sidebar()

def fold_turns(text):
    """Return list of segments: [{'type':'text','content':...}, {'type':'fold','title':...,'content':...}]"""
    # 先把4+反引号块替换为占位符，避免误切子agent嵌套的 LLM Running
    _ph = []
    safe = re.sub(r'`{4,}.*?`{4,}', lambda m: (_ph.append(m.group(0)), f'\x00PH{len(_ph)-1}\x00')[1], text, flags=re.DOTALL)
    # 流式中间态：末尾可能有未闭合的4+反引号块，也需保护
    safe = re.sub(r'`{4,}[^`].*$', lambda m: (_ph.append(m.group(0)), f'\x00PH{len(_ph)-1}\x00')[1], safe, flags=re.DOTALL)
    parts = re.split(r'(\**LLM Running \(Turn \d+\) \.\.\.\*\**)', safe)
    parts = [re.sub(r'\x00PH(\d+)\x00', lambda m: _ph[int(m.group(1))], p) for p in parts]
    if len(parts) < 4: return [{'type': 'text', 'content': text}]
    segments = []
    if parts[0].strip(): segments.append({'type': 'text', 'content': parts[0]})
    turns = []
    for i in range(1, len(parts), 2):
        marker = parts[i]
        content = parts[i+1] if i+1 < len(parts) else ''
        turns.append((marker, content))
    for idx, (marker, content) in enumerate(turns):
        if idx < len(turns) - 1:
            _c = re.sub(r'`{3,}.*?`{3,}|<thinking>.*?</thinking>', '', content, flags=re.DOTALL)
            matches = re.findall(r'<summary>\s*((?:(?!<summary>).)*?)\s*</summary>', _c, re.DOTALL)
            if matches:
                title = matches[0].strip()
                title = title.split('\n')[0]
                if len(title) > 50: title = title[:50] + '...'
            else:
                _plain = _c.strip().split('\n', 1)[0]
                title = (_plain[:50] + '...') if len(_plain) > 50 else (_plain or marker.strip('*'))
            segments.append({'type': 'fold', 'title': title, 'content': content})
        else: segments.append({'type': 'text', 'content': marker + content})
    return segments
_SUMMARY_TAG_RE = re.compile(r'<summary>.*?</summary>\s*', re.DOTALL)

def render_segments(segments, suffix=''):
    # 整块重画：调用方用 slot.container() 包裹，保证 DOM 路径稳定、跨 rerun 对齐（消除"灰色重影"）。
    # heartbeat 空转时 segments 不变 → Streamlit 后端 diff 无变化 → 前端零闪烁；
    # 但 container/markdown 本身是 API 调用，StopException 仍会被抛出（abort 照常起作用）。
    for seg in segments:
        if seg['type'] == 'fold':
            with st.expander(seg['title'], expanded=False): st.markdown(seg['content'])
        else:
            # Strip <summary> meta tags from text segments — folded turns already
            # promote them to expander titles; for the first/last segments
            # they'd otherwise leak into the chat as raw text (esp. after /continue
            # restores a multi-turn body).
            st.markdown(_SUMMARY_TAG_RE.sub('', seg['content']) + suffix)

def agent_backend_stream(prompt=None):
    """Drain main task display_queue.
    - prompt given:  start a fresh task; new dq is kept in session_state.
    - prompt is None: resume a dq left in session_state by a prior run (e.g. after /btw).
    Per-chunk progress is mirrored to session_state.partial_response so the rendered
    bubble survives reruns. No implicit agent.abort() — explicit stop is on the Stop button."""
    if prompt is not None:
        st.session_state.display_queue = agent.put_task(prompt, source="user")
        st.session_state.partial_response = ''
    dq = st.session_state.get('display_queue')
    if dq is None: return
    # Drop a dangling 'LLM Running (Turn N) ...' marker if the captured partial
    # ended right at a turn boundary with no content yet — otherwise the resume
    # bubble flashes as a marker-only gray line. The marker reappears with
    # content on the next chunk (raw_resp is cumulative).
    response = re.sub(r'\**LLM Running \(Turn \d+\) \.\.\.\**\s*$',
                      '', st.session_state.get('partial_response', '')).rstrip()
    try:
        while True:
            try: item = dq.get(timeout=1)
            except queue.Empty:
                yield response   # heartbeat: let outer st.markdown() run → Streamlit checks StopException
                continue
            if 'next' in item:
                response = item['next']
                st.session_state.partial_response = response
                yield response
            if 'done' in item:
                st.session_state.display_queue = None
                st.session_state.partial_response = ''
                yield item['done']; break
    finally:
        agent.abort()
        try:
            st.session_state.display_queue = None
            st.session_state.partial_response = ''
        except BaseException:
            pass


def render_main_stream(prompt=None):
    """Render the assistant bubble for the main task (new or resumed). Saves final to messages."""
    with st.chat_message("assistant"):
        frozen = 0; live = st.empty(); response = ''
        CURSOR = ' ▌'
        for response in agent_backend_stream(prompt):
            segs = fold_turns(response)
            n_done = max(0, len(segs) - 1)
            while frozen < n_done:
                with live.container(): render_segments([segs[frozen]])
                live = st.empty(); frozen += 1
            with live.container(): render_segments([segs[-1]], suffix=CURSOR)   # live 区域
        segs = fold_turns(response)
        for i in range(frozen, len(segs)):
            with live.container(): render_segments([segs[i]])
            if i < len(segs) - 1: live = st.empty()
    if response:
        st.session_state.messages.append({"role": "assistant", "content": response})
        st.session_state.last_reply_time = int(time.time())

if "messages" not in st.session_state: st.session_state.messages = []
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        # 用 slot=st.empty() + with slot.container(): ... 的外壳，DOM 路径和流式渲染完全一致，跨 rerun 对齐
        slot = st.empty()
        with slot.container():
            if msg["role"] == "assistant": render_segments(fold_turns(msg["content"]))
            else: st.markdown(msg["content"])

# Scroll-height ghost fix: during streaming, expander open/close mid-animation can leave
# phantom height → scrollbar long but can't scroll to bottom. Periodically detect & reflow.
try:
    from streamlit import iframe as _st_iframe  # 1.56+
    _embed_html = lambda html, **kw: _st_iframe(html, **{k: max(v, 1) if isinstance(v, int) else v for k, v in kw.items()})
except (ImportError, AttributeError):
    from streamlit.components.v1 import html as _embed_html  # ≤1.55
_js_scroll_fix = (
    "!function(){var p=window.parent;if(p.__sfx2)return;p.__sfx2=1;var d=p.document;"
    "function f(){var m=d.querySelector('section.main');if(!m)return;"
    "var s=m.scrollTop;m.style.minHeight=m.scrollHeight+1+'px';void m.offsetHeight;"
    "m.style.minHeight='';void m.offsetHeight;m.scrollTop=s}"
    "d.addEventListener('transitionend',function(e){"
    "e.target.closest&&e.target.closest('details')&&setTimeout(f,60)},!0);"
    "new MutationObserver(function(){setTimeout(f,80)})"
    ".observe(d.body,{subtree:1,attributes:1,attributeFilter:['open']});"
    "setInterval(f,5000)}()"
)
# IME composition fix (macOS only) - prevents Enter from submitting during CJK input
_js_ime_fix = ("" if os.name == 'nt' else
    "!function(){if(window.parent.__imeFix)return;window.parent.__imeFix=1;"
    "var d=window.parent.document,c=0;"
    "d.addEventListener('compositionstart',()=>c=1,!0);"
    "d.addEventListener('compositionend',()=>c=0,!0);"
    "function f(){d.querySelectorAll('textarea[data-testid=stChatInputTextArea]')"
    ".forEach(t=>{t.__imeFix||(t.__imeFix=1,t.addEventListener('keydown',e=>{"
    "e.key==='Enter'&&!e.shiftKey&&(e.isComposing||c||e.keyCode===229)&&"
    "(e.stopImmediatePropagation(),e.preventDefault())},!0))})}"
    "f();new MutationObserver(f).observe(d.body,{childList:1,subtree:1})}()")
_embed_html(f'<script>{_js_scroll_fix};{_js_ime_fix}</script>', height=0)

if prompt := st.chat_input("any task?"):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    cmd = (prompt or "").strip()
    def _reset_and_rerun():
        st.session_state.streaming = False
        st.session_state.stopping = False
        st.session_state.display_queue = None
        st.session_state.partial_response = ""
        st.session_state.reply_ts = ""
        st.session_state.current_prompt = ""
        st.session_state.last_reply_time = int(time.time())
        st.rerun()
    if cmd == "/new":
        st.session_state.messages = [{"role": "assistant", "content": reset_conversation(agent), "time": ts}]
        _reset_and_rerun()
    if cmd.startswith("/continue"):
        m = re.match(r'/continue\s+(\d+)\s*$', cmd.strip())
        sessions = list_sessions(exclude_pid=os.getpid()) if m else []
        idx = int(m.group(1)) - 1 if m else -1
        # Resolve target path BEFORE handle (which snapshots current log, shifting indices).
        target = sessions[idx][0] if 0 <= idx < len(sessions) else None
        result = handle_frontend_command(agent, cmd)
        history = extract_ui_messages(target) if target and result.startswith('✅') else None
        tail = [{"role": "assistant", "content": result, "time": ts}]
        if history:
            st.session_state.messages = history + tail
        else:
            st.session_state.messages = list(st.session_state.messages) + \
                [{"role": "user", "content": cmd, "time": ts}] + tail
        _reset_and_rerun()
    if cmd.startswith("/btw"):
        answer = btw_handle_frontend(agent, cmd)  # sync; bypasses put_task → main agent.run() untouched
        st.session_state.messages = list(st.session_state.messages) + [
            {"role": "user", "content": prompt, "time": ts},
            {"role": "assistant", "content": answer, "time": ts},
        ]
        st.rerun()  # preserve display_queue/partial_response so resume path drains the running main task
    # Regular prompt: any in-flight task will be aborted by the finally block in
    # agent_backend_stream when StopException interrupts the prior generator.
    st.session_state.messages.append({"role": "user", "content": prompt})
    if hasattr(agent, '_pet_req') and not prompt.startswith('/'): agent._pet_req('state=walk')
    with st.chat_message("user"): st.markdown(prompt)
    render_main_stream(prompt)
elif st.session_state.get('display_queue') is not None:
    # No new prompt but a task is mid-flight (typically a /btw rerun) — resume drain.
    render_main_stream()

if st.session_state.autonomous_enabled:
    st.markdown(f"""<div id="last-reply-time" style="display:none">{st.session_state.get('last_reply_time', int(time.time()))}</div>""", unsafe_allow_html=True)
