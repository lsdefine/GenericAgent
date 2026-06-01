import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "frontends")]

from frontends.chatapp_common import extract_files


class ExtractFilesTest(unittest.TestCase):
    def test_ignores_file_hint_placeholders(self):
        text = (
            "If you need to show files to user, use [FILE:filepath] in your response.\n"
            "Other placeholders: [FILE:<filepath>] [FILE:path] [FILE:<path>] "
            "[FILE:file_path] [FILE:<file_path>] [FILE:...]"
        )

        self.assertEqual(extract_files(text), [])

    def test_keeps_real_paths_and_deduplicates(self):
        text = (
            "Created [FILE:/tmp/report.txt]\n"
            "Again [FILE:/tmp/report.txt]\n"
            "Relative [FILE:outputs/chart.png]"
        )

        self.assertEqual(extract_files(text), ["/tmp/report.txt", "outputs/chart.png"])


if __name__ == "__main__":
    unittest.main()