import unittest
from types import SimpleNamespace

from agent_loop import BaseHandler, exhaust, agent_runner_loop


class StubClient:
    def __init__(self):
        self.last_tools = ""

    def chat(self, messages, tools):
        response = SimpleNamespace(content="final answer", tool_calls=[])

        def gen():
            if False:
                yield None
            return response

        return gen()


class StubHandler(BaseHandler):
    def __init__(self):
        self.parent = SimpleNamespace(task_dir=None)
        self._done_hooks = []
        self.turns = []

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        self.turns.append({
            "tool_calls": tool_calls,
            "next_prompt": next_prompt,
            "exit_reason": exit_reason,
        })
        return next_prompt


class AgentLoopNoToolTests(unittest.TestCase):
    def test_direct_answer_completes_without_fake_unknown_tool_retry(self):
        handler = StubHandler()
        result = exhaust(agent_runner_loop(
            StubClient(),
            "system",
            "user",
            handler,
            tools_schema=[],
            max_turns=1,
            verbose=False,
        ))

        self.assertEqual(result["result"], "CURRENT_TASK_DONE")
        self.assertEqual(len(handler.turns), 1)
        self.assertEqual(handler.turns[0]["tool_calls"][0]["tool_name"], "no_tool")
        self.assertEqual(handler.turns[0]["next_prompt"], "")
        self.assertNotIn("未知工具", handler.turns[0]["next_prompt"])


if __name__ == "__main__":
    unittest.main()
