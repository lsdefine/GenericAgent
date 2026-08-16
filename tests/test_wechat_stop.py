import importlib.util
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = ROOT / "frontends"


class FakeAgent:
    def __init__(self):
        self.verbose = False
        self.is_running = False
        self.abort_called = False
        self.abort_observer = None
        self.put_called = threading.Event()
        self.display_queue = queue.Queue()

    def put_task(self, query, source="user", images=None):
        self.is_running = True
        self.put_called.set()
        return self.display_queue

    def abort(self):
        self.abort_called = True
        if self.abort_observer:
            self.abort_observer()

    def next_llm(self, n=-1):
        return None

    def list_llms(self):
        return []

    def get_llm_name(self):
        return "fake"


class FakeBot:
    def __init__(self):
        self.sent_text = []
        self.sent_files = []
        self.sent_event = threading.Event()

    def extract_text(self, msg):
        return "\n".join(
            item.get("text_item", {}).get("text", "")
            for item in msg.get("item_list", [])
            if item.get("text_item")
        )

    def get_typing_ticket(self, uid, ctx):
        return ""

    def send_typing(self, *args, **kwargs):
        return None

    def send_text(self, uid, text, context_token=""):
        self.sent_text.append(text)
        self.sent_event.set()

    def send_file(self, uid, path, context_token=""):
        self.sent_files.append(path)

    send_image = send_file
    send_video = send_file


class WeChatStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        cls.test_home = Path(cls._tmp.name)
        cls._module_name = "wechatapp_stop_test"

        agentmain = types.ModuleType("agentmain")
        agentmain.GeneraticAgent = FakeAgent
        qrcode = types.ModuleType("qrcode")
        qrcode.QRCode = object
        qrcode.make = lambda *args, **kwargs: None
        crypto = types.ModuleType("Crypto")
        cipher = types.ModuleType("Crypto.Cipher")
        cipher.AES = object
        crypto.Cipher = cipher

        path = FRONTENDS / "wechatapp.py"
        spec = importlib.util.spec_from_file_location(cls._module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"failed to load {path}")
        module = importlib.util.module_from_spec(spec)
        stubs = {
            cls._module_name: module,
            "agentmain": agentmain,
            "qrcode": qrcode,
            "Crypto": crypto,
            "Crypto.Cipher": cipher,
        }
        old_home = os.environ.get("HOME")
        old_path = sys.path[:]
        try:
            os.environ["HOME"] = str(cls.test_home)
            with mock.patch.dict(sys.modules, stubs):
                spec.loader.exec_module(module)
        finally:
            sys.path[:] = old_path
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home
        cls.wechat = module

    def setUp(self):
        self.wechat._MODE = "agent"
        self.wechat._task_aborted.clear()
        self.wechat.agent.is_running = False
        self.wechat.agent.abort_called = False
        self.wechat.agent.abort_observer = None
        self.wechat.agent.put_called.clear()
        self.wechat.agent.display_queue = queue.Queue()
        self.bot = FakeBot()
        self.uid = "user-1"

    def _message(self, text):
        return {
            "from_user_id": self.uid,
            "context_token": "ctx",
            "item_list": [{"type": self.wechat.ITEM_TEXT, "text_item": {"text": text}}],
        }

    def _wait_for_text(self, needle, timeout=2):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(needle in text for text in self.bot.sent_text):
                return True
            self.bot.sent_event.wait(0.05)
            self.bot.sent_event.clear()
        return False

    def test_stop_suppresses_buffered_turn_output(self):
        self.wechat.on_message(self.bot, self._message("do work"))
        self.assertTrue(self.wechat.agent.put_called.wait(1), "worker did not start")

        self.wechat.on_message(self.bot, self._message("/stop"))
        self.assertTrue(self.wechat.agent.abort_called)

        self.wechat.agent.display_queue.put({
            "turn": 2,
            "outputs": ["LEAK_AFTER_STOP", "partial"],
        })
        self.wechat.agent.display_queue.put({
            "done": "final",
            "outputs": ["LEAK_AFTER_STOP"],
        })

        self.assertTrue(self._wait_for_text("已停止"), "stop acknowledgement was not sent")
        self.assertFalse(
            any("LEAK_AFTER_STOP" in text for text in self.bot.sent_text),
            f"buffered output leaked after stop: {self.bot.sent_text}",
        )

    def test_stop_does_not_send_files_from_cancelled_result(self):
        payload = self.test_home / "cancelled.txt"
        payload.write_text("cancelled", encoding="utf-8")

        self.wechat.on_message(self.bot, self._message("make a file"))
        self.assertTrue(self.wechat.agent.put_called.wait(1), "worker did not start")

        self.wechat.on_message(self.bot, self._message("/stop"))
        self.wechat.agent.display_queue.put({
            "done": f"[FILE:{payload}]",
            "outputs": [],
        })

        self.assertTrue(self._wait_for_text("已停止"), "stop acknowledgement was not sent")
        time.sleep(0.05)
        self.assertEqual([], self.bot.sent_files)

    def test_idle_stop_does_not_cancel_the_next_task(self):
        self.wechat.on_message(self.bot, self._message("/stop"))
        self.assertFalse(self.wechat.agent.is_running)
        self.bot.sent_text.clear()
        self.bot.sent_event.clear()

        self.wechat.on_message(self.bot, self._message("next task"))
        self.assertTrue(self.wechat.agent.put_called.wait(1), "next worker did not start")
        self.wechat.agent.display_queue.put({
            "done": "NEXT_TASK_OK",
            "outputs": ["NEXT_TASK_OK"],
        })

        self.assertTrue(self._wait_for_text("NEXT_TASK_OK"), self.bot.sent_text)
        self.assertFalse(any("已停止" in text for text in self.bot.sent_text))

    def test_abort_flag_is_armed_before_agent_abort(self):
        self.wechat.on_message(self.bot, self._message("race task"))
        self.assertTrue(self.wechat.agent.put_called.wait(1), "worker did not start")
        observed = []
        self.wechat.agent.abort_observer = lambda: observed.append(bool(self.wechat._task_aborted.get(self.uid)))

        self.wechat.on_message(self.bot, self._message("/stop"))

        self.assertEqual([True], observed)


if __name__ == "__main__":
    unittest.main()
