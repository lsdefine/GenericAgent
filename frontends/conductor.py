import os, sys, re, time, json, uuid, queue, asyncio, threading, builtins
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

# Silence print() from subagent threads (they share stdout with conductor)
_original_print = builtins.print
def _filtered_print(*args, **kwargs):
    t = threading.current_thread()
    if t.name.startswith('subagent-'):
        return
    return _original_print(*args, **kwargs)
builtins.print = _filtered_print

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from pydantic import BaseModel

# allow: python frontends/conductor.py
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agentmain import GenericAgent

HOST = "127.0.0.1"
PORT = 8900
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conductor.html")

app = FastAPI(title="Conductor")

class ChatIn(BaseModel):
    msg: str
    role: str = "conductor"  # conductor | system | user

class StartSubagentIn(BaseModel):
    prompt: str

class SubagentActionIn(BaseModel):
    action: str = "intervene"  # intervene | abort | kill
    msg: str = ""

@dataclass
class SubAgentState:
    id: str
    agent: GenericAgent
    prompt: str
    reply: str = ""
    status: str = "running"  # running | stopped | failed | aborted
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_done: str = ""
    monitor_threads: List[threading.Thread] = field(default_factory=list)

subagents: Dict[str, SubAgentState] = {}
sub_lock = threading.RLock()
ws_clients: set[WebSocket] = set()
main_loop: Optional[asyncio.AbstractEventLoop] = None
# conductor event queue: only user messages and subagent-done events enter here.
conductor_events: "queue.Queue[dict]" = queue.Queue()
conductor_agent: Optional[GenericAgent] = None
conductor_started = False
chat_messages: List[dict] = []

def now_ms() -> int:
    return int(time.time() * 1000)

def short_id() -> str:
    return uuid.uuid4().hex[:8]

_TURN_SPLIT_RE = re.compile(r'\**LLM Running \(Turn \d+\) \.\.\.\**')
_SUMMARY_RE = re.compile(r'<summary>(.*?)</summary>\s*', re.DOTALL)

def extract_last_summary(full: str) -> str:
    """Extract the latest <summary> content for in-progress display."""
    matches = _SUMMARY_RE.findall(full or "")
    if not matches:
        return ""
    s = matches[-1].strip()
    return s[-1000:] if len(s) > 1000 else s

def extract_last_text_reply(full: str) -> str:
    """Extract only the last turn's text reply (like stapp.py fold_turns logic)."""
    # Split by turn markers, take last segment
    parts = _TURN_SPLIT_RE.split(full)
    last = parts[-1] if parts else full
    # Strip <summary> tags
    last = _SUMMARY_RE.sub('', last)
    # Strip [Status] and [Info] lines
    last = re.sub(r'\[(Status|Info)\][^\n]*\n?', '', last)
    # Strip trailing whitespace
    last = last.strip()
    # Cap length
    return last[-3000:] if len(last) > 3000 else last

def subagent_snapshot() -> list[dict]:
    with sub_lock:
        return [
            {
                "id": s.id,
                "prompt": s.prompt,
                "reply": (extract_last_summary(s.reply) if s.status == "running" else extract_last_text_reply(s.reply)) if s.reply else "",
                "status": s.status,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in subagents.values()
            if s.status != "aborted"
        ]

def schedule_broadcast(payload: dict):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(payload), main_loop)

async def broadcast(payload: dict):
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)

def push_cards():
    schedule_broadcast({"type": "subagents", "items": subagent_snapshot()})

def add_chat(msg: str, role: str = "conductor"):
    item = {"id": short_id(), "role": role, "msg": msg, "ts": now_ms(), "read": role != "user"}
    chat_messages.append(item)
    if len(chat_messages) > 200:
        del chat_messages[:-200]
    schedule_broadcast({"type": "chat", "item": item})
    return item

def start_agent_runner(agent: GenericAgent, name: str):
    t = threading.Thread(target=agent.run, name=name, daemon=True)
    t.start()
    return t

def monitor_display_queue(agent_id: str, dq: "queue.Queue", trigger_when_done: bool):
    """Consume one GenericAgent display_queue.

    next: update card only, never wake conductor.
    done: update card/chat, then wake conductor if this is subagent queue.
    """
    acc = ""
    while True:
        item = dq.get()
        if "next" in item:
            chunk = item.get("next") or ""
            # agent.inc_out=True means next is delta.
            acc += chunk
            with sub_lock:
                s = subagents.get(agent_id)
                if s:
                    s.reply = acc
                    s.status = "running"
                    s.updated_at = time.time()
            push_cards()
        if "done" in item:
            done = item.get("done") or acc
            with sub_lock:
                s = subagents.get(agent_id)
                if s:
                    s.reply = done
                    s.last_done = done
                    if s.status != "aborted":
                        s.status = "stopped"
                    s.updated_at = time.time()
            push_cards()
            if trigger_when_done:
                conductor_events.put({"type": "subagent_done", "id": agent_id, "reply": done})
            break

def start_subagent(prompt: str) -> dict:
    sid = short_id()
    agent = GenericAgent()
    agent.inc_out = True
    agent.verbose = False

    start_agent_runner(agent, f"subagent-{sid}")
    state = SubAgentState(id=sid, agent=agent, prompt=prompt, status="running")
    with sub_lock:
        subagents[sid] = state
    dq = agent.put_task(prompt, source=f"subagent:{sid}")
    mt = threading.Thread(target=monitor_display_queue, args=(sid, dq, True), name=f"monitor-{sid}", daemon=True)
    mt.start()
    state.monitor_threads.append(mt)
    push_cards()
    return {"id": sid, "status": "running"}

def keyinfo_subagent(sid: str, msg: str) -> dict:
    """Inject into agent's working key_info; visible from next turn onward."""
    with sub_lock:
        s = subagents.get(sid)
    if not s:
        return {"error": "subagent not found", "id": sid}
    h = s.agent.handler
    h.working['key_info'] = h.working.get('key_info', '') + f"\n[MASTER] {msg}"
    s.updated_at = time.time()
    return {"id": sid, "status": "keyinfo_injected"}

def input_subagent(sid: str, msg: str) -> dict:
    """Start a new task round (used for input/reply when agent is stopped)."""
    with sub_lock:
        s = subagents.get(sid)
    if not s:
        return {"error": "subagent not found", "id": sid}
    if s.status == "running":
        return {"error": "subagent is still running, cannot input/reply. Start a new subagent instead.", "id": sid}
    s.prompt = msg
    s.reply = ""
    s.status = "running"
    s.updated_at = time.time()
    dq = s.agent.put_task(msg, source=f"subagent:{sid}")
    mt = threading.Thread(target=monitor_display_queue, args=(sid, dq, True), name=f"monitor-{sid}", daemon=True)
    mt.start()
    s.monitor_threads.append(mt)
    push_cards()
    return {"id": sid, "status": "running"}

def conductor_readme() -> str:
    base = f"http://{HOST}:{PORT}"
    return "\n".join([
        f"Conductor API\tBase: {base}",
        "",
        "POST /chat\tbody: {\"msg\": \"...\"}\t给用户发消息",
        "POST /subagent\tbody: {\"prompt\": \"...\"}\t启动新subagent，返回 {\"id\": \"xxx\"}",
        'POST /subagent/{id}\tbody: {\"action\": \"keyinfo\", \"msg\": \"...\"}\t注入key_info（agent下轮可见）',
        'POST /subagent/{id}\tbody: {\"action\": \"input\", \"msg\": \"...\"}\t开新一轮任务（agent停下后追加）',
        'POST /subagent/{id}\tbody: {\"action\": \"stop\"}\t中断执行但保留（可继续input/reply）',
        'POST /subagent/{id}\tbody: {\"action\": \"kill\"}\t彻底杀死（从卡片消失，不可复用）',
        "GET /chat?last=N\t返回最近N条对话（默认20）",
        "GET /subagent\t返回 {\"items\": [...]}\t查看所有subagent状态",
        "GET /readme\t本文档",
        "",
        "触发时机: 用户新消息 | subagent done",
    ])

def conductor_prompt_from_events(events: list) -> str:
    # 极简摘要：subagent数量和状态
    with sub_lock:
        running = sum(1 for s in subagents.values() if s.status == "running")
        stopped = sum(1 for s in subagents.values() if s.status != "running")
    unread = sum(1 for m in chat_messages if m.get("role") == "user" and not m.get("read"))
    done_count = sum(1 for e in events if e.get("type") == "subagent_done")
    summary = f"subagents: {running} running, {stopped} stopped | {unread}条用户未读消息, {done_count}个subagent完成报告"
    base = f"http://{HOST}:{PORT}"
    return f"""你是agent总管。用户只和你对话，你负责调度、验收、交付，目标是降低用户管理多个agent的负担。
API: {base}；先requests，GET /readme查用法，GET /chat读未读对话，GET /subagent看状态；POST /chat是唯一对用户说话方式。

铁律：
- 绝不亲自执行任务/探测环境；一切执行交给subagent。你只分析、派遣、审查、沟通。
- 每次唤醒只做最小必要动作（发消息/开subagent/reply/keyinfo/abort），做完立刻停，等待下次事件唤醒。
- 改写prompt时严禁添加用户未提及的假设、工具、前提条件。只能精炼/结构化用户原意，不能脑补，只能做很小的改写

用户消息流程：
1. 结合记忆、上下文和用户偏好判断真实需求；不清楚/不能代劳时，用精简checklist一次性问用户。
2. 判断是新任务还是延续现有任务；优先复用已有stopped subagent（用input追加），只有确实无关的新任务才新建。
3. 分派前必须POST /chat告知用户：改写后的prompt + 分派方案（新建/复用哪个subagent）。
4. 执行分派，完成即停。危险操作（改源码/删数据/安全敏感）必须改成先让subagent出方案；你验收后POST /chat请用户确认，确认后才继续执行。

subagent完成流程：
1. 读subagent输出；若最后一条不足以判断，GET /subagent或日志补足信息。
2. 预测用户是否满意；不满意就reply/keyinfo要求返工、修改、优化，继续监督，不急着报告。
3. 预计用户满意后，POST /chat给简洁交付报告。

原则：
- 信任subagent足够聪明，不要写具体步骤和容易探测的信息；能自己判断的自己判断，只在真正需要用户决策时打扰。
{summary}"""

def _auto_cleanup_loop():
    """Background: auto-abort stopped subagents idle for >1 hour."""
    IDLE_TIMEOUT = 3600  # 1 hour
    while True:
        time.sleep(300)  # check every 5 minutes
        now = time.time()
        to_abort = []
        with sub_lock:
            for sid, s in subagents.items():
                if s.status == "stopped" and (now - s.updated_at) > IDLE_TIMEOUT:
                    to_abort.append((sid, s))
        for sid, s in to_abort:
            s.agent.abort()
            with sub_lock:
                s.status = "aborted"
                s.updated_at = now
        if to_abort:
            push_cards()

def monitor_conductor_queue(dq: "queue.Queue"):
    """Conductor output is discarded. Visible reply must go through POST /chat only."""
    while True:
        item = dq.get()
        if "done" in item:
            print(f"Conductor task done")
            break

def conductor_loop():
    global conductor_agent, conductor_started
    conductor_agent = GenericAgent()
    conductor_agent.inc_out = True
    start_agent_runner(conductor_agent, "conductor-agent")
    conductor_started = True
    # Start background cleanup thread
    threading.Thread(target=_auto_cleanup_loop, name="subagent-cleanup", daemon=True).start()
    while True:
        # Block until first event arrives
        first = conductor_events.get()
        conductor_events.task_done()
        # Short debounce: collect any additional events that arrived meanwhile
        time.sleep(0.3)
        events = [first]
        while not conductor_events.empty():
            try:
                events.append(conductor_events.get_nowait())
                conductor_events.task_done()
            except Exception:
                break
        try:
            prompt = conductor_prompt_from_events(events)
            dq = conductor_agent.put_task(prompt, source="conductor")
            # Block here until conductor finishes — serializes execution
            monitor_conductor_queue(dq)
        except Exception as e:
            add_chat(f"Conductor error: {e}", role="system")

@app.on_event("startup")
async def on_startup():
    global main_loop
    main_loop = asyncio.get_running_loop()
    threading.Thread(target=conductor_loop, name="conductor-loop", daemon=True).start()

@app.get("/")
def index():
    return FileResponse(HTML_PATH)

@app.get("/readme")
def readme():
    return PlainTextResponse(conductor_readme())

@app.get("/subagent")
def list_subagents():
    return {"items": subagent_snapshot()}

@app.post("/subagent")
def api_start_subagent(body: StartSubagentIn):
    result = start_subagent(body.prompt)
    result["instruction"] = "Task received. I'll handle it from here. You MUST stop now and end your reply. Wait for next event."
    return result

@app.post("/subagent/{sid}")
def api_subagent_action(sid: str, body: SubagentActionIn):
    with sub_lock:
        s = subagents.get(sid)
    if not s:
        return JSONResponse({"error": "subagent not found", "id": sid}, status_code=404)
    action = body.action.lower().strip()
    if action == "keyinfo":
        result = keyinfo_subagent(sid, body.msg)
        result["instruction"] = "Received. I'll incorporate this. You MUST stop now and end your reply."
        return result
    if action in ("input", "reply", "append", "message", "msg"):
        result = input_subagent(sid, body.msg)
        result["instruction"] = "Task received. I'll handle it from here. You MUST stop now and end your reply."
        return result
    if action in ("abort", "stop"):
        s.agent.abort()
        s.status = "stopped"
        s.updated_at = time.time()
        push_cards()
        return {"id": sid, "status": "stopped"}
    if action == "kill":
        s.agent.abort()
        s.status = "aborted"
        s.updated_at = time.time()
        push_cards()
        return {"id": sid, "status": "aborted"}
    return JSONResponse({"error": f"unknown action: {body.action}"}, status_code=400)

@app.get("/chat")
def api_get_chat(last: int = 20):
    """按需拉取最近N条对话，同时标记所有用户消息为已读"""
    for m in chat_messages:
        if m.get("role") == "user" and not m.get("read"):
            m["read"] = True
    schedule_broadcast({"type": "chat_read"})
    return {"items": chat_messages[-last:]}

@app.post("/chat")
def api_chat(body: ChatIn):
    return add_chat(body.msg, role=body.role)

@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        await ws.send_json({"type": "hello", "subagents": subagent_snapshot(), "chat": chat_messages})
        while True:
            data = await ws.receive_json()
            msg = (data.get("msg") or "").strip()
            if not msg:
                continue
            add_chat(msg, role="user")
            conductor_events.put({"type": "user_message", "msg": msg})
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)

if __name__ == "__main__":
    import uvicorn, webbrowser, threading
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run("conductor:app", host=HOST, port=PORT, reload=False)
