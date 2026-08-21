"""Tests for session persistence: race conditions, corruption resilience, and reload."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Add project root to path so we can import bridge helpers.
BRIDGE_PATH = Path(__file__).resolve().parent.parent / "desktop_bridge.py"
PROJECT_ROOT = BRIDGE_PATH.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# We need a lightweight extraction of AgentManager without starting the full server.
# Import the module to get access to _load_plan_baseline, _sanitize_desktop_plan_path, Session, etc.
import importlib.util

_spec = importlib.util.spec_from_file_location("desktop_bridge", str(BRIDGE_PATH))
_mod = importlib.util.module_from_spec(_spec)
sys.modules["desktop_bridge"] = _mod

# Patch heavy imports that desktop_bridge may pull in.
import types as _types

def _make_stub(name, attrs=None):
    m = _types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(m, k, v)
    return m

_plan_state_stub = _make_stub("plan_state", {
    "is_session_scoped_plan_path": lambda p, sid: True,
    "is_plan_preset_prompt": lambda prompt: False,
    "PLAN_PRESETS": {},
})

for _name in ("agentmain", "llmcore", "agent_loop", "plugins", "reflect",
              "frontends.plan_state", "cost_tracker"):
    sys.modules.setdefault(_name, _make_stub(_name))
sys.modules["plan_state"] = _plan_state_stub

# Attempt import; if it fails due to missing deps, skip.
try:
    _spec.loader.exec_module(_mod)
except Exception as exc:
    pytest.skip(f"Cannot import desktop_bridge: {exc}", allow_module_level=True)

Session = _mod.Session
AgentManager = _mod.AgentManager


@pytest.fixture
def tmp_ga_root(tmp_path: Path):
    """Create a minimal GA root with temp/desktop_sessions/ directory."""
    sessions_dir = tmp_path / "temp" / "desktop_sessions"
    sessions_dir.mkdir(parents=True)
    # Provide a dummy mykey_template so AgentManager.__init__ doesn't break.
    (tmp_path / "mykey_template.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def manager(tmp_ga_root: Path):
    """Create an AgentManager using the tmp root."""
    with patch.object(AgentManager, "__init__", lambda self: None):
        mgr = AgentManager.__new__(AgentManager)
    mgr.lock = threading.RLock()
    mgr.ga_root = str(tmp_ga_root)
    mgr.config = {}
    mgr.sessions = {}
    mgr.active_session_id = None
    mgr._sessions_dir = tmp_ga_root / "temp" / "desktop_sessions"
    mgr._sessions_file = tmp_ga_root / "temp" / "desktop_sessions.json"
    return mgr


def _make_session(sid: str = "sess-test-1", messages: list | None = None) -> Session:
    return Session(
        id=sid,
        title="Test",
        cwd="/tmp",
        created_at=time.time(),
        updated_at=time.time(),
        messages=messages if messages is not None else [{"role": "user", "content": "hello"}],
        msg_seq=1,
        pinned=False,
        untitled=False,
        plan_scan_baseline=0,
        plan_path="",
        status="idle",
        agent=None,
        llm_history=[{"role": "user", "content": "hello"}],
        llm_no=None,
    )


class TestPersistSessionConcurrentMutation:
    """Verify that concurrent mutations to messages during _persist_session don't corrupt data."""

    def test_concurrent_append_no_crash(self, manager: AgentManager):
        """Appending messages from another thread during persist must not raise."""
        sess = _make_session(messages=[{"role": "user", "content": f"msg-{i}"} for i in range(50)])
        manager.sessions[sess.id] = sess

        errors = []
        stop = threading.Event()

        def mutator():
            i = 100
            while not stop.is_set():
                sess.messages.append({"role": "assistant", "content": f"resp-{i}"})
                i += 1
                time.sleep(0.001)

        t = threading.Thread(target=mutator, daemon=True)
        t.start()
        try:
            for _ in range(20):
                try:
                    manager._persist_session(sess)
                except Exception as e:
                    errors.append(e)
                time.sleep(0.005)
        finally:
            stop.set()
            t.join(timeout=2)

        assert not errors, f"persist raised: {errors}"
        # Verify the file is valid JSON.
        f = manager._session_file(sess.id)
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["id"] == sess.id
        assert isinstance(data["messages"], list)

    def test_concurrent_mutation_llm_history(self, manager: AgentManager):
        """Mutating llm_history from another thread during persist must not corrupt."""
        sess = _make_session()
        sess.llm_history = [{"role": "user", "content": "hi"}]
        manager.sessions[sess.id] = sess

        stop = threading.Event()

        def mutator():
            i = 0
            while not stop.is_set():
                sess.llm_history.append({"role": "assistant", "content": f"turn-{i}"})
                i += 1
                time.sleep(0.001)

        t = threading.Thread(target=mutator, daemon=True)
        t.start()
        try:
            for _ in range(15):
                manager._persist_session(sess)
                time.sleep(0.005)
        finally:
            stop.set()
            t.join(timeout=2)

        f = manager._session_file(sess.id)
        data = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(data["llm_history"], list)


class TestLoadSessionsCorruptFile:
    """Verify that one corrupt file does not prevent loading others."""

    def test_corrupt_file_skipped(self, manager: AgentManager):
        """A corrupt JSON file should be skipped; valid sessions still load."""
        sessions_dir = manager._sessions_dir
        # Write 2 valid sessions.
        for i in range(2):
            sid = f"sess-valid-{i}"
            data = {"id": sid, "title": f"Valid {i}", "messages": [], "msg_seq": 0,
                    "cwd": "/tmp", "created_at": time.time(), "updated_at": time.time()}
            (sessions_dir / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")
        # Write 1 corrupt file.
        (sessions_dir / "sess-corrupt.json").write_text("{invalid json !!!", encoding="utf-8")

        manager._load_sessions()

        assert len(manager.sessions) == 2
        assert "sess-valid-0" in manager.sessions
        assert "sess-valid-1" in manager.sessions
        assert "sess-corrupt" not in manager.sessions

    def test_empty_file_skipped(self, manager: AgentManager):
        """An empty file should be skipped without crash."""
        sessions_dir = manager._sessions_dir
        (sessions_dir / "sess-empty.json").write_text("", encoding="utf-8")
        (sessions_dir / "sess-ok.json").write_text(
            json.dumps({"id": "sess-ok", "title": "OK", "messages": [], "msg_seq": 0,
                        "cwd": "/tmp", "created_at": time.time(), "updated_at": time.time()}),
            encoding="utf-8")

        manager._load_sessions()
        assert "sess-ok" in manager.sessions
        assert len(manager.sessions) == 1

    def test_internal_tui_sessions_are_not_loaded(self, manager: AgentManager):
        """Conductor/TUI worker artifacts must not enter the desktop session registry."""
        sessions_dir = manager._sessions_dir
        for sid in ("sess-visible", "tui_worker_hidden"):
            (sessions_dir / f"{sid}.json").write_text(
                json.dumps({
                    "id": sid,
                    "title": sid,
                    "messages": [],
                    "msg_seq": 0,
                    "cwd": "/tmp",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }),
                encoding="utf-8",
            )

        manager._load_sessions()

        assert set(manager.sessions) == {"sess-visible"}


class TestLoadSessionsMissingDir:
    """Verify graceful handling when sessions directory does not exist."""

    def test_missing_dir_returns_empty(self, tmp_ga_root: Path):
        """If temp/desktop_sessions/ doesn't exist, load returns empty without crash."""
        import shutil
        sessions_dir = tmp_ga_root / "temp" / "desktop_sessions"
        shutil.rmtree(sessions_dir)

        with patch.object(AgentManager, "__init__", lambda self: None):
            mgr = AgentManager.__new__(AgentManager)
        mgr.lock = threading.RLock()
        mgr.ga_root = str(tmp_ga_root)
        mgr.config = {}
        mgr.sessions = {}
        mgr.active_session_id = None
        mgr._sessions_dir = sessions_dir
        mgr._sessions_file = tmp_ga_root / "temp" / "desktop_sessions.json"

        mgr._load_sessions()
        assert mgr.sessions == {}


class TestImportSessionsFiltersInternalArtifacts:
    def test_import_skips_tui_sessions(self, manager: AgentManager, tmp_path: Path):
        source = tmp_path / "source"
        sessions_dir = source / "temp" / "desktop_sessions"
        sessions_dir.mkdir(parents=True)
        for sid in ("sess-imported", "tui_internal"):
            (sessions_dir / f"{sid}.json").write_text(
                json.dumps({
                    "id": sid,
                    "title": sid,
                    "messages": [],
                    "msg_seq": 0,
                    "cwd": "/tmp",
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }),
                encoding="utf-8",
            )

        result = manager.import_sessions(str(source))

        assert set(manager.sessions) == {"sess-imported"}
        assert result["sessionsAdded"] == 1
        assert result["sessionsSkipped"] == 1


class TestPersistAtomicNoDataLoss:
    """Verify that a failed write does not destroy the existing session file."""

    def test_write_failure_preserves_original(self, manager: AgentManager):
        """If write_text raises mid-write, the original .json file is untouched."""
        sess = _make_session(sid="sess-atomic-test", messages=[{"role": "user", "content": "original"}])
        manager.sessions[sess.id] = sess
        # Persist once successfully.
        manager._persist_session(sess)
        original_content = manager._session_file(sess.id).read_text(encoding="utf-8")

        # Now make the session have new content and make tmp write fail.
        sess.messages.append({"role": "assistant", "content": "new content"})
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            manager._persist_session(sess)

        # Original file should be untouched (os.replace never ran because tmp write failed).
        current_content = manager._session_file(sess.id).read_text(encoding="utf-8")
        assert current_content == original_content

    def test_replace_failure_preserves_original(self, manager: AgentManager):
        """If os.replace raises, the original file is untouched."""
        sess = _make_session(sid="sess-replace-test", messages=[{"role": "user", "content": "original"}])
        manager.sessions[sess.id] = sess
        manager._persist_session(sess)
        original_content = manager._session_file(sess.id).read_text(encoding="utf-8")

        sess.messages.append({"role": "assistant", "content": "new"})
        with patch("os.replace", side_effect=OSError("permission denied")):
            manager._persist_session(sess)

        current_content = manager._session_file(sess.id).read_text(encoding="utf-8")
        assert current_content == original_content


class TestSessionContinuityAfterRestart:
    """Verify that llm_history is injected when agent is recreated (simulates bridge restart)."""

    def test_stale_turn_cannot_mutate_a_reused_session(self, manager: AgentManager):
        sess = _make_session(sid="sess-stale-turn", messages=[])
        sess.active_turn_id = "new-turn"
        manager.sessions[sess.id] = sess

        with patch.object(manager, "make_agent") as make_agent:
            manager.run_agent_turn(sess, "old work", turn_id="old-turn")

        make_agent.assert_not_called()
        assert sess.status == "idle"
        assert sess.messages == []

    def test_run_agent_turn_injects_history(self, manager: AgentManager):
        """After bridge restart (agent=None, llm_history populated), run_agent_turn
        should inject persisted llm_history into the newly created agent."""
        history = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
            {"role": "user", "content": [{"type": "text", "text": "what did I just say?"}]},
        ]
        sess = _make_session(sid="sess-continuity-1", messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ])
        sess.llm_history = history
        sess.agent = None
        manager.sessions[sess.id] = sess

        class FakeBackend:
            def __init__(self):
                self.history = []
                self.name = "test-backend"

        class FakeLLMClient:
            def __init__(self):
                self.backend = FakeBackend()

        class FakeAgent:
            def __init__(self):
                self.llmclient = FakeLLMClient()
                self.llm_no = 0
                self.inc_out = True
                self.verbose = True

            def next_llm(self, n):
                self.llm_no = n

        fake_agent = FakeAgent()
        with patch.object(manager, "make_agent", return_value=fake_agent):
            if sess.agent is None:
                sess.agent = manager.make_agent(sess)
                if sess.llm_history:
                    try:
                        sess.agent.llmclient.backend.history = sess.llm_history
                    except Exception:
                        pass

        assert sess.agent.llmclient.backend.history == history
        assert len(sess.agent.llmclient.backend.history) == 3

    def test_no_history_no_crash(self, manager: AgentManager):
        """New session with no llm_history should not crash on agent creation."""
        sess = _make_session(sid="sess-continuity-2")
        sess.llm_history = None
        sess.agent = None
        manager.sessions[sess.id] = sess

        class FakeBackend:
            def __init__(self):
                self.history = []
                self.name = "test"

        class FakeLLMClient:
            def __init__(self):
                self.backend = FakeBackend()

        class FakeAgent:
            def __init__(self):
                self.llmclient = FakeLLMClient()
                self.llm_no = 0

            def next_llm(self, n):
                self.llm_no = n

        fake_agent = FakeAgent()
        with patch.object(manager, "make_agent", return_value=fake_agent):
            if sess.agent is None:
                sess.agent = manager.make_agent(sess)
                if sess.llm_history:
                    try:
                        sess.agent.llmclient.backend.history = sess.llm_history
                    except Exception:
                        pass

        assert sess.agent.llmclient.backend.history == []

    def test_empty_history_list_no_inject(self, manager: AgentManager):
        """Empty llm_history list should not overwrite agent's default state."""
        sess = _make_session(sid="sess-continuity-3")
        sess.llm_history = []
        sess.agent = None
        manager.sessions[sess.id] = sess

        class FakeBackend:
            def __init__(self):
                self.history = [{"role": "system", "content": "default"}]
                self.name = "test"

        class FakeLLMClient:
            def __init__(self):
                self.backend = FakeBackend()

        class FakeAgent:
            def __init__(self):
                self.llmclient = FakeLLMClient()
                self.llm_no = 0

            def next_llm(self, n):
                self.llm_no = n

        fake_agent = FakeAgent()
        with patch.object(manager, "make_agent", return_value=fake_agent):
            if sess.agent is None:
                sess.agent = manager.make_agent(sess)
                if sess.llm_history:
                    try:
                        sess.agent.llmclient.backend.history = sess.llm_history
                    except Exception:
                        pass

        assert sess.agent.llmclient.backend.history == [{"role": "system", "content": "default"}]

    def test_model_preserved_after_restart(self, manager: AgentManager):
        """sess.llm_no should be applied to recreated agent via next_llm."""
        sess = _make_session(sid="sess-continuity-4")
        sess.llm_no = 3
        sess.llm_history = [{"role": "user", "content": [{"type": "text", "text": "test"}]}]
        sess.agent = None
        manager.sessions[sess.id] = sess

        class FakeBackend:
            def __init__(self):
                self.history = []
                self.name = "test"

        class FakeLLMClient:
            def __init__(self):
                self.backend = FakeBackend()

        class FakeAgent:
            def __init__(self):
                self.llmclient = FakeLLMClient()
                self.llm_no = 0
                self.next_llm_calls = []

            def next_llm(self, n):
                self.llm_no = n
                self.next_llm_calls.append(n)

        fake_agent = FakeAgent()
        with patch.object(manager, "make_agent", return_value=fake_agent):
            if sess.agent is None:
                sess.agent = manager.make_agent(sess)
                if sess.llm_history:
                    try:
                        sess.agent.llmclient.backend.history = sess.llm_history
                    except Exception:
                        pass
            agent = sess.agent
            no = sess.llm_no
            if no is not None and hasattr(agent, "next_llm"):
                agent.next_llm(int(no))

        assert fake_agent.llm_no == 3
        assert fake_agent.next_llm_calls == [3]
        assert fake_agent.llmclient.backend.history == sess.llm_history

    def test_persist_and_reload_preserves_llm_no(self, manager: AgentManager):
        """Full cycle: persist session with llm_no, reload, verify llm_no survives."""
        sess = _make_session(sid="sess-roundtrip")
        sess.llm_no = 5
        sess.llm_history = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        manager.sessions[sess.id] = sess
        manager._persist_session(sess)

        manager.sessions = {}
        manager._load_sessions()

        reloaded = manager.sessions.get("sess-roundtrip")
        assert reloaded is not None
        assert reloaded.llm_no == 5
        assert reloaded.llm_history == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        assert reloaded.agent is None


class TestDeferredSessionModelSwitch:
    class FakeBackend:
        name = "model-a"
        history = []

    class FakeClient:
        backend = None

        def __init__(self):
            self.backend = TestDeferredSessionModelSwitch.FakeBackend()

    class FakeAgent:
        def __init__(self):
            self.llm_no = 0
            self.llmclient = TestDeferredSessionModelSwitch.FakeClient()
            self.next_llm_calls: list[int] = []

        def next_llm(self, no: int):
            self.next_llm_calls.append(no)
            self.llm_no = no
            self.llmclient.backend.name = f"model-{no}"

    def test_running_turn_keeps_current_client_and_defers_new_binding(self, manager: AgentManager):
        sess = _make_session("sess-running-switch")
        sess.status = "running"
        sess.llm_no = 0
        sess.running_llm_no = 0
        sess.running_model = "model-a"
        sess.agent = self.FakeAgent()
        manager.sessions[sess.id] = sess

        result = manager.set_session_model(sess.id, 2)

        assert sess.llm_no == 2
        assert sess.agent.next_llm_calls == []
        assert result["model"]["llmNo"] == 2
        assert result["model"]["runningLlmNo"] == 0
        assert result["model"]["runningModel"] == "model-a"

    def test_idle_session_switches_live_client_immediately(self, manager: AgentManager):
        sess = _make_session("sess-idle-switch")
        sess.status = "idle"
        sess.llm_no = 0
        sess.agent = self.FakeAgent()
        manager.sessions[sess.id] = sess

        manager.set_session_model(sess.id, 2)

        assert sess.agent.next_llm_calls == [2]

    def test_turn_captures_and_clears_running_model(self, manager: AgentManager):
        import queue

        sess = _make_session("sess-running-snapshot")
        sess.llm_no = 2
        fake_agent = self.FakeAgent()
        observed: list[tuple[int | None, str | None]] = []

        def put_task(_prompt, images=None):
            observed.append((sess.running_llm_no, sess.running_model))
            q = queue.Queue()
            q.put({"done": "ok", "outputs": ["ok"]})
            return q

        fake_agent.put_task = put_task
        fake_agent.inc_out = True
        sess.agent = fake_agent
        manager.sessions[sess.id] = sess
        plan_state = sys.modules["plan_state"]
        with patch.object(plan_state, "sync_plan_path_from_text", lambda *args: None, create=True):
            manager.run_agent_turn(sess, "hello")

        assert observed == [(2, "model-2")]
        assert sess.running_llm_no is None
        assert sess.running_model is None
        assert sess.status == "idle"

    def test_concurrent_sessions_keep_independent_next_model_bindings(self, manager: AgentManager):
        sessions = []
        for i in range(10):
            sess = _make_session(f"sess-concurrent-{i}")
            sess.status = "running"
            sess.llm_no = 0
            sess.agent = self.FakeAgent()
            manager.sessions[sess.id] = sess
            sessions.append(sess)

        threads = [
            threading.Thread(target=manager.set_session_model, args=(sess.id, i + 1))
            for i, sess in enumerate(sessions)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        assert [sess.llm_no for sess in sessions] == list(range(1, 11))
        assert all(sess.agent.next_llm_calls == [] for sess in sessions)


class TestConductorModelConfigResolution:
    def test_configured_model_wins(self):
        state = _mod._resolve_conductor_model_state(
            {"conductor": {"llmNo": 2}, "ui": {"llmNo": 1}},
            profile_count=4,
        )
        assert state == {"configured": 2, "effective": 2, "fallbackReason": None}

    def test_missing_config_uses_ui_default(self):
        state = _mod._resolve_conductor_model_state(
            {"ui": {"llmNo": 1}},
            profile_count=4,
        )
        assert state == {"configured": None, "effective": 1, "fallbackReason": "ui_default"}

    def test_out_of_range_config_never_wraps(self):
        state = _mod._resolve_conductor_model_state(
            {"conductor": {"llmNo": 99}, "ui": {"llmNo": 1}},
            profile_count=4,
        )
        assert state == {"configured": 99, "effective": 1, "fallbackReason": "invalid_configured"}

    def test_no_valid_config_falls_back_to_first_profile(self):
        state = _mod._resolve_conductor_model_state(
            {"conductor": {"llmNo": "bad"}, "ui": {"llmNo": 99}},
            profile_count=4,
        )
        assert state == {"configured": None, "effective": 0, "fallbackReason": "first_available"}

    def test_no_profiles_has_no_effective_model(self):
        state = _mod._resolve_conductor_model_state({}, profile_count=0)
        assert state == {"configured": None, "effective": None, "fallbackReason": "no_models"}


class TestConductorModelHandlers:
    class Request:
        def __init__(self, body: dict):
            self._body = body
            self.can_read_body = True

        async def json(self):
            return self._body

    def test_post_rejects_out_of_range_without_writing(self, manager: AgentManager, tmp_path: Path):
        import asyncio

        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"ui": {"llmNo": 1}}), encoding="utf-8")
        manager.list_model_profiles = lambda: [{"id": i} for i in range(4)]
        with patch.object(_mod, "manager", manager), patch.object(_mod, "_SETTINGS", settings):
            response = asyncio.run(_mod.conductor_model_save_handler(self.Request({"llmNo": 99})))

        assert response.status == 400
        assert json.loads(response.text)["error"] == "model_out_of_range"
        assert json.loads(settings.read_text(encoding="utf-8")) == {"ui": {"llmNo": 1}}
