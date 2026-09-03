"""Smoke tests for genericagent_acp_bridge over stdio.

These tests exercise the non-LLM parts of the ACP bridge (initialize, auth,
session lifecycle, terminal management) without requiring valid API keys.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BRIDGE_PATH = PROJECT_ROOT / "frontends" / "genericagent_acp_bridge.py"
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"


class AcpClient:
    def __init__(self, process: subprocess.Popen):
        self.proc = process
        self._lock = threading.Lock()
        self._next_id = 1
        self._responses: dict[Any, dict[str, Any]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                if "id" in msg and msg["id"] is not None:
                    self._responses[msg["id"]] = msg
                else:
                    self._notifications.append(msg)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        raw = (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if req_id in self._responses:
                    return self._responses.pop(req_id)
            time.sleep(0.05)
        raise TimeoutError(f"No response for {method} (id={req_id})")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        raw = (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
        self.proc.stdin.write(raw)
        self.proc.stdin.flush()

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

    def notifications(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._notifications)


@pytest.fixture
def bridge(tmp_path: Path):
    """Start the ACP bridge in a temporary root directory."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [str(PYTHON), str(BRIDGE_PATH), "--root-dir", str(tmp_path), "--llm-no", "0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    client = AcpClient(proc)
    try:
        yield client
    finally:
        client.close()


def test_initialize(bridge: AcpClient) -> None:
    resp = bridge.call("initialize", {"protocolVersion": 1, "clientInfo": {"name": "test", "version": "1.0"}})
    assert "error" not in resp, resp.get("error")
    result = resp["result"]
    assert result["protocolVersion"] == 1
    caps = result["agentCapabilities"]
    assert caps["loadSession"] is True
    assert caps["promptCapabilities"]["audio"] is False
    assert caps["promptCapabilities"]["embeddedContext"] is True
    assert caps["promptCapabilities"]["image"] is False
    assert "list" in caps.get("sessionCapabilities", {})
    assert "delete" in caps.get("sessionCapabilities", {})


def test_session_lifecycle(bridge: AcpClient) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resp = bridge.call("session/new", {"cwd": tmp})
        assert "error" not in resp, resp.get("error")
        sid = resp["result"]["sessionId"]
        assert sid.startswith("ga_")

        resp = bridge.call("session/list")
        assert "error" not in resp, resp.get("error")
        sessions = resp["result"]["sessions"]
        assert any(s["sessionId"] == sid for s in sessions)

        resp = bridge.call("session/load", {"sessionId": sid})
        assert "error" not in resp, resp.get("error")
        assert resp["result"]["sessionId"] == sid

        resp = bridge.call("session/resume", {"sessionId": sid})
        assert "error" not in resp, resp.get("error")

        resp = bridge.call("session/delete", {"sessionId": sid})
        assert "error" not in resp, resp.get("error")

        resp = bridge.call("session/list")
        assert "error" not in resp, resp.get("error")
        sessions = resp["result"]["sessions"]
        assert not any(s["sessionId"] == sid for s in sessions)


def test_terminal_lifecycle(bridge: AcpClient) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resp = bridge.call("session/new", {"cwd": tmp})
        sid = resp["result"]["sessionId"]

        cmd = "python" if sys.platform == "win32" else "python3"
        resp = bridge.call("terminal/create", {
            "sessionId": sid,
            "command": cmd,
            "args": ["-c", "print('hello from terminal')"],
        })
        assert "error" not in resp, resp.get("error")
        tid = resp["result"]["terminalId"]

        # Wait briefly for the command to finish.
        time.sleep(1.0)
        resp = bridge.call("terminal/output", {"terminalId": tid})
        assert "error" not in resp, resp.get("error")
        assert "hello from terminal" in resp["result"]["output"]

        resp = bridge.call("terminal/release", {"terminalId": tid})
        assert "error" not in resp, resp.get("error")

        bridge.call("session/delete", {"sessionId": sid})


def test_prompt_builder_resource_and_omitted_media(tmp_path: Path) -> None:
    """Resources/embeddedContext are inlined; image/audio are omitted."""
    from frontends.genericagent_acp_bridge import PromptBuilder

    builder = PromptBuilder(str(tmp_path))
    text = builder.build([
        {"type": "text", "text": "Read the notes."},
        {"type": "resource", "uri": "file:///tmp/notes.md", "text": "hello world"},
        {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"},
        {"type": "audio", "data": "abc123", "mimeType": "audio/wav"},
    ])
    assert "Read the notes." in text
    assert "[Resource] file:///tmp/notes.md" in text
    assert "hello world" in text
    assert "[Image input omitted: capability not enabled]" in text
    assert "[Audio input omitted: capability not enabled]" in text


def test_chunk_update_includes_message_id() -> None:
    """Streaming chunks must carry a messageId so clients can reassemble them."""
    from frontends.genericagent_acp_bridge import make_chunk_update, make_text_block

    msg = make_chunk_update("sess-1", make_text_block("hello"), "msg-abc123")
    assert msg["method"] == "session/update"
    params = msg["params"]
    assert params["sessionId"] == "sess-1"
    update = params["update"]
    assert update["sessionUpdate"] == "agent_message_chunk"
    assert update["messageId"] == "msg-abc123"
    assert update["content"] == {"type": "text", "text": "hello"}
