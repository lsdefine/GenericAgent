import io
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Must run BEFORE importing agentmain — it reconfigures stdout at import time,
# and its submodules may print() during init.  We capture the raw binary stdout
# for ACP JSON-RPC, then redirect the text-mode stdout to stderr so any stray
# prints from agentmain/llmcore don't pollute the ACP channel.
if sys.platform == "win32":
    import msvcrt
    _stdout_fd = os.dup(sys.__stdout__.fileno())
    msvcrt.setmode(_stdout_fd, os.O_BINARY)
    _acp_stdout = os.fdopen(_stdout_fd, "wb", buffering=0)
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    os.set_inheritable(_stdout_fd, False)
    os.dup2(sys.stderr.fileno(), sys.__stdout__.fileno())
else:
    _stdout_fd = os.dup(sys.__stdout__.fileno())
    os.set_inheritable(_stdout_fd, False)
    _acp_stdout = os.fdopen(_stdout_fd, "wb", buffering=0)
    os.dup2(sys.stderr.fileno(), sys.__stdout__.fileno())


class _StdoutToStderrRouter(io.TextIOBase):
    """Redirect text-mode stdout to stderr so agentmain prints don't leak."""
    def writable(self): return True
    def write(self, s):
        if s:
            sys.stderr.write(s)
            sys.stderr.flush()
        return len(s) if s else 0
    def flush(self): sys.stderr.flush()

sys.stdout = _StdoutToStderrRouter()

import argparse
import queue
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentmain import GeneraticAgent


JSONRPC_VERSION = "2.0"
ACP_PROTOCOL_VERSION = 1


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def compact_json(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def parse_jsonrpc_line(line: str) -> Optional[Dict[str, Any]]:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def jsonrpc_error(code: int, message: str, req_id: Any = None, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": err}


def jsonrpc_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


def make_text_block(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def make_session_update(session_id: str, update: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": "session/update",
        "params": {"sessionId": session_id, "update": update},
    }


def make_message_update(session_id: str, role: str, blocks: List[Dict[str, Any]], message_id: Optional[str] = None) -> Dict[str, Any]:
    update: Dict[str, Any] = {
        "sessionUpdate": "agent_message",
        "role": role,
        "content": blocks,
    }
    if message_id:
        update["messageId"] = message_id
    return make_session_update(session_id, update)


def make_chunk_update(session_id: str, block: Dict[str, Any], message_id: str) -> Dict[str, Any]:
    return make_session_update(
        session_id,
        {
            "sessionUpdate": "agent_message_chunk",
            "content": block,
            "messageId": message_id,
        },
    )


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------

class SessionStore:
    """Simple JSON-backed store for ACP session metadata and history.

    Each session is stored as ``{sessions_dir}/{session_id}.json`` with:
    - id, cwd, createdAt, updatedAt, title
    - messages: list of {role, content_blocks}
    - llm_no: the llm index last used in the session
    """

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.sessions_dir = os.path.join(root_dir, "temp", "acp_sessions")
        os.makedirs(self.sessions_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> str:
        # session_id is already validated to be a safe identifier.
        return os.path.join(self.sessions_dir, f"{session_id}.json")

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        sessions: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for name in os.listdir(self.sessions_dir):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self.sessions_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (OSError, json.JSONDecodeError) as e:
                    eprint(f"[ACP-BRIDGE] skipping corrupt session file {path}: {e}")
                    continue
                sid = data.get("id")
                if not sid:
                    continue
                sessions[sid] = data
        return sessions

    def save(self, session_id: str, data: Dict[str, Any]) -> None:
        path = self._path(session_id)
        tmp_path = path + ".tmp"
        with self._lock:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, path)

    def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        with self._lock:
            try:
                os.remove(path)
                return True
            except FileNotFoundError:
                return False
            except OSError as e:
                eprint(f"[ACP-BRIDGE] failed to delete session file {path}: {e}")
                return False


# ---------------------------------------------------------------------------
# Terminal management
# ---------------------------------------------------------------------------

@dataclass
class TerminalState:
    terminal_id: str
    session_id: str
    process: subprocess.Popen
    output_buffer: List[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    exit_code: Optional[int] = None
    signal_name: Optional[str] = None
    released: bool = False


class TerminalManager:
    """Lightweight cross-platform pseudo-terminal manager for ACP terminal/* methods.

    Uses subprocess.Popen with pipes.  A real pty would be nicer on Unix but this
    keeps Windows parity without extra dependencies.
    """

    def __init__(self):
        self._terminals: Dict[str, TerminalState] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, command: str, args: List[str], cwd: Optional[str] = None,
               env: Optional[Dict[str, str]] = None, max_output_bytes: Optional[int] = None) -> TerminalState:
        terminal_id = f"t_{uuid.uuid4().hex}"
        cmd = [command] + args
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=cwd or os.getcwd(),
            env=proc_env,
            bufsize=0,
        )
        term = TerminalState(terminal_id=terminal_id, session_id=session_id, process=process)
        reader = threading.Thread(
            target=self._reader,
            args=(term, max_output_bytes or 2 * 1024 * 1024),
            daemon=True,
        )
        reader.start()
        with self._lock:
            self._terminals[terminal_id] = term
        return term

    def _reader(self, term: TerminalState, max_bytes: int) -> None:
        try:
            while True:
                chunk = term.process.stdout.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                with term.lock:
                    term.output_buffer.append(text)
                    # Truncate from the beginning if over limit.
                    current = "".join(term.output_buffer)
                    if len(current.encode("utf-8")) > max_bytes:
                        over = len(current.encode("utf-8")) - max_bytes
                        # Drop a bit more than needed to avoid thrashing.
                        current = current[over + 4096:]
                        term.output_buffer = [current]
        except Exception as e:
            eprint(f"[ACP-BRIDGE] terminal reader error: {e}")
        finally:
            try:
                term.process.wait(timeout=5)
                term.exit_code = term.process.returncode
            except subprocess.TimeoutExpired:
                term.process.kill()
                term.process.wait()
                term.signal_name = "SIGKILL"
            except Exception as e:
                eprint(f"[ACP-BRIDGE] terminal wait error: {e}")

    def get(self, terminal_id: str) -> Optional[TerminalState]:
        with self._lock:
            return self._terminals.get(terminal_id)

    def output(self, terminal_id: str) -> Dict[str, Any]:
        term = self.get(terminal_id)
        if term is None:
            return {"output": "", "truncated": False, "exitCode": None}
        with term.lock:
            output = "".join(term.output_buffer)
            truncated = False  # We truncate internally; client sees clean output.
            exit_code = term.exit_code
        return {"output": output, "truncated": truncated, "exitCode": exit_code}

    def wait_for_exit(self, terminal_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        term = self.get(terminal_id)
        if term is None:
            return {"exitCode": None, "signal": None}
        process = term.process
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exitCode": None, "signal": None}
        with term.lock:
            exit_code = term.exit_code if term.exit_code is not None else process.returncode
            signal_name = term.signal_name
        return {"exitCode": exit_code, "signal": signal_name}

    def kill(self, terminal_id: str) -> bool:
        term = self.get(terminal_id)
        if term is None:
            return False
        try:
            term.process.terminate()
        except Exception:
            pass
        return True

    def release(self, terminal_id: str) -> bool:
        with self._lock:
            term = self._terminals.pop(terminal_id, None)
        if term is None:
            return False
        try:
            term.process.kill()
            term.process.wait(timeout=2)
        except Exception:
            pass
        term.released = True
        return True

    def release_session_terminals(self, session_id: str) -> None:
        to_release: List[str] = []
        with self._lock:
            for tid, term in list(self._terminals.items()):
                if term.session_id == session_id:
                    to_release.append(tid)
        for tid in to_release:
            self.release(tid)


# ---------------------------------------------------------------------------
# Content block handling
# ---------------------------------------------------------------------------

class PromptBuilder:
    """Convert ACP content blocks into a prompt string.

    Images and audio are deliberately skipped per project policy; the bridge
    reports both as ``false`` in capabilities.  Embedded resources are inlined
    as text.
    """

    def __init__(self, root_dir: str):
        self.root_dir = root_dir

    def build(self, blocks: List[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            elif btype == "resource_link":
                name = block.get("name") or "resource"
                uri = block.get("uri") or ""
                desc = block.get("description") or ""
                parts.append(f"[ResourceLink] {name}: {uri}\n{desc}".strip())
            elif btype == "resource":
                uri = block.get("uri") or "resource"
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(f"[Resource] {uri}\n{text}")
                else:
                    parts.append(f"[Resource] {uri}")
            elif btype in ("image", "audio"):
                parts.append(f"[{btype.capitalize()} input omitted: capability not enabled]")
            else:
                parts.append(f"[Unsupported content block: {btype}]")
        return "\n\n".join(p for p in parts if p).strip()


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    session_id: str
    cwd: str
    agent: GeneraticAgent
    current_prompt_id: Any = None
    prompt_lock: threading.Lock = field(default_factory=threading.Lock)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    title: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    llm_no: int = 0
    persist_lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: bool = False


class GenericAgentAcpBridge:
    def __init__(self, llm_no: int = 0, root_dir: Optional[str] = None):
        self.llm_no = llm_no
        self.root_dir = root_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.store = SessionStore(self.root_dir)
        self.terminals = TerminalManager()
        self.prompt_builder = PromptBuilder(self.root_dir)
        self._json_out = _acp_stdout
        self._write_lock = threading.Lock()
        self._sessions: Dict[str, SessionState] = {}
        self._shutdown = False
        self._load_sessions()

    def _load_sessions(self) -> None:
        for sid, data in self.store.load_all().items():
            agent = self._new_agent(data.get("llm_no", self.llm_no))
            self._restore_history(agent, data.get("messages", []))
            session = SessionState(
                session_id=sid,
                cwd=data.get("cwd", os.getcwd()),
                agent=agent,
                created_at=data.get("createdAt", time.time()),
                updated_at=data.get("updatedAt", time.time()),
                title=data.get("title", ""),
                messages=data.get("messages", []),
                llm_no=data.get("llm_no", self.llm_no),
            )
            self._sessions[sid] = session

    def _new_agent(self, llm_no: Optional[int] = None) -> GeneraticAgent:
        agent = GeneraticAgent()
        agent.next_llm(llm_no if llm_no is not None else self.llm_no)
        agent.verbose = True
        agent.inc_out = True
        threading.Thread(target=agent.run, daemon=True).start()
        return agent

    def _restore_history(self, agent: GeneraticAgent, messages: List[Dict[str, Any]]) -> None:
        """Replay persisted ACP messages into the agent's backend history."""
        try:
            backend_history = agent.llmclient.backend.history
        except Exception:
            return
        for msg in messages:
            role = msg.get("role")
            blocks = msg.get("content", [])
            text = content_blocks_to_text(blocks)
            if role == "user":
                backend_history.append({"role": "user", "content": text})
            elif role == "assistant":
                backend_history.append({"role": "assistant", "content": text})

    def _persist_session(self, session: SessionState) -> None:
        data = {
            "id": session.session_id,
            "cwd": session.cwd,
            "createdAt": session.created_at,
            "updatedAt": time.time(),
            "title": session.title,
            "messages": session.messages,
            "llm_no": session.llm_no,
        }
        self.store.save(session.session_id, data)

    def write_message(self, msg: Dict[str, Any]) -> None:
        payload = compact_json(msg)
        raw = (payload + "\n").encode("utf-8")
        eprint(f"[ACP-BRIDGE] >>> {payload[:500]}")
        try:
            with self._write_lock:
                self._json_out.write(raw)
                self._json_out.flush()
        except Exception as e:
            eprint(f"[ACP-BRIDGE] WRITE FAILED: {type(e).__name__}: {e}")

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    def handle_initialize(self, req_id: Any, params: Dict[str, Any]) -> None:
        requested_version = params.get("protocolVersion", ACP_PROTOCOL_VERSION)
        version = ACP_PROTOCOL_VERSION if requested_version == ACP_PROTOCOL_VERSION else ACP_PROTOCOL_VERSION
        result = {
            "protocolVersion": version,
            "agentCapabilities": {
                "loadSession": True,
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": True,
                },
                "sessionCapabilities": {
                    "list": {},
                    "load": {},
                    "resume": {},
                    "delete": {},
                },
                "mcpCapabilities": {"http": False, "sse": False},
            },
            "agentInfo": {
                "name": "genericagent-acp",
                "title": "GenericAgent",
                "version": "0.2.0",
            },
            "authMethods": [],
        }
        self.write_message(jsonrpc_result(req_id, result))

    # -----------------------------------------------------------------------
    # Sessions
    # -----------------------------------------------------------------------

    def _make_session_info(self, session: SessionState) -> Dict[str, Any]:
        return {
            "sessionId": session.session_id,
            "cwd": session.cwd,
            "createdAt": session.created_at,
            "updatedAt": session.updated_at,
            "title": session.title or "Untitled session",
        }

    def handle_session_new(self, req_id: Any, params: Dict[str, Any]) -> None:
        cwd = params.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            self.write_message(jsonrpc_error(-32602, "cwd is required", req_id))
            return
        if not os.path.isabs(cwd):
            cwd = os.path.abspath(cwd)
        session_id = f"ga_{uuid.uuid4().hex}"
        agent = self._new_agent(self.llm_no)
        session = SessionState(
            session_id=session_id,
            cwd=cwd,
            agent=agent,
            llm_no=self.llm_no,
        )
        self._sessions[session_id] = session
        self._persist_session(session)
        self.write_message(
            jsonrpc_result(
                req_id,
                {
                    "sessionId": session_id,
                    "modes": None,
                    "configOptions": None,
                },
            )
        )

    def handle_session_list(self, req_id: Any, params: Dict[str, Any]) -> None:
        cwd_filter = params.get("cwd")
        sessions = []
        for session in self._sessions.values():
            if cwd_filter and session.cwd != cwd_filter:
                continue
            sessions.append(self._make_session_info(session))
        sessions.sort(key=lambda s: s["updatedAt"], reverse=True)
        self.write_message(jsonrpc_result(req_id, {"sessions": sessions, "nextCursor": None}))

    def handle_session_load(self, req_id: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        session = self._sessions.get(session_id)
        if session is None:
            # Try loading from disk if not already in memory.
            data = self.store.load_all().get(session_id)
            if data is None:
                self.write_message(jsonrpc_error(-32602, "unknown sessionId", req_id))
                return
            agent = self._new_agent(data.get("llm_no", self.llm_no))
            self._restore_history(agent, data.get("messages", []))
            session = SessionState(
                session_id=session_id,
                cwd=data.get("cwd", os.getcwd()),
                agent=agent,
                created_at=data.get("createdAt", time.time()),
                updated_at=data.get("updatedAt", time.time()),
                title=data.get("title", ""),
                messages=data.get("messages", []),
                llm_no=data.get("llm_no", self.llm_no),
            )
            self._sessions[session_id] = session

        # Stream conversation history back to the client.
        for msg in session.messages:
            self.write_message(
                make_message_update(session_id, msg.get("role", "user"), msg.get("content", []))
            )

        self.write_message(
            jsonrpc_result(
                req_id,
                {
                    "sessionId": session_id,
                    "modes": None,
                    "configOptions": None,
                },
            )
        )

    def handle_session_resume(self, req_id: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        session = self._sessions.get(session_id)
        if session is None:
            data = self.store.load_all().get(session_id)
            if data is None:
                self.write_message(jsonrpc_error(-32602, "unknown sessionId", req_id))
                return
            agent = self._new_agent(data.get("llm_no", self.llm_no))
            self._restore_history(agent, data.get("messages", []))
            session = SessionState(
                session_id=session_id,
                cwd=data.get("cwd", os.getcwd()),
                agent=agent,
                created_at=data.get("createdAt", time.time()),
                updated_at=data.get("updatedAt", time.time()),
                title=data.get("title", ""),
                messages=data.get("messages", []),
                llm_no=data.get("llm_no", self.llm_no),
            )
            self._sessions[session_id] = session
        self.write_message(
            jsonrpc_result(
                req_id,
                {
                    "sessionId": session_id,
                    "modes": None,
                    "configOptions": None,
                },
            )
        )

    def handle_session_delete(self, req_id: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        session = self._sessions.pop(session_id, None)
        if session is not None:
            try:
                session.agent.abort()
            except Exception:
                pass
            self.terminals.release_session_terminals(session_id)
        self.store.delete(session_id)
        self.write_message(jsonrpc_result(req_id, {}))

    def handle_session_close(self, req_id: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        session = self._sessions.pop(session_id, None)
        if session is not None:
            try:
                session.agent.abort()
            except Exception:
                pass
            self.terminals.release_session_terminals(session_id)
            self._persist_session(session)
        self.write_message(jsonrpc_result(req_id, {}))

    # -----------------------------------------------------------------------
    # Prompts
    # -----------------------------------------------------------------------

    def handle_session_prompt(self, req_id: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        prompt_blocks = params.get("prompt")
        session = self._sessions.get(session_id)
        if session is None:
            self.write_message(jsonrpc_error(-32602, "unknown sessionId", req_id))
            return
        if not isinstance(prompt_blocks, list):
            self.write_message(jsonrpc_error(-32602, "prompt must be an array", req_id))
            return
        prompt_text = self.prompt_builder.build(prompt_blocks)
        if not prompt_text:
            self.write_message(jsonrpc_error(-32602, "prompt must contain text or supported content", req_id))
            return

        # Persist the user turn.
        user_message = {"role": "user", "content": [b for b in prompt_blocks if isinstance(b, dict)]}
        session.messages.append(user_message)
        session.updated_at = time.time()
        self._persist_session(session)

        with session.prompt_lock:
            if session.current_prompt_id is not None:
                self.write_message(
                    jsonrpc_error(-32603, "session already has an active prompt", req_id)
                )
                return
            session.current_prompt_id = req_id

        def run_prompt() -> None:
            stop_reason = "end_turn"
            message_id = f"msg_{uuid.uuid4().hex}"
            assistant_blocks: List[Dict[str, Any]] = []
            try:
                dq = session.agent.put_task(prompt_text, source="acp")
                assistant_text = self._drain_agent_queue(session, dq, message_id)
                if assistant_text:
                    assistant_blocks = [make_text_block(assistant_text)]
            except Exception as exc:
                err_text = f"[Bridge error] {type(exc).__name__}: {exc}"
                assistant_blocks = [make_text_block(err_text)]
                self.write_message(make_chunk_update(session.session_id, make_text_block(err_text), message_id))
                eprint("[GenericAgent ACP] prompt thread failed:", traceback.format_exc())
            finally:
                with session.prompt_lock:
                    finished_req_id = session.current_prompt_id
                    session.current_prompt_id = None
                    was_cancelled = session.cancelled
                    session.cancelled = False
                if was_cancelled:
                    stop_reason = "cancelled"
                if assistant_blocks:
                    session.messages.append({"role": "assistant", "content": assistant_blocks})
                    session.updated_at = time.time()
                    self._persist_session(session)
                if finished_req_id is not None:
                    time.sleep(0.1)
                    self.write_message(
                        jsonrpc_result(finished_req_id, {"stopReason": stop_reason})
                    )

        threading.Thread(target=run_prompt, daemon=True).start()

    def _drain_agent_queue(self, session: SessionState, dq: "queue.Queue[Dict[str, Any]]", message_id: str) -> str:
        sent_any = False
        full_resp = ""
        while True:
            item = dq.get()
            if not isinstance(item, dict):
                continue
            if "next" in item and "done" not in item:
                delta = item["next"]
                if isinstance(delta, str) and delta:
                    sent_any = True
                    full_resp += delta
                    try:
                        self.write_message(
                            make_chunk_update(session.session_id, make_text_block(delta), message_id)
                        )
                    except Exception as e:
                        eprint(f"[ACP-BRIDGE] ERROR writing update: {e}")
            if "done" in item:
                if not sent_any:
                    done_text = item["done"]
                    if isinstance(done_text, str) and done_text:
                        full_resp = done_text
                        try:
                            self.write_message(
                                make_chunk_update(session.session_id, make_text_block(done_text), message_id)
                            )
                        except Exception as e:
                            eprint(f"[ACP-BRIDGE] ERROR writing done: {e}")
                break
        return full_resp

    def handle_session_cancel(self, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        session = self._sessions.get(session_id)
        if session is None:
            return
        if session.current_prompt_id is not None:
            session.cancelled = True
            session.agent.abort()

    # -----------------------------------------------------------------------
    # Terminals
    # -----------------------------------------------------------------------

    def handle_terminal_create(self, req_id: Any, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        if session_id not in self._sessions:
            self.write_message(jsonrpc_error(-32602, "unknown sessionId", req_id))
            return
        command = params.get("command")
        if not isinstance(command, str) or not command:
            self.write_message(jsonrpc_error(-32602, "command is required", req_id))
            return
        args = params.get("args") or []
        if not isinstance(args, list):
            self.write_message(jsonrpc_error(-32602, "args must be an array", req_id))
            return
        cwd = params.get("cwd")
        env = params.get("env")
        max_output_bytes = params.get("maxOutputBytes")
        term = self.terminals.create(
            session_id=session_id,
            command=command,
            args=args,
            cwd=cwd,
            env=env,
            max_output_bytes=max_output_bytes,
        )
        self.write_message(jsonrpc_result(req_id, {"terminalId": term.terminal_id}))

    def handle_terminal_output(self, req_id: Any, params: Dict[str, Any]) -> None:
        terminal_id = params.get("terminalId")
        if self.terminals.get(terminal_id) is None:
            self.write_message(jsonrpc_error(-32602, "unknown terminalId", req_id))
            return
        result = self.terminals.output(terminal_id)
        self.write_message(jsonrpc_result(req_id, result))

    def handle_terminal_wait_for_exit(self, req_id: Any, params: Dict[str, Any]) -> None:
        terminal_id = params.get("terminalId")
        timeout = params.get("timeout")
        if self.terminals.get(terminal_id) is None:
            self.write_message(jsonrpc_error(-32602, "unknown terminalId", req_id))
            return
        result = self.terminals.wait_for_exit(terminal_id, timeout=timeout)
        self.write_message(jsonrpc_result(req_id, result))

    def handle_terminal_kill(self, req_id: Any, params: Dict[str, Any]) -> None:
        terminal_id = params.get("terminalId")
        if not self.terminals.kill(terminal_id):
            self.write_message(jsonrpc_error(-32602, "unknown terminalId", req_id))
            return
        self.write_message(jsonrpc_result(req_id, {}))

    def handle_terminal_release(self, req_id: Any, params: Dict[str, Any]) -> None:
        terminal_id = params.get("terminalId")
        if not self.terminals.release(terminal_id):
            self.write_message(jsonrpc_error(-32602, "unknown terminalId", req_id))
            return
        self.write_message(jsonrpc_result(req_id, {}))

    # -----------------------------------------------------------------------
    # Dispatch
    # -----------------------------------------------------------------------

    def handle_message(self, msg: Dict[str, Any]) -> None:
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        try:
            if method == "initialize":
                self.handle_initialize(req_id, params)
            elif method == "session/new":
                self.handle_session_new(req_id, params)
            elif method == "session/prompt":
                self.handle_session_prompt(req_id, params)
            elif method == "session/cancel":
                self.handle_session_cancel(params)
            elif method == "session/list":
                self.handle_session_list(req_id, params)
            elif method == "session/load":
                self.handle_session_load(req_id, params)
            elif method == "session/resume":
                self.handle_session_resume(req_id, params)
            elif method == "session/delete":
                self.handle_session_delete(req_id, params)
            elif method == "session/close":
                self.handle_session_close(req_id, params)
            elif method == "terminal/create":
                self.handle_terminal_create(req_id, params)
            elif method == "terminal/output":
                self.handle_terminal_output(req_id, params)
            elif method == "terminal/wait_for_exit":
                self.handle_terminal_wait_for_exit(req_id, params)
            elif method == "terminal/kill":
                self.handle_terminal_kill(req_id, params)
            elif method == "terminal/release":
                self.handle_terminal_release(req_id, params)
            elif method is None:
                if req_id is not None:
                    self.write_message(jsonrpc_error(-32600, "invalid request", req_id))
            else:
                if req_id is not None:
                    self.write_message(jsonrpc_error(-32601, f"method not found: {method}", req_id))
        except Exception as exc:
            eprint("[GenericAgent ACP] request handler failed:", traceback.format_exc())
            if req_id is not None:
                self.write_message(
                    jsonrpc_error(-32603, f"internal error: {type(exc).__name__}: {exc}", req_id)
                )

    def serve(self) -> None:
        eprint("[GenericAgent ACP] bridge started")
        stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace") if hasattr(sys.stdin, 'buffer') else sys.stdin
        for raw_line in stdin:
            msg = parse_jsonrpc_line(raw_line)
            if msg is None:
                continue
            self.handle_message(msg)
            if self._shutdown:
                break
        eprint("[GenericAgent ACP] bridge stopped")


def content_blocks_to_text(blocks: List[Dict[str, Any]]) -> str:
    """Fallback helper for restoring persisted history into backend format."""
    parts: List[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
        elif block_type == "resource_link":
            name = block.get("name") or "resource"
            uri = block.get("uri") or ""
            desc = block.get("description") or ""
            parts.append(f"[ResourceLink] {name}: {uri}\n{desc}".strip())
        elif block_type == "resource":
            uri = block.get("uri") or "resource"
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append(f"[Resource] {uri}\n{text}")
            else:
                parts.append(f"[Resource] {uri}")
        elif block_type in ("image", "audio"):
            parts.append(f"[{block_type.capitalize()} omitted]")
        else:
            parts.append(f"[Unsupported content block: {block_type}]")
    return "\n\n".join(p for p in parts if p).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="GenericAgent ACP bridge over stdio")
    parser.add_argument("--llm-no", type=int, default=0, help="LLM index for GenericAgent")
    parser.add_argument("--root-dir", type=str, default=None, help="Project root directory")
    args = parser.parse_args()
    bridge = GenericAgentAcpBridge(llm_no=args.llm_no, root_dir=args.root_dir)
    bridge.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
