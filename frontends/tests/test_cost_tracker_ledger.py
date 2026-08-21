"""Regression tests for the per-call token ledger."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "desktop_cost_tracker_under_test", ROOT / "frontends" / "cost_tracker.py"
)
assert _SPEC and _SPEC.loader
cost_tracker = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cost_tracker
_SPEC.loader.exec_module(cost_tracker)


def _close_ledger() -> None:
    fd = cost_tracker._ledger_fd
    if fd is not None:
        fd.close()
    cost_tracker._ledger_fd = None
    cost_tracker._ledger_path = None


def setup_function() -> None:
    _close_ledger()


def teardown_function() -> None:
    _close_ledger()


def test_append_persists_and_aggregates_per_session(tmp_path):
    cost_tracker.init_ledger(str(tmp_path))

    cost_tracker._append_ledger("GA-sess-1", 10, 0, 2, 3)
    cost_tracker._append_ledger("GA-sess-1", 0, 7, 0, 0)
    cost_tracker._append_ledger("GA-sess-2", 4, 5, 0, 1)

    entries = cost_tracker.read_ledger()
    assert len(entries) == 3
    aggregate = cost_tracker.aggregate_ledger()
    by_id = {entry["sessionId"]: entry for entry in aggregate["history"]}
    assert by_id["sess-1"]["input"] == 10
    assert by_id["sess-1"]["output"] == 7
    assert by_id["sess-1"]["cacheCreate"] == 2
    assert by_id["sess-1"]["cacheRead"] == 3
    assert aggregate["snap"]["GA-sess-2"] == {
        "input": 4,
        "output": 5,
        "cacheCreate": 0,
        "cacheRead": 1,
    }


def test_concurrent_appends_are_serialized(tmp_path, monkeypatch):
    cost_tracker.init_ledger(str(tmp_path))
    real_fd = cost_tracker._ledger_fd

    class DetectConcurrentWrites:
        def __init__(self):
            self.active = 0
            self.overlapped = False

        def write(self, value):
            self.active += 1
            if self.active > 1:
                self.overlapped = True
            time.sleep(0.01)
            result = real_fd.write(value)
            self.active -= 1
            return result

        def flush(self):
            real_fd.flush()

        def close(self):
            real_fd.close()

    detector = DetectConcurrentWrites()
    monkeypatch.setattr(cost_tracker, "_ledger_fd", detector)
    threads = [
        threading.Thread(target=cost_tracker._append_ledger, args=(f"GA-{i}", 1, 0, 0, 0))
        for i in range(12)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert detector.overlapped is False
    assert len(cost_tracker.read_ledger()) == 12


def test_threshold_compaction_runs_during_process_lifetime(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_COMPACT_THRESHOLD", 1)
    cost_tracker.init_ledger(str(tmp_path))

    cost_tracker._append_ledger("GA-sess-1", 10, 7, 2, 3)

    entries = cost_tracker.read_ledger()
    assert len(entries) == 1
    assert entries[0]["_compacted"] is True


def test_compaction_preserves_last_activity_timestamp(tmp_path):
    cost_tracker.init_ledger(str(tmp_path))
    ledger_path = tmp_path / "temp" / "token_ledger.jsonl"
    first_ts = 1_700_000_000.0
    second_ts = 1_700_000_100.0
    cost_tracker._ledger_fd.close()
    cost_tracker._ledger_fd = None
    ledger_path.write_text(
        "\n".join(
            [
                json.dumps({"t": first_ts, "k": "GA-sess-1", "i": 10, "o": 0, "cc": 0, "cr": 0}),
                json.dumps({"t": second_ts, "k": "GA-sess-1", "i": 0, "o": 7, "cc": 0, "cr": 0}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cost_tracker._ledger_fd = ledger_path.open("a", encoding="utf-8")

    cost_tracker._compact_ledger()

    history = cost_tracker.aggregate_ledger()["history"]
    assert history[0]["ts"] == second_ts


def test_reinitializing_closes_the_previous_descriptor(tmp_path):
    cost_tracker.init_ledger(str(tmp_path / "one"))
    previous_fd = cost_tracker._ledger_fd

    cost_tracker.init_ledger(str(tmp_path / "two"))

    assert previous_fd.closed is True


def test_init_migrates_legacy_snapshot_when_ledger_is_empty(tmp_path):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    (temp_dir / "desktop_token_history.json").write_text(
        json.dumps(
            {
                "history": [
                    {
                        "sessionId": "sess-legacy",
                        "title": "Legacy session",
                        "input": 3,
                        "output": 4,
                        "cacheCreate": 5,
                        "cacheRead": 6,
                        "model": "legacy-model",
                        "ts": 1_700_000_000.0,
                    }
                ],
                "snap": {
                    "GA-sess-legacy": {
                        "input": 30,
                        "output": 40,
                        "cacheCreate": 50,
                        "cacheRead": 60,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    cost_tracker.init_ledger(str(tmp_path))

    aggregate = cost_tracker.aggregate_ledger()
    assert aggregate["snap"]["GA-sess-legacy"] == {
        "input": 30,
        "output": 40,
        "cacheCreate": 50,
        "cacheRead": 60,
    }
    assert aggregate["history"][0]["title"] == "Legacy session"
    assert aggregate["history"][0]["model"] == "legacy-model"
    assert aggregate["history"][0]["ts"] == 1_700_000_000.0


def test_init_does_not_migrate_legacy_snapshot_into_nonempty_ledger(tmp_path):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    (temp_dir / "token_ledger.jsonl").write_text(
        json.dumps({"t": 2.0, "k": "GA-current", "i": 1, "o": 0, "cc": 0, "cr": 0}) + "\n",
        encoding="utf-8",
    )
    (temp_dir / "desktop_token_history.json").write_text(
        json.dumps({"snap": {"GA-legacy": {"input": 99, "output": 0, "cacheCreate": 0, "cacheRead": 0}}}),
        encoding="utf-8",
    )

    cost_tracker.init_ledger(str(tmp_path))

    assert set(cost_tracker.aggregate_ledger()["snap"]) == {"GA-current"}


@pytest.mark.parametrize(
    ("api_mode", "usage", "expected"),
    [
        (
            "messages",
            {
                "input_tokens": 10,
                "output_tokens": 1,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 3,
            },
            {"input": 10, "output": 7, "cacheCreate": 2, "cacheRead": 3},
        ),
        (
            "chat_completions",
            {"prompt_tokens": 13, "prompt_tokens_details": {"cached_tokens": 3}},
            {"input": 10, "output": 7, "cacheCreate": 0, "cacheRead": 3},
        ),
        (
            "responses",
            {"input_tokens": 13, "input_tokens_details": {"cached_tokens": 3}},
            {"input": 10, "output": 7, "cacheCreate": 0, "cacheRead": 3},
        ),
    ],
)
def test_install_hooks_append_each_api_mode(tmp_path, monkeypatch, api_mode, usage, expected):
    original_calls = []
    fake_llmcore = types.ModuleType("llmcore")
    fake_llmcore._record_usage = lambda value, mode: original_calls.append((value, mode))
    monkeypatch.setitem(sys.modules, "llmcore", fake_llmcore)
    monkeypatch.setattr(cost_tracker, "_INSTALLED", False)
    cost_tracker._trackers.clear()
    cost_tracker.init_ledger(str(tmp_path))

    cost_tracker.install()
    fake_llmcore._record_usage(usage, api_mode)
    fake_llmcore.print("[Output] tokens=7")

    snapshot = next(iter(cost_tracker.aggregate_ledger()["snap"].values()))
    assert snapshot == expected
    assert original_calls == [(usage, api_mode)]


def test_concurrent_appends_remain_exact_across_compactions(tmp_path, monkeypatch):
    monkeypatch.setattr(cost_tracker, "_COMPACT_THRESHOLD", 1_000)
    cost_tracker.init_ledger(str(tmp_path))
    per_thread = 20

    def append_session(key: str) -> None:
        for _ in range(per_thread):
            cost_tracker._append_ledger(key, 1, 2, 3, 4)

    threads = [
        threading.Thread(target=append_session, args=(key,))
        for key in (f"GA-sess-{i}" for i in range(8))
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    aggregate = cost_tracker.aggregate_ledger()
    assert len(aggregate["snap"]) == 8
    for snapshot in aggregate["snap"].values():
        assert snapshot == {
            "input": per_thread,
            "output": per_thread * 2,
            "cacheCreate": per_thread * 3,
            "cacheRead": per_thread * 4,
        }


def test_corrupt_and_truncated_lines_are_skipped(tmp_path):
    cost_tracker.init_ledger(str(tmp_path))
    cost_tracker._append_ledger("GA-valid", 3, 4, 5, 6)
    ledger_path = tmp_path / "temp" / "token_ledger.jsonl"
    cost_tracker._ledger_fd.write("not-json\n{\"truncated\":\n")
    cost_tracker._ledger_fd.flush()

    assert cost_tracker.aggregate_ledger()["snap"] == {
        "GA-valid": {"input": 3, "output": 4, "cacheCreate": 5, "cacheRead": 6}
    }


def test_compaction_uses_atomic_replace_and_keeps_descriptor_writable(tmp_path, monkeypatch):
    cost_tracker.init_ledger(str(tmp_path))
    cost_tracker._append_ledger("GA-valid", 3, 4, 0, 0)
    real_replace = cost_tracker.os.replace
    replacements = []

    def observe_replace(source, target):
        replacements.append((Path(source), Path(target)))
        assert Path(source).name == "token_ledger.jsonl.tmp"
        assert Path(target).name == "token_ledger.jsonl"
        real_replace(source, target)

    monkeypatch.setattr(cost_tracker.os, "replace", observe_replace)
    cost_tracker._compact_ledger()
    cost_tracker._append_ledger("GA-valid", 0, 2, 0, 0)

    assert len(replacements) == 1
    assert cost_tracker.aggregate_ledger()["snap"]["GA-valid"]["output"] == 6


def test_real_10mb_threshold_compacts_on_init(tmp_path):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    ledger_path = temp_dir / "token_ledger.jsonl"
    valid = json.dumps({"t": 1, "k": "GA-valid", "i": 3, "o": 4, "cc": 0, "cr": 0}) + "\n"
    with ledger_path.open("wb") as ledger:
        ledger.write(valid.encode("utf-8"))
        ledger.truncate(cost_tracker._COMPACT_THRESHOLD)

    cost_tracker.init_ledger(str(tmp_path))

    assert ledger_path.stat().st_size < 1_000
    assert cost_tracker.aggregate_ledger()["snap"]["GA-valid"] == {
        "input": 3,
        "output": 4,
        "cacheCreate": 0,
        "cacheRead": 0,
    }


def test_repeated_init_migrates_legacy_snapshot_only_once(tmp_path):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    (temp_dir / "desktop_token_history.json").write_text(
        json.dumps({
            "snap": {
                "GA-legacy": {"input": 7, "output": 8, "cacheCreate": 9, "cacheRead": 10}
            }
        }),
        encoding="utf-8",
    )

    cost_tracker.init_ledger(str(tmp_path))
    cost_tracker.init_ledger(str(tmp_path))

    assert cost_tracker.aggregate_ledger()["snap"]["GA-legacy"] == {
        "input": 7,
        "output": 8,
        "cacheCreate": 9,
        "cacheRead": 10,
    }
    assert len(cost_tracker.read_ledger()) == 1
