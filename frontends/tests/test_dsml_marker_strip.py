"""Contracts for DSML tool-call marker stripping (llmcore) and the leak guard (ga.py).

Symptom: DeepSeek sometimes emits its DSML tool-call markup as plain assistant text
(issue #804). The closed PR #805 added a per-chunk content filter, and upstream f7e4cc5
added a narrow ``content.rstrip().endswith('</... calls>')`` retry in ``ga.py``. Three
cases still slipped through and stalled the agent loop:

* closing tags (``</... parameter>``) -- the pattern required ``<`` directly followed by
  the DSML token, so a leading ``/`` never matched;
* the double full-width-pipe variant (``|P||P|DSML|P||P|``) -- matching started at the
  second pipe, leaving a stray ``<`` / ``</`` behind;
* markers split across SSE chunks -- filtering each chunk independently cannot see them.

These tests load the DSML helpers straight from ``llmcore.py`` (no import, no mykey, no
side effects) and pin the integration points.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
LLMCORE = ROOT / "llmcore.py"
GA = ROOT / "ga.py"

PIPE_ASCII = "|"
PIPE_FULL = chr(0xFF5C)   # fullwidth vertical line
PIPE_HEAVY = chr(0x2016)  # double vertical line

TAG_DOUBLE = PIPE_FULL * 2 + "DSML" + PIPE_FULL * 2   # ||DSML||
TAG_SINGLE = PIPE_FULL + "DSML" + PIPE_FULL           # |DSML|
TAG_HEAVY = PIPE_HEAVY + "DSML" + PIPE_HEAVY          # ||DSML|| (heavy)
TAG_ASCII = PIPE_ASCII + "DSML" + PIPE_ASCII          # |DSML|
ALL_TAGS = (TAG_DOUBLE, TAG_SINGLE, TAG_HEAVY, TAG_ASCII)


def _dsml_namespace() -> dict:
    """Exec only the DSML constants/helpers from llmcore.py, without importing it."""
    tree = ast.parse(LLMCORE.read_text(encoding="utf-8"))
    wanted_assign = {"_DSML_WS", "_DSML_PIPES", "_DSML_TAG", "_DSML_PATTERN", "_DSML_LEAK"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) in wanted_assign for target in node.targets
        ):
            body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "_strip_dsml_markers":
            body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "_DsmlStreamFilter":
            body.append(node)
    names = [type(node).__name__ + ":" + getattr(node, "name", "") for node in body]
    assert len(body) == 7, f"unexpected DSML declarations in llmcore.py: {names}"
    namespace: dict = {"re": re}
    exec(compile(ast.Module(body=body, type_ignores=[]), "llmcore_dsml.py", "exec"), namespace)
    return namespace


NS = _dsml_namespace()
STRIP = NS["_strip_dsml_markers"]
STREAM_FILTER = NS["_DsmlStreamFilter"]


def _reset_latch() -> None:
    NS["_DSML_LEAK"] = False


def test_strips_closing_tag_variants():
    """Regression for issue #804: '</' + token must be removed, not left as '</'."""
    for tag in ALL_TAGS:
        assert STRIP("</" + tag + " parameter>") == "", tag
        assert STRIP("</" + tag + " calls>") == "", tag


def test_strips_invoke_and_parameter_variants():
    for tag in ALL_TAGS:
        assert STRIP("<" + tag + ' invoke name="ShellCommand" arguments="{}">') == "", tag
        # markup is removed, the payload between the open/close markers is kept
        assert STRIP("<" + tag + ' parameter name="cmd">ls -la</' + tag + " parameter>") == "ls -la", tag


def test_strips_markers_around_and_inside_text():
    assert STRIP("before <" + TAG_SINGLE + " tool_calls>after") == "before after"
    assert STRIP("a</" + TAG_DOUBLE + " parameter>b") == "ab"


def test_plain_text_is_untouched_and_does_not_latch():
    _reset_latch()
    for text in ("<summary>ok</summary>", "1 < 2 and 3 > 2", "<thinking>x</thinking>", ""):
        assert STRIP(text) == text
    assert NS["_DSML_LEAK"] is False


def test_latch_is_set_when_a_marker_is_removed():
    """The latch is what lets ga.do_no_tool retry even if payload text survives."""
    _reset_latch()
    assert NS["_DSML_LEAK"] is False
    STRIP("</" + TAG_DOUBLE + " parameter>")
    assert NS["_DSML_LEAK"] is True


def test_stream_filter_removes_marker_split_across_chunks():
    stream_filter = STREAM_FILTER()
    marker = TAG_HEAVY + "tool_calls>"
    chunks = ["hello<" + marker[:3], marker[3:] + "world"]
    out = "".join(stream_filter.feed(chunk) for chunk in chunks) + stream_filter.flush()
    assert "DSML" not in out
    assert out == "helloworld"


def test_stream_filter_removes_marker_split_right_after_open_bracket():
    stream_filter = STREAM_FILTER()
    out = "".join(
        [
            stream_filter.feed("hi <"),
            stream_filter.feed(TAG_DOUBLE + " parameter>"),
            stream_filter.flush(),
        ]
    )
    assert out == "hi "


def test_stream_filter_flushes_plain_text_unchanged():
    stream_filter = STREAM_FILTER()
    out = "".join([stream_filter.feed("plain "), stream_filter.flush()])
    assert out == "plain "


def test_all_streamed_content_chunks_pass_through_the_filter():
    """Integration contract: every streamed content yield must be filtered."""
    source = LLMCORE.read_text(encoding="utf-8")
    # responses: delta, output_text.done, completed-snapshot fallback, incomplete/chat: delta
    assert source.count("yield dsml_f.feed(") == 4, "responses delta/done/completed + chat delta"
    assert source.count("dsml_f.flush()") == 2, "one flush per api_mode branch"
    assert "_DSML_LEAK = False  # this parse" in source, "latch reset per parse"


def test_non_streaming_paths_strip_too():
    source = LLMCORE.read_text(encoding="utf-8")
    assert 'content = _strip_dsml_markers(msg.get("content", ""))' in source
    assert '_txt = _strip_dsml_markers(p["text"])' in source


def test_ga_no_tool_guard_uses_latch_and_variant_agnostic_tail_check():
    source = GA.read_text(encoding="utf-8")
    assert "getattr(response, 'dsml_leak', False)" in source
    assert "</?[" + PIPE_ASCII + PIPE_FULL + PIPE_HEAVY + "]{1,2}DSML" in source
