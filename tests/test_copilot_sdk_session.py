import io
import sys
import types
import unittest
from unittest.mock import patch

import llmcore


class _StubSession:
    """Minimal session stub for MixinSession integration tests."""

    def __init__(self, name, reply="stub-fallback-reply", should_error=False):
        self.name = name
        self.model = "stub-model"
        self.max_retries = 0
        self.history = []
        self.system = ""
        self.tools = None
        self.temperature = 1
        self.max_tokens = None
        self.reasoning_effort = None
        self.context_win = 28000
        self._reply = reply
        self._should_error = should_error

    def raw_ask(self, messages):
        if self._should_error:
            err = "!!!Error: StubError: intentional failure"
            yield err
            return [{"type": "text", "text": err}]
        yield self._reply
        return [{"type": "text", "text": self._reply}]

    def ask(self, prompt):
        def _gen():
            msg = {"role": "user", "content": [{"type": "text", "text": prompt}]}
            self.history.append(msg)
            gen = self.raw_ask([msg])
            chunks = []
            try:
                while True:
                    chunk = next(gen)
                    chunks.append(chunk)
                    yield chunk
            except StopIteration:
                pass
            self.history.append({"role": "assistant", "content": [{"type": "text", "text": "".join(chunks)}]})
        return _gen()


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

    def _install_copilot_stubs(self, error=False):
        record = self.record

        class FakeSubprocessConfig:
            def __init__(self, **kwargs):
                record["subprocess_kwargs"] = kwargs
                self.kwargs = kwargs

        class FakeSession:
            async def send_and_wait(self, prompt):
                record["prompt"] = prompt
                if error:
                    raise RuntimeError("Copilot CLI unavailable")
                return types.SimpleNamespace(data=types.SimpleNamespace(content="stubbed copilot reply"))

            async def disconnect(self):
                record["disconnected"] = True

        class FakeCopilotClient:
            def __init__(self, config=None, **kwargs):
                record["client_config"] = config
                record["client_kwargs"] = kwargs
                self._client = types.SimpleNamespace(
                    get_stderr_output=lambda: record.get("stderr_output", "")
                )

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
            reject_all = object()

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
        self.assertIs(
            self.record["create_session_kwargs"]["on_permission_request"],
            sys.modules["copilot.session"].PermissionHandler.reject_all,
        )
        self.assertEqual(self.record["subprocess_kwargs"]["github_token"], "ghp_test")
        self.assertTrue(self.record.get("disconnected"))

    def test_copilot_sdk_allows_approve_all_by_permission_mode(self):
        cfg = {"model": "gpt-5", "permission_mode": "approve_all"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            session = llmcore.resolve_session("copilot_sdk_config")
            _ = "".join(session.ask("hello copilot sdk"))
        self.assertIs(
            self.record["create_session_kwargs"]["on_permission_request"],
            sys.modules["copilot.session"].PermissionHandler.approve_all,
        )

    def test_resolve_client_wraps_copilot_sdk_as_tool_client(self):
        cfg = {"model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            client = llmcore.resolve_client("copilot_sdk_config")
        self.assertIsInstance(client, llmcore.ToolClient)

    def test_copilot_sdk_logs_cli_output_to_console(self):
        cfg = {"model": "gpt-5"}
        self.record["stderr_output"] = "copilot cli debug log\n"
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            session = llmcore.resolve_session("copilot_sdk_config")
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                output = "".join(session.ask("hello copilot sdk"))
        self.assertIn("stubbed copilot reply", output)
        self.assertIn("copilot cli debug log", stderr.getvalue())

    def test_copilot_sdk_can_disable_cli_console_logs(self):
        cfg = {"model": "gpt-5", "cli_log_to_console": False}
        self.record["stderr_output"] = "copilot cli debug log\n"
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            session = llmcore.resolve_session("copilot_sdk_config")
            with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                output = "".join(session.ask("hello copilot sdk"))
        self.assertIn("stubbed copilot reply", output)
        self.assertEqual("", stderr.getvalue())

    def test_copilot_sdk_response_shows_in_console_log(self):
        cfg = {"model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            session = llmcore.resolve_session("copilot_sdk_config")
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                output = "".join(session.ask("hello copilot sdk"))
        self.assertIn("stubbed copilot reply", output)
        self.assertIn("stubbed copilot reply", stdout.getvalue())

    def test_copilot_sdk_can_disable_response_console_log(self):
        cfg = {"model": "gpt-5", "response_log_to_console": False}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            session = llmcore.resolve_session("copilot_sdk_config")
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                output = "".join(session.ask("hello copilot sdk"))
        self.assertIn("stubbed copilot reply", output)
        self.assertNotIn("stubbed copilot reply", stdout.getvalue())

    def test_copilot_sdk_in_mixin_session_by_index(self):
        """CopilotSDKSession referenced by integer index in MixinSession returns copilot reply."""
        cfg = {"name": "copilot-sdk", "model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            sdk_client = llmcore.resolve_client("copilot_sdk_config")
        mixin = llmcore.MixinSession([sdk_client], {"llm_nos": [0], "max_retries": 0})
        output = "".join(mixin.ask("hello from mixin"))
        self.assertIn("stubbed copilot reply", output)

    def test_copilot_sdk_in_mixin_session_by_name(self):
        """CopilotSDKSession referenced by name in MixinSession llm_nos returns copilot reply."""
        cfg = {"name": "copilot-sdk", "model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            sdk_client = llmcore.resolve_client("copilot_sdk_config")
        mixin = llmcore.MixinSession([sdk_client], {"llm_nos": ["copilot-sdk"], "max_retries": 0})
        output = "".join(mixin.ask("hello from mixin by name"))
        self.assertIn("stubbed copilot reply", output)

    def test_mixin_session_falls_back_from_copilot_sdk_on_error(self):
        """MixinSession falls back to a second session when CopilotSDKSession reports an error."""
        self._install_copilot_stubs(error=True)
        cfg = {"name": "copilot-sdk", "model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            sdk_client = llmcore.resolve_client("copilot_sdk_config")
        fallback = _StubSession("fallback", reply="fallback reply")
        fallback_client = llmcore.ToolClient(fallback)
        mixin = llmcore.MixinSession(
            [sdk_client, fallback_client],
            {"llm_nos": [0, 1], "max_retries": 1},
        )
        output = "".join(mixin.ask("hello with fallback"))
        self.assertIn("fallback reply", output)
        self.assertNotIn("stubbed copilot reply", output)

    def test_mixin_session_wraps_copilot_sdk_as_tool_client(self):
        """ToolClient wrapping a MixinSession backed by CopilotSDKSession is usable for chat."""
        cfg = {"name": "copilot-sdk", "model": "gpt-5"}
        with patch.object(llmcore, "reload_mykeys", return_value=({"copilot_sdk_config": cfg}, True)):
            sdk_client = llmcore.resolve_client("copilot_sdk_config")
        mixin = llmcore.MixinSession([sdk_client], {"llm_nos": [0], "max_retries": 0})
        tool_client = llmcore.ToolClient(mixin)
        self.assertIsInstance(tool_client, llmcore.ToolClient)
        messages = [{"role": "user", "content": "hello"}]
        output = "".join(tool_client.chat(messages))
        self.assertIn("stubbed copilot reply", output)


if __name__ == "__main__":
    unittest.main()
