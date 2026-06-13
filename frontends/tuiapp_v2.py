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
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import subprocess
import shutil

# Local: cross-platform shortcut-label formatter (Win/Linux "Ctrl+B" vs mac "⌃B").
# Imported early because _TIPS at module load time uses fmt_key().
from keysym import fmt_key, fmt_keys  # noqa: E402
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Callable, Optional

def _ensure_tui_deps() -> None:
    """Try the imports; on first miss, pip-install the wheel and retry once.
    Keeps `ga-cli` working on a fresh Python (Windows / macOS / Linux) where
    Textual or Rich hasn't been installed yet. Bails with a clear message if
    pip itself is unavailable or the install fails — never silently."""
    import importlib.util, subprocess
    needed = ("rich", "textual")
    missing = [m for m in needed if importlib.util.find_spec(m) is None]
    if not missing: return
    print(f"[ga-tui] installing {' '.join(missing)} into {sys.executable} ...", file=sys.stderr)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])
    except Exception as e:
        print(f"[ga-tui] auto-install failed: {e}\n    fix: {sys.executable} -m pip install {' '.join(missing)}",
              file=sys.stderr)
        raise SystemExit(2)
    for m in missing: importlib.invalidate_caches()


_ensure_tui_deps()
try:
    from rich.markdown import Markdown
    from rich.table import Table
    from rich.text import Text
    from textual import events
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.geometry import Region
    from textual.message import Message
    from textual.screen import ModalScreen
    from textual.widget import Widget
    from textual.widgets import Input, OptionList, SelectionList, Static, TextArea
    from textual.widgets.option_list import Option
    from textual.widgets.selection_list import Selection
except ModuleNotFoundError as exc:
    print(f"[ga-tui] still missing: {exc.name}. Run: {sys.executable} -m pip install rich textual",
          file=sys.stderr)
    raise SystemExit(2) from exc


def _hint_terminal_capabilities() -> None:
    """Warn once at startup if we detect a terminal known to render Textual
    poorly (e.g. bare mintty/git-bash). The UI still works, but visuals like
    truecolor chips and unicode glyphs may degrade. Heuristic-only — never
    blocks startup, just prints a hint to stderr.
    """
    if os.name != "nt": return
    if os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM"):
        return  # Windows Terminal / iTerm2 / VSCode / Hyper — all fine
    if os.environ.get("TERM", "").startswith("xterm"):
        # mintty exports TERM=xterm-256color. Textual still renders, but
        # mouse + truecolor handling is patchy. Point at the better option.
        print("[ga-tui] hint: best rendering on Windows Terminal (`wt`) — "
              "the mintty/git-bash console may clip colors or mouse events.",
              file=sys.stderr)


_hint_terminal_capabilities()


# Strip terminal control sequences from subprocess stdout but keep SGR color codes,
# otherwise Text.from_ansi loses color downstream.
_ANSI_CONTROL_RE = re.compile(
    r"\x1b\[\?[\d;]*[hl]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[=>]"
)

# Strip SGR-only codes — used when we need plain text for downstream parsing
# (e.g. mapping narrow rendered output to source positions for selection).
_ANSI_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")

# Strip the leading turn marker that agent_loop yields per turn — covers
# both the default `**LLM Running (Turn N) ...**` and the task-mode short
# `**Turn N ...**` (agent_loop.py:52 switches when handler.parent.task_dir
# is set; v2 sets task_dir for the `_stop` / `_keyinfo` consume paths).
# fold_turns still needs the marker in source content to split turns, so we only strip at
# render time. Applies to the live (last) text segment, since folded turns don't include it.
_TURN_MARKER_RE = re.compile(r"^\s*\**(?:LLM Running \()?Turn \d+\)?[^\n]*\**\s*", re.MULTILINE)

# Commonmark task-list patterns: `- [ ] foo` / `* [x] foo` / `+ [X] foo`.
# Group 1 keeps the bullet + leading space so we can substitute the [ ] / [x]
# portion only and let the Markdown renderer still treat the line as a list item.
_TASKLIST_OPEN_RE = re.compile(r"^(\s*[-*+] )\[ \] ", re.MULTILINE)
_TASKLIST_DONE_RE = re.compile(r"^(\s*[-*+] )\[[xX]\] ", re.MULTILINE)

# `<tool_use>{...}</tool_use>` envelope emitted by the streaming layer in
# llmcore. Agents emit one per tool call; the wrapped object always has
# {"name": ..., "arguments": ...}. We replace the whole envelope so the raw
# JSON braces/quotes never leak into the markdown render.
_TOOL_USE_RE = re.compile(r"<tool_use>\s*(\{.*?\})\s*</tool_use>", re.DOTALL)

# Agent-internal metadata tags. The sidebar's `S:` and the fold title already
# surface the summary; the chat body should not show the raw tag. Stripping is
# also required because `<summary>X</summary>\n<body>` (no blank line) is parsed
# as a CommonMark HTML block that swallows the following body line, so the
# model's actual reply disappears from the rendered output.
# Only the start-of-line form triggers the CommonMark HTML-block swallow; mid-line
# occurrences are inline HTML that Rich renders as text, and tags inside backticks
# / fenced / indented code must stay verbatim. Anchoring sidesteps all of those.
_META_TAG_RE = re.compile(
    r"^[ ]{0,3}<(summary|thinking)>.*?</\1>\s*",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)


# Rotating usage tips, picked once per launch.
_TIPS = (
    "Tip: 按 / 唤起命令面板；任何命令都能用方向键选择。",
    "Tip: /rename <name> 持久化会话名；/continue <name> 跨次重开同名会话。",
    "Tip: /cost 查看 token 用量；/cost all 列出所有会话的累计。",
    "Tip: /continue 列出最近 20 个历史会话，按 Enter 进入。",
    "Tip: /btw <问题> 让 side-agent 回答而不打断主任务。",
    f"Tip: {fmt_key('ctrl+b')} 折叠侧栏；{fmt_key('ctrl+o')} 切换长输出折叠；{fmt_key('ctrl+/')} 查看快捷键。",
    f"Tip: {fmt_key('ctrl+n')} 新建会话；{fmt_keys('ctrl+up','ctrl+down')} 在多个会话间切换。",
    "Tip: 粘贴图片 / 文件后会自动折叠成 [Image #N] / [File #N] 占位符。",
    f"Tip: 多行输入用 {fmt_key('ctrl+j')} 换行；Enter 直接发送。",
    "Tip: /rewind <n> 回退最近 n 轮对话；/stop 中止当前任务。",
    "Tip: /export clip 把上一条回复复制到剪贴板；/export all 给出完整日志路径。",
    "Tip: /branch [name] 从当前历史分裂出新会话，互不污染。",
    "Tip: ask_user 题目里写 [多选] 自动切到 SelectionList；任何 picker 都有 \"Type something\" 走自由输入。",
    "Tip: plan 模式下的 todo 会渲染在消息区与输入框之间的 📋 Plan 卡片，完成后自动消失。",
    "Tip: /update 让主 agent 自动 git pull 并核查影响面；/autorun 进入 autonomous 自主模式。",
    "Tip: /morphling <目标> 启用蒸馏吞噬外部技能。",
    "Tip: /goal <目标> 进入 Goal 模式（缺 condition 时会回头问你预算 / worker 上限）。",
    "Tip: /hive <目标> 进入 Hive 多 worker 协作；/scheduler 调出 reflect 任务多选启动器。",
    "Tip: /conductor <任务> 直接交给 frontends/conductor.py 做多 subagent 编排。",
    "Tip: /update 是双分支 upstream 同步 —— 先 diff 预演，再分别快进。",
    "Tip: /scheduler 里再点一下已勾选的任务可以 stop —— 取消勾选 = 停止。",
    f"Tip: {fmt_key('ctrl+s')} 把当前输入 stash 起来，下次 / 打开 picker 时还在。",
)


def _random_tip(exclude: str = "") -> str:
    """Pick a tip distinct from `exclude` so rotation doesn't repeat."""
    import random
    pool = [t for t in _TIPS if t != exclude] or list(_TIPS)
    return random.choice(pool)


def _tip_line(text: str = ""):
    """`└ Tip: …` as styled Rich Text; empty `text` → blank pulse line."""
    from rich.text import Text as _T
    t = _T()
    if not text:
        return t
    t.append("└ ", style="#6e7681")
    t.append("Tip: ", style="bold #6e7681")
    t.append(text.removeprefix("Tip: "), style="#6e7681")
    return t

# Defensive cleaners for ask_user candidates. The model occasionally smuggles
# JSON envelope debris (`"}`, `]`, `\`) in or out of a candidate string, or
# mashes several options together with `\n`. Both arrive as opaque strings
# from `_install_ask_user_hook` — we sanitize at the boundary so the picker
# never has to render broken text.
_CAND_LEFT_TRIM = re.compile(r'^[",\[\]{}\\\s]+')
_CAND_RIGHT_TRIM = re.compile(r'[",\[\]{}\\\s]+$')
_CAND_NUMBER_PFX = re.compile(r'^\d+\s*[.)、：:）．]\s*')


def _sanitize_candidates(raw) -> list[str]:
    """Normalize whatever the agent passes as `candidates` into a clean,
    deduped list of human-facing strings. Handles a `list[str]` of clean
    options (no-op), as well as the failure modes we've seen in the wild:
    JSON debris glued to one entry, a single string with embedded `\\n` that
    really meant N entries, numbered prefixes (`3. foo`) the picker would
    re-number, and pathologically long entries.
    """
    out: list[str] = []
    items = raw if isinstance(raw, list) else [raw] if raw else []
    for item in items:
        s = str(item) if item is not None else ""
        # An entry with literal `\n` or real newlines is N entries mashed together.
        for line in s.replace("\\n", "\n").splitlines() or [s]:
            line = _CAND_LEFT_TRIM.sub("", line)
            line = _CAND_RIGHT_TRIM.sub("", line)
            line = _CAND_NUMBER_PFX.sub("", line)
            line = line.strip()
            if not line: continue
            if len(line) > 200: line = line[:200] + "…"
            if line not in out: out.append(line)
    return out


def _render_tool_use_block(match) -> str:
    """Render a `<tool_use>{...}</tool_use>` envelope as readable markdown.

    For `ask_user` with candidates we deliberately render only the question —
    the interactive picker (drained in `_drain_ask_user_events`) shows the
    actual choices and owns the user input. Rendering candidates here too
    would double up the visible card.

    For `ask_user` without candidates (pure free-text prompt) the markdown
    stays the source of truth, so we still emit `> 💬 question`.

    All other tools collapse to a single `tool: <name>` line — the full fold
    machinery still hides the raw turn body when fold-mode is on.
    """
    try:
        obj = json.loads(match.group(1))
    except Exception:
        return match.group(0)
    name = obj.get("name", "")
    args = obj.get("arguments") or {}
    if name == "ask_user":
        question = (args.get("question") or "").strip()
        if not question:
            return ""
        return f"\n> 💬 **{question}**\n"
    return f"\n*tool: {name}*\n"


# ---------------------------------------------------------------------------
# Write-tool diff rendering.
#
# `file_patch` / `file_write` are the only tools whose *content* matters at a
# glance, so we render them as a real, themed diff instead of the generic
# `tool: <name>` line. The render produces two parallel strings:
#   - an ANSI string (line-number gutter + ±/space sign + low-saturation row
#     background) injected into the colored "narrow" markdown stream, and
#   - a plain string (identical visible text, no SGR) injected into the
#     "wide" stream so `_align_md_renders` can pair them line-for-line and
#     mouse-selection / copy still works.
# Both strings have the SAME line count and the SAME post-rstrip text, which is
# the invariant `_align_md_renders` relies on (K==W branch).
#
# The verbose display stream (agent_loop.py:78) shows tool args as pretty JSON
# inside a ```` ```text ```` fence — but `get_pretty_json` turns escaped `\n`
# into *real* newlines, so multi-line content no longer parses as JSON. Instead
# of parsing the display text, `_install_write_snapshot_hook` captures the real
# structured `args` dict (plus the file's pre-write content for `overwrite`)
# from a `tool_before` hook, keyed by `hash(get_pretty_json(args))`. At render
# time we hash the fence body and look the capture back up — content-addressed,
# so it survives re-renders and pairs each block with its exact call.
# ---------------------------------------------------------------------------

# hash(get_pretty_json(args)) -> {"name", "args", "existed", "old"}
_WRITE_CAP: dict[int, dict] = {}

# Cap the rendered diff body so a 2000-line file_write can't flood the chat.
_DIFF_MAX_ROWS = 80
_DIFF_CONTEXT = 3

# Visual-only left margin for the rendered card: prefixed to the ANSI (narrow)
# stream but NOT the plain (wide) copy source, so mouse-copy stays margin-free.
# `_align_md_renders` maps the offset via line_indents (single-line groups), and
# `_md_line_has_box_drawing` exempts the card's `└─ ` line from the table
# passthrough that would otherwise copy the visible (margined) text.
_DIFF_MARGIN = 2

# Matches the verbose tool display agent_loop.py emits:
#   🛠️ Tool: `file_patch`  📥 args:
#   ````text
#   { ...pretty json... }
#   ````
# Group 1 = tool name, group 2 = the (newline-mangled) pretty-JSON fence body,
# which we hash to recover the real args captured by the snapshot hook.
_VERBOSE_WRITE_RE = re.compile(
    r"🛠️ Tool: `(file_write|file_patch|file_read|code_run)`  📥 args:\n`{4}\w*\n(.*?)\n`{4}"
    # Also swallow the dispatch output fence that immediately follows
    # (`[Action]…`/`{status}` lines) — its info moves into the diff header.
    r"(?:\s*`{5}\n(.*?)\n`{5})?",
    re.DOTALL,
)


# Any other tool's verbose block — same shape, any tool name. Substituted AFTER
# `_VERBOSE_WRITE_RE` (write blocks are already sentinels by then), purely to
# add the left margin while keeping the Rich-markdown look unchanged.
_VERBOSE_TOOL_RE = re.compile(
    r"🛠️ Tool: `(\w+)`  📥 args:\n`{4}\w*\n.*?\n`{4}"
    r"(?:\s*`{5}\n.*?\n`{5})?",
    re.DOTALL,
)


def _fence_status(fence_body):
    """Per-block outcome from the dispatch-output fence trailing a write call
    (a `{"status": ..., "msg": ...}` line). This is the only *per-occurrence*
    signal: `_WRITE_CAP` is keyed by args, so two identical calls (fail → mkdir
    → retry) share one capture and its stored status is last-write-wins."""
    for line in (fence_body or "").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict) and "status" in d:
            return d.get("status"), str(d.get("msg") or "")
    return None


def _sgr_fg(hex_color: str) -> str:
    r, g, b = _hex_rgb(hex_color)
    return f"\x1b[38;2;{r};{g};{b}m"


def _sgr_bg(hex_color: str) -> str:
    r, g, b = _hex_rgb(hex_color)
    return f"\x1b[48;2;{r};{g};{b}m"


_SGR_RESET = "\x1b[0m"


def _chop_cells(s: str, w: int) -> list[str]:
    """Split into chunks each ≤ w display cells (CJK counts as 2)."""
    from rich.cells import cell_len
    out, cur, cw = [], [], 0
    for ch in s:
        c = cell_len(ch)
        if cur and cw + c > w:
            out.append("".join(cur)); cur, cw = [ch], c
        else:
            cur.append(ch); cw += c
    if cur:
        out.append("".join(cur))
    return out or [""]


def _cell_tail(s: str, n: int) -> str:
    """Keep the tail of `s` within n cells, prefixing … if truncated."""
    from rich.cells import cell_len
    if cell_len(s) <= n:
        return s
    if n <= 1:
        return "…"
    out, w = [], 0
    for ch in reversed(s):
        c = cell_len(ch)
        if w + c > n - 1:
            break
        out.append(ch); w += c
    return "…" + "".join(reversed(out))


def _cell_head(s: str, n: int) -> str:
    """Keep the head of `s` within n cells, suffixing … if truncated.
    (省略末尾 — names: keep the start, drop the tail.)"""
    from rich.cells import cell_len
    if cell_len(s) <= n:
        return s
    if n <= 1:
        return "…"
    out, w = [], 0
    for ch in s:
        c = cell_len(ch)
        if w + c > n - 1:
            break
        out.append(ch); w += c
    return "".join(out) + "…"


def _cell_mid(s: str, n: int) -> str:
    """Keep head+tail of `s` within n cells, eliding the middle with ….
    (省略中间 — paths: the project root and the leaf both stay visible.)"""
    from rich.cells import cell_len
    if cell_len(s) <= n:
        return s
    if n <= 1:
        return "…"
    avail = n - 1                      # reserve one cell for …
    head_budget = avail - avail // 2   # head gets the rounding bias
    tail_budget = avail // 2
    head, w = [], 0
    for ch in s:
        c = cell_len(ch)
        if w + c > head_budget:
            break
        head.append(ch); w += c
    tail, w = [], 0
    for ch in reversed(s):
        c = cell_len(ch)
        if w + c > tail_budget:
            break
        tail.append(ch); w += c
    return "".join(head) + "…" + "".join(reversed(tail))


class _CardWriter:
    """Accumulates a tool card's two parallel streams: `ansi` (narrow, colored,
    later margined) and `plain` (wide, the copy source — no margin). `row()`
    takes (text, color) segments for simple uniform lines; `raw()` takes
    pre-built ansi/plain for rows with gutters/backgrounds. `finish()` applies
    the visual-only left margin to the ANSI stream ONLY (keeping it out of the
    copy source) and joins both. Shared by all three tool cards so the _hrow /
    margin boilerplate lives in one place."""
    __slots__ = ("ansi", "plain")

    def __init__(self):
        self.ansi, self.plain = [], []

    def row(self, *segs):
        self.plain.append("".join(s for s, _ in segs))
        self.ansi.append("".join(f"{_sgr_fg(c)}{s}" for s, c in segs) + _SGR_RESET)

    def raw(self, ansi_line, plain_line):
        self.ansi.append(ansi_line)
        self.plain.append(plain_line)

    def finish(self):
        m = " " * _DIFF_MARGIN
        return "\n".join(m + l for l in self.ansi), "\n".join(self.plain)


def _card_status_row(cw, base_segs, err, detail, width):
    """Emit a card's status-bearing line: `base_segs` followed by an inline red
    `✗ detail` if it fits, else a bare `✗` with `detail` wrapped onto indented
    red lines. `detail=''` with `err=True` yields a bare ✗. The single place
    the three cards' failure-header layout lives."""
    from rich.cells import cell_len
    col = _diff_colors()
    base_plain = "".join(s for s, _ in base_segs)
    mark = (f"  ✗ {detail}" if detail else "  ✗") if err else ""
    inline = (not detail) or cell_len(base_plain + mark) <= width
    cw.row(*base_segs,
           *([(mark if inline else "  ✗", col["del_sign"])] if err else []))
    if err and not inline and detail:
        for chunk in _chop_cells(detail, max(8, width - 3)):
            cw.row(("   " + chunk, col["del_sign"]))


def _card_note(cw, text):
    """A card annotation line (truncation / omission notes), head color. One
    style so every card's `… +N 行…` note reads alike."""
    cw.row((text, _diff_colors()["head"]))


def _emit_gutter(cw, content_w, segs, glyph_first, glyph_rest):
    """Emit (text, color) segments behind a 2-col gutter: `glyph_first` on the
    block's first physical row, `glyph_rest` after; soft-wraps each line, gutter
    always dim. The code card's command (`│ `) and output (`└ `/`  `) blocks
    share it."""
    col = _diff_colors()
    first = True
    for text, color in segs:
        for chunk in _chop_cells(text, content_w):
            g = glyph_first if first else glyph_rest
            cw.raw(f"{_sgr_fg(col['gutter'])}{g}{_sgr_fg(color)}{chunk}{_SGR_RESET}",
                   f"{g}{chunk}".rstrip())
            first = False


def _diff_colors() -> dict:
    """Derive diff colors from the live `_palette`. Backgrounds/foregrounds are
    blended *from the theme's own bg/fg*, so the same code yields dark tints on
    a dark theme and light tints on a light one — no explicit dark/light fork."""
    p = _palette
    bg = p.get("bg") or "#0d1117"
    fg = p.get("fg") or "#c9d1d9"
    # Fixed add/del hues so the diff semantics stay green/red on any theme
    # (palette["green"] falls back to a theme's primary, which isn't always
    # green). Backgrounds are still blended *from the theme bg*, so the tint
    # auto-darkens on dark themes and lightens on light ones.
    green = "#3fb950"
    red = "#e5534b"
    return {
        "bg": bg,
        "add_bg": _mix(bg, green, 0.18),
        "del_bg": _mix(bg, red, 0.18),
        "add_fg": _mix(fg, green, 0.50),
        "del_fg": _mix(fg, red, 0.50),
        "add_sign": green,
        "del_sign": red,
        "ctx_fg": _mix(bg, fg, 0.78),
        "gutter": p.get("dim") or _mix(bg, fg, 0.35),
        "head": p.get("muted") or _mix(bg, fg, 0.55),
    }


def _diff_hunks(old: str, new: str, context: int = _DIFF_CONTEXT) -> list[list[tuple]]:
    """Group a diff into hunks of `(sign, line_no, text)` rows. `sign` is one of
    '+'/'-'/' '; `line_no` is the new-file number for '+'/' ' and the old-file
    number for '-'. Uses difflib's grouped opcodes so each hunk carries `context`
    unchanged lines around the change, and gaps collapse into separate hunks."""
    from difflib import SequenceMatcher
    a, b = old.splitlines(), new.splitlines()
    sm = SequenceMatcher(None, a, b, autojunk=False)
    hunks: list[list[tuple]] = []
    for group in sm.get_grouped_opcodes(context):
        rows: list[tuple] = []
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for k in range(i2 - i1):
                    rows.append((" ", j1 + k + 1, b[j1 + k]))
            else:
                for k in range(i1, i2):
                    rows.append(("-", k + 1, a[k]))
                for k in range(j1, j2):
                    rows.append(("+", k + 1, b[k]))
        if rows:
            hunks.append(rows)
    return hunks


def _insert_hunk(text: str, start_no: int = 1) -> list[list[tuple]]:
    """A single all-'+' hunk for a brand-new / appended / prepended file."""
    return [[("+", start_no + k, line) for k, line in enumerate(text.splitlines())]]


def _render_write_diff(name: str, args: dict, existed: bool, old: str, width: int,
                       status: str = None, msg: str = ""):
    """Render a file_write/file_patch call as a themed diff.

    `existed`/`old` describe the target before the write (captured by the hook).
    For file_patch, `old` (the pre-write full file) lets us render a whole-file
    diff with real line numbers + surrounding context; without it we fall back to
    diffing just the old/new fragment. `status` is the tool outcome
    ('success'/'error'); success stays silent, error tags the header with a red ✗
    (+msg) so the noisy `[Action]`/`{status}` lines can be dropped. Returns
    `(ansi, plain)` parallel strings, or `None` to fall back."""
    args = args or {}
    old = old or ""
    width = max(20, width - _DIFF_MARGIN)  # body math sees the post-margin width
    path = str(args.get("path") or "").strip()
    if not path:
        return None

    display_mode = None
    if name == "file_patch":
        old_c = str(args.get("old_content") or "")
        new_c = str(args.get("new_content") or "")
        if not old_c and not new_c:
            return None
        # Whole-file diff (real line numbers + context around the change) when we
        # have the pre-write full file and old_content matches exactly once;
        # otherwise diff just the fragment (no file context available, e.g.
        # /continue without a tracked full file).
        if existed and old and old_c and old.count(old_c) == 1:
            hunks = _diff_hunks(old, old.replace(old_c, new_c, 1))
        else:
            hunks = _diff_hunks(old_c, new_c)
    elif name == "file_write":
        new = args.get("content")
        if new is None:
            return None  # content lives in the response body, not args — can't diff
        new = str(new)
        mode = str(args.get("mode") or "overwrite")
        display_mode = mode
        if mode in ("append", "prepend"):
            if existed:
                # Show append/prepend with the same surrounding unchanged context
                # as file_patch by diffing the whole pre/post file, instead of an
                # isolated all-green insertion block.
                hunks = _diff_hunks(old, old + new if mode == "append" else new + old)
            else:
                hunks = _insert_hunk(new)
        elif existed and old != new:
            hunks = _diff_hunks(old, new)
        elif existed:
            return None  # overwrite with identical content — nothing to diff
        else:
            hunks = _insert_hunk(new)
    else:
        return None

    if not any(hunks):
        return None

    added = sum(1 for h in hunks for r in h if r[0] == "+")
    removed = sum(1 for h in hunks for r in h if r[0] == "-")
    max_no = max((r[1] for h in hunks for r in h), default=1)
    lw = max(2, len(str(max_no)))
    content_w = max(8, width - (lw + 3))  # "<no> <sign> " prefix
    col = _diff_colors()

    from rich.cells import cell_len, set_cell_size

    cw = _CardWriter()

    # Header: compact tool-call line + tree child path/counts. Keep file_patch
    # bare, but show the file_write mode as file_write(overwrite|append|prepend).
    # Path is tail-truncated by display width so the header never wraps.
    err = (status == "error")
    msg = " ".join(str(msg or "").split())
    tool_label = name if name == "file_patch" else f"{name}({display_mode})"
    add_seg, del_seg = f"  +{added}", f" -{removed}"
    child_prefix = "└─ "
    avail = width - cell_len(child_prefix + add_seg + del_seg) - (cell_len("  ✗") if err else 0)
    shown = _cell_tail(path, max(4, avail))
    cw.row((tool_label, col["head"]))
    _card_status_row(cw, [(child_prefix + shown, col["head"]),
                          (add_seg, col["add_sign"]), (del_seg, col["del_sign"])],
                     err, msg, width)

    def emit(sign: str, no, text: str):
        text = (text or "").replace("\t", "    ").replace("\x1b", "")
        no_str = (str(no) if no is not None else "").rjust(lw)
        if sign == "+":
            row_bg, sign_c, text_c = col["add_bg"], col["add_sign"], col["add_fg"]
        elif sign == "-":
            row_bg, sign_c, text_c = col["del_bg"], col["del_sign"], col["del_fg"]
        else:
            row_bg, sign_c, text_c = None, col["gutter"], col["ctx_fg"]
        bg = _sgr_bg(row_bg) if row_bg else ""
        # Active soft-wrap: split long lines into width-sized physical rows so
        # each row carries its own full-width background (Textual's own wrap
        # leaves continuation rows unpainted). Continuation rows get a blank
        # gutter so content stays aligned under the first row.
        for ci, chunk in enumerate(_chop_cells(text, content_w)):
            body = set_cell_size(chunk, content_w)  # pad to exactly content_w cells
            if ci == 0:
                gutter = f"{_sgr_fg(col['gutter'])}{no_str} {_sgr_fg(sign_c)}{sign} "
                cw.raw(f"{bg}{gutter}{_sgr_fg(text_c)}{body}{_SGR_RESET}",
                       f"{no_str} {sign} {chunk}")
            else:
                gutter = " " * (lw + 3)
                cw.raw(f"{bg}{gutter}{_sgr_fg(text_c)}{body}{_SGR_RESET}",
                       f"{' ' * (lw + 3)}{chunk}")

    rows_emitted = 0
    truncated = 0
    for hi, hunk in enumerate(hunks):
        if hi > 0:
            cw.raw(f"{_sgr_fg(col['gutter'])}{'⋯'.rjust(lw + 2)}{_SGR_RESET}",
                   "⋯".rjust(lw + 2))
        for sign, no, text in hunk:
            if rows_emitted >= _DIFF_MAX_ROWS:
                truncated += 1
                continue
            emit(sign, no, text)
            rows_emitted += 1
    if truncated:
        _card_note(cw, f"… +{truncated} 行未显示")

    return cw.finish()


_READ_MAX_ROWS = 10

# Lines of a file_read result that exist for the LLM, not the user: the
# show_linenos preamble, the `[FILE] N lines | PARTIAL …` header, truncation
# tips, and the keyword-fallback explanation. All stripped from the card.
_READ_NOISE_RE = re.compile(
    r"^(?:由于设置了show_linenos|\[FILE[\] ]|\[FILE PARTIAL|（某些行被截断"
    r"|Keyword '.*' not found after line )"
)


def _render_read_card(args, content, width):
    """Render a file_read call like the write cards: header + the lines the
    tool actually returned, LLM-facing chrome stripped (see _READ_NOISE_RE).
    The gutter always shows line numbers when they're knowable: parsed from the
    `N|` prefixes (show_linenos), else synthesized from `start` for sequential
    reads — numbers and content are decoupled; the only number the renderer
    can't derive is a keyword window's position without `N|`. smart_format's
    `[omitted long content]` hole renders as a `⋯` row and ends the gutter for
    the rest of the card (parsed and synthesized alike — the cut is mid-line,
    so post-hole numbers mislead).
    Body capped at _READ_MAX_ROWS with a tail count. `Error:` results render
    header-✗ only — the Did-you-mean suggestions are for the agent's
    self-correction, not the user. Returns (ansi, plain) or None."""
    args = args or {}
    width = max(20, width - _DIFF_MARGIN)
    path = str(args.get("path") or "").strip()
    if content is None or not path:
        return None
    from rich.cells import cell_len
    col = _diff_colors()
    text = str(content)
    err = text.startswith("Error:")

    rows: list[tuple] = []  # (lineno_or_None, text)
    linenos = bool(args.get("show_linenos", True))
    if not err:
        # Strip LLM-facing chrome, then trim blank runs at both ends
        # (separators around the stripped noise) BEFORE numbering; interior
        # blanks are real file content and stay.
        lines = [ln for ln in text.split("\n") if not _READ_NOISE_RE.match(ln.strip())]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        # Without `N|` prefixes, synthesize the gutter: a sequential read's
        # lines are start, start+1, … Stay blank where numbers would be
        # guesses: a keyword window's position is unknown (unless the keyword
        # fell back to a sequential read).
        fell_back = "not found after line" in text.split("\n", 1)[0]
        synth = (not linenos) and (not args.get("keyword") or fell_back)
        no = int(args.get("start") or 1) if synth else None
        holed = False
        for ln in lines:
            if ln.strip() == "[omitted long content]":
                rows.append((None, "⋯"))
                no, holed = None, True  # gutter ends at the hole: the cut is
                continue                # mid-line, post-hole numbers mislead
            m = re.match(r"^(\d+)\|(.*)$", ln) if linenos else None
            if m:
                rows.append((None if holed else int(m.group(1)), m.group(2)))
            else:
                rows.append((no, ln))
                if no is not None:
                    no += 1
        if not rows:
            return None

    msg = " ".join(text.split("\n")[0][len("Error:"):].split()) if err else ""
    child_prefix = "└─ "
    avail = width - cell_len(child_prefix) - (cell_len("  ✗") if err else 0)
    shown = _cell_tail(path, max(4, avail))

    cw = _CardWriter()
    cw.row(("file_read", col["head"]))
    _card_status_row(cw, [(child_prefix + shown, col["head"])], err, msg, width)

    shown_rows = rows[:_READ_MAX_ROWS]
    hidden = len(rows) - len(shown_rows)
    max_no = max((no for no, _ in shown_rows if no), default=0)
    lw = max(2, len(str(max_no or 1)))
    content_w = max(8, width - (lw + 3))
    for no, body in shown_rows:
        body = (body or "").replace("\t", "    ").replace("\x1b", "")
        no_str = (str(no) if no is not None else "").rjust(lw)
        for ci, chunk in enumerate(_chop_cells(body, content_w)):
            gutter = f"{no_str}   " if ci == 0 else " " * (lw + 3)
            cw.raw(f"{_sgr_fg(col['gutter'])}{gutter}"
                   f"{_sgr_fg(col['ctx_fg'])}{chunk}{_SGR_RESET}",
                   f"{gutter}{chunk}".rstrip())
    if hidden > 0:
        _card_note(cw, f"… +{hidden} 行未显示")

    return cw.finish()


_CODE_MAX_CODE_ROWS = 20   # 代码段从头展示
_CODE_MAX_OUT_ROWS = 15    # 输出段保尾展示（报错 traceback 关键在末尾）
_CODE_DEFAULT_CWD = {"", ".", "./", ".\\"}


def _code_parse_data(data):
    """把 code_run 的 StepOutcome.data 归一成 (out_text, exit_code, err_msg, is_err)。
    兼容三种返回形态:
      - 正常/进程异常 dict: {"status","stdout","exit_code"} 或 {"status":"error","msg"}
      - inline_eval 字符串: eval 的 repr，或 'Error: ...'
      - 代码缺失字符串: '[Error] Code missing ...'
    out_text 只取真正的输出(dict 的 stdout / 字符串结果)，绝不回退 msg——msg
    是 dict 进程异常的摘要，单独走 err_msg 进头部，避免和输出段重复显示。
    is_err 标记失败但无独立 detail 的情形(字符串错误本身就是输出)，让头部至少
    打个裸 ✗。out_text 已规整 CRLF→LF。"""
    exit_code, err_msg, is_err = None, "", False
    if isinstance(data, dict):
        out_text = data.get("stdout") or ""
        exit_code = data.get("exit_code")
        if data.get("status") == "error":
            is_err = True
            err_msg = str(data.get("msg") or "")
    elif isinstance(data, str):
        out_text = data
        if data.lstrip().startswith(("Error:", "[Error]")):
            is_err = True  # 内容即错误，留给输出段；头部裸 ✗
    else:
        out_text = "" if data is None else str(data)
    out_text = str(out_text).replace("\r\n", "\n").replace("\r", "\n")
    return out_text, exit_code, err_msg, is_err


def _render_code_card(args, data, width):
    """CC/Codex-style gutter card for code_run — no borders, structure comes
    from dim gutters (Codex's exec cell look, adapted to our card family):

        code_run(python)              ← header; red `✗ Exit 1 …` on failure
        │ import os                   ← command: `│ ` gutter (plain text)
        │ print(run())
        └ epoch 1 loss 0.3            ← output: `└ ` + dim text, continuation
          … +12 行已省略                 indented 2; TAIL-kept (traceback ends
          ValueError: boom               matter most — differs from CC/Codex)

    The command segment renders only when the code rode in via `script`/`code`
    args; a body ```block``` source is already rendered above by markdown.
    Returns (ansi, plain); tolerant of every data shape (_code_parse_data)."""
    args = args or {}
    width = max(20, width - _DIFF_MARGIN)
    col = _diff_colors()
    ctype = str(args.get("type") or "python").strip() or "python"
    code = str(args.get("script") or args.get("code") or "")
    out_text, exit_code, err_msg, is_err = _code_parse_data(data)

    # Timeout / manual-stop markers live inside stdout (ga.py:72-73).
    note_extra = ("超时" if "[Timeout Error]" in out_text
                  else "已停止" if "[Stopped]" in out_text else "")
    # Header failure detail. exit_code may be None (inline_eval has none, a
    # killed process polls None) — only a non-zero *integer* counts. err_msg is
    # the dict-error summary; a string-error's text stays in the output body, so
    # it sets is_err (bare ✗) but contributes no detail (avoids duplication).
    parts = []
    if isinstance(exit_code, int) and exit_code != 0:
        parts.append(f"Exit {exit_code}")
    if note_extra:
        parts.append(note_extra)
    if err_msg:
        m = err_msg
        for p in ("Error:", "[Error]"):
            if m.startswith(p):
                m = m[len(p):].strip()
        if m:
            parts.append(m)
    err = is_err or bool(parts)
    detail = " ".join(" · ".join(parts).split())

    cw = _CardWriter()
    _card_status_row(cw, [(f"code_run({ctype})", col["head"])], err, detail, width)
    cwd = str(args.get("cwd") or "").strip()
    if cwd and cwd not in _CODE_DEFAULT_CWD:
        for chunk in _chop_cells(f"cwd: {cwd}", max(8, width)):
            cw.row((chunk, col["gutter"]))

    content_w = max(8, width - 2)  # behind the 2-col gutter

    # Command segment: `│ ` gutter on every physical line (plain text). Only
    # when the code rode in via script/code args (a body ```block``` source is
    # already rendered above by markdown).
    code_lines = code.split("\n") if code.strip() else []
    if code_lines:
        shown = [l.replace("\t", "    ").replace("\x1b", "")
                 for l in code_lines[:_CODE_MAX_CODE_ROWS]]
        segs = [(l, col["ctx_fg"]) for l in shown]
        extra = len(code_lines) - len(shown)
        if extra > 0:
            segs.append((f"… +{extra} 行未显示", col["head"]))
        _emit_gutter(cw, content_w, segs, "│ ", "│ ")

    # Output segment: `└ ` first row, `  ` after, dim. Tail-kept — the omission
    # note leads, the tail lines follow (a traceback's last lines matter most).
    out_lines = [l.replace("\t", "    ").replace("\x1b", "")
                 for l in out_text.split("\n")]
    while out_lines and not out_lines[-1].strip():
        out_lines.pop()
    segs = []
    omitted = len(out_lines) - _CODE_MAX_OUT_ROWS
    if omitted > 0:
        segs.append((f"… +{omitted} 行已省略", col["head"]))
        out_lines = out_lines[-_CODE_MAX_OUT_ROWS:]
    if not out_lines and not segs:
        segs.append(("(无输出)", col["gutter"]))
    segs += [(l, col["ctx_fg"]) for l in out_lines]
    _emit_gutter(cw, content_w, segs, "└ ", "  ")

    return cw.finish()


def _extract_user_text(entry: dict) -> str:
    c = entry.get("content") if isinstance(entry, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get("text", "") for b in c
                 if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(p for p in parts if p)
    return ""


def fold_turns(text: str) -> list[dict]:
    placeholders: list[str] = []
    def stash(m):
        placeholders.append(m.group(0))
        return f"\x00PH{len(placeholders) - 1}\x00"
    # Line-anchored so backticks embedded in tool output (e.g. `N|\`\`\`\``
    # gutter from file_read) don't pair with later real fences.
    safe = re.sub(r"^`{4,}.*?^`{4,}\n?", stash, text, flags=re.DOTALL | re.MULTILINE)
    parts = re.split(r"(\**(?:LLM Running \()?Turn \d+\)? \.\.\.\**)", safe)
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


# Rich's Markdown.TableElement adds columns without specifying `overflow`,
# so Rich Table falls back to "ellipsis" — long cell contents get truncated
# with `…` in narrow terminals. Patch to use "fold" instead so cells wrap
# across multiple lines and full content stays visible.
def _patch_markdown_table_overflow():
    import rich.markdown as _rmd
    from rich.table import Table as _RichTable
    from rich import box as _rich_box

    def _table_render(self, console, options):
        # `markdown.table.border` / `markdown.table.header` were Rich default
        # styles in older releases but have been dropped from DEFAULT_STYLES;
        # resolving the bare names now raises MissingStyle. Resolve with a
        # fallback so a table never aborts the whole Markdown render — which
        # would drop the entire message to raw, unrendered text.
        table = _RichTable(
            box=_rich_box.SIMPLE,
            pad_edge=False,
            style=console.get_style("markdown.table.border", default="none"),
            show_edge=True,
            collapse_padding=True,
        )
        if self.header is not None and self.header.row is not None:
            header_style = console.get_style("markdown.table.header", default="bold")
            for column in self.header.row.cells:
                heading = column.content.copy()
                heading.stylize(header_style)
                table.add_column(heading, overflow="fold")
        if self.body is not None:
            for row in self.body.rows:
                row_content = [element.content for element in row.cells]
                table.add_row(*row_content)
        yield table

    _rmd.TableElement.__rich_console__ = _table_render


_patch_markdown_table_overflow()


# Rich/Textual wrap treats a continuous CJK run as one indivisible word and
# bumps it whole to the next line when it doesn't fit the remaining space,
# leaving the line tail padded and producing wraps like "AI ↩ 助手...". We patch
# every binding of divide_line/compute_wrap_offsets so CJK-bearing chunks pack
# leading chars into the remainder then fold the rest at full width.
# Covers CJK Unified Ideographs, Hangul Syllables, fullwidth/halfwidth forms.
_CJK_WRAP_RE = re.compile(
    r"[　-鿿"   # CJK punctuation through Unified Ideographs
    r"가-힯"    # Hangul Syllables
    r"＀-￯]"   # Halfwidth / Fullwidth Forms
)


def _fold_chunk_cells(chunk, width, char_width_fn, line_offset=0):
    """Walk chunk char-by-char; return (breaks_relative_to_chunk, final_offset).

    A break at index i means a newline lands before chunk[i]. line_offset is the
    column where chunk[0] starts. char_width_fn must be called in order — it may
    carry state (e.g. tab section index).
    """
    breaks: list[int] = []
    for i, ch in enumerate(chunk):
        cw = char_width_fn(ch)
        if line_offset > 0 and line_offset + cw > width:
            breaks.append(i)
            line_offset = cw
        else:
            line_offset += cw
    return breaks, line_offset


def _cjk_divide_line(text: str, width: int, fold: bool = True) -> list[int]:
    from rich._wrap import words as _words
    from rich.cells import cell_len as _clen

    breaks: list[int] = []
    cell_offset = 0
    for start, _end, word in _words(text):
        word_length = _clen(word.rstrip())
        if width - cell_offset >= word_length:
            cell_offset += _clen(word)
            continue
        if not fold:
            if cell_offset:
                breaks.append(start)
            cell_offset = _clen(word)
            continue

        has_cjk = bool(_CJK_WRAP_RE.search(word))
        if not has_cjk and word_length <= width:
            if cell_offset:
                breaks.append(start)
            cell_offset = _clen(word)
            continue

        if has_cjk:
            line_offset = cell_offset
        else:
            if cell_offset:
                breaks.append(start)
            line_offset = 0
        sub_breaks, cell_offset = _fold_chunk_cells(
            word, width, _clen, line_offset
        )
        breaks.extend(start + b for b in sub_breaks)
    return breaks


def _cjk_compute_wrap_offsets(text, width, tab_size, fold=True,
                              precomputed_tab_sections=None):
    from rich.cells import get_character_cell_size
    from textual._cells import cell_len as _clen
    from textual._loop import loop_last
    from textual.expand_tabs import get_tab_widths

    tab_size = min(tab_size, width)
    tab_sections = precomputed_tab_sections or get_tab_widths(text, tab_size)

    cumulative_widths: list[int] = []
    cumulative_width = 0
    for last, (tab_section, tab_width) in loop_last(tab_sections):
        cumulative_widths.extend([cumulative_width] * (len(tab_section) + int(bool(tab_width))))
        cumulative_width += tab_width
        if last:
            cumulative_widths.append(cumulative_width)

    tab_idx = [0]
    def char_width(ch):
        if ch == "\t":
            cw = tab_sections[tab_idx[0]][1]
            tab_idx[0] += 1
            return cw
        return get_character_cell_size(ch)

    breaks: list[int] = []
    cell_offset = 0
    pos = 0
    chunk_re = re.compile(r"\S+\s*|\s+")
    while pos < len(text):
        m = chunk_re.match(text, pos)
        if m is None:
            break
        start, end = m.span()
        chunk = m.group(0)
        pos = end
        chunk_width = _clen(chunk) + (cumulative_widths[end] - cumulative_widths[start])

        if width - cell_offset >= chunk_width:
            cell_offset += chunk_width
            continue
        if not fold:
            if cell_offset:
                breaks.append(start)
            cell_offset = chunk_width
            continue

        has_cjk = bool(_CJK_WRAP_RE.search(chunk))
        if not has_cjk and chunk_width <= width:
            if cell_offset:
                breaks.append(start)
            cell_offset = chunk_width
            continue

        if has_cjk:
            line_offset = cell_offset
        else:
            if cell_offset:
                breaks.append(start)
            line_offset = 0
        sub_breaks, cell_offset = _fold_chunk_cells(chunk, width, char_width, line_offset)
        breaks.extend(start + b for b in sub_breaks)
    return breaks


def _install_cjk_wrap() -> None:
    # `from X import fn` copies the binding into the importer's namespace, so a
    # rebind on the source module misses every holder. Patch each one explicitly.
    import rich._wrap as _rw
    import rich.text as _rt
    import textual.content as _tc
    import textual._wrap as _tw
    import textual.document._wrapped_document as _twd
    if getattr(_cjk_divide_line, "_cjk_patched", False):
        return
    _cjk_divide_line._cjk_patched = True
    _rw.divide_line = _cjk_divide_line
    _rt.divide_line = _cjk_divide_line
    _tc.divide_line = _cjk_divide_line
    _tw.compute_wrap_offsets = _cjk_compute_wrap_offsets
    _twd.compute_wrap_offsets = _cjk_compute_wrap_offsets


_install_cjk_wrap()


# Markdown render result that supports clean copy. We render twice: once at the
# display width (wraps to ANSI for selectability) and once at a wide width (one
# logical line per block, no wrap newlines). The narrow render goes into the
# Text widget for display; the wide render becomes the "source" string that
# get_selection extracts from, with per-visual-line offsets mapping cursor
# positions back into source — wrap continuations skip the wide-side whitespace
# eaten at the break, and hanging indent on wrap lines maps to the same source
# position as the start of the wrapped content.
@dataclass
class _MdRender:
    text: Text
    source: str
    line_starts: list  # source offset for the content start of each visual line
    line_indents: list  # leading whitespace count to skip when mapping x
    line_lengths: list  # total length of each visual line (incl. indent)


_CENTER_LEAD_MIN = 4


def _strip_quote_deco(s: str) -> tuple:
    """Rich Markdown re-emits the `▌ ` blockquote marker on every wrapped visual
    line in narrow, but the wide single-line render contains it only once at the
    block start. Treat the re-prefix on continuation lines as visual indent that
    doesn't consume wide chars. Returns (content_without_deco, deco_width)."""
    if not s.startswith("▌"):  # `▌`
        return s, 0
    rest = s[1:]
    if rest.startswith(" "):
        return rest[1:], 2
    return rest, 1


def _md_line_has_box_drawing(line: str) -> bool:
    """Return True for Rich table / box-art glyphs, not for normal dashes.

    The previous table workaround keyed on the literal `─` at the whole-widget
    level.  That was too broad: one table anywhere in a message made ordinary
    paragraphs copy from the wrapped/narrow render, reintroducing visual
    newlines.  Use the Unicode Box Drawing block so SIMPLE/ROUNDED/HEAVY/etc.
    table styles are covered while em-dashes (`—`) and ASCII/Unicode hyphens are
    not mistaken for tables.

    A leading `\u2514\u2500 ` (with the space) is the write-diff card's child-path line,
    not a table border \u2014 borders run the glyphs together (`\u2514\u2500\u2500\u2500\u2500\u2534\u2500\u2500\u2500\u2518`). Same
    for the code card's `\u2502 ` / `\u2514 ` gutters, and a gutter-only row (`\u2502` / `\u2514`
    left after rstrip trims the trailing space of an empty command/output line).
    Exempt all of them so the cards keep their exact narrow\u2194wide line mapping
    instead of the visible-text passthrough (which would copy the card's
    visual-only margin).

    A pure horizontal run (only `─` + spaces) is NOT exempt: a SIMPLE-box
    Markdown table's only box glyph is its header rule, so exempting bare
    `─` rows drops the whole table out of passthrough and misaligns CJK
    copy. The cosmetic cost is that a real markdown hr copies as a dash run
    — the pre-card behavior, never reported as a problem.
    """
    s = line.lstrip()
    for pfx in ("\u2514\u2500 ", "\u2502 ", "\u2514 "):
        if s.startswith(pfx):
            s = s[len(pfx):]
            break
    else:
        if s in ("\u2502", "\u2514"):  # gutter-only row (empty command/output line)
            s = ""
    return any("\u2500" <= ch <= "\u257f" for ch in s)


def _md_run_has_box_drawing(lines: list[str]) -> bool:
    return any(_md_line_has_box_drawing(line) for line in lines)


def _build_passthrough_source(narrow_plain: str):
    """Fallback aligner: treat narrow render as the copy source verbatim.

    Used when the wide/narrow line-by-line correspondence assumed by
    `_align_md_renders` breaks down — most notably for Rich tables, where
    the wide render keeps each logical row on one line with `│` separators
    while the narrow render lays cells vertically. In that case we can't
    map (y, x) selection coordinates back to the wide source, so we just
    copy whatever is visually on screen and accept the cosmetic cost of
    leaving the table's `─`/`│` box characters in the clipboard output.

    Returns the same 4-tuple shape as `_align_md_renders`:
        (source, line_starts, line_indents, line_lengths)
    """
    lines = narrow_plain.split("\n")
    line_starts = [0] * len(lines)
    line_indents = [0] * len(lines)
    line_lengths = [0] * len(lines)
    parts = []
    pos = 0
    for i, raw in enumerate(lines):
        # Strip the `▌` user-message side bar the same way the aligner does,
        # so selections inside user echoes still copy clean text.
        body, deco = _strip_quote_deco(raw)
        line_starts[i] = pos
        line_indents[i] = deco
        line_lengths[i] = len(body)
        parts.append(body)
        pos += len(body)
        if i != len(lines) - 1:
            parts.append("\n")
            pos += 1
    return "".join(parts), line_starts, line_indents, line_lengths


def _align_md_renders(narrow_raw: str, wide_raw: str):
    """Walk narrow + wide line-by-line; return (source, line_starts, line_indents, line_lengths)."""
    narrow = [l.rstrip() for l in narrow_raw.split("\n")]
    wide = [l.rstrip() for l in wide_raw.split("\n")]

    wrap_groups: list = []
    ni = 0
    wi = 0
    while ni < len(narrow):
        if narrow[ni] == "":
            ni += 1
            while wi < len(wide) and wide[wi] == "":
                wi += 1
            continue
        run_start = ni
        while ni < len(narrow) and narrow[ni] != "":
            ni += 1
        run_lines = narrow[run_start:ni]

        wide_start = wi
        while wi < len(wide) and wide[wi] != "":
            wi += 1
        wide_lines = wide[wide_start:wi]

        K, W = len(run_lines), len(wide_lines)
        if _md_run_has_box_drawing(run_lines):
            # Rich tables are inherently two-dimensional: a single logical row in
            # the wide render may become several visual rows in the narrow render.
            # Treat only this *run* as visual/passthrough.  Do not poison the
            # rest of the widget, otherwise paragraphs before/after the table
            # start copying their wrapped visual newlines again.
            for k in range(K):
                wrap_groups.append(((run_start + k, run_start + k + 1), run_lines[k], True))
        elif W == 0:
            for k in range(K):
                wrap_groups.append(((run_start + k, run_start + k + 1), run_lines[k], False))
        elif K == W:
            for k in range(K):
                wrap_groups.append(((run_start + k, run_start + k + 1), wide_lines[k], False))
        else:
            j = 0
            for w_idx, w_line in enumerate(wide_lines):
                g_start = run_start + j
                accumulated = 0
                target = len(w_line)
                is_last = (w_idx == W - 1)
                while j < K and (accumulated < target or is_last):
                    nt = run_lines[j]
                    if j > g_start - run_start:
                        content, _ = _strip_quote_deco(nt.lstrip())
                    else:
                        # First line of the group: drop any visual-only left
                        # margin (narrow lead beyond the wide line's own lead —
                        # margined tool blocks) so the accumulation against the
                        # wide target stays balanced.
                        n_lead = len(nt) - len(nt.lstrip())
                        w_lead = len(w_line) - len(w_line.lstrip())
                        content = nt[max(0, n_lead - w_lead):]
                    accumulated += len(content)
                    j += 1
                    # Each wrap boundary eats one space from the wide line, so
                    # the narrow side's accumulated content runs (consumed - 1)
                    # chars short of target at the natural wrap point.
                    consumed = j - (g_start - run_start)
                    if not is_last and accumulated + max(0, consumed - 1) >= target:
                        break
                wrap_groups.append(((g_start, run_start + j), w_line, False))

    source_parts: list = []
    line_starts = [0] * len(narrow)
    line_indents = [0] * len(narrow)
    line_lengths = [len(nt) for nt in narrow]
    src_pos = 0
    last_was_content = False
    group_idx = 0

    ni = 0
    while ni < len(narrow):
        if narrow[ni] == "":
            line_starts[ni] = src_pos
            if last_was_content:
                source_parts.append("\n")
                src_pos += 1
            source_parts.append("\n")
            src_pos += 1
            last_was_content = False
            ni += 1
            continue

        while group_idx < len(wrap_groups) and ni >= wrap_groups[group_idx][0][1]:
            group_idx += 1
        if group_idx >= len(wrap_groups):
            line_starts[ni] = src_pos
            source_parts.append(narrow[ni])
            src_pos += len(narrow[ni])
            ni += 1
            last_was_content = True
            continue

        (g_start, g_end), wide_line, passthrough = wrap_groups[group_idx]
        single_line = (g_end - g_start == 1)

        nt0 = narrow[g_start]
        nt0_lead = len(nt0) - len(nt0.lstrip())
        wide_lead = len(wide_line) - len(wide_line.lstrip())
        # Rich centers H1 against the available width, so wide_lead grows with the
        # console width (≈ 5000 at width=10000) while nt0_lead reflects narrow's
        # half-padding. Code lines, list/blockquote markers, etc. have wide_lead
        # ≈ nt0_lead — without the >=2× guard the heuristic would strip indent
        # from any code line with ≥5 leading spaces (e.g. `    print("hi")`),
        # causing the visible selection and the copied text to disagree.
        is_centered = (single_line and wide_lead > _CENTER_LEAD_MIN and nt0_lead > 0
                       and wide_lead >= 2 * nt0_lead)

        if last_was_content:
            source_parts.append("\n")
            src_pos += 1

        if passthrough:
            # Visual/source mapping for table rows: keep exactly what the user
            # sees on this line (minus quote decoration) so x offsets remain
            # valid.  Each table visual line is its own group, so no wrapped
            # paragraph outside the table inherits this behavior.
            body, deco = _strip_quote_deco(narrow[g_start])
            source_parts.append(body)
            line_starts[g_start] = src_pos
            line_indents[g_start] = deco
            src_pos += len(body)
        elif is_centered:
            content = wide_line.lstrip()
            source_parts.append(content)
            line_starts[g_start] = src_pos
            line_indents[g_start] = nt0_lead
            src_pos += len(content)
        else:
            block_start = src_pos
            source_parts.append(wide_line)
            src_pos += len(wide_line)
            pointer = 0
            for k in range(g_start, g_end):
                nt = narrow[k]
                if k == g_start:
                    # A narrow line with MORE lead than its wide twin is showing
                    # a visual-only left margin (write-diff cards / margined tool
                    # blocks). Map it as indent so selection x-coords shift and
                    # copies exclude it; drop it from `content` so the pointer
                    # accounting over the wide line stays balanced.
                    nt_lead = len(nt) - len(nt.lstrip())
                    indent = max(0, nt_lead - wide_lead)
                    content = nt[indent:]
                else:
                    indent = len(nt) - len(nt.lstrip())
                    content = nt.lstrip()
                    content, deco = _strip_quote_deco(content)
                    indent += deco
                    while pointer < len(wide_line) and wide_line[pointer].isspace():
                        pointer += 1
                line_starts[k] = block_start + pointer
                line_indents[k] = indent
                pointer += len(content)
        ni = g_end
        last_was_content = True

    return "".join(source_parts).rstrip("\n"), line_starts, line_indents, line_lengths


# ---------------------------------------------------------------------------
# @ 文件引用（at-mention）— 补全版（completion-only）
#   编辑期：光标处 @token → 后台文件索引 + 模糊匹配 → 复用 #palette 下拉，
#   选中把 @路径 补进输入框（索引根 = 会话 workspace，未绑定退化为 CWD）。
#   提交期：不处理，@路径 作为普通文本发给 agent，由其自行决定是否 file_read。
#   纯逻辑（索引/模糊/token）抽到 frontends/at_complete.py，与 tui_v3 共用；
#   自动预读那一版见 temp/plan_v2_at_mention/autoread_version.py。
from at_complete import get_index, fuzzy_rank, find_at_token, format_pick, candidates_for, absolutize_mentions


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
FRONTENDS_DIR = os.path.dirname(os.path.abspath(__file__))
if FRONTENDS_DIR not in sys.path:
    sys.path.insert(0, FRONTENDS_DIR)

_TASK_DIR_GLOB = os.path.join(FRONTENDS_DIR, '..', 'temp', '_tui_v2_*')


def _rmdir_if_empty(path: Optional[str]) -> None:
    """Best-effort remove a signal task_dir once it holds no in-flight files.
    `os.rmdir` only succeeds on an empty dir, so a stray `_intervene` still
    pending consumption is never clobbered."""
    if not path:
        return
    try: os.rmdir(path)
    except OSError: pass


def _sweep_stale_task_dirs() -> None:
    """Delete empty `temp/_tui_v2_*` signal dirs left by prior runs (incl.
    crashes).  Empty == no pending signal, so removal is safe even while
    another live instance owns one — its writer re-creates lazily on the
    next inject."""
    import glob as _glob
    for d in _glob.glob(_TASK_DIR_GLOB):
        if os.path.isdir(d):
            _rmdir_if_empty(d)

# Side-effect imports activate /btw + /continue monkey-patches.
import chatapp_common  # noqa: F401
from chatapp_common import format_restore
from btw_cmd import handle_frontend_command as btw_handle
from review_cmd import handle as review_handle
from continue_cmd import list_sessions as continue_list, extract_ui_messages as continue_extract
import workspace_cmd
from export_cmd import last_assistant_text, export_to_temp, wrap_for_clipboard

# Cross-platform clipboard copy for /export clip. Mirrors tui_v3's native-tool
# strategy but stays local to v2 so the Textual frontend has no dependency on
# the raw terminal frontend module.
_HAS_WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY"))


def _clipboard_run(cmd: list[str], input: bytes | None = None, timeout: float = 3.0) -> bytes | None:
    try:
        r = subprocess.run(cmd, input=input, capture_output=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _copy_to_clipboard_win32(text: str) -> bool:
    """Copy Unicode text on Windows without going through console code pages."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        GMEM_MOVEABLE = 0x0002
        CF_UNICODETEXT = 13

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.restype = wintypes.BOOL

        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        locked = kernel32.GlobalLock(handle)
        if not locked:
            kernel32.GlobalFree(handle)
            return False
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(handle)
            return False
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                return False
            # Ownership transferred to the clipboard; do not free `handle`.
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def _copy_to_clipboard(text: str) -> bool:
    data = text.encode("utf-8")
    if sys.platform == "darwin":
        return _clipboard_run(["pbcopy"], input=data) is not None
    if sys.platform == "win32":
        return _copy_to_clipboard_win32(text)
    if _HAS_WAYLAND and shutil.which("wl-copy"):
        return _clipboard_run(["wl-copy"], input=data) is not None
    if shutil.which("xclip"):
        return _clipboard_run(["xclip", "-selection", "clipboard"], input=data) is not None
    if shutil.which("xsel"):
        return _clipboard_run(["xsel", "--clipboard", "--input"], input=data) is not None
    return False

AgentFactory = Callable[[], Any]

# ---------- themes ----------
# Our `ga-default` palette is registered as a Textual Theme; the other themes in
# `_THEME_CYCLE` are Textual built-ins, whose ga-* slots are derived in
# get_css_variables. C_* globals are kept in sync via watch_theme so Rich Text
# styles (which take plain hex strings) update on theme switch.
_DEFAULT_PALETTE: dict[str, str] = {
    "fg": "#c9d1d9", "muted": "#8b949e", "dim": "#6e7681",
    "bg": "#0d1117", "alt_bg": "#21262d", "sel_bg": "#161b22",
    "border": "#30363d", "border_hi": "#484f58",
    "green": "#7ec27e", "blue": "#82adcf", "purple": "#b596d8",
    # Topbar info-segment chips — distinct hues for at-a-glance scanability.
    # Values are from the github-dark palette; built-in Textual themes derive
    # these from primary/secondary/warning/accent/success in get_css_variables.
    "chip_name":   "#79c0ff",  # session name — cyan-blue
    "chip_model":  "#a5d6ff",  # model id     — pale blue
    "chip_effort": "#f0883e",  # effort       — amber (heat)
    "chip_tasks":  "#d2a8ff",  # task count   — lavender
    "chip_time":   "#7ec27e",  # clock        — same muted green as the sidebar's active-session marker
}

_THEME_CYCLE = ["ga-default", "nord", "gruvbox", "dracula", "tokyo-night", "textual-light"]


# ---------- persisted settings ----------
# Lightweight JSON dropbox for cross-run UI state (theme, future toggles).
# Lives under temp/ alongside model logs so it tracks the workspace.
_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "temp", "tui_settings.json"
)

def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _save_settings(patch: dict) -> None:
    cur = _load_settings()
    cur.update(patch)
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

_palette: dict[str, str] = dict(_DEFAULT_PALETTE)
C_FG     = _palette["fg"]
C_MUTED  = _palette["muted"]
C_DIM    = _palette["dim"]
C_SEL_BG = _palette["sel_bg"]
C_GREEN  = _palette["green"]
C_BLUE   = _palette["blue"]
C_PURPLE = _palette["purple"]
C_CHIP_NAME   = _palette["chip_name"]
C_CHIP_MODEL  = _palette["chip_model"]
C_CHIP_EFFORT = _palette["chip_effort"]
C_CHIP_TASKS  = _palette["chip_tasks"]
C_CHIP_TIME   = _palette["chip_time"]


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "#000000").lstrip("#")
    if len(h) == 3: h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _hex_rgb(a), _hex_rgb(b)
    return _rgb_hex(tuple(ra[i] * (1 - t) + rb[i] * t for i in range(3)))


def _markdown_rich_theme(p: dict[str, str], minimal: bool = False):
    """Map our palette to Rich Markdown's named styles so code/links/headings
    follow the active theme instead of Rich's frozen defaults.

    `minimal=True` collapses everything to fg/muted so non-default themes don't
    fight Rich's frozen accent colors — each theme can be re-colorised case by
    case later."""
    from rich.theme import Theme as _RichTheme
    if minimal:
        fg, muted, dim, border = p["fg"], p["muted"], p["dim"], p["border"]
        return _RichTheme({
            "markdown.h1":          f"bold {fg}",
            "markdown.h2":          f"bold {fg}",
            "markdown.h3":          f"bold {fg}",
            "markdown.h4":          f"bold {fg}",
            "markdown.h5":          f"bold {fg}",
            "markdown.h6":          f"bold {fg}",
            "markdown.code":        f"bold {fg}",
            "markdown.code_block":  fg,
            "markdown.link":        f"underline {fg}",
            "markdown.link_url":    f"underline {dim}",
            "markdown.block_quote": muted,
            "markdown.item":        fg,
            "markdown.list":        fg,
            "markdown.item.bullet": f"bold {fg}",
            "markdown.item.number": fg,
            "markdown.hr":          border,
            "markdown.strong":      f"bold {fg}",
            "markdown.em":          f"italic {fg}",
            "markdown.s":           f"strike {dim}",
            "markdown.table.border": border,
            "markdown.table.header": f"bold {fg}",
        })
    return _RichTheme({
        "markdown.h1":          f"bold {p['green']}",
        "markdown.h2":          f"bold {p['blue']}",
        "markdown.h3":          f"bold {p['purple']}",
        "markdown.h4":          f"bold {p['fg']}",
        "markdown.h5":          f"bold {p['fg']}",
        "markdown.h6":          f"bold {p['fg']}",
        "markdown.code":        f"bold {p['fg']}",
        "markdown.code_block":  f"{p['fg']} on {p['sel_bg']}",
        "markdown.link":        p["blue"],
        "markdown.link_url":    f"underline {p['dim']}",
        "markdown.block_quote": p["muted"],
        "markdown.item":        p["fg"],
        "markdown.list":        p["blue"],
        "markdown.item.bullet": f"bold {p['blue']}",
        "markdown.item.number": p["blue"],
        "markdown.hr":          p["border"],
        "markdown.strong":      f"bold {p['fg']}",
        "markdown.em":          f"italic {p['fg']}",
        "markdown.s":           f"strike {p['dim']}",
        "markdown.table.border": p["border"],
        "markdown.table.header": f"bold {p['fg']}",
    })


def _palette_from_resolved_vars(v: dict[str, str], dark: bool) -> dict[str, str]:
    """Derive our 11-slot palette from Textual's *resolved* CSS variables (i.e.
    after super().get_css_variables()). Textual auto-fills foreground / surface /
    panel when the Theme leaves them None, so we read those rather than raw
    Theme attributes."""
    bg = v.get("background") or ("#1a1a1a" if dark else "#ffffff")
    fg = v.get("foreground") or ("#e6e6e6" if dark else "#1a1a1a")
    surface = v.get("surface") or _mix(bg, fg, 0.08)
    panel = v.get("panel") or _mix(bg, fg, 0.14)
    primary = v.get("primary") or fg
    return {
        "fg": fg, "bg": bg,
        "alt_bg": surface, "sel_bg": panel,
        # text-muted / text-disabled in Textual resolve to "auto NN%" — a Textual-only
        # syntax Rich can't parse. Always derive from bg/fg blend so the strings we
        # hand to Rich Text are plain hex.
        "muted": _mix(bg, fg, 0.55),
        "dim":   _mix(bg, fg, 0.35),
        "border":    _mix(bg, fg, 0.20),
        "border_hi": _mix(bg, fg, 0.35),
        "green":  v.get("success") or primary,
        "blue":   v.get("secondary") or primary,
        "purple": v.get("accent") or primary,
        # Topbar chips — five distinguishable Textual roles so each segment keeps
        # its own hue across themes. Fall back to primary if a slot is missing.
        "chip_name":   v.get("primary") or primary,
        "chip_model":  v.get("secondary") or primary,
        "chip_effort": v.get("warning") or v.get("accent") or primary,
        "chip_tasks":  v.get("accent") or primary,
        "chip_time":   v.get("success") or primary,
    }


_MAIN_CSS = """
Screen { background: $ga-bg; color: $ga-fg; }

#topbar, #bottombar {
    height: 1;
    background: $ga-bg;
    padding: 0 2;
}

#body { height: 1fr; }

/* Outer scroll container owns the geometry (width/height/border) and the
   scrolling; the inner #sidebar Static keeps the padding so the click
   hit-test math in on_click (event.y - 3) is unchanged. */
#sidebar-scroll {
    width: 34;
    height: 100%;
    background: $ga-bg;
    border-right: solid $ga-alt-bg;
    overflow-y: auto;
    overflow-x: hidden;
    scrollbar-size: 0 1;
    /* Reserve the 1-col scrollbar gutter up front so overflowing the window
       doesn't suddenly squeeze the session rows narrower. */
    scrollbar-gutter: stable;
}
#sidebar-scroll.-hidden, #sidebar-scroll.-narrow { display: none; }

#sidebar {
    width: 1fr;
    height: auto;
    padding: 1 2;
}

#main {
    height: 100%;
    padding: 1 6;
    background: $ga-bg;
}

#messages {
    height: 1fr;
    background: $ga-bg;
    /* horizontal hidden, 1-col vertical bar on right. */
    scrollbar-size: 0 1;
    scrollbar-background: $ga-bg;
    scrollbar-background-hover: $ga-bg;
    scrollbar-background-active: $ga-bg;
    scrollbar-color: $ga-border;
    scrollbar-color-hover: $ga-border-hi;
    scrollbar-color-active: $ga-dim;
}

/* Plan/todo panel — fixed 5-row card between messages and composer.
   `display: none` default so the empty post-compose frame doesn't flash;
   renderer flips it on once items materialize. Fixed height (no scroll)
   keeps layout stable; body truncates to 4 items + "+N more" footer. */
/* Plan card. Outer #planbar-scroll owns the frame (border/padding) + show-hide.
   #planbar-head pins the header + current-step line. #planbar-tasks is the only
   scrolling region: capped at 4 rows so at most 4 TODO items show at once, the
   rest reachable by wheel/PageUp. */
#planbar-scroll {
    display: none;
    height: auto;
    background: $ga-sel-bg;
    padding: 0 1;
    margin: 0 0 1 0;
    border-left: thick $ga-green;
}
#planbar-scroll.-visible { display: block; }
#planbar-head {
    height: auto;
    background: $ga-sel-bg;
}
#planbar-tasks {
    height: auto;
    max-height: 4;
    background: $ga-sel-bg;
    scrollbar-size: 0 1;
    scrollbar-background: $ga-sel-bg;
    scrollbar-background-hover: $ga-sel-bg;
    scrollbar-background-active: $ga-sel-bg;
    scrollbar-color: $ga-border;
}
#planbar {
    height: auto;
    background: $ga-sel-bg;
}

/* `└ Tip:` footer — one dim row, never grows. */
#tipbar {
    height: 1;
    background: $ga-bg;
    padding: 0;
    color: $ga-dim;
}

/* Pickers — used by both ChoiceList (OptionList) and MultiChoiceList
   (SelectionList). Same flat single-column look as the rest of the chat,
   with a thin green left edge so the picker reads as an actionable card. */
OptionList.picker, SelectionList.picker {
    height: auto;
    max-height: 12;
    margin: 0 0 1 0;
    padding: 0 1;
    background: $ga-bg;
    border: none;
    border-left: thick $ga-green;
    scrollbar-size: 0 1;
}
OptionList.picker > .option-list--option-hover,
SelectionList.picker > .option-list--option-hover { background: $ga-sel-bg; }
OptionList.picker > .option-list--option-highlighted,
SelectionList.picker > .option-list--option-highlighted {
    background: $ga-blue 20%;
    color: $ga-fg;
    text-style: none;
}
SelectionList.picker > .selection-list--button { color: $ga-dim; }
SelectionList.picker > .selection-list--button-selected { color: $ga-green; }
SelectionList.picker > .selection-list--button-highlighted { background: transparent; }

/* Searchable `/continue` picker wrapper. Textual's Vertical container defaults
   to a flex-like height in this scroll layout; if left implicit, scroll_end can
   align only the wrapper's tail and leave the search box / options hidden under
   the composer. Keep the wrapper content-sized; the inner OptionList.picker
   remains the only scrollable/clamped part (12 rows). */
SearchableChoiceList.picker {
    height: auto;
    margin: 0 0 1 0;
}

/* `/continue` search box: one-row gap above (to separate the input from the
   "选择要恢复的会话 …" prompt header) and one-row gap below (to separate it
   from the result list), so the input is visually distinct on both sides
   (user feedback 2026-05-27). */
#continue-search { margin: 1 0 1 0; }

.role {
    height: 1;
    margin-top: 1;
    margin-bottom: 0;
}
.msg {
    height: auto;
    margin-bottom: 0;
}
.fold-header:hover { background: $ga-sel-bg; }
.spinner {
    height: 1;
    margin-top: 1;
}

#palette {
    height: auto;
    max-height: 8;
    background: $ga-bg;
    border: none;
    padding: 0;
    display: none;
    margin-bottom: 1;
    scrollbar-size: 0 0;
}
#palette.-visible { display: block; }
OptionList {
    background: $ga-bg;
    border: none;
    padding: 0;
}
OptionList > .option-list--option {
    padding: 0 2;
    background: $ga-bg;
    color: $ga-fg;
}
OptionList > .option-list--option-highlighted {
    background: $ga-fg;
    color: $ga-bg;
    text-style: bold;
}

ChoiceList {
    height: auto;
    max-height: 12;
    background: $ga-bg;
    border: none;
    padding: 0;
    margin-bottom: 1;
    scrollbar-size: 0 0;
}

#input {
    height: 3;
    min-height: 3;
    max-height: 5;
    /* min-width guards TextArea.render_lines against `range() arg 3 must not be zero`
       when the content region collapses to <= 0 cols (narrow window + sidebar shown). */
    min-width: 10;
    background: $ga-sel-bg;
    border: none;
    margin-bottom: 1;
    padding: 1 2;
    color: $ga-fg;
    scrollbar-size: 0 0;
}
#input:focus { border: none; }
"""


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
    # Optional Esc/cancel hook for choice cards. When set, _cancel_choice
    # invokes this *after* removing the card (used by /scheduler's submit-
    # confirm card to re-show the picker, mirroring ask_user's free-text
    # "Esc rolls back to the previous picker" UX).
    on_cancel: Optional[Callable] = field(default=None, repr=False)
    selected_label: Optional[str] = None
    # Indices into `choices` that should render pre-ticked when the card first
    # mounts (multi_choice only). Used by /scheduler so already-running
    # services show up checked, making "untick = stop" discoverable (bug#4).
    preselected_indices: list[int] = field(default_factory=list)
    # Optional lazy-render hints for choice pickers with huge option counts
    # (e.g. /continue across thousands of sessions). Default is empty / 0,
    # so every existing call site keeps the eager-mount behavior bit-for-bit.
    lazy_choice_items: Optional[list] = field(default=None, repr=False)
    lazy_choice_batch: int = 0
    # `/continue` picker opt-in: when True, _mount_message wraps the picker
    # with an Input filter; `all_choices` is the unfiltered baseline so empty
    # queries restore the full list. Other call sites keep searchable=False
    # (default) and the existing eager/lazy paths run untouched.
    searchable: bool = False
    search_query: str = ""
    all_choices: Optional[list] = field(default=None, repr=False)
    # Free-input opt-in for searchable pickers (/model): when True, Enter in
    # the search box with NO selectable match commits the raw query text as
    # the value — the filter box doubles as a custom-name input. /continue
    # keeps the default False, so a no-match Enter stays a no-op there.
    free_input: bool = False
    # Optional placeholder for the search Input ("" → the /continue default).
    search_placeholder: str = ""
    # Hint row shown (disabled) under the search Input when choices is empty —
    # doubles as a "loading…" indicator for pickers filled asynchronously (/model).
    empty_hint: str = "(no matches)"
    image_paths: list[str] = field(default_factory=list)
    _role_widget: Any = field(default=None, repr=False)
    _hint_widget: Any = field(default=None, repr=False)
    _body_widget: Any = field(default=None, repr=False)
    _cached_body: Any = field(default=None, repr=False)
    _cache_key: tuple = field(default=(), repr=False)
    # Fold indices the user has manually toggled away from the global default.
    # Effective expansion = (default ⊕ in this set), where default = not fold_mode.
    _toggled_folds: set = field(default_factory=set, repr=False)
    _segment_widgets: list = field(default_factory=list, repr=False)
    _segment_sig: tuple = field(default=(), repr=False)
    _spinner_widget: Any = field(default=None, repr=False)
    # Stream start + token baselines so the spinner shows *this turn's* deltas.
    _stream_started_at: Optional[float] = field(default=None, repr=False)
    _stream_baseline_input: int = field(default=0, repr=False)
    _stream_baseline_output: int = field(default=0, repr=False)
    # Frozen `(elapsed, last_in, last_out)` at done→True; keeps the post-turn
    # card from ticking when the next turn shifts cost_tracker deltas.
    _done_summary: Optional[tuple] = field(default=None, repr=False)
    # Frozen `(elapsed, last_in, last_out)` stamped the instant the user aborts
    # (Ctrl+C / `/stop`). Flips the live spinner to a settled "Stopping…" line so
    # elapsed stops climbing while the LLM stream unwinds in the background.
    _stop_summary: Optional[tuple] = field(default=None, repr=False)
    # Per-(seg_hash, width) Text cache; survives fold-toggle re-mounts.
    _seg_render_cache: dict = field(default_factory=dict, repr=False)


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
    # Per-session input box state. Restored into the shared InputArea on session switch.
    input_text: str = ""
    input_history: list[str] = field(default_factory=list)
    input_pastes: dict[int, str] = field(default_factory=dict)
    input_paste_counter: int = 0
    buffer: str = ""
    # Per-session workspace/project-mode binding. Empty means ordinary mode.
    workspace_name: str = ""
    workspace_path: str = ""
    workspace_link: str = ""
    # Drives topbar heat-color ramp + elapsed label; set on first running tick.
    _busy_since: Optional[float] = None
    # Stamps running→idle; topbar dot flashes green for ~5s after.
    _done_at: Optional[float] = None
    # ask_user INTERRUPT events; drained by display thread on turn done.
    ask_user_events: Any = field(default_factory=lambda: queue.Queue())
    # Pending `{question:str}` after the user picks free-text in an ask_user
    # picker; next submission becomes a 2-step "Ready to submit?" confirm.
    free_text_pending: Optional[dict] = None
    # Plan state: items + grace-period timers (3s farewell, 1.5s lost-grace).
    plan_items: list = field(default_factory=list)
    plan_complete_since: Optional[float] = None
    plan_lost_since: Optional[float] = None
    # Boundary between restored history (≤ idx) and this run (> idx); only
    # `current_step`'s 📌-line scan uses it now — card activation no longer
    # reads messages.
    plan_scan_baseline: int = 0
    # plan.md recovered from the transcript's structured `enter_plan_mode`
    # tool_use by /continue (continue_cmd.find_plan_entry). Drives card
    # activation alongside the live `working['in_plan_mode']` stash.
    restored_plan_path: str = ""
    # `pending`: raw user text for UI display ([queued #N] chip).
    # `pending_wrapped`: same entries wrapped with the "complete current
    # task first" supplementary phrasing, in the form actually appended
    # to `_intervene`.  Replay uses these so the exit-turn put_task
    # carries the wrap context.
    pending: list[str] = field(default_factory=list)
    pending_wrapped: list[str] = field(default_factory=list)
    pending_lk: threading.Lock = field(default_factory=threading.Lock)


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
    ("/rename",   "<name>",           "重命名当前会话（持久化）"),
    ("/branch",   "[name]",           "从当前会话分支"),
    ("/rewind",   "[n]",              "回退最近 n 轮"),
    ("/clear",    "",                 "清空显示（不动 LLM 历史）"),
    ("/stop",     "",                 "中止当前任务"),
    ("/llm",      "[n]",              "查看 / 切换模型"),
    ("/model",    "[name]",           "查看 / 设置当前渠道的 model（列表在线拉取）"),
    ("/effort",   "[level]",          "查看 / 设置 reasoning effort（off 清除；Claude xhigh→max）"),
    ("/btw",      "<question>",       "side question — 不打断主 agent"),
    ("/review",   "[request]",         "in-session 代码审查（直接输出报告）"),
    # ── slash_cmds bundle (prompt-injection + /scheduler picker).  Kept in
    # the same table so /-completion + the palette pick them up for free.
    ("/update",    "[note]",           "git pull 更新 GA 仓库并报告影响面"),
    ("/autorun",   "[seed]",           "进入 autonomous_operation 自主模式"),
    ("/morphling", "[target]",         "启用 Morphling 蒸馏 / 吞噬外部技能"),
    ("/goal",      "[goal]",           "进入 Goal 模式（需 condition 约束）"),
    ("/hive",      "[target]",         "进入 Hive 多 worker 协作模式"),
    ("/conductor", "[task]",           "调用 frontends/conductor.py 多 subagent 编排"),
    ("/scheduler", "",                 "多选启动/停止 reflect 任务（cron 由 reflect/scheduler.py 驱动）"),
    ("/continue", "[n|name]",         "列出 / 恢复历史会话"),
    ("/workspace","[path|off]",       "设定工作目录(绝对路径)并进入项目模式"),
    ("/resume",   "",                 "列出最近会话并恢复其中一个"),
    ("/cost",     "[all]",            "显示当前会话 token 用量（all = 所有会话）"),
    ("/export",   "clip|<file>|all",  "导出最后回复"),
    ("/restore",  "",                 "恢复上次模型响应日志"),
    ("/reload-keys", "",              "重新加载mykey.py（不重启）"),
    ("/quit",     "",                 "退出"),
]


# ---------- widgets ----------
# Picker sentinels — opaque values routed through `_collapse_choice` so any
# kind of picker can hand off to the same handlers.
#   FREE_TEXT — user wants to type a free-form answer instead of picking
#   EDIT_ANSWER — back from the submit-confirmation, go re-edit the draft
FREE_TEXT_CHOICE = "\x00__free_text__"
FREE_TEXT_LABEL = "Type something"
EDIT_ANSWER_CHOICE = "\x00__edit_answer__"


class ChoiceList(OptionList):
    BINDINGS = [*OptionList.BINDINGS,
                Binding("right", "select", "Select", show=False),
                # `left` mirrors Esc — pickers spawned with an on_cancel
                # (e.g. /scheduler's submit-confirm card → rollback to
                # picker) get a directional way to back out without
                # reaching for Esc.  Choices without an on_cancel just
                # dismiss, same as Esc.
                Binding("left",  "cancel", "Back",   show=False),
                Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, msg: "ChatMessage", *options, **kwargs):
        super().__init__(*[self._single_line(o) for o in options], **kwargs)
        self.msg = msg

    @staticmethod
    def _single_line(item):
        # A str prompt → a no-wrap, ellipsis-on-overflow Option so a long
        # candidate (e.g. a workspace `name · /very/long/path · …`) stays on
        # exactly one row instead of soft-wrapping into several. Already-built
        # Option / None pass through untouched.
        if isinstance(item, str):
            return Option(Text(item, no_wrap=True, overflow="ellipsis"))
        return item

    def add_option(self, option=None):
        return super().add_option(self._single_line(option))

    def add_options(self, items):
        return super().add_options([self._single_line(i) for i in items])

    def action_cancel(self) -> None:
        try:
            self.app._cancel_choice(self.msg)
        except Exception:
            pass

    def on_key(self, event) -> None:
        # Inside `/continue`'s SearchablePicker, Up on the first row returns
        # focus to the search box (mirrors Down going search → list), closing
        # the navigation loop. No-op for ChoiceLists mounted outside a
        # SearchablePicker (other pickers have no `_search_input` parent), so
        # this stays scoped to `/continue`.
        if event.key != "up":
            return
        search = getattr(self.parent, "_search_input", None)
        if search is None:
            return
        if self.highlighted not in (None, 0):
            return
        try:
            # Clear the highlight on the way out so the search box doesn't show
            # row 0 as still-selected, and the next Down re-enters at the first
            # row (cursor_down from None → 0) instead of skipping to the second.
            self.highlighted = None
            search.focus()
        except Exception:
            pass
        event.stop(); event.prevent_default()


class LazyChoiceList(ChoiceList):
    """ChoiceList that materializes options in bounded batches.

    Why: `/continue` can list thousands of historical sessions; mounting every
    `Option` up-front stalls Textual's render pipeline for ~hundreds of ms and
    inflates the row cache. We mount the first `batch` rows immediately so the
    picker is interactive on first paint, then extend the mounted set as the
    cursor approaches the loaded tail (Down/PageDown/End) or as the user asks
    for the last row from the top via Up — see `action_cursor_up`.

    Back-end contract: ChoiceList already accepts whatever the picker's
    `highlighted` Option's prompt is — the consumer code uses the index via
    `msg.choices`. Lazy only changes *when* rows enter the DOM, not the value
    contract. Falls back to eager super() behaviour for empty / tiny lists.
    """

    def __init__(self, msg: "ChatMessage", labels: list, batch: int = 50, **kwargs):
        self._lazy_labels = list(labels or [])
        self._lazy_loaded = 0
        self._lazy_batch = max(1, int(batch or 50))
        super().__init__(msg, **kwargs)
        # Mount the first batch synchronously so the picker is usable on the
        # very first frame; remaining rows stream in on demand.
        self._load_more(self._lazy_batch)

    @property
    def _has_more(self) -> bool:
        return self._lazy_loaded < len(self._lazy_labels)

    def _load_more(self, count: Optional[int] = None) -> bool:
        if not self._has_more:
            return False
        take = (len(self._lazy_labels) - self._lazy_loaded) if count is None else max(1, int(count))
        end = min(len(self._lazy_labels), self._lazy_loaded + take)
        try:
            self.add_options([self._lazy_labels[i] for i in range(self._lazy_loaded, end)])
        except Exception:
            # If the list isn't mounted yet (very early call), fall back to
            # buffering via _options if available; otherwise silently bail so
            # the eager half still works.
            return False
        self._lazy_loaded = end
        return True

    def _ensure_window(self) -> None:
        """Extend the loaded window when the cursor nears the tail."""
        hi = self.highlighted
        if hi is None or not self._has_more:
            return
        if hi >= max(0, self._lazy_loaded - 5):
            self._load_more(self._lazy_batch)

    def action_cursor_down(self) -> None:
        before = self.highlighted
        super().action_cursor_down()
        # If Down had no effect (cursor was at the last loaded row), extend.
        if self.highlighted == before and self._has_more:
            if self._load_more(self._lazy_batch):
                super().action_cursor_down()
        self._ensure_window()

    def action_page_down(self) -> None:
        # PageDown can leap ~10 rows at once; pre-extend by a full batch so the
        # visible window doesn't get capped by the load horizon.
        if self._has_more:
            self._load_more(self._lazy_batch)
        super().action_page_down()
        self._ensure_window()

    def action_last(self) -> None:
        # End/Last must reveal the genuine last session, not the last *loaded*
        # row. Load everything (one-shot, no batching loop) then defer to super.
        if self._has_more:
            self._load_more(None)
        super().action_last()

    def action_cursor_up(self) -> None:
        # OptionList wraps Up-at-row-0 to the last *mounted* row. With lazy
        # loading that would land on row 99, not on the actual most-recent
        # session. Detect the wrap intent and redirect to the real tail.
        cur = self.highlighted
        if (cur in (None, 0)) and self._has_more:
            self._load_more(None)
            try:
                self.highlighted = len(self._lazy_labels) - 1
                return
            except Exception:
                pass
        super().action_cursor_up()


def _filter_choices(all_choices: list, query: str) -> list:
    """Case-insensitive multi-term filter for `/continue` style pickers.

    `all_choices` is `[(label, value), ...]`. Each whitespace-separated token
    in `query` must hit somewhere in either:
      * the label text (cheap, always tried first), or
      * the **full** `value` when it's a string (e.g. a workspace's complete
        real path — so a mid-path directory still matches even though the
        displayed label elides the middle; display-layer truncation must not
        shrink the searchable data), or
      * the **content** of the session file at `value` (first ~1MB), so users
        who remember a phrase from inside a session ("Conductor", "subB diff",
        a file path they pasted) can find it back.

    Empty/whitespace query short-circuits to the full list. Lives at module
    scope so the smoke test can exercise it without booting the TUI.
    """
    q = (query or "").strip().lower()
    if not q:
        return list(all_choices or [])
    terms = [t for t in q.split() if t]
    if not terms:
        return list(all_choices or [])

    # Lazy import: continue_cmd already lives next to this module and provides
    # the bounded-window file grep. We keep the import inside the function so
    # other (non-/continue) pickers don't pay for it on app startup.
    try:
        from . import continue_cmd as _cc
    except Exception:
        try:
            import continue_cmd as _cc  # type: ignore
        except Exception:
            _cc = None

    out = []
    for item in (all_choices or []):
        try:
            label, value = item[0], item[1]
        except (TypeError, IndexError):
            continue
        meta = str(label).lower()
        if isinstance(value, str) and value:
            # Full value, not just basename: workspace pickers put the complete
            # real path here, and the displayed label elides the middle — search
            # must see the whole path so a mid-path term still matches.
            meta = meta + "\n" + value.lower()
        if all(t in meta for t in terms):
            out.append(item)
            continue
        # Fall back to session-file content grep so phrases that only appear
        # inside the conversation (not in the one-line preview label) still
        # surface. Path-shaped string values only — non-path values skip.
        if (
            _cc is not None
            and isinstance(value, str)
            and value
            and os.path.isfile(value)
            and _cc.file_contains_all(value, terms)
        ):
            out.append(item)
    return out


class SearchableChoiceList(Vertical):
    """Picker wrapper: an Input filter on top of an inner ChoiceList.

    Only used when `ChatMessage.searchable=True` (today: `/continue`). Other
    pickers keep mounting `ChoiceList` / `LazyChoiceList` / `MultiChoiceList`
    directly so this code path has zero blast radius outside `/continue`.

    The inner picker is rebuilt on every query change because OptionList
    doesn't expose a stable "replace all options" primitive that plays nice
    with the lazy-loading subclass. Rebuilds are cheap relative to the user's
    typing cadence and use the same eager/lazy threshold as the original
    `_mount_message` (≤50 eager, >50 lazy).
    """

    LAZY_THRESHOLD = 50

    def __init__(self, msg: "ChatMessage", initial_picker: Optional[OptionList] = None, **kwargs):
        super().__init__(**kwargs)
        self.msg = msg
        self._search_input: Optional[Input] = None
        # `initial_picker` is the eager/lazy widget that `_mount_message`
        # already built from the unfiltered choices. We reuse it on first
        # mount so the eager/lazy decision stays in one place.
        self.picker: Optional[OptionList] = initial_picker

    def compose(self):
        self._search_input = Input(
            value=self.msg.search_query or "",
            placeholder=(self.msg.search_placeholder
                         or "Search sessions: type to filter, Esc to cancel"),
            id="continue-search",
        )
        yield self._search_input
        if self.picker is None:
            self.picker = self._build_picker(self.msg.choices)
        yield self.picker

    def on_mount(self) -> None:
        # First paint: the inner picker was just yielded from compose, but a
        # LazyChoiceList populates its rows across later refresh passes. Defer
        # a scroll so we pin the *settled* wrapper height into view rather than
        # racing the lazy fill (see _rescroll_into_view).
        self._rescroll_into_view()

    def _rescroll_into_view(self) -> None:
        """Pin this picker into the viewport after its inner list (re)mounts.

        The inner LazyChoiceList fills its option rows across refresh passes,
        so the wrapper's final height isn't known until after the next layout.
        Scrolling synchronously here — or relying solely on the single
        deferred scroll_end in `_mount_message` — can fire before those rows
        land, leaving the options below the fold (the `/continue` bug seen
        with a populated history). Deferring our own `scroll_visible()` to
        after the next refresh guarantees we scroll against the settled
        height. Covers both first mount and every query rebuild. Guarded: a
        harmless no-op if the widget is already detached.
        """
        def _do():
            try:
                self.scroll_visible(animate=False)
            except Exception:
                pass
        try:
            self.call_after_refresh(_do)
        except Exception:
            _do()

    def _build_picker(self, choices: list) -> ChoiceList:
        labels = [lbl for lbl, _ in choices]
        # `classes="picker"` is what lets the OptionList.picker CSS rule
        # (`max-height: 12`) clamp the inner list's physical height. Without
        # it the inner ChoiceList falls back to OptionList's default
        # `max-height: 100%`, which — combined with this wrapper being a
        # plain Vertical (height: 1fr inside a VerticalScroll → content-sized)
        # — lets the picker grow to ≈50 rows and push the head / role / search
        # input above the viewport fold on `/continue`. The outer wrapper
        # already carries `classes="picker"` from `_mount_message`, but that
        # selector is type-qualified (`OptionList.picker, SelectionList.picker`)
        # so it does NOT match the Vertical wrapper — only the inner list it
        # builds can claim the height cap. (Root-cause fix 2026-05-27.)
        if len(choices) > self.LAZY_THRESHOLD:
            return LazyChoiceList(self.msg, labels, batch=self.LAZY_THRESHOLD, classes="picker")
        return ChoiceList(self.msg, *labels, classes="picker")

    # Debounce window for incremental filtering. Content-grep across ~270
    # session files costs ~0.2s; running it per keystroke makes the Input
    # feel laggy. Wait until the user pauses for this many seconds before
    # rebuilding the picker. Empty query still applies immediately so a
    # Ctrl+U / backspace-to-empty restores the full list with no perceptible
    # delay. Tuned 2026-05-27 on user feedback ("每输入一个 char 都会立马搜索").
    DEBOUNCE_SEC = 0.22

    def on_input_changed(self, event) -> None:
        if event.input is not self._search_input:
            return
        query = event.value or ""
        self.msg.search_query = query
        # Cancel any pending rebuild from a previous keystroke — last input
        # wins, so we never grep for an intermediate prefix the user has
        # already moved past.
        prev = getattr(self, "_debounce_timer", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:
                pass
            self._debounce_timer = None
        # Empty query: clearing the box should feel instant, no debounce.
        if not query.strip():
            self._apply_filter(query)
            return
        # Otherwise schedule a single deferred rebuild.
        try:
            self._debounce_timer = self.set_timer(
                self.DEBOUNCE_SEC,
                lambda q=query: self._apply_filter(q),
            )
        except Exception:
            # Fallback: if set_timer is unavailable for any reason, apply
            # synchronously so search at least still works.
            self._apply_filter(query)

    def _apply_filter(self, query: str) -> None:
        """Rebuild the picker for `query`. Called from the debounce timer or
        directly for the empty-query fast path. Safe to call after the widget
        has been unmounted (guards every DOM op)."""
        self._debounce_timer = None
        # If the input value has moved on while we were waiting, skip this
        # stale rebuild — a fresher timer will land shortly with the latest
        # text. This keeps fast typing snappy without queueing grep work.
        try:
            current = self._search_input.value if self._search_input else query
        except Exception:
            current = query
        if (current or "") != (query or ""):
            return
        filtered = _filter_choices(self.msg.all_choices or [], query)
        self.msg.choices = filtered
        # Remove the old picker before mounting a new one. `remove()` is sync
        # enough for our needs — Textual flushes the DOM before the next paint.
        if self.picker is not None:
            try:
                self.picker.remove()
            except Exception:
                pass
            self.picker = None
        if not filtered:
            # Show a disabled hint row so Enter on an empty result set is a
            # no-op rather than a crash inside _collapse_choice.
            empty = ChoiceList(self.msg, self.msg.empty_hint or "(no matches)", classes="picker")
            try:
                empty.disabled = True
            except Exception:
                pass
            self.picker = empty
        else:
            self.picker = self._build_picker(filtered)
        try:
            self.mount(self.picker)
        except Exception:
            # Widget likely unmounted between the timer firing and now (e.g.
            # user pressed Esc). Drop silently — nothing to render into.
            return
        # A rebuilt result set changes the wrapper height; re-pin it into view
        # so a query that shrinks/grows the list never leaves the picker (or
        # the search Input) stranded below the fold. Same deferred-scroll
        # rationale as first mount.
        self._rescroll_into_view()

    def on_key(self, event) -> None:
        # While the Input has focus, redirect navigation keys to the picker so
        # the user can keep typing yet still drive selection. Enter/Right on
        # the Input commits the current highlight.
        if self._search_input is None or self.picker is None:
            return
        if not self._search_input.has_focus:
            return
        key = event.key
        if key == "up":
            # Up from the search box wraps around to the BOTTOM of the list, so
            # the loop is search ↓→ list top ... list top ↑→ search ↑→ list
            # bottom. Land on the last row directly.
            try:
                self.picker.focus()
                last = getattr(self.picker, "action_last", None)
                if last is not None:
                    last()
                else:
                    n = getattr(self.picker, "option_count", 0)
                    if n:
                        self.picker.highlighted = n - 1
            except Exception:
                pass
            event.stop(); event.prevent_default()
            return
        if key in ("down", "pageup", "pagedown", "home", "end"):
            try:
                self.picker.focus()
                # Replay one step so the very first arrow doesn't get swallowed
                # by the focus change. Subsequent arrows go straight to the picker.
                action = {
                    "down": self.picker.action_cursor_down,
                    "pagedown": getattr(self.picker, "action_page_down", None),
                    "pageup": getattr(self.picker, "action_page_up", None),
                    "home": getattr(self.picker, "action_first", None),
                    "end": getattr(self.picker, "action_last", None),
                }.get(key)
                if action is not None:
                    action()
            except Exception:
                pass
            event.stop(); event.prevent_default()
            return
        if key == "right":
            # Right commits the highlight ONLY when the caret is already at the
            # end of the query — otherwise let the Input consume it so Right
            # still moves the caret within the search text (the box must stay
            # editable). Without this guard Right was always swallowed and the
            # cursor could never move right inside `/continue`'s search box.
            try:
                at_end = self._search_input.cursor_position >= len(self._search_input.value or "")
            except Exception:
                at_end = True
            if not at_end:
                return
        if key in ("enter", "right"):
            # Don't go through picker.action_select() here: the OptionSelected
            # it posts is constructed while *this* widget's pump is active, so
            # its _sender == picker's parent and Textual auto-stops the bubble
            # one hop up — the App handler never sees it. Collapse directly.
            committed = False
            try:
                hi = self.picker.highlighted
                opts = getattr(self.picker, "_options", [])
                # Eligibility must be checked here, not inferred from
                # _collapse_choice "not raising": it silently no-ops on an
                # out-of-range idx (the disabled empty-hint picker highlights
                # its placeholder row at 0 while msg.choices is []).
                if (hi is not None and 0 <= hi < len(self.picker.msg.choices)
                        and hi < len(opts) and not opts[hi].disabled):
                    self.app._collapse_choice(self.picker.msg, hi)
                    committed = True
            except Exception:
                pass
            # Free-input pickers (/model): Enter with no selectable match
            # commits the raw query as the value — the search box doubles as
            # a custom-name input (list still loading / fetch failed / name
            # not in the list).
            if (not committed and key == "enter"
                    and getattr(self.msg, "free_input", False)):
                q = ""
                try:
                    q = (self._search_input.value or "").strip()
                except Exception:
                    pass
                if q:
                    try:
                        self.msg.choices = list(self.msg.choices or []) + [(q, q)]
                        self.app._collapse_choice(self.msg, len(self.msg.choices) - 1)
                    except Exception:
                        pass
            event.stop(); event.prevent_default()
            return


class MultiChoiceList(SelectionList):
    """Multi-select variant of ChoiceList. Space toggles, Enter submits all
    checked items joined by `; `. Esc cancels back to free-text input.

    SelectionList expects `Selection` objects as positional args, so we
    forward `*selections` through. The `msg` kwarg is ours.
    """
    BINDINGS = [*SelectionList.BINDINGS,
                Binding("enter", "submit", "Submit", show=True),
                Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, msg: "ChatMessage", *selections, **kwargs):
        super().__init__(*selections, **kwargs)
        self.msg = msg

    def action_submit(self) -> None:
        try:
            self.app._finalize_multi_choice(self.msg, list(self.selected))
        except Exception:
            pass

    def action_cancel(self) -> None:
        try:
            self.app._cancel_choice(self.msg)
        except Exception:
            pass


class SelectableStatic(Static):
    # PR #461: a SelectableStatic that gets removed from the DOM but whose
    # reference still lingers (e.g. cached in a closure) was firing mouse
    # selection on stale screen coordinates.  has_valid_selection_parent
    # is the cheap "am I still in the tree?" probe used by the screen-
    # level mouse-event filter (`_is_stale_selectable_mouse_event`).
    def has_valid_selection_parent(self) -> bool:
        return isinstance(self.parent, Widget)

    # Widget.get_selection returns None for non-Text/Content visuals; fall back to render_line.
    def get_selection(self, selection):
        render = getattr(self, "_ga_render", None)
        if render is not None:
            return _extract_md_render(render, selection), "\n"
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


def _extract_md_render(render, selection) -> str:
    starts = render.line_starts
    indents = render.line_indents
    lens = render.line_lengths
    n = len(starts)
    if n == 0:
        return ""

    if selection.start is None:
        s_y, s_x = 0, 0
    else:
        s_y, s_x = selection.start.y, selection.start.x
    if selection.end is None:
        e_y, e_x = n - 1, lens[n - 1]
    else:
        e_y, e_x = selection.end.y, selection.end.x

    s_y = max(0, min(s_y, n - 1))
    e_y = max(0, min(e_y, n - 1))

    def col(y, x):
        ind = indents[y]
        total = lens[y]
        content_len = max(0, total - ind)
        if x <= ind:
            return 0
        return min(x - ind, content_len)

    return render.source[starts[s_y] + col(s_y, s_x): starts[e_y] + col(e_y, e_x)]


class FoldHeader(SelectableStatic):
    # Clickable collapsed/expanded turn header. App.on_click reads .msg/.fold_idx
    # to toggle msg._toggled_folds and remount the segments around this widget.
    def __init__(self, body, msg, fold_idx, **kwargs):
        super().__init__(body, **kwargs)
        self.msg = msg
        self.fold_idx = fold_idx


# User-message display elision: pastes get expanded to full content before send
# (agent needs the whole thing) but the user-visible message echo collapses the
# middle so the chat log doesn't get buried under a 1000-line dump.
_USER_DISPLAY_HEAD_LINES = 10
_USER_DISPLAY_TAIL_LINES = 5
_USER_DISPLAY_MAX_LINES = _USER_DISPLAY_HEAD_LINES + _USER_DISPLAY_TAIL_LINES + 4


def _elide_user_display(text: str) -> str:
    """Collapse middle of long user messages: keep head + tail, summarize gap."""
    lines = text.split("\n")
    n = len(lines)
    if n <= _USER_DISPLAY_MAX_LINES:
        return text
    omitted = n - _USER_DISPLAY_HEAD_LINES - _USER_DISPLAY_TAIL_LINES
    head = lines[:_USER_DISPLAY_HEAD_LINES]
    tail = lines[-_USER_DISPLAY_TAIL_LINES:]
    return "\n".join(head + [f"⋯ 省略 {omitted} 行 ⋯"] + tail)


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


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico"}


def _grab_clipboard_file() -> Optional[tuple[str, bool]]:
    """Return (path, is_image) from clipboard. is_image distinguishes image files
    (rendered inline as `[Image #N]`) from any other file (folded as `[File #N]`)."""
    try:
        from PIL import ImageGrab, Image
        data = ImageGrab.grabclipboard()
    except Exception:
        return None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str) and os.path.isfile(item):
                is_img = os.path.splitext(item)[1].lower() in _IMAGE_EXTS
                return (item, is_img)
        return None
    if isinstance(data, Image.Image):
        try:
            out_dir = os.path.join(tempfile.gettempdir(), "genericagent_tui_clipboard")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"clipboard_{int(time.time() * 1000)}.png")
            data.save(path, "PNG")
            return (path, True)
        except Exception:
            return None
    return None


class InputArea(TextArea):
    _PASTE_RE = re.compile(r'\[Pasted text #(\d+) \+\d+ lines\]')
    # `[Image #N]` is the folded form; expand_placeholders restores the raw path at submit time.
    # The longer `[Image #N: ...]` form is tolerated for backward compatibility only.
    _IMAGE_RE = re.compile(r'\[Image #(\d+)(?::[^\]]*)?\]')
    _FILE_RE = re.compile(r'\[File #(\d+)\]')
    _PLACEHOLDER_RES = (_PASTE_RE, _IMAGE_RE, _FILE_RE)

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
        # Ctrl+S: toggle-stash the current draft.  First press → stash
        # text + clear input; second press on empty input → restore the
        # stashed draft.  Independent of Up/Down history so a queued
        # draft survives sending the previous one.  reset() uses
        # TextArea.clear() to avoid the document-rebuild path that
        # blocked the UI for seconds on long sessions.
        Binding("ctrl+s",      "stash", "Stash", show=False),
        Binding("cmd+s",       "stash", "Stash", show=False),
    ]

    def action_noop(self) -> None:
        pass

    def action_stash(self) -> None:
        """Stash/restore the input draft.  reset()/text restore both defer
        to `call_after_refresh` so the layout cascade runs off the
        keystroke event, leaving Ctrl+S itself snappy on long sessions."""
        current = self.text
        if current:
            self._draft_stash = current
            self._history_index = -1
            self._history_stash = ""
            try:
                self.app.call_after_refresh(self._stash_cleanup_clear)
            except Exception:
                # Last-resort synchronous fallback (re-introduces the freeze
                # window but at least keeps the function correct).
                self._stash_cleanup_clear()
        elif self._draft_stash:
            stashed = self._draft_stash
            self._draft_stash = ""
            self._history_index = -1
            self._history_stash = ""
            try:
                self.app.call_after_refresh(self._stash_cleanup_restore, stashed)
            except Exception:
                self._stash_cleanup_restore(stashed)

    def _stash_cleanup_clear(self) -> None:
        """Deferred companion to action_stash (clear path).  The Changed
        event posted by `clear()` is async-queued — set the flag and let
        `on_text_area_changed` self-clear it when the event lands.  A
        try/finally here clears the flag too early and lets the handler
        re-run the heavy resize + palette path."""
        self._skip_change_next = True
        self.reset()
        try: self.app._hide_palette()
        except Exception: pass
        try: self.app._resize_input(self)
        except Exception: pass

    def _stash_cleanup_restore(self, stashed: str) -> None:
        """Deferred companion to action_stash (restore path).  Mirrors the
        clear path: `self.text = stashed` rebuilds Document + WrappedDocument
        and triggers a full re-wrap + screen-wide relayout, which freezes the
        UI for seconds on long sessions.  Inject through the edit pipeline
        instead so only the affected range re-wraps; `_insert_via_keyboard`
        also moves the caret to the end, re-focuses, and resizes."""
        try: self._suppress_palette_next_change()
        except Exception: pass
        if self.document.text:
            self.clear()
        self._insert_via_keyboard(stashed)

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

    def _paste_file_from_clipboard(self) -> bool:
        result = _grab_clipboard_file()
        if not result:
            return False
        path, is_image = result
        self._paste_counter += 1
        sid = self._paste_counter
        self._pastes[sid] = path
        marker = f"[Image #{sid}]" if is_image else f"[File #{sid}]"
        self._insert_via_keyboard(marker)
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

    def _paste_gesture_echo(self, source: str) -> bool:
        """One VSCode right-click can emit BOTH a forwarded mouse-click
        (→ action_paste, source='manual') and a native bracketed paste
        (→ _on_paste, source='bracketed'), pasting the clipboard twice. Treat the
        second arrival from the *other* mechanism within a short window as an echo
        and report it so the caller can skip. Same-mechanism repeats (a deliberate
        double Ctrl+V) and lone gestures are never suppressed."""
        now = time.monotonic()
        prev = self._last_paste_gesture
        if prev and prev[0] != source and now - prev[1] < 0.5:
            self._last_paste_gesture = None   # pair consumed; next gesture starts clean
            return True
        self._last_paste_gesture = (source, now)
        return False

    def action_paste(self) -> None:
        if self.read_only or self._paste_gesture_echo("manual"):
            return
        if self._paste_file_from_clipboard():
            return
        text = _read_clipboard_text() or getattr(self.app, "clipboard", "")
        if text:
            self._insert_paste_text(text)

    def action_paste_file(self) -> None:
        self._paste_file_from_clipboard()

    def _placeholder_adjacent(self, side: str) -> Optional[tuple[int, int, int, int]]:
        """Return (row, start_col, end_col, sid) if a placeholder is flush against
        the caret on the given side ('left' = backspace target, 'right' = delete target)."""
        if self.selection.start != self.selection.end:
            return None
        row, col = self.cursor_location
        try:
            line = self.text.split("\n")[row]
        except IndexError:
            return None
        for pat in self._PLACEHOLDER_RES:
            for m in pat.finditer(line):
                edge = m.end() if side == "left" else m.start()
                if edge == col:
                    return (row, m.start(), m.end(), int(m.group(1)))
        return None

    def _delete_placeholder(self, side: str) -> bool:
        hit = self._placeholder_adjacent(side)
        if not hit:
            return False
        row, start, end, sid = hit
        self.delete((row, start), (row, end))
        self._pastes.pop(sid, None)
        try:
            self.app._resize_input(self)
        except Exception:
            pass
        return True

    def action_delete_left(self) -> None:
        if not self._delete_placeholder("left"):
            super().action_delete_left()

    def action_delete_right(self) -> None:
        if not self._delete_placeholder("right"):
            super().action_delete_right()

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        # Right-button: short-circuit TextArea's default cursor-move so
        # paste lands at the user's existing caret, not where their mouse
        # happened to be — matches every native text-box right-click.
        if getattr(event, "button", 0) == 3:
            event.stop(); event.prevent_default()
            return
        await super()._on_mouse_down(event)

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
        self._last_paste_gesture: Optional[tuple[str, float]] = None  # (source, monotonic) — VSCode right-click double-paste guard
        self._input_history: list[str] = []
        self._history_index: int = -1         # -1 means not browsing
        self._history_stash: str = ""
        # Ctrl+S scratch draft (PR#479 semantics). Distinct from
        # `_history_stash`, which is the Up/Down-arrow working buffer.
        self._draft_stash: str = ""
        # Set by `action_stash` to make on_input_area_changed bail out on
        # the synchronous Changed event from `reset()` — the layout work
        # is rescheduled via `call_after_refresh` so the keystroke handler
        # returns immediately even when streaming has the reactive queue
        # saturated.  Cleared by `_stash_cleanup_clear`.
        self._skip_change_next: bool = False
        self._HISTORY_MAX = 200

    def expand_placeholders(self, text: str) -> str:
        def repl(m):
            sid = int(m.group(1))
            return self._pastes.get(sid, m.group(0))
        for pat in self._PLACEHOLDER_RES:
            text = pat.sub(repl, text)
        return text

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
        # `self.text = ""` rebuilds Document + WrappedDocument and triggers
        # a full re-wrap + `_refresh_size` layout cascade.  On long
        # sessions (100+ message widgets in the scroll), that cascade
        # blocks the UI for seconds — perceived as freeze on Ctrl+S.
        # `clear()` deletes in place via the edit pipeline and only
        # re-wraps the affected range, so empty-out is O(content-len)
        # without rebuilding the document object.
        if self.document.text:
            self.clear()
        self._pastes.clear()
        self._paste_counter = 0
        self._history_index = -1
        self._history_stash = ""

    def action_newline(self) -> None:
        self._insert_via_keyboard("\n")

    def _shift_is_physically_down(self) -> bool:
        """Best-effort fallback for terminals/Textual builds that report Shift+Enter as plain Enter."""
        if os.name != "nt":
            return False
        try:
            import ctypes
            # VK_SHIFT = 0x10.  High bit means the key is currently down.
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x10) & 0x8000)
        except Exception:
            return False

    async def _on_paste(self, event: events.Paste) -> None:
        # Terminal Ctrl+V in bracketed-paste mode lands here, bypassing action_paste.
        if self.read_only:
            return
        event.stop(); event.prevent_default()
        # VSCode right-click fires this Paste AND a forwarded mouse-click
        # (→ _on_click → action_paste); collapse the duplicate. See _paste_gesture_echo.
        if self._paste_gesture_echo("bracketed"):
            return
        if self._paste_file_from_clipboard():
            return
        # Git-bash / mintty fallback: PIL.ImageGrab can't return Image objects
        # in that TTY env, but the OS clipboard does hold the file path the
        # screenshot tool wrote. Treat a single-line, on-disk path as if the
        # file grab had succeeded — same placeholder + `_pastes` entry.
        if self._paste_file_from_text(event.text):
            return
        self._insert_paste_text(event.text)

    def _paste_file_from_text(self, raw: str) -> bool:
        if not raw: return False
        path = raw.strip().strip('"').strip("'")
        if "\n" in path or "\r" in path: return False
        if len(path) > 1024: return False
        if not os.path.isfile(path): return False
        is_image = os.path.splitext(path)[1].lower() in _IMAGE_EXTS
        self._paste_counter += 1
        sid = self._paste_counter
        self._pastes[sid] = path
        marker = f"[Image #{sid}]" if is_image else f"[File #{sid}]"
        self._insert_via_keyboard(marker)
        return True

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
            # Pending-queue recall removed: each Enter while running writes
            # to `_intervene` immediately; popping back would leave a stale
            # entry in the file.  Up just walks input history; Esc clears.
            if self._history_up():
                event.stop(); event.prevent_default(); return
        if event.key == "down":
            row, col = self.cursor_location
            lines = self.text.split("\n")
            if row == len(lines) - 1 and col == len(lines[-1]):
                if self._history_down():
                    event.stop(); event.prevent_default(); return
        if event.key == "enter":  # plain Enter submits; physical Shift+Enter inserts newline
            if self._shift_is_physically_down():
                event.stop(); event.prevent_default()
                self.action_newline()
                return
            event.stop(); event.prevent_default()
            self.post_message(self.Submitted(self, self.text))
            return
        if self._history_index != -1 and event.key not in ("up", "down", "left", "right"):
            self._history_index = -1
        await super()._on_key(event)


# ---------- top bar ----------
def _fmt_elapsed(secs: int) -> str:
    if secs < 60: return f"{secs}s"
    if secs < 3600: return f"{secs // 60}m {secs % 60:02d}s"
    h, rem = divmod(secs, 3600); m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


_TITLE_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Done-flash window: dot stays green this many seconds after a run finishes.
_DONE_FLASH_SECS = 5

# Heat ramp for the running dot. Pale green → amber → deep orange → vivid red.
# The thresholds are deliberately non-linear: short runs stay cool, only past
# ~3min do we paint it red to signal "this is taking unusually long".
_HEAT_RAMP = (
    (20,  "#aae8aa"),       # <20s   pale mint
    (60,  "#d4a72c"),       # <60s   amber
    (180, "#dc6b1f"),       # <3min  deep orange
    (None, "bold #ff2c2c"), # ≥3min  vivid red — "stuck?" warning
)


def _heat_color(elapsed: int) -> str:
    """Map a busy-elapsed in seconds to a Rich style for the running dot."""
    for threshold, color in _HEAT_RAMP:
        if threshold is None or elapsed < threshold:
            return color
    return _HEAT_RAMP[-1][1]


# Gerund (`Reticulating…`) easter-egg color ramp. Drives a two-axis heat:
# elapsed seconds + accumulated tokens. Cool blue → cyan → mint → amber → red.
# Each tier returns a Rich style string. Keep bands wide so the color rarely
# strobes between adjacent ticks.
_GERUND_RAMP = (
    "#5e9fd6",          # cool blue   — fresh, < ~10s and < ~1k tokens
    "#56d4d4",          # cyan        — warming up
    "#7ec27e",          # mint        — settled cruise
    "#d4a72c",          # amber       — taking a while
    "#dc6b1f",          # deep orange — long wait
    "bold #ff2c2c",     # vivid red   — really stuck
)


def _gerund_color(elapsed: int, tokens: int) -> str:
    """Compose a tier index from elapsed (sec) + tokens, then index the ramp.

    The two axes contribute additively so a tokenless 3-minute hang and a
    fast-but-token-heavy run both walk up the ramp. Tiers are integer-clamped
    to len(ramp)-1 so the worst case caps at the red band.
    """
    t_tier = 0 if elapsed < 10 else 1 if elapsed < 30 else 2 if elapsed < 90 else 3 if elapsed < 180 else 4
    k_tier = 0 if tokens < 1_000 else 1 if tokens < 10_000 else 2 if tokens < 50_000 else 3
    tier = min(len(_GERUND_RAMP) - 1, t_tier + k_tier)
    return _GERUND_RAMP[tier]


def render_status_chip(busy: bool, elapsed: int = 0) -> Text:
    """`✦ GenericAgent` identity chip. Brightens green when any session is busy.

    The `elapsed` kwarg is kept for API stability but intentionally unrendered:
    the per-session dot now carries the elapsed counter, which is more accurate
    than an app-wide tally when multiple sessions run concurrently.
    """
    chip = Text()
    chip.append("✦ ", style=C_GREEN if busy else C_DIM)
    chip.append("GenericAgent", style=f"bold {C_GREEN}" if busy else f"bold {C_FG}")
    return chip


def render_topbar(session_name: str, status: str, model: str, tasks_running: int,
                  fold_mode: bool = True, busy_elapsed: int = 0,
                  effort: str = "", sess_elapsed: int = 0,
                  just_done: bool = False, term_width: int = 0,
                  workspace: str = "") -> Table:
    # Layout: identity-chip + session + status + fold packed LEFT; model + effort
    # + tasks CENTERED; clock RIGHT. The 2:2:1 ratio keeps the centered model
    # chip visually anchored even when the left column has the long status pill.
    # The OS terminal tab title carries the session name separately — see
    # GenericAgentTUI._update_terminal_title.
    t = Table.grid(expand=True)
    # Equal column widths so the middle column's geometric center sits at the
    # window center. Uneven ratios shift the centered band off-axis.
    t.add_column(ratio=1, justify="left", no_wrap=True, overflow="ellipsis")
    t.add_column(ratio=1, justify="center", no_wrap=True, overflow="ellipsis")
    t.add_column(ratio=1, justify="right", no_wrap=True)

    short_name = session_name if len(session_name) <= 20 else session_name[:19] + "…"

    # LEFT: identity chip · session · status
    left = Text()
    left.append_text(render_status_chip(busy=tasks_running > 0, elapsed=busy_elapsed))
    left.append("  ·  ", style=C_DIM)
    left.append("session: ", style=C_MUTED); left.append(short_name, style=f"bold {C_CHIP_NAME}")
    left.append("  ·  ", style=C_DIM)
    if status == "running":
        dot_color = _heat_color(sess_elapsed)
        left.append("● ", style=dot_color)
        left.append(f"running {_fmt_elapsed(sess_elapsed)}", style=f"bold {dot_color}")
    elif just_done:
        left.append("● ", style=f"bold {C_GREEN}")
        left.append("done", style=f"bold {C_GREEN}")
    else:
        left.append("● ", style=C_DIM); left.append(status, style=C_MUTED)

    # CENTER: model · effort · tasks — dropped right-to-left on narrow terminals
    # so the chip column never wraps under the left half.
    budget = max(20, (term_width * 2 // 5) - 6) if term_width else 999
    def chip_w(label: str, value: str) -> int:
        return len(label) + len(value) + 5
    used = chip_w("model: ", model or "?")
    show_effort = bool(effort) and used + chip_w("effort: ", effort) <= budget
    if show_effort: used += chip_w("effort: ", effort)
    show_tasks = used + chip_w("tasks: ", str(tasks_running)) <= budget
    mid = Text()
    mid.append("model: ", style=C_MUTED); mid.append(model or "?", style=C_CHIP_MODEL)
    if show_effort:
        mid.append("  ·  ", style=C_DIM)
        mid.append("effort: ", style=C_MUTED); mid.append(effort, style=f"bold {C_CHIP_EFFORT}")
    if show_tasks:
        mid.append("  ·  ", style=C_DIM)
        mid.append("tasks: ", style=C_MUTED); mid.append(str(tasks_running), style=C_CHIP_TASKS)

    # RIGHT: fold indicator + clock. Moved here from the LEFT column to keep the
    # narrow `▾ fold` glyph from being eaten by the left's ellipsis when the
    # running status pill fills the column budget.
    right = Text()
    # workspace chip (top-right) — only when active. Clean real-dir basename,
    # never the hashed junction name, so the hash never reaches the user.
    if workspace:
        short_ws = workspace if len(workspace) <= 18 else workspace[:17] + "…"
        right.append("workspace: ", style=C_MUTED)
        right.append(short_ws, style=f"bold {C_GREEN}")
        right.append("  ·  ", style=C_DIM)
    if fold_mode:
        right.append("▾ fold", style=C_DIM)
        right.append("  ·  ", style=C_DIM)
    right.append(time.strftime("%H:%M:%S"), style=C_CHIP_TIME)

    t.add_row(left, mid, right)
    return t


def render_bottombar(quit_armed: bool = False, rewind_armed: bool = False) -> Table:
    t = Table.grid(expand=True)
    t.add_column(justify="left")
    left = Text()
    if quit_armed:
        left.append(f"再按 {fmt_key('ctrl+c')} 退出", style=f"bold {C_GREEN}")
    elif rewind_armed:
        left.append("再按 Esc 回退", style=f"bold {C_GREEN}")
    else:
        pairs = [("enter", "发送"), ("ctrl+n", "新会话"),
                 ("ctrl+b", "侧栏"), ("ctrl+c", "停止/退出"),
                 ("/", "命令面板"), ("ctrl+/", "快捷键帮助")]
        for i, (combo, d) in enumerate(pairs):
            if i: left.append("    ")
            k = "/" if combo == "/" else fmt_key(combo)
            left.append(k, style=C_GREEN if combo in ("/", "ctrl+/") else C_FG)
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
        # C_DIM blends bg/fg at 0.35 — under SEL_BG on the active row the contrast
        # collapses (e.g. tokyo-night). C_MUTED (0.55 blend) stays readable in both.
        sess_tbl.add_row(blank, blank,
                         Text(f"{label}: {txt}", style=C_MUTED, no_wrap=True, overflow="ellipsis"),
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
        background: $ga-alt-bg;
        border: solid $ga-border;
        padding: 1 2;
        color: $ga-fg;
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


class ThemePicker(ModalScreen):
    # Live-preview theme picker: highlight applies the theme so the rest of the
    # UI repaints behind the modal; Enter commits + persists, Esc reverts.
    CSS = """
    ThemePicker { align: center middle; }
    ThemePicker > OptionList {
        width: 36;
        max-height: 80%;
        background: $ga-alt-bg;
        border: solid $ga-border;
        padding: 0 1;
        color: $ga-fg;
    }
    ThemePicker > OptionList > .option-list--option-highlighted {
        background: $ga-sel-bg;
        color: $ga-fg;
    }
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter",  "commit", "Apply",  show=False),
    ]

    def __init__(self, themes: list[str], current: str) -> None:
        super().__init__()
        self._themes = themes
        self._initial = current

    def compose(self) -> ComposeResult:
        ol = OptionList(*self._themes, id="theme-picker")
        yield ol

    def on_mount(self) -> None:
        ol = self.query_one(OptionList)
        try:
            ol.highlighted = self._themes.index(self._initial)
        except ValueError:
            ol.highlighted = 0
        ol.focus()

    def on_option_list_option_highlighted(self, ev) -> None:
        name = self._themes[ev.option_index]
        if self.app.theme != name:
            self.app.theme = name

    def on_option_list_option_selected(self, ev) -> None:
        self.action_commit()

    def action_commit(self) -> None:
        _save_settings({"theme": self.app.theme})
        self.dismiss()

    def action_cancel(self) -> None:
        if self.app.theme != self._initial:
            self.app.theme = self._initial
        self.dismiss()


class GenericAgentTUI(App[None]):

    CSS = _MAIN_CSS

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
        Binding("ctrl+d",     "drop_session",  "Drop",  show=False, priority=True),
        Binding("cmd+d",      "drop_session",  "Drop",  show=False, priority=True),
        # Terminals report Ctrl+/ as ctrl+slash or legacy ctrl+_ (ASCII 0x1F); bind both.
        Binding("ctrl+slash", "show_help", "Help", show=False),
        Binding("ctrl+/",     "show_help", "Help", show=False),
        Binding("ctrl+underscore", "show_help", "Help", show=False),
        Binding("cmd+slash",  "show_help", "Help", show=False),
        Binding("cmd+/",      "show_help", "Help", show=False),
        Binding("escape",     "escape",        "Close", show=False),
        Binding("tab",        "complete_command", "Complete", show=False, priority=True),
        Binding("ctrl+t",     "pick_theme",    "Theme", show=False),
    ]

    def __init__(self, agent_factory: Optional[AgentFactory] = None) -> None:
        super().__init__()
        self.agent_factory: AgentFactory = agent_factory or default_agent_factory
        self.sessions: dict[int, AgentSession] = {}
        self.current_id: Optional[int] = None
        # Wall-clock marker used by `/cost` to scope subagent log scans to
        # logs touched after the TUI started — pre-launch leftovers shouldn't
        # bleed into "this run's" total.
        self._started_at: float = time.time()
        self._ids = count(1)
        self._suppress_palette_open = False
        self.fold_mode: bool = True
        self._last_size: tuple[int, int] = (-1, -1)
        self._resize_timer = None
        self._quit_armed: bool = False
        self._quit_timer = None
        self._rewind_armed: bool = False
        self._rewind_timer = None
        self._busy_since: Optional[float] = None
        self._chip_timer = None
        self._title_frame: int = 0
        self._title_timer = None
        self._last_title: str = ""
        # Register our github-dark palette as a first-class Textual theme; the other
        # cycle entries are Textual built-ins (nord, gruvbox, dracula, tokyo-night,
        # textual-light), whose ga-* CSS slots are derived in get_css_variables.
        from textual.theme import Theme as _TxTheme
        p = _DEFAULT_PALETTE
        self.register_theme(_TxTheme(
            name="ga-default", dark=True,
            background=p["bg"], surface=p["alt_bg"], panel=p["sel_bg"],
            foreground=p["fg"],
            primary=p["green"], secondary=p["blue"], accent=p["purple"],
        ))
        saved = _load_settings().get("theme")
        self.theme = saved if saved in _THEME_CYCLE else "ga-default"
        self._spinner_frame: int = 0
        self._spinner_timer = None
        self._handlers: dict = {
            "help": self._cmd_help, "status": self._cmd_status, "sessions": self._cmd_status,
            "new": self._cmd_new, "switch": self._cmd_switch, "close": self._cmd_close,
            "rename": self._cmd_rename,
            "branch": self._cmd_branch, "rewind": self._cmd_rewind, "clear": self._cmd_clear,
            "stop": self._cmd_stop, "llm": self._cmd_llm, "model": self._cmd_model,
            "effort": self._cmd_effort,
            "export": self._cmd_export,
            "restore": self._cmd_restore, "btw": self._cmd_btw, "review": self._cmd_review,
            "continue": self._cmd_continue, "cost": self._cmd_cost,
            "workspace": self._cmd_workspace,
            "reload-keys": self._cmd_reload_keys,
            # slash_cmds bundle — see frontends/slash_cmds.py for the prompt
            # bodies + reflect/scheduler discovery.  All but /scheduler are
            # thin shims that build a prompt and re-enter submit_user_message,
            # so the agent processes them as ordinary turns.
            "update": self._cmd_slash_inject, "autorun": self._cmd_slash_inject,
            "morphling": self._cmd_slash_inject, "goal": self._cmd_slash_inject,
            "hive": self._cmd_slash_inject, "conductor": self._cmd_slash_inject,
            "scheduler": self._cmd_scheduler,
            "quit": self._cmd_quit, "exit": self._cmd_quit,
        }
        try:
            import cost_tracker; cost_tracker.install()
        except Exception:
            pass
        # Patch GenericAgent for /review in case chatapp_common didn't wire it.
        try:
            from agentmain import GenericAgent as _GA
            import review_cmd; review_cmd.install(_GA)
        except Exception:
            pass
        # Drop session_names entries pointing at rotated-away logs.
        try:
            import session_names; session_names.gc()
        except Exception:
            pass

    # PR #461 (upstream 08f21e8): suppress mouse events that target a
    # SelectableStatic whose parent is no longer in the widget tree.
    # Such widgets persist as cached references (e.g. the ChatMessage
    # picker collapse path stashes the previous body widget) but they're
    # no longer mounted, so any MouseDown/MouseMove on their old screen
    # rect would fire selection callbacks on detached objects → crash.
    def _is_stale_selectable_mouse_event(self, event) -> bool:
        if not isinstance(event, (events.MouseDown, events.MouseMove)):
            return False
        try:
            select_widget, select_offset = self.screen.get_widget_and_offset_at(
                event.x, event.y
            )
        except Exception:
            return False
        return (
            select_offset is not None
            and isinstance(select_widget, SelectableStatic)
            and not select_widget.has_valid_selection_parent()
        )

    async def on_event(self, event) -> None:
        if self._is_stale_selectable_mouse_event(event):
            if isinstance(event, events.MouseDown):
                try:
                    self.screen.clear_selection()
                except Exception:
                    pass
            event.stop()
            return
        await super().on_event(event)

    def compose(self) -> ComposeResult:
        yield Static("", id="topbar")
        with Horizontal(id="body"):
            _sidebar = VerticalScroll(Static("", id="sidebar"), id="sidebar-scroll")
            _sidebar.can_focus = False
            yield _sidebar
            with Vertical(id="main"):
                yield VerticalScroll(id="messages")
                # Plan card: pinned header/step (#planbar-head) above a task list
                # (#planbar) that scrolls inside a 4-row window (#planbar-tasks).
                with Vertical(id="planbar-scroll"):
                    yield Static("", id="planbar-head")
                    _tasks = VerticalScroll(Static("", id="planbar"), id="planbar-tasks")
                    _tasks.can_focus = False  # don't steal Tab focus from input
                    yield _tasks
                yield OptionList(id="palette")
                yield InputArea(
                    "",
                    id="input",
                    soft_wrap=True,
                    show_line_numbers=False,
                    compact=True,
                    highlight_cursor_line=False,
                    placeholder=f"输入指令或问题... (Enter 发送, {fmt_key('ctrl+j')} 换行, / 唤起命令面板)",
                )
                # Tip line sits inside #main so it doesn't compete for height
                # with #body's 1fr. Content set at compose so the first frame
                # already shows it.
                yield Static(_tip_line(_random_tip()), id="tipbar")
        yield Static(render_bottombar(), id="bottombar")

    def on_mount(self) -> None:
        _sweep_stale_task_dirs()  # clear empty signal dirs left by prior runs
        try: workspace_cmd.cleanup()  # remove dangling/unregistered workspace junctions
        except Exception: pass
        try: workspace_cmd.session_map_prune()  # drop session→ws entries whose log is gone
        except Exception: pass
        get_index(os.path.join(ROOT_DIR, "temp")).warm()   # @ 补全：预热未绑时的默认根（temp）
        self.add_session("main")
        self._system(f"Welcome to GenericAgent TUI. 按 / 唤起命令面板，{fmt_key('ctrl+n')} 新建会话。")

        # CSS `#planbar-scroll { display: none }` keeps it hidden by default —
        # the renderer adds `-visible` once plan items materialize.
        self.query_one("#input", InputArea).focus()
        self.set_interval(0.5, self._tick)
        self._patch_auto_scroll_for_selection()
        self._start_plan_watcher()
        self._start_tip_rotator()
        self._apply_responsive_layout()
        # Disable alternate scroll mode (?1007). Textual enables ?1006 SGR mouse but doesn't
        # turn off ?1007, which on macOS Terminal / iTerm2 makes the wheel emit both mouse
        # events and ↑/↓ keys — triggering InputArea history nav.
        self._term_write("\x1b[?1007l")

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
        # Per-session task_dir path enables ga's `_intervene` / `_keyinfo`
        # consume paths (ga.py:575).  PID+session scoped so concurrent
        # sessions don't share signal files.  We only set the *path* here —
        # the dir is created lazily by the writer (`_session_intervene_path`)
        # when a signal is actually injected.  Eager makedirs left a stale
        # empty `temp/_tui_v2_<pid>_<id>` behind for every session that never
        # used intervene; `consume_file` tolerates a missing dir.
        try:
            agent.task_dir = os.path.join(FRONTENDS_DIR, '..', 'temp',
                                          f'_tui_v2_{os.getpid()}_{agent_id}')
        except Exception:
            pass
        try:
            # Opt TUI v2 agents into per-agent project-mode selection. The
            # plugin falls back to the legacy pid anchor only when this
            # private attribute is absent, so None here means "ordinary mode"
            # for this session rather than "use the process-global workspace".
            agent._ga_project_mode_name = None
            agent._ga_project_mode_workspace_path = ""
        except Exception:
            pass
        sess = AgentSession(agent_id=agent_id, name=name or f"agent-{agent_id}", agent=agent)
        thread = threading.Thread(target=agent.run, name=f"ga-tui-agent-{agent_id}", daemon=True)
        thread.start()
        sess.thread = thread
        self.sessions[agent_id] = sess
        self.current_id = agent_id
        self._install_ask_user_hook(sess)
        self._install_intervene_replay_hook(sess)
        self._install_write_snapshot_hook()
        self._refresh_all()
        return sess

    def _bind_workspace(self, sess: AgentSession, info: Optional[dict]) -> None:
        if info:
            sess.workspace_name = info.get("name") or ""
            sess.workspace_path = info.get("target") or info.get("path") or ""
            sess.workspace_link = info.get("link") or ""
            project_name = sess.workspace_name or None
            project_path = sess.workspace_path
        else:
            sess.workspace_name = ""
            sess.workspace_path = ""
            sess.workspace_link = ""
            project_name = None
            project_path = ""
        try:
            sess.agent._ga_project_mode_name = project_name
            sess.agent._ga_project_mode_workspace_path = project_path
        except Exception:
            pass
        # 持久化绑定/off → /continue 即时恢复，不必先聊一轮留 PROJECT MODE 块。
        workspace_cmd.session_ws_set(getattr(sess.agent, "log_path", "") or "", project_path or "")
        if project_path:
            get_index(project_path).warm()  # @ 候选跟随 workspace

    def _at_root(self, sess: Optional["AgentSession"] = None) -> str:
        # @ 索引根：绑了 workspace 用真实 target；否则用 agent 的实际工作目录
        # ROOT_DIR/temp（file_read/code_run 都相对它），而非飘忽的 os.getcwd()。
        # 一律真实路径，绝不暴露哈希 junction 名。
        s = sess or (self.sessions.get(self.current_id) if self.current_id is not None else None)
        return (s.workspace_path if s and s.workspace_path else os.path.join(ROOT_DIR, "temp"))

    _write_snapshot_hook_installed = False

    def _install_write_snapshot_hook(self) -> None:
        """Register one global `tool_before` hook that captures the structured
        args of every file_write/file_patch (plus a file_write target's pre-write
        content) into `_WRITE_CAP`, keyed by `hash(get_pretty_json(args))`.

        That hash is the bridge to the display layer: agent_loop renders the same
        `get_pretty_json(args)` inside the verbose `📥 args:` fence, so at render
        time `_render_md` hashes the fence body and looks the real args back up —
        no need to parse the newline-mangled pretty JSON. Content-addressed, so it
        survives re-renders and pairs each block with its exact call. The registry
        is process-global, so install at most once."""
        if GenericAgentTUI._write_snapshot_hook_installed:
            return
        try:
            from plugins import hooks as _ph
            from agent_loop import get_pretty_json

            def _strip_dispatch_keys(raw):
                # dispatch() injects `_index`/`_tool_num` into args *before* the
                # hooks fire, but the verbose display (agent_loop.py:78) ran
                # get_pretty_json on the args *before* dispatch — i.e. without
                # those keys. Strip them so our hash matches the fence body the
                # renderer will hash.
                return {k: v for k, v in (raw or {}).items()
                        if k not in ("_index", "_tool_num")}

            def _snap(ctx):
                try:
                    name = (ctx or {}).get("tool_name")
                    if name not in ("file_write", "file_patch", "file_read", "code_run"):
                        return ctx
                    handler = (ctx or {}).get("self")
                    args = _strip_dispatch_keys((ctx or {}).get("args"))
                    if name == "code_run":
                        # No path; the card shows args (code) + the result
                        # stamped by _snap_after. Keyed the same way.
                        _WRITE_CAP[hash(get_pretty_json(args))] = {
                            "name": name, "args": args,
                        }
                        if len(_WRITE_CAP) > 256:
                            for k in list(_WRITE_CAP)[:128]:
                                _WRITE_CAP.pop(k, None)
                        return ctx
                    path = args.get("path")
                    if not path or handler is None:
                        return ctx
                    if name == "file_read":
                        # No disk snapshot needed — the read card shows the
                        # tool's own result, stamped by _snap_after from
                        # StepOutcome.data.
                        _WRITE_CAP[hash(get_pretty_json(args))] = {
                            "name": name, "args": args,
                        }
                    else:
                        # Snapshot the pre-write full file for BOTH write tools:
                        # file_write overwrite diffs against it, and file_patch
                        # uses it to render a whole-file diff (real line numbers
                        # + surrounding context) instead of just the fragment.
                        existed, old = False, ""
                        try:
                            abs_path = handler._get_abs_path(path)
                            existed = os.path.exists(abs_path)
                            if existed:
                                with open(abs_path, "r", encoding="utf-8") as f:
                                    old = f.read()
                        except Exception:
                            existed, old = False, ""
                        _WRITE_CAP[hash(get_pretty_json(args))] = {
                            "name": name, "args": args, "existed": existed, "old": old,
                        }
                    # Bound memory: keep only the most recent captures.
                    if len(_WRITE_CAP) > 256:
                        for k in list(_WRITE_CAP)[:128]:
                            _WRITE_CAP.pop(k, None)
                except Exception:
                    pass
                return ctx

            def _snap_after(ctx):
                # Stamp the outcome onto the same capture: write tools get
                # {status, msg} for the header ✗; file_read gets the result text
                # itself (its StepOutcome.data IS the content the card shows).
                try:
                    name = (ctx or {}).get("tool_name")
                    if name not in ("file_write", "file_patch", "file_read", "code_run"):
                        return ctx
                    args = _strip_dispatch_keys((ctx or {}).get("args"))
                    data = getattr((ctx or {}).get("ret"), "data", None)
                    h = hash(get_pretty_json(args))
                    if h not in _WRITE_CAP:
                        return ctx
                    if name == "file_read":
                        if isinstance(data, str):
                            _WRITE_CAP[h]["content"] = data
                    elif name == "code_run":
                        # data is the StepOutcome.data verbatim: dict
                        # {status,stdout,exit_code} | {status:error,msg} | str.
                        _WRITE_CAP[h]["data"] = data
                    elif isinstance(data, dict):
                        _WRITE_CAP[h]["status"] = data.get("status")
                        _WRITE_CAP[h]["msg"] = str(data.get("msg") or "")
                except Exception:
                    pass
                return ctx

            _ph.register("tool_before")(_snap)
            _ph.register("tool_after")(_snap_after)
            GenericAgentTUI._write_snapshot_hook_installed = True
        except Exception:
            pass

    def _install_ask_user_hook(self, sess: AgentSession) -> None:
        """Capture ask_user INTERRUPT payloads from agent_loop's turn_end hook.

        The agent yields `{"status": "INTERRUPT", "intent": "HUMAN_INTERVENTION",
        "data": {question, candidates}}` via `exit_reason.data`. We push events
        onto the session queue; `_on_stream(done=True)` drains and posts an
        interactive ChoiceList ChatMessage. Candidates pass through
        `_sanitize_candidates` so envelope debris / numbered prefixes / mashed
        multi-line strings don't leak into the picker.

        ga.turn_end_callback reads hooks from `self.parent._turn_end_hooks`
        where `parent` is the GenericAgent — so the dict lives on the agent.
        """
        agent = sess.agent
        try:
            hooks = getattr(agent, "_turn_end_hooks", None)
            if hooks is None:
                hooks = agent._turn_end_hooks = {}
            def _hook(ctx, _q=sess.ask_user_events):
                er = (ctx or {}).get("exit_reason") or {}
                if er.get("result") != "EXITED": return
                payload = er.get("data")
                if not isinstance(payload, dict): return
                if payload.get("status") != "INTERRUPT" or payload.get("intent") != "HUMAN_INTERVENTION": return
                data = payload.get("data") or {}
                cands = _sanitize_candidates(data.get("candidates"))
                if not cands: return
                q = str(data.get("question") or "请选择：").strip() or "请选择："
                _q.put({"question": q, "candidates": cands})
            hooks["_ga_tui_ask_user"] = _hook
        except Exception:
            pass

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

    def copy_to_clipboard(self, text: str) -> None:
        self._clipboard = text
        _ssh = os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY")
        if not _ssh and _copy_to_clipboard(text):
            return
        super().copy_to_clipboard(text)

    def action_handle_ctrl_c(self) -> None:
        # Two-stage quit: when no task is running, first press clears input and arms;
        # second press within 2s exits.
        try:
            inp = self.query_one("#input", InputArea)
        except Exception:
            inp = None
        # Copy precedence: focused InputArea selection first (screen-level selection
        # doesn't cover TextArea internals), then screen drag selection.
        if inp is not None and self.focused is inp and inp.selected_text:
            try: self.copy_to_clipboard(inp.selected_text)
            except Exception: pass
            self._disarm_quit()
            return
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

    def _disarm_rewind(self) -> None:
        if not self._rewind_armed and self._rewind_timer is None:
            return
        self._rewind_armed = False
        if self._rewind_timer is not None:
            try: self._rewind_timer.stop()
            except Exception: pass
            self._rewind_timer = None
        try: self._refresh_bottombar()
        except Exception: pass

    def on_key(self, event: events.Key) -> None:
        if self._quit_armed and event.key not in ("ctrl+c", "cmd+c"):
            self._disarm_quit()
        if self._rewind_armed and event.key != "escape":
            self._disarm_rewind()

    def action_toggle_sidebar(self) -> None:
        # display:none/block reflow doesn't always settle within one refresh, so
        # mirror the resize debounce: invalidate width-keyed caches, then remount
        # via a short timer (call_after_refresh alone races the layout and the
        # remount can capture the old content_region.width — leaving messages
        # wrapped at the previous width after Ctrl+B).
        sidebar = self.query_one("#sidebar-scroll", VerticalScroll)
        sidebar.toggle_class("-hidden")
        for sess in self.sessions.values():
            for m in sess.messages:
                if m.role == "assistant":
                    m._cached_body = None
                    m._cache_key = ()
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.05, self._flush_resize)

    def action_toggle_fold(self) -> None:
        self.fold_mode = not self.fold_mode
        # Global toggle is authoritative: clear per-fold overrides so the new state
        # is uniformly all-collapsed or all-expanded.
        for sess in self.sessions.values():
            for m in sess.messages:
                if m.role == "assistant":
                    m._toggled_folds.clear()
                    m._cached_body = None
                    m._cache_key = ()
        self._remount_current_session()
        self._refresh_topbar()
        self.notify(f"Fold: {'on' if self.fold_mode else 'off'}", timeout=1)

    def action_escape(self) -> None:
        # Back out of free-text-input mode → restore the picker the user was
        # answering. Takes priority over the normal Esc path so the InputArea
        # doesn't eat the press.
        if self._return_from_free_text():
            self._disarm_rewind()
            return
        choice = self._active_choice()
        if choice is not None:
            self._cancel_choice(choice.msg)
            self._disarm_rewind()
            return
        try:
            palette = self.query_one("#palette", OptionList)
        except Exception:
            palette = None
        if palette is not None and palette.has_class("-visible"):
            self._hide_palette()
            self.query_one("#input", InputArea).focus()
            self._disarm_rewind()
            return
        # Pending-queue cancel: Esc with the input empty and entries queued
        # drops the lot.  Runs before quit-arm so a single Esc clears the
        # queue (no second-press needed).
        try:
            sess = self.current
        except Exception:
            sess = None
        if sess is not None and sess.pending:
            try:
                inp_empty = not (self.query_one("#input", InputArea).text or "")
            except Exception:
                inp_empty = True
            if inp_empty:
                with sess.pending_lk:
                    n = len(sess.pending)
                    sess.pending = []
                    sess.pending_wrapped = []
                self._clear_intervene(sess)
                self._system(f"已清空 {n} 条待发送消息")
                self._disarm_rewind()
                return
        if self._quit_armed:
            self._disarm_quit()
            return
        if self._rewind_armed:
            self._disarm_rewind()
            self._cmd_rewind([], "")
            return
        self._rewind_armed = True
        self._refresh_bottombar()
        if self._rewind_timer is not None:
            try: self._rewind_timer.stop()
            except Exception: pass
        self._rewind_timer = self.set_timer(2.0, self._disarm_rewind)

    def action_drop_session(self) -> None:
        # Sidebar-only removal: drops the in-memory session so it stops appearing
        # in the sidebar/switcher. The on-disk log + session_names entry are kept,
        # so the session is still recoverable via `/continue <name>` later.
        if len(self.sessions) <= 1:
            self._system("⚠️ 至少保留一个会话")
            return
        sid = self.current_id
        name = self.current.name
        ids = list(self.sessions)
        i = ids.index(sid)
        next_id = ids[i + 1] if i + 1 < len(ids) else ids[i - 1]
        del self.sessions[sid]
        self.current_id = next_id
        self._last_title = ""  # force title refresh on next call
        self._refresh_all()
        self._system(f"✅ 已从侧栏移除 #{sid} {name!r}")

    def action_show_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(HelpScreen(self._render_help()))

    def action_pick_theme(self) -> None:
        if isinstance(self.screen, ThemePicker):
            return
        self.push_screen(ThemePicker(list(_THEME_CYCLE), self.theme or "ga-default"))

    def _resolve_palette(self) -> dict[str, str]:
        theme = self.current_theme
        if theme is not None and theme.name == "ga-default":
            return dict(_DEFAULT_PALETTE)
        base = super().get_css_variables()
        dark = bool(getattr(theme, "dark", True)) if theme is not None else True
        return _palette_from_resolved_vars(base, dark)

    def get_css_variables(self) -> dict[str, str]:
        base = super().get_css_variables()
        p = self._resolve_palette()
        for k, v in p.items():
            base[f"ga-{k.replace('_', '-')}"] = v
        return base

    def watch_theme(self, _old_theme, _new_theme) -> None:
        # Triggered by `self.theme = name`. Sync Python-side state (palette dict,
        # C_* globals, cached widgets) so Rich Text and Markdown also follow.
        theme = self.current_theme
        if theme is None: return
        global _palette, C_FG, C_MUTED, C_DIM, C_SEL_BG, C_GREEN, C_BLUE, C_PURPLE
        global C_CHIP_NAME, C_CHIP_MODEL, C_CHIP_EFFORT, C_CHIP_TASKS, C_CHIP_TIME
        _palette = self._resolve_palette()
        C_FG, C_MUTED, C_DIM = _palette["fg"], _palette["muted"], _palette["dim"]
        C_SEL_BG = _palette["sel_bg"]
        C_GREEN, C_BLUE, C_PURPLE = _palette["green"], _palette["blue"], _palette["purple"]
        C_CHIP_NAME   = _palette["chip_name"]
        C_CHIP_MODEL  = _palette["chip_model"]
        C_CHIP_EFFORT = _palette["chip_effort"]
        C_CHIP_TASKS  = _palette["chip_tasks"]
        C_CHIP_TIME   = _palette["chip_time"]
        # watch_theme fires once during __init__ when we set ga-default — at that
        # point sessions is empty and the DOM isn't composed yet. Skip the rebuild.
        if not self.is_mounted or self.current_id is None:
            return
        # Cached Rich Text / Markdown captured the old hex values; force a remount.
        for s in self.sessions.values():
            for m in s.messages:
                m._cache_key = None
                m._cached_body = None
                m._seg_render_cache.clear()
                m._segment_widgets = []
                m._segment_sig = ()
                m._role_widget = None
                m._body_widget = None
                m._hint_widget = None
                m._spinner_widget = None
        try:
            self._remount_current_session()
            self._refresh_topbar()
            self._refresh_sidebar()
            self._refresh_bottombar()
        except Exception:
            pass

    def _render_help(self) -> Text:
        rows = [
            ("Enter",                            "发送"),
            (fmt_keys("ctrl+j", "ctrl+enter"),   "换行（Shift+Enter 同义）"),
            (fmt_key("ctrl+c"),                  "停止任务 / 空闲时连按两次退出"),
            (fmt_key("ctrl+n"),                  "新建会话"),
            (fmt_key("ctrl+b"),                  "切换侧栏"),
            (fmt_keys("ctrl+up", "ctrl+down"),   "切换会话"),
            (fmt_key("ctrl+d"),                  "侧栏移除会话"),
            (fmt_key("ctrl+o"),                  "折叠 / 展开已完成的轮次"),
            (fmt_key("ctrl+u"),                  "清空输入框"),
            (fmt_key("ctrl+v"),                  "粘贴（图片优先）"),
            ("↑ / ↓",                            "输入框：浏览发送历史 / 面板内：移动"),
            ("/",                                "唤起命令面板"),
            ("Tab",                              "命令面板可见时补全"),
            ("Esc",                              "取消选择 / 关闭面板 / 关闭帮助"),
            ("Esc Esc",                          "打开回退选择"),
            (fmt_key("ctrl+t"),                  "切换主题"),
            (fmt_key("ctrl+/"),                  "显示 / 隐藏本帮助"),
        ]
        t = Text()
        t.append("快捷键帮助\n\n", style=f"bold {C_GREEN}")
        for k, d in rows:
            t.append(f"  {k:<22}", style=C_FG)
            t.append(f"{d}\n", style=C_MUTED)
        t.append(f"\n按 Esc 或 {fmt_key('ctrl+/')} 关闭", style=C_DIM)
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

    async def _on_paste(self, event: events.Paste) -> None:
        # Windows Terminal yanks window focus when its large-paste-warning dialog
        # pops, and the focus doesn't return to any specific widget after confirm.
        # Without a focused widget Textual routes the Paste event to the App
        # bubble — InputArea never sees it. Forward it back to the input box.
        try:
            inp = self.query_one("#input", InputArea)
        except Exception:
            return
        inp.focus()
        await inp._on_paste(event)
        event.stop(); event.prevent_default()

    def on_click(self, event: events.Click) -> None:
        w = event.widget
        if isinstance(w, FoldHeader):
            msg = w.msg
            idx = w.fold_idx
            if idx in msg._toggled_folds:
                msg._toggled_folds.discard(idx)
            else:
                msg._toggled_folds.add(idx)
            msg._cached_body = None
            msg._cache_key = ()
            self._remount_assistant_message(msg)
            return
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
            sidebar = self.query_one("#sidebar-scroll", VerticalScroll)
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
        # Preserve scroll position across remount. "Near the bottom" snaps to
        # bottom afterwards so streaming output stays visible; mid-scroll keeps
        # the same scroll_y so resize/sidebar-toggle don't yank the user away
        # from what they're reading. 2-line tolerance covers rounding.
        try:
            was_at_bottom = (container.scroll_y + container.size.height
                             >= container.virtual_size.height - 2)
            prev_scroll_y = container.scroll_y
        except Exception:
            was_at_bottom = True
            prev_scroll_y = 0
        container.remove_children()
        for m in self.current.messages:
            m._role_widget = None
            m._body_widget = None
            m._hint_widget = None
            m._segment_widgets = []
            m._segment_sig = ()
            m._spinner_widget = None
        for m in self.current.messages:
            self._mount_message(container, m)
        if was_at_bottom:
            container.scroll_end(animate=False)
        else:
            container.scroll_to(y=prev_scroll_y, animate=False)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "input":
            return
        inp = event.text_area
        # action_stash flips this flag right before `reset()`/text assign
        # so the synchronous Changed event won't trigger the heavy
        # _resize_input + palette-query on the keystroke hot path.  The
        # deferred `_stash_cleanup_*` callbacks (call_after_refresh) own
        # all the layout work for that path.
        if getattr(inp, "_skip_change_next", False):
            inp._skip_change_next = False
            return
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
            return
        # @ file mention: reuse the same palette for path candidates when the
        # cursor sits inside an `@token` (claude-code parity, workspace-rooted).
        try:
            row, col = inp.cursor_location
            line = inp.document.get_line(row)[:col]
        except Exception:
            line = ""
        tok = find_at_token(line)
        if tok is not None:
            self._populate_at_palette(tok[0])
        else:
            self._hide_palette()

    def _populate_at_palette(self, query: str) -> None:
        sess = self.sessions.get(self.current_id)
        unbound = not (sess and sess.workspace_path)   # 未绑 workspace → 根是 temp，显示完整路径
        matches = candidates_for(query, self._at_root(), absolute=unbound)
        palette = self.query_one("#palette", OptionList)
        palette.clear_options()
        if not matches:
            self._hide_palette()
            return
        for path in matches:
            t = Text()
            if unbound:                                 # 未绑：整条完整路径（根不直观）
                t.append(path)
            else:                                       # 绑 workspace：base + 父目录（短）
                # 目录候选末尾带 '/'，先剥掉再拆 base，否则 rsplit 得到空串 → 空白行。
                is_dir = path.endswith("/")
                core = path.rstrip("/")
                parent, name = core.rsplit("/", 1) if "/" in core else ("", core)
                base = name + ("/" if is_dir else "")
                t.append(base, style="bold")
                if parent:
                    t.append(f"  {parent}", style=C_MUTED)
            palette.add_option(Option(t, id=f"at:{path}"))
        self._show_palette()

    def _resize_input(self, inp: TextArea) -> None:
        # wrapped_document.height counts soft-wrapped lines; document.line_count only logical.
        try:
            lines = inp.wrapped_document.height or inp.document.line_count
        except Exception:
            lines = inp.document.line_count
        target = min(max(lines, 1), 3) + 2  # +2 for padding 1 2 top/bottom
        # No-op guard: assigning `styles.height` re-triggers a screen-wide,
        # O(mounted-widgets) relayout in Textual even when the value is
        # unchanged. With 100+ messages on screen each call costs hundreds of
        # ms, which makes typing laggy and makes Ctrl+S/stash feel frozen
        # (this method is called on every keystroke and twice per stash/submit).
        # `_resize_input` is the only writer of the input height, so caching the
        # last value we applied is an authoritative, API-stable way to skip the
        # redundant relayouts. A genuine height change still relayouts once.
        if getattr(inp, "_ga_last_height", None) == target:
            return
        inp._ga_last_height = target
        inp.styles.height = target

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
        # Pick up mykey.py edits without restart: load_llm_sessions() is a
        # cheap mtime check when nothing changed; on change it rebuilds the
        # llm clients in place, migrating history. Done per submit so a user
        # who tweaks mykey then sends a message gets the new config.
        try:
            sess = self.sessions.get(self.current_id)
            if sess is not None and hasattr(sess, "agent"):
                sess.agent.load_llm_sessions()
        except Exception:
            pass
        if text.startswith("!"):
            # Shell-mode magic: run the rest as a host shell command, echo
            # the command + output into scrollback, and append the pair to
            # the agent's LLM history so a follow-up question can reference
            # it (parity with v3 _run_shell).
            self._run_shell(text[1:].strip())
            try:
                self.query_one("#messages", VerticalScroll).scroll_end(animate=False)
            except Exception:
                pass
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
            if cmd == "resume":
                # GA's _handle_slash_cmd expands `/resume` at agent side —
                # forward the literal so the agent recovers context.
                self.submit_user_message(text)
                return
        # @ mentions (completion-only): rewrite @relative → @absolute so the
        # agent's file_read can locate it; scrollback keeps the short form via
        # display_text. No content is read here. (Content-injecting auto-read
        # variant: temp/plan_v2_at_mention/autoread_version.py.)
        if "@" in text:
            abs_text = absolutize_mentions(text, self._at_root())
            if abs_text != text:
                self.submit_user_message(abs_text, images=images, display_text=text)
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
            if cmd_id and cmd_id.startswith("at:"):
                # @ candidate accepted: replace the in-progress @token with the
                # picked path (quoted when it contains spaces), cursor to end.
                inp = self.query_one("#input", InputArea)
                try:
                    row, col = inp.cursor_location
                    line = inp.document.get_line(row)[:col]
                    tok = find_at_token(line)
                    if tok is not None:
                        rep = format_pick(cmd_id[3:])
                        self._suppress_palette_open = True
                        inp.replace(rep, (row, tok[1]), (row, col))
                        inp.move_cursor((row, tok[1] + len(rep)))
                except Exception:
                    pass
                self._hide_palette()
                inp.focus()
                return
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
                # SearchableChoiceList wraps a ChoiceList; expose the inner
                # picker so all the existing keyboard / selected_label code
                # (action_select, page_up/down, etc.) works untouched.
                if isinstance(w, SearchableChoiceList):
                    if isinstance(w.picker, ChoiceList):
                        return w.picker
                    return None
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
        # ask_user-style rollback hook: if the card declared an on_cancel
        # callable (e.g. /scheduler submit-confirm wants Esc to re-show the
        # picker), fire it after the card is gone.
        cb = getattr(msg, "on_cancel", None)
        if cb is not None:
            try: cb()
            except Exception as e:
                self._system(f"on_cancel 异常: {type(e).__name__}: {e}")

    def _finalize_multi_choice(self, msg: ChatMessage, indices: list[int]) -> None:
        """User pressed Enter on a MultiChoiceList.

        - If any picked entry is the free-text sentinel, switch the whole
          message into free-text mode (the user wants to type instead).
        - If `msg.on_select` is set, *the picker owner* consumes the picked
          values directly (used by `/scheduler`'s multi-pick reflect launcher).
          We still collapse the picker into a "Selected: ..." breadcrumb so the
          scrollback shows what happened, but skip the `Submit answers?`
          confirmation card — the caller handles follow-up actions itself.
        - Otherwise (default `ask_user` multi-mode) post a `Ready to submit
          your answers?` confirmation card (Submit / Edit answer) before the
          agent sees it.

        Indices are SelectionList values (set = list index in _mount_message)."""
        picked = [msg.choices[i] for i in indices if 0 <= i < len(msg.choices)]
        if any(v == FREE_TEXT_CHOICE for _, v in picked):
            self._enter_free_text_mode(msg)
            return
        labels = [lbl for lbl, _ in picked]
        values = [val for _, val in picked]
        # Empty selection: for default ask_user multi-mode this means "nothing
        # picked yet" → keep the picker up.  But a picker *owner* (on_select set,
        # e.g. /scheduler) treats an empty set as a deliberate action — namely
        # "stop everything that was preselected" — so we must let it through.
        if not labels and msg.on_select is None:
            return  # nothing selected → keep the picker up
        joined = "; ".join(labels) if labels else "（无 / none）"
        question = msg.content.split("    ")[0].rstrip() if "    " in msg.content else msg.content
        msg.selected_label = f"{question} → {joined}"
        msg.content = msg.selected_label
        container = self.query_one("#messages", VerticalScroll)
        body = Text()
        body.append("✓ ", style=C_GREEN); body.append("Selected: ", style=C_MUTED)
        body.append(joined, style=C_FG)
        new_widget = SelectableStatic(body, classes="msg")
        anchor = msg._hint_widget or msg._body_widget
        if anchor is not None: container.mount(new_widget, after=anchor)
        else: container.mount(new_widget)
        if msg._hint_widget is not None: msg._hint_widget.remove(); msg._hint_widget = None
        if msg._body_widget is not None: msg._body_widget.remove()
        msg._body_widget = new_widget
        # Picker-owner short-circuit: caller wants the raw list of picked
        # values, no confirm card.  Try labels too so callers can pick either.
        if msg.on_select is not None:
            try:
                msg.on_select(values)
            except Exception as e:
                self._system(f"multi_choice on_select 异常: {type(e).__name__}: {e}")
            return
        sess = self.sessions.get(self.current_id)
        if sess is None: return
        confirm = ChatMessage(
            role="system",
            content="Ready to submit your answers?    ←/→ 选择 · Enter 确认 · Esc 取消",
            kind="choice",
            choices=[("Submit answers", joined), ("Edit answer", EDIT_ANSWER_CHOICE)],
            on_select=lambda v, aid=sess.agent_id: self._finalize_free_text(aid, v),
        )
        sess.messages.append(confirm)
        self._refresh_messages()

    def _collapse_choice(self, msg: ChatMessage, idx: int) -> None:
        if not (0 <= idx < len(msg.choices)):
            return
        label, value = msg.choices[idx]
        # Free-text sentinel: collapse the picker into a "type your answer"
        # prompt (keeping the question visible), focus the input, and arm
        # `sess.free_text_pending` so the next submit goes through a
        # `Ready to submit?` confirmation step before reaching the agent.
        if value == FREE_TEXT_CHOICE:
            self._enter_free_text_mode(msg)
            return
        # Edit sentinel: emitted from the submit-confirmation card to mean
        # "go back to typing". Just collapse this card and refocus input —
        # the user's pending answer is already in `sess.free_text_pending`.
        if value == EDIT_ANSWER_CHOICE:
            self._return_to_free_text_edit(msg)
            return
        result_text = None
        if msg.on_select:
            try:
                result_text = msg.on_select(value)
            except Exception as e:
                result_text = f"❌ 失败: {type(e).__name__}: {e}"
        # PR #466 (upstream 8ae3645): if on_select rebuilt the message
        # container (e.g. /rewind picker → _do_rewind → _remount_current_session
        # detaches every widget under #messages), the captured anchors are
        # now stale.  Bail out early so we don't try to mount(after=...)
        # against a detached widget — that'd raise NoWidget and crash.
        anchor_guard = msg._hint_widget or msg._body_widget
        if (anchor_guard is not None
                and hasattr(anchor_guard, 'is_mounted')
                and not anchor_guard.is_mounted):
            return
        display = (result_text or label).strip() or label
        msg.selected_label = display
        msg.content = display
        container = self.query_one("#messages", VerticalScroll)
        was_at_bottom = self._at_bottom(container)
        body = Text()
        body.append("✓ ", style=C_GREEN)
        body.append(display, style=C_FG)
        new_widget = SelectableStatic(body, classes="msg")
        # Prefer hint anchor; fall back to body; finally append at the bottom.
        # `getattr(..., "is_mounted", False)` guards against a hint that was
        # already removed by a concurrent re-render path (Textual raises
        # NoWidget when mounting after a detached widget).
        anchor = msg._hint_widget if getattr(msg._hint_widget, "is_mounted", False) else None
        if anchor is None and getattr(msg._body_widget, "is_mounted", False):
            anchor = msg._body_widget
        try:
            if anchor is not None:
                container.mount(new_widget, after=anchor)
            else:
                container.mount(new_widget)
        except Exception:
            # Last-resort: append at the end so the user still sees the choice
            # they made. The selectable widget itself is correct; only its
            # placement degrades.
            container.mount(new_widget)
        if msg._hint_widget is not None:
            msg._hint_widget.remove()
            msg._hint_widget = None
        if msg._body_widget is not None:
            msg._body_widget.remove()
        msg._body_widget = new_widget
        if was_at_bottom:
            container.scroll_end(animate=False)
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
        closed = self.sessions.pop(self.current_id)
        _rmdir_if_empty(getattr(closed.agent, 'task_dir', None))
        self.current_id = next(iter(self.sessions))
        self._refresh_all()

    def _cmd_rename(self, args, raw):
        if not args:
            self._system("Usage: /rename <name>"); return
        name = " ".join(args).strip()
        if not name:
            self._system("Usage: /rename <name>"); return
        if name.lower() == (self.current.name or "").lower():
            self._system(f"⚠️ 已经叫 {name!r}"); return
        for sid, s in self.sessions.items():
            if sid != self.current_id and s.name.lower() == name.lower():
                self._system(f"❌ 名称已被会话 #{sid} 占用，请换一个"); return
        # Registry collision: another log already owns this name on disk.
        # `agent.log_path` is the microsecond-stamped file the agent actually
        # writes to (see agentmain.GenericAgent.__init__); exclude its basename
        # so renaming yourself isn't reported as a collision.
        log_path = getattr(self.current.agent, "log_path", "") or ""
        own_key = os.path.basename(log_path)
        try:
            import session_names
            if session_names.has_name(name, exclude_basename=own_key):
                self._system(f"❌ 名称已被另一会话注册，请换一个"); return
        except Exception:
            session_names = None
        self.current.name = name
        if log_path and session_names is not None:
            try:
                session_names.set_name(log_path, name)
            except Exception as e:
                self._system(f"⚠️ 名称未持久化: {type(e).__name__}: {e}")
        self._refresh_topbar(); self._refresh_sidebar()
        self._system(f"✅ 已重命名为 {name!r}")

    def _cmd_branch(self, args, raw):
        import copy
        old = self.current
        name = " ".join(args).strip() or f"{old.name}-branch"
        new = self.add_session(name)
        try:
            new.agent.llmclient.backend.history = copy.deepcopy(old.agent.llmclient.backend.history)
        except Exception as e:
            self._system(f"Branch warning: {e}"); return
        if old.workspace_name:
            self._bind_workspace(new, {
                "name": old.workspace_name,
                "target": old.workspace_path,
                "link": old.workspace_link,
            })
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
            nm._segment_widgets = []
            nm._segment_sig = ()
            nm._toggled_folds = set()
            nm._spinner_widget = None
            new.messages.append(nm)
        new.task_seq = old.task_seq
        n = len(new.agent.llmclient.backend.history)
        self._system(f"Branched #{old.agent_id} → #{new.agent_id} ({n} msgs).")

    def _cmd_rewind(self, args, raw):
        sess = self.current
        if sess.status == "running":
            self._system("Cannot rewind while running. /stop first."); return
        turns = self._rewindable_turns()
        if not turns:
            self._system("No rewindable turns."); return
        if args:
            try: n = int(args[0])
            except ValueError: self._system("Usage: /rewind <n>"); return
            if n < 1 or n > len(turns):
                self._system(f"Invalid: 1-{len(turns)}"); return
            self._system(self._do_rewind(n))
            return
        LIMIT = 20
        recent = list(reversed(turns))[:LIMIT]
        choices = []
        for offset, (_, prev) in enumerate(recent, 1):
            preview = (prev or "（空）").replace("\n", " ").strip()[:60]
            choices.append((f"回退 {offset} 轮 · {preview}", offset))
        head = "选择回退到的轮次 (↑/↓ 移动，→/Enter 确认，Esc 取消)"
        if len(turns) > LIMIT:
            head += f"  [仅显示最近 {LIMIT}/{len(turns)}]"
        msg = ChatMessage(
            role="system", content=head, kind="choice", choices=choices,
            on_select=lambda v: self._do_rewind(v),
        )
        sess.messages.append(msg)
        self._refresh_messages()

    def _rewindable_turns(self) -> list[tuple[int, str]]:
        history = self.current.agent.llmclient.backend.history
        turns: list[tuple[int, str]] = []
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
        return turns

    def _do_rewind(self, n: int) -> str:
        sess = self.current
        turns = self._rewindable_turns()
        if not (1 <= n <= len(turns)):
            return f"❌ 回退失败：n 应在 1-{len(turns)}"
        history = sess.agent.llmclient.backend.history
        cut = turns[-n][0]
        prefill = _extract_user_text(history[cut]) if cut < len(history) else ""
        removed = len(history) - cut
        history[:] = history[:cut]
        real_user = [i for i, msg in enumerate(sess.messages) if msg.role == "user"]
        if n <= len(real_user):
            sess.messages = sess.messages[:real_user[-n]]
        try: sess.agent.history.append(f"[USER]: /rewind {n}")
        except Exception: pass
        self._remount_current_session()
        self._refresh_topbar()
        self._refresh_sidebar()
        if prefill:
            try:
                inp = self.query_one("#input", InputArea)
                inp.text = prefill
                inp.move_cursor((inp.document.line_count - 1, len(prefill.split("\n")[-1])))
                inp.focus()
                self._resize_input(inp)
            except Exception: pass
        return f"已回退 {n} 轮（移除 {removed} 条历史）"

    def _cmd_clear(self, args, raw):
        self.current.messages.clear()
        self._remount_current_session()
        self._refresh_topbar()
        self._refresh_sidebar()
        self._system("已清空显示（LLM 历史保留）")

    def _cmd_stop(self, args, raw):
        sess = self.current
        # Locate the last user message AND whether the agent already produced a
        # reply for that turn. Walking reversed, any non-empty assistant message
        # seen *before* we reach the user message means this turn was consumed
        # (the LLM emitted output → it's in history; a resend would duplicate).
        # System "[queued #n]" steers are skipped (neither role). The current
        # task's assistant placeholder starts empty, so an interrupt before any
        # stream leaves `consumed` False.
        last_user_text = None
        consumed = False
        for m in reversed(sess.messages):
            if m.role == "assistant" and (m.content or "").strip():
                consumed = True
            elif m.role == "user":
                last_user_text = m.content
                break
        try:
            sess.agent.abort()
            if sess.status == "running":
                sess.status = "stopping"
            self._mark_stopping(sess)
            self._system(f"Stop sent to #{sess.agent_id}.")
        except Exception as e:
            self._system(f"Stop failed: {e}")
        # Refill the input box with the interrupted user text so edit-and-
        # resend is one keystroke away — but only for an *unconsumed* turn
        # (aborted before the LLM replied). Once the agent has answered, the
        # turn lives in history and a resend would duplicate it, so leave the
        # box alone. Also only when the box is empty (don't clobber a
        # half-typed follow-up).
        if last_user_text and not consumed:
            try:
                inp = self.query_one("#input", InputArea)
                if not inp.text:
                    inp.text = last_user_text
                    inp.move_cursor((inp.document.line_count - 1,
                                     len(last_user_text.split("\n")[-1])))
                    inp.focus()
                    self._resize_input(inp)
            except Exception:
                pass
        self._refresh_all()

    def _cmd_reload_keys(self, args, raw):
        # Force rebuild of every session's llmclients from a fresh mykey.py.
        # reload_mykeys() uses a module-level mtime cache, so the first agent
        # to call it consumes the "changed" signal and subsequent agents see
        # changed=False (and skip rebuild). Invalidate the cache before each
        # agent so every session picks up the new config.
        try:
            import llmcore
        except Exception as e:
            self._system(f"❌ 无法 import llmcore: {e}"); return
        n_ok = n_fail = 0
        for sess in self.sessions.values():
            agent = getattr(sess, "agent", None)
            if agent is None:
                continue
            try:
                llmcore._mykey_mtime = None
                agent.load_llm_sessions()
                n_ok += 1
            except Exception:
                n_fail += 1
        msg = f"🔑 已重载 mykey.py（{n_ok} 个会话）" + (f"，{n_fail} 个失败" if n_fail else "")
        self._system(msg)

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

    # ---------------- /model: 渠道内 model 切换（逻辑在 model_cmd.py） ----------------
    def _cmd_model(self, args, raw):
        import model_cmd
        agent = self.current.agent
        if args:  # /model <name> 直设, 不拉列表
            self._system(model_cmd.set_model(agent, " ".join(args)))
            return
        self._open_model_picker()

    def _open_model_picker(self) -> None:
        """立即挂一个空的 searchable picker(输入框先可用, 下方 hint 行显示加载中),
        后台拉取完成后 _fill_model_picker 就地填充。mixin 不再选渠道, 直接作用于
        当前子渠道 (model_cmd sub=None 即当前)。"""
        import model_cmd
        agent = self.current.agent
        cur = model_cmd.current_model(agent, None)
        msg = ChatMessage(
            role="system",
            content=f"选择模型 (当前: {cur} · 输入过滤或自定义名称 · ↑/↓ 移动，Enter 确认，Esc 取消)",
            kind="choice", choices=[],
            on_select=lambda v: model_cmd.set_model(self.current.agent, v),
        )
        msg.searchable = True
        msg.free_input = True
        msg.search_placeholder = "输入关键字过滤；无匹配时 Enter 设置自定义模型名"
        msg.all_choices = []
        msg.empty_hint = "⏳ 正在拉取模型列表… (或直接输入完整模型名 Enter 直设)"
        self.current.messages.append(msg)
        self._refresh_messages()

        def worker():
            try:
                models = model_cmd.fetch_models(agent, None)
                err = None if models else "渠道未返回模型列表"
            except Exception as e:
                models, err = [], f"{type(e).__name__}: {e}"
            self.call_from_thread(self._fill_model_picker, msg, models, err, cur)

        threading.Thread(target=worker, daemon=True, name="ga-tui-model").start()

    # ---------------- /effort: reasoning effort 切换（逻辑在 model_cmd.py） ----------------
    def _cmd_effort(self, args, raw):
        import model_cmd
        if args:  # /effort <level> 直设
            self._system(model_cmd.set_effort(self.current.agent, " ".join(args)))
            return
        agent = self.current.agent
        cur = model_cmd.current_effort(agent)
        protocols = model_cmd._protocols(agent)
        # (显示名, value, 备注, 是否当前选中)。有备注的行名字补齐到等宽，
        # 备注对齐成一列；无备注的行直接用显示名，不留尾随空格。
        rows = [("默认", "off", "", not cur)]
        for lv in model_cmd.EFFORT_LEVELS:
            rows.append((lv, lv, model_cmd.effort_note(lv, protocols), cur == lv))
        w = max(len(d) for d, _, _, _ in rows)
        choices = [(("✓ " if tick else "  ")
                    + (disp.ljust(w) + f"    {note}" if note else disp), val)
                   for disp, val, note, tick in rows]
        msg = ChatMessage(
            role="system",
            content=(f"选择 reasoning effort (当前: {cur or '未设置'} · "
                     "↑/↓ 移动，Enter 确认，Esc 取消)"),
            kind="choice", choices=choices,
            on_select=lambda v: model_cmd.set_effort(self.current.agent, v),
        )
        self.current.messages.append(msg)
        self._refresh_messages()

    def _fill_model_picker(self, msg, models, err, cur) -> None:
        """拉取完成: 就地重建 picker 区, 保留 Input 焦点与已输入的过滤词。"""
        w = msg._body_widget
        if (msg.selected_label is not None or w is None
                or not getattr(w, "is_mounted", False)):
            return  # 用户已 Esc/已选, 静默丢弃
        if err:
            msg.empty_hint = f"❌ 拉取失败: {err} · 直接输入完整模型名 Enter 设置"
        else:
            msg.all_choices = [(("✓ " if m == cur else "  ") + m, m) for m in models]
            msg.empty_hint = "(无匹配 · Enter 设置自定义模型名)"
            msg.content = (f"选择模型 ({len(models)} 个 · 当前: {cur} · "
                           "输入过滤或自定义名称 · ↑/↓ 移动，Enter 确认，Esc 取消)")
            try:
                msg._hint_widget.update(Text(msg.content, style=C_MUTED))
            except Exception:
                pass
        w._apply_filter(msg.search_query or "")

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

    def _cmd_review(self, args, raw):
        """`/review` via TUI's streaming path; the TUI intercepts slash commands
        before `review_cmd.install`'s patch, so we render the prompt via
        `review_cmd.handle` and submit it as a normal task with `/review ...`
        kept as the visible user message."""
        body = (raw or "").strip()
        if body == "/review":
            body = ""
        elif body.startswith("/review ") or body.startswith("/review\t"):
            body = body[len("/review"):].strip()
        else:
            body = " ".join(args).strip()
        sess = self.current
        if body in ("help", "?", "-h", "--help"):
            try:
                dq = queue.Queue()
                rendered = review_handle(sess.agent, body, dq)
                try:
                    item = dq.get_nowait()
                    self._system(str(item.get("done") or ""))
                except queue.Empty:
                    if rendered:
                        self._system(rendered)
            except Exception as e:
                self._system(f"❌ /review help 失败: {type(e).__name__}: {e}")
            return
        if sess.status == "running":
            self._system(f"#{sess.agent_id} 正在跑，/stop 后再发。")
            return
        try:
            prompt = review_handle(sess.agent, body, queue.Queue())
        except Exception as e:
            self._system(f"❌ /review 初始化失败: {type(e).__name__}: {e}")
            return
        if not prompt:
            self._system("❌ /review 未生成审查提示。")
            return
        display_text = raw.strip() if (raw or "").strip() else "/review"
        self.submit_user_message(prompt, display_text=display_text)

    def _cmd_continue(self, args, raw):
        sess = self.current
        m = re.match(r"/continue\s+(\S.*?)\s*$", (raw or "").strip())
        if m:
            token = m.group(1)
            if token.isdigit():
                sessions = continue_list(exclude_pid=os.getpid())
                idx = int(token) - 1
                if not (0 <= idx < len(sessions)):
                    self._system(f"❌ 索引越界（有效范围 1-{len(sessions)}）"); return
                self._do_continue_restore(sessions[idx][0])
                return
            log_path = getattr(sess.agent, "log_path", "") or ""
            own_key = os.path.basename(log_path)
            try:
                import session_names
                path = session_names.path_for(token, exclude_basename=own_key)
                if path is None and session_names.name_for(log_path).lower() == token.strip().lower():
                    self._system(f"✅ 当前已在 {token!r} 会话中"); return
            except Exception:
                path = None
            if not path:
                self._system(f"❌ 找不到名为 {token!r} 的会话"); return
            self._do_continue_restore(path)
            return
        sessions = continue_list(exclude_pid=os.getpid())
        if not sessions:
            self._system("❌ 没有可恢复的历史会话"); return
        choices = []
        try:
            import session_names as _sn
        except Exception:
            _sn = None
        for path, mtime, first, n in sessions:
            preview = (first or "（无法预览）").replace("\n", " ").strip()[:50]
            nm = _sn.name_for(path) if _sn else ""
            tag = f"{nm} · " if nm else ""
            choices.append((f"{_short_age(mtime)} · {tag}{n}轮 · {preview}", path))
        head = f"选择要恢复的会话 ({len(sessions)} 条 · 输入关键字过滤 · ↑/↓ 移动，→/Enter 确认，Esc 取消)"
        msg = ChatMessage(
            role="system", content=head, kind="choice", choices=choices,
            on_select=lambda v: self._do_continue_restore(v),
        )
        # `/continue` is the only place that opts into the searchable picker
        # (per task B 2026-05-27). `all_choices` is the unfiltered baseline so
        # clearing the query restores the full list; `searchable=True` flips
        # the `_mount_message` branch to wrap the picker with an Input filter.
        msg.searchable = True
        msg.all_choices = list(choices)
        # Threshold chosen empirically (user-preferred 2026-05-27): mounting 50
        # rows fits typical viewport with no perceptible cost, so the eager
        # path stays for ≤50 entries; larger lists stream via LazyChoiceList
        # with the same 50-row first batch.
        if len(choices) > 50:
            msg.lazy_choice_items = [label for label, _ in choices]
            msg.lazy_choice_batch = 50
        sess.messages.append(msg)
        self._refresh_messages()

    def _do_continue_restore(self, path: str) -> str:
        sess = self.current
        from continue_cmd import reset_conversation, restore
        try:
            reset_conversation(sess.agent, message=None)
            result, ok = restore(sess.agent, path)
        except Exception as e:
            msg = f"❌ 恢复失败: {e}"
            self._system(msg); return msg
        if not ok:
            self._system(result); return result
        # Mirror the source transcript into this agent's own log file so a
        # future /continue resolves the merged history under the migrated name.
        current_log = getattr(sess.agent, "log_path", "") or ""
        if current_log and path != current_log:
            try:
                import shutil
                shutil.copyfile(path, current_log)
            except Exception:
                pass
        def _finish():
            sess.messages.clear()
            # Plan state belongs to the *previous* conversation. Clearing it
            # along with messages stops the planbar from leaking stale items
            # (`Plan (3/7)` from #4 qxs) into the freshly-restored session.
            sess.plan_items = []
            sess.plan_complete_since = None
            sess.plan_lost_since = None
            sess.restored_plan_path = ""
            self._plan_mtime.pop(sess.agent_id, None)
            # Live mode fills _WRITE_CAP from the tool_before hook; on restore that
            # is gone, so seed it from the log's structured tool_use inputs (keyed
            # the same way) — otherwise restored file_write/file_patch fall back to
            # the raw verbose args block instead of a diff.
            try:
                from continue_cmd import iter_write_captures
                from agent_loop import get_pretty_json
                for cap in iter_write_captures(path):
                    _WRITE_CAP[hash(get_pretty_json(cap["args"]))] = cap
            except Exception:
                pass
            for h in continue_extract(path):
                sess.messages.append(ChatMessage(role=h["role"], content=h["content"]))
            # Plan-card restore is keyed off the transcript's structured
            # `enter_plan_mode` tool_use (find_plan_entry), NOT off plan.md
            # paths mentioned in chat text — a typed filename can't fake it.
            # Restore iff the entered plan still exists, parses to ≥1 task,
            # and isn't all-done (an abandoned finished/headless plan stays
            # buried). baseline stays 0: it only scopes current_step's 📌 scan.
            sess.plan_scan_baseline = 0
            import plan_state
            from continue_cmd import find_plan_entry
            pp = find_plan_entry(path)
            rp = plan_state._resolve_stashed(pp) if pp else None
            if rp:
                try:
                    with open(rp, encoding="utf-8", errors="replace") as f:
                        items = plan_state.extract(f.read())
                except OSError:
                    items = []
                if items and not plan_state.is_complete(items):
                    sess.restored_plan_path = rp
                    sess.plan_items = items
            try:
                import session_names
                nm = session_names.name_for(path)
                if nm:
                    sess.name = nm
                    if current_log:
                        session_names.migrate(path, current_log)
            except Exception:
                pass
            # Auto-restore workspace: if the continued session worked in a
            # registered workspace, bind it to this session (recreating the
            # junction if needed) without touching the legacy process anchor.
            self._bind_workspace(self.current, None)
            try:
                rec = workspace_cmd.session_ws_get(path)   # 路径 / "" (off) / None(无记录)
                if rec is not None:
                    ws_path = rec or None                  # "" → 该会话已 off，明确不恢复
                else:
                    info = workspace_cmd.workspace_from_log(path)   # 老会话：回退扫日志
                    ws_path = info["path"] if info else None
                if ws_path:
                    r = workspace_cmd.prepare(ws_path)
                    if r.get("ok"):
                        self._bind_workspace(self.current, r)
                        self._system(f"⌂ 已恢复工作目录: {r['target']}")
                    else:
                        self._system(f"⚠ workspace 恢复失败: {r.get('error')}")
            except Exception:
                pass
            self._remount_current_session()
            self._refresh_all()
        self.call_after_refresh(_finish)
        return result.splitlines()[0] if result else "✅ 已恢复"

    def _cmd_workspace(self, args, raw):
        # /workspace <abs path> | /workspace off | /workspace (picker).
        # Path may contain spaces (Windows) → capture the whole tail.
        m = re.match(r"/workspace\s+(\S.*?)\s*$", (raw or "").strip())
        if m:
            token = m.group(1)
            if token.lower() == "off":
                sess = self.current
                if sess.workspace_name:
                    self._bind_workspace(sess, None)
                    self._system("已退出 workspace（项目模式关闭;junction 与文件保留）")
                else:
                    self._system("当前未处于 workspace 模式")
                self._refresh_topbar()
                return
            # 直接路径无 picker 面包屑，自己显示一条。
            self._system(self._do_workspace_activate(token))
            return
        # No arg → searchable picker: free-text input (type an abs path to
        # create/enter) over a candidate list of registered workspaces.
        sess = self.current
        choices = []
        for it in workspace_cmd.registry_list():
            age = _short_age(it["last_used"]) if it["last_used"] else "—"
            mem = f"{it['mem_lines']}行记忆" if it["mem_lines"] else "空"
            flag = " ⚠失效" if it["dangling"] else ""
            # 显示名取真实目录 basename（天然不含 junction 的 -hash8 后缀）；
            # dangling 无 path 时退回剥掉 name 尾部 hash。名称省略末尾、路径
            # 省略中间，整行经 ChoiceList 单行渲染不会折行。
            disp = os.path.basename((it["path"] or "").rstrip("/\\")) \
                or re.sub(r"-[0-9a-f]{8}$", "", it["name"])
            label = f"{_cell_head(disp, 22)} · {_cell_mid(it['path'], 46)} · {age} · {mem}{flag}"
            choices.append((label, it["path"]))
        head = ("指定工作目录（输入绝对路径回车新建/进入，或从下方选择已有 · "
                "↑/↓ 移动，→/Enter 确认，Esc 取消）")
        msg = ChatMessage(
            role="system", content=head, kind="choice", choices=choices,
            on_select=lambda v: self._do_workspace_activate(v),
        )
        msg.searchable = True
        msg.free_input = True          # Enter on a typed abs path commits it as a new workspace
        msg.all_choices = list(choices)
        sess.messages.append(msg)
        self._refresh_messages()

    def _do_workspace_activate(self, path: str) -> str:
        # 唯一展示文本 = 返回值：picker 路径由 _collapse_choice 渲染成 `✓ …`
        # 面包屑；直接 `/workspace <path>` 路径由 _cmd_workspace 用 _system 显示。
        # 两条路径各出一条，故此处不再自行 _system（否则与面包屑重复）。
        r = workspace_cmd.prepare(path)
        if not r.get("ok"):
            return f"❌ workspace 设定失败: {r.get('error')}"
        self._bind_workspace(self.current, r)
        self._refresh_topbar()
        # 显示名去 hash（与 picker 一致）：真实目录 basename，退回剥 name 尾 hash。
        disp = os.path.basename((r.get("target") or "").rstrip("/\\")) \
            or re.sub(r"-[0-9a-f]{8}$", "", r.get("name") or "")
        out = f"✅ 已进入 workspace「{disp}」"
        if r.get("warning"):
            out += f"  ⚠ {r['warning']}"
        return out

    def _cmd_cost(self, args, raw):
        try:
            import cost_tracker
        except Exception as e:
            self._system(f"❌ cost_tracker 不可用: {e}"); return
        show_all = bool(args) and args[0].lower() == "all"

        def _k(n: int) -> str:
            # Human-readable number: 12.3K / 1.45M / 167 — keeps the column
            # narrow so the layout doesn't shift between idle and 200K-deep sessions.
            n = int(n)
            if n < 1000: return f"{n}"
            if n < 1_000_000:
                v = n / 1000.0
                return f"{v:.1f}K" if v < 100 else f"{int(v)}K"
            v = n / 1_000_000.0
            return f"{v:.2f}M" if v < 100 else f"{int(v)}M"

        def _elapsed(secs: float) -> str:
            s = int(secs)
            if s < 60: return f"{s}s"
            if s < 3600: return f"{s // 60}m {s % 60:02d}s"
            h, rem = divmod(s, 3600); m, sec = divmod(rem, 60)
            return f"{h}h {m:02d}m {sec:02d}s"

        def _section(sid: int, sess, t) -> list[str]:
            try: model = sess.agent.get_llm_name(model=True) or "?"
            except Exception: model = "?"
            total = t.total_tokens()
            inp_side = t.total_input_side()
            ls = []
            ls.append(f"#{sid} {sess.name}  ·  model: {model}  ·  elapsed: {_elapsed(t.elapsed_seconds())}")
            ls.append(
                f"  Token usage:     {_k(total):>7} total  "
                f"({_k(inp_side)} input + {_k(t.output)} output)"
            )
            if t.cache_read or t.cache_create:
                ls.append(
                    f"  Cache:           {_k(t.cache_read):>7} read  ·  "
                    f"{_k(t.cache_create)} created  ·  "
                    f"{t.cache_hit_rate():.1f}% hit"
                )
            try: backend = sess.agent.llmclient.backend
            except Exception: backend = None
            cap = cost_tracker.context_window_chars(backend) if backend else 0
            used = cost_tracker.current_input_chars(backend) if backend else 0
            if cap > 0:
                pct_left = max(0.0, (cap - used) / cap * 100.0)
                ls.append(
                    f"  Context window:  {pct_left:>5.0f}% left  "
                    f"({_k(used)} chars used / {_k(cap)} cap)"
                )
            ls.append(f"  Requests:        {t.requests:>7}")
            return ls

        # Scope subagent logs to this TUI run so prior-session logs don't bleed in.
        try: sub = cost_tracker.scan_subagent_logs(since=getattr(self, "_started_at", 0.0))
        except Exception: sub = None

        def _sub_section() -> list[str]:
            if not sub or sub.total_tokens() == 0: return []
            ls = ["", f"subagents (扫描 temp/*/stdout.log)"]
            ls.append(
                f"  Token usage:     {_k(sub.total_tokens()):>7} total  "
                f"({_k(sub.total_input_side())} input + {_k(sub.output)} output)"
            )
            if sub.cache_read or sub.cache_create:
                ls.append(
                    f"  Cache:           {_k(sub.cache_read):>7} read  ·  "
                    f"{_k(sub.cache_create)} created  ·  "
                    f"{sub.cache_hit_rate():.1f}% hit"
                )
            ls.append(f"  Requests:        {sub.requests:>7}")
            return ls

        lines: list[str] = []
        if show_all:
            trackers = cost_tracker.all_trackers()
            if not trackers and not (sub and sub.total_tokens()):
                lines = ["✦ Token usage", "  (尚无任何 LLM 调用记录)"]
            else:
                # Resolve each thread back to a session if we still know it; otherwise
                # surface the bare thread name (the session may have been Ctrl+D'd).
                by_name = {(s.thread.name if s.thread else f"ga-tui-agent-{sid}"): (sid, s)
                           for sid, s in self.sessions.items()}
                lines.append("✦ Token usage (all sessions)")
                first = True
                for tname in sorted(trackers):
                    if not first: lines.append("")
                    first = False
                    if tname in by_name:
                        sid, s = by_name[tname]
                        lines += _section(sid, s, trackers[tname])
                    else:
                        t = trackers[tname]
                        lines.append(f"[{tname}]  ·  elapsed: {_elapsed(t.elapsed_seconds())}")
                        total = t.total_tokens()
                        lines.append(
                            f"  Token usage:     {_k(total):>7} total  "
                            f"({_k(t.total_input_side())} input + {_k(t.output)} output)"
                        )
                        lines.append(f"  Requests:        {t.requests:>7}")
                lines += _sub_section()
        else:
            sess = self.current
            tname = sess.thread.name if sess.thread else f"ga-tui-agent-{sess.agent_id}"
            t = cost_tracker.get(tname)
            lines.append("✦ Token usage")
            lines += _section(sess.agent_id, sess, t)
            lines += _sub_section()
        self._system("\n".join(lines))

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
                payload = wrap_for_clipboard(text)
                if _copy_to_clipboard(payload):
                    return "✅ 已复制最后一轮回复到剪贴板"
                return f"⚠️ 自动复制失败，请手动复制:\n\n{payload}"
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
        self._reset_terminal_title()
        self.exit()

    # ---------------- slash_cmds bundle ----------------
    def _cmd_slash_inject(self, args, raw):
        """`/update /autorun /morphling /goal /hive /conductor` → prompt
        injection.  We strip the leading slash command from `raw`, hand the
        tail to `slash_cmds.prompt_for`, and re-enter `submit_user_message`
        so the agent sees it as a normal user turn (display bubble still
        shows the original `/cmd ...` for clarity).
        """
        from frontends import slash_cmds
        text = (raw or "").strip()
        # Pull just the leading token to look up the prompt builder.
        head = text.split(None, 1)[0] if text else ""
        if not head.startswith("/"):
            self._system("❌ /slash 命令解析失败"); return
        tail = text[len(head):].strip()
        prompt = slash_cmds.prompt_for(head, tail)
        if prompt is None:
            self._system(f"❌ 未知命令 {head}"); return
        sess = self.current
        if sess.status == "running":
            self._system(f"#{sess.agent_id} 正在跑，/stop 后再发。")
            return
        # Keep the user's original `/cmd ...` as the visible bubble so the
        # transcript stays self-explanatory; the agent sees the long prompt.
        self.submit_user_message(prompt, display_text=text or head)

    def _cmd_scheduler(self, args, raw):
        """`/scheduler` lists reflect/*.py + sche_tasks/*.json and starts the
        chosen reflect task(s).  Usage:
          /scheduler                — interactive multi-select picker
                                      (Space toggles, Enter launches every
                                      checked task in one batch)
          /scheduler start <name>   — start one reflect task by stem (CLI)
          /scheduler start a,b,c    — start several at once (CSV, CLI)
        Cron-style sche_tasks/*.json are read-only here; the launch.pyw
        scheduler daemon already owns them.
        """
        from frontends import slash_cmds
        body = " ".join(args).strip()
        parts = body.split(None, 1)
        head = parts[0].lower() if parts else ""
        if head in ("start", "run"):
            names = (parts[1] if len(parts) > 1 else "").replace(",", " ").split()
            if not names:
                self._system("Usage: /scheduler start <reflect_name>[,<name2>...]"); return
            self._launch_service_batch(names)
            return
        # Default: surface a MultiChoiceList picker for reflect/*.py so the
        # user can tick several tasks at once (Space toggle, Enter submit).
        # sche_tasks/*.json are read-only — shown below as a system advisory
        # so the user still has visibility, but they can't be launched here.
        services = slash_cmds.list_launchable_services()
        if not services:
            self._system("📋 没有可启动的服务（reflect/*.py 与 frontends/*app*.py 均为空）"); return
        # bug#4: query what's actually alive *now* (psutil cmdline scan) so the
        # picker can (a) pre-tick running services and (b) tag them visibly.
        # Unticking a pre-ticked row therefore reads as "stop this service".
        try:
            running = slash_cmds.running_services()  # {name: pid}
        except Exception:
            running = {}
        # Mirror hub.pyw: reflect tasks + frontend apps, grouped by kind so the
        # picker reads like the GUI launcher.  Picker value = hub-style path.
        choices = []
        preselected = []   # indices into `choices` that are running right now
        for kind in ("reflect", "frontend"):
            for s in (svc for svc in services if svc["kind"] == kind):
                doc = f"  — {s['doc']}" if s["doc"] else ""
                is_running = s["name"] in running
                tag = "  · running" if is_running else ""
                if is_running:
                    preselected.append(len(choices))
                label = f"{s['name']}{doc}{tag}"
                # Functional green for already-running rows so they're
                # distinguishable even when the [x] tick is small or the
                # row scrolls off the visible window.
                if is_running:
                    from rich.text import Text as _T
                    rich_label = _T(label, style="green")
                    choices.append((rich_label, s["name"]))
                else:
                    choices.append((label, s["name"]))
        sess = self.current
        hint = ("选择要启动的服务（与 hub.pyw 一致：reflect 任务 + frontend 应用）"
                "    Space 勾选 · Enter 提交 · Esc 取消 — 提交后还需二次确认")
        if running:
            hint += f"\n   绿色 = 正在运行（已勾选）；取消勾选即停止该服务（共 {len(running)} 个在运行）"
        try:
            cron_n = len(slash_cmds.list_scheduler_tasks())
        except Exception:
            cron_n = 0
        if cron_n:
            sch_running = 'reflect/scheduler.py' in running
            cron_state = "已激活" if sch_running else "未激活（启动 reflect/scheduler.py 来调度）"
            hint += f"\n   cron：sche_tasks/*.json 共 {cron_n} 个任务 · {cron_state}"
        msg = ChatMessage(
            role="system",
            content=hint,
            kind="multi_choice",
            choices=choices,
            preselected_indices=preselected,
            on_select=lambda names, base=dict(running): self._scheduler_confirm(names, base),
        )
        sess.messages.append(msg)
        self._refresh_messages()

    def _scheduler_diff(self, selected: list[str], running: dict) -> tuple[list[str], list[str]]:
        """Translate the picker's *final tick state* into actions relative to
        the running baseline (bug#4):
          starts = ticked but not currently running
          stops  = currently running but unticked
        Order is preserved from `selected`/`running` for stable summaries."""
        sel = list(dict.fromkeys(selected))  # dedupe, keep order
        run_names = list(running.keys())
        starts = [n for n in sel if n not in running]
        stops = [n for n in run_names if n not in sel]
        return starts, stops

    def _scheduler_confirm(self, names: list[str], running: dict | None = None) -> None:
        """Picker submitted → ask one more ask_user-style submit-confirm card
        before actually launching/stopping anything (user-requested safety).

        UX mirrors `ask_user`'s `Ready to submit your answer?` confirmation:
          - No ✅ glyph on the choice labels (style consistency).
          - ←/→ Enter Esc hint in the title.
          - Esc / "Edit selection" → re-open the picker (rollback to previous
            screen) just like Esc rolls back free-text typing to the picker.
        bug#4: the card now spells out the *diff* (start X / stop Y) so the
        consequence of unticking a running service is explicit before commit.
        """
        running = running or {}
        starts, stops = self._scheduler_diff(names, running)
        if not starts and not stops:
            self._system("（选择无变化 — 没有要启动或停止的服务）"); return
        sess = self.current
        if sess is None: return
        lines = []
        if starts:
            lines.append(f"▶ 启动 {len(starts)} 个: " + "、".join(starts))
        if stops:
            lines.append(f"■ 停止 {len(stops)} 个: " + "、".join(stops))
        detail = "\n".join("   " + ln for ln in lines)
        confirm = ChatMessage(
            role="system",
            content=(f"Ready to submit your selection?\n{detail}"
                     "\n    ←/→ 选择 · Enter 确认 · Esc 回退"),
            kind="choice",
            choices=[("Submit", "__SCHED_GO__"), ("Edit selection", "__SCHED_EDIT__")],
            on_select=lambda v, st=list(starts), sp=list(stops): self._scheduler_commit(v, st, sp),
            # Esc on the confirm card → roll back to the picker (ask_user style).
            on_cancel=lambda: self._cmd_scheduler([], ""),
        )
        sess.messages.append(confirm)
        self._refresh_messages()

    def _scheduler_commit(self, value: str, starts: list[str], stops: list[str]) -> str:
        """on_select for the submit-confirm card; returns the breadcrumb text
        shown after the card collapses (see _collapse_choice).

        - Submit (__SCHED_GO__) → apply the start/stop diff.
        - Edit selection (__SCHED_EDIT__) → re-open the picker (rollback).
        """
        if value == "__SCHED_EDIT__":
            # Re-show the picker on the next tick so the breadcrumb settles
            # first; using call_after_refresh keeps message order stable.
            try:
                self.call_after_refresh(self._cmd_scheduler, [], "")
            except Exception:
                self._cmd_scheduler([], "")
            return "已回到选择界面"
        if value != "__SCHED_GO__":
            return "已取消，未改动任何服务"
        self._apply_scheduler_diff(starts, stops)
        bits = []
        if starts: bits.append(f"启动 {len(starts)}")
        if stops: bits.append(f"停止 {len(stops)}")
        return "已确认 — " + "、".join(bits) if bits else "已确认（无改动）"

    def _apply_scheduler_diff(self, starts: list[str], stops: list[str]) -> None:
        """Run the start/stop actions and print one ✅/❌ summary block.
        Stops run first so a restart (stop+start of the same name) can't race
        the cmdline scan — though the diff never produces such a pair."""
        from frontends import slash_cmds
        lines = []
        for name in stops:
            ok, detail = slash_cmds.stop_service(name)
            lines.append(("■ " if ok else "❌ ") + detail)
        for name in starts:
            ok, detail = slash_cmds.start_service(name)
            lines.append(("▶ " if ok else "❌ ") + detail)
        if not lines:
            lines = ["（无改动）"]
        self._system("调度变更结果:\n" + "\n".join(lines))

    def _launch_service_batch(self, names: list[str]) -> None:
        """Shared by `/scheduler start ...` (CLI) and the confirmed picker.
        Launches every requested service via slash_cmds.start_service and
        prints a single ✅/❌ summary block."""
        from frontends import slash_cmds
        if not names:
            self._system("（未选择任何服务）"); return
        lines = [f"批量启动 {len(names)} 个服务："]
        for n in names:
            ok, msg = slash_cmds.start_service(n)
            lines.append(("  ✅ " if ok else "  ❌ ") + msg)
        self._system("\n".join(lines))

    def _reset_terminal_title(self) -> None:
        # Direct write on purpose: this runs at teardown when frames have stopped
        # (so there's no writer-thread race to avoid) and the driver may already
        # be stopped (enqueued writes would be silently dropped). See _term_write.
        try:
            out = sys.__stdout__
            out.write("\x1b]0;\x07")
            out.flush()
        except Exception:
            pass

    def on_unmount(self) -> None:
        self._reset_terminal_title()
        # Drop this run's empty signal dirs on graceful exit; the startup
        # sweep mops up anything a crash leaves behind.
        for s in list(self.sessions.values()):
            _rmdir_if_empty(getattr(s.agent, 'task_dir', None))

    def _run_shell(self, cmd: str) -> None:
        """`!cmd` magic: run `cmd` in the user's shell (Git Bash / pwsh /
        sh — see `detect_user_shell`), echo command + output into the
        current session's scrollback, and append a `[!shell]` pair to
        backend.history so the agent sees it on the next turn."""
        if not cmd:
            return
        sess = self.current
        sess.messages.append(ChatMessage("system",
                                         f"! {cmd}",
                                         kind="system"))
        import subprocess
        from frontends.slash_cmds import detect_user_shell
        shell_argv, shell_name = detect_user_shell()
        out = ''; rc = 0
        try:
            r = subprocess.run(
                shell_argv + [cmd], capture_output=True,
                timeout=30, encoding='utf-8', errors='replace',
            )
            out = (r.stdout or '') + (r.stderr or '')
            rc = r.returncode
        except subprocess.TimeoutExpired:
            out = '[shell: timeout 30s]'; rc = -1
        except Exception as e:
            out = f'[shell error: {type(e).__name__}: {e}]'; rc = -1
        body = (out.rstrip('\n') or '(no output)').split('\n')
        formatted = '\n'.join(('  └ ' + ln if i == 0 else '    ' + ln)
                              for i, ln in enumerate(body))
        sess.messages.append(ChatMessage("system", formatted, kind="system"))
        if sess.agent_id == self.current_id:
            self._refresh_messages()
        try:
            be = getattr(sess.agent, 'llmclient', None)
            be = getattr(be, 'backend', None) if be is not None else None
            if be is not None and hasattr(be, 'history'):
                txt = f"[!shell {shell_name}] {cmd}\n```\n{out.rstrip()}\n```\n(exit {rc})"
                be.history.append({"role": "user",
                                   "content": [{"type": "text", "text": txt}]})
        except Exception:
            pass

    # ---------------- agent task + stream ----------------
    # Pending-queue transport: submit while running → wrap text with the
    # "complete current task first, then address this" supplementary
    # phrasing and append to `_intervene` so ga.turn_end_callback prepends
    # it to next_prompt as `[MASTER] ...` mid-turn.  The wrap makes
    # `[MASTER]` read as an envelope, not a directive override.  On an
    # exit-turn boundary consume_file ate the file but next_prompt was
    # discarded — the replay hook re-routes via put_task.

    # Soft-guidance wrap — frame the user's mid-task message as input to fold
    # into ongoing reasoning, not a deferred queue item. This lets the model
    # redirect mid-flight if the message warrants it.
    _INTERVENE_WRAP_EN = (
        "User sent a message while you were working:\n"
        "{text}\n"
        "Please take it into consideration and adjust direction if needed."
    )
    _INTERVENE_WRAP_ZH = (
        "用户在你工作时发来了一条新消息：\n"
        "{text}\n"
        "请将其纳入考虑，必要时调整方向。"
    )

    def _wrap_user_steer(self, text: str) -> str:
        lang = (os.environ.get("GA_LANG", "") or "").lower()
        tmpl = self._INTERVENE_WRAP_EN if lang == "en" else self._INTERVENE_WRAP_ZH
        return tmpl.format(text=text)

    def _session_intervene_path(self, sess: AgentSession) -> Optional[str]:
        td = getattr(sess.agent, 'task_dir', None)
        if not td:
            return None
        try: os.makedirs(td, exist_ok=True)
        except Exception: return None
        return os.path.join(td, '_intervene')

    def _inject_intervene(self, sess: AgentSession, text: str) -> bool:
        """Append `text` to `<task_dir>/_intervene`.  Append-mode keeps us
        idempotent under the consume_file race."""
        if sess.status != "running":
            return False
        fp = self._session_intervene_path(sess)
        if not fp:
            return False
        try:
            sep = ''
            try:
                if os.path.getsize(fp) > 0: sep = '\n\n'
            except OSError: pass
            with open(fp, 'a', encoding='utf-8') as f:
                f.write(sep + text)
            return True
        except Exception:
            return False

    def _clear_intervene(self, sess: AgentSession) -> None:
        fp = self._session_intervene_path(sess)
        if fp:
            try: os.remove(fp)
            except OSError: pass

    def _install_intervene_replay_hook(self, sess: AgentSession) -> None:
        """At each turn boundary: non-exit → consume_file already delivered
        our wrapped text into next_prompt (clear UI mirror).  Exit → file
        was eaten but next_prompt was discarded; re-route the combined
        wrapped text via put_task so the user's words aren't lost."""
        agent = sess.agent
        try:
            hooks = getattr(agent, "_turn_end_hooks", None)
            if hooks is None:
                hooks = agent._turn_end_hooks = {}
            def _hook(ctx, _s=sess):
                with _s.pending_lk:
                    if not _s.pending_wrapped:
                        return
                    combined = "\n\n".join(_s.pending_wrapped)
                    _s.pending_wrapped = []
                    _s.pending = []
                if (ctx or {}).get("exit_reason"):
                    try:
                        dq = _s.agent.put_task(combined, source="user")
                    except Exception:
                        dq = None
                    if dq is not None:
                        _s.task_seq += 1
                        tid = _s.task_seq
                        _s.current_task_id = tid
                        _s.current_display_queue = dq
                        _s.buffer = ""
                        _s.status = "running"
                        _s.messages.append(ChatMessage("assistant", "", task_id=tid, done=False))
                        threading.Thread(
                            target=self._consume_display_queue,
                            args=(_s.agent_id, tid, dq),
                            daemon=True,
                            name=f"ga-tui-consume-{_s.agent_id}-{tid}",
                        ).start()
                try: self.call_from_thread(self._refresh_messages)
                except Exception: pass
                try: self.call_from_thread(self._refresh_bottombar)
                except Exception: pass
            hooks[f"tui_v2_intervene_{sess.agent_id}"] = _hook
        except Exception:
            pass

    def submit_user_message(self, text: str, images: Optional[list[str]] = None, display_text: Optional[str] = None) -> int:
        sess = self.current
        # Free-text ask_user answers go through a 2-step submit-confirm card.
        if self._maybe_intercept_free_text(sess, text):
            return -1
        if sess.status == "running":
            wrapped = self._wrap_user_steer(text)
            if self._inject_intervene(sess, wrapped):
                visible = text if display_text is None else display_text
                with sess.pending_lk:
                    sess.pending.append(text)
                    sess.pending_wrapped.append(wrapped)
                    n = len(sess.pending)
                sess.messages.append(ChatMessage(
                    "system",
                    f"[queued #{n}] {visible}",
                    kind="system",
                ))
                if sess.agent_id == self.current_id:
                    self._refresh_messages()
                    self._refresh_bottombar()
                return -1
            # Status flipped in the race — fall through to idle put_task.
        sess.task_seq += 1
        tid = sess.task_seq
        sess.current_task_id = tid
        sess.buffer = ""
        sess.status = "running"
        image_paths = list(images or [])
        visible_text = text if display_text is None else display_text
        sess.messages.append(ChatMessage("user", visible_text, image_paths=image_paths))
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
        if not s: return
        if s.current_task_id != task_id:
            # Exit-boundary replay can start a follow-up task before the original
            # display queue emits its final `done`.  The old done event must still
            # settle that assistant message; otherwise a single-turn interrupted
            # run keeps its spinner forever while the replay task owns
            # current_task_id.
            if done:
                found = None
                for m in reversed(s.messages):
                    if m.role == "assistant" and m.task_id == task_id:
                        m.content = text
                        m.done = True
                        found = m
                        break
                if found and agent_id == self.current_id:
                    if found._segment_widgets:
                        try: self._stream_update_assistant(found)
                        except Exception: self._refresh_messages()
                    else:
                        self._refresh_messages()
                    if refresh_chrome:
                        self._refresh_sidebar()
                        self._refresh_topbar()
                    self._ensure_spinner()
            return
        s.buffer = text
        if done:
            s.status = "idle"
            s.current_display_queue = None
        self._update_assistant(agent_id, text, task_id=task_id, done=done, refresh_chrome=True)
        if done:
            self._update_plan_state(s, text)
            self._drain_ask_user_events(s)

    # Phrasing-based opt-in for multi-select picker (no core schema change).
    _MULTI_RE = re.compile(r"\[?(?:多选|multi(?:[-_ ]?select)?|select all)\]?", re.IGNORECASE)

    def _drain_ask_user_events(self, sess: AgentSession) -> None:
        """Pop any pending ask_user INTERRUPTs and surface them as an
        interactive picker. The selected text is fed back via
        `submit_user_message`, exactly like a typed reply.

        - Single-select (default) → ChoiceList; ↑/↓ + Enter to pick.
        - Multi-select (when question hints `[多选]`) → MultiChoiceList;
          Space toggles, Enter submits joined by `; `.
        - Always appends a free-text escape hatch as the last option.
        """
        latest = None
        while True:
            try: latest = sess.ask_user_events.get_nowait()
            except queue.Empty: break
        if not latest: return
        question = latest["question"]; candidates = latest["candidates"]
        multi = bool(self._MULTI_RE.search(question))
        kind = "multi_choice" if multi else "choice"
        choices = [(c, c) for c in candidates] + [(FREE_TEXT_LABEL, FREE_TEXT_CHOICE)]
        hint = "Space 切换 · Enter 提交 · Esc 取消" if multi else "↑/↓ 选择 · Enter 确认 · Esc 取消"
        head = f"{question}    {hint}"
        # multi_choice hands `_finalize_multi_choice` a list of picked values;
        # single choice hands a plain string. The agent answer must be a string,
        # so collapse a list the same way the breadcrumb does ("; ".join).
        msg = ChatMessage(
            role="system", content=head, kind=kind, choices=choices,
            on_select=lambda v: self._answer_ask_user(
                sess.agent_id, "; ".join(v) if isinstance(v, list) else v),
        )
        sess.messages.append(msg)
        if sess.agent_id == self.current_id:
            self._refresh_messages()

    def _enter_free_text_mode(self, msg: ChatMessage) -> None:
        """User picked the free-text option. Swap the picker for a one-line
        prompt, keep the question hint visible, focus the input, and stash
        the full picker state so Esc can restore it. The question text is
        recovered from `msg.content`'s leading line (head was rendered as
        `question    ↑/↓...`)."""
        sess = self.sessions.get(self.current_id)
        if sess is None: return
        question = msg.content.split("    ")[0].rstrip() if "    " in msg.content else msg.content
        # Stash everything needed to rebuild the picker on Esc.
        sess.free_text_pending = {
            "question": question,
            "choices": list(msg.choices),
            "on_select": msg.on_select,
            "kind": msg.kind,
            "head": msg.content,
            "picker_msg": msg,
        }
        msg.selected_label = "Other (typing below — Esc to go back)"
        if msg._body_widget is not None:
            try: msg._body_widget.remove()
            except Exception: pass
        prompt = Text()
        prompt.append("Type your answer below, then press Enter. ", style=C_MUTED)
        prompt.append("Esc", style=C_GREEN)
        prompt.append(" goes back to the choices.", style=C_MUTED)
        try:
            container = self.query_one("#messages", VerticalScroll)
            new_widget = SelectableStatic(prompt, classes="msg")
            anchor = msg._hint_widget
            if anchor is not None: container.mount(new_widget, after=anchor)
            else: container.mount(new_widget)
            msg._body_widget = new_widget
            container.scroll_end(animate=False)
        except Exception:
            pass
        try: self.query_one("#input", InputArea).focus()
        except Exception: pass

    def _return_from_free_text(self) -> bool:
        """Esc while in free-text mode → restore the original picker.

        Tears down the `Type your answer below…` prompt and any draft input,
        then reposts the picker as a fresh ChatMessage. Returns True iff a
        restoration ran (so action_escape knows to swallow the key)."""
        sess = self.sessions.get(self.current_id) if self.current_id is not None else None
        pending = sess.free_text_pending if sess else None
        if not pending or not sess: return False
        old: ChatMessage = pending.get("picker_msg")  # type: ignore
        # Clear the input draft.
        try:
            inp = self.query_one("#input", InputArea)
            inp.text = ""
        except Exception: pass
        # Remove the consumed picker entirely so the rebuilt one is the only
        # active picker — keeps `_active_choice` unambiguous.
        if old is not None:
            for w in (old._role_widget, old._hint_widget, old._body_widget):
                if w is not None:
                    try: w.remove()
                    except Exception: pass
            if old in sess.messages: sess.messages.remove(old)
        # Repost a fresh picker using the stashed state. _refresh_messages
        # mounts the widget; on_mount focuses it.
        revived = ChatMessage(
            role="system", content=pending["head"], kind=pending["kind"],
            choices=pending["choices"], on_select=pending["on_select"],
        )
        sess.messages.append(revived)
        sess.free_text_pending = None
        self._refresh_messages()
        return True

    def _return_to_free_text_edit(self, confirm_msg: ChatMessage) -> None:
        """The submit-confirmation card sent us back to Edit. Tear down the
        confirmation, restore the typed answer to the input, and refocus."""
        sess = self.sessions.get(self.current_id)
        if sess is None: return
        prior = (sess.free_text_pending or {}).get("draft", "")
        for w in (confirm_msg._role_widget, confirm_msg._hint_widget, confirm_msg._body_widget):
            if w is not None:
                try: w.remove()
                except Exception: pass
        if confirm_msg in sess.messages: sess.messages.remove(confirm_msg)
        try:
            inp = self.query_one("#input", InputArea)
            inp.text = prior
            inp.focus()
        except Exception: pass

    def _maybe_intercept_free_text(self, sess: AgentSession, text: str) -> bool:
        """If a free-text answer is pending, show the `Ready to submit
        your answer?` confirmation card and DON'T forward to the agent yet.
        Returns True if the submit was intercepted."""
        if not sess.free_text_pending or not text.strip(): return False
        question = sess.free_text_pending.get("question", "")
        sess.free_text_pending["draft"] = text
        head = (f"Question: {question}\n"
                f"Your answer: {text}\n\n"
                f"Ready to submit your answer?    ←/→ 选择 · Enter 确认 · Esc 取消")
        confirm = ChatMessage(
            role="system", content=head, kind="choice",
            choices=[("Submit answer", text), ("Edit answer", EDIT_ANSWER_CHOICE)],
            on_select=lambda v, aid=sess.agent_id: self._finalize_free_text(aid, v),
        )
        sess.messages.append(confirm)
        self._refresh_messages()
        return True

    def _finalize_free_text(self, agent_id: int, value: str) -> str:
        """Submit-confirmation accepted: clear the pending state and route
        through the normal user-message path so the agent gets the answer."""
        s = self.sessions.get(agent_id)
        if s is not None: s.free_text_pending = None
        return self._answer_ask_user(agent_id, value)

    def _answer_ask_user(self, agent_id: int, value: str) -> str:
        s = self.sessions.get(agent_id)
        if not s: return value
        # submit_user_message must run on this agent's session — switch first
        # so it routes to the right put_task. (Choice clicks always come from
        # the foreground session anyway, but be defensive.)
        prev = self.current_id
        if agent_id != prev:
            self.current_id = agent_id
        try: self.submit_user_message(value)
        finally:
            if agent_id != prev: self.current_id = prev
        return value

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
        if found and found._segment_widgets:
            try:
                container = self.query_one("#messages", VerticalScroll)
                was_at_bottom = self._at_bottom(container)
                self._stream_update_assistant(found)
                if was_at_bottom:
                    container.scroll_end(animate=False)
            except Exception:
                self._refresh_messages()
        else:
            self._refresh_messages()
        if refresh_chrome:
            self._refresh_sidebar()
            self._refresh_topbar()
        self._ensure_spinner()

    # ---------------- Plan/todo panel ----------------
    # State machine (graces absorb mid-stream parse misses / let final tally read):
    #   hidden → active(n_done/n_total) → complete(n/n) → [3s grace] → hidden
    #   active/complete → empty → [1.5s grace] → hidden
    _PLAN_GRACE_SEC = 3.0
    _PLAN_LOST_GRACE_SEC = 1.5

    def _update_plan_state(self, sess: AgentSession, _stream_text: str = "") -> None:
        import plan_state
        prev = sess.plan_items
        # Detect plan mode: `working['in_plan_mode']` (live) first, then
        # `restored_plan_path` (/continue, recovered from the structured
        # enter_plan_mode tool_use). Chat text mentioning a plan path is
        # deliberately NOT a signal — no messages passed.
        new_items: list = []
        if plan_state.is_active(sess.agent, restored_path=sess.restored_plan_path):
            path = plan_state.resolve_path(sess.agent, restored_path=sess.restored_plan_path)
            if path:
                try:
                    with open(path, encoding="utf-8", errors="replace") as f:
                        new_items = plan_state.extract(f.read())
                except OSError:
                    new_items = []
        now_c = plan_state.is_complete(new_items) and new_items
        was_c = plan_state.is_complete(prev) and prev
        if now_c and not was_c: sess.plan_complete_since = time.time()
        elif not now_c:         sess.plan_complete_since = None
        if not new_items and prev:
            sess.plan_lost_since = time.time()
        elif new_items:
            sess.plan_lost_since = None
            sess.plan_items = new_items
        if sess.agent_id == self.current_id:
            self._refresh_planbar()

    def _refresh_planbar(self) -> None:
        try: bar = self.query_one("#planbar", Static)
        except Exception: return
        sess = self.sessions.get(self.current_id) if self.current_id is not None else None
        items = sess.plan_items if sess else []
        if sess and sess.plan_lost_since is not None:
            if time.time() - sess.plan_lost_since >= self._PLAN_LOST_GRACE_SEC:
                sess.plan_items = []; sess.plan_lost_since = None; items = []
        import plan_state
        msgs = sess.messages if sess else None
        base = sess.plan_scan_baseline if sess else 0
        # Plan-mode armed but no items yet → placeholder (covers the
        # enter_plan_mode → first plan.md write gap).
        if not items:
            if sess and plan_state.is_active(sess.agent,
                                             restored_path=sess.restored_plan_path):
                self._render_planbar_placeholder(bar, sess)
                return
            self._set_planbar_visible(bar, False); return
        n_done, n_total = plan_state.summary(items)
        complete = plan_state.is_complete(items)
        if complete and sess and sess.plan_complete_since is not None:
            if time.time() - sess.plan_complete_since >= self._PLAN_GRACE_SEC:
                self._set_planbar_visible(bar, False); return
        # Render all tasks — #planbar-tasks caps the visible window at 4 rows and
        # scrolls the rest. Open tasks first, done last (open work stays on top).
        step = plan_state.current_step(msgs, start_idx=base)
        ordered = [(c, st) for c, st in items if st != "done"] + \
                  [(c, st) for c, st in items if st == "done"]
        sig = (tuple(ordered), step, bool(complete and sess and sess.plan_complete_since))
        if getattr(bar, "_plan_sig", None) == sig and self._planbar_shown(): return
        bar._plan_sig = sig
        head = Text()
        head.append(f"✓ Plan complete ({n_total}/{n_total})" if complete
                    else f"📋 Plan ({n_done}/{n_total})", style=f"bold {C_GREEN}")
        if step:
            head.append("\n  ▸ ", style=C_GREEN)
            head.append(step[:120], style=C_MUTED)
        body = Text()
        for i, (c, st) in enumerate(ordered):
            if i: body.append("\n")
            if st == "done": body.append("  [x] ", style=C_GREEN); body.append(c, style=C_DIM)
            else:            body.append("  [ ] ", style=C_DIM);  body.append(c, style=C_FG)
        self._planbar_paint(head, body, bar)
        self._set_planbar_visible(bar, True)

    def _render_planbar_placeholder(self, bar: Static, sess: AgentSession) -> None:
        # Placeholder for armed-but-empty plan mode (pre-first plan.md write).
        import plan_state
        base = sess.plan_scan_baseline
        path = (plan_state._stashed_plan_path(sess.agent)
                or sess.restored_plan_path
                or "")
        hint = "/".join(path.replace("\\", "/").rstrip("/").split("/")[-2:]) if path else "plan.md"
        step = plan_state.current_step(sess.messages, start_idx=base)
        sig = ("__placeholder__", hint, step)
        if getattr(bar, "_plan_sig", None) == sig and self._planbar_shown(): return
        bar._plan_sig = sig
        head = Text()
        head.append("📋 Plan 模式已激活", style=f"bold {C_GREEN}")
        if step:
            head.append("\n  ▸ ", style=C_GREEN)
            head.append(step[:120], style=C_MUTED)
        body = Text()
        body.append(f"  等待写入 {hint} …", style=C_DIM)
        self._planbar_paint(head, body, bar)
        self._set_planbar_visible(bar, True)

    def _planbar_paint(self, head: Text, body: Text, bar: Static) -> None:
        # Header/step go to the pinned #planbar-head; tasks to #planbar (the
        # scrolling body). bar is #planbar, passed in by the callers.
        try: self.query_one("#planbar-head", Static).update(head)
        except Exception: pass
        bar.update(body)

    def _planbar_shown(self) -> bool:
        try: return self.query_one("#planbar-scroll", Vertical).has_class("-visible")
        except Exception: return False

    def _set_planbar_visible(self, bar: Static, visible: bool) -> None:
        # Visibility lives on the outer container (display:none ↔ -visible),
        # mirroring #palette. Repaint only on show→hide transition; idle ticks no-op.
        try: cont = self.query_one("#planbar-scroll", Vertical)
        except Exception: return
        if not visible:
            if not cont.has_class("-visible"): return
            cont.remove_class("-visible")
            try: self.query_one("#planbar-head", Static).update(Text())
            except Exception: pass
            bar.update(Text())
            bar._plan_sig = None
            return
        if not cont.has_class("-visible"):
            cont.add_class("-visible")

    def _start_plan_watcher(self) -> None:
        if getattr(self, "_plan_timer", None) is not None: return
        self._plan_mtime: dict = {}
        try: self._plan_timer = self.set_interval(1.0, self._poll_plan_files)
        except Exception: pass

    def _poll_plan_files(self) -> None:
        # Poll only the visible session — background sessions don't paint planbar.
        import plan_state
        sess = self.sessions.get(self.current_id) if self.current_id is not None else None
        if sess is None: return
        if not plan_state.is_active(sess.agent, restored_path=sess.restored_plan_path):
            self._refresh_planbar(); return
        path = plan_state.resolve_path(sess.agent, restored_path=sess.restored_plan_path)
        if not path:
            self._refresh_planbar(); return
        try: mtime = os.path.getmtime(path)
        except OSError:
            self._refresh_planbar(); return
        if self._plan_mtime.get(sess.agent_id) != mtime:
            self._plan_mtime[sess.agent_id] = mtime
            self._update_plan_state(sess); return
        self._refresh_planbar()  # tick grace timers

    # ---------------- Tip rotation ----------------
    # 12s show → 1s blank → next tip.
    _TIP_SHOW_SEC = 12.0
    _TIP_BLANK_SEC = 1.0

    def _start_tip_rotator(self) -> None:
        if getattr(self, "_tip_timer", None) is not None: return
        self._tip_current: str = ""
        try: self._tip_timer = self.set_interval(self._TIP_SHOW_SEC, self._rotate_tip)
        except Exception: pass

    def _rotate_tip(self) -> None:
        try: bar = self.query_one("#tipbar", Static)
        except Exception: return
        bar.update(_tip_line(""))  # blank pulse
        nxt = _random_tip(exclude=self._tip_current)
        self._tip_current = nxt
        try: self.set_timer(self._TIP_BLANK_SEC, lambda: self._show_tip(nxt))
        except Exception: self._show_tip(nxt)

    def _show_tip(self, tip: str) -> None:
        try: bar = self.query_one("#tipbar", Static)
        except Exception: return
        bar.update(_tip_line(tip))

    # ---------------- UI refresh ----------------
    def _system(self, text: str) -> None:
        if self.current_id is None: return
        self.current.messages.append(ChatMessage("system", text))
        self._refresh_messages()

    def _refresh_all(self):
        if not self.is_mounted: return
        self._swap_input_for_session()
        self._refresh_topbar()
        self._refresh_sidebar()
        self._refresh_messages()
        self._refresh_planbar()
        self._ensure_spinner()

    def _swap_input_for_session(self) -> None:
        """Persist the InputArea's text/history/pastes per-session so switching
        agents doesn't bleed input state across them."""
        if self.current_id is None:
            return
        try:
            inp = self.query_one("#input", InputArea)
        except Exception:
            return
        prev_id = getattr(self, "_input_owner_id", None)
        if prev_id == self.current_id:
            return
        if prev_id is not None and prev_id in self.sessions:
            prev = self.sessions[prev_id]
            prev.input_text = inp.text
            prev.input_history = inp._input_history
            prev.input_pastes = inp._pastes
            prev.input_paste_counter = inp._paste_counter
        sess = self.current
        inp._input_history = sess.input_history
        inp._pastes = sess.input_pastes
        inp._paste_counter = sess.input_paste_counter
        inp._history_index = -1
        inp._history_stash = ""
        try: inp._suppress_palette_next_change()
        except Exception: pass
        inp.text = sess.input_text
        self._input_owner_id = self.current_id
        try: self._resize_input(inp)
        except Exception: pass

    def _refresh_topbar(self):
        if not self.is_mounted or self.current_id is None: return
        s = self.current
        try: model = s.agent.get_llm_name(model=True)
        except Exception: model = "?"
        try: effort = getattr(s.agent.llmclient.backend, "reasoning_effort", "") or ""
        except Exception: effort = ""
        tasks_running = sum(1 for x in self.sessions.values() if x.status == "running")
        # App-wide busy window for the ✦ identity chip.
        if tasks_running > 0:
            if self._busy_since is None: self._busy_since = time.time()
            elapsed = int(time.time() - self._busy_since)
        else:
            self._busy_since = None
            elapsed = 0
        # Per-session busy window — drives the heat-color dot + done-flash.
        now = time.time()
        if s.status == "running":
            if s._busy_since is None: s._busy_since = now
            sess_elapsed = int(now - s._busy_since)
            just_done = False
        else:
            if s._busy_since is not None:
                s._done_at = now
                s._busy_since = None
            sess_elapsed = 0
            just_done = bool(s._done_at and (now - s._done_at) < _DONE_FLASH_SECS)
        # Chip ticker: keep running both for the elapsed counter AND so the
        # done-flash decays back to dim after _DONE_FLASH_SECS without input.
        need_ticker = (tasks_running > 0) or just_done
        if need_ticker and self._chip_timer is None:
            try: self._chip_timer = self.set_interval(1.0, self._refresh_topbar)
            except Exception: pass
        elif not need_ticker and self._chip_timer is not None:
            try: self._chip_timer.stop()
            except Exception: pass
            self._chip_timer = None
        try: term_w = self.size.width
        except Exception: term_w = 0
        # Workspace label is per-session, not the legacy process-global anchor.
        p = (s.workspace_path or "").rstrip("/\\")
        ws_name = os.path.basename(p) if p else s.workspace_name
        self.query_one("#topbar", Static).update(
            render_topbar(s.name, s.status, model, tasks_running,
                          fold_mode=self.fold_mode, busy_elapsed=elapsed, effort=effort,
                          sess_elapsed=sess_elapsed, just_done=just_done,
                          term_width=term_w, workspace=ws_name))
        self._ensure_title_timer()
        self._update_terminal_title()

    def _term_write(self, data: str) -> None:
        """Emit a raw control sequence to the terminal THROUGH Textual's driver.

        Direct sys.__stdout__ writes race Textual's background WriterThread at the
        byte level: an OSC/control sequence injected mid-frame splits one of
        Textual's own escape sequences, and the terminal renders the wreckage as
        flashing ANSI garbage (cleared by the next frame). Reproduces reliably by
        switching sessions while streaming, when the title ticker fires often.
        Routing through self._driver.write enqueues the sequence on the same
        serialized writer queue as the frames, so it lands atomically between
        them. Falls back to __stdout__ before the driver exists / in headless.
        """
        drv = getattr(self, "_driver", None)
        if drv is not None:
            try:
                drv.write(data)
                return
            except Exception:
                pass
        try:
            sys.__stdout__.write(data); sys.__stdout__.flush()
        except Exception:
            pass

    def _update_terminal_title(self) -> None:
        # OSC 0 (set window + icon title). Mainstream terminals consume it: Windows
        # Terminal, mintty (MinGW64/MSYS), iTerm2, Terminal.app, kitty, alacritty,
        # gnome-terminal, xterm. Others ignore the sequence silently.
        # IMPORTANT: write to sys.__stdout__, NOT sys.stdout — Textual replaces
        # sys.stdout with _capture_stdout during run, so writes to it never reach
        # the terminal. (textual/app.py: `with redirect_stdout(self._capture_stdout)`)
        if not self.is_mounted or self.current_id is None: return
        sess = self.current
        busy = any(x.status == "running" for x in self.sessions.values())
        name = (sess.name or "session").strip() or "session"
        if busy:
            glyph = _TITLE_SPINNER_FRAMES[self._title_frame % len(_TITLE_SPINNER_FRAMES)]
            title = f"{glyph} {name} · GenericAgent"
        else:
            title = f"{name} · GenericAgent"
        if title == self._last_title: return
        self._last_title = title
        # Serialize through the driver — see _term_write for the race this avoids.
        self._term_write(f"\x1b]0;{title}\x07")

    def _ensure_title_timer(self) -> None:
        busy = any(x.status == "running" for x in self.sessions.values())
        if busy and self._title_timer is None:
            try: self._title_timer = self.set_interval(0.2, self._tick_title)
            except Exception: pass
        elif not busy and self._title_timer is not None:
            try: self._title_timer.stop()
            except Exception: pass
            self._title_timer = None

    def _tick_title(self) -> None:
        self._title_frame = (self._title_frame + 1) % len(_TITLE_SPINNER_FRAMES)
        self._update_terminal_title()
        if not any(x.status == "running" for x in self.sessions.values()):
            self._ensure_title_timer()

    def _refresh_bottombar(self):
        if not self.is_mounted: return
        try:
            self.query_one("#bottombar", Static).update(render_bottombar(
                quit_armed=self._quit_armed,
                rewind_armed=self._rewind_armed,
            ))
        except Exception:
            pass

    def _refresh_sidebar(self):
        if not self.is_mounted: return
        self.query_one("#sidebar", Static).update(render_sidebar(self.sessions, self.current_id))
        self._scroll_active_session_into_view()

    def _scroll_active_session_into_view(self) -> None:
        # Keyboard session-switching (ctrl+up/down) can land on a session below
        # the fold; mirror on_click's row math to bring its block into view.
        if self.current_id is None:
            return
        try:
            scroll = self.query_one("#sidebar-scroll", VerticalScroll)
        except Exception:
            return
        y = 3  # pad-top(1) + "SESSIONS"(1) + blank(1), matches on_click
        for sid, sess in self.sessions.items():
            rows = 3
            if _sidebar_last_user(sess): rows += 1
            if _sidebar_last_summary(sess): rows += 1
            if sid == self.current_id:
                self.call_after_refresh(scroll.scroll_to_region,
                                        Region(0, y, 1, rows), animate=False)
                return
            y += rows

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
                m._segment_widgets = []
                m._segment_sig = ()
                m._spinner_widget = None
            self._last_session_id = sess.agent_id
        for m in sess.messages:
            if m._role_widget is None:
                self._mount_message(container, m)
        if was_at_bottom:
            # Defer the scroll until AFTER Textual has laid out any freshly
            # mounted widgets (e.g. a SearchableChoiceList picker). Calling
            # scroll_end() synchronously here races the layout pass: the new
            # widget still reports a stale/zero height, so we scroll to a
            # too-short virtual size and land on the message head, then the
            # picker expands below the fold (the "title visible, options
            # hidden" bug). call_after_refresh runs post-layout, so the final
            # height is known and scroll_end pins the true bottom.
            self.call_after_refresh(lambda: container.scroll_end(animate=False))

    def _messages_width(self) -> int:
        try:
            w = self.query_one("#messages", VerticalScroll).content_region.width
            return max(40, w)
        except Exception:
            return 100

    def _render_md(self, text: str, width: int):
        # Markdown via RichVisual loses segment.style.meta["offset"] so mouse selection
        # can't anchor; round-trip through ANSI → Text.from_ansi to restore selectability.
        # A parallel wide render builds a wrap-free "source" string that
        # SelectableStatic.get_selection uses, so copy never includes wrap newlines.
        try:
            from io import StringIO
            from rich.console import Console
            render_w = max(1, width - 1)
            text = _TASKLIST_OPEN_RE.sub(r"\1☐ ", text)
            text = _TASKLIST_DONE_RE.sub(r"\1✔ ", text)
            # file_write/file_patch render as a themed diff that markdown can't
            # express; swap them for a sentinel now and splice the prerendered
            # ANSI (narrow) / plain (wide) blocks back in after markdown runs.
            diff_blocks: dict[int, tuple[str, str]] = {}
            def _stash(rendered, _b=diff_blocks):
                n = len(_b)
                _b[n] = rendered
                return f"\n\nGADIFFSENTINEL{n}END\n\n"

            # Render a standalone markdown block to (narrow-ANSI, wide-plain)
            # streams with the card left margin: same theme/widths as the main
            # render so the spliced block matches its surroundings, but only the
            # narrow lines get the visual-only margin (kept out of the copy
            # source). Shared by the code_run card and the generic tool margin.
            def _md_to_streams(seg, _w=render_w):
                nbuf, wbuf = StringIO(), StringIO()
                Console(file=nbuf, width=max(8, _w - _DIFF_MARGIN),
                        force_terminal=True, color_system="truecolor",
                        legacy_windows=False,
                        theme=_markdown_rich_theme(_palette, minimal=(self.theme != "ga-default"))
                        ).print(HardBreakMarkdown(seg), end="")
                Console(file=wbuf, width=10000, force_terminal=False,
                        legacy_windows=False).print(HardBreakMarkdown(seg), end="")
                margin = " " * _DIFF_MARGIN
                nar = "\n".join(margin + l for l in nbuf.getvalue().rstrip("\n").split("\n"))
                return nar, wbuf.getvalue().rstrip("\n")

            # Primary path: the verbose `🛠️ Tool: …  📥 args:` block. Hash the
            # fence body to recover the real args the snapshot hook captured.
            def _sub_verbose(m, _w=render_w):
                cap = _WRITE_CAP.get(hash(m.group(2)))
                if cap:
                    if cap["name"] == "file_read":
                        r = _render_read_card(cap["args"], cap.get("content"), _w)
                    elif cap["name"] == "code_run":
                        r = _render_code_card(cap["args"], cap.get("data"), _w)
                    else:
                        status, msg = cap.get("status"), cap.get("msg", "")
                        st = _fence_status(m.group(3))
                        if st:
                            status, msg = st
                        r = _render_write_diff(cap["name"], cap["args"],
                                               cap["existed"], cap["old"], _w,
                                               status=status, msg=msg)
                    if r:
                        return _stash(r)
                return m.group(0)
            text = _VERBOSE_WRITE_RE.sub(_sub_verbose, text)
            # Every other tool keeps its Rich-markdown look but gains the same
            # left margin: render the block standalone with the same theme.
            # file_read / code_run with a missing capture fall through here and
            # at least get the margin (their bespoke cards already ran above).
            def _sub_tool_margin(m, _w=render_w):
                return _stash(_md_to_streams(m.group(0), _w))
            text = _VERBOSE_TOOL_RE.sub(_sub_tool_margin, text)
            # Legacy path: a raw `<tool_use>{…}</tool_use>` envelope (weak-tool
            # models that inline tool calls as text rather than native calls).
            def _sub_tool(m, _w=render_w):
                try:
                    obj = json.loads(m.group(1))
                except Exception:
                    return m.group(0)
                if obj.get("name") in ("file_write", "file_patch"):
                    args = obj.get("arguments") or {}
                    r = _render_write_diff(obj.get("name"), args, False, "", _w)
                    if r:
                        return _stash(r)
                return _render_tool_use_block(m)
            text = _TOOL_USE_RE.sub(_sub_tool, text)
            text = _META_TAG_RE.sub("", text)
            buf = StringIO()
            Console(file=buf, width=render_w, force_terminal=True,
                    color_system="truecolor", legacy_windows=False,
                    theme=_markdown_rich_theme(_palette, minimal=(self.theme != "ga-default"))
                    ).print(HardBreakMarkdown(text), end="")
            narrow_raw = buf.getvalue().rstrip("\n")

            wide_buf = StringIO()
            Console(file=wide_buf, width=10000, force_terminal=False,
                    legacy_windows=False).print(HardBreakMarkdown(text), end="")
            wide_raw = wide_buf.getvalue().rstrip("\n")

            # Splice diff blocks over their sentinel lines (ANSI → narrow,
            # plain → wide). Identical post-rstrip text keeps line counts equal
            # so `_align_md_renders` pairs them via its K==W branch.
            for n, (ansi_block, plain_block) in diff_blocks.items():
                pat = re.compile(rf"^.*GADIFFSENTINEL{n}END.*$", re.M)
                narrow_raw = pat.sub(lambda _m, _a=ansi_block: _a, narrow_raw, count=1)
                wide_raw = pat.sub(lambda _m, _p=plain_block: _p, wide_raw, count=1)

            t = Text.from_ansi(narrow_raw)
            t.highlight_regex(r"✔[^\n]*", style=C_DIM)
            t.highlight_regex(r"☐", style=C_DIM)
            t.highlight_regex(r"✔", style=C_GREEN)

            narrow_plain = _ANSI_SGR_RE.sub("", narrow_raw)
            # `_align_md_renders` handles Rich table/box-drawing runs at run
            # granularity: only the table block is copied visually, while normal
            # paragraphs in the same widget still use the wrap-stripping wide
            # source.  A whole-widget table bypass regressed mixed
            # paragraph+table messages by copying visual wrap newlines.
            source, starts, indents, lens = _align_md_renders(narrow_plain, wide_raw)
            return _MdRender(text=t, source=source, line_starts=starts,
                             line_indents=indents, line_lengths=lens)
        except Exception:
            fallback = Text(text, style=C_FG)
            return _MdRender(text=fallback, source=text,
                             line_starts=[0], line_indents=[0], line_lengths=[len(text)])

    def _assistant_segments(self, m: ChatMessage, width: int) -> list[tuple]:
        """Return [(kind, body, fold_idx_or_None)]. kind ∈ {'text','fold-header','fold-body'}.
        fold_idx is the position in fold_turns() output — stable across streaming since
        new turns only append. Last segment carries the streaming suffix."""
        raw = m.content or ""
        # Cache final renders — Markdown re-parse on every resize is expensive over long history.
        key = (len(raw), m.done, width, self.fold_mode, frozenset(m._toggled_folds))
        if m.done and m._cache_key == key and m._cached_body is not None:
            return m._cached_body
        # No streaming suffix here — spinner lives in m._spinner_widget so Markdown
        # rendering (unclosed code fences, paragraph whitespace stripping) can't eat it.
        if not raw.strip():
            return [("text", Text("（空）" if m.done else " ", style=C_DIM), None)]
        cleaned = _ANSI_CONTROL_RE.sub("", raw)
        raw_segs = fold_turns(cleaned)
        # Drop cache entries whose width changed — content keys with stale width
        # would never be hit again and would leak memory across resizes.
        if m._seg_render_cache and any(k[1] != width for k in m._seg_render_cache):
            m._seg_render_cache.clear()

        def cached_render(content: str) -> "_MdRender":
            k = (hash(content), width)
            v = m._seg_render_cache.get(k)
            if v is None:
                v = self._render_md(content, width)
                m._seg_render_cache[k] = v
            return v

        out: list[tuple] = []
        last_i = len(raw_segs) - 1
        for i, seg in enumerate(raw_segs):
            if seg["type"] == "fold":
                # fold_mode=True → default collapsed; False → default expanded. Per-fold
                # clicks flip the default for that fold via the toggle set.
                expanded = (not self.fold_mode) ^ (i in m._toggled_folds)
                arrow = "▾" if expanded else "▸"
                title = seg.get("title") or "completed turn"
                header = Text(); header.append(f"{arrow} ", style=C_DIM); header.append(title, style=C_MUTED)
                out.append(("fold-header", header, i))
                if expanded:
                    out.append(("fold-body", cached_render(seg.get("content", "")), i))
            else:
                content = _TURN_MARKER_RE.sub("", seg.get("content", ""), count=1)
                # While streaming, the tail text segment grows every chunk — Markdown
                # parsing it per chunk is the streaming-lag root cause. Render via
                # Text.from_ansi during streaming (O(n) scan, no reflow) so SGR codes
                # in the chunk become styles instead of literal `[31m` glyphs;
                # _stream_update_assistant swaps in the real Markdown render once
                # m.done flips True.
                if i == last_i and not m.done:
                    out.append(("text", Text.from_ansi(content, style=C_FG), None))
                else:
                    out.append(("text", cached_render(content), None))
        if m.done:
            m._cached_body = out
            m._cache_key = key
        return out

    _SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    # Spinner gerund pool (stable per-message via id-hash; separate from _DONE_GERUNDS).
    _SPINNER_GERUNDS = (
        "Pondering", "Reticulating", "Sleuthing", "Hatching", "Pouncing",
        "Brewing", "Sharpening", "Untangling", "Compiling", "Unraveling",
        "Distilling", "Calibrating", "Marinating", "Conjuring", "Foraging",
        "Spelunking", "Synthesizing", "Refactoring thoughts", "Tracing breadcrumbs",
        "Following the rabbit hole",
        "Routing", "Threading", "Polling", "Spinning", "Hooking",
        "Patching", "Caching", "Yielding", "Hydrating", "Folding",
        "Streaming", "Resolving", "Reaping", "Tuning",
    )

    def _spinner_glyph(self) -> str:
        return self._SPINNER_FRAMES[self._spinner_frame % len(self._SPINNER_FRAMES)]

    def _spinner_gerund(self, m) -> str:
        # ID-hashed → stable per-message; survives content mutation.
        idx = (id(m) // 16) % len(self._SPINNER_GERUNDS)
        return self._SPINNER_GERUNDS[idx]

    @staticmethod
    def _humanize_tokens(n: int) -> str:
        if n < 1000: return f"{n}"
        if n < 1_000_000:
            v = n / 1000.0
            return f"{v:.1f}k" if v < 100 else f"{int(v)}k"
        return f"{n / 1_000_000.0:.2f}M"

    def _fmt_tokens(self, last_in: int, last_out: int) -> str:
        """`↑ N · ↓ M` for the latest call's sizes, or "" when both are zero."""
        if last_in <= 0 and last_out <= 0:
            return ""
        return f"↑ {self._humanize_tokens(last_in)} · ↓ {self._humanize_tokens(last_out)}"

    def _spinner_annotation(self, m) -> Text:
        """Render `⠋ Gerund… (Xm Ys · ↑ N · ↓ M)` for a streaming message.
        ↑/↓ are the latest LLM call's prompt / completion sizes, gated on
        cumulative counters moving past the baselines captured at stream start
        (otherwise the prior turn's tail values leak in on prompt submit).
        """
        if m._stop_summary is not None:
            return self._stopping_annotation(m)
        out = Text()
        elapsed = int(time.time() - m._stream_started_at) if m._stream_started_at else 0
        last_in, last_out = self._live_call_tokens(m)
        gerund_style = _gerund_color(elapsed, last_in)
        out.append(self._spinner_glyph(), style=gerund_style)
        out.append(f" {self._spinner_gerund(m)}…", style=gerund_style)
        bits = []
        if m._stream_started_at:
            bits.append(_fmt_elapsed(elapsed))
        tok = self._fmt_tokens(last_in, last_out)
        if tok:
            bits.append(tok)
        if bits:
            out.append("  (", style=C_DIM)
            out.append(" · ".join(bits), style=C_DIM)
            out.append(")", style=C_DIM)
        return out

    def _live_call_tokens(self, m) -> tuple:
        """`(last_in, last_out)` for this turn, gated on cumulative deltas past
        the per-message baselines. Returns zeros until the new turn moves
        the counters. Shared by spinner + done-card."""
        last_in = last_out = 0
        try:
            import cost_tracker
            sess = self.sessions.get(self.current_id)
            tname = sess.thread.name if sess and sess.thread else f"ga-tui-agent-{self.current_id}"
            t = cost_tracker.get(tname)
            cum_in = t.input + t.cache_create + t.cache_read
            cum_out = t.output
            if cum_in > m._stream_baseline_input: last_in = t.last_input
            if cum_out > m._stream_baseline_output: last_out = t.last_output
        except Exception:
            pass
        return last_in, last_out

    # Settled-state braille pairs with the spinner frames (⠋…⠏ → ⠿).
    _DONE_GLYPH = "⠿"

    # Past-tense pool for the post-turn card; reads "{Verb} for Xm Ys".
    _DONE_GERUNDS = (
        "Churned", "Ruminated", "Brewed", "Cooked", "Marinated", "Percolated",
        "Distilled", "Crystallized", "Synthesized", "Sharpened", "Conjured",
        "Pondered", "Spelunked", "Untangled", "Foraged", "Hatched", "Pounced",
        "Sleuthed", "Unraveled", "Calibrated", "Mused", "Schemed", "Tinkered",
        "Forged", "Simmered", "Steeped",
        "Threaded", "Folded", "Patched", "Streamed", "Cached", "Hooked",
        "Routed", "Resolved", "Yielded", "Hydrated", "Reaped", "Tuned",
        "Plotted", "Reviewed", "Audited", "Verified", "Adjudicated",
        "Conducted", "Orchestrated",
        "Mapped", "Reduced", "Dispatched",
        "Recalled", "Stashed", "Indexed",
    )

    def _done_gerund(self, m) -> str:
        # Stable per-message — id-hash so re-mount (theme / resize / fold) keeps
        # the verb; spinner uses a separate pool so live/settled never collide.
        idx = (id(m) // 16) % len(self._DONE_GERUNDS)
        return self._DONE_GERUNDS[idx]

    def _done_annotation(self, m) -> Text:
        """Render `⠿ {Verb} for Xm Ys · ↑ N · ↓ M` after a turn finishes.
        Numbers frozen via `_done_summary` so re-mounts / next turn don't
        shift the line. A user-aborted turn reads `⠿ Stopped after Xm Ys`
        off the abort-time `_stop_summary` instead."""
        if m._stop_summary is not None:
            elapsed, last_in, last_out = m._stop_summary
            verb, glyph_style = "Stopped after", C_DIM
        else:
            elapsed, last_in, last_out = m._done_summary or (0, 0, 0)
            verb, glyph_style = f"{self._done_gerund(m)} for", C_GREEN
        out = Text()
        out.append(self._DONE_GLYPH + " ", style=glyph_style)
        out.append(f"{verb} {_fmt_elapsed(int(elapsed))}", style=C_DIM)
        tok = self._fmt_tokens(last_in, last_out)
        if tok:
            out.append("  · " + tok, style=C_DIM)
        return out

    def _stopping_annotation(self, m) -> Text:
        """Settled `⠿ Stopping… (Xm Ys · ↑ N · ↓ M)` shown from the moment the
        user aborts until the LLM stream actually unwinds. Numbers frozen via
        `_stop_summary` so elapsed stops climbing while we wait — the live
        spinner would otherwise keep ticking until `done` finally flips."""
        elapsed, last_in, last_out = m._stop_summary or (0, 0, 0)
        out = Text()
        out.append(self._DONE_GLYPH + " ", style=C_DIM)
        out.append(f"Stopping… ({_fmt_elapsed(int(elapsed))}", style=C_DIM)
        tok = self._fmt_tokens(last_in, last_out)
        if tok:
            out.append(" · " + tok, style=C_DIM)
        out.append(")", style=C_DIM)
        return out

    def _freeze_summary(self, m) -> tuple:
        """Snapshot `(elapsed, last_in, last_out)` at the current instant."""
        elapsed = (time.time() - m._stream_started_at) if m._stream_started_at else 0.0
        return (elapsed, *self._live_call_tokens(m))

    def _capture_done_summary(self, m) -> None:
        """Freeze the turn's numbers once it flips done→True. Idempotent, so
        re-mounts and stream-update passes never overwrite the snapshot."""
        if m._done_summary is None and m.done:
            m._done_summary = self._freeze_summary(m)

    def _capture_stop_summary(self, m) -> None:
        """Freeze the turn's numbers the instant the user aborts. Idempotent —
        the first Ctrl+C / `/stop` wins so a late real abort can't bump elapsed."""
        if m._stop_summary is None:
            m._stop_summary = self._freeze_summary(m)

    def _mark_stopping(self, sess) -> None:
        """Freeze every in-flight assistant in `sess` to the settled "Stopping…"
        line and push it now, so the spinner stops climbing the instant the user
        aborts instead of after the LLM stream unwinds in the background."""
        for m in sess.messages:
            if m.role == "assistant" and not m.done:
                self._capture_stop_summary(m)
                if m._spinner_widget is not None:
                    try: m._spinner_widget.update(self._stopping_annotation(m))
                    except Exception: pass

    def _has_streaming(self) -> bool:
        if self.current_id is None:
            return False
        return any(m.role == "assistant" and not m.done for m in self.current.messages)

    def _ensure_spinner(self) -> None:
        # Independent timer keeps frames advancing between chunks (chunks may stall on the
        # network). Self-stops once no assistant message in the current session is streaming.
        running = self._has_streaming()
        if running and self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.1, self._spinner_tick)
        elif not running and self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
            self._spinner_frame = 0

    def _spinner_tick(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(self._SPINNER_FRAMES)
        if self.current_id is None:
            self._ensure_spinner(); return
        for m in self.current.messages:
            if m.role == "assistant" and not m.done and m._spinner_widget is not None:
                if m._stream_started_at is None:
                    self._mark_stream_start(m)
                try: m._spinner_widget.update(self._spinner_annotation(m))
                except Exception: pass
        if not self._has_streaming():
            self._ensure_spinner()

    def _mark_stream_start(self, m) -> None:
        """Lazily timestamp a streaming message so the spinner can show elapsed/tokens.
        Snapshots both input-side and output-side token totals as baselines so
        the spinner's `↑ N · ↓ M` reflects *this* turn only."""
        m._stream_started_at = time.time()
        try:
            import cost_tracker
            sess = self.sessions.get(self.current_id)
            tname = sess.thread.name if sess and sess.thread else f"ga-tui-agent-{self.current_id}"
            t = cost_tracker.get(tname)
            m._stream_baseline_input = t.input + t.cache_create + t.cache_read
            m._stream_baseline_output = t.output
        except Exception:
            m._stream_baseline_input = 0
            m._stream_baseline_output = 0

    @staticmethod
    def _segment_sig(segs: list[tuple]) -> tuple:
        # Topology fingerprint: ignores body content so streaming chunks within the same
        # last text segment don't invalidate the structure. Used to decide stream-update
        # (in-place .update of last widget) vs. full remount (when folds appear/expand).
        return tuple((kind, idx) for kind, _, idx in segs)

    def _mount_message(self, container: VerticalScroll, m: ChatMessage) -> None:
        # Looked up at call time (not class init) so theme switches propagate.
        color = {"user": C_PURPLE, "system": C_BLUE, "assistant": C_GREEN}.get(m.role, C_GREEN)
        label = m.role.upper() if m.role != "assistant" else "AGENT"
        m._role_widget = SelectableStatic(f"[bold {color}]{label}[/]", classes="role")
        container.mount(m._role_widget)

        if m.kind in ("choice", "multi_choice") and m.selected_label is None:
            m._hint_widget = SelectableStatic(Text(m.content, style=C_MUTED), classes="msg")
            container.mount(m._hint_widget)
            if m.kind == "multi_choice":
                # Index into m.choices is preserved as the Selection value, so
                # the submit handler can recover labels — including the free-
                # text option, treated as a "drop everything and type" trigger.
                # `initial_state=True` for indices already running (bug#4) so
                # the card opens with them ticked → unticking == "stop this".
                _pre = set(m.preselected_indices or [])
                widget = MultiChoiceList(m, *(Selection(cl, idx, idx in _pre)
                                              for idx, (cl, _) in enumerate(m.choices)),
                                         classes="picker")
            else:
                if m.lazy_choice_items:
                    # Lazy path: mount only the first batch, stream the rest.
                    # `lazy_choice_items` holds the label list mirrored from
                    # m.choices so we never mutate the canonical choices array.
                    widget = LazyChoiceList(
                        m, m.lazy_choice_items,
                        batch=m.lazy_choice_batch or 50,
                        classes="picker",
                    )
                elif m.searchable and not m.choices:
                    # Async-filled picker still loading (or empty): disabled
                    # hint row under the Input, same shape as the no-matches row.
                    widget = ChoiceList(m, m.empty_hint, classes="picker")
                    widget.disabled = True
                else:
                    widget = ChoiceList(m, classes="picker")
                    for cl, _ in m.choices:
                        widget.add_option(cl)
                # `searchable` wraps the freshly-built picker in a Vertical
                # container with an Input filter on top. The original picker
                # is preserved as `.picker` so `_active_choice`, key routing
                # and `_collapse_choice` all keep working unchanged.
                if m.searchable:
                    widget = SearchableChoiceList(m, widget, classes="picker")
            m._body_widget = widget
            container.mount(widget)
            # For searchable pickers we focus the Input so the user can start
            # typing immediately; for plain pickers we focus the OptionList as
            # before so arrow keys work out of the box.
            if isinstance(widget, SearchableChoiceList):
                def _focus_input(w=widget):
                    inp = getattr(w, "_search_input", None)
                    try:
                        (inp or w).focus()
                    except Exception:
                        pass
                self.call_after_refresh(_focus_input)
            else:
                self.call_after_refresh(widget.focus)
            return

        if m.kind in ("choice", "multi_choice"):  # selected_label is not None
            body = Text(); body.append("✓ ", style=C_GREEN); body.append(m.selected_label, style=C_FG)
            m._body_widget = SelectableStatic(body, classes="msg")
            container.mount(m._body_widget)
            return
        if m.role == "user":
            body = Text(); body.append("> ", style=C_DIM); body.append(_elide_user_display(m.content), style=C_FG)
            for path in m.image_paths:
                body.append(f"\n📎 {path}", style=C_MUTED)
            m._body_widget = SelectableStatic(body, classes="msg")
            container.mount(m._body_widget)
            return
        if m.role == "system":
            m._body_widget = SelectableStatic(Text(m.content, style=C_MUTED), classes="msg")
            container.mount(m._body_widget)
            return
        # assistant — multi-segment for per-fold click-to-expand
        segs = self._assistant_segments(m, self._messages_width())
        self._mount_assistant_segments(container, m, segs)

    def _mount_assistant_segments(self, container, m: ChatMessage, segs: list[tuple],
                                  after=None) -> None:
        m._segment_widgets = []
        last_text = None
        anchor = after
        for kind, body, fold_idx in segs:
            if kind == "fold-header":
                w = FoldHeader(body, m, fold_idx, classes="msg fold-header")
            else:
                if isinstance(body, _MdRender):
                    w = SelectableStatic(body.text, classes="msg")
                    w._ga_render = body
                else:
                    w = SelectableStatic(body, classes="msg")
            if anchor is None:
                container.mount(w)
            else:
                container.mount(w, after=anchor)
                anchor = w
            m._segment_widgets.append(w)
            if kind == "text":
                last_text = w
        m._body_widget = last_text  # keeps existing streaming `.update()` paths working
        m._segment_sig = self._segment_sig(segs)
        self._sync_spinner_widget(container, m, anchor)

    def _sync_spinner_widget(self, container, m: ChatMessage, anchor) -> None:
        """Tiny dedicated Static after segment widgets — outside Markdown so
        unclosed code fences / paragraph trimming can't eat it. While streaming
        shows the spinner annotation; once `m.done` flips True, the same widget
        becomes the post-turn `⠿ Churned for Xm Ys` card (frozen via
        `_capture_done_summary`)."""
        if m.done:
            # `_stream_started_at` is the marker that this message was actually
            # streamed in this TUI session. Restored /continue history flips
            # done=True without ever streaming, so skip the card there — a
            # "⠿ Churned for 0s" badge under every archived turn is just noise.
            if m._stream_started_at is None:
                if m._spinner_widget is not None:
                    try: m._spinner_widget.remove()
                    except Exception: pass
                    m._spinner_widget = None
                return
            self._capture_done_summary(m)
            if m._spinner_widget is None:
                w = Static(self._done_annotation(m), classes="msg spinner")
                if anchor is None: container.mount(w)
                else:               container.mount(w, after=anchor)
                m._spinner_widget = w
            else:
                try: m._spinner_widget.update(self._done_annotation(m))
                except Exception: pass
            return
        if m._spinner_widget is None:
            if m._stream_started_at is None:
                self._mark_stream_start(m)
            w = Static(self._spinner_annotation(m), classes="msg spinner")
            if anchor is None:
                container.mount(w)
            else:
                container.mount(w, after=anchor)
            m._spinner_widget = w

    def _stream_update_assistant(self, m: ChatMessage) -> None:
        """Cheap path for per-chunk streaming: if the fold topology is unchanged, only
        the last text segment got new content, so render and update that one widget.
        Otherwise (a new Turn marker appeared), do a full remount."""
        new_sig = self._assistant_sig_only(m)
        if (new_sig == m._segment_sig and m._segment_widgets
                and new_sig and new_sig[-1][0] == "text"):
            width = self._messages_width()
            raw = m.content or ""
            cleaned = _ANSI_CONTROL_RE.sub("", raw)
            last_seg = fold_turns(cleaned)[-1]
            last_text = _TURN_MARKER_RE.sub("", last_seg.get("content", ""), count=1)
            last_widget = m._segment_widgets[-1]
            # During streaming use Text.from_ansi — Markdown parse per chunk is
            # O(chunks × turn_len), but raw Text() would render upstream SGR codes
            # as literal `[31m` glyphs (visible as ANSI garbage until done flips
            # True or a resize forces remount). from_ansi is O(n) and resolves
            # the codes into Rich styles. On the terminal `done` chunk we render
            # Markdown once and swap, restoring code blocks / lists / inline
            # styling and clean-copy.
            if m.done:
                rendered = self._render_md(last_text, width)
                if isinstance(rendered, _MdRender):
                    last_widget._ga_render = rendered
                    last_widget.update(rendered.text)
                else:
                    last_widget.update(rendered)
            else:
                last_widget._ga_render = None
                # Normalise CRLF → LF before from_ansi. On Windows child stdout
                # is `\r\n`; from_ansi treats `\r` as a carriage return, so each
                # line's text gets overwritten/erased by its own trailing `\r`
                # and the whole `[Stdout]` block renders as blank lines until the
                # turn finishes (the done-state Markdown render strips `\r`). We
                # show the output as-is otherwise — blank-line runs are left for
                # Markdown to fold on completion. Lone `\r` (no `\n`) is kept so
                # progress-bar overwrites still work.
                display = last_text.replace("\r\n", "\n")
                last_widget.update(Text.from_ansi(display, style=C_FG))
            if m.done and m._spinner_widget is not None:
                # Convert the live spinner into the post-turn ⠿ card in place.
                self._capture_done_summary(m)
                try: m._spinner_widget.update(self._done_annotation(m))
                except Exception: pass
            return
        self._remount_assistant_message(m)

    def _assistant_sig_only(self, m: ChatMessage) -> tuple:
        # Topology signature without rendering bodies — used by the streaming fast path.
        raw = m.content or ""
        if not raw.strip():
            return (("text", None),)
        cleaned = _ANSI_CONTROL_RE.sub("", raw)
        sig = []
        for i, seg in enumerate(fold_turns(cleaned)):
            if seg["type"] == "fold":
                sig.append(("fold-header", i))
                if (not self.fold_mode) ^ (i in m._toggled_folds):
                    sig.append(("fold-body", i))
            else:
                sig.append(("text", None))
        return tuple(sig)

    def _remount_assistant_message(self, m: ChatMessage) -> None:
        """Rebuild just this message's segments in-place. Used by click-to-expand and
        by streaming when fold topology changes."""
        try:
            container = self.query_one("#messages", VerticalScroll)
        except Exception:
            return
        anchor = m._role_widget
        for w in m._segment_widgets:
            try: w.remove()
            except Exception: pass
        m._segment_widgets = []
        if m._spinner_widget is not None:
            try: m._spinner_widget.remove()
            except Exception: pass
            m._spinner_widget = None
        segs = self._assistant_segments(m, self._messages_width())
        self._mount_assistant_segments(container, m, segs, after=anchor)


# ---------- CLI ----------
def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="GenericAgent TUI v2 (refined visual style)")


def _warn_mintty():
    """Warn only for direct Git Bash/mintty, not Git Bash inside Windows Terminal."""
    if sys.platform != 'win32':
        return
    # Direct Git Bash uses mintty. Git Bash hosted by Windows Terminal still sets
    # MSYSTEM, but has WT_SESSION and renders Textual correctly, so do not block it.
    term_prog = os.environ.get('TERM_PROGRAM', '').lower()
    wt_session = os.environ.get('WT_SESSION', '')
    direct_mintty = term_prog == 'mintty' and not wt_session
    if direct_mintty:
        print(
            "\033[33m[ga-tui] WARNING: direct Git Bash/mintty detected.\033[0m\n"
            "  Textual TUI requires a modern terminal with full VT/xterm support.\n"
            "  Direct mintty can cause rendering issues (blank screen, garbled output).\n"
            "\n"
            "  Recommended alternatives:\n"
            "    - Windows Terminal Git Bash: wt -p \"Git Bash\" python frontends/tuiapp_v2.py\n"
            "    - Windows Terminal:          wt python frontends/tuiapp_v2.py\n"
            "    - CMD:                       python frontends\\tuiapp_v2.py\n"
            "    - PowerShell:                python frontends/tuiapp_v2.py\n"
            "\n"
            "  To continue anyway, set GA_TUI_FORCE=1",
            file=sys.stderr,
        )
        if not os.environ.get('GA_TUI_FORCE'):
            raise SystemExit(1)


def main(argv: Optional[list[str]] = None) -> int:
    build_arg_parser().parse_args(argv)
    _warn_mintty()
    GenericAgentTUI().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
