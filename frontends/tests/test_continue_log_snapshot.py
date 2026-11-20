import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SPEC = spec_from_file_location("continue_cmd_under_test", ROOT / "frontends" / "continue_cmd.py")
assert SPEC and SPEC.loader
continue_cmd = module_from_spec(SPEC)
SPEC.loader.exec_module(continue_cmd)

LOG_CONTENT = (
    "=== Prompt === 2026-01-01 00:00:00\nhello\n\n"
    "=== Response === 2026-01-01 00:00:01 model=test\nworld\n\n"
)


def _agent(log_path):
    backend = SimpleNamespace(history=["backend turn"])
    client = SimpleNamespace(backend=backend, last_tools="cached tools")
    return SimpleNamespace(
        abort=lambda: None, log_path=log_path, history=["agent turn"],
        llmclients=[client], llmclient=client, handler=object(),
    )


def test_reset_snapshots_the_agents_active_log(tmp_path, monkeypatch):
    active_log = tmp_path / f"model_responses_{os.getpid() + 1}.txt"
    active_log.write_text(LOG_CONTENT, encoding="utf-8")
    agent = _agent(str(active_log))
    monkeypatch.setattr(continue_cmd, "_LOG_DIR", str(tmp_path))

    continue_cmd.reset_conversation(agent)

    snapshots = list(tmp_path.glob("model_responses_snapshot_*.txt"))
    assert active_log.read_text(encoding="utf-8") == ""
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == LOG_CONTENT
    assert agent.history == []
    assert agent.llmclient.backend.history == []
    assert agent.llmclient.last_tools == ""
    assert agent.handler is None


def test_reset_does_not_touch_pid_log_when_logging_is_disabled(tmp_path, monkeypatch):
    pid_log = tmp_path / f"model_responses_{os.getpid()}.txt"
    pid_log.write_text(LOG_CONTENT, encoding="utf-8")
    monkeypatch.setattr(continue_cmd, "_LOG_DIR", str(tmp_path))

    continue_cmd.reset_conversation(_agent(False))

    assert pid_log.read_text(encoding="utf-8") == LOG_CONTENT
    assert not list(tmp_path.glob("model_responses_snapshot_*.txt"))


def test_snapshot_retains_the_legacy_pid_fallback(tmp_path, monkeypatch):
    pid_log = tmp_path / "model_responses_123456.txt"
    pid_log.write_text(LOG_CONTENT, encoding="utf-8")
    monkeypatch.setattr(continue_cmd, "_LOG_DIR", str(tmp_path))

    snapshot = continue_cmd._snapshot_current_log(123456)

    assert pid_log.read_text(encoding="utf-8") == ""
    assert Path(snapshot).read_text(encoding="utf-8") == LOG_CONTENT
