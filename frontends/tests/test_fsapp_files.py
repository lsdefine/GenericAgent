"""Exercise fsapp's real file helpers and completion paths without Lark or a model.

As in the bridge contracts, AST loading avoids module-level configuration and
SDK startup. UI/network boundaries and queued task execution are fake; helpers,
completion methods and the task hook are loaded directly from production source.
"""
import ast
import asyncio
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "fsapp.py"


@pytest.fixture
def files(tmp_path, monkeypatch):
    root, work = tmp_path / "repo", tmp_path / "custom 工作目录"
    root.mkdir()
    work.mkdir()
    monkeypatch.chdir(root)
    uploads, messages = [], []

    def upload(path):
        uploads.append((Path(path).resolve(), Path(path).read_bytes()))
        return "fake-key"

    class ChatMixin:
        def __init__(self, agent, user_tasks):
            self.agent, self.user_tasks = agent, user_tasks

    ns = {
        "os": os, "json": json, "re": re, "asyncio": asyncio,
        "Q": queue, "threading": threading, "time": time, "uuid": uuid,
        "traceback": __import__("traceback"),
        "AgentChatMixin": ChatMixin, "_TaskCard": Mock(),
        "_display_text": lambda text: text, "FILE_HINT": "[FILE:filepath]",
        "AGENT_TIMEOUT_SEC": 1,
        "_IMAGE_EXTS": {".png"}, "_AUDIO_EXTS": {".opus"}, "_VIDEO_EXTS": {".mp4"},
        "_upload_file_sync": upload, "_upload_image_sync": upload,
        "send_message": lambda *a, **kw: messages.append((a, kw)),
    }
    names = {"_extract_files", "_send_local_file", "_send_generated_files",
             "_make_task_hook", "FeishuApp"}
    nodes = [n for n in ast.parse(SOURCE.read_text(encoding="utf-8")).body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return SimpleNamespace(root=root, work=work, uploads=uploads, messages=messages, ns=ns)


@pytest.mark.parametrize("marker", ["report.txt", "reports/研究 报告.txt", "picture.png"])
def test_relative_file_uses_agent_cwd(files, marker):
    target = files.work / marker
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"generated")
    files.ns["_send_generated_files"]("chat", f"[FILE:{marker}]", cwd=str(files.work))
    assert files.uploads == [(target, b"generated")]


def test_agent_file_wins_over_same_name_in_process_cwd(files):
    (files.work / "report.txt").write_bytes(b"generated")
    (files.root / "report.txt").write_bytes(b"unrelated")
    files.ns["_send_generated_files"]("chat", "[FILE:report.txt]", cwd=str(files.work))
    assert files.uploads == [(files.work / "report.txt", b"generated")]


@pytest.mark.parametrize("marker", ["report.txt", "./temp/report.txt"])
def test_existing_process_relative_file_remains_usable(files, marker):
    target = files.root / marker
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"legacy")
    files.ns["_send_generated_files"]("chat", f"[FILE:{marker}]", cwd=str(files.work))
    assert files.uploads == [(target.resolve(), b"legacy")]


def test_absolute_file_is_unchanged(files):
    target = files.root / "absolute.txt"
    target.write_bytes(b"absolute")
    files.ns["_send_generated_files"]("chat", f"[FILE:{target}]", cwd=str(files.work))
    assert files.uploads == [(target, b"absolute")]


@pytest.mark.parametrize("marker", ["missing.txt", "reports"])
def test_missing_file_or_directory_is_not_uploaded(files, marker):
    (files.work / "reports").mkdir()
    files.ns["_send_generated_files"]("chat", f"[FILE:{marker}]", cwd=str(files.work))
    assert files.uploads == []
    assert "文件不存在" in files.messages[0][0][1]


def test_no_handler_preserves_legacy_completion(files):
    target = files.root / "legacy.txt"
    target.write_bytes(b"legacy")
    app = files.ns["FeishuApp"](SimpleNamespace(), {})
    asyncio.run(app.send_done("chat", "[FILE:legacy.txt]"))
    assert files.uploads == [(target, b"legacy")]


@pytest.mark.parametrize("completion", ["send_done", "queue", "hook"])
def test_completion_passes_current_handler_cwd(files, completion):
    target = files.work / "report.txt"
    target.write_bytes(b"generated")
    raw = "[FILE:report.txt]"
    agent = SimpleNamespace(handler=SimpleNamespace(cwd=str(files.work)), abort=Mock())

    def put_task(*args, **kwargs):
        if completion == "hook":
            ctx = {"self": SimpleNamespace(parent=agent), "exit_reason": "done",
                   "response": SimpleNamespace(content=raw)}
            for hook in agent._turn_end_hooks.values():
                hook(ctx)
        out = queue.Queue()
        out.put({"done": raw})
        return out

    agent.put_task = put_task
    app = files.ns["FeishuApp"](agent, {})
    if completion == "send_done":
        asyncio.run(app.send_done("chat", raw, receive_id="group", receive_id_type="chat_id"))
    else:
        asyncio.run(app.run_agent("chat", "make a report", receive_id="group", receive_id_type="chat_id"))
        assert app.user_tasks == {}
        assert agent._turn_end_hooks == {}
    assert files.uploads == [(target, b"generated")]
    sent = [m for m in files.messages if m[1].get("msg_type") == "file"]
    assert len(sent) == 1
    assert sent[0][0][0] == "group"
    assert sent[0][1]["receive_id_type"] == "chat_id"
