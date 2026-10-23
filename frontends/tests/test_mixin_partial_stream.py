from __future__ import annotations

import importlib.util
import threading
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("llmcore_mixin_under_test", ROOT / "llmcore.py")
llmcore = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(llmcore)
MixinSession = llmcore.MixinSession


class FakeSession:
    def __init__(self, name, chunks):
        self.name = name
        self.chunks = list(chunks)
        self.calls = 0
        self.history = []
        self.system = ""
        self.tools = None
        self.lock = threading.Lock()
        self.max_retries = 0
        self.closed = 0

    def make_messages(self, messages):
        return messages

    def raw_ask(self, messages):
        self.calls += 1
        try:
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed += 1
        return [{"type": "text", "text": "".join(c for c in self.chunks if not c.startswith("!!!Error:"))}]


def _mixin(*sessions, retries=1):
    mixin = MixinSession.__new__(MixinSession)
    mixin._sessions = list(sessions)
    mixin._retries = retries
    mixin._base_delay = 0
    mixin._spring_sec = 300
    mixin._cur_idx = 0
    mixin._switched_at = 0
    mixin._native = False
    mixin.name = "|".join(s.name for s in sessions)
    mixin.history = []
    mixin.system = ""
    mixin.tools = None
    mixin.lock = threading.Lock()
    return mixin


def _collect(generator):
    chunks = []
    try:
        while True: chunks.append(next(generator))
    except StopIteration as exc:
        return chunks, exc.value


def test_failure_before_output_can_fail_over_transparently():
    primary = FakeSession("A", ["!!!Error: overloaded"])
    backup = FakeSession("B", ["B-complete"])
    chunks, _ = _collect(_mixin(primary, backup).raw_ask([{"role": "user", "content": "x"}]))
    assert chunks == ["B-complete"]
    assert primary.calls == backup.calls == 1


def test_failure_after_output_does_not_concatenate_attempts():
    primary = FakeSession("A", ["A-part", "!!!Error: upstream reset"])
    backup = FakeSession("B", ["B-complete"])
    mixin = _mixin(primary, backup)
    chunks, blocks = _collect(mixin.raw_ask([{"role": "user", "content": "x"}]))
    assert chunks == ["A-part", "!!!Error: upstream reset"]
    assert blocks == [{"type": "text", "text": "A-part"}]
    assert backup.calls == 0
    assert mixin.current_name == "B"
    assert primary.closed == 1


def test_partial_failure_keeps_remaining_chunks_from_the_same_attempt():
    primary = FakeSession("A", ["A-part", "!!!Error: upstream reset", "A-tail"])
    backup = FakeSession("B", ["B-complete"])
    chunks, _ = _collect(_mixin(primary, backup).raw_ask([{"role": "user", "content": "x"}]))
    assert chunks == ["A-part", "!!!Error: upstream reset", "A-tail"]
    assert backup.calls == 0


def test_backup_is_used_on_the_next_request_after_partial_failure():
    primary = FakeSession("A", ["A-part", "!!!Error: upstream reset"])
    backup = FakeSession("B", ["B-complete"])
    mixin = _mixin(primary, backup)
    _collect(mixin.raw_ask([{"role": "user", "content": "first"}]))
    chunks, _ = _collect(mixin.raw_ask([{"role": "user", "content": "second"}]))
    assert chunks == ["B-complete"]
    assert backup.calls == 1
