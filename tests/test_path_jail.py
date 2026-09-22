import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from ga import GenericAgentHandler


class TestPathJail(unittest.TestCase):
    def make_handler(self, cwd: Path) -> GenericAgentHandler:
        handler = GenericAgentHandler.__new__(GenericAgentHandler)
        handler.cwd = str(cwd)
        return handler

    def test_relative_and_absolute_paths_inside_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            handler = self.make_handler(root)
            self.assertEqual(handler._get_abs_path("notes.txt"), str(root / "notes.txt"))
            self.assertEqual(handler._get_abs_path(str(root / "notes.txt")), str(root / "notes.txt"))

    def test_parent_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = self.make_handler(Path(directory) / "temp")
            with self.assertRaisesRegex(ValueError, "inside working directory"):
                handler._get_abs_path("../assets/code_run_header.py")

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "temp"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            link = root / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable on this platform")

            handler = self.make_handler(root)
            with self.assertRaisesRegex(ValueError, "inside working directory"):
                handler._get_abs_path("link/poisoned.py")

    def test_file_write_reports_rejected_path(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = self.make_handler(Path(directory) / "temp")
            response = SimpleNamespace(content="<file_content>poison</file_content>")
            operation = handler.do_file_write({"path": "../assets/code_run_header.py"}, response)

            first_message = next(operation)
            self.assertIn("路径拒绝", first_message)
            with self.assertRaises(StopIteration) as stopped:
                next(operation)
            self.assertEqual(stopped.exception.value.data["status"], "error")


if __name__ == "__main__":
    unittest.main()
