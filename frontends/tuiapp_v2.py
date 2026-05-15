"""GenericAgent TUI v2 — Textual app with refined visual style.

Run from project root:
    python frontends/tuiapp_v2.py

Visual design carried from temp/GA_tui 设计/tui_demo.py;
functionality migrated from frontends/tuiapp.py plus new commands:
- /btw       — side question (subagent, doesn't interrupt main)
- /continue  — list / restore historical sessions
- /export    — export last reply (clip / file / all)
- /restore   — restore last model_responses log
"""
from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Callable, Optional

try:
    from rich.markdown import Markdown
    from rich.table import Table
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.message import Message
    from textual.screen import ModalScreen
    from textual.widgets import OptionList, Static, TextArea
    from textual.widgets.option_list import Option
except ModuleNotFoundError as exc:
    print(f"Missing dependency: {exc.name}. Install Textual: pip install textual",
          file=sys.stderr)
    raise SystemExit(2) from exc


# Strip terminal control sequences from subprocess stdout but keep SGR color codes,
# otherwise Text.from_ansi loses color downstream.
_ANSI_CONTROL_RE = re.compile(
    r"\x1b\[\?[\d;]*[hl]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[=>]"
)


def fold_turns(text: str) -> list[dict]:
    placeholders: list[str] = []
    def stash(m):
        placeholders.append(m.group(0))
        return f"\x00PH{len(placeholders) - 1}\x00"
    safe = re.sub(r"`{4,}.*?`{4,}", stash, text, flags=re.DOTALL)
    safe = re.sub(r"`{4,}[^`].*$", stash, safe, flags=re.DOTALL)
    parts = re.split(r"(\**LLM Running \(Turn \d+\) \.\.\.\**)", safe)
    parts = [re.sub(r"\x00PH(\d+)\x00", lambda m: placeholders[int(m.group(1))], p) for p in parts]
    if len(parts) < 4:
        return [{"type": "text", "content": text}]
    segs: list[dict] = []
    if parts[0].strip():
        segs.append({"type": "text", "content": parts[0]})
    turns = [(parts[i], parts[i + 1] if i + 1 < len(parts) else "")
             for i in range(1, len(parts), 2)]
    for idx, (marker, content) in enumerate(turns):
        if idx == len(turns) - 1:
            segs.append({"type": "text", "content": marker + content})
            continue
        cleaned = re.sub(r"`{3,}.*?`{3,}|<thinking>.*?</thinking>", "", content, flags=re.DOTALL)
        ms = re.findall(r"<summary>\s*((?:(?!<summary>).)*?)\s*</summary>", cleaned, re.DOTALL)
        title = (ms[0].strip().split("\n", 1)[0] if ms
                 else re.sub(r",?\s*args:.*$", "", cleaned.strip().split("\n", 1)[0] or marker.strip("*")))
        if len(title) > 72: title = title[:72] + "..."
        segs.append({"type": "fold", "title": title, "content": content})
    return segs


def render_folded_text(text: str) -> str:
    out = []
    for seg in fold_turns(text):
        out.append(f"\n▸ {seg.get('title') or 'completed turn'}\n\n"
                   if seg["type"] == "fold" else seg.get("content", ""))
    return "".join(out)


class HardBreakMarkdown(Markdown):
    # softbreak → hardbreak so multi-line agent logs aren't collapsed into one line.
    def __init__(self, markup, **kwargs):
        super().__init__(markup, **kwargs)
        self._soft_to_hard(self.parsed)

    @staticmethod
    def _soft_to_hard(tokens):
        for tok in tokens:
            if tok.type == "softbreak":
                tok.type = "hardbreak"
            if tok.children:
                HardBreakMarkdown._soft_to_hard(tok.children)

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
FRONTENDS_DIR = os.path.dirname(os.path.abspath(__file__))
if FRONTENDS_DIR not in sys.path:
    sys.path.insert(0, FRONTENDS_DIR)

# Side-effect imports activate /btw + /continue monkey-patches.
import chatapp_common  # noqa: F401
from chatapp_common import format_restore
from btw_cmd import handle_frontend_command as btw_handle
from continue_cmd import list_sessions as continue_list, extract_ui_messages as continue_extract
from export_cmd import last_assistant_text, export_to_temp, wrap_for_clipboard

AgentFactory = Callable[[], Any]

# ---------- colors ----------
C_FG     = "#c9d1d9"
C_MUTED  = "#8b949e"
C_DIM    = "#6e7681"
C_SEL_BG = "#161b22"
C_GREEN  = "#7ec27e"
C_BLUE   = "#82adcf"
C_PURPLE = "#b596d8"


@dataclass
class ChatMessage:
    role: str            # 'user' | 'assistant' | 'system'
    content: str
    task_id: Optional[int] = None
    done: bool = True
    # Interactive choice support
    kind: str = "text"   # "text" | "choice"
    choices: list = field(default_factory=list)   # [(label, value), ...]
    on_select: Optional[Callable] = field(default=None, repr=False)
    selected_label: Optional[str] = None
    image_paths: list[str] = field(default_factory=list)
    _role_widget: Any = field(default=None, repr=False)
    _hint_widget: Any = field(default=None, repr=False)
    _body_widget: Any = field(default=None, repr=False)
    _cached_body: Any = field(default=None, repr=False)
    _cache_key: tuple = field(default=(), repr=False)


@dataclass
class AgentSession:
    agent_id: int
    name: str
    agent: Any
    thread: Optional[threading.Thread] = None
    status: str = "idle"
    messages: list[ChatMessage] = field(default_factory=list)
    task_seq: int = 0
    current_task_id: Optional[int] = None
    current_display_queue: Optional[queue.Queue] = None
    buffer: str = ""


def default_agent_factory() -> Any:
    from agentmain import GenericAgent
    agent = GenericAgent()
    agent.inc_out = True
    return agent


# ---------- commands ----------
COMMANDS = [
    ("/help",     "",                 "显示帮助"),
    ("/status",   "",                 "查看会话状态"),
    ("/sessions", "",                 "列出所有会话"),
    ("/new",      "[name]",           "新建并切换到新会话"),
    ("/switch",   "<id|name>",        "切换到指定会话"),
    ("/close",    "",                 "关闭当前会话"),
    ("/branch",   "[name]",           "从当前会话分支"),
    ("/rewind",   "[n]",              "回退最近 n 轮"),
    ("/clear",    "",                 "清空显示（不动 LLM 历史）"),
    ("/stop",     "",                 "中止当前任务"),
    ("/llm",      "[n]",              "查看 / 切换模型"),
    ("/btw",      "<question>",       "side question — 不打断主 agent"),
    ("/continue", "[n]",              "列出 / 恢复历史会话"),
    ("/export",   "clip|<file>|all",  "导出最后回复"),
    ("/restore",  "",                 "恢复上次模型响应日志"),
    ("/quit",     "",                 "退出"),
]


# ---------- widgets ----------
class ChoiceList(OptionList):
    BINDINGS = [*OptionList.BINDINGS,
                Binding("right", "select", "Select", show=False),
                Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, msg: "ChatMessage", **kwargs):
        super().__init__(**kwargs)
        self.msg = msg

    def action_cancel(self) -> None:
        try:
            self.app._cancel_choice(self.msg)
        except Exception:
            pass


class SelectableStatic(Static):
    # Widget.get_selection returns None for non-Text/Content visuals; fall back to render_line.
    def get_selection(self, selection):
        result = super().get_selection(selection)
        if result is not None:
            return result
        height = self.size.height
        if height <= 0:
            return None
        lines = []
        for y in range(height):
            try:
                strip = self.render_line(y)
            except Exception:
                lines.append("")
                continue
            lines.append("".join(seg.text for seg in strip))
        if not lines:
            return None
        return selection.extract("\n".join(lines)), "\n"



def _read_clipboard_text() -> str:
    try:
        import tkinter as tk
        r = tk.Tk(); r.withdraw()
        try:
            return r.clipboard_get() or ""
        finally:
            r.destroy()
    except Exception:
        return ""


def _save_clipboard_image() -> Optional[str]:
    try:
        from PIL import ImageGrab, Image
    except Exception:
        return None
    try:
        data = ImageGrab.grabclipboard()
    except Exception:
        return None
    if data is None:
        return None
    try:
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str) and os.path.isfile(item):
                    return item
            return None
        if isinstance(data, Image.Image):
            out_dir = os.path.join(tempfile.gettempdir(), "genericagent_tui_clipboard")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"clipboard_{int(time.time() * 1000)}.png")
            data.save(path, "PNG")
            return path
    except Exception:
        return None
    return None


class InputArea(TextArea):
    _PASTE_RE = re.compile(r'\[Pasted text #(\d+) \+\d+ lines\]')
    # `[Image #N]` is the folded form; expand_placeholders restores the raw path at submit time.
    # The longer `[Image #N: ...]` form is tolerated for backward compatibility only.
    _IMAGE_RE = re.compile(r'\[Image #(\d+)(?::[^\]]*)?\]')

    BINDINGS = [
        Binding("ctrl+j",      "newline", "Newline", show=False),
        Binding("ctrl+enter",  "newline", "Newline", show=False),
        Binding("shift+enter", "newline", "Newline", show=False),
        Binding("ctrl+v",      "paste", "Paste", show=False),
        # macOS muscle-memory alias: most terminals swallow Cmd+V (forward via bracketed
        # paste → _on_paste); this only hits if the terminal forwards Cmd as a key.
        Binding("cmd+v",       "paste", "Paste", show=False),
        # Ctrl+U: readline-style kill-line, repurposed here to clear the whole input.
        Binding("ctrl+u",      "clear_input", "ClearInput", show=False),
    ]

    def action_noop(self) -> None:
        pass

    def action_clear_input(self) -> None:
        self.reset()
        self._history_index = -1
        self._history_stash = ""
        try:
            self.app._hide_palette()
        except Exception:
            pass
        try:
            self.app._resize_input(self)
        except Exception:
            pass

    def _insert_via_keyboard(self, text: str) -> None:
        result = self._replace_via_keyboard(text, *self.selection)
        if result:
            self.move_cursor(result.end_location)
            self.focus()
            try:
                self.app._resize_input(self)
            except Exception:
                pass

    def _paste_image_from_clipboard(self) -> bool:
        path = _save_clipboard_image()
        if not path:
            return False
        self._paste_counter += 1
        sid = self._paste_counter
        self._pastes[sid] = path
        self._insert_via_keyboard(f"[Image #{sid}]")
        return True

    def _insert_paste_text(self, text: str) -> None:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        line_count = len(text.splitlines()) or 1
        if line_count > 2:
            self._paste_counter += 1
            sid = self._paste_counter
            self._pastes[sid] = text
            text = f"[Pasted text #{sid} +{line_count} lines]"
        self._insert_via_keyboard(text)

    def action_paste(self) -> None:
        if self.read_only or self._paste_image_from_clipboard():
            return
        text = _read_clipboard_text() or getattr(self.app, "clipboard", "")
        if text:
            self._insert_paste_text(text)

    def action_paste_image(self) -> None:
        self._paste_image_from_clipboard()

    async def _on_click(self, event: events.Click) -> None:
        if getattr(event, "button", 0) == 3 and not self.read_only:
            self.action_paste()
            event.stop(); event.prevent_default()

    class Submitted(Message):
        def __init__(self, input_area: "InputArea", value: str) -> None:
            super().__init__()
            self.input_area = input_area
            self.value = value

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pastes: dict[int, str] = {}
        self._paste_counter = 0
        self._input_history: list[str] = []
        self._history_index: int = -1         # -1 means not browsing
        self._history_stash: str = ""
        self._HISTORY_MAX = 200

    def expand_placeholders(self, text: str) -> str:
        def repl_paste(m):
            sid = int(m.group(1))
            return self._pastes.get(sid, m.group(0))
        def repl_image(m):
            sid = int(m.group(1))
            return self._pastes.get(sid, m.group(0))
        text = self._PASTE_RE.sub(repl_paste, text)
        return self._IMAGE_RE.sub(repl_image, text)

    # ---- history public API ----
    def record_history(self, raw_text: str) -> None:
        stripped = raw_text.strip()
        if not stripped:
            return
        if not (self._input_history and self._input_history[-1] == stripped):
            self._input_history.append(stripped)
            if len(self._input_history) > self._HISTORY_MAX:
                self._input_history = self._input_history[-self._HISTORY_MAX:]
        self._history_index = -1
        self._history_stash = ""

    def _suppress_palette_next_change(self) -> None:
        # Single-shot guard against re-opening the palette during programmatic text changes.
        self.app._suppress_palette_open = True

    def _history_up(self) -> bool:
        if not self._input_history:
            return False
        if self._history_index == -1:
            self._history_stash = self.text
            self._history_index = len(self._input_history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        else:
            return True  # already at oldest — absorb the key
        self._suppress_palette_next_change()
        self.text = self._input_history[self._history_index]
        return True

    def _history_down(self) -> bool:
        if self._history_index == -1:
            return False
        if self._history_index < len(self._input_history) - 1:
            self._history_index += 1
            new_text = self._input_history[self._history_index]
        else:
            self._history_index = -1
            new_text = self._history_stash
        self._suppress_palette_next_change()
        self.text = new_text
        return True

    def reset(self) -> None:
        self.text = ""
        self._pastes.clear()
        self._paste_counter = 0
        self._history_index = -1
        self._history_stash = ""

    def action_newline(self) -> None:
        self._insert_via_keyboard("\n")

    async def _on_paste(self, event: events.Paste) -> None:
        # Terminal Ctrl+V in bracketed-paste mode lands here, bypassing action_paste.
        if self.read_only:
            return
        if self._paste_image_from_clipboard():
            event.stop(); event.prevent_default(); return
        self._insert_paste_text(event.text)
        event.stop(); event.prevent_default()

    async def _on_key(self, event: events.Key) -> None:
        # 1) command palette routing
        try:
            palette = self.app.query_one("#palette", OptionList)
        except Exception:
            palette = None
        if palette is not None and palette.has_class("-visible"):
            routes = {"up": palette.action_cursor_up, "down": palette.action_cursor_down}
            if event.key in {"enter", "right"} and palette.highlighted is not None:
                routes[event.key] = palette.action_select
            elif event.key == "left":
                routes["left"] = self.app._hide_palette
            fn = routes.get(event.key)
            if fn:
                fn(); event.stop(); event.prevent_default(); return
        # 2) inline ChoiceList routing — borrow arrow keys without moving focus.
        choice = getattr(self.app, "_active_choice", lambda: None)()
        if choice is not None:
            if event.key == "up":
                choice.action_cursor_up(); event.stop(); event.prevent_default(); return
            if event.key == "down":
                choice.action_cursor_down(); event.stop(); event.prevent_default(); return
            if event.key in ("enter", "right") and choice.highlighted is not None:
                choice.action_select(); event.stop(); event.prevent_default(); return
            if event.key == "escape":
                self.app._cancel_choice(choice.msg); event.stop(); event.prevent_default(); return
        # 3) history browse: only at (0,0) for up / end-of-text for down, so in-line
        #    cursor movement is preserved.
        if event.key == "up" and self.cursor_location == (0, 0):
            if self._history_up():
                event.stop(); event.prevent_default(); return
        if event.key == "down":
            row, col = self.cursor_location
            lines = self.text.split("\n")
            if row == len(lines) - 1 and col == len(lines[-1]):
                if self._history_down():
                    event.stop(); event.prevent_default(); return
        if event.key == "enter":  # newline keys are bound separately
            event.stop(); event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        if self._history_index != -1 and event.key not in ("up", "down", "left", "right"):
            self._history_index = -1
        await super()._on_key(event)


# ---------- top bar ----------
def render_topbar(session_name: str, status: str, model: str, tasks_running: int,
                  fold_mode: bool = True) -> Table:
    t = Table.grid(expand=True)
    t.add_column(ratio=1, justify="left")
    t.add_column(ratio=1, justify="center")
    t.add_column(ratio=1, justify="right")

    left = Text()
    left.append("GenericAgent", style=f"bold {C_GREEN}")
    left.append("    ")
    left.append("session: ", style=C_MUTED)
    left.append(session_name, style=C_FG)
    left.append("    ")
    dot_color = C_GREEN if status == "running" else C_DIM
    left.append("● ", style=dot_color)
    left.append(status, style=C_MUTED)
    if fold_mode:
        left.append("    ")
        left.append("▾ fold", style=C_DIM)

    mid = Text()
    mid.append("model: ", style=C_MUTED)
    mid.append(model or "?", style=C_FG)
    mid.append("  ·  ", style=C_DIM)
    mid.append("tasks: ", style=C_MUTED)
    mid.append(str(tasks_running), style=C_FG)

    right = Text()
    right.append(time.strftime("%H:%M:%S"), style=C_FG)

    t.add_row(left, mid, right)
    return t


def render_bottombar(quit_armed: bool = False) -> Table:
    t = Table.grid(expand=True)
    t.add_column(justify="left")
    left = Text()
    if quit_armed:
        left.append("再按 Ctrl+C 退出", style=f"bold {C_GREEN}")
    else:
        pairs = [("Enter", "发送"), ("Ctrl+N", "新会话"),
                 ("Ctrl+B", "侧栏"), ("Ctrl+C", "停止/退出"),
                 ("/", "命令面板"), ("Ctrl+/", "快捷键帮助")]
        for i, (k, d) in enumerate(pairs):
            if i: left.append("    ")
            left.append(k, style=C_GREEN if k in ("/", "Ctrl+/") else C_FG)
            left.append(" ")
            left.append(d, style=C_MUTED)
    t.add_row(left)
    return t


# ---------- sidebar ----------
def _truncate(text: str, max_w: int) -> str:
    import unicodedata
    w, out = 0, []
    for ch in text:
        wch = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + wch > max_w:
            out.append("…"); break
        out.append(ch); w += wch
    return "".join(out)


def _short_age(mtime: float) -> str:
    d = int(time.time() - mtime)
    if d < 60: return f"{d}s"
    if d < 3600: return f"{d // 60}m"
    if d < 86400: return f"{d // 3600}h"
    return f"{d // 86400}d"


def _history_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _sidebar_last_user(sess: AgentSession) -> str:
    # Read from LLM-side history so /clear (display-only) doesn't wipe sidebar preview.
    try:
        history = sess.agent.llmclient.backend.history
    except Exception:
        return ""
    for m in reversed(history):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        text = _history_text(c)
        if text.strip():
            return re.sub(r"\s+", " ", text).strip()
    return ""


def _sidebar_last_summary(sess: AgentSession) -> str:
    try:
        history = sess.agent.llmclient.backend.history
    except Exception:
        return ""
    for m in reversed(history):
        if m.get("role") != "assistant":
            continue
        text = _history_text(m.get("content"))
        if not text:
            continue
        matches = re.findall(r"<summary>\s*(.*?)\s*</summary>", text, re.DOTALL)
        if matches:
            return re.sub(r"\s+", " ", matches[-1]).strip()
    return ""


def render_sidebar(sessions: dict[int, AgentSession], current_id: Optional[int]) -> Table:
    outer = Table.grid(expand=True)
    outer.add_column()

    SEL = f"on {C_SEL_BG}"
    sess_tbl = Table.grid(expand=True)
    sess_tbl.add_column(width=2)
    sess_tbl.add_column(width=2)
    sess_tbl.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
    sess_tbl.add_column(justify="right")
    sess_tbl.add_column(width=2)
    blank = Text("")
    def spacer(style):
        sess_tbl.add_row(blank, blank, blank, blank, blank, style=style)
    def preview(label, txt, style):
        sess_tbl.add_row(blank, blank,
                         Text(f"{label}: {txt}", style=C_DIM, no_wrap=True, overflow="ellipsis"),
                         blank, blank, style=style)
    for sid, sess in sessions.items():
        active = sid == current_id
        style = SEL if active else None
        spacer(style)
        sess_tbl.add_row(
            blank,
            Text("●" if active else "›", style=C_GREEN if active else C_DIM),
            Text(_truncate(f"#{sid} {sess.name}", 16), style=C_GREEN if active else C_MUTED),
            Text(sess.status, style=C_DIM),
            blank, style=style,
        )
        if (q := _sidebar_last_user(sess)): preview("Q", q, style)
        if (s := _sidebar_last_summary(sess)): preview("S", s, style)
        spacer(style)
    outer.add_row(Text("SESSIONS", style=f"bold {C_DIM}"))
    outer.add_row(Text(""))
    outer.add_row(sess_tbl)
    return outer


# ---------- App ----------


class HelpScreen(ModalScreen):
    CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Static {
        width: auto;
        max-width: 80;
        height: auto;
        max-height: 80%;
        background: #21262d;
        border: solid #30363d;
        padding: 1 2;
        color: #c9d1d9;
    }
    """
    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("ctrl+slash", "dismiss", "Close", show=False),
        Binding("ctrl+/", "dismiss", "Close", show=False),
        Binding("ctrl+underscore", "dismiss", "Close", show=False),
        Binding("cmd+slash", "dismiss", "Close", show=False),
        Binding("cmd+/", "dismiss", "Close", show=False),
    ]

    def __init__(self, content) -> None:
        super().__init__()
        self._content = content

    def compose(self) -> ComposeResult:
        yield Static(self._content)


class GenericAgentTUI(App[None]):

    CSS = """
    Screen { background: #0d1117; color: #c9d1d9; }

    #topbar, #bottombar {
        height: 1;
        background: #0d1117;
        padding: 0 2;
    }

    #body { height: 1fr; }

    #sidebar {
        width: 34;
        height: 100%;
        background: #0d1117;
        padding: 1 2;
        border-right: solid #21262d;
    }
    #sidebar.-hidden, #sidebar.-narrow { display: none; }

    #main {
        height: 100%;
        padding: 1 6;
        background: #0d1117;
    }

    #messages {
        height: 1fr;
        background: #0d1117;
        scrollbar-size: 0 0;
    }

    .role {
        height: 1;
        margin-top: 1;
        margin-bottom: 0;
    }
    .msg {
        height: auto;
        margin-bottom: 0;
    }

    #palette {
        height: auto;
        max-height: 8;
        background: #0d1117;
        border: none;
        padding: 0;
        display: none;
        margin-bottom: 1;
        scrollbar-size: 0 0;
    }
    #palette.-visible { display: block; }
    OptionList {
        background: #0d1117;
        border: none;
        padding: 0;
    }
    OptionList > .option-list--option {
        padding: 0 2;
        background: #0d1117;
        color: #c9d1d9;
    }
    OptionList > .option-list--option-highlighted {
        background: #c9d1d9;
        color: #0d1117;
        text-style: bold;
    }

    ChoiceList {
        height: auto;
        max-height: 12;
        background: #0d1117;
        border: none;
        padding: 0;
        margin-bottom: 1;
        scrollbar-size: 0 0;
    }

    #input {
        height: 3;
        min-height: 3;
        max-height: 5;
        background: #161b22;
        border: none;
        margin-bottom: 1;
        padding: 1 2;
        color: #c9d1d9;
        scrollbar-size: 0 0;
    }
    #input:focus { border: none; }
    """

    BINDINGS = [
        Binding("ctrl+c",     "handle_ctrl_c", "Stop/Quit", show=False, priority=True),
        # macOS muscle-memory aliases — only fire if the terminal forwards Cmd as a key
        # (Terminal.app / default iTerm2 swallow them; Ghostty / WezTerm / kitty can forward).
        Binding("cmd+c",      "handle_ctrl_c", "Stop/Quit", show=False, priority=True),
        Binding("ctrl+n",     "new_session",   "New",   show=False),
        Binding("cmd+n",      "new_session",   "New",   show=False),
        Binding("ctrl+b",     "toggle_sidebar","Sidebar", show=False),
        Binding("ctrl+o",     "toggle_fold",   "Fold",  show=False),
        Binding("ctrl+up",    "prev_session",  "Prev",  show=False, priority=True),
        Binding("ctrl+down",  "next_session",  "Next",  show=False, priority=True),
        # Terminals report Ctrl+/ as ctrl+slash or legacy ctrl+_ (ASCII 0x1F); bind both.
        Binding("ctrl+slash", "show_help", "Help", show=False),
        Binding("ctrl+/",     "show_help", "Help", show=False),
        Binding("ctrl+underscore", "show_help", "Help", show=False),
        Binding("cmd+slash",  "show_help", "Help", show=False),
        Binding("cmd+/",      "show_help", "Help", show=False),
        Binding("escape",     "escape",        "Close", show=False),
        Binding("tab",        "complete_command", "Complete", show=False, priority=True),
    ]

    def __init__(self, agent_factory: Optional[AgentFactory] = None) -> None:
        super().__init__()
        self.agent_factory: AgentFactory = agent_factory or default_agent_factory
        self.sessions: dict[int, AgentSession] = {}
        self.current_id: Optional[int] = None
        self._ids = count(1)
        self._suppress_palette_open = False
        self.fold_mode: bool = True
        self._last_size: tuple[int, int] = (-1, -1)
        self._resize_timer = None
        self._quit_armed: bool = False
        self._quit_timer = None
        self._handlers: dict = {
            "help": self._cmd_help, "status": self._cmd_status, "sessions": self._cmd_status,
            "new": self._cmd_new, "switch": self._cmd_switch, "close": self._cmd_close,
            "branch": self._cmd_branch, "rewind": self._cmd_rewind, "clear": self._cmd_clear,
            "stop": self._cmd_stop, "llm": self._cmd_llm, "export": self._cmd_export,
            "restore": self._cmd_restore, "btw": self._cmd_btw, "continue": self._cmd_continue,
            "quit": self._cmd_quit, "exit": self._cmd_quit,
        }

    def compose(self) -> ComposeResult:
        yield Static("", id="topbar")
        with Horizontal(id="body"):
            yield Static("", id="sidebar")
            with Vertical(id="main"):
                yield VerticalScroll(id="messages")
                yield OptionList(id="palette")
                yield InputArea(
                    "",
                    id="input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    compact=True,
                    highlight_cursor_line=False,
                    placeholder="输入指令或问题... (Enter 发送, Ctrl+J 换行, / 唤起命令面板)",
                )
        yield Static(render_bottombar(), id="bottombar")

    def on_mount(self) -> None:
        self.add_session("main")
        self._system("Welcome to GenericAgent TUI. 按 / 唤起命令面板，Ctrl+N 新建会话。")
        self.query_one("#input", InputArea).focus()
        self.set_interval(0.5, self._tick)
        self._patch_auto_scroll_for_selection()
        self._apply_responsive_layout()
        # Disable alternate scroll mode (?1007). Textual enables ?1006 SGR mouse but doesn't
        # turn off ?1007, which on macOS Terminal / iTerm2 makes the wheel emit both mouse
        # events and ↑/↓ keys — triggering InputArea history nav.
        try:
            sys.stdout.write("\x1b[?1007l"); sys.stdout.flush()
        except Exception:
            pass

    def _tick(self) -> None:
        # 0.5s poll: refresh clock + detect resizes Windows misses (snap, fullscreen).
        self._refresh_topbar()
        size = (self.size.width, self.size.height)
        if size != self._last_size:
            self._last_size = size
            self._apply_responsive_layout()

    def _patch_auto_scroll_for_selection(self) -> None:
        # Make selection-drag into #input still scroll #messages: include _select_start as a
        # candidate source, and trigger when the mouse leaves the scrollable above or below.
        from textual._auto_scroll import get_auto_scroll_regions
        from textual.geometry import Offset
        from textual.widget import Widget as _W

        screen = self.screen
        app = self

        def patched(select_widget, mouse_coord, delta_y):
            if not app.ENABLE_SELECT_AUTO_SCROLL:
                return
            if screen._auto_select_scroll_timer is None and abs(delta_y) < 1:
                return
            mouse_x, mouse_y = mouse_coord
            mouse_offset = Offset(int(mouse_x), int(mouse_y))
            scroll_lines = app.SELECT_AUTO_SCROLL_LINES

            candidates = [select_widget]
            # Textual 8.2.6 renamed _select_start to _select_state (SelectState.start.container).
            select_state = getattr(screen, "_select_state", None)
            if select_state is not None:
                sw = select_state.start.container
            else:
                ss = getattr(screen, "_select_start", None)
                sw = ss[0] if ss is not None else None
            if sw is not None and sw is not select_widget:
                candidates.append(sw)

            for source in candidates:
                for ancestor in source.ancestors_with_self:
                    if not isinstance(ancestor, _W):
                        break
                    if not ancestor.allow_vertical_scroll:
                        continue
                    ar = ancestor.content_region
                    up_r, down_r = get_auto_scroll_regions(ar, auto_scroll_lines=scroll_lines)
                    if mouse_offset in up_r:
                        if ancestor.scroll_y > 0:
                            speed = (scroll_lines - (mouse_y - up_r.y)) / scroll_lines
                            if speed:
                                screen._start_auto_scroll(ancestor, -1, speed)
                                return
                    elif mouse_offset in down_r:
                        if ancestor.scroll_y < ancestor.max_scroll_y:
                            speed = (mouse_y - down_r.y) / scroll_lines
                            if speed:
                                screen._start_auto_scroll(ancestor, +1, speed)
                                return
                    elif mouse_y >= ar.y + ar.height:
                        if ancestor.scroll_y < ancestor.max_scroll_y:
                            screen._start_auto_scroll(ancestor, +1, 1.0)
                            return
                    elif mouse_y < ar.y:
                        if ancestor.scroll_y > 0:
                            screen._start_auto_scroll(ancestor, -1, 1.0)
                            return
            screen._stop_auto_scroll()

        screen._check_auto_scroll = patched

    # ---------------- session management ----------------
    @property
    def current(self) -> AgentSession:
        if self.current_id is None:
            raise RuntimeError("no active session")
        return self.sessions[self.current_id]

    def add_session(self, name: Optional[str] = None) -> AgentSession:
        agent_id = next(self._ids)
        agent = self.agent_factory()
        try: agent.inc_out = True
        except Exception: pass
        sess = AgentSession(agent_id=agent_id, name=name or f"agent-{agent_id}", agent=agent)
        thread = threading.Thread(target=agent.run, name=f"ga-tui-agent-{agent_id}", daemon=True)
        thread.start()
        sess.thread = thread
        self.sessions[agent_id] = sess
        self.current_id = agent_id
        self._refresh_all()
        return sess

    def action_new_session(self) -> None:
        sess = self.add_session()
        self._system(f"Created session #{sess.agent_id} — {sess.name}")

    def action_prev_session(self) -> None:
        ids = sorted(self.sessions.keys())
        if len(ids) <= 1: return
        i = ids.index(self.current_id)
        self.current_id = ids[(i - 1) % len(ids)]
        self._refresh_all()

    def action_next_session(self) -> None:
        ids = sorted(self.sessions.keys())
        if len(ids) <= 1: return
        i = ids.index(self.current_id)
        self.current_id = ids[(i + 1) % len(ids)]
        self._refresh_all()

    def action_handle_ctrl_c(self) -> None:
        # Two-stage quit: when no task is running, first press clears input and arms;
        # second press within 2s exits.
        try:
            selected_text = self.screen.get_selected_text()
        except Exception:
            selected_text = None
        if selected_text:
            try: self.copy_to_clipboard(selected_text)
            except Exception: pass
            self._disarm_quit()
            return
        sess = self.sessions.get(self.current_id)
        if sess is not None and sess.status == "running":
            self._cmd_stop([], "")
            self._disarm_quit()
            return
        if self._quit_armed:
            self.exit()
            return
        try:
            inp = self.query_one("#input", InputArea)
        except Exception:
            inp = None
        if inp is not None and inp.text:
            inp.reset()
            try: self._resize_input(inp)
            except Exception: pass
        self._quit_armed = True
        self._refresh_bottombar()
        if self._quit_timer is not None:
            try: self._quit_timer.stop()
            except Exception: pass
        self._quit_timer = self.set_timer(2.0, self._disarm_quit)

    def _disarm_quit(self) -> None:
        if not self._quit_armed and self._quit_timer is None:
            return
        self._quit_armed = False
        if self._quit_timer is not None:
            try: self._quit_timer.stop()
            except Exception: pass
            self._quit_timer = None
        try: self._refresh_bottombar()
        except Exception: pass

    def on_key(self, event: events.Key) -> None:
        # Any key other than the quit trigger (Ctrl+C or its Cmd+C alias) disarms.
        if self._quit_armed and event.key not in ("ctrl+c", "cmd+c"):
            self._disarm_quit()

    def action_toggle_sidebar(self) -> None:
        self.query_one("#sidebar", Static).toggle_class("-hidden")

    def action_toggle_fold(self) -> None:
        self.fold_mode = not self.fold_mode
        # Invalidate assistant caches: fold state changes the rendered length.
        for sess in self.sessions.values():
            for m in sess.messages:
                if m.role == "assistant":
                    m._cached_body = None
                    m._cache_key = ()
        self._remount_current_session()
        self._refresh_topbar()
        self.notify(f"Fold: {'on' if self.fold_mode else 'off'}", timeout=1)

    def action_escape(self) -> None:
        # Priority chain: pending choice → visible palette → disarm quit.
        choice = self._active_choice()
        if choice is not None:
            self._cancel_choice(choice.msg)
            return
        try:
            palette = self.query_one("#palette", OptionList)
        except Exception:
            palette = None
        if palette is not None and palette.has_class("-visible"):
            self._hide_palette()
            self.query_one("#input", InputArea).focus()
            return
        self._disarm_quit()

    def action_show_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(HelpScreen(self._render_help()))

    def _render_help(self) -> Text:
        rows = [
            ("Enter",                   "发送"),
            ("Ctrl+J / Ctrl+Enter",     "换行（Shift+Enter 同义）"),
            ("Ctrl+C",                  "停止任务 / 空闲时连按两次退出"),
            ("Ctrl+N",                  "新建会话"),
            ("Ctrl+B",                  "切换侧栏"),
            ("Ctrl+↑ / Ctrl+↓",         "切换会话"),
            ("Ctrl+O",                  "折叠 / 展开已完成的轮次"),
            ("Ctrl+U",                  "清空输入框"),
            ("Ctrl+V",                  "粘贴（图片优先）"),
            ("↑ / ↓",                   "输入框：浏览发送历史 / 面板内：移动"),
            ("/",                       "唤起命令面板"),
            ("Tab",                     "命令面板可见时补全"),
            ("Esc",                     "取消选择 / 关闭面板 / 关闭帮助"),
            ("Ctrl+/",                  "显示 / 隐藏本帮助"),
        ]
        t = Text()
        t.append("快捷键帮助\n\n", style=f"bold {C_GREEN}")
        for k, d in rows:
            t.append(f"  {k:<22}", style=C_FG)
            t.append(f"{d}\n", style=C_MUTED)
        t.append("\n按 Esc 或 Ctrl+/ 关闭", style=C_DIM)
        return t

    def action_complete_command(self) -> None:
        palette = self.query_one("#palette", OptionList)
        if not palette.has_class("-visible"):
            return
        inp = self.query_one("#input", InputArea)
        if not inp.has_focus:
            return
        if palette.highlighted is None:
            palette.action_cursor_down()
        if palette.highlighted is not None:
            palette.action_select()

    def on_click(self, event: events.Click) -> None:
        try:
            sidebar = self.query_one("#sidebar", Static)
        except Exception:
            return
        if event.widget is not sidebar:
            return
        # event.y is widget-local (includes padding-top=1). Layout: pad + "SESSIONS" + blank.
        y = event.y - 3
        if y < 0:
            return
        for sid, sess in self.sessions.items():
            rows = 3
            if _sidebar_last_user(sess): rows += 1
            if _sidebar_last_summary(sess): rows += 1
            if y < rows:
                if sid != self.current_id:
                    self.current_id = sid
                    self._refresh_all()
                return
            y -= rows

    # ---------------- input + palette ----------------
    def on_resize(self, event) -> None:
        # Terminals fire multiple resize events per drag; short-circuit on identical size.
        size = (self.size.width, self.size.height)
        if size == self._last_size:
            return
        self._last_size = size
        # Input height auto-fit is latency-sensitive; full layout reflow is debounced 80ms.
        try: self._resize_input(self.query_one("#input", InputArea))
        except Exception: pass
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.08, self._flush_resize)

    def _flush_resize(self) -> None:
        self._resize_timer = None
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        try:
            sidebar = self.query_one("#sidebar", Static)
            main = self.query_one("#main", Vertical)
        except Exception:
            return
        w = self.size.width
        self._last_size = (w, self.size.height)
        # -narrow is auto-hide; -hidden is the Ctrl+B manual toggle. Keep them separate.
        if w < 70:
            sidebar.add_class("-narrow")
        else:
            sidebar.remove_class("-narrow")
            sidebar.styles.width = max(30, min(50, w // 5))
        main.styles.padding = (1, 2) if w < 90 else (1, 6)
        # Padding changes recompute layout asynchronously — defer remount one frame.
        self.call_after_refresh(self._remount_current_session)

    def _remount_current_session(self) -> None:
        if self.current_id is None or not self.is_mounted:
            return
        try:
            container = self.query_one("#messages", VerticalScroll)
        except Exception:
            return
        container.remove_children()
        for m in self.current.messages:
            m._role_widget = None
            m._body_widget = None
            m._hint_widget = None
        for m in self.current.messages:
            self._mount_message(container, m)
        container.scroll_end(animate=False)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "input":
            return
        inp = event.text_area
        self._resize_input(inp)
        val = (inp.text or "").lstrip()
        if self._suppress_palette_open:
            self._suppress_palette_open = False
            self._hide_palette()
            return
        # Only show palette while the first line still looks like a command name.
        first_line = val.split("\n", 1)[0]
        if first_line.startswith("/") and " " not in first_line and "\n" not in val:
            self._populate_palette(first_line)
            self._show_palette()
        else:
            self._hide_palette()

    def _resize_input(self, inp: TextArea) -> None:
        # wrapped_document.height counts soft-wrapped lines; document.line_count only logical.
        try:
            lines = inp.wrapped_document.height or inp.document.line_count
        except Exception:
            lines = inp.document.line_count
        inp.styles.height = min(max(lines, 1), 3) + 2  # +2 for padding 1 2 top/bottom

    def on_input_area_submitted(self, event: "InputArea.Submitted") -> None:
        inp = event.input_area
        if inp.id != "input":
            return
        text = inp.expand_placeholders(event.value).rstrip()
        images = re.findall(r"\[Image #\d+: (.*?)\]", text)
        inp.record_history(event.value)
        inp.reset()
        self._hide_palette()
        self._resize_input(inp)
        if not text:
            return
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0][1:].lower()
            args = parts[1].split() if len(parts) > 1 else []
            if cmd in self._handlers:
                self._dispatch_command(cmd, args, raw=text)
                try:
                    self.query_one("#messages", VerticalScroll).scroll_end(animate=False)
                except Exception:
                    pass
                return
        self.submit_user_message(text, images=images)

    def _show_palette(self) -> None:
        self.query_one("#palette", OptionList).add_class("-visible")

    def _hide_palette(self) -> None:
        self.query_one("#palette", OptionList).remove_class("-visible")

    def _populate_palette(self, value: str) -> None:
        palette = self.query_one("#palette", OptionList)
        prefix = value.strip().lower()
        matches = [c for c in COMMANDS if c[0].startswith(prefix)]
        palette.clear_options()
        if not matches:
            self._hide_palette()
            return
        for cmd, args, desc in matches:
            # No color: reverse-video highlight pairs badly with colored text.
            t = Text()
            t.append(f"{cmd:<11}", style="bold")
            t.append(f"{args:<18}")
            t.append(f"  {desc}")
            palette.add_option(Option(t, id=cmd))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        ol = event.option_list
        if ol.id == "palette":
            cmd_id = event.option.id
            if cmd_id:
                inp = self.query_one("#input", InputArea)
                needs_args = any(c[1] for c in COMMANDS if c[0] == cmd_id)
                self._suppress_palette_open = True
                new_text = cmd_id + (" " if needs_args else "")
                inp.text = new_text
                inp.move_cursor((0, len(new_text)))
            self._hide_palette()
            self.query_one("#input", InputArea).focus()
            return
        if isinstance(ol, ChoiceList):
            self._collapse_choice(ol.msg, event.option_index)
            return

    def _active_choice(self) -> Optional["ChoiceList"]:
        if self.current_id is None:
            return None
        for m in reversed(self.current.messages):
            if m.kind == "choice" and m.selected_label is None:
                w = m._body_widget
                if isinstance(w, ChoiceList):
                    return w
        return None

    def _cancel_choice(self, msg: ChatMessage) -> None:
        for w in (msg._role_widget, msg._hint_widget, msg._body_widget):
            if w is not None:
                try: w.remove()
                except Exception: pass
        msg._role_widget = None
        msg._hint_widget = None
        msg._body_widget = None
        sess = self.sessions.get(self.current_id)
        if sess and msg in sess.messages:
            sess.messages.remove(msg)
        try:
            self.query_one("#input", InputArea).focus()
        except Exception:
            pass

    def _collapse_choice(self, msg: ChatMessage, idx: int) -> None:
        if not (0 <= idx < len(msg.choices)):
            return
        label, value = msg.choices[idx]
        result_text = None
        if msg.on_select:
            try:
                result_text = msg.on_select(value)
            except Exception as e:
                result_text = f"❌ 失败: {type(e).__name__}: {e}"
        display = (result_text or label).strip() or label
        msg.selected_label = display
        msg.content = display
        container = self.query_one("#messages", VerticalScroll)
        body = Text()
        body.append("✓ ", style=C_GREEN)
        body.append(display, style=C_FG)
        new_widget = SelectableStatic(body, classes="msg")
        anchor = msg._hint_widget or msg._body_widget
        if anchor is not None:
            container.mount(new_widget, after=anchor)
        else:
            container.mount(new_widget)
        if msg._hint_widget is not None:
            msg._hint_widget.remove()
            msg._hint_widget = None
        if msg._body_widget is not None:
            msg._body_widget.remove()
        msg._body_widget = new_widget
        self.query_one("#input", InputArea).focus()

    def _dispatch_command(self, cmd: str, args: list[str], raw: str = "") -> None:
        h = self._handlers.get(cmd)
        if h: h(args, raw)

    # ---------------- legacy commands ----------------
    def _cmd_help(self, args, raw):
        lines = [f"{c:<11} {a:<18} {d}" for c, a, d in COMMANDS]
        self._system("命令列表:\n" + "\n".join(lines))

    def _cmd_status(self, args, raw):
        lines = []
        for sid, s in self.sessions.items():
            mark = "*" if sid == self.current_id else " "
            lines.append(f"{mark} #{sid} {s.name} [{s.status}] msgs={len(s.messages)} task={s.current_task_id}")
        self._system("Sessions:\n" + "\n".join(lines))

    def _cmd_new(self, args, raw):
        name = " ".join(args).strip() or None
        sess = self.add_session(name)
        self._system(f"Created session #{sess.agent_id} ({sess.name}).")

    def _cmd_switch(self, args, raw):
        if not args:
            self._system("Usage: /switch <id|name>"); return
        key = " ".join(args)
        target = int(key) if key.isdigit() and int(key) in self.sessions else None
        if target is None:
            for sid, s in self.sessions.items():
                if s.name == key: target = sid; break
        if target is None:
            self._system(f"No session: {key!r}"); return
        self.current_id = target
        self._refresh_all()
        self._system(f"Switched to #{target}.")

    def _cmd_close(self, args, raw):
        if len(self.sessions) <= 1:
            self._system("Cannot close the last session."); return
        del self.sessions[self.current_id]
        self.current_id = next(iter(self.sessions))
        self._refresh_all()

    def _cmd_branch(self, args, raw):
        import copy
        old = self.current
        name = " ".join(args).strip() or f"{old.name}-branch"
        new = self.add_session(name)
        try:
            new.agent.llmclient.backend.history = copy.deepcopy(old.agent.llmclient.backend.history)
        except Exception as e:
            self._system(f"Branch warning: {e}"); return
        # deepcopy(old.messages) trips on mounted Textual widget refs; shallow-copy each
        # ChatMessage and null out widget/cache fields so the new session re-mounts cleanly.
        new.messages = []
        for m in old.messages:
            nm = copy.copy(m)
            nm._role_widget = None
            nm._body_widget = None
            nm._hint_widget = None
            nm._cached_body = None
            nm._cache_key = ()
            new.messages.append(nm)
        new.task_seq = old.task_seq
        n = len(new.agent.llmclient.backend.history)
        self._system(f"Branched #{old.agent_id} → #{new.agent_id} ({n} msgs).")

    def _cmd_rewind(self, args, raw):
        sess = self.current
        if sess.status == "running":
            self._system("Cannot rewind while running. /stop first."); return
        history = sess.agent.llmclient.backend.history
        turns = []
        for i, m in enumerate(history):
            if m.get("role") != "user": continue
            c = m.get("content")
            if isinstance(c, str):
                turns.append((i, c[:60])); continue
            if isinstance(c, list):
                if any(b.get("type") == "tool_result" for b in c if isinstance(b, dict)):
                    continue
                texts = [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"]
                if texts and any(t.strip() for t in texts):
                    turns.append((i, texts[0][:60]))
        if not turns:
            self._system("No rewindable turns."); return
        if not args:
            lines = [f"Rewindable turns ({len(turns)}):"]
            for offset, (_, prev) in enumerate(reversed(turns[-10:]), 1):
                lines.append(f"  {offset}) {prev!r}")
            lines.append("/rewind <n> to undo n turns")
            self._system("\n".join(lines)); return
        try: n = int(args[0])
        except ValueError: self._system("Usage: /rewind <n>"); return
        if n < 1 or n > len(turns):
            self._system(f"Invalid: 1-{len(turns)}"); return
        cut = turns[-n][0]
        removed = len(history) - cut
        history[:] = history[:cut]
        real_user = [i for i, m in enumerate(sess.messages) if m.role == "user"]
        if n <= len(real_user):
            sess.messages = sess.messages[:real_user[-n]]
        try: sess.agent.history.append(f"[USER]: /rewind {n}")
        except Exception: pass
        self._remount_current_session()
        self._refresh_topbar()
        self._refresh_sidebar()
        self._system(f"Rewound {n} turn(s). Removed {removed} entries.")

    def _cmd_clear(self, args, raw):
        self.current.messages.clear()
        self._remount_current_session()
        self._refresh_topbar()
        self._refresh_sidebar()
        self._system("已清空显示（LLM 历史保留）")

    def _cmd_stop(self, args, raw):
        sess = self.current
        try:
            sess.agent.abort()
            if sess.status == "running":
                sess.status = "stopping"
            self._system(f"Stop sent to #{sess.agent_id}.")
        except Exception as e:
            self._system(f"Stop failed: {e}")
        self._refresh_all()

    def _cmd_llm(self, args, raw):
        sess = self.current
        if args:
            try:
                sess.agent.next_llm(int(args[0]))
                self._system(f"Switched model to #{int(args[0])}.")
            except Exception as e:
                self._system(f"Switch failed: {e}")
            return
        try:
            rows = sess.agent.list_llms()
        except Exception as e:
            self._system(f"List failed: {e}")
            return
        if not rows:
            self._system("没有可用模型。")
            return
        choices = []
        for i, name, cur in rows:
            mark = "✓ " if cur else "  "
            choices.append((f"{mark}[{i}] {name}", i))
        msg = ChatMessage(
            role="system",
            content="选择模型 (↑/↓ 移动，→/Enter 确认，Esc 取消)",
            kind="choice",
            choices=choices,
            on_select=lambda v: self._do_switch_llm(v),
        )
        self.current.messages.append(msg)
        self._refresh_messages()

    def _do_switch_llm(self, idx: int) -> str:
        try:
            self.current.agent.next_llm(int(idx))
            name = self.current.agent.get_llm_name()
            return f"已切换到 [{idx}] {name}"
        except Exception as e:
            return f"❌ 切换失败: {e}"

    # ---------------- new commands ----------------
    def _cmd_btw(self, args, raw):
        question = " ".join(args).strip()
        if not question:
            self._system("Usage: /btw <question>"); return
        sess = self.current
        sess.messages.append(ChatMessage("user", f"/btw {question}"))
        placeholder = ChatMessage("assistant", "（side question 处理中...）", done=False)
        sess.messages.append(placeholder)
        self._refresh_messages()

        def worker():
            try:
                answer = btw_handle(sess.agent, raw)
            except Exception as e:
                answer = f"❌ /btw 失败: {type(e).__name__}: {e}"
            self.call_from_thread(self._update_assistant, sess.agent_id, answer)

        threading.Thread(target=worker, daemon=True, name="ga-tui-btw").start()

    def _cmd_continue(self, args, raw):
        sess = self.current
        m = re.match(r"/continue\s+(\d+)\s*$", (raw or "").strip())
        if m:
            sessions = continue_list(exclude_pid=os.getpid())
            idx = int(m.group(1)) - 1
            if not (0 <= idx < len(sessions)):
                self._system(f"❌ 索引越界（有效范围 1-{len(sessions)}）"); return
            self._do_continue_restore(sessions[idx][0])
            return
        sessions = continue_list(exclude_pid=os.getpid())
        if not sessions:
            self._system("❌ 没有可恢复的历史会话"); return
        LIMIT = 20
        choices = []
        for path, mtime, first, n in sessions[:LIMIT]:
            preview = (first or "（无法预览）").replace("\n", " ").strip()[:50]
            choices.append((f"{_short_age(mtime)} · {n}轮 · {preview}", path))
        head = "选择要恢复的会话 (↑/↓ 移动，→/Enter 确认，Esc 取消)"
        if len(sessions) > LIMIT:
            head += f"  [仅显示最近 {LIMIT}/{len(sessions)}]"
        msg = ChatMessage(
            role="system", content=head, kind="choice", choices=choices,
            on_select=lambda v: self._do_continue_restore(v),
        )
        sess.messages.append(msg)
        self._refresh_messages()

    def _do_continue_restore(self, path: str) -> str:
        sess = self.current
        from continue_cmd import reset_conversation, restore
        try:
            reset_conversation(sess.agent, message=None)
            result, _ok = restore(sess.agent, path)
        except Exception as e:
            return f"❌ 恢复失败: {e}"
        def _finish():
            sess.messages.clear()
            for h in continue_extract(path):
                sess.messages.append(ChatMessage(role=h["role"], content=h["content"]))
            self._remount_current_session()
            self._refresh_all()
        self.call_after_refresh(_finish)
        return result.splitlines()[0] if result else "✅ 已恢复"

    def _cmd_export(self, args, raw):
        """Forms:
            /export                 → 3-choice picker (clip/all/file with timestamp)
            /export clip|copy       last reply wrapped in code block
            /export all             full log file path
            /export file [name]     export last reply to file
            /export <name>          legacy: equivalent to /export file <name>
        """
        sub = args[0].lower() if args else ""
        if not sub:
            choices = [
                ("📋 clip — 复制最后一轮回复（代码块包裹，便于粘贴）", "clip"),
                ("📂 all  — 显示完整日志文件路径", "all"),
                ("💾 file — 导出到文件（提交前可编辑文件名）", "file"),
            ]
            msg = ChatMessage(
                role="system",
                content="选择导出方式 (↑/↓ 移动，→/Enter 确认，Esc 取消)",
                kind="choice",
                choices=choices,
                on_select=lambda v: self._prompt_export_filename() if v == "file" else self._do_export(v),
            )
            self.current.messages.append(msg)
            self._refresh_messages()
            return
        if sub == "file":
            custom = " ".join(args[1:]).strip() or None
            self._system(self._do_export("file", custom))
            return
        if sub == "all":
            self._system(self._do_export("all"))
            return
        if sub in ("clip", "copy"):
            self._system(self._do_export("clip"))
            return
        self._system(self._do_export("file", " ".join(args).strip()))

    def _prompt_export_filename(self) -> str:
        from datetime import datetime as _dt
        default = "export-" + _dt.now().strftime("%Y%m%d-%H%M%S") + ".md"
        text = "/export " + default
        def _fill():
            try:
                inp = self.query_one("#input", InputArea)
                self._suppress_palette_open = True
                inp.text = text
                inp.move_cursor((0, len(text)))
                inp.focus()
                self._resize_input(inp)
            except Exception:
                pass
        self.call_after_refresh(_fill)
        return "✏️ 已填入默认文件名，按 Enter 确认或先编辑"

    def _do_export(self, kind: str, filename: str | None = None) -> str:
        sess = self.current
        try:
            if kind == "all":
                log = getattr(sess.agent, "log_path", "")
                if log and os.path.isfile(log):
                    return f"📂 完整日志:\n{log}"
                return "❌ 尚无日志文件"
            text = last_assistant_text(sess.agent)
            if not text:
                return "❌ 还没有可导出的回复"
            if kind == "clip":
                return f"📋 最后一轮回复:\n\n{wrap_for_clipboard(text)}"
            if kind == "file":
                if not filename:
                    from datetime import datetime as _dt
                    filename = "export-" + _dt.now().strftime("%Y%m%d-%H%M%S") + ".md"
                path = export_to_temp(text, filename)
                return f"✅ 已导出: {path}"
            return f"❌ 未知选项: {kind}"
        except Exception as e:
            return f"❌ 导出失败: {type(e).__name__}: {e}"

    def _cmd_restore(self, args, raw):
        sess = self.current
        try:
            info, err = format_restore()
        except Exception as e:
            self._system(f"❌ 恢复失败: {e}"); return
        if err:
            self._system(err); return
        restored, fname, count = info
        try:
            sess.agent.abort()
            sess.agent.history.extend(restored)
            self._system(f"✅ 已恢复 {count} 轮上下文，来源: {fname}")
        except Exception as e:
            self._system(f"❌ 注入失败: {e}")

    def _cmd_quit(self, args, raw):
        self.exit()

    # ---------------- agent task + stream ----------------
    def submit_user_message(self, text: str, images: Optional[list[str]] = None) -> int:
        sess = self.current
        if sess.status == "running":
            self._system(f"#{sess.agent_id} 正在跑，/stop 后再发。")
            return -1
        sess.task_seq += 1
        tid = sess.task_seq
        sess.current_task_id = tid
        sess.buffer = ""
        sess.status = "running"
        image_paths = list(images or [])
        sess.messages.append(ChatMessage("user", text, image_paths=image_paths))
        sess.messages.append(ChatMessage("assistant", "", task_id=tid, done=False))
        self._refresh_all()
        try:
            self.query_one("#messages", VerticalScroll).scroll_end(animate=False)
        except Exception:
            pass
        try:
            dq = sess.agent.put_task(text, source="user")
        except Exception as e:
            sess.status = "error"
            self._update_assistant(sess.agent_id, f"[ERROR] put_task: {e}", task_id=tid, refresh_chrome=True)
            return tid
        sess.current_display_queue = dq
        threading.Thread(
            target=self._consume_display_queue,
            args=(sess.agent_id, tid, dq),
            daemon=True,
            name=f"ga-tui-consume-{sess.agent_id}-{tid}",
        ).start()
        return tid

    def _consume_display_queue(self, agent_id, task_id, dq):
        buf = ""
        while True:
            try: item = dq.get(timeout=0.25)
            except queue.Empty: continue
            if "next" in item:
                buf += str(item.get("next") or "")
                self.call_from_thread(self._on_stream, agent_id, task_id, buf, False)
            if "done" in item:
                done_text = str(item.get("done") or buf)
                self.call_from_thread(self._on_stream, agent_id, task_id, done_text, True)
                return

    def _on_stream(self, agent_id, task_id, text, done):
        s = self.sessions.get(agent_id)
        if not s or s.current_task_id != task_id:
            return
        s.buffer = text
        if done:
            s.status = "idle"
            s.current_display_queue = None
        self._update_assistant(agent_id, text, task_id=task_id, done=done, refresh_chrome=True)

    def _update_assistant(self, agent_id, text, *, task_id=None, done=True, refresh_chrome=False):
        # task_id=None matches the last assistant message; otherwise matches by task_id.
        s = self.sessions.get(agent_id)
        if not s: return
        found = None
        for m in reversed(s.messages):
            if m.role == "assistant" and (task_id is None or m.task_id == task_id):
                m.content = text
                m.done = done
                found = m
                break
        if agent_id != self.current_id:
            return
        if found and found._body_widget is not None:
            try:
                container = self.query_one("#messages", VerticalScroll)
                was_at_bottom = self._at_bottom(container)
                found._body_widget.update(self._build_assistant_body(found))
                if was_at_bottom:
                    container.scroll_end(animate=False)
            except Exception:
                self._refresh_messages()
        else:
            self._refresh_messages()
        if refresh_chrome:
            self._refresh_sidebar()
            self._refresh_topbar()

    # ---------------- UI refresh ----------------
    def _system(self, text: str) -> None:
        if self.current_id is None: return
        self.current.messages.append(ChatMessage("system", text))
        self._refresh_messages()

    def _refresh_all(self):
        if not self.is_mounted: return
        self._refresh_topbar()
        self._refresh_sidebar()
        self._refresh_messages()

    def _refresh_topbar(self):
        if not self.is_mounted or self.current_id is None: return
        s = self.current
        try: model = s.agent.get_llm_name(model=True)
        except Exception: model = "?"
        tasks_running = sum(1 for x in self.sessions.values() if x.status == "running")
        self.query_one("#topbar", Static).update(
            render_topbar(s.name, s.status, model, tasks_running, fold_mode=self.fold_mode))

    def _refresh_bottombar(self):
        if not self.is_mounted: return
        try:
            self.query_one("#bottombar", Static).update(render_bottombar(quit_armed=self._quit_armed))
        except Exception:
            pass

    def _refresh_sidebar(self):
        if not self.is_mounted: return
        self.query_one("#sidebar", Static).update(render_sidebar(self.sessions, self.current_id))

    def _at_bottom(self, container) -> bool:
        try:
            return container.scroll_y >= container.max_scroll_y - 1
        except Exception:
            return True

    def _refresh_messages(self):
        if not self.is_mounted or self.current_id is None: return
        sess = self.current
        container = self.query_one("#messages", VerticalScroll)
        switched = getattr(self, "_last_session_id", None) != sess.agent_id
        was_at_bottom = True if switched else self._at_bottom(container)
        if switched:
            container.remove_children()
            for m in sess.messages:
                m._role_widget = None
                m._body_widget = None
            self._last_session_id = sess.agent_id
        for m in sess.messages:
            if m._role_widget is None:
                self._mount_message(container, m)
        if was_at_bottom:
            container.scroll_end(animate=False)

    def _messages_width(self) -> int:
        try:
            w = self.query_one("#messages", VerticalScroll).content_region.width
            return max(40, w)
        except Exception:
            return 100

    def _build_assistant_body(self, m: ChatMessage):
        # Markdown via RichVisual loses segment.style.meta["offset"] so mouse selection
        # can't anchor; round-trip through ANSI → Text.from_ansi to restore selectability.
        width = self._messages_width()
        key = (len(m.content or ""), m.done, width, self.fold_mode)
        if m._cache_key == key and m._cached_body is not None:
            return m._cached_body
        suffix = "" if m.done else " …"
        raw = m.content or ""
        cleaned = _ANSI_CONTROL_RE.sub("", raw)
        if self.fold_mode:
            cleaned = render_folded_text(cleaned)
        text = cleaned + suffix
        if not raw.strip():
            return Text(suffix or "（空）", style=C_DIM)
        try:
            from io import StringIO
            from rich.console import Console
            buf = StringIO()
            Console(file=buf, width=width, force_terminal=True,
                    color_system="truecolor", legacy_windows=False
                    ).print(HardBreakMarkdown(text), end="")
            body = Text.from_ansi(buf.getvalue().rstrip("\n"))
        except Exception:
            body = Text(text, style=C_FG)
        if m.done:  # streaming content keeps changing — only cache final
            m._cached_body = body
            m._cache_key = key
        return body

    _ROLE_COLOR = {"user": C_PURPLE, "system": C_BLUE, "assistant": C_GREEN}

    def _mount_message(self, container: VerticalScroll, m: ChatMessage) -> None:
        color = self._ROLE_COLOR.get(m.role, C_GREEN)
        label = m.role.upper() if m.role != "assistant" else "AGENT"
        m._role_widget = SelectableStatic(f"[bold {color}]{label}[/]", classes="role")
        container.mount(m._role_widget)

        if m.kind == "choice" and m.selected_label is None:
            m._hint_widget = SelectableStatic(Text(m.content, style=C_MUTED), classes="msg")
            container.mount(m._hint_widget)
            choice = ChoiceList(m)
            for cl, _ in m.choices:
                choice.add_option(Option(cl))
            m._body_widget = choice
            container.mount(choice)
            self.call_after_refresh(choice.focus)
            return

        if m.kind == "choice":  # selected_label is not None
            body = Text(); body.append("✓ ", style=C_GREEN); body.append(m.selected_label, style=C_FG)
        elif m.role == "user":
            body = Text(); body.append("> ", style=C_DIM); body.append(m.content, style=C_FG)
            for path in m.image_paths:
                body.append(f"\n📎 {path}", style=C_MUTED)
        elif m.role == "system":
            body = Text(m.content, style=C_MUTED)
        else:
            body = self._build_assistant_body(m)
        m._body_widget = SelectableStatic(body, classes="msg")
        container.mount(m._body_widget)


# ---------- CLI ----------
def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="GenericAgent TUI v2 (refined visual style)")


def main(argv: Optional[list[str]] = None) -> int:
    build_arg_parser().parse_args(argv)
    GenericAgentTUI().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
