import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ga import check_cli_task, delegate_cli_task


class TestCliDelegation(unittest.TestCase):
    def test_dry_run_builds_gemini_command_without_prompt_leak(self):
        with patch("ga.shutil.which", return_value="/usr/local/bin/gemini"):
            result = delegate_cli_task(
                target="gemini",
                prompt="check this repo",
                cwd=tempfile.gettempdir(),
                mode="read_only",
                dry_run=True,
            )

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["command"][0], "/usr/local/bin/gemini")
        self.assertIn("-p", result["command"])
        self.assertIn("<prompt>", result["command"])
        self.assertIn("--approval-mode", result["command"])
        self.assertIn("plan", result["command"])
        self.assertNotIn("check this repo", " ".join(result["command"]))

    def test_missing_cli_returns_error(self):
        with patch("ga.shutil.which", return_value=None):
            result = delegate_cli_task(
                target="gemini",
                prompt="hello",
                cwd=tempfile.gettempdir(),
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("CLI not found", result["msg"])

    def test_runs_qwen_with_structured_result(self):
        with patch("ga.shutil.which", return_value="/usr/local/bin/qwen"), \
             patch("ga._run_cli_delegate_process", return_value=(0, "done", "")) as run:
            result = delegate_cli_task(
                target="qwen",
                prompt="summarize",
                cwd=tempfile.gettempdir(),
                mode="auto_edit",
                timeout=12,
                wait=False,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["stdout"], "done")
        args, kwargs = run.call_args
        self.assertEqual(args[3], 12)
        self.assertFalse(kwargs["wait"])
        self.assertEqual(args[1], os.path.abspath(tempfile.gettempdir()))
        self.assertEqual(args[0][0], "/usr/local/bin/qwen")
        self.assertIn("--bare", args[0])
        self.assertIn("--approval-mode", args[0])
        self.assertIn("auto-edit", args[0])

    def test_check_cli_task_running_when_status_missing(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as out:
            out.write("partial")
            output_path = out.name
        try:
            result = check_cli_task(output_path, output_path + ".status")
        finally:
            os.unlink(output_path)

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["stdout"], "partial")

    def test_check_cli_task_completed_and_cleanup(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as out:
            out.write("done")
            output_path = out.name
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as status:
            status.write("0")
            status_path = status.name

        result = check_cli_task(output_path, status_path, cleanup=True)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "done")
        self.assertFalse(os.path.exists(output_path))
        self.assertFalse(os.path.exists(status_path))

    def test_tool_schemas_include_cli_delegation(self):
        for path in ("assets/tools_schema.json", "assets/tools_schema_cn.json"):
            with open(path, encoding="utf-8") as f:
                schema = json.load(f)
            names = [item["function"]["name"] for item in schema]
            self.assertIn("delegate_cli_task", names)
            self.assertIn("check_cli_task", names)


if __name__ == "__main__":
    unittest.main()
