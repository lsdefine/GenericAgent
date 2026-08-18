import sys
import unittest
from unittest import mock

from ga_cli import cli


class GaCliInterpreterTests(unittest.TestCase):
    def test_python_launcher_uses_current_interpreter(self):
        proc = mock.Mock()
        with mock.patch.object(cli.subprocess, "Popen", return_value=proc) as popen, \
             mock.patch.object(cli.os, "chdir"):
            cli.launch_frontend(["python", "{PROJECT_DIR}/agentmain.py"], ["--help"])

        popen.assert_called_once()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith("agentmain.py"))
        self.assertEqual(command[2:], ["--help"])
        proc.wait.assert_called_once_with()

    def test_non_python_launcher_is_not_rewritten(self):
        proc = mock.Mock()
        with mock.patch.object(cli.subprocess, "Popen", return_value=proc) as popen, \
             mock.patch.object(cli.os, "chdir"):
            cli.launch_frontend(["custom-runtime", "script"], None)

        self.assertEqual(popen.call_args.args[0][0], "custom-runtime")


if __name__ == "__main__":
    unittest.main()
