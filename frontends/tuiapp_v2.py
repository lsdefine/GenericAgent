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
    from textual.widgets import OptionList, Static, TextArea
    from textual.widgets.option_list import Option
except ModuleNotFoundError as exc:
    print(f"Missing dependency: {exc.name}. Install Textual: pip install textual",
          file=sys.stderr)
    raise SystemExit(2) from exc


# 剥子进程 stdout 里漏出来的终端控制序列（如 bracketed paste / 隐藏光标），
# 保留 SGR 颜色码 (\x1b[<num>m)，否则后面 Text.from_ansi 染色会丢
_ANSI_CONTROL_RE = re.compile(
    r"\x1b\[\?[\d;]*[hl]"      # 私有模式: ?2004h / ?25l ...
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC: 标题 / 超链接
    r"|\x1b[=>]"               # 键盘模式切换
)


def fold_turns(text: str) -> list[dict]:
    """按 `**LLM Running (Turn N) ...**` 标记切分；已完成 turn 标为 fold，末尾未完成 turn 保持原文。"""
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
    """Rich Markdown 默认把 softbreak 渲成空格，把 agent 多行日志粘成一行；改走 hardbreak。"""
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

# Project import path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
FRONTENDS_DIR = os.path.dirname(os.path.abspath(__file__))
if FRONTENDS_DIR not in sys.path:
    sys.path.insert(0, FRONTENDS_DIR)

# Side-effect imports: activate /btw + /continue monkey-patches on GenericAgent
import chatapp_common  # noqa: F401
from chatapp_common import format_restore
from btw_cmd import handle_frontend_command as btw_handle
from continue_cmd import handle_frontend_command as continue_handle, list_sessions as continue_list, extract_ui_messages as continue_extract
from export_cmd import last_assistant_text, export_to_temp, wrap_for_clipboard

AgentFactory = Callable[[], Any]

# ---------- 配色 ----------
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
    # Mounted widget refs (None until mounted)
    _role_widget: Any = field(default=None, repr=False)
    _hint_widget: Any = field(default=None, repr=False)
    _body_widget: Any = field(default=None, repr=False)
    # Cached rendered Text + key (content_len, done, width, fold_mode)
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


# ---------- 命令定义（用于命令面板 + 本地拦截集合） ----------
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


# ---------- 交互式选择 widget ----------
class ChoiceList(OptionList):
    """OptionList 子类，记住所属 ChatMessage，便于选中后回填。"""
    def __init__(self, msg: "ChatMessage", **kwargs):
        super().__init__(**kwargs)
        self.msg = msg


class SelectableStatic(Static):
    """Widget.get_selection 对非 Text/Content visual 返回 None；从 render_line 抠字符兜底。"""
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


class InputArea(TextArea):
    """多行输入框：Enter 发送 / Ctrl+J 等换行 / 粘贴 >2 行收为 [Pasted text #N +M lines]。"""
    _PASTE_RE = re.compile(r'\[Pasted text #(\d+) \+\d+ lines\]')

    BINDINGS = [
        Binding("ctrl+j",      "newline", "Newline", show=False),
        Binding("alt+enter",   "newline", "Newline", show=False),
        Binding("ctrl+enter",  "newline", "Newline", show=False),
        Binding("shift+enter", "newline", "Newline", show=False),
        # 拆掉父类 ctrl+v：父类会走 action_paste 从 app.clipboard 再插一次，
        # 和终端 bracketed paste 触发的 _on_paste 双重插入 → 单行粘贴会重复
        Binding("ctrl+v",      "noop",    "Noop",    show=False),
    ]

    def action_noop(self) -> None:
        pass

    class Submitted(Message):
        def __init__(self, input_area: "InputArea", value: str) -> None:
            super().__init__()
            self.input_area = input_area
            self.value = value

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pastes: dict[int, str] = {}
        self._paste_counter = 0

    def expand_placeholders(self, text: str) -> str:
        def repl(m):
            sid = int(m.group(1))
            return self._pastes.get(sid, m.group(0))
        return self._PASTE_RE.sub(repl, text)

    def reset(self) -> None:
        self.text = ""
        self._pastes.clear()
        self._paste_counter = 0

    def action_newline(self) -> None:
        result = self._replace_via_keyboard("\n", *self.selection)
        if result:
            self.move_cursor(result.end_location)

    async def _on_paste(self, event: events.Paste) -> None:
        if self.read_only:
            return
        text = event.text.replace("\r\n", "\n").replace("\r", "\n")
        line_count = len(text.splitlines()) or 1
        if line_count > 2:
            self._paste_counter += 1
            sid = self._paste_counter
            self._pastes[sid] = text
            text = f"[Pasted text #{sid} +{line_count} lines]"
        result = self._replace_via_keyboard(text, *self.selection)
        if result:
            self.move_cursor(result.end_location)
            self.focus()
        event.stop(); event.prevent_default()

    async def _on_key(self, event: events.Key) -> None:
        try:
            palette = self.app.query_one("#palette", OptionList)
        except Exception:
            palette = None
        if palette is not None and palette.has_class("-visible"):
            routes = {"up": palette.action_cursor_up, "down": palette.action_cursor_down}
            if event.key == "enter" and palette.highlighted is not None:
                routes["enter"] = palette.action_select
            fn = routes.get(event.key)
            if fn:
                fn(); event.stop(); event.prevent_default(); return
        if event.key == "enter":  # 换行键已被 BINDINGS 拦走
            event.stop(); event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        await super()._on_key(event)


# ---------- 顶部栏 ----------
def render_topbar(session_name: str, status: str, model: str, tasks_running: int) -> Table:
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


def render_bottombar() -> Table:
    t = Table.grid(expand=True)
    t.add_column(ratio=2, justify="left")
    t.add_column(ratio=1, justify="right")
    left = Text()
    pairs = [("Enter", "发送"), ("↑/↓", "选择"),
             ("Ctrl+N", "新会话"), ("Ctrl+B", "侧栏"),
             ("Ctrl+F", "折叠"), ("Ctrl+S", "停止")]
    for i, (k, d) in enumerate(pairs):
        if i: left.append("    ")
        left.append(k, style=C_FG)
        left.append(" ")
        left.append(d, style=C_MUTED)
    right = Text()
    right.append("/", style=C_GREEN)
    right.append(" 命令面板", style=C_MUTED)
    t.add_row(left, right)
    return t


# ---------- 侧栏 ----------
def _truncate(text: str, max_w: int) -> str:
    import unicodedata
    w, out = 0, []
    for ch in text:
        wch = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + wch > max_w:
            out.append("…"); break
        out.append(ch); w += wch
    return "".join(out)


def _sidebar_last_user(sess: AgentSession) -> str:
    for m in reversed(sess.messages):
        if m.role == "user":
            return re.sub(r"\s+", " ", m.content).strip()
    return ""


def _sidebar_last_summary(sess: AgentSession) -> str:
    """最近一条 assistant 输出里最后一个 <summary> 的首段。"""
    for m in reversed(sess.messages):
        if m.role == "assistant" and m.content:
            matches = re.findall(r"<summary>\s*(.*?)\s*</summary>", m.content, re.DOTALL)
            if matches:
                return re.sub(r"\s+", " ", matches[-1]).strip()
    return ""


def render_sidebar(sessions: dict[int, AgentSession], current_id: Optional[int]) -> Table:
    outer = Table.grid(expand=True)
    outer.add_column()

    SEL = f"on {C_SEL_BG}"
    sess_tbl = Table.grid(expand=True)
    sess_tbl.add_column(width=2)              # left pad
    sess_tbl.add_column(width=2)              # icon
    sess_tbl.add_column(ratio=1, no_wrap=True, overflow="ellipsis")  # name / Q / S
    sess_tbl.add_column(justify="right")      # status
    sess_tbl.add_column(width=2)              # right pad
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
        Binding("ctrl+n",     "new_session",   "New",   show=False),
        Binding("ctrl+b",     "toggle_sidebar","Sidebar", show=False),
        Binding("ctrl+s",     "stop_current",  "Stop",  show=False),
        Binding("ctrl+f",     "toggle_fold",   "Fold",  show=False),
        Binding("ctrl+q",     "quit",          "Quit",  show=False),
        Binding("ctrl+left",  "prev_session",  "Prev",  show=False, priority=True),
        Binding("ctrl+right", "next_session",  "Next",  show=False, priority=True),
        Binding("escape",     "close_palette", "Close", show=False),
        Binding("tab",        "complete_command", "Complete", show=False, priority=True),
    ]

    def __init__(self, agent_factory: Optional[AgentFactory] = None) -> None:
        super().__init__()
        self.agent_factory: AgentFactory = agent_factory or default_agent_factory
        self.sessions: dict[int, AgentSession] = {}
        self.current_id: Optional[int] = None
        self._ids = count(1)
        self._suppress_palette_open = False   # 选中 option 后抑制下一次 on_input_changed 重开 palette
        self.fold_mode: bool = True           # 折叠已完成的 turn，Ctrl+F 切
        self._last_width: int = -1            # 轮询时检测变化用（Windows 窗口吸附/全屏不发 resize 时的兜底）

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

    def _tick(self) -> None:
        """0.5s 轮询：刷顶栏时间 + 兜底检测尺寸变化（Windows 窗口吸附/全屏不发 resize）。"""
        self._refresh_topbar()
        w = self.size.width
        if w != self._last_width:
            self._last_width = w
            self._apply_responsive_layout()

    def _patch_auto_scroll_for_selection(self) -> None:
        """让选区拖拽到 #input 上时仍能滚动 #messages：把 _select_start 也当候选源，鼠标在 scrollable 下/上方也触发。"""
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
            if screen._select_start is not None:
                sw = screen._select_start[0]
                if sw is not select_widget:
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
                        # 扩展：鼠标在 scrollable 下方（如拖到 #input 上）
                        if ancestor.scroll_y < ancestor.max_scroll_y:
                            screen._start_auto_scroll(ancestor, +1, 1.0)
                            return
                    elif mouse_y < ar.y:
                        # 扩展：鼠标在 scrollable 上方
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

    def action_stop_current(self) -> None:
        self._cmd_stop([])

    def action_toggle_sidebar(self) -> None:
        self.query_one("#sidebar", Static).toggle_class("-hidden")

    def action_toggle_fold(self) -> None:
        self.fold_mode = not self.fold_mode
        # 清掉所有 assistant 缓存，强制重渲（fold 状态改变 → 内容长度变）
        for sess in self.sessions.values():
            for m in sess.messages:
                if m.role == "assistant":
                    m._cached_body = None
                    m._cache_key = ()
        self._remount_current_session()
        self.notify(f"Fold: {'on' if self.fold_mode else 'off'}", timeout=1)

    def action_close_palette(self) -> None:
        self._hide_palette()
        self.query_one("#input", InputArea).focus()

    def action_complete_command(self) -> None:
        """Tab：命令面板可见时补全到当前高亮命令；否则什么都不做。"""
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
        """点击侧栏会话条目 → 切换。"""
        try:
            sidebar = self.query_one("#sidebar", Static)
        except Exception:
            return
        if event.widget is not sidebar:
            return
        # event.y 是 widget 区相对坐标（含 padding-top=1）。
        # 布局：padding 1 行 + "SESSIONS" + 空行 + sessions 块 → 减 3。
        y = event.y - 3
        if y < 0:
            return
        for sid, sess in self.sessions.items():
            rows = 3  # top spacer + name + bottom spacer
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
        self._apply_responsive_layout()
        try: self._resize_input(self.query_one("#input", InputArea))
        except Exception: pass

    def _apply_responsive_layout(self) -> None:
        """按终端宽度调侧栏宽 + 主区横向 padding。<70 列隐藏侧栏，宽屏按比例放大。"""
        try:
            sidebar = self.query_one("#sidebar", Static)
            main = self.query_one("#main", Vertical)
        except Exception:
            return
        w = self.size.width
        self._last_width = w
        # 自动隐藏走 -narrow 类，跟用户手动 Ctrl+B 切的 -hidden 互不干扰
        if w < 70:
            sidebar.add_class("-narrow")
        else:
            sidebar.remove_class("-narrow")
            sidebar.styles.width = max(30, min(50, w // 5))
        main.styles.padding = (1, 2) if w < 90 else (1, 6)
        self._remount_current_session()  # 宽度变了 → markdown 要按新宽重渲

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
        # 高度自适应：内容 1-3 行随之撑高，>3 行固定为 3 行（内部滚动）
        self._resize_input(inp)
        val = (inp.text or "").lstrip()
        if self._suppress_palette_open:
            self._suppress_palette_open = False
            self._hide_palette()
            return
        # 仅当首行还在命令名阶段（以 / 开头、没空格、没换行）才弹 palette
        first_line = val.split("\n", 1)[0]
        if first_line.startswith("/") and " " not in first_line and "\n" not in val:
            self._populate_palette(first_line)
            self._show_palette()
        else:
            self._hide_palette()

    def _resize_input(self, inp: TextArea) -> None:
        # wrapped_document.height 才是含软换行的可见行数；document.line_count 只数逻辑行
        try:
            lines = inp.wrapped_document.height or inp.document.line_count
        except Exception:
            lines = inp.document.line_count
        inp.styles.height = min(max(lines, 1), 3) + 2  # +2 = padding 1 2 的上下边

    def on_input_area_submitted(self, event: "InputArea.Submitted") -> None:
        inp = event.input_area
        if inp.id != "input":
            return
        text = inp.expand_placeholders(event.value).rstrip()
        inp.reset()
        self._hide_palette()
        self._resize_input(inp)
        if not text:
            return
        if text.startswith("/"):
            parts = text.split(maxsplit=1)
            cmd = parts[0][1:].lower()
            args = parts[1].split() if len(parts) > 1 else []
            if cmd in self._handlers():
                self._dispatch_command(cmd, args, raw=text)
                return
        self.submit_user_message(text)

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
            # 不上彩色——反色高亮时彩字配亮底不好看；仅用 bold 区分命令名
            t = Text()
            t.append(f"{cmd:<11}", style="bold")
            t.append(f"{args:<18}")
            t.append(f"  {desc}")
            palette.add_option(Option(t, id=cmd))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        ol = event.option_list
        # 1) 命令面板
        if ol.id == "palette":
            cmd_id = event.option.id
            if cmd_id:
                inp = self.query_one("#input", InputArea)
                needs_args = any(c[1] for c in COMMANDS if c[0] == cmd_id)
                self._suppress_palette_open = True   # 阻止 inp.text= 触发 on_text_area_changed 再开
                new_text = cmd_id + (" " if needs_args else "")
                inp.text = new_text
                inp.move_cursor((0, len(new_text)))
            self._hide_palette()
            self.query_one("#input", InputArea).focus()
            return
        # 2) 聊天中嵌入的 ChoiceList
        if isinstance(ol, ChoiceList):
            self._collapse_choice(ol.msg, event.option_index)
            return

    def _collapse_choice(self, msg: ChatMessage, idx: int) -> None:
        """选中后：执行 on_select → 用结果文本替换 hint+ChoiceList，单条 SYSTEM 消息。"""
        if not (0 <= idx < len(msg.choices)):
            return
        label, value = msg.choices[idx]
        # 先跑回调拿结果文本
        result_text = None
        if msg.on_select:
            try:
                result_text = msg.on_select(value)
            except Exception as e:
                result_text = f"❌ 失败: {type(e).__name__}: {e}"
        display = (result_text or label).strip() or label
        msg.selected_label = display
        msg.content = display  # 保持 dataclass 一致，便于将来重新挂载
        # 用单个塌缩 Static 替换 hint + ChoiceList
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

    def _handlers(self) -> dict:
        """单 arg 命令直挂；btw/continue 用 lambda 接 raw；quit/exit 共用一个。"""
        return {
            "help": self._cmd_help, "status": self._cmd_status, "sessions": self._cmd_status,
            "new": self._cmd_new, "switch": self._cmd_switch, "close": self._cmd_close,
            "branch": self._cmd_branch, "rewind": self._cmd_rewind, "clear": self._cmd_clear,
            "stop": self._cmd_stop, "llm": self._cmd_llm, "export": self._cmd_export,
            "restore": self._cmd_restore,
            "btw": lambda a, r: self._cmd_btw(a, r),
            "continue": lambda a, r: self._cmd_continue(a, r),
            "quit": lambda *_: self.exit(), "exit": lambda *_: self.exit(),
        }

    def _dispatch_command(self, cmd: str, args: list[str], raw: str = "") -> None:
        h = self._handlers().get(cmd)
        if not h: return
        try: h(args, raw)
        except TypeError: h(args)

    # ---------------- legacy commands ----------------
    def _cmd_help(self, args):
        lines = [f"{c:<11} {a:<18} {d}" for c, a, d in COMMANDS]
        self._system("命令列表:\n" + "\n".join(lines))

    def _cmd_status(self, args):
        lines = []
        for sid, s in self.sessions.items():
            mark = "*" if sid == self.current_id else " "
            lines.append(f"{mark} #{sid} {s.name} [{s.status}] msgs={len(s.messages)} task={s.current_task_id}")
        self._system("Sessions:\n" + "\n".join(lines))

    def _cmd_new(self, args):
        name = " ".join(args).strip() or None
        sess = self.add_session(name)
        self._system(f"Created session #{sess.agent_id} ({sess.name}).")

    def _cmd_switch(self, args):
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

    def _cmd_close(self, args):
        if len(self.sessions) <= 1:
            self._system("Cannot close the last session."); return
        del self.sessions[self.current_id]
        self.current_id = next(iter(self.sessions))
        self._refresh_all()

    def _cmd_branch(self, args):
        import copy
        old = self.current
        name = " ".join(args).strip() or f"{old.name}-branch"
        new = self.add_session(name)
        try:
            new.agent.llmclient.backend.history = copy.deepcopy(old.agent.llmclient.backend.history)
        except Exception as e:
            self._system(f"Branch warning: {e}"); return
        new.messages = copy.deepcopy(old.messages)
        new.task_seq = old.task_seq
        n = len(new.agent.llmclient.backend.history)
        self._system(f"Branched #{old.agent_id} → #{new.agent_id} ({n} msgs).")

    def _cmd_rewind(self, args):
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
        self._refresh_all()
        self._system(f"Rewound {n} turn(s). Removed {removed} entries.")

    def _cmd_clear(self, args):
        self.current.messages.clear()
        self._refresh_all()

    def _cmd_stop(self, args):
        sess = self.current
        try:
            sess.agent.abort()
            if sess.status == "running":
                sess.status = "stopping"
            self._system(f"Stop sent to #{sess.agent_id}.")
        except Exception as e:
            self._system(f"Stop failed: {e}")
        self._refresh_all()

    def _cmd_llm(self, args):
        sess = self.current
        if args:
            try:
                sess.agent.next_llm(int(args[0]))
                self._system(f"Switched model to #{int(args[0])}.")
            except Exception as e:
                self._system(f"Switch failed: {e}")
            return
        # 无参数 → 交互式选择
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
            content="选择模型 (↑/↓ 移动，Enter 确认)",
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
        # /continue N 时先把 path 锁住：handle_frontend_command 会先 snapshot 当前日志，
        # 之后 list_sessions 的索引会偏，必须在 handle 之前解析
        m = re.match(r"/continue\s+(\d+)\s*$", (raw or "").strip())
        target = None
        if m:
            sessions = continue_list(exclude_pid=os.getpid())
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(sessions):
                target = sessions[idx][0]
        try:
            result = continue_handle(sess.agent, raw)
        except Exception as e:
            result = f"❌ /continue 失败: {e}"
        # 成功恢复：把历史 user/assistant 消息塞进当前 session 的 messages
        if target and result.startswith("✅"):
            sess.messages.clear()
            for h in continue_extract(target):
                sess.messages.append(ChatMessage(role=h["role"], content=h["content"]))
            self._remount_current_session()
        self._system(result)
        self._refresh_all()

    def _cmd_export(self, args):
        sess = self.current
        sub = args[0].lower() if args else ""
        if not sub:
            self._system(
                "用法:\n"
                "  /export clip       — 整理到代码块\n"
                "  /export <文件名>   — 导出到 temp/<文件名>\n"
                "  /export all        — 显示完整日志路径"
            ); return
        if sub == "all":
            log = getattr(sess.agent, "log_path", "")
            self._system(f"📂 完整日志:\n{log}" if log and os.path.isfile(log)
                         else "❌ 尚无日志文件")
            return
        try:
            text = last_assistant_text(sess.agent)
        except Exception as e:
            self._system(f"❌ 读取失败: {e}"); return
        if not text:
            self._system("❌ 还没有可导出的回复"); return
        if sub in ("clip", "copy"):
            self._system(f"📋 最后一轮回复:\n\n{wrap_for_clipboard(text)}")
        else:
            try:
                path = export_to_temp(text, args[0])
                self._system(f"✅ 已导出: {path}")
            except Exception as e:
                self._system(f"❌ 导出失败: {e}")

    def _cmd_restore(self, args):
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

    # ---------------- agent task + stream ----------------
    def submit_user_message(self, text: str) -> int:
        sess = self.current
        if sess.status == "running":
            self._system(f"#{sess.agent_id} 正在跑，/stop 后再发。")
            return -1
        sess.task_seq += 1
        tid = sess.task_seq
        sess.current_task_id = tid
        sess.buffer = ""
        sess.status = "running"
        sess.messages.append(ChatMessage("user", text))
        sess.messages.append(ChatMessage("assistant", "", task_id=tid, done=False))
        self._refresh_all()
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
        """task_id=None → 改最后一条 assistant；否则按 task_id 匹配。"""
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
                found._body_widget.update(self._build_assistant_body(found))
                self.query_one("#messages", VerticalScroll).scroll_end(animate=False)
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
        self.query_one("#topbar", Static).update(render_topbar(s.name, s.status, model, tasks_running))

    def _refresh_sidebar(self):
        if not self.is_mounted: return
        self.query_one("#sidebar", Static).update(render_sidebar(self.sessions, self.current_id))

    def _refresh_messages(self):
        if not self.is_mounted or self.current_id is None: return
        sess = self.current
        container = self.query_one("#messages", VerticalScroll)
        # Session change → full reset (release old refs)
        if getattr(self, "_last_session_id", None) != sess.agent_id:
            container.remove_children()
            for m in sess.messages:
                m._role_widget = None
                m._body_widget = None
            self._last_session_id = sess.agent_id
        # Mount any messages that haven't been mounted yet
        for m in sess.messages:
            if m._role_widget is None:
                self._mount_message(container, m)
        container.scroll_end(animate=False)

    def _messages_width(self) -> int:
        """渲染 Markdown 时用的列宽：取 #messages 的实际 content 宽度，避免 120 死宽留白。"""
        try:
            w = self.query_one("#messages", VerticalScroll).content_region.width
            return max(40, w)
        except Exception:
            return 100

    def _build_assistant_body(self, m: ChatMessage):
        # Markdown 走 RichVisual 路径没有 segment.style.meta["offset"]，鼠标选区起不来；
        # 先 Console 渲成 ANSI 再 Text.from_ansi 解回 Text，selection 才能命中。
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
        if m.done:  # 只缓存已完成；流式中 content 持续变，缓存意义不大
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
            body = Text.from_markup(f"[{C_DIM}]>[/] {m.content}")
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
