import os, sys, subprocess
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

from functools import lru_cache
from datetime import timedelta
import agentmain, llmcore
from agentmain import GenericAgent
try:  # optional slash cmds; missing modules must not block main chat
    import chatapp_common  # monkey-patches GenericAgent: /continue /btw /review
    from continue_cmd import handle_frontend_command, reset_conversation, list_sessions, extract_ui_messages
    from btw_cmd import handle_frontend_command as btw_handle_frontend
    from export_cmd import last_assistant_text, export_to_temp, wrap_for_clipboard
    _SLASH = True
except ImportError:
    _SLASH = False

st.set_page_config(page_title="Cowork", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
[data-testid="stBottom"]{position:fixed!important;bottom:0!important;left:0!important;right:0!important;width:100vw!important;z-index:999;background:var(--background-color,#fff)}
@media (min-width:768px){[data-testid="stSidebar"][aria-expanded="true"]~div [data-testid="stBottom"]{left:300px!important;width:calc(100vw - 300px)!important}}
.stMainBlockContainer{padding-bottom:10rem!important}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] hr,
[data-testid="stSidebar"] hr{margin:0.55rem 0!important}
[data-testid="stSidebar"] [data-testid="element-container"]:has(hr){margin:0!important;padding:0!important}
</style>
""", unsafe_allow_html=True)

LANG = os.environ.get('GA_LANG', 'zh')
if LANG not in ('zh', 'en'): LANG = 'zh'
I18N = {
    'zh': {
        'force_stop': '强行停止任务',
        'desktop_pet': '🐱 桌面宠物',
        'suggest_btn': '🎯 给我找点事做',
        'suggest_prompt': '按照自主行动的规划部分，充分分析我的情况，给我生成一批TODO，务必让我感兴趣',
        'auto_pause': '⏸️ 禁止自主行动',
        'auto_enable': '▶️ 允许自主行动',
        'auto_on_cap': '🟢 已允许：约1分钟后启动，之后空闲30分钟再触发',
        'auto_off_cap': '🔴 自主行动已停止',
        'auto_prompt': '[AUTO]🤖 用户已经离开超过30分钟，作为自主智能体，请阅读自动化sop，执行自动任务。',
        'detached_running': '⏳ 后台任务运行中…（本页已刷新，实时流不再接入；完成后自动刷新）',
        'get_token': '🔑 获取 Token',
        'get_token_toast': '已打开浏览器',
        'need_mykey': '⚠️ 请配置 mykey.py',
        'reopen_page': '等待配置写入，完成后将自动进入…',
        'show_earlier': '📜 展开更早的 {n} 条',
        'hide_earlier': '📕 收起更早消息',
    },
    'en': {
        'force_stop': 'Force Stop',
        'desktop_pet': '🐱 Desktop Pet',
        'suggest_btn': '🎯 Suggest tasks',
        'suggest_prompt': 'Following the planning section of autonomous sop, analyze my situation thoroughly and generate a batch of TODOs that will interest me.',
        'auto_pause': '⏸️ Pause auto-action',
        'auto_enable': '▶️ Enable auto-action',
        'auto_on_cap': '🟢 On: first run ~1min, then every 30min idle',
        'auto_off_cap': '🔴 Auto-action disabled',
        'auto_prompt': '[AUTO]🤖 User has been idle for over 30 minutes. As an autonomous agent, read the automation SOP and execute automatic tasks.',
        'detached_running': '⏳ A task is running in the background… (this page was refreshed, live stream not attached; will refresh when done)',
        'get_token': '🔑 Get Token',
        'get_token_toast': 'Opened in browser',
        'need_mykey': '⚠️ Please set mykey.py',
        'reopen_page': 'Waiting for config… will enter automatically',
        'show_earlier': '📜 Show {n} earlier messages',
        'hide_earlier': '📕 Collapse earlier messages',
    },
}
def T(key): return I18N.get(LANG, I18N['zh']).get(key, key)

@st.cache_resource
def init():
    agent = GenericAgent()
    threading.Thread(target=agent.run, daemon=True).start()
    return agent

agent = init()
# NOTE: never abort merely because a new session appeared (F5 / 2nd tab / external probe).
# Aborting is an *intent*, triggered only by a new prompt or the Stop button.
_sp = getattr(agentmain, "start_subscription_portal", None)

@st.fragment(run_every=timedelta(seconds=2))
def _watch_portal():
    b = st.session_state["portal_wait"]
    c = tuple(n for _, n, _ in agent.list_llms())
    if c and c != b:
        del st.session_state["portal_wait"]
        st.session_state.pop("sidebar_llm_select", None)
        st.rerun(scope="app")

if not agent.llmclients and _sp:
    st.session_state.setdefault("portal_wait", ()); _sp()
if "portal_wait" in st.session_state: _watch_portal()

if not agent.llmclients:
    if _sp: st.warning(T("reopen_page"))
    else: st.error(T("need_mykey"))
    st.stop()

def build_prompt(objective):
    return f"""读取 {agent.log_path} 尾部，获取 agent 的最新输出。
用户的 loop 诉求：<objective>{objective}</objective>
判断该 agent 是否偷懒、是否真正完成诉求，用 <next_prompt></next_prompt> 输出要追加给它的指令：
一般复述 objective，或不超过 10 字的**督促**，如：别停，继续 / 这就叫最优？你优化到位了吗 / 看我要求，你达成了吗 / 你好好看清楚 / 你能不能看看记忆 / 把关键发现和阶段性成果落盘，然后继续
不允许促进 agent 停止或代替宣告任务完成，只允许催促不要对原任务进行评价，特别**禁止**“任务已完成，结束”这种让agent结束的指令，你的任务是让agent继续loop而非停止。
只输出 <next_prompt>…</next_prompt>，若需要停止则不要输出此tag。
"""

@st.cache_resource
def get_controller():
    b = {'ev': threading.Event(), 'obj': '', 'out': None, 'ready': False, 'ag': None, 'epoch': 0}
    def loop():
        ag = GenericAgent(); ag.verbose = False; ag.log_path = False; b['ag'] = ag
        threading.Thread(target=ag.run, daemon=True).start()
        while True:
            b['ev'].wait(); b['ev'].clear(); ep = b.get('job', b['epoch'])
            if ep != b['epoch']: continue
            if ag.llm_no != agent.llm_no: ag.next_llm(agent.llm_no)
            dq = ag.put_task(build_prompt(b['obj']), source="controller")
            while 'done' not in (it := dq.get()): pass
            if ep != b['epoch']: continue   # Stop Loop 已翻页 → 丢弃过期决策
            ms = re.findall(r'<next_prompt>(.*?)</next_prompt>', it['done'], re.S)
            b['out'] = ms[-1].strip() if ms else None; b['ready'] = True
    threading.Thread(target=loop, daemon=True).start(); return b

st.title("🖥️ Cowork")

st.session_state.setdefault('autonomous_enabled', False)

@st.fragment
def render_sidebar():
    llm_options = agent.list_llms()
    current_idx = agent.llm_no
    llm_labels = {idx: f"{idx}: {(name or '').strip()}" for idx, name, _ in llm_options}
    st.caption(f"LLM Core: {llm_labels.get(current_idx, str(current_idx))}")
    selected_idx = st.selectbox("LLM", [idx for idx, _, _ in llm_options], index=next((i for i, (idx, _, _) in enumerate(llm_options) if idx == current_idx), 0), format_func=llm_labels.get, label_visibility="collapsed", key="sidebar_llm_select")
    if selected_idx != current_idx:
        agent.next_llm(selected_idx); st.rerun()
    if st.button(T('force_stop')):
        agent.abort()
        st.toast("Stop signal sent")
        st.rerun(scope="app")
    if st.button(T('desktop_pet')):
        kwargs = {'creationflags': 0x08} if sys.platform == 'win32' else {}
        pet_script = os.path.join(script_dir, 'desktop_pet_v2.pyw')
        if not os.path.exists(pet_script):
            st.error("desktop_pet_v2.pyw not found")
            return
        subprocess.Popen([sys.executable, pet_script], **kwargs)
        if not hasattr(agent, '_turn_end_hooks'): agent._turn_end_hooks = {}
        def _pet_hook(ctx):     # the pet subscribes to the bus topic 'turn': no port, no HTTP, one hop
            done = ctx.get('exit_reason')
            # NOTE: must be a statement, not a bare expression -- streamlit's AST "magic"
            # rewrites bare expressions into st.write(), which fires "missing ScriptRunContext"
            # from this worker thread (and would try to render the return value).
            if agent._hub:
                agent._hub.emit('turn', {'state': 'idle' if done else None, 'msg': '\n'.join(
                    [f"Turn {ctx.get('turn', '?')}"] + [x for x in (ctx.get('summary'), done and 'DONE') if x])})
        agent._turn_end_hooks['pet'] = _pet_hook
        st.toast("Desktop pet started")
    
    if st.button(T('suggest_btn')):
        st.session_state['_inject_prompt'] = T('suggest_prompt')
        st.rerun(scope="app")
    st.divider()
    st.markdown("""<style>
    [data-testid="stSidebar"] .stTextArea textarea {
        field-sizing: content; min-height: 1.6em !important; height: auto !important;
    }
    </style>""", unsafe_allow_html=True)
    st.text_area("Loop prompt", value=st.session_state.get('loop_prompt_input', "继续" if LANG=='zh' else 'next'), key="loop_prompt_input", height=68)
    if st.session_state.get('loop_enabled'):
        if st.button("⏹️ Stop Loop"):
            st.session_state.loop_enabled = False
            b = get_controller(); b['epoch'] += 1; b['ready'] = False
            if b['ag'] is not None: b['ag'].abort()  # controller 若在决策也断掉
            agent.abort()   # 兼做 Force Stop：立刻断
            st.toast("⏹️ Loop stopped"); st.rerun(scope="app")
        st.caption("🔁 Looping")
    else:
        if st.button("🔁 Loop!"):
            st.session_state.loop_enabled = True
            get_controller(); st.toast("🔁 Looping")
            # 流式中不做 app rerun（会打断本轮）：留给本轮收尾回调戳 controller 续
            if st.session_state.get('display_queue') is None:
                st.session_state['_inject_prompt'] = st.session_state.get('loop_prompt_input', '')
                st.rerun(scope="app")
    st.divider()
    if st.session_state.autonomous_enabled:
        if st.button(T('auto_pause')):
            st.session_state.autonomous_enabled = False
            st.toast(T('auto_pause')); st.rerun(scope="app")
        st.caption(T('auto_on_cap'))
    else:
        if st.button(T('auto_enable'), type="primary"):
            # 允许 = 约1分钟后首次触发（阈值 1800-60），之后仍按空闲30分钟
            st.session_state.last_reply_time = int(time.time()) - 1740
            st.session_state.autonomous_enabled = True
            st.toast("✅"); st.rerun(scope="app")
        st.caption(T('auto_off_cap'))
    if _sp:
        st.divider()
        if st.button(T("get_token")):
            st.session_state.portal_wait = tuple(n for _, n, _ in agent.list_llms())
            _sp(); st.rerun(scope="app")
with st.sidebar: render_sidebar()

def _fold_turns_impl(text):
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
            segments.append({'type': 'fold', 'title': _step_title(content, idx) or marker.strip('*'), 'content': content})
        else: segments.append({'type': 'text', 'content': marker + content})
    return segments

def _step_title(s, j=0):
    body = re.sub(r'\**LLM Running \(Turn \d+\) \.\.\.\**|`{3,}.*?`{3,}|<thinking>.*?</thinking>', '', s or '', flags=re.DOTALL)
    m = re.search(r'<summary>\s*(.*?)\s*</summary>', body, re.DOTALL)
    t = (m.group(1) if m else body.strip()).strip().split('\n')[0]
    return (t[:50] + '...' if len(t) > 50 else t) or f'step {j + 1}'

@st.cache_resource
def _get_fold_turns(): return lru_cache(maxsize=128)(_fold_turns_impl)

fold_turns = _get_fold_turns()
def render_segments(segments, suffix=''):
    for seg in segments:
        if seg['type'] == 'fold':
            with st.expander(seg['title'], expanded=False): st.markdown(seg['content'])
        else:
            st.markdown(seg['content'] + suffix)

def _start_main_task(prompt):
    """Start a task whose queue can be drained across Streamlit reruns."""
    st.session_state.display_queue = agent.put_task(prompt, source="user")
    st.session_state.task_start_ts = time.time()
    st.session_state.pop('task_end_ts', None)
    st.session_state.pop('_stream_frozen', None)

def _cancel_main_task():
    agent.abort()
    st.session_state.display_queue = None
    st.session_state.pop('_stream_frozen', None)

def _poll_main_task(max_items=256):
    """Doorbell only — drain queue; render reads agent.all_outputs."""
    dq = st.session_state.get("display_queue")
    if dq is None: return None
    done = None
    for _ in range(max_items):
        try: item = dq.get_nowait()
        except queue.Empty: break
        if "done" in item:
            done = item["done"]
            st.session_state.task_end_ts = time.time()
            st.session_state.display_queue = None
            break
    return done

def _render_stat_badge(is_running):
    if 'task_start_ts' not in st.session_state or not hasattr(llmcore, 'STATS'): return
    end_ts = time.time() if is_running else st.session_state.get('task_end_ts', time.time())
    secs = max(0, int(end_ts - st.session_state.task_start_ts))
    stats = dict(llmcore.STATS)
    short = lambda n: f'{n / 1000:.0f}k' if n >= 1000 else str(n)
    usage = ((f"{stats['session']} │ " if stats.get('session') else '') +
             f"{short(stats['ctx'])} chars·{stats['msgs']}msgs │ "
             f"in {short(stats.get('inp', 0))} toks·cached{short(stats.get('cached', 0))}·out{short(stats.get('out', 0))} │ "
             if 'ctx' in stats else '')
    st.markdown(f'<div class="ga-stat-badge">{usage}{secs // 60}:{secs % 60:02d}</div>',
                unsafe_allow_html=True)


if not hasattr(agent, "_ui_messages"): agent._ui_messages = st.session_state.get("messages", [])
if "messages" not in st.session_state: st.session_state.messages = agent._ui_messages
if not hasattr(agent, "_hub"):
    try:
        import hub; agent._hub = hub.connect(agent, 'stapp')
    except Exception: agent._hub = None
# Lazy history: long sessions (esp. after loop) render thousands of elements on every
# full-app rerun → seconds of gray/RUNNING. Only render the tail unless expanded.
_HIST_TAIL = 10
_msgs = st.session_state.messages
if len(_msgs) > _HIST_TAIL:
    if not st.session_state.get("show_full_history"):
        if st.button(T('show_earlier').format(n=len(_msgs) - _HIST_TAIL), key="_show_hist"):
            st.session_state.show_full_history = True
            st.rerun()
        _msgs = _msgs[-_HIST_TAIL:]
    else:
        if st.button(T('hide_earlier'), key="_hide_hist"):
            st.session_state.show_full_history = False
            st.rerun()
for msg in _msgs:
    with st.chat_message(msg["role"]):
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
_embed_html(f'<script>{_js_ime_fix}</script>', height=0)

_typed = st.chat_input("any task?")
_injected = None if _typed else st.session_state.pop('_inject_prompt', None)  # typed run: keep parked
if (_injected is None and not _typed and not agent.is_running
        and st.session_state.get('display_queue') is None and getattr(agent, '_hub_inbox', None)):
    try: _injected = agent._hub_inbox.pop(0)   # hub text enters the SAME entrance as typing
    except IndexError: pass                    # another tab won the pop
prompt = _typed or _injected
if prompt:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    cmd = (prompt or "").strip()
    def _reset_and_rerun():
        _cancel_main_task()
        st.session_state.streaming = False
        st.session_state.reply_ts = ""
        st.session_state.current_prompt = ""
        st.session_state.last_reply_time = int(time.time())
        st.rerun()
    def _slash_missing(name):
        st.session_state.messages.extend([
            {"role": "user", "content": cmd, "time": ts},
            {"role": "assistant", "content": f"❌ `{name}` 模块未安装", "time": ts},
        ])
        _reset_and_rerun()
    if cmd == "/new":
        if not _SLASH: _slash_missing('continue_cmd')
        st.session_state.messages[:] = [{"role": "assistant", "content": reset_conversation(agent), "time": ts}]
        _reset_and_rerun()
    if cmd.startswith("/continue"):
        if not _SLASH: _slash_missing('continue_cmd')
        m = re.match(r'/continue\s+(\d+)\s*$', cmd.strip())
        sessions = list_sessions(exclude_pid=os.getpid()) if m else []
        idx = int(m.group(1)) - 1 if m else -1
        # Resolve target path BEFORE handle (which snapshots current log, shifting indices).
        target = sessions[idx][0] if 0 <= idx < len(sessions) else None
        result = handle_frontend_command(agent, cmd)
        history = extract_ui_messages(target) if target and result.startswith('✅') else None
        tail = [{"role": "assistant", "content": result, "time": ts}]
        if history: st.session_state.messages[:] = history + tail
        else: st.session_state.messages.extend([{"role": "user", "content": cmd, "time": ts}] + tail)
        _reset_and_rerun()
    if cmd.startswith("/btw"):
        if not _SLASH: _slash_missing('btw_cmd')
        answer = btw_handle_frontend(agent, cmd)  # sync; bypasses put_task → main agent.run() untouched
        st.session_state.messages.extend([
            {"role": "user", "content": prompt, "time": ts},
            {"role": "assistant", "content": answer, "time": ts},
        ])
        st.rerun()  # preserve display_queue so resume path drains the running main task
    if cmd.startswith("/export"):
        parts = cmd.split(maxsplit=1)
        sub = parts[1].strip() if len(parts) > 1 else ""
        sub_lower = sub.lower()
        if not sub:
            result = (
                "**选择导出方式：**\n\n"
                "- `/export clip` — 整理到代码块中\n"
                "- `/export <文件名>` — 导出到 `temp/<文件名>`（默认 .md 后缀）\n"
                "- `/export all` — 显示完整对话日志路径"
            )
        elif sub_lower == "all":  # only needs agent.log_path
            log = agent.log_path
            result = (f"📂 完整对话日志:\n\n`{log}`" if os.path.isfile(log)
                      else f"❌ 当前会话尚无日志文件")
        elif not _SLASH:
            result = "❌ `export_cmd` 模块未安装"
        else:
            text = last_assistant_text(agent)
            if not text:
                result = "❌ 还没有模型回复可导出"
            elif sub_lower in ("clip", "copy"):
                result = f"📋 最后一轮回复（点代码块右上角 📋 复制）:\n\n{wrap_for_clipboard(text)}"
            else:
                try:
                    path = export_to_temp(text, sub)
                    result = f"✅ 已导出:\n\n`{path}`"
                except Exception as e:
                    result = f"❌ 导出失败: {e}"
        st.session_state.messages.extend([
            {"role": "user", "content": cmd, "time": ts},
            {"role": "assistant", "content": result, "time": ts},
        ])
        _reset_and_rerun()
    # Regular prompt starts a new main task. Explicitly detach any prior task first;
    # sidebar-only reruns never pass through this branch, so they keep the queue.
    if agent.is_running or st.session_state.get("display_queue") is not None:
        _cancel_main_task()
    st.session_state.messages.append({"role": "user", "content": prompt})
    if agent._hub and not prompt.startswith('/'): agent._hub.emit('turn', {'state': 'walk'})
    with st.chat_message("user"): st.markdown(prompt)
    _start_main_task(prompt)

# Stream hosts only when this session owns the queue.
# Single always-on 1s tick below (stream / detached / hub / idle) — never unregistered.
_stream_fh = _stream_ls = None
if st.session_state.get('display_queue') is not None:
    with st.chat_message("assistant"):
        _stream_fh = st.container()
        _stream_ls = st.empty()
    # New hosts every full-app run → repaint completed steps from 0.
    st.session_state._stream_frozen = 0
elif agent.is_running:
    st.chat_message("assistant").markdown(T("detached_running"))

@st.fragment(run_every=timedelta(seconds=1))
def _tick():
    """One heartbeat: if-dispatch stream / detached / hub / idle. Always registered."""
    # 1) Own stream: drain done, paint all_outputs
    if _stream_fh is not None:
        done = _poll_main_task()
        if done is not None:
            if done:
                st.session_state.messages.append({"role": "assistant", "content": done})
                st.session_state.last_reply_time = int(time.time())
                if st.session_state.get('loop_enabled'):
                    b = get_controller()
                    b['obj'] = st.session_state.get('loop_prompt_input', '')
                    b['ready'] = False; b['job'] = b['epoch']; b['ev'].set()
            st.session_state.pop('_stream_frozen', None)
            st.rerun(scope="app"); return
        # Only paint all_outputs[-1] when worker is on *this* display_queue.
        # After force-stop + immediate next prompt, UI already owns a new queue while
        # agent still finishes / hasn't dequeued the new task → [-1] is the old task.
        # Reading it would dump old expanders into the new bubble and inflate
        # _stream_frozen so new steps never fold. Gate on queue identity (no hub change).
        _dq = st.session_state.get("display_queue")
        steps = (list(((agent.all_outputs or [{}])[-1].get("outputs")) or [])
                 if _dq is getattr(agent, "_current_queue", None) else [])
        frozen = st.session_state.get('_stream_frozen', 0)
        while frozen < max(0, len(steps) - 1):
            body = steps[frozen] or ''
            with _stream_fh:
                with st.expander(_step_title(body, frozen), expanded=False): st.markdown(body)
            frozen += 1
        st.session_state._stream_frozen = frozen
        live = re.sub(r'\**LLM Running \(Turn \d+\) \.\.\.\**\s*$', '',
                      (steps[-1] if steps else '') or '').rstrip()
        with _stream_ls.container(): st.markdown(live + " ▌")
        _render_stat_badge(is_running=True)
        return

    # 2) Detached: salvage done from agent queue (refresh / 2nd tab)
    dq = getattr(agent, "_current_queue", None)
    if dq is not None and st.session_state.get('display_queue') is None:
        while True:
            try: item = dq.get_nowait()
            except Exception: break
            if isinstance(item, dict) and "done" in item:
                if item["done"]:
                    st.session_state.messages.append({"role": "assistant", "content": item["done"]})
                st.rerun(scope="app"); return
    if agent.is_running:
        st.session_state['_saw_detached'] = True
        return
    if st.session_state.pop('_saw_detached', None):
        st.rerun(scope="app"); return

    # 3) Hub inbox: just wake a full run; the unified entrance pops it when idle (mimics typing)
    if getattr(agent, '_hub_inbox', None) and st.session_state.get('display_queue') is None and not agent.is_running:
        st.rerun(scope="app"); return

    # 4) Loop / autonomous idle inject (was 1min fragment; time-gated so 1s tick is fine)
    if st.session_state.get('loop_enabled'):
        b = get_controller()
        if b['ready']:
            b['ready'] = False
            if b['out'] and '停止循环' not in b['out']:
                st.session_state['_inject_prompt'] = b['out']
            else:
                st.session_state.loop_enabled = False
            st.rerun(scope="app")
        return
    if st.session_state.get('autonomous_enabled'):
        last = st.session_state.get('last_reply_time', int(time.time()))
        if time.time() - last > 1800:
            st.session_state['_inject_prompt'] = T('auto_prompt')
            st.session_state['last_reply_time'] = int(time.time())
            st.rerun(scope="app")

_tick()

# Badges project backend only: agent.is_running. task_start_ts is just UI clock for the stat line.
_has_task_stats = 'task_start_ts' in st.session_state
_is_running = bool(agent.is_running)
if _has_task_stats and not _is_running:
    _render_stat_badge(is_running=False)

if _has_task_stats or _is_running:
    st.markdown(
        ('<div class="ga-run-badge">RUNNING</div>' if _is_running else '') +
        '<style>.ga-run-badge,.ga-stat-badge{position:fixed;top:1.25rem;z-index:1000001;'
        'padding:1px 10px;border-radius:12px;font-size:.72rem;font-weight:600;letter-spacing:.05em}'
        '.ga-run-badge{right:2.8rem;background:rgba(255,75,75,.10);color:#ff4b4b;animation:gaPulse 1.2s ease-in-out infinite}'
        '.ga-stat-badge{right:8.4rem;background:rgba(128,128,128,.1);color:#8a8a8a;'
        'font-variant-numeric:tabular-nums;letter-spacing:0}'
        '@keyframes gaPulse{50%{opacity:.35}}</style>', unsafe_allow_html=True)
