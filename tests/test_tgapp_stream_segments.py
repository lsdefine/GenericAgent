import importlib
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = REPO_ROOT / "frontends"
for path in (str(REPO_ROOT), str(FRONTENDS)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _install_import_stubs():
    telegram = types.ModuleType("telegram")
    telegram.BotCommand = object
    telegram.InlineKeyboardButton = object
    telegram.InlineKeyboardMarkup = object

    constants = types.ModuleType("telegram.constants")

    class ChatType:
        PRIVATE = "private"

    class MessageLimit:
        MAX_TEXT_LENGTH = 4096

    class ParseMode:
        MARKDOWN_V2 = "MarkdownV2"

    constants.ChatType = ChatType
    constants.MessageLimit = MessageLimit
    constants.ParseMode = ParseMode

    error = types.ModuleType("telegram.error")

    class RetryAfter(Exception):
        def __init__(self, retry_after=0):
            super().__init__("retry after")
            self.retry_after = retry_after

    error.RetryAfter = RetryAfter

    ext = types.ModuleType("telegram.ext")
    ext.ApplicationBuilder = object
    ext.CallbackQueryHandler = object
    ext.MessageHandler = object
    ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    ext.filters = types.SimpleNamespace(
        COMMAND=object(),
        PHOTO=object(),
        TEXT=object(),
        Document=types.SimpleNamespace(ALL=object()),
    )

    helpers = types.ModuleType("telegram.helpers")
    helpers.escape_markdown = lambda text, version=2, entity_type=None: text or ""

    request = types.ModuleType("telegram.request")
    request.HTTPXRequest = object

    agentmain = types.ModuleType("agentmain")

    class GeneraticAgent:
        def __init__(self):
            self.verbose = False
            self.inc_out = False

    agentmain.GeneraticAgent = GeneraticAgent

    chatapp_common = types.ModuleType("chatapp_common")
    chatapp_common.FILE_HINT = ""
    chatapp_common.HELP_TEXT = ""
    chatapp_common.TELEGRAM_MENU_COMMANDS = []
    chatapp_common.clean_reply = lambda text: text
    chatapp_common.ensure_single_instance = lambda *args, **kwargs: None
    chatapp_common.extract_files = lambda text: []
    chatapp_common.format_restore = lambda: (([], "", 0), None)
    chatapp_common.redirect_log = lambda *args, **kwargs: None
    chatapp_common.require_runtime = lambda *args, **kwargs: None
    chatapp_common.split_text = lambda text, limit: [text[i : i + limit] for i in range(0, len(text), limit)]

    continue_cmd = types.ModuleType("continue_cmd")
    continue_cmd.handle_frontend_command = lambda *args, **kwargs: ""
    continue_cmd.reset_conversation = lambda *args, **kwargs: ""

    llmcore = types.ModuleType("llmcore")
    llmcore.mykeys = {}

    sys.modules.update(
        {
            "telegram": telegram,
            "telegram.constants": constants,
            "telegram.error": error,
            "telegram.ext": ext,
            "telegram.helpers": helpers,
            "telegram.request": request,
            "agentmain": agentmain,
            "chatapp_common": chatapp_common,
            "continue_cmd": continue_cmd,
            "llmcore": llmcore,
        }
    )


_install_import_stubs()
tgapp = importlib.import_module("tgapp")


class FakeChat:
    type = tgapp.ChatType.PRIVATE
    id = 123


class FakeMessage:
    _next_id = 1

    def __init__(self, root, text=""):
        self.root = root
        self.chat = FakeChat()
        self.message_id = FakeMessage._next_id
        FakeMessage._next_id += 1
        self.text = text
        self.parse_mode = None
        self.edit_count = 0
        self.deleted = False

    async def reply_text(self, text, parse_mode=None):
        msg = FakeMessage(self.root, text)
        msg.parse_mode = parse_mode
        self.root.messages.append(msg)
        return msg

    async def edit_text(self, text, parse_mode=None):
        self.text = text
        self.parse_mode = parse_mode
        self.edit_count += 1
        return self

    async def delete(self):
        self.deleted = True


class FakeRoot(FakeMessage):
    def __init__(self):
        self.root = self
        self.chat = FakeChat()
        self.message_id = 0
        self.messages = []


class TelegramStreamSegmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_text_keeps_primary_live_message_when_text_overflows(self):
        root = FakeRoot()
        session = tgapp._TelegramStreamSession(root)
        primary = await root.reply_text("thinking...")

        live_msg = await session._edit_text(primary, "a" * 5000, wait_retry=False)

        self.assertIs(live_msg, primary)
        self.assertEqual(len(root.messages), 2)
        self.assertEqual(root.messages[0], primary)
        self.assertEqual(primary.text, "a" * 4096)
        self.assertEqual(root.messages[1].text, "a" * 904)

    async def test_repeated_overflow_edit_reuses_overflow_message_without_duplicates(self):
        root = FakeRoot()
        session = tgapp._TelegramStreamSession(root)
        primary = await root.reply_text("thinking...")

        live_msg = await session._edit_text(primary, "a" * 5000, wait_retry=False)
        overflow = root.messages[1]
        live_msg = await session._edit_text(live_msg, "b" * 6000, wait_retry=False)

        self.assertIs(live_msg, primary)
        self.assertEqual(len(root.messages), 2)
        self.assertIs(root.messages[1], overflow)
        self.assertEqual(primary.text, "b" * 4096)
        self.assertEqual(overflow.text, "b" * 1904)
        self.assertEqual(primary.edit_count, 2)
        self.assertEqual(overflow.edit_count, 1)

    async def test_shrinking_edited_text_deletes_stale_overflow_segment(self):
        root = FakeRoot()
        session = tgapp._TelegramStreamSession(root)
        primary = await root.reply_text("thinking...")

        live_msg = await session._edit_text(primary, "a" * 5000, wait_retry=False)
        overflow = root.messages[1]
        live_msg = await session._edit_text(live_msg, "short", wait_retry=False)

        self.assertIs(live_msg, primary)
        self.assertEqual(primary.text, "short")
        self.assertTrue(overflow.deleted)
        self.assertEqual(session._edit_overflow_msgs, {})


if __name__ == "__main__":
    unittest.main()
