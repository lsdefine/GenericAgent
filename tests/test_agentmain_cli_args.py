import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTMAIN = ROOT / "agentmain.py"
_RUNNER = (
    "import runpy, sys\n"
    "target = sys.argv[1]\n"
    "sys.argv = [target, *sys.argv[2:]]\n"
    "runpy.run_path(target, run_name='__main__')\n"
)


def run_agentmain(*args):
    with tempfile.TemporaryDirectory() as tmp:
        state = Path(tmp)
        (state / "mykey.py").write_text("", encoding="utf-8")
        plugins = state / "plugins"
        plugins.mkdir()
        (plugins / "__init__.py").write_text("", encoding="utf-8")
        (plugins / "hooks.py").write_text(
            "def trigger(event, ctx): return ctx\n"
            "def discover_and_load(plugin_dir=None): return None\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["GA_LANG"] = "en"
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONPATH"] = os.pathsep.join((str(state), str(ROOT)))
        return subprocess.run(
            [sys.executable, "-c", _RUNNER, str(AGENTMAIN), *args],
            cwd=state,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            env=env,
        )


class AgentMainCliArgumentTests(unittest.TestCase):
    def test_unknown_args_without_reflect_fail_fast(self):
        result = run_agentmain("--goal", "dummy-goal.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --goal dummy-goal.json", result.stderr)
        self.assertNotIn("EOFError", result.stderr)

    def test_reflect_extras_require_complete_key_value_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "reflect_exit.py"
            script.write_text("def check(): return '/exit'\n", encoding="utf-8")
            for extras in (("--name",), ("--name", "--other"), ("---name", "hive-master")):
                with self.subTest(extras=extras):
                    result = run_agentmain("--reflect", str(script), *extras)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("reflect extra arguments must be --key value pairs", result.stderr)

    def test_reflect_rejects_empty_script_path_explicitly(self):
        result = run_agentmain("--reflect", "", "--name", "hive-master")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--reflect requires a non-empty script path", result.stderr)

    def test_reflect_key_value_extras_remain_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "reflect_exit.py"
            script.write_text(
                "def init(args): print('INIT_NAME=' + str(args.get('name')))\n"
                "def check(): return '/exit'\n",
                encoding="utf-8",
            )
            result = run_agentmain("--reflect", str(script), "--name", "hive-master")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("INIT_NAME=hive-master", result.stdout)
        self.assertIn("[Reflect] loaded", result.stdout)


if __name__ == "__main__":
    unittest.main()
