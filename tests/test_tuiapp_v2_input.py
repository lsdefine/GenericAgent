import asyncio
import contextlib
import io
import importlib
import sys
import unittest
from pathlib import Path

try:
    from textual import events
    from textual.app import App, ComposeResult
except ModuleNotFoundError:  # pragma: no cover - optional UI dependency
    events = None
    App = object
    ComposeResult = object


@unittest.skipIf(events is None, "textual is not installed")
class TuiAppV2InputPasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[1]
        frontends = repo_root / "frontends"
        for path in (str(repo_root), str(frontends)):
            if path not in sys.path:
                sys.path.insert(0, path)

        saved_modules = {}
        for name in ("agentmain", "chatapp_common", "continue_cmd", "llmcore"):
            saved_modules[name] = sys.modules.pop(name, None)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                module = importlib.import_module("frontends.tuiapp_v2")
        finally:
            for name, module_stub in saved_modules.items():
                if module_stub is not None:
                    sys.modules[name] = module_stub
        input_cls = module.InputArea

        class InputHarness(App[None]):
            def compose(self) -> ComposeResult:
                yield input_cls(id="input")

            def on_mount(self) -> None:
                self.query_one(input_cls).focus()

        cls.InputArea = input_cls
        cls.InputHarness = InputHarness

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_ctrl_v_pastes_from_textual_clipboard(self):
        async def run():
            async with self.InputHarness().run_test() as pilot:
                input_area = pilot.app.query_one(self.InputArea)
                pilot.app.copy_to_clipboard("hello from clipboard")

                await pilot.press("ctrl+v")

                self.assertEqual(input_area.text, "hello from clipboard")

        self.run_async(run())

    def test_bracketed_paste_normalizes_windows_newlines(self):
        async def run():
            async with self.InputHarness().run_test() as pilot:
                input_area = pilot.app.query_one(self.InputArea)

                pilot.app.post_message(events.Paste("first\r\nsecond"))
                await pilot.pause()

                self.assertEqual(input_area.text, "first\nsecond")

        self.run_async(run())

    def test_long_multiline_paste_uses_placeholder_but_submits_full_text(self):
        async def run():
            async with self.InputHarness().run_test() as pilot:
                input_area = pilot.app.query_one(self.InputArea)

                pilot.app.post_message(events.Paste("one\ntwo\nthree"))
                await pilot.pause()

                self.assertEqual(input_area.text, "[Pasted text #1 +3 lines]")
                self.assertEqual(input_area.expand_placeholders(input_area.text), "one\ntwo\nthree")

        self.run_async(run())

    def test_ctrl_v_and_bracketed_paste_do_not_duplicate_same_payload(self):
        async def run():
            async with self.InputHarness().run_test() as pilot:
                input_area = pilot.app.query_one(self.InputArea)
                pilot.app.copy_to_clipboard("same")

                await pilot.press("ctrl+v")
                pilot.app.post_message(events.Paste("same"))
                await pilot.pause()

                self.assertEqual(input_area.text, "same")

        self.run_async(run())


if __name__ == "__main__":
    unittest.main()
