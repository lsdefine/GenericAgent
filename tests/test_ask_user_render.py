import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ask_user_render import (
    extract_ask_user_event,
    extract_ask_user_event_from_text,
    format_ask_user_message,
    summarize_tool_args,
)


class AskUserRenderTests(unittest.TestCase):
    def setUp(self):
        self.exit_reason = {
            "result": "EXITED",
            "data": {
                "status": "INTERRUPT",
                "intent": "HUMAN_INTERVENTION",
                "data": {
                    "question": "下一步怎么做？",
                    "candidates": ["继续部署", "先看日志", "回滚"],
                },
            },
        }

    def test_extract_ask_user_event(self):
        event = extract_ask_user_event(self.exit_reason)
        self.assertEqual(
            event,
            {
                "question": "下一步怎么做？",
                "candidates": ["继续部署", "先看日志", "回滚"],
            },
        )

    def test_extract_ask_user_event_from_text_python_repr(self):
        text = str(self.exit_reason["data"])
        event = extract_ask_user_event_from_text(text)
        self.assertEqual(event["question"], "下一步怎么做？")
        self.assertEqual(event["candidates"][1], "先看日志")

    def test_format_ask_user_message(self):
        message = format_ask_user_message(extract_ask_user_event(self.exit_reason))
        self.assertIn("🙋 需要你来决定下一步", message)
        self.assertIn("下一步怎么做？", message)
        self.assertIn("1. 继续部署", message)
        self.assertIn("3. 回滚", message)

    def test_summarize_tool_args_for_ask_user(self):
        summary = summarize_tool_args(
            "ask_user",
            {"question": "选择数据库", "candidates": ["MySQL", "Postgres"]},
            max_len=200,
        )
        self.assertIn("等待用户回复", summary)
        self.assertIn("选择数据库", summary)
        self.assertIn("MySQL", summary)

    def test_format_from_python_repr_payload(self):
        raw_text = str(self.exit_reason["data"])
        event = extract_ask_user_event_from_text(raw_text)
        rendered = format_ask_user_message(event)
        self.assertIn("🙋 需要你来决定下一步", rendered)
        self.assertIn("下一步怎么做？", rendered)
        self.assertNotIn("'status': 'INTERRUPT'", rendered)


if __name__ == "__main__":
    unittest.main()
