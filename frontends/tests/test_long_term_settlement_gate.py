"""Tests for the completion-time long-term settlement gate (#789).

ga.py imports with stdlib only (agent_loop falls back when plugins.hooks is
absent), so these tests exercise the real GenericAgentHandler.
Run: pytest frontends/tests/test_long_term_settlement_gate.py -v
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent

# test_bridge_sessions installs an attribute-less `agent_loop` stub into
# sys.modules; evict it so the real module can load (ga imports agent_loop).
_stub = sys.modules.get("agent_loop")
if _stub is not None and not hasattr(_stub, "BaseHandler"):
    del sys.modules["agent_loop"]
sys.path.insert(0, str(ROOT))

from ga import GenericAgentHandler


def _handler(turn, history=None):
    parent = SimpleNamespace(task_dir=None, verbose=False, extrakeyinfo=None, intervene=None)
    h = GenericAgentHandler(parent, last_history=history or [])
    h.current_turn = turn
    return h


def _run(gen):
    """Exhaust a do_* generator -> (yielded strings, returned StepOutcome)."""
    yields, outcome = [], None
    try:
        while True:
            yields.append(next(gen))
    except StopIteration as e:
        outcome = e.value
    return yields, outcome


def _response(content="任务已完成"):
    return SimpleNamespace(content=content, thinking="", tool_calls=None)


_SETTLE_MARK = "记忆提纯"


class TestGateThreshold:
    def test_turn_14_completes_normally(self):
        h = _handler(14)
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert outcome.next_prompt is None
        assert not h._lt_started

    def test_turn_15_enters_settlement_once(self):
        h = _handler(15)
        yields, outcome = _run(h.do_no_tool({}, _response()))
        assert h._lt_started
        assert _SETTLE_MARK in outcome.next_prompt
        assert any("distilling" in y for y in yields)

    def test_turn_40_enters_settlement(self):
        h = _handler(40)
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert _SETTLE_MARK in outcome.next_prompt

    def test_settlement_completion_exits_without_recursion(self):
        h = _handler(20)
        _, first = _run(h.do_no_tool({}, _response()))
        assert first.next_prompt is not None          # settlement phase started
        _, second = _run(h.do_no_tool({}, _response()))
        assert second.next_prompt is None             # settlement done -> normal exit

    def test_explicit_call_blocks_gate(self):
        h = _handler(20)
        _, settled = _run(h.do_start_long_term_update({}, _response()))
        assert settled.next_prompt is not None
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert outcome.next_prompt is None            # gate already satisfied

    def test_refused_early_call_does_not_block_gate(self):
        h = _handler(5)
        _, refused = _run(h.do_start_long_term_update({}, _response()))
        assert "only used after completing" in refused.data
        assert not h._lt_started
        h.current_turn = 20
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert _SETTLE_MARK in outcome.next_prompt     # gate still fires later


class TestExemptions:
    def test_no_user_tools_exempt(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["ga", "--no-user-tools"])
        h = _handler(30)
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert outcome.next_prompt is None
        assert not h._lt_started

    def test_autonomous_flow_exempt(self):
        h = _handler(30, history=["[USER]: [AUTO]🤖 用户已经离开超过30分钟，执行自动任务。"])
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert outcome.next_prompt is None
        assert not h._lt_started

    def test_normal_user_message_not_exempt(self):
        h = _handler(30, history=["[USER]: 帮我规划旅行"])
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert _SETTLE_MARK in outcome.next_prompt

    def test_autonomous_detection_uses_latest_user_message(self):
        h = _handler(30, history=[
            "[USER]: [AUTO] auto task",
            "[Agent] did stuff",
            "[USER]: 普通问题",
        ])
        _, outcome = _run(h.do_no_tool({}, _response()))
        assert _SETTLE_MARK in outcome.next_prompt
