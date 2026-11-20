from __future__ import annotations

import multiprocessing
import builtins
import importlib.util
import os
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _load_ga():
    spec = importlib.util.spec_from_file_location("ga_file_patch_under_test", ROOT / "ga.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    previous_agent_loop = sys.modules.pop("agent_loop", None)
    try:
        spec.loader.exec_module(module)
    finally:
        if previous_agent_loop is not None: sys.modules["agent_loop"] = previous_agent_loop
    return module


def _patch(path: str, old: str, new: str, ready):
    ga = _load_ga()
    ready.wait()
    print(ga.file_patch(path, old, new), flush=True)


def test_concurrent_file_patches_are_serialized(tmp_path):
    path = tmp_path / "state.txt"
    path.write_text("A=0\nB=0\n", encoding="utf-8")
    ready = multiprocessing.get_context("spawn").Event()
    workers = [
        multiprocessing.get_context("spawn").Process(target=_patch, args=(str(path), "A=0", "A=1", ready)),
        multiprocessing.get_context("spawn").Process(target=_patch, args=(str(path), "B=0", "B=1", ready)),
    ]
    for worker in workers: worker.start()
    ready.set()
    for worker in workers:
        worker.join(timeout=10)
        assert worker.exitcode == 0
    assert path.read_text(encoding="utf-8") == "A=1\nB=1\n"


def test_same_process_patches_do_not_read_a_stale_snapshot(tmp_path, monkeypatch):
    ga = _load_ga()

    path = tmp_path / "state.txt"
    path.write_text("A=0\nB=0\n", encoding="utf-8")
    both_read = threading.Event()
    read_count = 0
    read_count_lock = threading.Lock()
    real_open = builtins.open

    class SynchronizedReader:
        def __init__(self, file): self.file = file
        def __enter__(self): self.file.__enter__(); return self
        def __exit__(self, *args): return self.file.__exit__(*args)
        def read(self):
            nonlocal read_count
            content = self.file.read()
            with read_count_lock:
                read_count += 1
                if read_count == 2: both_read.set()
            both_read.wait(timeout=0.2)
            return content

    def synchronized_open(file, mode="r", *args, **kwargs):
        handle = real_open(file, mode, *args, **kwargs)
        return SynchronizedReader(handle) if os.fspath(file) == str(path) and mode == "r" else handle

    monkeypatch.setattr(builtins, "open", synchronized_open)
    start = threading.Barrier(3)
    results = []

    def patch(old, new):
        start.wait()
        results.append(ga.file_patch(str(path), old, new))

    threads = [
        threading.Thread(target=patch, args=("A=0", "A=1")),
        threading.Thread(target=patch, args=("B=0", "B=1")),
    ]
    for thread in threads: thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert all(result["status"] == "success" for result in results)
    assert path.read_text(encoding="utf-8") == "A=1\nB=1\n"
