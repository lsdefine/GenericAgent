"""Contracts for text-channel tool-call recovery (#837).

Symptom (observed 2026-10-17, session 423177): DeepSeek ends a turn with the call
written as literal markup in the *text* channel -- "<code_run\">" (truncated) or a
complete "<code_run><parameter ...>...</parameter></code_run>" -- and returns no
tool_call at all.  The loop then treats the turn as a finished answer: nothing runs
and the agent just stops.

These tests pin the recovery helpers in ``llmcore.py`` and the two stream fixes that
made the failure invisible (``response.completed`` snapshot fallback, terminal-event
tracking).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LLMCORE = ROOT / "llmcore.py"


def _load_llmcore():
    spec = importlib.util.spec_from_file_location("llmcore_under_test", LLMCORE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


llmcore = _load_llmcore()
split = llmcore.split_text_tool_calls
TOOLS = {"code_run", "file_read", "file_write"}


def test_truncated_marker_is_partial():
    # exactly the shape that ended session 423177 at 15:34:17
    calls, partial = split('<summary>x</summary>\n\n<code_run">', TOOLS)
    assert calls == [] and partial is True


def test_bare_opening_tag_is_partial():
    calls, partial = split('blah\n<code_run>', TOOLS)
    assert calls == [] and partial is True


def test_complete_parameter_form_is_executable():
    text = '<summary>go</summary>\n<code_run><parameter name="script">print(1)</parameter></code_run>'
    calls, partial = split(text, TOOLS)
    assert partial is False
    assert calls == [("code_run", {"script": "print(1)"})]


def test_complete_tag_with_attributes_and_raw_body():
    text = '<code_run type="python">print("hi")</code_run>'
    calls, partial = split(text, TOOLS)
    assert partial is False
    assert calls == [("code_run", {"script": 'print("hi")', "type": "python"})]


def test_json_tool_use_form():
    payload = json.dumps({"name": "file_read", "arguments": {"path": "a.txt"}})
    calls, partial = split("<tool_use>" + payload + "</tool_use>", TOOLS)
    assert partial is False
    assert calls == [("file_read", {"path": "a.txt"})]


def test_quoted_sample_mid_reply_is_ignored():
    text = '示例：<code_run></code_run> 就是工具调用。\n然后用 file_read 读取。'
    calls, partial = split(text, TOOLS)
    assert calls == [] and partial is False


def test_text_after_closing_tag_is_ignored():
    text = '<code_run><parameter name="script">x=1</parameter></code_run>\n以上是脚本。'
    calls, partial = split(text, TOOLS)
    assert calls == [] and partial is False


def _run_sse(lines):
    gen = llmcore._parse_openai_sse(lines, "responses")
    chunks = []
    try:
        while True:
            chunks.append(next(gen))
    except StopIteration as e:
        return "".join(chunks), (e.value or [])


def _sse(obj):
    return "data: " + json.dumps(obj)


def test_completed_snapshot_recovers_tool_call():
    # no delta events at all; the call only exists in the terminal snapshot
    lines = [
        _sse({"type": "response.completed", "response": {"output": [
            {"type": "function_call", "name": "code_run", "arguments": '{"script":"print(2)"}', "call_id": "c1"}]}}),
    ]
    _, blocks = _run_sse(lines)
    tool = [b for b in blocks if b.get("type") == "tool_use"]
    assert tool and tool[0]["name"] == "code_run"
    assert tool[0]["input"] == {"script": "print(2)"}


def test_stream_without_terminal_event_is_flagged():
    lines = [_sse({"type": "response.output_text.delta", "delta": "partial answer"})]
    text, blocks = _run_sse(lines)
    assert "stream ended without a terminal event" in text


def test_incomplete_with_content_is_flagged():
    lines = [
        _sse({"type": "response.output_text.delta", "delta": "half a sentence"}),
        _sse({"type": "response.incomplete", "response": {"incomplete_details": {"reason": "max_output_tokens"}}}),
    ]
    text, _ = _run_sse(lines)
    assert "output truncated: max_output_tokens" in text

def _load_agent_loop():
    spec = importlib.util.spec_from_file_location("agent_loop_under_test", ROOT / "agent_loop.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


agent_loop = _load_agent_loop()


def test_schema_names_accept_the_openai_nested_form():
    # Regression: assets/tools_schema.json ships {"type": "function", "function": {"name": ...}}.
    # Reading only entry["name"] yielded an empty name set, and split_text_tool_calls
    # bails out immediately on an empty set -- so recovery silently never ran, and the
    # leaked markup reached the user (2026-10-17, after the first fix looked applied).
    names = agent_loop.tool_names_from_schema([
        {"type": "function", "function": {"name": "code_run"}},
        {"name": "flat_form_tool"},
        "junk",
        {},
    ])
    assert names == {"code_run", "flat_form_tool"}


def test_schema_names_of_the_shipped_schema():
    schema = json.loads((ROOT / "assets" / "tools_schema.json").read_text(encoding="utf-8"))
    names = agent_loop.tool_names_from_schema(schema)
    assert "code_run" in names and "file_write" in names and len(names) >= 9


def test_leaked_block_survives_a_language_tag_line_and_is_recovered():
    # The real leak ended with "...\n python\n</code_run>": the language tag sits
    # *inside* the block, so the tail still parses -- provided the name set is real.
    text = (
        "Run: list the files.\n\n"
        ' <code_run>\n import os\n print(os.getcwd())\n\n python\n </code_run> '
    )
    schema = json.loads((ROOT / "assets" / "tools_schema.json").read_text(encoding="utf-8"))
    names = agent_loop.tool_names_from_schema(schema)
    calls, partial = split(text, names)
    assert partial is False
    assert len(calls) == 1 and calls[0][0] == "code_run"
    assert "print(os.getcwd())" in calls[0][1]["script"]
