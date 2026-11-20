from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("ga_code_run_under_test", ROOT / "ga.py")
ga = importlib.util.module_from_spec(spec)
assert spec.loader is not None
previous_agent_loop = sys.modules.pop("agent_loop", None)
try:
    spec.loader.exec_module(ga)
finally:
    if previous_agent_loop is not None: sys.modules["agent_loop"] = previous_agent_loop


def _run_with_child(tmp_path, *, timeout, stop_signal, ignore_term=False):
    started = tmp_path / "child-started"
    canary = tmp_path / "orphan-canary"
    child = (
        "import pathlib,signal,time; "
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "") +
        f"pathlib.Path({str(started)!r}).write_text('started'); "
        "time.sleep(2); "
        f"pathlib.Path({str(canary)!r}).write_text('orphaned')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "time.sleep(30)"
    )
    result = None
    runner = ga.code_run(parent, "python", timeout, str(tmp_path), str(tmp_path), stop_signal)
    try:
        while True: next(runner)
    except StopIteration as exc: result = exc.value
    return result, started, canary


def test_manual_stop_terminates_descendants(tmp_path):
    stop_signal = []
    outcome = {}

    def run(): outcome["result"], outcome["started"], outcome["canary"] = _run_with_child(
        tmp_path, timeout=10, stop_signal=stop_signal)

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.time() + 5
    while not (tmp_path / "child-started").exists() and time.time() < deadline: time.sleep(0.02)
    assert (tmp_path / "child-started").exists()
    stop_signal.append(1)
    thread.join(timeout=5)
    assert not thread.is_alive()
    time.sleep(2.2)
    assert not outcome["canary"].exists()
    assert "[Stopped]" in outcome["result"]["stdout"]


def test_timeout_terminates_descendants(tmp_path):
    result, started, canary = _run_with_child(
        tmp_path, timeout=0.1, stop_signal=[], ignore_term=True)
    assert started.exists()
    time.sleep(2.2)
    assert not canary.exists()
    assert "[Timeout Error]" in result["stdout"]
