import unittest
from types import SimpleNamespace

from agent_loop import exhaust
from ga import GenericAgentHandler


class NoToolRetryTests(unittest.TestCase):
    def setUp(self):
        self.handler = GenericAgentHandler.__new__(GenericAgentHandler)
        self.handler._in_plan_mode = lambda: False

    def respond(self, content, thinking="", error=None):
        return exhaust(self.handler.do_no_tool({}, SimpleNamespace(content=content, thinking=thinking, error=error)))

    def test_short_error_retries(self):
        outcome = self.respond("!!!Error: ConnectionError: empty response", error="transport")
        self.assertIsNotNone(outcome.next_prompt)
        self.assertFalse(outcome.should_exit)

    def test_error_prefix_retries_with_long_details(self):
        self.assertIsNotNone(self.respond("!!!Error: ConnectionError: " + "x" * 150, error="transport").next_prompt)

    def test_error_retries_are_bounded(self):
        for attempt in range(3):
            outcome = self.respond("!!!Error: ConnectionError: empty response", error="transport")
            self.assertEqual(outcome.should_exit, attempt == 2)
            self.assertEqual(outcome.next_prompt is None, attempt == 2)

    def test_existing_retry_cases(self):
        for content in ("",
                        "<summary>Working</summary>", "max_tokens !!!]"):
            with self.subTest(content=content):
                self.setUp()
                self.assertIsNotNone(self.respond(content).next_prompt)

    def test_normal_and_quoted_responses_finish(self):
        for content, thinking in (("!!!Error: ConnectionError: empty response", ""), ("x" * 60 + "!!!Error: disconnected", ""), ("Done.", ""), ("", "Reasoning only"),
                                  ("The marker is '!!!Error:'.", "")):
            with self.subTest(content=content):
                self.assertIsNone(self.respond(content, thinking).next_prompt)
                self.assertFalse(hasattr(self.handler, "_empty_ct"))


if __name__ == "__main__":
    unittest.main()
