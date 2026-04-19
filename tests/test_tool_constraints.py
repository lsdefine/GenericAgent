"""Regression tests for tool constraint handling."""
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_loop import exhaust
from ga import GenericAgentHandler
from llmcore import ToolClient


class TestToolConstraints(unittest.TestCase):
    def setUp(self):
        self.repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.temp_dir = os.path.join(self.repo_dir, "temp")
        os.makedirs(self.temp_dir, exist_ok=True)
        self.parent = SimpleNamespace(verbose=False, task_dir=self.temp_dir)
        self.handler = GenericAgentHandler(self.parent, cwd=self.temp_dir)

    def test_code_run_infers_powershell_from_fenced_block(self):
        captured = {}

        def fake_code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=None):
            captured.update({
                "code": code,
                "code_type": code_type,
                "cwd": cwd,
                "code_cwd": code_cwd,
            })
            if False:
                yield None
            return {"status": "success"}

        response = SimpleNamespace(content="List files first.\n```powershell\nGet-ChildItem\n```")
        with patch("ga.code_run", new=fake_code_run):
            outcome = exhaust(self.handler.do_code_run({}, response))

        self.assertEqual(captured["code"], "Get-ChildItem")
        self.assertEqual(captured["code_type"], "powershell")
        self.assertEqual(outcome.data, {"status": "success"})

    def test_code_run_missing_script_returns_retry_hint(self):
        response = SimpleNamespace(content="Need to inspect the folder.")
        outcome = exhaust(self.handler.do_code_run({"type": "python"}, response))

        self.assertIn("code_run requires a non-empty script", outcome.data)
        self.assertIn("cwd:'../'", outcome.next_prompt)
        self.assertIn(self.repo_dir, outcome.next_prompt)

    def test_web_execute_js_extracts_js_alias_block(self):
        captured = {}

        def fake_web_execute_js(script, switch_tab_id=None, no_monitor=False):
            captured.update({
                "script": script,
                "switch_tab_id": switch_tab_id,
                "no_monitor": no_monitor,
            })
            return {"status": "success", "js_return": "ok"}

        response = SimpleNamespace(content="```js\nconsole.log('ok')\n```")
        with patch("ga.web_execute_js", new=fake_web_execute_js):
            outcome = exhaust(self.handler.do_web_execute_js({}, response))

        self.assertEqual(captured["script"], "console.log('ok')")
        self.assertIn('"status": "success"', outcome.data)

    def test_cached_tool_prompt_keeps_critical_rules(self):
        client = ToolClient(SimpleNamespace(name="test-backend"))
        tools = [{
            "type": "function",
            "function": {
                "name": "code_run",
                "description": "Code executor",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

        first = client._prepare_tool_instruction_v2(tools)
        second = client._prepare_tool_instruction_v2(tools)

        self.assertIn("Critical tool rules", first)
        self.assertIn("Critical tool rules", second)
        self.assertIn("cwd:'../'", second)
        self.assertIn("Format: ```<tool_use>", second)


if __name__ == "__main__":
    unittest.main()
