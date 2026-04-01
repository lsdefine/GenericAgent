import os, sys
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
try: sys.stdout.reconfigure(errors='replace')
except: pass
try: sys.stderr.reconfigure(errors='replace')
except: pass
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import streamlit as st
import time, json, re, threading, queue
from agentmain import GeneraticAgent

st.set_page_config(page_title="Cowork", layout="wide")

@st.cache_resource
def init():
    agent = GeneraticAgent()
    if agent.llmclient is None:
        st.error("⚠️ 未配置任何可用的 LLM 接口，请在 mykey.py 中添加 sider_cookie 或 oai_apikey+oai_apibase 等信息后重启。")
        st.stop()
    else:
        threading.Thread(target=agent.run, daemon=True).start()
    return agent

agent = init()

st.title("🖥️ Cowork")

if 'autonomous_enabled' not in st.session_state: st.session_state.autonomous_enabled = False

@st.fragment
def render_sidebar():
    current_idx = agent.llm_no
    st.caption(f"LLM Core: {current_idx}: {agent.get_llm_name()}", help="点击切换备用链路")
    last_reply_time = st.session_state.get('last_reply_time', 0)
    if last_reply_time > 0:
        st.caption(f"空闲时间：{int(time.time()) - last_reply_time}秒", help="当超过30分钟未收到回复时，系统会自动任务")
    if st.button("切换备用链路"):
        agent.next_llm()
        st.rerun(scope="fragment")
    if st.button("强行停止任务"):
        agent.abort()
        st.toast("已发送停止信号")
        st.rerun()
    if st.button("重新注入System Prompt"):
        agent.llmclient.last_tools = ''
        st.toast("下次将重新注入System Prompt")
    
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


def agent_backend_stream(prompt):
    display_queue = agent.put_task(prompt, source="user")
    response = ''
    try:
        while True:
            try: item = display_queue.get(timeout=1)
            except queue.Empty:
                yield response   # heartbeat: let outer st.markdown() run → Streamlit checks StopException
                continue
            if 'next' in item:
                response = item['next']; yield response
            if 'done' in item:
                yield item['done']; break
    finally: agent.abort()

if "messages" not in st.session_state: st.session_state.messages = []
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]): st.markdown(msg["content"], unsafe_allow_html=True)

# IME composition fix (macOS only) - prevents Enter from submitting during CJK input
if os.name != 'nt':
    import streamlit.components.v1 as components
    components.html('<script>!function(){if(window.parent.__imeFix)return;window.parent.__imeFix=1;var d=window.parent.document,c=0;d.addEventListener("compositionstart",()=>c=1,!0);d.addEventListener("compositionend",()=>c=0,!0);function f(){d.querySelectorAll("textarea[data-testid=stChatInputTextArea]").forEach(t=>{t.__imeFix||(t.__imeFix=1,t.addEventListener("keydown",e=>{e.key==="Enter"&&!e.shiftKey&&(e.isComposing||c||e.keyCode===229)&&(e.stopImmediatePropagation(),e.preventDefault())},!0))})}f();new MutationObserver(f).observe(d.body,{childList:1,subtree:1})}()</script>', height=0)

if prompt := st.chat_input("请输入指令"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt, unsafe_allow_html=False)  # 小心 XSS

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        response = ''
        for response in agent_backend_stream(prompt):
            message_placeholder.markdown(response + "▌", unsafe_allow_html=False)
        message_placeholder.markdown(response, unsafe_allow_html=False)
    st.session_state.messages.append({"role": "assistant", "content": response})
    st.session_state.last_reply_time = int(time.time())

if st.session_state.autonomous_enabled:
    st.markdown(f"""<div id="last-reply-time" style="display:none">{st.session_state.get('last_reply_time', int(time.time()))}</div>""", unsafe_allow_html=True)

