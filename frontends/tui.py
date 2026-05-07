#!/usr/bin/env python3
"""Terminal UI frontend for GenericAgent.

Run from the project root:
    python frontends/tui.py

Optional packages for the richer experience:
    pip install rich prompt_toolkit
"""

from __future__ import annotations

import argparse
import asyncio
import os
import queue
import re
import sys
import threading
from dataclasses import dataclass
from typing import Iterable


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
for path in (PROJECT_ROOT, SCRIPT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}
SHARED_CHAT_COMMANDS = {
    "/help",
    "/status",
    "/stop",
    "/new",
    "/restore",
    "/continue",
    "/llm",
}
TOOL_PREFIX = "\U0001f6e0"


def is_shared_chat_command(text: str) -> bool:
    """Return True for slash commands already implemented by chat frontends."""
    op = (text or "").strip().split(maxsplit=1)[0].lower()
    return op in SHARED_CHAT_COMMANDS


def is_exit_command(text: str) -> bool:
    return (text or "").strip().lower() in EXIT_COMMANDS


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    text: str


class StreamFormatter:
    """Convert raw agent stream chunks into small terminal rendering events."""

    _turn_re = re.compile(r"^\*{0,2}LLM Running \(Turn (\d+)\) \.\.\.\*{0,2}\s*$")
    _progress_prefixes = (
        "[Action]",
        "[Status]",
        "[Info]",
        "[Warn]",
        "[Debug]",
        "JS ",
    )

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[StreamEvent]:
        self._buffer += chunk or ""
        events: list[StreamEvent] = []
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            events.append(self._classify(line.rstrip("\r")))
        return events

    def flush(self) -> list[StreamEvent]:
        if not self._buffer:
            return []
        line = self._buffer
        self._buffer = ""
        return [self._classify(line.rstrip("\r"))]

    def _classify(self, line: str) -> StreamEvent:
        stripped = line.strip()
        if not stripped:
            return StreamEvent("blank", "")

        turn_match = self._turn_re.match(stripped)
        if turn_match:
            return StreamEvent("turn", f"Turn {turn_match.group(1)}")

        if stripped.startswith(TOOL_PREFIX):
            return StreamEvent("tool", stripped)

        if stripped.startswith(self._progress_prefixes):
            return StreamEvent("progress", stripped)

        return StreamEvent("text", line)


class PlainRenderer:
    """Fallback renderer when Rich is unavailable."""

    def banner(self, agent) -> None:
        print("GenericAgent TUI")
        print(f"LLM: [{agent.llm_no}] {agent.get_llm_name()}")
        print("Commands: /help, /status, /llm, /continue, /new, /restore, /stop, /exit")
        print()

    def prompt_text(self) -> str:
        return "GA> "

    def system(self, text: str) -> None:
        print(text)

    def error(self, text: str) -> None:
        print(f"ERROR: {text}", file=sys.stderr)

    def render_events(self, events: Iterable[StreamEvent]) -> None:
        for event in events:
            self.render_event(event)

    def render_event(self, event: StreamEvent) -> None:
        if event.kind == "blank":
            print()
        elif event.kind == "turn":
            print(f"\n-- {event.text} --")
        elif event.kind in {"tool", "progress"}:
            print(f"  {event.text}")
        else:
            print(event.text)

    def render_block(self, text: str) -> None:
        print(text or "")


class RichRenderer(PlainRenderer):
    """Rich-based renderer for a compact nanobot-like terminal experience."""

    def __init__(self) -> None:
        from rich.console import Console

        self.console = Console()

    def banner(self, agent) -> None:
        from rich.panel import Panel
        from rich.table import Table

        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        table.add_row("LLM", f"[{agent.llm_no}] {agent.get_llm_name()}")
        table.add_row("Commands", "/help  /status  /llm  /continue  /new  /restore  /stop  /exit")
        self.console.print(Panel(table, title="GenericAgent TUI", border_style="cyan"))

    def system(self, text: str) -> None:
        from rich.text import Text

        self.console.print(Text(text, style="dim"))

    def error(self, text: str) -> None:
        from rich.text import Text

        line = Text("ERROR: ", style="bold red")
        line.append(text)
        self.console.print(line, stderr=True)

    def render_event(self, event: StreamEvent) -> None:
        from rich.text import Text

        if event.kind == "blank":
            self.console.print()
        elif event.kind == "turn":
            self.console.print(f"\n[bold cyan]{event.text}[/bold cyan]")
        elif event.kind == "tool":
            line = Text("  ")
            line.append(event.text, style="magenta")
            self.console.print(line)
        elif event.kind == "progress":
            line = Text("  ")
            line.append(event.text, style="dim")
            self.console.print(line)
        else:
            self.console.print(Text(event.text, overflow="fold"))

    def render_block(self, text: str) -> None:
        from rich.markdown import Markdown

        self.console.print(Markdown(text or ""))


def make_renderer(prefer_rich: bool = True) -> PlainRenderer:
    if not prefer_rich:
        return PlainRenderer()
    try:
        return RichRenderer()
    except Exception:
        return PlainRenderer()


class SharedCommandAdapter:
    """Reuse AgentChatMixin command handling and collect its text output."""

    def __init__(self, agent) -> None:
        from chatapp_common import AgentChatMixin

        class _Adapter(AgentChatMixin):
            label = "TUI"
            source = "tui"

            def __init__(self, wrapped_agent) -> None:
                super().__init__(wrapped_agent, {})
                self.messages: list[str] = []

            async def send_text(self, chat_id, content, **ctx) -> None:
                self.messages.append(content or "")

            def run(self, command: str) -> list[str]:
                self.messages = []
                asyncio.run(self.handle_command("tui", command))
                return list(self.messages)

        self._adapter = _Adapter(agent)

    def handle(self, command: str) -> list[str]:
        return self._adapter.run(command)


def make_prompt_session(history_path: str):
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory

        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        return PromptSession(history=FileHistory(history_path), enable_open_in_editor=False)
    except Exception:
        return None


def read_prompt(session, prompt_text: str) -> str:
    if session is None:
        return input(prompt_text)

    try:
        from prompt_toolkit.patch_stdout import patch_stdout

        with patch_stdout(raw=True):
            return session.prompt(prompt_text)
    except EOFError:
        raise


def drain_agent_queue(agent, display_queue, renderer: PlainRenderer) -> None:
    formatter = StreamFormatter()
    streamed = False
    stop_requested = False
    renderer.system("Running agent. Press Ctrl-C to request stop.")

    while True:
        try:
            item = display_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        except KeyboardInterrupt:
            if stop_requested:
                raise
            stop_requested = True
            agent.abort()
            renderer.system("Stop requested. Waiting for the current turn to settle...")
            continue

        if "next" in item:
            streamed = True
            renderer.render_events(formatter.feed(item.get("next", "")))

        if "done" in item:
            renderer.render_events(formatter.flush())
            if not streamed:
                renderer.render_block(item.get("done", ""))
            renderer.system("Task finished.")
            return


def run_once(agent, prompt: str, renderer: PlainRenderer) -> None:
    display_queue = agent.put_task(prompt, source="tui")
    drain_agent_queue(agent, display_queue, renderer)


def interactive_loop(agent, renderer: PlainRenderer, history_path: str) -> None:
    command_adapter = SharedCommandAdapter(agent)
    session = make_prompt_session(history_path)
    renderer.banner(agent)

    while True:
        try:
            raw = read_prompt(session, renderer.prompt_text()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not raw:
            continue
        if is_exit_command(raw):
            return

        if is_shared_chat_command(raw):
            try:
                for message in command_adapter.handle(raw):
                    renderer.render_block(message)
            except Exception as exc:
                renderer.error(str(exc))
            continue

        try:
            run_once(agent, raw, renderer)
        except KeyboardInterrupt:
            agent.abort()
            renderer.system("Interrupted.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GenericAgent terminal UI")
    parser.add_argument("--llm-no", type=int, default=0, help="LLM config index")
    parser.add_argument("--verbose", action="store_true", help="show full agent loop/tool details")
    parser.add_argument("--plain", action="store_true", help="disable Rich rendering")
    parser.add_argument("--once", help="run one prompt and exit")
    parser.add_argument(
        "--history",
        default=os.path.join(PROJECT_ROOT, "temp", "tui_history.txt"),
        help="prompt history file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from agentmain import GeneraticAgent

    agent = GeneraticAgent()
    agent.next_llm(args.llm_no)
    agent.verbose = bool(args.verbose)
    agent.inc_out = True

    worker = threading.Thread(target=agent.run, daemon=True)
    worker.start()

    renderer = make_renderer(prefer_rich=not args.plain)
    if args.once:
        renderer.banner(agent)
        if is_shared_chat_command(args.once):
            command_adapter = SharedCommandAdapter(agent)
            for message in command_adapter.handle(args.once):
                renderer.render_block(message)
        elif not is_exit_command(args.once):
            run_once(agent, args.once, renderer)
    else:
        interactive_loop(agent, renderer, args.history)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
