# -*- coding: utf-8 -*-
"""Pseudo-XML tool calls written into plain content must be reconstructed or retried.

Run:  python tests/test_text_tool_call.py   (or: pytest tests/test_text_tool_call.py -q)

Background (issue #863)
-----------------------
Some upstreams emit the tool call as **plain text** instead of a native `tool_calls`
array.  `_parse_text_tool_calls` only understood a trailing JSON `tool_use` array and
`<tool_use>`/`<tool_call>` JSON wrappers, so all of the shapes below fell through to
`ga.do_no_tool`, which had no matching guard, and the task ended silently.

    A  <code_run><script>…</script></code_run>
    B  <code_run><parameter name="script">…</parameter></code_run>
    C  <file_read">…</file_read>            stray quote after the tool name
    D  <type><parameter name="x">…</parameter           no tool name at all
    E  <||DSML||tool_calls><||DSML||invoke name="code_run">…
    F  <function=code_run><parameter=script>…</parameter></function>
    G  </code_run><code_run></code_run>                 empty shell
    H  <code_run><script>…</script>                     stream cut mid-call

A-C, E and F are reconstructable.  D, G and H are not: they must become a *retry*, never
a final answer and never an executable call.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llmcore  # noqa: E402

DSML = "\uff5c\uff5cDSML\uff5c\uff5c"

SHAPES = {
    "A": "<code_run>\n<script>print(1)</script>\n</code_run>",
    "B": '<code_run>\n<parameter name="script">print(1)</parameter>'
         '<parameter name="timeout">600</parameter>\n</code_run>',
    "C": '<file_read">\n<parameter name="path">/tmp/a.txt</parameter>\n</file_read>',
    "D": '<type>\n<parameter name="x">1</parameter>',
    "E": f'<{DSML}tool_calls>\n<{DSML}invoke name="code_run">\n'
         f'<{DSML}parameter name="script" string="true">print(1)</{DSML}parameter>\n'
         f'</{DSML}invoke>\n</{DSML}tool_calls>',
    "F": "<function=code_run><parameter=script>print(1)</parameter></function>",
    "G": "</code_run>\n<code_run>\n\n\n</code_run>",
    "H": "<code_run>\n<script>import os\nprint(os.getcwd()",
}

EXPECTED = {
    "A": ("code_run", {"script": "print(1)"}),
    "B": ("code_run", {"script": "print(1)", "timeout": 600}),
    "C": ("file_read", {"path": "/tmp/a.txt"}),
    "E": ("code_run", {"script": "print(1)"}),
    "F": ("code_run", {"script": "print(1)"}),
}

RESIDUE = {"D": "orphan", "G": "empty", "H": "unclosed"}


def _calls(content):
    calls, _ = llmcore._parse_pseudo_xml_tool_calls(content)
    return [(c.function.name, json.loads(c.function.arguments)) for c in calls]


def test_reconstructable_shapes():
    for shape, expected in EXPECTED.items():
        assert _calls(SHAPES[shape]) == [expected], shape
        assert llmcore.textual_tool_residue(SHAPES[shape]) is None, shape


def test_unreconstructable_shapes_become_a_retry():
    for shape, residue in RESIDUE.items():
        assert _calls(SHAPES[shape]) == [], shape
        assert llmcore.textual_tool_residue(SHAPES[shape]) == residue, shape


def test_closed_but_broken_script_is_residue():
    """A block that closes but cannot be executed safely is still a residue.

    If `_parse_pseudo_xml_tool_calls` merely dropped it, the reply would reach
    `do_no_tool` unchanged and be delivered as the final answer.
    """
    broken = "<code_run>\n<script>import os\nprint(os.getcwd()</script>\n</code_run>"
    assert _calls(broken) == []
    assert llmcore.textual_tool_residue(broken) == "invalid"


def test_cut_that_still_parses_is_not_executed():
    """The dangerous case: the stream is cut, but the fragment happens to be valid Python."""
    cut = "<code_run>\n<script>import os\nprint(1)"
    assert _calls(cut) == []
    assert llmcore.textual_tool_residue(cut) == "unclosed"


def test_negatives_produce_no_calls():
    for content in [
        "任务完成，没有异常。",
        "你可以用 `<code_run>` 来跑脚本。",
        "```xml\n<code_run>\n<script>print(1)</script>\n</code_run>\n```",
        '示例：{"type":"tool_use","name":"code_run","input":{"script":"print(1)"}}',
        "<thinking>…</thinking>\n<summary>一句话</summary>",
    ]:
        assert _calls(content) == [], content
        assert llmcore.textual_tool_residue(content) is None, content


def test_fenced_block_is_never_executed_even_at_offset_zero():
    """A fence that starts at index 0 must still be treated as a quotation."""
    fenced = "```\n<code_run>\n<script>print(1)</script>\n</code_run>\n```"
    assert _calls(fenced) == []


if __name__ == "__main__":
    fails = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                fails.append(f"{name}: {exc}")
    print("FAIL\n" + "\n".join(fails) if fails else "ALL PASS")
    sys.exit(1 if fails else 0)
