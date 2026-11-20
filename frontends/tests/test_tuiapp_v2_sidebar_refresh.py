"""Sidebar repaint policy: paint only when what it draws actually changed.

Background: the streaming path calls `_refresh_sidebar()` on every 50ms paint
batch.  Before this policy that rebuilt the whole session table 20x/s.

A plain time-based throttle is *wrong* for this widget.  `render_sidebar()`
draws exactly four things per row — session id, name, status, and the Q/S
preview lines — and all four are covered by `_sidebar_visible_sig()`.  So the
correct policy is content-driven, not clock-driven:

* **While tokens stream**: status and history are frozen (messages are only
  appended at turn boundaries), so the signature is stable → strictly zero
  repaints, not "one every 5s".
* **The instant something really changes** (running→idle when `done` arrives, a
  new prompt, a fresh summary) → a single repaint, with no timer in between.
  This is the same edge-triggered behaviour the desktop notifier gets from its
  `agent_after` ping.
* `force=True` (switch / rename / rewind / theme) → paint regardless.

Run: pytest frontends/tests/test_tuiapp_v2_sidebar_refresh.py -v
"""
import asyncio
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "frontends"))

import tuiapp_v2 as T  # noqa: E402


class _StubAgent:
    """Minimal stand-in for GenericAgent: idle run loop + attrs add_session sets."""

    def __init__(self):
        self.log_path = ""
        self.inc_out = True
        self.task_dir = ""
        self.extra_sys_prompts = []
        self._rw_store = None
        self.history = []
        self._stop = threading.Event()
        self.llmclient = None

    def abort(self):
        pass

    def run(self):
        self._stop.wait(3600)


def _attach_history(sess, messages):
    sess.agent.llmclient = SimpleNamespace(
        backend=SimpleNamespace(history=messages))


def test_sidebar_repaints_only_when_rendered_content_changes():
    async def scenario():
        app = T.GenericAgentTUI(agent_factory=lambda: _StubAgent())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            paints = []
            real_paint = app._paint_sidebar

            def counting_paint():
                paints.append(time.monotonic())
                real_paint()

            app._paint_sidebar = counting_paint

            sid = next(iter(app.sessions))
            sess = app.sessions[sid]
            hist = [{"role": "user", "content": "hello"}]
            _attach_history(sess, hist)
            sess.status = "idle"

            # 0) baseline: force paints once and settles the painted signature
            app._refresh_sidebar(force=True)
            assert len(paints) == 1

            # 1) stream hot path: 20 calls, nothing rendered changed → zero paints
            for _ in range(20):
                app._refresh_sidebar()
            assert len(paints) == 1, "unchanged sidebar must not repaint"

            # 2) status flip (task finished) → immediate, no timer involved
            sess.status = "running"
            app._refresh_sidebar()
            assert len(paints) == 2, "status change must paint immediately"

            sess.status = "idle"
            started = time.monotonic()
            app._refresh_sidebar()
            assert len(paints) == 3, "running→idle must paint immediately"
            assert time.monotonic() - started < 1.0, \
                "done must land without waiting for any throttle window"

            # 3) turn boundary: Q/S preview changes → immediate repaint
            hist.append({"role": "assistant", "content": "<summary>did it</summary>"})
            app._refresh_sidebar()
            assert len(paints) == 4, "new summary preview must paint immediately"

            # 4) streaming into the same turn (backend.history untouched) → no paint
            for _ in range(20):
                app._refresh_sidebar()
            assert len(paints) == 4, "streaming must not repaint the sidebar"

            # 5) user action forces a paint even with an identical signature
            app._refresh_sidebar(force=True)
            assert len(paints) == 5

            # 6) no timer machinery: repaint is purely content-driven, so the
            #    app must never arm a delayed sidebar repaint.
            assert not hasattr(app, "_sidebar_timer")
            assert not hasattr(app, "_sidebar_dirty")

    asyncio.run(scenario())


def test_sidebar_preview_cache_avoids_rescanning_history():
    """Q/S derivation walks + regexes the history; memoise it per (list, len)."""
    app = T.GenericAgentTUI(agent_factory=lambda: _StubAgent())
    sess = T.AgentSession(agent_id=1, name="s", agent=_StubAgent())
    hist = [{"role": "user", "content": "hi"}]
    _attach_history(sess, hist)
    app.sessions = {1: sess}

    first = app._sidebar_visible_sig()
    calls = []
    real_user = T._sidebar_last_user

    def counting_user(s):
        calls.append(s)
        return real_user(s)

    T._sidebar_last_user = counting_user
    try:
        second = app._sidebar_visible_sig()
        assert second == first
        assert calls == [], "unchanged history must hit the cache"

        hist.append({"role": "assistant", "content": "<summary>ok</summary>"})
        third = app._sidebar_visible_sig()
        assert third != second, "appended history must invalidate the cache"
        assert len(calls) == 1
    finally:
        T._sidebar_last_user = real_user


def test_sidebar_signature_covers_everything_render_sidebar_draws():
    """Guard against a future render_sidebar field that the signature ignores."""
    import inspect
    src = inspect.getsource(T.render_sidebar)
    for token in ('sess.name', 'sess.status', '_sidebar_last_user',
                  '_sidebar_last_summary', 'sessions.items()'):
        assert token in src, f"render_sidebar draws {token}; keep the sig in sync"


def test_stream_path_uses_non_forced_refresh():
    """Streaming/fast paths must go through the signature check, not force."""
    src = (ROOT / "frontends" / "tuiapp_v2.py").read_text(encoding="utf-8")
    # the 50ms stream flush calls the non-forced form
    assert "self._refresh_sidebar()\n                    self._refresh_topbar()" in src
    # the 1s watchdog keeps its cheap (sid, status) pre-check
    # the non-forced path compares the full rendered-content signature
    assert "self._sidebar_visible_sig()" in src
    assert 'if not force and self._sidebar_visible_sig() == getattr(' in src
    assert 'self, "_sidebar_painted_sig", None):' in src
    assert "SIDEBAR_REFRESH_SEC" not in src, \
        "time-based throttle was removed in favour of content-driven refresh"
