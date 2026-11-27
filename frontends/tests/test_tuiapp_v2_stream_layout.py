"""Streaming repaint must not re-arrange the transcript on every token.

`Static.update()` defaults to `layout=True`, so the 20Hz streaming paint used to
mark the whole screen layout-dirty and make Textual re-arrange every message on
the next frame (5-15ms per chunk on a 30-turn session, ~430ms on long ones).

`_update_text()` only asks for a layout pass when the rendered height changes.
These tests pin both halves of that contract:
  * same-line growth must not request a layout (the perf fix),
  * content that grows new lines must still grow the widget (no clipping).
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FE = ROOT / "frontends"
if str(FE) not in sys.path:
    sys.path.insert(0, str(FE))



def _repo_module_names() -> set:
    """Top-level module names that really exist on disk in this checkout."""
    names = set()
    for base in (ROOT, FE):
        try:
            for entry in os.listdir(base):
                if entry.endswith(".py"):
                    names.add(entry[:-3])
        except OSError:
            pass
    return names


def _purge_stub_modules() -> None:
    """Drop bare-namespace stubs that sibling tests leave in ``sys.modules``.

    Several tests stub repo modules (``agentmain``, ``agent_loop``, ``llmcore``)
    for isolation; a leftover stub has ``__file__ is None`` and makes the real
    import fail with "cannot import name ... (unknown location)".  Only names
    that correspond to an actual ``.py`` in this checkout are considered, so
    builtins such as ``sys`` (which legitimately has no ``__file__``) are safe.
    """
    if sys.modules.get("sys") is not sys:            # some tests swap this one out
        sys.modules["sys"] = sys
    for name in _repo_module_names():
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__file__", None) is None:
            sys.modules.pop(name, None)


def _import_tui():
    """Import the TUI module with the import chain cleaned up first."""
    global T
    _purge_stub_modules()
    try:
        import tuiapp_v2
        return tuiapp_v2
    except ImportError:
        # A stubbed dependency deeper in the chain (imported by a real module)
        # only surfaces as ImportError on the first try; purge and retry once.
        for name in ("tuiapp_v2", "chatapp_common", "agentmain", "agent_loop", "llmcore"):
            sys.modules.pop(name, None)
        _purge_stub_modules()
        import tuiapp_v2
        return tuiapp_v2

T = None


class _StubAgent:
    """Enough of an agent for the app to mount a message without a network."""

    def __init__(self):
        self.log_path = ""
        self.inc_out = True
        self.task_dir = ""
        self.extra_sys_prompts = []
        self._rw_state = {}
        self.history = []
        self.name = "probe"
        self.model_name = "stub"
        self.last_tokens = (0, 0)
        self.token_usage = {}


def _patch_layout_counter(app):
    counts = {"n": 0, "t": 0.0}
    screen_cls = type(app.screen)
    original = screen_cls._refresh_layout

    def counting(screen, *args, **kwargs):
        start = time.perf_counter()
        try:
            return original(screen, *args, **kwargs)
        finally:
            counts["n"] += 1
            counts["t"] += time.perf_counter() - start

    screen_cls._refresh_layout = counting
    return counts, lambda: setattr(screen_cls, "_refresh_layout", original)


async def _scenario():
    app = T.GenericAgentTUI()
    app.make_agent = lambda sess: setattr(sess, "agent", _StubAgent())
    result = {}
    async with app.run_test(size=(120, 40)) as pilot:
        counts, restore = _patch_layout_counter(app)
        try:
            app.add_session("probe")
            sess = app.current
            m = T.ChatMessage(role="assistant", content="", done=False)
            sess.messages.append(m)
            app._mount_message(app.query_one("#messages"), m)

            # 1) growth inside one line: no layout requests, height stays 1.
            counts["n"] = 0
            for i in range(20):
                m.content = "x" * 10 + "y" * (i * 3)
                app._stream_update_assistant(m)
                await pilot.pause(0.01)
            widget = m._segment_widgets[-1]
            result["inline_layouts"] = counts["n"]
            result["inline_height"] = widget.size.height

            # 2) new lines: layout must be requested and the widget must grow.
            counts["n"] = 0
            for i in range(1, 9):
                m.content = "\n".join("line %02d" % j for j in range(i + 1))
                app._stream_update_assistant(m)
                await pilot.pause(0.05)
            result["line_layouts"] = counts["n"]
            result["line_height"] = widget.size.height
            last = widget.render_line(widget.size.height - 1)
            result["last_line"] = "".join(seg.text for seg in last).strip()
        finally:
            restore()
    return result


def test_streaming_repaint_is_height_aware():
    global T
    T = _import_tui()
    r = asyncio.run(_scenario())

    # A 20-chunk same-line stream must not re-arrange the screen per chunk.
    assert r["inline_layouts"] <= 4, (
        "same-line streaming requested %d layouts (expected <=4)" % r["inline_layouts"])
    assert r["inline_height"] == 1, (
        "single-line content occupies %d rows" % r["inline_height"])

    # Growing to 9 lines must be visible, not clipped.
    assert r["line_height"] == 9, (
        "9-line content rendered in %d rows" % r["line_height"])
    assert "line 08" in r["last_line"], (
        "last line clipped, got %r" % r["last_line"])
    assert r["line_layouts"] >= 6, (
        "line growth requested only %d layouts" % r["line_layouts"])
