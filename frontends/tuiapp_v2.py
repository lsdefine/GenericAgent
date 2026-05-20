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
    from textual.message import Message
    from textual.screen import ModalScreen
    from textual.widgets import OptionList, SelectionList, Static, TextArea
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

# Strip the leading `**LLM Running (Turn N) ...**` marker that agent_loop yields per turn.
# fold_turns still needs the marker in source content to split turns, so we only strip at
# render time. Applies to the live (last) text segment, since folded turns don't include it.
_TURN_MARKER_RE = re.compile(r"^\s*\**LLM Running \(Turn \d+\) \.\.\.\**\s*", re.MULTILINE)

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
    "Tip: Ctrl+B 折叠侧栏；Ctrl+O 切换长输出折叠；Ctrl+/ 查看快捷键。",
    "Tip: Ctrl+N 新建会话；Ctrl+↑/↓ 在多个会话间切换。",
    "Tip: 粘贴图片 / 文件后会自动折叠成 [Image #N] / [File #N] 占位符。",
    "Tip: 多行输入用 Ctrl+J 换行；Enter 直接发送。",
    "Tip: /rewind <n> 回退最近 n 轮对话；/stop 中止当前任务。",
    "Tip: /export clip 把上一条回复复制到剪贴板；/export all 给出完整日志路径。",
    "Tip: /branch [name] 从当前历史分裂出新会话，互不污染。",
    "Tip: ask_user 题目里写 [多选] 自动切到 SelectionList；任何 picker 都有 \"Type something\" 走自由输入。",
    "Tip: plan 模式下的 todo 会渲染在消息区与输入框之间的 📋 Plan 卡片，完成后自动消失。",
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


# Rich's Markdown.TableElement adds columns without specifying `overflow`,
# so Rich Table falls back to "ellipsis" — long cell contents get truncated
# with `…` in narrow terminals. Patch to use "fold" instead so cells wrap
# across multiple lines and full content stays visible.
def _patch_markdown_table_overflow():
    import rich.markdown as _rmd
    from rich.table import Table as _RichTable
    from rich import box as _rich_box

    def _table_render(self, console, options):
        table = _RichTable(
            box=_rich_box.SIMPLE,
            pad_edge=False,
            style="markdown.table.border",
            show_edge=True,
            collapse_padding=True,
        )
        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                heading = column.content.copy()
                heading.stylize("markdown.table.header")
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
        if W == 0:
            for k in range(K):
                wrap_groups.append(((run_start + k, run_start + k + 1), run_lines[k]))
        elif K == W:
            for k in range(K):
                wrap_groups.append(((run_start + k, run_start + k + 1), wide_lines[k]))
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
                        content = nt
                    accumulated += len(content)
                    j += 1
                    # Each wrap boundary eats one space from the wide line, so
                    # the narrow side's accumulated content runs (consumed - 1)
                    # chars short of target at the natural wrap point.
                    consumed = j - (g_start - run_start)
                    if not is_last and accumulated + max(0, consumed - 1) >= target:
                        break
                wrap_groups.append(((g_start, run_start + j), w_line))

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

        (g_start, g_end), wide_line = wrap_groups[group_idx]
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

        if is_centered:
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
                    content = nt
                    indent = 0
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
from review_cmd import handle as review_handle
from continue_cmd import list_sessions as continue_list, extract_ui_messages as continue_extract
from export_cmd import last_assistant_text, export_to_temp, wrap_for_clipboard

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

#sidebar {
    width: 34;
    height: 100%;
    background: $ga-bg;
    padding: 1 2;
    border-right: solid $ga-alt-bg;
}
#sidebar.-hidden, #sidebar.-narrow { display: none; }

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
#planbar {
    display: none;
    height: 5;
    max-height: 5;
    background: $ga-sel-bg;
    padding: 0 1;
    margin: 0 0 1 0;
    border-left: thick $ga-green;
}

/* `└ Tip:` footer — one dim row, never grows. */
#tipbar {
    height: 1;
    background: $ga-bg;
    padding: 0 2;
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
.spinner { height: 1; }

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
    selected_label: Optional[str] = None
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
    # Boundary between restored history (≤ idx) and this run (> idx);
    # `/continue` bumps to `len(messages)` so old plan cards don't resurrect.
    plan_scan_baseline: int = 0


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
    ("/btw",      "<question>",       "side question — 不打断主 agent"),
    ("/review",   "[request]",         "in-session 代码审查（直接输出报告）"),
    ("/continue", "[n|name]",         "列出 / 恢复历史会话"),
    ("/cost",     "[all]",            "显示当前会话 token 用量（all = 所有会话）"),
    ("/export",   "clip|<file>|all",  "导出最后回复"),
    ("/restore",  "",                 "恢复上次模型响应日志"),
    ("/reload-keys", "",              "重新加载 mykey.py（不重启）"),
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
                Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, msg: "ChatMessage", *options, **kwargs):
        super().__init__(*options, **kwargs)
        self.msg = msg

    def action_cancel(self) -> None:
        try:
            self.app._cancel_choice(self.msg)
        except Exception:
            pass


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

    def action_paste(self) -> None:
        if self.read_only or self._paste_file_from_clipboard():
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
        if self._paste_file_from_clipboard():
            event.stop(); event.prevent_default(); return
        # Git-bash / mintty fallback: PIL.ImageGrab can't return Image objects
        # in that TTY env, but the OS clipboard does hold the file path the
        # screenshot tool wrote. Treat a single-line, on-disk path as if the
        # file grab had succeeded — same placeholder + `_pastes` entry.
        if self._paste_file_from_text(event.text):
            event.stop(); event.prevent_default(); return
        self._insert_paste_text(event.text)
        event.stop(); event.prevent_default()

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
                  just_done: bool = False, term_width: int = 0) -> Table:
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
        left.append("再按 Ctrl+C 退出", style=f"bold {C_GREEN}")
    elif rewind_armed:
        left.append("再按 Esc 回退", style=f"bold {C_GREEN}")
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
            "stop": self._cmd_stop, "llm": self._cmd_llm, "export": self._cmd_export,
            "restore": self._cmd_restore, "btw": self._cmd_btw, "review": self._cmd_review,
            "continue": self._cmd_continue, "cost": self._cmd_cost,
            "reload-keys": self._cmd_reload_keys,
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

    def compose(self) -> ComposeResult:
        yield Static("", id="topbar")
        with Horizontal(id="body"):
            yield Static("", id="sidebar")
            with Vertical(id="main"):
                yield VerticalScroll(id="messages")
                yield Static("", id="planbar")
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
                # Tip line sits inside #main so it doesn't compete for height
                # with #body's 1fr. Content set at compose so the first frame
                # already shows it.
                yield Static(_tip_line(_random_tip()), id="tipbar")
        yield Static(render_bottombar(), id="bottombar")

    def on_mount(self) -> None:
        self.add_session("main")
        self._system("Welcome to GenericAgent TUI. 按 / 唤起命令面板，Ctrl+N 新建会话。")
        # CSS `#planbar { display: none }` keeps it hidden by default —
        # the renderer flips it on once items materialize.
        self.query_one("#input", InputArea).focus()
        self.set_interval(0.5, self._tick)
        self._patch_auto_scroll_for_selection()
        self._start_plan_watcher()
        self._start_tip_rotator()
        self._apply_responsive_layout()
        # Disable alternate scroll mode (?1007). Textual enables ?1006 SGR mouse but doesn't
        # turn off ?1007, which on macOS Terminal / iTerm2 makes the wheel emit both mouse
        # events and ↑/↓ keys — triggering InputArea history nav.
        try:
            sys.__stdout__.write("\x1b[?1007l"); sys.__stdout__.flush()
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
        self._install_ask_user_hook(sess)
        self._refresh_all()
        return sess

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
        """Override Textual's OSC 52 clipboard (broken on macOS Terminal.app).
        Use pbcopy on macOS, fall back to OSC 52 on other platforms."""
        import sys, subprocess as _sp
        if sys.platform == "darwin":
            try:
                _sp.Popen(["pbcopy"], stdin=_sp.PIPE, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL).communicate(text.encode("utf-8"))
                self._clipboard = text
                return
            except Exception:
                pass
        # Non-macOS or pbcopy failed: fall back to Textual default (OSC 52)
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
        sidebar = self.query_one("#sidebar", Static)
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
            ("Enter",                   "发送"),
            ("Ctrl+J / Ctrl+Enter",     "换行（Shift+Enter 同义）"),
            ("Ctrl+C",                  "停止任务 / 空闲时连按两次退出"),
            ("Ctrl+N",                  "新建会话"),
            ("Ctrl+B",                  "切换侧栏"),
            ("Ctrl+↑ / Ctrl+↓",         "切换会话"),
            ("Ctrl+D",                  "侧栏移除会话"),
            ("Ctrl+O",                  "折叠 / 展开已完成的轮次"),
            ("Ctrl+U",                  "清空输入框"),
            ("Ctrl+V",                  "粘贴（图片优先）"),
            ("↑ / ↓",                   "输入框：浏览发送历史 / 面板内：移动"),
            ("/",                       "唤起命令面板"),
            ("Tab",                     "命令面板可见时补全"),
            ("Esc",                     "取消选择 / 关闭面板 / 关闭帮助"),
            ("Esc Esc",                 "打开回退选择"),
            ("Ctrl+T",                  "切换主题"),
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

    def _finalize_multi_choice(self, msg: ChatMessage, indices: list[int]) -> None:
        """User pressed Enter on a MultiChoiceList.

        - If any picked entry is the free-text sentinel, switch the whole
          message into free-text mode (the user wants to type instead).
        - Otherwise post a `Ready to submit your answers?` confirmation
          card (Submit / Edit answer) before the agent sees it.

        Indices are SelectionList values (set = list index in _mount_message)."""
        picked = [msg.choices[i] for i in indices if 0 <= i < len(msg.choices)]
        if any(v == FREE_TEXT_CHOICE for _, v in picked):
            self._enter_free_text_mode(msg)
            return
        labels = [lbl for lbl, _ in picked]
        joined = "; ".join(labels)
        if not labels: return  # nothing selected → keep the picker up
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
        display = (result_text or label).strip() or label
        msg.selected_label = display
        msg.content = display
        container = self.query_one("#messages", VerticalScroll)
        was_at_bottom = self._at_bottom(container)
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
        del self.sessions[self.current_id]
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
        try:
            sess.agent.abort()
            if sess.status == "running":
                sess.status = "stopping"
            self._system(f"Stop sent to #{sess.agent_id}.")
        except Exception as e:
            self._system(f"Stop failed: {e}")
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
        head = f"选择要恢复的会话 ({len(sessions)} 条 · ↑/↓ 移动，→/Enter 确认，Esc 取消)"
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
            self._plan_mtime.pop(sess.agent_id, None)
            for h in continue_extract(path):
                sess.messages.append(ChatMessage(role=h["role"], content=h["content"]))
            # Baseline past restored history so the scanner ignores the prior
            # session's plan.md; only re-shows on a fresh enter_plan_mode.
            sess.plan_scan_baseline = len(sess.messages)
            try:
                import session_names
                nm = session_names.name_for(path)
                if nm:
                    sess.name = nm
                    if current_log:
                        session_names.migrate(path, current_log)
            except Exception:
                pass
            self._remount_current_session()
            self._refresh_all()
        self.call_after_refresh(_finish)
        return result.splitlines()[0] if result else "✅ 已恢复"

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
        self._reset_terminal_title()
        self.exit()

    def _reset_terminal_title(self) -> None:
        # Send via sys.__stdout__ — see _update_terminal_title for why.
        try:
            out = sys.__stdout__
            out.write("\x1b]0;\x07")
            out.flush()
        except Exception:
            pass

    def on_unmount(self) -> None:
        self._reset_terminal_title()

    # ---------------- agent task + stream ----------------
    def submit_user_message(self, text: str, images: Optional[list[str]] = None, display_text: Optional[str] = None) -> int:
        sess = self.current
        # Free-text ask_user answers go through a 2-step submit-confirm card.
        if self._maybe_intercept_free_text(sess, text):
            return -1
        if sess.status == "running":
            self._system(f"#{sess.agent_id} 正在跑，/stop 后再发。")
            return -1
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
        if not s or s.current_task_id != task_id:
            return
        s.buffer = text
        if done:
            s.status = "idle"
            s.current_display_queue = None
        self._update_assistant(agent_id, text, task_id=task_id, done=done, refresh_chrome=True)
        # End-of-turn re-parse only; mid-stream `[...]` fragments would flash.
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
        msg = ChatMessage(
            role="system", content=head, kind=kind, choices=choices,
            on_select=lambda v: self._answer_ask_user(sess.agent_id, v),
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
        # Detect plan mode: `working['in_plan_mode']` first, fallback to per-
        # session message scan for a `plan_*/plan.md` reference. Strictly
        # per-session via `plan_scan_baseline` to avoid /continue bleed.
        new_items: list = []
        msgs = sess.messages
        base = sess.plan_scan_baseline
        if plan_state.is_active(sess.agent, messages=msgs, start_idx=base):
            path = plan_state.resolve_path(sess.agent, messages=msgs, start_idx=base)
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
            if sess and plan_state.is_active(sess.agent, messages=msgs, start_idx=base):
                self._render_planbar_placeholder(bar, sess)
                return
            self._set_planbar_visible(bar, False); return
        n_done, n_total = plan_state.summary(items)
        complete = plan_state.is_complete(items)
        if complete and sess and sess.plan_complete_since is not None:
            if time.time() - sess.plan_complete_since >= self._PLAN_GRACE_SEC:
                self._set_planbar_visible(bar, False); return
        # 5-row budget: header(1) + step(0/1) + tasks(N) + overflow(0/1).
        step = plan_state.current_step(msgs, start_idx=base)
        budget = 4 - (1 if step else 0)
        ordered = [(c, st) for c, st in items if st != "done"] + \
                  [(c, st) for c, st in items if st == "done"]
        body_lines = budget - 1 if len(ordered) > budget else budget
        shown = ordered[:body_lines]
        overflow = max(0, len(ordered) - body_lines)
        sig = (tuple(shown), overflow, step, bool(complete and sess and sess.plan_complete_since))
        if getattr(bar, "_plan_sig", None) == sig and bar.display: return
        bar._plan_sig = sig
        body = Text()
        head = f"✓ Plan complete ({n_total}/{n_total})\n" if complete else f"📋 Plan ({n_done}/{n_total})\n"
        body.append(head, style=f"bold {C_GREEN}")
        if step:
            body.append("  ▸ ", style=C_GREEN)
            body.append(step[:120] + "\n", style=C_MUTED)
        for c, st in shown:
            if st == "done": body.append("  ✔ ", style=C_GREEN); body.append(c + "\n", style=C_DIM)
            else:            body.append("  ☐ ", style=C_DIM);  body.append(c + "\n", style=C_FG)
        if overflow:
            body.append(f"  ⋮ +{overflow} more", style=C_DIM)
        bar.update(body)
        self._set_planbar_visible(bar, True)

    def _render_planbar_placeholder(self, bar: Static, sess: AgentSession) -> None:
        # Placeholder for armed-but-empty plan mode (pre-first plan.md write).
        import plan_state
        base = sess.plan_scan_baseline
        path = (plan_state._stashed_plan_path(sess.agent)
                or plan_state.find_path_in_messages(sess.messages, start_idx=base)
                or "")
        hint = "/".join(path.replace("\\", "/").rstrip("/").split("/")[-2:]) if path else "plan.md"
        step = plan_state.current_step(sess.messages, start_idx=base)
        sig = ("__placeholder__", hint, step)
        if getattr(bar, "_plan_sig", None) == sig and bar.display: return
        bar._plan_sig = sig
        body = Text()
        body.append("📋 Plan 模式已激活\n", style=f"bold {C_GREEN}")
        if step:
            body.append("  ▸ ", style=C_GREEN)
            body.append(step[:120] + "\n", style=C_MUTED)
        body.append(f"  等待写入 {hint} …", style=C_DIM)
        bar.update(body)
        self._set_planbar_visible(bar, True)

    def _set_planbar_visible(self, bar: Static, visible: bool) -> None:
        # Repaint only on show→hide transition; idle ticks no-op.
        if not visible:
            if not bar.display: return
            bar.display = False
            bar.update(Text())
            bar._plan_sig = None
            return
        if not bar.display: bar.display = True

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
        msgs = sess.messages
        base = sess.plan_scan_baseline
        if not plan_state.is_active(sess.agent, messages=msgs, start_idx=base):
            self._refresh_planbar(); return
        path = plan_state.resolve_path(sess.agent, messages=msgs, start_idx=base)
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
        self.query_one("#topbar", Static).update(
            render_topbar(s.name, s.status, model, tasks_running,
                          fold_mode=self.fold_mode, busy_elapsed=elapsed, effort=effort,
                          sess_elapsed=sess_elapsed, just_done=just_done,
                          term_width=term_w))
        self._ensure_title_timer()
        self._update_terminal_title()

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
        try:
            out = sys.__stdout__
            out.write(f"\x1b]0;{title}\x07")
            out.flush()
        except Exception:
            pass

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
            container.scroll_end(animate=False)

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
            text = _TASKLIST_OPEN_RE.sub(r"\1☐ ", text)
            text = _TASKLIST_DONE_RE.sub(r"\1✔ ", text)
            text = _TOOL_USE_RE.sub(_render_tool_use_block, text)
            text = _META_TAG_RE.sub("", text)
            from io import StringIO
            from rich.console import Console
            render_w = max(1, width - 1)
            buf = StringIO()
            Console(file=buf, width=render_w, force_terminal=True,
                    color_system="truecolor", legacy_windows=False,
                    theme=_markdown_rich_theme(_palette, minimal=(self.theme != "ga-default"))
                    ).print(HardBreakMarkdown(text), end="")
            narrow_raw = buf.getvalue().rstrip("\n")
            t = Text.from_ansi(narrow_raw)
            t.highlight_regex(r"✔[^\n]*", style=C_DIM)
            t.highlight_regex(r"☐", style=C_DIM)
            t.highlight_regex(r"✔", style=C_GREEN)

            wide_buf = StringIO()
            Console(file=wide_buf, width=10000, force_terminal=False,
                    legacy_windows=False).print(HardBreakMarkdown(text), end="")
            wide_raw = wide_buf.getvalue().rstrip("\n")
            narrow_plain = _ANSI_SGR_RE.sub("", narrow_raw)
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

    def _spinner_annotation(self, m) -> Text:
        """Render `⠋ Gerund… (Xm Ys · ↑ N · ↓ M)` for a streaming message.
        ↑/↓ are the latest LLM call's prompt / completion sizes, gated on
        cumulative counters moving past the baselines captured at stream start
        (otherwise the prior turn's tail values leak in on prompt submit).
        """
        out = Text()
        elapsed = int(time.time() - m._stream_started_at) if m._stream_started_at else 0
        last_in, last_out = self._live_call_tokens(m)
        gerund_style = _gerund_color(elapsed, last_in)
        out.append(self._spinner_glyph(), style=gerund_style)
        out.append(f" {self._spinner_gerund(m)}…", style=gerund_style)
        bits = []
        if m._stream_started_at:
            bits.append(_fmt_elapsed(elapsed))
        if last_in > 0 or last_out > 0:
            bits.append(f"↑ {self._humanize_tokens(last_in)} · ↓ {self._humanize_tokens(last_out)}")
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
        shift the line."""
        elapsed, last_in, last_out = m._done_summary or (0, 0, 0)
        verb = self._done_gerund(m)
        out = Text()
        out.append(self._DONE_GLYPH + " ", style=C_GREEN)
        out.append(f"{verb} for {_fmt_elapsed(int(elapsed))}", style=C_DIM)
        if last_in > 0 or last_out > 0:
            out.append("  · ", style=C_DIM)
            out.append(f"↑ {self._humanize_tokens(last_in)} · ↓ {self._humanize_tokens(last_out)}",
                       style=C_DIM)
        return out

    def _capture_done_summary(self, m) -> None:
        """Freeze `(elapsed, last_in, last_out)` once when an assistant message
        transitions done→True. Idempotent — repeat calls are no-ops so re-mounts
        and stream-update passes won't overwrite the snapshot."""
        if m._done_summary is not None or not m.done: return
        elapsed = (time.time() - m._stream_started_at) if m._stream_started_at else 0.0
        last_in, last_out = self._live_call_tokens(m)
        m._done_summary = (elapsed, last_in, last_out)

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
                widget = MultiChoiceList(m, *(Selection(cl, idx) for idx, (cl, _) in enumerate(m.choices)),
                                         classes="picker")
            else:
                widget = ChoiceList(m, classes="picker")
                for cl, _ in m.choices:
                    widget.add_option(Option(cl))
            m._body_widget = widget
            container.mount(widget)
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
                last_widget.update(Text.from_ansi(last_text, style=C_FG))
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
