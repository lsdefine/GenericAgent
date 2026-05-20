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

    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:
        def __init__(self, rows):
            self.inline_keyboard = rows

    telegram.BotCommand = object
    telegram.InlineKeyboardButton = InlineKeyboardButton
    telegram.InlineKeyboardMarkup = InlineKeyboardMarkup

    constants = types.ModuleType("telegram.constants")
    constants.ChatType = types.SimpleNamespace(PRIVATE="private")
    constants.MessageLimit = types.SimpleNamespace(MAX_TEXT_LENGTH=4096)
    constants.ParseMode = types.SimpleNamespace(MARKDOWN_V2="MarkdownV2")

    error = types.ModuleType("telegram.error")
    error.RetryAfter = type("RetryAfter", (Exception,), {})

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

    class FakeAgent:
        def __init__(self):
            self.verbose = False
            self.inc_out = False
            self.llm_no = 0
            self.prompts = []

        def list_llms(self):
            return [
                (0, "gpt-4o", self.llm_no == 0),
                (1, "claude-sonnet", self.llm_no == 1),
            ]

        def next_llm(self, n):
            if n not in (0, 1):
                raise IndexError(n)
            self.llm_no = n

        def get_llm_name(self):
            return self.list_llms()[self.llm_no][1]

        def put_task(self, prompt, source=None):
            self.prompts.append((prompt, source))
            return object()

    agentmain = types.ModuleType("agentmain")
    agentmain.GeneraticAgent = FakeAgent

    chatapp_common = types.ModuleType("chatapp_common")
    chatapp_common.FILE_HINT = "FILE_HINT"
    chatapp_common.HELP_TEXT = ""
    chatapp_common.TELEGRAM_MENU_COMMANDS = []
    chatapp_common.clean_reply = lambda text: text
    chatapp_common.ensure_single_instance = lambda *args, **kwargs: None
    chatapp_common.extract_files = lambda text: []
    chatapp_common.format_restore = lambda: (([], "", 0), None)
    chatapp_common.redirect_log = lambda *args, **kwargs: None
    chatapp_common.require_runtime = lambda *args, **kwargs: None
    chatapp_common.split_text = lambda text, limit: [text]

    continue_cmd = types.ModuleType("continue_cmd")
    continue_cmd.handle_frontend_command = lambda *args, **kwargs: ""
    continue_cmd.reset_conversation = lambda *args, **kwargs: ""

    btw_cmd = types.ModuleType("btw_cmd")
    btw_cmd.handle_frontend_command = lambda *args, **kwargs: ""

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
            "btw_cmd": btw_cmd,
            "llmcore": llmcore,
        }
    )


_install_import_stubs()
tgapp = importlib.import_module("tgapp")


class FakeMessage:
    text = "/llm"

    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.replies.append(types.SimpleNamespace(text=text, reply_markup=reply_markup))
        return self.replies[-1]


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answers = []
        self.edited_text = None
        self.edited_markup = None

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None):
        self.edited_text = text
        self.edited_markup = reply_markup

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edited_markup = reply_markup


class FakeUpdate:
    effective_user = types.SimpleNamespace(id=1)

    def __init__(self, query=None, message=None):
        self.callback_query = query
        self.message = message


class TelegramInlineSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tgapp._ask_menu_store.clear()
        tgapp._llm_menu_store.clear()
        tgapp.agent = tgapp.GeneraticAgent()

        async def fake_stream(*args, **kwargs):
            return None

        self._original_stream = tgapp._stream
        tgapp._stream = fake_stream

    async def asyncTearDown(self):
        tgapp._stream = self._original_stream

    def test_multi_ask_markup_tracks_selected_items(self):
        markup = tgapp._build_ask_user_markup(
            "menu",
            ["Python", "Go"],
            multi=True,
            selected_indexes=[0],
        )

        rows = markup.inline_keyboard
        self.assertEqual(rows[0][0].text, "✓ Python")
        self.assertEqual(rows[0][0].callback_data, "ask:menu:toggle:0")
        self.assertEqual(rows[1][0].callback_data, "ask:menu:toggle:1")
        self.assertEqual(rows[2][0].callback_data, "ask:menu:done")

    async def test_multi_ask_done_submits_joined_selection(self):
        tgapp._ask_menu_store["menu"] = {
            "question": "Pick [多选]",
            "candidates": ["Python", "JavaScript", "Go"],
            "multi": True,
            "selected": [0, 2],
        }
        query = FakeQuery("ask:menu:done")
        ctx = types.SimpleNamespace(user_data={})

        await tgapp.handle_ask_callback(FakeUpdate(query=query), ctx)

        self.assertNotIn("menu", tgapp._ask_menu_store)
        self.assertIn("Python; Go", query.edited_text)
        self.assertEqual(tgapp.agent.prompts[-1][0], "FILE_HINT\n\nPython; Go")
        self.assertEqual(tgapp.agent.prompts[-1][1], "telegram")

    async def test_llm_command_sends_inline_keyboard_and_callback_switches(self):
        message = FakeMessage()

        await tgapp.cmd_llm(FakeUpdate(message=message), types.SimpleNamespace())

        self.assertEqual(message.replies[0].text, tgapp._LLM_MENU_PROMPT)
        menu_id = next(iter(tgapp._llm_menu_store))
        rows = message.replies[0].reply_markup.inline_keyboard
        self.assertEqual(rows[1][0].callback_data, f"llm:{menu_id}:1")

        query = FakeQuery(f"llm:{menu_id}:1")
        await tgapp.handle_llm_callback(
            FakeUpdate(query=query),
            types.SimpleNamespace(user_data={}),
        )

        self.assertEqual(tgapp.agent.llm_no, 1)
        self.assertIn("claude-sonnet", query.edited_text)
        self.assertNotIn(menu_id, tgapp._llm_menu_store)


if __name__ == "__main__":
    unittest.main()
