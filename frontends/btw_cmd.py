"""`/btw` 命令：side question — 不打断主 Agent 的临时 subagent 问答。

- 持锁 deepcopy backend.history → 后台线程 backend.raw_ask 单次拉答
- 主 agent backend.history 零写入；不入 task_queue
- 答案 → display_queue 'done'（install 路径）或同步 return（frontend 路径）

复用 backend.raw_ask + make_messages，不新建 LLM 实例。
"""
from __future__ import annotations
import copy, os, threading, time
from typing import Optional


_WRAPPER_ZH = """<system-reminder>
这是用户的临时插问 (side question)。主 agent 仍在后台运行，**不会被打断**。

身份与边界：
- 你是一个独立的轻量 sub-agent
- 上下文里能看到主 agent 与用户的完整对话、最近的工具调用与结果
- 用户在问当前进展或顺便确认某事——基于已有信息**一次性**作答
- 没有任何工具可用：不要"让我查一下" / "我去试试" / 任何承诺动作
- 信息不足就坦白说"基于目前对话我不知道"

侧问内容如下：
</system-reminder>

{question}"""

_WRAPPER_EN = """<system-reminder>
This is a side question from the user. The main agent is NOT interrupted — it continues in the background.

Identity & boundaries:
- You are an independent lightweight sub-agent
- You can see the full conversation between the main agent and the user, plus recent tool calls/results
- The user is asking about current progress or a quick aside — answer in **one shot** from existing info
- You have NO tools — never say "let me check" / "I'll try" / any action promise
- If info is missing, just say "based on the conversation I don't know"

Question:
</system-reminder>

{question}"""

_TIMEOUT_SEC = 120


def _wrapper(): return _WRAPPER_EN if os.environ.get('GA_LANG') == 'en' else _WRAPPER_ZH


def _strip_cmd(query):
    s = (query or '').strip()
    return s[len('/btw'):].strip() if s.startswith('/btw') else s


def _help_text():
    return ('**/btw 用法**：side question — 临时问主 agent 当前进展，不打断主线\n\n'
            '`/btw <你的问题>`\n\n'
            '行为：抓取当前对话上下文 → 单轮纯文本作答（无工具）→ 主 agent 历史不变。')


def _snapshot_history(backend):
    """Lock + deepcopy: defends against concurrent compress_history_tags mutating inner blocks."""
    with backend.lock:
        return copy.deepcopy(list(backend.history))


def _build_wire(backend, history, sidequest_msg):
    """history + sidequest → wire-format. Dispatches: BaseSession subclasses → make_messages,
    Native* → raw pairs (raw_ask runs _fix/_drop/_ensure transforms itself)."""
    msgs = history + [sidequest_msg]
    if hasattr(backend, 'make_messages'):
        return backend.make_messages(msgs)
    return [{"role": m["role"], "content": list(m.get("content", []))} for m in msgs]


def _ask(agent, question, deadline):
    """One-shot raw_ask against current backend; never mutates backend.history."""
    backend = agent.llmclient.backend
    user_msg = {"role": "user",
                "content": [{"type": "text", "text": _wrapper().format(question=question)}]}
    wire = _build_wire(backend, _snapshot_history(backend), user_msg)
    text = ''
    for chunk in backend.raw_ask(wire):
        text += chunk
        if time.time() > deadline:
            return text + '\n\n⚠️ /btw 超时，仅返回部分回复。'
    return text


def _format(question, body, took):
    head = f'> 🟡 /btw {question}\n\n'
    return head + (body.strip() or '*(空回复)*') + f'\n\n*({took:.1f}s)*'


def _run(agent, question, deadline):
    """Catches errors at the boundary so neither caller path needs its own try/except."""
    try: return _ask(agent, question, deadline)
    except Exception as e: return f'❌ /btw 失败: {type(e).__name__}: {e}'


def handle(agent, query, display_queue) -> Optional[str]:
    """Slash-cmd entry (server-side, install path). Spawn worker; return None to consume."""
    question = _strip_cmd(query)
    if not question or question in ('help', '?', '-h', '--help'):
        display_queue.put({'done': _help_text(), 'source': 'system'})
        return None
    started = time.time()
    deadline = started + _TIMEOUT_SEC

    def worker():
        body = _run(agent, question, deadline)
        display_queue.put({'done': _format(question, body, time.time() - started), 'source': 'system'})

    threading.Thread(target=worker, daemon=True, name='btw-sidequest').start()
    return None


def handle_frontend_command(agent, query) -> str:
    """Sync entry for frontends wanting a string back (tg/wx/stapp/...)."""
    question = _strip_cmd(query)
    if not question or question in ('help', '?', '-h', '--help'):
        return _help_text()
    started = time.time()
    body = _run(agent, question, started + _TIMEOUT_SEC)
    return _format(question, body, time.time() - started)


def install(cls):
    """Idempotent monkey-patch: intercept /btw before original dispatch."""
    orig = cls._handle_slash_cmd
    if getattr(orig, '_btw_patched', False): return

    def patched(self, raw_query, display_queue):
        s = (raw_query or '').strip()
        if s == '/btw' or s.startswith('/btw ') or s.startswith('/btw\t'):
            r = handle(self, raw_query, display_queue)
            if r is None: return None
            return r
        return orig(self, raw_query, display_queue)

    patched._btw_patched = True
    cls._handle_slash_cmd = patched
