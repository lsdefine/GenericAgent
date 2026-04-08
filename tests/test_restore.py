"""Tests for /restore log discovery and parsing."""
import os
import shutil
import unittest

from frontends.chatapp_common import format_restore


class TestRestoreFormatting(unittest.TestCase):
    """Test /restore compatibility with current log layout."""

    def setUp(self):
        self.repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.log_dir = os.path.join(self.repo_dir, "temp", "model_responses")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "model_responses_test_restore.txt")

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        if os.path.isdir(self.log_dir) and not os.listdir(self.log_dir):
            shutil.rmtree(self.log_dir)

    def test_format_restore_reads_current_prompt_response_logs(self):
        """Should restore chat turns from Prompt/Response log blocks."""
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(
                "=== Prompt === 2026-04-08 10:00:00\n你好，帮我总结一下\n\n"
                "=== Response === 2026-04-08 10:00:02\n当然可以，这是总结。\n\n"
                "=== Prompt === 2026-04-08 10:01:00\n第二个问题\n\n"
                "=== Response === 2026-04-08 10:01:03\n第二个回答\n\n"
            )

        restored_info, err = format_restore()

        self.assertIsNone(err)
        restored, fname, count = restored_info
        self.assertEqual(fname, os.path.basename(self.log_path))
        self.assertEqual(count, 2)
        self.assertEqual(
            restored,
            [
                "[USER]: 你好，帮我总结一下",
                "[Agent] 当然可以，这是总结。",
                "[USER]: 第二个问题",
                "[Agent] 第二个回答",
            ],
        )
