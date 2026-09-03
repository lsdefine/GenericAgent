import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


previous_agent_loop = sys.modules.get('agent_loop')
real_agent_loop = load_module('_long_term_gate_agent_loop', ROOT / 'agent_loop.py')
sys.modules['agent_loop'] = real_agent_loop
try:
    ga = load_module('_long_term_gate_ga', ROOT / 'ga.py')
finally:
    if previous_agent_loop is None:
        del sys.modules['agent_loop']
    else:
        sys.modules['agent_loop'] = previous_agent_loop

GenericAgentHandler = ga.GenericAgentHandler


class Parent:
    def get_ctx_multiplier(self):
        return 1


def exhaust(generator):
    try:
        while True:
            next(generator)
    except StopIteration as exc:
        return exc.value


class LongTermUpdateGateTests(unittest.TestCase):
    def handler(self, enabled=True):
        return GenericAgentHandler(Parent(), cwd='./temp', long_term_update_pending=enabled)

    def finish(self, handler, turn):
        handler.current_turn = turn
        response = SimpleNamespace(content='Task complete.', thinking='')
        return exhaust(handler.do_no_tool({}, response))

    def test_turn_before_threshold_exits_normally(self):
        handler = self.handler()
        outcome = self.finish(handler, 14)
        self.assertIsNone(outcome.next_prompt)
        self.assertTrue(handler.long_term_update_pending)

    @patch.object(ga, 'file_read', return_value='memory SOP')
    @patch.object(ga, 'get_global_memory', return_value='memory index')
    @patch.object(ga.os.path, 'exists', return_value=True)
    def test_threshold_starts_evaluation_once(self, _exists, _memory, _read):
        handler = self.handler()
        outcome = self.finish(handler, 15)
        self.assertIn('memory SOP', outcome.next_prompt)
        self.assertIn('总结提炼经验', outcome.next_prompt)
        self.assertFalse(handler.long_term_update_pending)

        second = self.finish(handler, 16)
        self.assertIsNone(second.next_prompt)

    def test_disabled_gate_exits_normally(self):
        handler = self.handler(enabled=False)
        outcome = self.finish(handler, 20)
        self.assertIsNone(outcome.next_prompt)
        self.assertFalse(handler.long_term_update_pending)

    @patch.object(ga, 'file_read', return_value='memory SOP')
    @patch.object(ga, 'get_global_memory', return_value='memory index')
    @patch.object(ga.os.path, 'exists', return_value=True)
    def test_explicit_update_consumes_completion_gate(self, _exists, _memory, _read):
        handler = self.handler()
        handler.current_turn = 10
        exhaust(handler.do_start_long_term_update({}, SimpleNamespace()))
        self.assertFalse(handler.long_term_update_pending)

        outcome = self.finish(handler, 20)
        self.assertIsNone(outcome.next_prompt)
        self.assertFalse(handler.long_term_update_pending)

    def test_rejected_early_call_keeps_completion_gate_pending(self):
        handler = self.handler()
        handler.current_turn = 9
        outcome = exhaust(handler.do_start_long_term_update({}, SimpleNamespace()))
        self.assertEqual('\n', outcome.next_prompt)
        self.assertTrue(handler.long_term_update_pending)


if __name__ == '__main__':
    unittest.main()
