import unittest
from types import SimpleNamespace

from agent_loop import BaseHandler, exhaust, agent_runner_loop


class StubClient:
    def __init__(self, arguments):
        self.arguments = arguments
        self.last_tools = ""

    def chat(self, messages, tools):
        response = SimpleNamespace(
            content="",
            tool_calls=[SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name="file_read", arguments=self.arguments),
            )],
        )

        def gen():
            if False:
                yield None
            return response

        return gen()


class StubHandler(BaseHandler):
    def __init__(self):
        self.parent = SimpleNamespace(task_dir=None)
        self._done_hooks = []
        self.next_prompts = []

    def do_file_read(self, args, response):
        if False:
            yield None
        return SimpleNamespace(data=None, next_prompt="ok", should_exit=False)

    def turn_end_callback(self, response, tool_calls, tool_results, turn, next_prompt, exit_reason):
        self.next_prompts.append(next_prompt)
        return next_prompt


class AgentLoopBadJsonTests(unittest.TestCase):
    def _run(self, arguments):
        handler = StubHandler()
        result = exhaust(agent_runner_loop(
            StubClient(arguments),
            "system",
            "user",
            handler,
            tools_schema=[],
            max_turns=1,
            verbose=False,
        ))
        return result, handler

    def test_malformed_tool_arguments_are_returned_to_model_for_retry(self):
        result, handler = self._run('{"path":')
        self.assertEqual(result, {"result": "MAX_TURNS_EXCEEDED"})
        self.assertEqual(len(handler.next_prompts), 1)
        self.assertIn("file_read", handler.next_prompts[0])
        self.assertIn("invalid JSON", handler.next_prompts[0])

    def test_non_object_json_tool_arguments_are_returned_for_retry(self):
        for arguments in ("null", "[]", '"path"', "1", "true"):
            with self.subTest(arguments=arguments):
                result, handler = self._run(arguments)
                self.assertEqual(result, {"result": "MAX_TURNS_EXCEEDED"})
                self.assertEqual(len(handler.next_prompts), 1)
                self.assertIn("file_read", handler.next_prompts[0])
                self.assertIn("JSON object", handler.next_prompts[0])

    def test_malformed_argument_retry_preview_is_bounded(self):
        arguments = '{"path":"' + ('x' * 20_000)
        result, handler = self._run(arguments)

        self.assertEqual(result, {"result": "MAX_TURNS_EXCEEDED"})
        self.assertEqual(len(handler.next_prompts), 1)
        prompt = handler.next_prompts[0]
        self.assertLess(len(prompt), 2_000)
        self.assertIn("truncated", prompt.lower())
        self.assertIn(str(len(arguments)), prompt)


if __name__ == "__main__":
    unittest.main()
