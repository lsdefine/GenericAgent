import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = ROOT / "frontends"
_TEST_GA_ROOT = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(_TEST_GA_ROOT.cleanup)
_TEST_GA_PATH = Path(_TEST_GA_ROOT.name)
(_TEST_GA_PATH / "agentmain.py").touch()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load_module("plan_state", FRONTENDS / "plan_state.py")
_old_ga_root = os.environ.get("GA_ROOT")
_old_argv = sys.argv[:]
os.environ["GA_ROOT"] = str(_TEST_GA_PATH)
sys.argv = [sys.argv[0]]
try:
    bridge = _load_module("desktop_bridge_memory_import_test", FRONTENDS / "desktop_bridge.py")
finally:
    sys.argv = _old_argv
    if _old_ga_root is None:
        os.environ.pop("GA_ROOT", None)
    else:
        os.environ["GA_ROOT"] = _old_ga_root


class DesktopMemoryImportBoundaryTests(unittest.TestCase):
    def test_memory_import_does_not_follow_external_file_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            memory = source / "memory"
            memory.mkdir(parents=True)
            secret = root / "outside-secret.txt"
            secret.write_text("outside-secret", encoding="utf-8")
            try:
                (memory / "leak.txt").symlink_to(secret)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            result = bridge._import_memory_from(str(source), str(destination))

            leaked = destination / "memory" / "leak.txt"
            self.assertFalse(leaked.exists())
            self.assertEqual(result["memoryCopied"], 0)

    def test_memory_import_does_not_follow_external_directory_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            memory = source / "memory"
            external = root / "outside-dir"
            memory.mkdir(parents=True)
            external.mkdir()
            (external / "secret.txt").write_text("outside-directory-secret", encoding="utf-8")
            try:
                (memory / "linked").symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            result = bridge._import_memory_from(str(source), str(destination))

            self.assertFalse((destination / "memory" / "linked").exists())
            self.assertEqual(result["memoryCopied"], 0)

    def test_model_response_import_does_not_follow_external_file_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            responses = source / "temp" / "model_responses"
            responses.mkdir(parents=True)
            secret = root / "outside-response.txt"
            secret.write_text("outside-response", encoding="utf-8")
            try:
                (responses / "leak.txt").symlink_to(secret)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            result = bridge._import_memory_from(str(source), str(destination))

            leaked = destination / "temp" / "model_responses" / "leak.txt"
            self.assertFalse(leaked.exists())
            self.assertEqual(result["responsesCopied"], 0)

    def test_resolution_errors_fail_import_instead_of_silently_skipping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            memory = source / "memory"
            memory.mkdir(parents=True)
            broken = memory / "broken.txt"
            broken.write_text("must-not-be-silently-skipped", encoding="utf-8")
            original_resolve = Path.resolve

            def resolve_with_failure(path, *args, **kwargs):
                if path == broken:
                    raise OSError("simulated resolution failure")
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(Path, "resolve", autospec=True, side_effect=resolve_with_failure):
                with self.assertRaisesRegex(OSError, "simulated resolution failure"):
                    bridge._import_memory_from(str(source), str(destination))

    def test_regular_files_still_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            destination = root / "destination"
            memory = source / "memory"
            responses = source / "temp" / "model_responses"
            memory.mkdir(parents=True)
            responses.mkdir(parents=True)
            (memory / "note.txt").write_text("memory", encoding="utf-8")
            (responses / "response.txt").write_text("response", encoding="utf-8")

            result = bridge._import_memory_from(str(source), str(destination))

            self.assertEqual((destination / "memory" / "note.txt").read_text(encoding="utf-8"), "memory")
            self.assertEqual(
                (destination / "temp" / "model_responses" / "response.txt").read_text(encoding="utf-8"),
                "response",
            )
            self.assertEqual(result["memoryCopied"], 1)
            self.assertEqual(result["responsesCopied"], 1)


if __name__ == "__main__":
    unittest.main()
