"""Runtime model-routing tests for the isolated Conductor process."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent.parent
CONDUCTOR_PATH = ROOT / "frontends" / "conductor.py"


class StubGenericAgent:
    pass


agentmain_stub = types.ModuleType("agentmain")
agentmain_stub.GenericAgent = StubGenericAgent
previous_agentmain = sys.modules.get("agentmain")
sys.modules["agentmain"] = agentmain_stub

spec = importlib.util.spec_from_file_location("conductor_model_under_test", CONDUCTOR_PATH)
conductor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
_argv = sys.argv
try:
    sys.argv = [str(CONDUCTOR_PATH), "--no-browser"]
    spec.loader.exec_module(conductor)
finally:
    sys.argv = _argv
if previous_agentmain is None:
    del sys.modules["agentmain"]
else:
    sys.modules["agentmain"] = previous_agentmain


class Backend:
    def __init__(self, name: str):
        self.name = name
        self.model = name


class Client:
    def __init__(self, name: str | None):
        if name is not None:
            self.backend = Backend(name)


class FakeAgent:
    def __init__(self, names: list[str | None], failing: set[int] | None = None):
        self.llmclients = [Client(name) for name in names]
        self.llm_no = 0
        self.llmclient = self.llmclients[0]
        self.next_llm_calls: list[int] = []
        self.reloads = 0
        self.failing = failing or set()

    def load_llm_sessions(self):
        self.reloads += 1

    def next_llm(self, no: int):
        # Deliberately mirrors GenericAgent's modulo behavior. The Conductor
        # resolver must validate before calling this method.
        self.next_llm_calls.append(no)
        if no in self.failing:
            raise RuntimeError("broken client")
        self.llm_no = no % len(self.llmclients)
        self.llmclient = self.llmclients[self.llm_no]

    def get_llm_name(self, client=None, model=False):
        client = client or self.llmclient
        return client.backend.model if model else client.backend.name


def test_out_of_range_config_falls_back_without_modulo(monkeypatch):
    agent = FakeAgent(["zero", "one", "two", "three"])
    monkeypatch.setattr(
        conductor,
        "_settings_doc",
        lambda: {"conductor": {"llmNo": 99}, "ui": {"llmNo": 1}},
    )

    state = conductor._apply_desktop_model(agent)

    assert agent.next_llm_calls == [1]
    assert state["effective"] == 1
    assert state["fallbackReason"] == "invalid_configured"


def test_unusable_configured_client_falls_back_to_ui_default(monkeypatch):
    agent = FakeAgent(["zero", "one", None, "three"])
    monkeypatch.setattr(
        conductor,
        "_settings_doc",
        lambda: {"conductor": {"llmNo": 2}, "ui": {"llmNo": 1}},
    )

    state = conductor._apply_desktop_model(agent)

    assert agent.next_llm_calls == [1]
    assert state["effective"] == 1
    assert state["fallbackReason"] == "configured_unavailable"


def test_configured_activation_failure_falls_back_to_ui_default(monkeypatch):
    agent = FakeAgent(["zero", "one", "two"], failing={2})
    monkeypatch.setattr(
        conductor,
        "_settings_doc",
        lambda: {"conductor": {"llmNo": 2}, "ui": {"llmNo": 1}},
    )

    state = conductor._apply_desktop_model(agent)

    assert agent.next_llm_calls == [2, 1]
    assert state["effective"] == 1
    assert state["fallbackReason"] == "configured_unavailable"


def test_missing_config_uses_first_usable_when_ui_is_invalid(monkeypatch):
    agent = FakeAgent([None, None, "two", "three"])
    monkeypatch.setattr(conductor, "_settings_doc", lambda: {"ui": {"llmNo": 99}})

    state = conductor._apply_desktop_model(agent)

    assert agent.next_llm_calls == [2]
    assert state["effective"] == 2
    assert state["fallbackReason"] == "first_available"


def test_explicit_numeric_worker_model_rejects_out_of_range():
    agent = FakeAgent(["zero", "one"])

    with pytest.raises(ValueError, match="out of range"):
        conductor._select_llm(agent, 99)

    assert agent.next_llm_calls == []


def test_runtime_model_snapshot_is_broadcast_with_running_state(monkeypatch):
    instance = conductor.Conductor()
    payloads: list[dict] = []
    monkeypatch.setattr(conductor, "schedule_broadcast", payloads.append)
    state = {
        "configured": 2,
        "effective": 1,
        "fallbackReason": "configured_unavailable",
        "current": "model-one",
    }

    instance._publish_model_state(state, running=True)

    assert instance.model_snapshot() == {**state, "running": True}
    assert payloads == [{"type": "model", "model": {**state, "running": True}}]


def test_parallel_worker_model_selection_keeps_agents_isolated():
    from concurrent.futures import ThreadPoolExecutor

    agents = [FakeAgent(["zero", "one", "two", "three"]) for _ in range(10)]
    requested = [i % 4 for i in range(10)]
    with ThreadPoolExecutor(max_workers=10) as executor:
        selected = list(executor.map(
            lambda pair: conductor._select_llm(pair[0], pair[1]),
            zip(agents, requested),
        ))

    assert selected == [True] * 10
    assert [agent.llm_no for agent in agents] == requested
    assert [agent.next_llm_calls for agent in agents] == [[no] for no in requested]
