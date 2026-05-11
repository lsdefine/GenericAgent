import sys
import types
import unittest
from unittest.mock import patch

import llmcore


class CopilotSDKSessionTests(unittest.TestCase):
    def setUp(self):
        self._saved_modules = {}
        self.record = {}
        self._install_copilot_stubs()

    def tearDown(self):
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def _swap_module(self, name, module):
        if name not in self._saved_modules:
            self._saved_modules[name] = sys.modules.get(name)
        sys.modules[name] = module

    def _install_copilot_stubs(self):
        record = self.record

        class FakeSubprocessConfig:
            def __init__(self, **kwargs):
                record["subprocess_kwargs"] = kwargs
                self.kwargs = kwargs

        class FakeSession:
            async def send_and_wait(self, prompt):
                record["prompt"] = prompt
                return types.SimpleNamespace(data=types.SimpleNamespace(content="stubbed copilot reply"))

            async def disconnect(self):
                record["disconnected"] = True

        class FakeCopilotClient:
            def __init__(self, config=None, **kwargs):
                record["client_config"] = config
                record["client_kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def create_session(self, **kwargs):
                record["create_session_kwargs"] = kwargs
                return FakeSession()

        copilot_mod = types.ModuleType("copilot")
        copilot_mod.CopilotClient = FakeCopilotClient
        copilot_mod.SubprocessConfig = FakeSubprocessConfig

        session_mod = types.ModuleType("copilot.session")

        class PermissionHandler:
            approve_all = object()

        session_mod.PermissionHandler = PermissionHandler
        self._swap_module("copilot", copilot_mod)
        self._swap_module("copilot.session", session_mod)

    def test_resolve_session_supports_copilot_sdk_config(self):
        cfg = {
            "name": "copilot-sdk",
            "model": "gpt-5",
            "github_token": "ghp_test",
            "copilot_home": "/tmp/copilot-home",
            "cli_args": ["--dummy-flag"],
            "cli_log_level": "debug",
        }
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            session = llmcore.resolve_session("copilot_sdk_config")
            self.assertIsInstance(session, llmcore.CopilotSDKSession)
            output = "".join(session.ask("hello copilot sdk"))

        self.assertIn("stubbed copilot reply", output)
        self.assertEqual(self.record["create_session_kwargs"]["model"], "gpt-5")
        self.assertIn("on_permission_request", self.record["create_session_kwargs"])
        self.assertEqual(self.record["subprocess_kwargs"]["github_token"], "ghp_test")
        self.assertTrue(self.record.get("disconnected"))

    def test_resolve_client_wraps_copilot_sdk_as_tool_client(self):
        cfg = {"model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            client = llmcore.resolve_client("copilot_sdk_config")
        self.assertIsInstance(client, llmcore.ToolClient)


if __name__ == "__main__":
    unittest.main()
