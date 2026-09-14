"""Regression test for the messages-API usage accounting fix in llmcore.

Before fix: ``_record_usage(usage, api_mode='messages')`` hard-coded
``out = 0``. As a result, ``STATS['out']`` was never updated for Claude
(Anthropic Messages API) usage, the user-facing cost/running-stats
display never reflected real output tokens, and the
``[Output] tokens=...`` log line never printed for Claude sessions.

After fix: ``out = _i(usage.get('output_tokens'))`` so STATS tracks
output tokens for all three API modes (chat_completions, responses,
messages) and the log line is consistent with the other branches.
"""

import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LLMCORE_PATH = REPO_ROOT / "llmcore.py"


def _load_llmcore_module():
    """Load llmcore.py in isolation. Heavy deps (agentmain, requests,
    websockets, etc.) are stubbed just enough to import the module and
    access ``_record_usage`` + ``STATS`` without spinning up a network or
    starting the agent runtime.
    """
    stubs = {
        "requests": types.ModuleType("requests"),
        "websockets": types.ModuleType("websockets"),
        "agentmain": types.ModuleType("agentmain"),
    }
    stubs["requests"].post = lambda *a, **kw: None
    stubs["requests"].Session = type("Session", (), {})
    for name, mod in stubs.items():
        sys.modules.setdefault(name, mod)

    spec = importlib.util.spec_from_file_location("llmcore_under_test", LLMCORE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reset_stats(mod):
    mod.STATS.clear()
    mod.STATS.update({"session": ""})


def test_messages_mode_records_output_tokens():
    """The Claude messages API emits output_tokens; the fix must pick it up."""
    mod = _load_llmcore_module()
    _reset_stats(mod)

    usage = {
        "input_tokens": 100,
        "output_tokens": 47,
        "cache_creation_input_tokens": 5,
        "cache_read_input_tokens": 30,
    }

    captured = []
    real_print = mod.print if hasattr(mod, "print") else __builtins__["print"]
    # llmcore.py uses bare ``print(...)``. Capture via stdout redirect.
    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod._record_usage(usage, "messages")
    finally:
        sys.stdout = old_stdout
    log = buf.getvalue()

    assert mod.STATS.get("out") == 47, (
        f"messages API: STATS['out'] not updated from output_tokens; "
        f"got {mod.STATS.get('out')!r}"
    )
    assert "Output" in log and "tokens=47" in log, (
        f"messages API: [Output] log line missing output_tokens=47; "
        f"log was: {log!r}"
    )
    assert mod.STATS.get("inp") == 100 + 5 + 30, (
        f"messages API: input accounting broken; inp={mod.STATS.get('inp')!r}"
    )
    assert mod.STATS.get("cached") == 30, (
        f"messages API: cached (= cache_read_input_tokens) accounting "
        f"broken; cached={mod.STATS.get('cached')!r}"
    )


def test_messages_mode_handles_missing_output_tokens():
    """Older / partial usage payloads may omit output_tokens; the fix must
    degrade gracefully to 0 instead of KeyError-ing."""
    mod = _load_llmcore_module()
    _reset_stats(mod)

    usage = {"input_tokens": 100}  # no output_tokens, no cache fields

    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod._record_usage(usage, "messages")
    finally:
        sys.stdout = old_stdout

    assert mod.STATS.get("out") == 0
    assert mod.STATS.get("inp") == 100
    assert mod.STATS.get("cached") == 0
    # No Output log line because out is 0.
    assert "Output" not in buf.getvalue(), (
        f"messages API: should not log [Output] when output_tokens is "
        f"missing/zero; log was: {buf.getvalue()!r}"
    )


def test_messages_mode_handles_null_output_tokens():
    """Claude may emit ``output_tokens: null`` rather than omitting the
    key. ``_i`` already coerces ``None`` -> ``0`` via the same path the
    other branches use, so STATS must end up with ``out=0``."""
    mod = _load_llmcore_module()
    _reset_stats(mod)

    usage = {"input_tokens": 100, "output_tokens": None}

    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod._record_usage(usage, "messages")
    finally:
        sys.stdout = old_stdout

    assert mod.STATS.get("out") == 0, (
        f"messages API: null output_tokens must coerce to 0; "
        f"got {mod.STATS.get('out')!r}"
    )


def test_chat_completions_mode_still_works():
    """Sanity check: the other branches must not regress when we touch
    the messages branch."""
    mod = _load_llmcore_module()
    _reset_stats(mod)

    usage = {
        "prompt_tokens": 200,
        "completion_tokens": 80,
        "prompt_tokens_details": {"cached_tokens": 25},
    }

    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod._record_usage(usage, "chat_completions")
    finally:
        sys.stdout = old_stdout

    assert mod.STATS.get("inp") == 200
    assert mod.STATS.get("out") == 80
    assert mod.STATS.get("cached") == 25
    assert "Output" in buf.getvalue() and "tokens=80" in buf.getvalue()


def test_responses_mode_still_works():
    """Sanity check for the OpenAI Responses branch."""
    mod = _load_llmcore_module()
    _reset_stats(mod)

    usage = {
        "input_tokens": 300,
        "output_tokens": 120,
        "input_tokens_details": {"cached_tokens": 50},
    }

    import io
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        mod._record_usage(usage, "responses")
    finally:
        sys.stdout = old_stdout

    assert mod.STATS.get("inp") == 300
    assert mod.STATS.get("out") == 120
    assert mod.STATS.get("cached") == 50


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
            except Exception as e:
                failures += 1
                print(f"ERROR {name}: {type(e).__name__}: {e}")
    if failures:
        sys.exit(1)
    print("ALL PASS")
