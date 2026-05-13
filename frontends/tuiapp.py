"""Textual terminal UI for GenericAgent.

Run from the project root:

    python frontends/tuiapp.py

Useful options:

    python frontends/tuiapp.py --help

MVP design notes:
- One TUI manages multiple GenericAgent instances.
- GenericAgent.put_task() returns a per-task display_queue; the TUI records a task_id for every submit.
- Agent.run() and display_queue.get() run in daemon threads; UI updates are posted via App.call_from_thread().
- Multiple sessions may run concurrently, but GenericAgent still shares project temp/memory/tool globals.
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
    from rich.panel import Panel
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.message import Message
    from textual.widgets import Footer, Header, RichLog, Static, TextArea
except ModuleNotFoundError as exc:  # pragma: no cover - exercised by manual missing-dep path
    if exc.name == "textual":
        print("Textual is required. Install with: pip install textual", file=sys.stderr)
    else:
        print(f"Missing dependency: {exc.name}", file=sys.stderr)
    raise SystemExit(2) from exc

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

AgentFactory = Callable[[], Any]


@dataclass
class ChatMessage:
    role: str
    content: str
    task_id: Optional[int] = None
    done: bool = True
    _rendered_panel: Any = field(default=None, repr=False)


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


def fold_turns(text: str) -> list[dict[str, str]]:
    """Split GenericAgent turn output into text/fold segments.

    Completed turns become ``{'type': 'fold', 'title': ..., 'content': ...}``.
    The latest/incomplete turn remains ``type='text'`` for streaming refresh.
    """
    placeholders: list[str] = []

    def stash(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00PH{len(placeholders) - 1}\x00"

    safe = re.sub(r"`{4,}.*?`{4,}", stash, text, flags=re.DOTALL)
    safe = re.sub(r"`{4,}[^`].*$", stash, safe, flags=re.DOTALL)
    parts = re.split(r"(\**LLM Running \(Turn \d+\) \.\.\.\**)", safe)

    def restore(part: str) -> str:
        return re.sub(r"\x00PH(\d+)\x00", lambda m: placeholders[int(m.group(1))], part)

    parts = [restore(p) for p in parts]
    if len(parts) < 4:
        return [{"type": "text", "content": text}]

    segments: list[dict[str, str]] = []
    if parts[0].strip():
        segments.append({"type": "text", "content": parts[0]})

    turns: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        marker = parts[i]
        content = parts[i + 1] if i + 1 < len(parts) else ""
        turns.append((marker, content))

    for idx, (marker, content) in enumerate(turns):
        if idx < len(turns) - 1:
            cleaned = re.sub(r"`{3,}.*?`{3,}|<thinking>.*?</thinking>", "", content, flags=re.DOTALL)
            matches = re.findall(r"<summary>\s*((?:(?!<summary>).)*?)\s*</summary>", cleaned, re.DOTALL)
            if matches:
                title = matches[0].strip().split("\n", 1)[0]
            else:
                title = cleaned.strip().split("\n", 1)[0] or marker.strip("*")
                # Strip trailing args portion from tool-call lines
                title = re.sub(r",?\s*args:.*$", "", title)
            if len(title) > 72:
                title = title[:72] + "..."
            segments.append({"type": "fold", "title": title, "content": content})
        else:
            segments.append({"type": "text", "content": marker + content})
    return segments


def render_folded_text(text: str) -> str:
    """Render fold segments as terminal-friendly Markdown text.

    Textual's interactive Collapsible widgets are best for static layouts; the MVP uses
    a RichLog and re-renders compact summaries for completed turns to keep streaming cheap.
    """
    rendered: list[str] = []
    for seg in fold_turns(text):
        if seg["type"] == "fold":
            rendered.append(f"\n▸ {seg.get('title') or 'completed turn'}\n\n")
        else:
            rendered.append(seg.get("content", ""))
    return "".join(rendered)


def parse_local_command(raw: str) -> tuple[str, list[str]] | None:
    """Return (command, args) for TUI-owned slash commands; unknown slash is passthrough."""
    text = (raw or "").strip()
    if not text.startswith("/"):
        return None
    name, *rest = text.split(maxsplit=1)
    cmd = name[1:].lower()
    args = rest[0].split() if rest else []
    if cmd in {"help", "status", "new", "switch", "sessions", "stop", "llm", "branch", "rewind", "clear", "close", "quit", "exit"}:
        return cmd, args
    return None


def default_agent_factory() -> Any:
    from agentmain import GenericAgent

    agent = GenericAgent()
    agent.inc_out = True
    return agent


class PromptInput(TextArea):
    """Multi-line input: Enter submits, Ctrl+Enter (ctrl+j) inserts newline, paste never auto-submits."""

    BINDINGS = [
        Binding("ctrl+j", "newline", "Newline", show=False),
    ]

    class Submitted(Message):
        """Posted when the user presses Enter to submit."""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, placeholder: str = "", **kwargs) -> None:
        super().__init__(language=None, show_line_numbers=False, compact=True, placeholder=placeholder, **kwargs)

    def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            # Enter → submit
            event.stop()
            event.prevent_default()
            value = self.text.rstrip()
            self.clear()
            self.post_message(self.Submitted(value))
        elif event.key == "ctrl+j":
            # Ctrl+Enter (ctrl+j) → insert newline
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
        else:
            super()._on_key(event)


class GenericAgentTUI(App[None]):
    """Textual app that manages multiple GenericAgent sessions."""

    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #sidebar { width: 30; min-width: 24; border: solid $accent; padding: 0 1; overflow-x: hidden; }
    #main { width: 1fr; }
    #status { height: 3; border: solid $primary; padding: 0 1; }
    #log { height: 1fr; border: solid $primary; padding: 0 1; }
    #prompt { dock: bottom; height: auto; min-height: 1; max-height: 8; margin-bottom: 1; }
    .hint { color: $text-muted; }
    """

    BINDINGS = [
        ("ctrl+n", "new_session", "New session"),
        ("ctrl+s", "stop_current", "Stop"),
        ("ctrl+f", "toggle_fold", "Fold/Unfold"),
        ("ctrl+q", "quit", "Quit"),
        Binding("ctrl+left", "prev_session", "←Prev", show=True, priority=True),
        Binding("ctrl+right", "next_session", "Next→", show=True, priority=True),
    ]

    def __init__(self, agent_factory: Optional[AgentFactory] = None) -> None:
        super().__init__()
        self.agent_factory: AgentFactory = agent_factory or default_agent_factory
        self.sessions: dict[int, AgentSession] = {}
        self.current_id: Optional[int] = None
        self._ids = count(1)
        self.fold_mode: bool = True
        self._last_stream_refresh: float = 0.0
        self._stream_throttle_ms: float = 0.15  # seconds between streaming UI refreshes

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            yield Static("", id="sidebar")
            with Vertical(id="main"):
                yield Static("", id="status")
                yield RichLog(id="log", wrap=True, highlight=True, markup=True)
        yield PromptInput(placeholder="Message, or /help  /new  /branch  /rewind  /switch  /clear  /close  /stop  /llm  /resume", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.add_session("main")
        self._system("Welcome to GenericAgent TUI. Type /help for commands.")
        self.query_one("#prompt", PromptInput).focus()

    def on_resize(self, event) -> None:
        narrow = self.size.width < 70
        self.query_one("#sidebar").styles.display = "none" if narrow else "block"

    @property
    def current(self) -> AgentSession:
        if self.current_id is None:
            raise RuntimeError("no active session")
        return self.sessions[self.current_id]

    def add_session(self, name: Optional[str] = None) -> AgentSession:
        agent_id = next(self._ids)
        agent = self.agent_factory()
        try:
            agent.inc_out = True
        except Exception:
            pass
        session = AgentSession(agent_id=agent_id, name=name or f"agent-{agent_id}", agent=agent)
        thread = threading.Thread(target=agent.run, name=f"ga-tui-agent-{agent_id}", daemon=True)
        thread.start()
        session.thread = thread
        self.sessions[agent_id] = session
        self.current_id = agent_id
        self._refresh_all()
        return session

    def action_prev_session(self) -> None:
        """Switch to previous session."""
        ids = sorted(self.sessions.keys())
        if len(ids) <= 1:
            return
        idx = ids.index(self.current_id)
        self.current_id = ids[(idx - 1) % len(ids)]
        self._refresh_all()

    def action_next_session(self) -> None:
        """Switch to next session."""
        ids = sorted(self.sessions.keys())
        if len(ids) <= 1:
            return
        idx = ids.index(self.current_id)
        self.current_id = ids[(idx + 1) % len(ids)]
        self._refresh_all()

    def action_switch_session(self, n: int) -> None:
        """Switch to session by id (used by /switch command)."""
        if n in self.sessions:
            self.current_id = n
            self._refresh_all()
        else:
            self.notify(f"Session #{n} does not exist.", severity="warning")

    def action_new_session(self) -> None:
        self.add_session()
        self._system(f"Created and switched to session #{self.current_id}.")

    def action_stop_current(self) -> None:
        self._cmd_stop([])

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        value = event.value.rstrip()
        if not value:
            self._system("Empty input ignored. Type /help for commands.")
            return
        parsed = parse_local_command(value)
        if parsed:
            cmd, args = parsed
            self._dispatch_command(cmd, args)
            return
        self.submit_user_message(value)

    def _dispatch_command(self, cmd: str, args: list[str]) -> None:
        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "new": self._cmd_new,
            "switch": self._cmd_switch,
            "sessions": self._cmd_sessions,
            "stop": self._cmd_stop,
            "llm": self._cmd_llm,
            "branch": self._cmd_branch,
            "rewind": self._cmd_rewind,
            "clear": self._cmd_clear,
            "close": self._cmd_close,
            "quit": lambda _args: self.exit(),
            "exit": lambda _args: self.exit(),
        }
        handlers[cmd](args)

    def submit_user_message(self, text: str) -> int:
        session = self.current
        if session.status == "running":
            self._system(f"Session #{session.agent_id} is already running; wait or /stop before submitting another task.")
            return -1
        session.task_seq += 1
        task_id = session.task_seq
        session.current_task_id = task_id
        session.buffer = ""
        session.status = "running"
        session.messages.append(ChatMessage("user", text))
        session.messages.append(ChatMessage("assistant", "", task_id=task_id, done=False))
        self._refresh_all()
        try:
            display_queue = session.agent.put_task(text, source="user")
        except Exception as exc:
            session.status = "error"
            self._set_assistant_message(session.agent_id, task_id, f"[ERROR] put_task failed: {exc}", done=True)
            return task_id
        session.current_display_queue = display_queue
        threading.Thread(
            target=self._consume_display_queue,
            args=(session.agent_id, task_id, display_queue),
            name=f"ga-tui-consumer-{session.agent_id}-{task_id}",
            daemon=True,
        ).start()
        return task_id

    def _consume_display_queue(self, agent_id: int, task_id: int, display_queue: queue.Queue) -> None:
        buffer = ""
        while True:
            try:
                item = display_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if "next" in item:
                buffer += str(item.get("next") or "")
                self.call_from_thread(self._on_stream_update, agent_id, task_id, buffer, False)
            if "done" in item:
                done_text = str(item.get("done") or buffer)
                self.call_from_thread(self._on_stream_update, agent_id, task_id, done_text, True)
                return

    def _on_stream_update(self, agent_id: int, task_id: int, text: str, done: bool) -> None:
        session = self.sessions.get(agent_id)
        if not session:
            return
        if session.current_task_id != task_id:
            session.messages.append(ChatMessage("system", f"Stale update ignored for task {task_id}.", done=True))
            return
        session.buffer = text
        if done:
            session.status = "idle"
            session.current_display_queue = None
        self._set_assistant_message(agent_id, task_id, text, done=done)

    def _set_assistant_message(self, agent_id: int, task_id: int, text: str, *, done: bool) -> None:
        session = self.sessions.get(agent_id)
        if not session:
            return
        for msg in reversed(session.messages):
            if msg.role == "assistant" and msg.task_id == task_id:
                msg.content = text
                msg.done = done
                break
        else:
            session.messages.append(ChatMessage("assistant", text, task_id=task_id, done=done))
        if agent_id == self.current_id:
            self._refresh_all()
        else:
            self._refresh_sidebar()

    def _cmd_help(self, args: list[str]) -> None:
        self._system(
            "Commands:\n"
            "/help - show this help\n"
            "/new [name] - create and switch to a new agent session\n"
            "/branch [name] - fork current session (copies LLM history + display)\n"
            "/rewind - list rewindable turns; /rewind <n> to truncate history\n"
            "/switch <id|name> - switch active session\n"
            "/sessions - list sessions\n"
            "/status - show current/all status\n"
            "/stop - abort current session task\n"
            "/clear - clear chat display (keeps LLM history)\n"
            "/close - close current session (cannot close last)\n"
            "/llm - list models for current session\n"
            "/llm <n> - switch model for current session\n"
            "/quit - exit TUI\n\n"
            "Unknown slash commands (for example /session.x=... or /resume) are sent to GenericAgent."
        )

    def _cmd_new(self, args: list[str]) -> None:
        name = " ".join(args).strip() or None
        session = self.add_session(name)
        self._system(f"Created session #{session.agent_id} {session.name!r}. Shared temp/memory are not isolated.")

    def _cmd_branch(self, args: list[str]) -> None:
        import copy
        old_session = self.current
        name = " ".join(args).strip() or f"{old_session.name}-branch"
        new_session = self.add_session(name)
        # Copy LLM backend history
        try:
            new_session.agent.llmclient.backend.history = copy.deepcopy(
                old_session.agent.llmclient.backend.history
            )
        except Exception as e:
            self._system(f"Branch warning: failed to copy history: {e}")
            return
        # Copy TUI display messages
        new_session.messages = copy.deepcopy(old_session.messages)
        new_session.task_seq = old_session.task_seq
        n = len(new_session.agent.llmclient.backend.history)
        self._system(f"Branched from #{old_session.agent_id} → #{new_session.agent_id} ({n} messages inherited).")

    def _cmd_rewind(self, args: list[str]) -> None:
        session = self.current
        if session.status == "running":
            self._system("Cannot rewind while running. /stop first.")
            return
        history = session.agent.llmclient.backend.history
        # Find real user turn boundaries — skip tool_result messages
        turns = []  # list of (index_in_history, preview_text)
        for i, msg in enumerate(history):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            # Pure string content is always a real user message
            if isinstance(content, str):
                turns.append((i, content[:60]))
                continue
            if isinstance(content, list):
                # Skip if content is purely tool_result blocks
                has_tool_result = any(b.get("type") == "tool_result" for b in content if isinstance(b, dict))
                if has_tool_result:
                    continue
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if texts and any(t.strip() for t in texts):
                    turns.append((i, (texts[0] or "")[:60]))
        if not turns:
            self._system("No rewindable turns in history.")
            return
        # Reverse numbering: 1 = most recent turn, 2 = second most recent, etc.
        # /rewind without args: show list
        if not args:
            lines = [f"Rewindable turns ({len(turns)} total, showing last 10):"]
            show = turns[-10:]
            for offset, (_, preview) in enumerate(reversed(show), 1):
                lines.append(f"  {offset}) {preview!r}")
            lines.append("/rewind <n> to rewind n turns (1 = undo last turn).")
            self._system("\n".join(lines))
            return
        # /rewind <n>: truncate last n turns
        try:
            n = int(args[0])
        except ValueError:
            self._system("Usage: /rewind <n> (1 = undo last turn)")
            return
        if n < 1 or n > len(turns):
            self._system(f"Invalid: range is 1-{len(turns)}")
            return
        # cut_at = index of the n-th turn from the end
        cut_at = turns[-n][0]
        removed = len(history) - cut_at
        history[:] = history[:cut_at]
        # Sync TUI messages: keep only messages before the corresponding user message
        real_user_indices = [i for i, msg in enumerate(session.messages) if msg.role == "user"]
        if n <= len(real_user_indices):
            cut_msg = real_user_indices[-n]
            session.messages = session.messages[:cut_msg]
        # Mark rewind in agentmain's working memory history
        try: session.agent.history.append(f"[USER]: /rewind {n}")
        except Exception: pass
        self._system(f"Rewound {n} turn(s). Removed {removed} history entries.")

    def _cmd_clear(self, args: list[str]) -> None:
        self.current.messages.clear(); self._refresh_all()

    def _cmd_close(self, args: list[str]) -> None:
        if len(self.sessions) <= 1:
            self._system("Cannot close the last session."); return
        del self.sessions[self.current_id]
        self.current_id = next(iter(self.sessions))
        self._refresh_all()

    def _cmd_switch(self, args: list[str]) -> None:
        if not args:
            self._system("Usage: /switch <id|name>")
            return
        key = " ".join(args)
        target: Optional[int] = None
        if key.isdigit() and int(key) in self.sessions:
            target = int(key)
        else:
            for sid, session in self.sessions.items():
                if session.name == key:
                    target = sid
                    break
        if target is None:
            self._system(f"No session found for {key!r}.")
            return
        self.current_id = target
        self._refresh_all()
        self._system(f"Switched to session #{target}.")

    def _cmd_sessions(self, args: list[str]) -> None:
        lines = []
        for sid, session in self.sessions.items():
            mark = "*" if sid == self.current_id else " "
            lines.append(f"{mark} #{sid} {session.name} [{session.status}] messages={len(session.messages)} task={session.current_task_id}")
        self._system("Sessions:\n" + "\n".join(lines))

    def _cmd_status(self, args: list[str]) -> None:
        self._cmd_sessions(args)

    def _cmd_stop(self, args: list[str]) -> None:
        session = self.current
        try:
            session.agent.abort()
            session.status = "stopping" if session.status == "running" else session.status
            self._system(f"Stop signal sent to session #{session.agent_id}.")
        except Exception as exc:
            self._system(f"Stop failed: {exc}")
        self._refresh_all()

    def _cmd_llm(self, args: list[str]) -> None:
        session = self.current
        if args:
            try:
                session.agent.next_llm(int(args[0]))
                self._system(f"Switched model to #{int(args[0])}.")
            except Exception as exc:
                self._system(f"Model switch failed: {exc}")
                return
        try:
            rows = session.agent.list_llms()
            self._system("Models:\n" + "\n".join(f"{'*' if cur else ' '} {i}: {name}" for i, name, cur in rows))
        except Exception as exc:
            self._system(f"Listing models failed: {exc}")

    def _system(self, text: str) -> None:
        if self.current_id is not None and self.current_id in self.sessions:
            self.current.messages.append(ChatMessage("system", text))
        self._refresh_all()

    def _refresh_all(self) -> None:
        if not self.is_mounted:
            return
        self._refresh_sidebar()
        self._refresh_status()
        self._refresh_log()

    def _session_last_user_query(self, session: AgentSession) -> str:
        """Return the last user message content, truncated for sidebar display."""
        for msg in reversed(session.messages):
            if msg.role == "user":
                text = msg.content.strip().replace("\n", " ")
                return self._truncate_display(text, 20)
        return ""

    def _session_last_summary(self, session: AgentSession) -> str:
        """Extract the last <summary> from the most recent assistant message."""
        for msg in reversed(session.messages):
            if msg.role == "assistant" and msg.content:
                matches = re.findall(r"<summary>\s*(.*?)\s*</summary>", msg.content, re.DOTALL)
                if matches:
                    text = matches[-1].strip().split("\n", 1)[0].replace("\n", " ")
                    return self._truncate_display(text, 20)
        return ""

    @staticmethod
    def _truncate_display(text: str, max_width: int) -> str:
        """Truncate text by display width (CJK chars count as 2)."""
        import unicodedata
        width = 0
        result = []
        for ch in text:
            w = 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
            if width + w > max_width:
                result.append("…")
                break
            result.append(ch)
            width += w
        return "".join(result)

    def _refresh_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Static)
        max_w = 26  # 30 - 2(border) - 2(padding)
        lines: list[str] = ["[b]Sessions[/b]", ""]
        for sid, session in self.sessions.items():
            mark = "▶" if sid == self.current_id else " "
            last_q = self._session_last_user_query(session)
            last_s = self._session_last_summary(session)
            status_style = "green" if session.status == "running" else "dim"
            # Header line: "▶ #1 name status" — truncate name if needed
            prefix = f"{mark} #{sid} "
            suffix = f" {session.status}"
            name_max = max_w - len(prefix) - len(suffix)
            name_disp = self._truncate_display(session.name, max(name_max, 4))
            lines.append(f"{prefix}{name_disp} [{status_style}]{session.status}[/{status_style}]")
            if last_q:
                lines.append(f"   [dim]Q:{last_q}[/dim]")
            if last_s:
                lines.append(f"   [dim]S:{last_s}[/dim]")
        lines.append("")
        lines.append("[dim]/new, /switch, Ctrl+N[/dim]")
        lines.append("[dim]I have memory, just say what you want[/dim]")
        sidebar.update("\n".join(lines))

    def _refresh_status(self) -> None:
        status = self.query_one("#status", Static)
        if self.current_id is None:
            status.update("No session")
            return
        session = self.current
        try:
            model = session.agent.get_llm_name(model=True)
        except Exception:
            model = "unknown"
        status.update(
            f"[b]#{session.agent_id} {session.name}[/b]  status={session.status}  task={session.current_task_id}  model={model}\n"
            "Enter message or /help. Per-task queue streaming is enabled (inc_out=True)."
        )

    def action_toggle_fold(self) -> None:
        self.fold_mode = not self.fold_mode
        # Invalidate cached panels for assistant messages since fold state changed
        if self.current_id is not None:
            for msg in self.current.messages:
                if msg.role == "assistant":
                    msg._rendered_panel = None
        self._refresh_log()
        mode_label = "folded" if self.fold_mode else "expanded"
        self.notify(f"Display mode: {mode_label} (Ctrl+F to toggle)")

    def _refresh_log(self) -> None:
        log = self.query_one("#log", RichLog)
        log.clear()
        if self.current_id is None:
            return
        all_msgs = self.current.messages
        # Limit to last 150 messages for performance
        if len(all_msgs) > 150:
            display_msgs = all_msgs[-150:]
            log.write(Text(f"  ↑ {len(all_msgs) - 150} older messages hidden ↑", style="dim italic"))
        else:
            display_msgs = all_msgs
        # Collect recent task_ids to only expand the latest 3 tasks
        recent_task_ids: set[int] = set()
        if not self.fold_mode:
            seen: list[int] = []
            for msg in reversed(display_msgs):
                if msg.role == "assistant" and msg.task_id not in seen:
                    seen.append(msg.task_id)
                    if len(seen) == 5:
                        break
            recent_task_ids = set(seen)
        for msg in display_msgs:
            if msg.role == "user":
                if msg._rendered_panel is None:
                    msg._rendered_panel = Panel(Markdown(msg.content), title="You", border_style="blue")
                log.write(msg._rendered_panel)
            elif msg.role == "assistant":
                if msg.done and msg._rendered_panel is not None:
                    log.write(msg._rendered_panel)
                else:
                    suffix = "" if msg.done else "\n▌"
                    # Fold older tasks even in unfold mode to reduce render cost
                    should_fold = self.fold_mode or (msg.task_id not in recent_task_ids)
                    content = render_folded_text(msg.content) if should_fold else msg.content
                    panel = Panel(Markdown(content + suffix), title=f"Agent task {msg.task_id}", border_style="green")
                    if msg.done:
                        msg._rendered_panel = panel
                    log.write(panel)
            else:
                if msg._rendered_panel is None:
                    msg._rendered_panel = Panel(Text(msg.content), title="System", border_style="yellow")
                log.write(msg._rendered_panel)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Textual TUI for GenericAgent")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    app = GenericAgentTUI()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
