import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    # Mark the ACP fd as non-inheritable so child processes can't write to it.
    os.set_inheritable(_stdout_fd, False)
    # Redirect the original stdout fd to stderr so child processes
    # (tool calls) don't write into the ACP JSON-RPC channel.
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
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agentmain import GeneraticAgent


JSONRPC_VERSION = "2.0"
ACP_PROTOCOL_VERSION = 1


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def make_text_block(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def make_session_update(session_id: str, update: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "method": "session/update",
        "params": {"sessionId": session_id, "update": update},
    }


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


def content_blocks_to_text(blocks: List[Dict[str, Any]]) -> str:
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
        elif block_type == "image":
            uri = block.get("uri") or "inline-image"
            parts.append(f"[Image omitted] {uri}")
        else:
            parts.append(f"[Unsupported content block: {block_type}]")
    return "\n\n".join(p for p in parts if p).strip()


def jsonrpc_error(code: int, message: str, req_id: Any = None, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "error": err}


def jsonrpc_result(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": result}


@dataclass
class SessionState:
    session_id: str
    cwd: str
    agent: GeneraticAgent
    current_prompt_id: Any = None
    prompt_lock: threading.Lock = field(default_factory=threading.Lock)


class GenericAgentAcpBridge:
    def __init__(self, llm_no: int = 0):
        self.llm_no = llm_no
        self._json_out = _acp_stdout
        self._write_lock = threading.Lock()
        self._sessions: Dict[str, SessionState] = {}
        self._shutdown = False

    def write_message(self, msg: Dict[str, Any]) -> None:
        payload = compact_json(msg)
        raw = (payload + "\n").encode("utf-8")
        method = msg.get("method", msg.get("id", "?"))
        eprint(f"[ACP-BRIDGE] >>> {payload[:500]}")
        try:
            with self._write_lock:
                self._json_out.write(raw)
                self._json_out.flush()
        except Exception as e:
            eprint(f"[ACP-BRIDGE] WRITE FAILED: {type(e).__name__}: {e}")

    def new_agent(self) -> GeneraticAgent:
        agent = GeneraticAgent()
        agent.next_llm(self.llm_no)
        agent.verbose = True
        agent.inc_out = True
        threading.Thread(target=agent.run, daemon=True).start()
        return agent

    def handle_initialize(self, req_id: Any, params: Dict[str, Any]) -> None:
        requested_version = params.get("protocolVersion", ACP_PROTOCOL_VERSION)
        version = ACP_PROTOCOL_VERSION if requested_version == ACP_PROTOCOL_VERSION else ACP_PROTOCOL_VERSION
        result = {
            "protocolVersion": version,
            "agentCapabilities": {
                "loadSession": False,
                "mcpCapabilities": {"http": False, "sse": False},
                "promptCapabilities": {
                    "image": False,
                    "audio": False,
                    "embeddedContext": False,
                },
                "sessionCapabilities": {},
            },
            "agentInfo": {
                "name": "genericagent-acp",
                "title": "GenericAgent",
                "version": "0.1.0",
            },
            "authMethods": [],
        }
        self.write_message(jsonrpc_result(req_id, result))

    def handle_session_new(self, req_id: Any, params: Dict[str, Any]) -> None:
        cwd = params.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            self.write_message(jsonrpc_error(-32602, "cwd is required", req_id))
            return
        if not os.path.isabs(cwd):
            cwd = os.path.abspath(cwd)
        session_id = f"ga_{uuid.uuid4().hex}"
        agent = self.new_agent()
        session = SessionState(session_id=session_id, cwd=cwd, agent=agent)
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
        prompt_text = content_blocks_to_text(prompt_blocks)
        if not prompt_text:
            self.write_message(jsonrpc_error(-32602, "prompt must contain text or supported content", req_id))
            return

        with session.prompt_lock:
            if session.current_prompt_id is not None:
                self.write_message(
                    jsonrpc_error(-32603, "session already has an active prompt", req_id)
                )
                return
            session.current_prompt_id = req_id

        def run_prompt() -> None:
            stop_reason = "end_turn"
            try:
                dq = session.agent.put_task(prompt_text, source="acp")
                self._drain_agent_queue(session, dq)
            except Exception as exc:
                stop_reason = "end_turn"
                self.write_message(
                    make_session_update(
                        session.session_id,
                        {
                            "sessionUpdate": "agent_message_chunk",
                            "content": make_text_block(
                                f"[Bridge error] {type(exc).__name__}: {exc}"
                            ),
                        },
                    )
                )
                eprint("[GenericAgent ACP] prompt thread failed:", traceback.format_exc())
            finally:
                with session.prompt_lock:
                    finished_req_id = session.current_prompt_id
                    session.current_prompt_id = None
                if finished_req_id is not None:
                    import time
                    time.sleep(0.1)
                    self.write_message(
                        jsonrpc_result(finished_req_id, {"stopReason": stop_reason})
                    )

        threading.Thread(target=run_prompt, daemon=True).start()

    def _drain_agent_queue(self, session: SessionState, dq: "queue.Queue[Dict[str, Any]]") -> None:
        sent_any = False
        while True:
            item = dq.get()
            if not isinstance(item, dict):
                continue
            # With inc_out=True, "next" items are already incremental deltas.
            if "next" in item and "done" not in item:
                delta = item["next"]
                if isinstance(delta, str) and delta:
                    sent_any = True
                    try:
                        self.write_message(
                            make_session_update(
                                session.session_id,
                                {
                                    "sessionUpdate": "agent_message_chunk",
                                    "content": make_text_block(delta),
                                },
                            )
                        )
                    except Exception as e:
                        eprint(f"[ACP-BRIDGE] ERROR writing update: {e}")
            if "done" in item:
                # "done" text has post-processing (</summary>\n\n insertion)
                # that shifts offsets — cannot safely compute a tail delta.
                # Only use "done" content if nothing was streamed (error case).
                if not sent_any:
                    done_text = item["done"]
                    if isinstance(done_text, str) and done_text:
                        try:
                            self.write_message(
                                make_session_update(
                                    session.session_id,
                                    {
                                        "sessionUpdate": "agent_message_chunk",
                                        "content": make_text_block(done_text),
                                    },
                                )
                            )
                        except Exception as e:
                            eprint(f"[ACP-BRIDGE] ERROR writing done: {e}")
                break

    def handle_session_cancel(self, params: Dict[str, Any]) -> None:
        session_id = params.get("sessionId")
        session = self._sessions.get(session_id)
        if session is None:
            return
        if session.current_prompt_id is not None:
            session.agent.abort()

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
            elif method == "session/load":
                self.write_message(jsonrpc_error(-32601, "session/load not supported", req_id))
            elif method == "session/list":
                self.write_message(jsonrpc_error(-32601, "session/list not supported", req_id))
            elif method == "session/close":
                self.write_message(jsonrpc_result(req_id, {}))
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


def main() -> int:
    parser = argparse.ArgumentParser(description="GenericAgent ACP bridge over stdio")
    parser.add_argument("--llm-no", type=int, default=0, help="LLM index for GenericAgent")
    args = parser.parse_args()
    bridge = GenericAgentAcpBridge(llm_no=args.llm_no)
    bridge.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
