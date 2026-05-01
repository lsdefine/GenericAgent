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
from auto_routing_agent import AutoRoutingAgent
import chatapp_common  # activate /continue command (monkey patches GeneraticAgent)
from continue_cmd import handle_frontend_command, reset_conversation, list_sessions, extract_ui_messages

st.set_page_config(page_title="Cowork", layout="wide")

AUTO_ROUTE_CONFIG_PATH = os.path.join(script_dir, '..', 'auto_route_config.json')


def _format_route_status(status):
    def _clip(value, max_len=72):
        text = str(value or '-').replace('\n', ' ').replace('\r', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > max_len:
            return text[:max_len - 3] + '...'
        return text

    if not status:
        return '自动路由状态不可用'
    last = status.get('last_route') or {}
    blocked = status.get('blocked_targets') or {}
    lines = [
        f"auto_route: {'on' if status.get('auto_route_enabled') else 'off'}",
        f"manual_override: {'on' if status.get('manual_override') else 'off'}",
        f"effective_mode: {_clip(status.get('effective_mode'))}",
        f"current_model: {_clip(status.get('current_model'))}",
    ]
    if last:
        lines.append(f"last_reason: {_clip(last.get('reason'))}")
        lines.append(f"last_selected: {_clip(last.get('selected_name'))}")
        trigger = (last.get('details') or {}).get('trigger_source')
        if trigger:
            lines.append(f"trigger_source: {_clip(trigger)}")
        if last.get('fallback_reason'):
            lines.append(f"fallback: {_clip(last.get('fallback_reason'))}")
    if blocked:
        lines.append(f"blocked_targets: {len(blocked)}")
    return '\n'.join(lines)

@st.cache_resource
def init():
    base_agent = GeneraticAgent()
    agent = AutoRoutingAgent(base_agent=base_agent, config_path=AUTO_ROUTE_CONFIG_PATH)
    if agent.llmclient is None:
        st.error("⚠️ 未配置任何可用的 LLM 接口，请设置mykey.py。")
        st.stop()
    else:
        threading.Thread(target=agent.base_agent.run, daemon=True).start()
    return agent

agent = init()

st.title("🖥️ Cowork")

st.session_state.setdefault('autonomous_enabled', False)

@st.fragment
def render_sidebar():
    st.session_state.setdefault('autonomous_enabled', False)
    st.session_state.setdefault('auto_route_enabled_ui', True)
    llm_options = agent.list_llms()
    current_idx = agent.llm_no
    llm_labels = {idx: f"{idx}: {(name or '').strip()}" for idx, name, _ in llm_options}
    st.caption(f"LLM Core: {llm_labels.get(current_idx, str(current_idx))}", help="下拉切换备用链路")
    selected_idx = st.selectbox("备用链路", [idx for idx, _, _ in llm_options], index=next((i for i, (idx, _, _) in enumerate(llm_options) if idx == current_idx), 0), format_func=llm_labels.get, label_visibility="collapsed", key="sidebar_llm_select")
    if selected_idx != current_idx:
        agent.next_llm(selected_idx); st.rerun()
    last_reply_time = st.session_state.get('last_reply_time', 0)
    if last_reply_time > 0:
        st.caption(f"空闲时间：{int(time.time()) - last_reply_time}秒", help="当超过30分钟未收到回复时，系统会自动任务")
    if st.button("强行停止任务"):
        agent.abort(); st.toast("已发送停止信号"); st.rerun()
    if st.button("重新注入工具"):
        agent.llmclient.last_tools = ''
        try:
            hist_path = os.path.join(script_dir, '..', 'assets', 'tool_usable_history.json')
            with open(hist_path, 'r', encoding='utf-8') as f: tool_hist = json.load(f)
            agent.llmclient.backend.history.extend(tool_hist)
            st.toast(f"已重新注入工具，追加了 {len(tool_hist)} 条示范记录")
        except Exception as e: st.toast(f"注入工具示范失败: {e}")

    st.divider()
    route_status = agent.route_status() if hasattr(agent, 'route_status') else {}
    auto_enabled = bool(route_status.get('auto_route_enabled'))
    manual_locked = bool(route_status.get('manual_override'))
    st.caption("自动路由", help="按任务特征自动选择模型；手动切换后会进入手动锁定")
    if auto_enabled:
        if st.button("关闭自动路由"):
            agent.enable_auto_route(False)
            st.toast("已关闭自动路由")
            st.rerun()
    else:
        if st.button("开启自动路由", type="primary"):
            agent.enable_auto_route(True, clear_manual_override=True)
            st.toast("已开启自动路由")
            st.rerun()
    if manual_locked:
        if st.button("解除手动锁定"):
            agent.clear_manual_override()
            st.toast("已解除手动锁定")
            st.rerun()
        st.caption("当前处于手动锁定：自动路由不会改写你手动选择的模型")
    else:
        st.caption("当前未锁定：自动路由可在请求前切换模型")
    st.code(_format_route_status(route_status), language='text')

    if st.button("🐱 桌面宠物"):
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
            if ctx.get('exit_reason'): parts.append('任务已完成')
            _pet_req(f'msg={quote(chr(10).join(parts))}')
            if ctx.get('exit_reason'): _pet_req('state=idle')
        agent._turn_end_hooks['pet'] = _pet_hook
        st.toast("桌面宠物已启动")
    
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
            else: title = marker.strip('*')
            segments.append({'type': 'fold', 'title': title, 'content': content})
        else: segments.append({'type': 'text', 'content': marker + content})
    return segments
def render_segments(segments, suffix=''):
    # 整块重画：调用方用 slot.container() 包裹，保证 DOM 路径稳定、跨 rerun 对齐（消除"灰色重影"）。
    # heartbeat 空转时 segments 不变 → Streamlit 后端 diff 无变化 → 前端零闪烁；
    # 但 container/markdown 本身是 API 调用，StopException 仍会被抛出（abort 照常起作用）。
    for seg in segments:
        if seg['type'] == 'fold':
            with st.expander(seg['title'], expanded=False): st.markdown(seg['content'])
        else:
            st.markdown(seg['content'] + suffix)

def agent_backend_stream(prompt):
    display_queue = agent.put_task(prompt, source="user")
    status = agent.route_status() if hasattr(agent, 'route_status') else {}
    last = (status.get('last_route') or {}) if isinstance(status, dict) else {}
    mode = status.get('effective_mode') if isinstance(status, dict) else None
    selected = last.get('selected_name') or status.get('current_model')
    reason = last.get('reason') or mode or 'unknown'
    trigger = (last.get('details') or {}).get('trigger_source') if isinstance(last, dict) else None
    if trigger:
        route_line = f"[ROUTE] {mode or 'unknown'} -> {selected or 'unknown'} ({reason}; {trigger})"
    else:
        route_line = f"[ROUTE] {mode or 'unknown'} -> {selected or 'unknown'} ({reason})"
    response = ""
    try:
        while True:
            try: item = display_queue.get(timeout=1)
            except queue.Empty:
                yield response   # heartbeat: let outer st.markdown() run → Streamlit checks StopException
                continue
            if 'next' in item:
                response = item['next']
                yield response
            if 'done' in item:
                # 回复最后一行加路由信息
                done = item.get('done', '')
                if done.endswith('\n'):
                    response = done + route_line
                elif done:
                    response = done + '\n' + route_line
                else:
                    response = route_line
                yield response
                break
    finally: agent.abort()

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
_js_scroll_fix = ("!function(){var p=window.parent;if(p.__sfx)return;p.__sfx=1;"
    "var d=p.document;setInterval(function(){"
    "var m=d.querySelector('section.main');if(!m)return;"
    "var b=m.querySelector('.block-container');if(!b)return;"
    "if(m.scrollHeight>b.scrollHeight+150){"
    "m.style.overflow='hidden';void m.offsetHeight;m.style.overflow=''}"
    "},3000)}()")
# IME composition fix (cross-platform) - prevents Enter from submitting during CJK input
_js_ime_fix = (
    "!function(){if(window.parent.__imeFix)return;window.parent.__imeFix=1;"
    "var d=window.parent.document,c=0;"
    "d.addEventListener('compositionstart',()=>c=1,!0);"
    "d.addEventListener('compositionend',()=>c=0,!0);"
    "function f(){d.querySelectorAll('textarea[data-testid=stChatInputTextArea]')"
    ".forEach(t=>{t.__imeFix||(t.__imeFix=1,t.addEventListener('keydown',e=>{"
    "e.key==='Enter'&&!e.shiftKey&&(e.isComposing||c||e.keyCode===229)&&"
    "(e.stopImmediatePropagation(),e.preventDefault())},!0))})}"
    "f();new MutationObserver(f).observe(d.body,{childList:1,subtree:1})}()")

# Draft guard: cache/restore unsent text to reduce occasional Enter-send loss.
_js_draft_guard = (
    "!function(){var p=window.parent,d=p.document;if(p.__gaDraftGuard)return;p.__gaDraftGuard=1;"
    "var K='ga_chat_draft';"
    "function ta(){return d.querySelector('textarea[data-testid=stChatInputTextArea]')}"
    "function setV(el,v){var s=Object.getOwnPropertyDescriptor(p.HTMLTextAreaElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}))}"
    "function save(v){try{p.localStorage.setItem(K,v||'')}catch(e){}}"
    "function restore(){var t=ta();if(!t||t.value)return;var v='';try{v=p.localStorage.getItem(K)||''}catch(e){}if(v)setV(t,v)}"
    "function bind(){var t=ta();if(!t)return;if(!t.__gaDraftBind){t.__gaDraftBind=1;t.addEventListener('input',function(){save(t.value)},!0);"
    "t.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey)save(t.value)},!0)}"
    "var b=d.querySelector('[data-testid=stChatInputSubmitButton]');if(b&&!b.__gaDraftBind){b.__gaDraftBind=1;b.addEventListener('click',function(){var t2=ta();if(t2)save(t2.value)},!0)}"
    "restore()}"
    "bind();new MutationObserver(bind).observe(d.body,{childList:1,subtree:1});setInterval(restore,900)}()"
)
_embed_html(f'<script>{_js_scroll_fix};{_js_ime_fix};{_js_draft_guard}</script>', height=0)

if prompt := st.chat_input("any task?"):
    _embed_html("<script>try{window.parent.localStorage.removeItem('ga_chat_draft')}catch(e){}</script>", height=0)
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
    if cmd == '/route_status':
        st.session_state.messages = list(st.session_state.messages) + [
            {"role": "user", "content": cmd, "time": ts},
            {"role": "assistant", "content": _format_route_status(agent.route_status()), "time": ts}
        ]
        _reset_and_rerun()
    if cmd.startswith('/auto_route'):
        parts = cmd.split()
        if len(parts) != 2 or parts[1].lower() not in ('on', 'off'):
            result = '用法: /auto_route on|off'
        elif parts[1].lower() == 'on':
            agent.enable_auto_route(True, clear_manual_override=True)
            result = '✅ 自动路由已开启（并清除手动锁定）'
        else:
            agent.enable_auto_route(False)
            result = '⏸️ 自动路由已关闭'
        st.session_state.messages = list(st.session_state.messages) + [
            {"role": "user", "content": cmd, "time": ts},
            {"role": "assistant", "content": result, "time": ts}
        ]
        _reset_and_rerun()
    st.session_state.messages.append({"role": "user", "content": prompt})
    if hasattr(agent, '_pet_req') and not prompt.startswith('/'): agent._pet_req('state=walk')
    with st.chat_message("user"): st.markdown(prompt)

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
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.session_state.last_reply_time = int(time.time())

if st.session_state.autonomous_enabled:
    st.markdown(f"""<div id="last-reply-time" style="display:none">{st.session_state.get('last_reply_time', int(time.time()))}</div>""", unsafe_allow_html=True)
