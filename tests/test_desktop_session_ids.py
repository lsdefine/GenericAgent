import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


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
    bridge = _load_module("desktop_bridge_session_id_test", FRONTENDS / "desktop_bridge.py")
finally:
    sys.argv = _old_argv
    if _old_ga_root is None:
        os.environ.pop("GA_ROOT", None)
    else:
        os.environ["GA_ROOT"] = _old_ga_root


class DesktopSessionIdPersistenceTests(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(_TEST_GA_PATH / "temp", ignore_errors=True)
        for path in _TEST_GA_PATH.glob("*.json"):
            path.unlink()
        self.manager = bridge.AgentManager()
        self.manager.sessions.clear()
        self.manager.active_session_id = None

    @staticmethod
    def _write_session(source: Path, sid: str):
        sessions = source / "temp" / "desktop_sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / "import.json").write_text(
            json.dumps({"id": sid, "messages": [], "msg_seq": 0}),
            encoding="utf-8",
        )

    def test_import_rejects_traversal_id_without_writing_outside_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            self._write_session(source, "../../escape")
            escaped = _TEST_GA_PATH / "escape.json"

            result = self.manager.import_sessions(str(source))

        self.assertEqual(result["sessionsAdded"], 0)
        self.assertEqual(result["sessionsSkipped"], 1)
        self.assertNotIn("../../escape", self.manager.sessions)
        self.assertFalse(escaped.exists())

    def test_import_rejects_absolute_id_without_writing_outside_store(self):
        sid = str(_TEST_GA_PATH / "absolute-escape")
        escaped = Path(f"{sid}.json")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            self._write_session(source, sid)

            result = self.manager.import_sessions(str(source))

        self.assertEqual(result["sessionsAdded"], 0)
        self.assertEqual(result["sessionsSkipped"], 1)
        self.assertNotIn(sid, self.manager.sessions)
        self.assertFalse(escaped.exists())

    def test_import_rejects_normalized_alias_that_collides_with_existing_session(self):
        safe_id = "sess-safe123"
        alias_id = f"nested/../{safe_id}"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            self._write_session(source, safe_id)
            first = self.manager.import_sessions(str(source))
            self._write_session(source, alias_id)
            second = self.manager.import_sessions(str(source))

        persisted = json.loads(
            (self.manager._sessions_dir / f"{safe_id}.json").read_text(encoding="utf-8")
        )
        self.assertEqual(first["sessionsAdded"], 1)
        self.assertEqual(second["sessionsAdded"], 0)
        self.assertEqual(second["sessionsSkipped"], 1)
        self.assertNotIn(alias_id, self.manager.sessions)
        self.assertEqual(persisted["id"], safe_id)

    def test_import_rejects_windows_style_path_separator(self):
        sid = r"nested\..\sess-safe123"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            self._write_session(source, sid)

            result = self.manager.import_sessions(str(source))

        self.assertEqual(result["sessionsAdded"], 0)
        self.assertEqual(result["sessionsSkipped"], 1)
        self.assertNotIn(sid, self.manager.sessions)

    def test_import_keeps_valid_session_ids(self):
        sid = "sess-safe456"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            self._write_session(source, sid)

            result = self.manager.import_sessions(str(source))

        self.assertEqual(result["sessionsAdded"], 1)
        self.assertEqual(result["sessionsSkipped"], 0)
        self.assertIn(sid, self.manager.sessions)
        self.assertTrue((self.manager._sessions_dir / f"{sid}.json").is_file())


if __name__ == "__main__":
    unittest.main()
