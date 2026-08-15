"""Regression test for frontends/tuiapp_v2.py:6594 NameError on the
exit-boundary replay path.

Background
----------
`_on_stream(self, agent_id, task_id, text, done)` is invoked from
`_consume_display_queue` (a worker thread) via `call_from_thread`. The
function does NOT accept a `refresh_chrome` parameter, but its stale-replay
branch (when `s.current_task_id != task_id`) referenced `refresh_chrome` —
triggering `NameError: name 'refresh_chrome' is not defined` whenever an
exit-boundary replay settled an old assistant message.

The regular `done=True` path (line ~6603) handles the same situation by
always calling `_refresh_sidebar` + `_refresh_topbar`, so the fix mirrors
that.

Repro
-----
Construct a minimal `GenericAgentTUI` instance with a fake session whose
`current_task_id` is newer than the incoming `task_id` and call
`_on_stream(... task_id=old, done=True)`. Before the fix this raises
`NameError`; after the fix it returns cleanly and calls the three refresh
methods.
"""
from __future__ import annotations

import sys
import os
import importlib.util
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))                 # for `keysym`
sys.path.insert(0, str(ROOT / "frontends"))   # for `tuiapp_v2`

# Pre-import the textual/rich/keysym deps so spec.loader.exec_module() doesn't
# fall into the auto-install fallback (it requires network + write perms).
import textual  # noqa: F401
import rich  # noqa: F401
import keysym  # noqa: F401


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "tuiapp_v2_under_test", ROOT / "frontends" / "tuiapp_v2.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class StaleReplayNameErrorRepro(unittest.TestCase):
    def setUp(self) -> None:
        self.m = _load_module()
        self.app = self.m.GenericAgentTUI.__new__(self.m.GenericAgentTUI)
        # Minimal session state for the stale-replay branch.
        sess = types.SimpleNamespace()
        sess.agent = None
        sess.current_task_id = 99  # the new (replay owner's) task
        sess.messages = []
        sess.status = "idle"
        msg = types.SimpleNamespace(
            role="assistant",
            content="",
            done=False,
            task_id=42,            # the OLD task being settled
            _segment_widgets=None,
        )
        sess.messages.append(msg)
        self.app.sessions = {"s1": sess}
        self.app.current_id = "s1"

        # Counters for each refresh callback.
        self.calls = {
            "stream_update": 0,
            "refresh_messages": 0,
            "refresh_sidebar": 0,
            "refresh_topbar": 0,
            "ensure_spinner": 0,
        }

        def make(name):
            def _cb(*_a, **_k):
                self.calls[name] += 1
            _cb.__name__ = name
            return _cb

        self.app._stream_update_assistant = make("stream_update")
        self.app._refresh_messages = make("refresh_messages")
        self.app._refresh_sidebar = make("refresh_sidebar")
        self.app._refresh_topbar = make("refresh_topbar")
        self.app._ensure_spinner = make("ensure_spinner")

    def test_replay_path_runs_without_name_error(self) -> None:
        """Pre-fix this raises NameError; post-fix it returns cleanly."""
        try:
            self.app._on_stream("s1", 42, "final text", done=True)
        except NameError as exc:
            self.fail(f"Replay path raised NameError: {exc}")
        # Old assistant message must be marked done.
        msg = self.app.sessions["s1"].messages[0]
        self.assertTrue(msg.done, "old assistant message should be settled")
        self.assertEqual(msg.content, "final text")
        # Sidebar + topbar must refresh on settle, mirror the regular path.
        self.assertEqual(self.calls["refresh_sidebar"], 1)
        self.assertEqual(self.calls["refresh_topbar"], 1)
        self.assertEqual(self.calls["ensure_spinner"], 1)
        # messages refresh: 1 from the empty-_segment_widgets branch.
        self.assertEqual(self.calls["refresh_messages"], 1)
        # stream_update: not used (no widgets).
        self.assertEqual(self.calls["stream_update"], 0)

    def test_done_false_is_a_noop(self) -> None:
        """The replay path is gated on `done=True`; done=False must skip everything."""
        self.app._on_stream("s1", 42, "intermediate", done=False)
        for k, v in self.calls.items():
            self.assertEqual(v, 0, f"{k} should be 0 on done=False, got {v}")
        # The message is NOT marked done when done=False.
        msg = self.app.sessions["s1"].messages[0]
        self.assertFalse(msg.done)


if __name__ == "__main__":
    unittest.main()
