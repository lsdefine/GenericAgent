"""Regression tests for `llmcore.estimate_context_tokens` (#750).

Background: `trim_messages_history` historically used the heuristic
``3 chars == 1 token`` inlined into the cap calculation
(``cap = sess.context_win * 3``). Issue #750 called for that heuristic to
be moved into a single named place, so a future model-aware estimator can
swap it without touching the trim path. This file pins the v1 behaviour
and exercises both extension points:
``sess.token_estimator`` (callable override) and
``sess.token_chars_per_token`` (float multiplier override).

The tests load `llmcore.py` in isolation (heavy deps stubbed) — same trick
used by `tests/test_llmcore_record_usage_messages.py`.
"""

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LLMCORE_PATH = REPO_ROOT / "llmcore.py"


def _load_llmcore_module():
    """Load `llmcore` without spinning up the agent runtime.

    `llmcore` is a top-level script that imports `agentmain`, `requests`,
    and `websockets` at module load time. We stub just enough to import the
    module and access the helpers we want to test, then return it.
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


llmcore = _load_llmcore_module()


def _history(*pairs):
    """Build a history list of `{role, content}` dicts from (role, text) pairs."""
    return [{"role": role, "content": text} for role, text in pairs]


def _sess(**attrs):
    """Build a throw-away session stub. Only the attributes our estimator
    reads are set; everything else is irrelevant."""
    return types.SimpleNamespace(**attrs)


class EstimateContextTokensDefaultHeuristicTests(unittest.TestCase):
    """Pin the v1 behaviour: `int(char_count / 3)` rounded down."""

    def _json_chars(self, *pairs):
        # The estimator sums `len(json.dumps(m, ensure_ascii=False)) for m in history`
        # i.e. it json-serialises each message *individually* and sums. Match that
        # here so we don't bake in the wrong assumption about list-vs-per-msg.
        return sum(len(json.dumps({"role": r, "content": c}, ensure_ascii=False)) for r, c in pairs)

    def test_empty_history_returns_zero(self):
        self.assertEqual(llmcore.estimate_context_tokens([]), 0)
        self.assertEqual(llmcore.estimate_context_tokens([], None), 0)

    def test_short_english_history(self):
        # {"role":"user","content":"hello"} -> 36 chars -> 36/3 = 12 tokens.
        hist = _history(("user", "hello"))
        self.assertEqual(llmcore.estimate_context_tokens(hist), self._json_chars(("user", "hello")) // 3)
        self.assertEqual(llmcore.estimate_context_tokens(hist), 12)

    def test_cjk_history_is_one_token_per_three_chars(self):
        # CJK glyphs are still 1 char each under ensure_ascii=False — that
        # is the v1 bug #750 calls out. Pin the behaviour so a future
        # tokenizer-aware fix doesn't silently regress English history.
        hist = _history(("user", "你好世界你好"))
        self.assertEqual(llmcore.estimate_context_tokens(hist), self._json_chars(("user", "你好世界你好")) // 3)
        self.assertEqual(llmcore.estimate_context_tokens(hist), 12)

    def test_uses_ensure_ascii_false_so_cjk_counts_in_chars(self):
        # `json.dumps(..., ensure_ascii=False)` keeps the original chars
        # rather than escaping them to \uXXXX (which would inflate CJK).
        # With escaped form "你好" would become "\u4f60\u597d" (12 chars);
        # with ensure_ascii=False the content stays at 2 chars. We pin the
        # unescaped form (the value used by the original `cost()` too).
        hist = _history(("user", "你好"))
        self.assertEqual(llmcore.estimate_context_tokens(hist), self._json_chars(("user", "你好")) // 3)
        # Sanity: escaped form would yield a different number.
        escaped_chars = len(json.dumps({"role": "user", "content": "你好"}, ensure_ascii=True))
        self.assertNotEqual(self._json_chars(("user", "你好")), escaped_chars)

    def test_history_with_multiple_messages(self):
        # The estimator sums per-message json.dumps chars, then divides.
        hist = _history(("user", "abc"), ("assistant", "defg"))
        self.assertEqual(
            llmcore.estimate_context_tokens(hist),
            self._json_chars(("user", "abc"), ("assistant", "defg")) // 3,
        )

    def test_non_json_serialisable_messages_are_handled_by_json_dumps(self):
        # `cost()` (and the estimator) use `json.dumps` directly. A
        # non-serialisable value will raise inside the estimator — that's
        # acceptable because the trim path catches and treats it as
        # over-cap (the original code also relied on this). Pin it.
        bad = [{"role": "user", "content": {"nested": object()}}]
        with self.assertRaises(TypeError):
            llmcore.estimate_context_tokens(bad)


class EstimateContextTokensCharsPerTokenOverrideTests(unittest.TestCase):
    """`sess.token_chars_per_token` is the float-multiplier override."""

    def test_string_is_coerced_to_float(self):
        sess = _sess(token_chars_per_token="1.5")
        # 36 chars / 1.5 = 24 tokens
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hello")), sess), 24)

    def test_invalid_value_falls_back_to_default(self):
        # Garbage values must not crash the trim path; the fallback is the
        # module default of 3.
        sess = _sess(token_chars_per_token="not-a-number")
        # 38 chars / 3 = 12 tokens
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hello")), sess), 12)

    def test_zero_divisor_is_replaced_by_default(self):
        # A misconfigured zero / negative must not produce a ZeroDivisionError
        # or a wildly negative estimate — it falls back to the default.
        sess = _sess(token_chars_per_token=0)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hello")), sess), 12)
        sess = _sess(token_chars_per_token=-2)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hello")), sess), 12)

    def test_none_value_falls_back_to_default(self):
        sess = _sess(token_chars_per_token=None)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hello")), sess), 12)


class EstimateContextTokensCallableOverrideTests(unittest.TestCase):
    """`sess.token_estimator` is the full-callable override."""

    def test_callable_takes_precedence_over_chars_per_token(self):
        sess = _sess(token_estimator=lambda h: 42, token_chars_per_token=1.5)
        # The callable wins even when chars_per_token would also be set.
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hi")), sess), 42)

    def test_callable_returning_zero_or_none_is_clamped(self):
        # `int(estimator(history) or 0)` then `max(0, ...)` — defensive
        # against a buggy estimator that returns None or 0 or a negative.
        sess = _sess(token_estimator=lambda h: 0)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hi")), sess), 0)
        sess = _sess(token_estimator=lambda h: None)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hi")), sess), 0)
        sess = _sess(token_estimator=lambda h: -7)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hi")), sess), 0)

    def test_callable_returning_non_int_is_truncated(self):
        # Floats must be coerced to int — the estimator contract says int.
        sess = _sess(token_estimator=lambda h: 1.9)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hi")), sess), 1)

    def test_buggy_callable_is_swallowed_and_falls_back(self):
        # The estimator must never crash the trim path — a buggy override
        # should fall back to the chars-per-token path.
        sess = _sess(token_estimator=lambda h: 1 / 0, token_chars_per_token="3")
        # 38 chars / 3 = 12 tokens (fallback to chars_per_token path)
        self.assertEqual(llmcore.estimate_context_tokens(_history(("user", "hello")), sess), 12)

    def test_callable_receives_full_history(self):
        captured = []
        sess = _sess(token_estimator=lambda h: captured.append(list(h)) or 99)
        hist = _history(("user", "hi"), ("assistant", "yo"))
        llmcore.estimate_context_tokens(hist, sess)
        # The estimator sees the whole list, not a slice.
        self.assertEqual(len(captured[0]), 2)
        self.assertEqual(captured[0][0]["role"], "user")


class TrimMessagesHistoryBehaviorPreservedTests(unittest.TestCase):
    """The trim *gate* must keep its char-based behaviour byte-identical
    with the previous implementation — only the debug log gains the new
    `tokens_est` field."""

    def _make_sess(self, context_win=100, trim_keep_prefix=0, trim_keep_rate=0.6):
        return _sess(
            context_win=context_win,
            trim_keep_prefix=trim_keep_prefix,
            trim_keep_rate=trim_keep_rate,
        )

    def test_small_history_does_not_trim_and_logs_both_stats(self):
        sess = self._make_sess(context_win=1000)
        hist = _history(("user", "hi"))
        llmcore.trim_messages_history(hist, sess)
        # gate says: under cap -> return without trimming
        self.assertEqual(len(hist), 1)
        # stats now expose both `ctx` (chars, for cost_tracker compat) and
        # `tokens_est` (the new field).
        self.assertIn("ctx", llmcore.STATS)
        self.assertIn("tokens_est", llmcore.STATS)
        # tokens_est is the same as ctx / 3 under the default heuristic.
        self.assertEqual(llmcore.STATS["tokens_est"], llmcore.STATS["ctx"] // 3)

    def test_large_history_triggers_hard_cut(self):
        # context_win * 3 chars is the trim trigger. Build a history
        # whose post-compress cost > target (the trim target), then
        # confirm:
        #   * length decreases
        #   * tokens_est tracks ctx / 3 under the default heuristic
        # compress_history_tags() shrinks <thinking>/<tool_use> blocks in
        # older messages but does not drop messages, so plain content is
        # left alone and the trim's hard-cut loop (which loops while
        # `len(post) > 9`) is the only thing that can drop messages.
        sess = self._make_sess(context_win=2, trim_keep_prefix=0, trim_keep_rate=0.3)
        # 25 user messages of 30-char content. context_win*3 = 6 cap,
        # target = 6 * 0.3 = 1. hard-cut loop: pops until either
        # len(post) <= 9 OR cost <= target. With 30-char msgs at >1
        # char target the loop terminates by len(post) > 9, ending at 9.
        hist = _history(*[("user", "x" * 30)] * 25)
        before = len(hist)
        llmcore.trim_messages_history(hist, sess)
        self.assertLess(len(hist), before)
        # The trim path always leaves the last <=9 messages (that's the
        # only shape the existing hard-cut loop can produce). Pin it.
        self.assertLessEqual(len(hist), 9)
        # tokens_est still tracks ctx / 3 under the default heuristic.
        self.assertEqual(llmcore.STATS["tokens_est"], llmcore.STATS["ctx"] // 3)

    def test_session_with_custom_chars_per_token_is_honoured_in_log_only(self):
        # The estimator must reflect the per-session override in STATS,
        # but the trim gate must still use the default 3-char multiplier
        # (so behaviour stays byte-identical for v1).
        sess = self._make_sess(context_win=1000)
        sess.token_chars_per_token = 1.5
        hist = _history(("user", "hi"))
        llmcore.trim_messages_history(hist, sess)
        # ctx stays char-based.
        self.assertGreater(llmcore.STATS["ctx"], 0)
        # tokens_est uses the per-session override (1.5x larger than /3).
        # exact formula: ctx / 1.5 (rounded down by int()).
        self.assertEqual(llmcore.STATS["tokens_est"], llmcore.STATS["ctx"] // 1.5)


if __name__ == "__main__":
    unittest.main()