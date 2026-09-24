import importlib.util
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = ROOT / "frontends"
_MISSING = object()


class DesktopSessionPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._test_ga_root = tempfile.TemporaryDirectory()
        cls.test_ga_path = Path(cls._test_ga_root.name)
        (cls.test_ga_path / "agentmain.py").touch()

        cls._module_name = "desktop_bridge_persistence_test"
        cls._old_module = sys.modules.get(cls._module_name, _MISSING)
        old_ga_root = os.environ.get("GA_ROOT")
        old_argv = sys.argv[:]
        old_sys_path = sys.path[:]
        os.environ["GA_ROOT"] = str(cls.test_ga_path)
        sys.argv = [sys.argv[0]]
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(FRONTENDS))
        try:
            path = FRONTENDS / "desktop_bridge.py"
            spec = importlib.util.spec_from_file_location(cls._module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"failed to load {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[cls._module_name] = module
            spec.loader.exec_module(module)
            cls.bridge = module
        finally:
            sys.argv = old_argv
            sys.path[:] = old_sys_path
            if old_ga_root is None:
                os.environ.pop("GA_ROOT", None)
            else:
                os.environ["GA_ROOT"] = old_ga_root

    @classmethod
    def tearDownClass(cls):
        if cls._old_module is _MISSING:
            sys.modules.pop(cls._module_name, None)
        else:
            sys.modules[cls._module_name] = cls._old_module
        cls._test_ga_root.cleanup()
        super().tearDownClass()

    def setUp(self):
        sessions_dir = self.test_ga_path / "temp" / "desktop_sessions"
        if sessions_dir.is_dir():
            for path in sessions_dir.iterdir():
                if path.is_file():
                    path.unlink()
        self.manager = self.bridge.AgentManager()
        self.manager.sessions.clear()
        self.manager.active_session_id = None

    def _registered_session(self, sid="sess-race123"):
        sess = self.bridge.Session(id=sid, cwd=str(self.test_ga_path))
        with self.manager.lock:
            self.manager.sessions[sid] = sess
        return sess

    def test_same_session_temp_writes_do_not_overlap(self):
        sess = self._registered_session()
        original_write_text = Path.write_text
        guard = threading.Lock()
        first_entered = threading.Event()
        second_entered = threading.Event()
        active = 0
        overlap = False

        def probed_write_text(path, *args, **kwargs):
            nonlocal active, overlap
            if path.name != f"{sess.id}.json.tmp":
                return original_write_text(path, *args, **kwargs)
            with guard:
                active += 1
                slot = active
                if active > 1:
                    overlap = True
                if slot == 1:
                    first_entered.set()
                else:
                    second_entered.set()
            if slot == 1:
                second_entered.wait(0.3)
            else:
                first_entered.wait(0.3)
            try:
                return original_write_text(path, *args, **kwargs)
            finally:
                with guard:
                    active -= 1

        with mock.patch.object(Path, "write_text", autospec=True, side_effect=probed_write_text):
            threads = [threading.Thread(target=self.manager._persist_session, args=(sess,)) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(overlap, "same-session temp writes overlapped")

    def test_late_persist_does_not_recreate_deleted_session_file(self):
        sess = self._registered_session("sess-deleted123")
        self.manager._persist_session(sess)
        session_file = self.manager._session_file(sess.id)
        self.assertTrue(session_file.is_file())

        self.manager.delete_session(sess.id)
        self.assertFalse(session_file.exists())

        self.manager._persist_session(sess)

        self.assertFalse(session_file.exists())
        self.assertNotIn(sess.id, self.manager.sessions)


if __name__ == "__main__":
    unittest.main()
