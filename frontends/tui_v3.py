"""tui_v3 — scrollback-first TUI for GenericAgent, consolidated.

Merged from frontends/tui/ (cjk, clipboard, renderer, protocol, core/sb)
into a single file so the v3 frontend ships as one drop-in module.
Run: `python -m frontends.tui_v3` or `python frontends/tui_v3.py`.
"""
from __future__ import annotations

import atexit, json, logging, os, queue, re, select, shutil, signal, subprocess
import sys, tempfile, termios, threading, time, tty

# Make `frontends/` parent (project root) importable so `from agentmain import …`
# works whether this file is run as `python -m frontends.tui_v3` or directly
# via `python frontends/tui_v3.py`.
_proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_front_dir = os.path.dirname(os.path.abspath(__file__))
for _p in (_proj_root, _front_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentmain import GeneraticAgent
from dataclasses import dataclass
from dataclasses import dataclass, field
from functools import lru_cache
from io import StringIO
from rich.cells import cell_len
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text
from rich.theme import Theme
from typing import Callable


# Module-level `clip` shim: keep sb.py-style `clip.copy(...)` calls
# working without a separate clipboard module — the underlying funcs
# (copy, paste, paste_image) are defined later in this same file.
class _Clip:
    @staticmethod
    def copy(text):       return copy(text)
    @staticmethod
    def paste():          return paste()
    @staticmethod
    def paste_image():    return paste_image()
clip = _Clip()


# ────────────────────────────────────────────────────────────────────────────
# cjk: CJK wrap monkey-patch for Rich
# ────────────────────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)

_CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F), (0x2B740, 0x2B81F), (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF), (0xF900, 0xFAFF), (0x2F800, 0x2FA1F),
    (0x3000, 0x303F), (0x3040, 0x309F), (0x30A0, 0x30FF),
    (0x31F0, 0x31FF), (0xFF00, 0xFFEF), (0xAC00, 0xD7AF),
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _is_wide(ch: str) -> bool:
    try:
        from rich.cells import cell_len
        return cell_len(ch) == 2
    except ImportError:
        return _is_cjk(ch)


def install_cjk_wrap() -> bool:
    """Monkey-patch Rich's word-wrap to handle CJK char-level breaks.
    Returns True on success, False on fallback."""
    try:
        import rich._wrap as wrap_mod
        from rich.cells import cell_len
    except (ImportError, AttributeError) as e:
        log.warning("CJK patch skipped: %s", e)
        return False

    orig_divide = getattr(wrap_mod, 'divide_line', None)
    if orig_divide is None:
        log.warning("CJK patch skipped: Rich lacks divide_line")
        return False

    def _patched_divide_line(text, width, fold=True):
        divides = set()
        line_width = 0
        for i, ch in enumerate(text._text if hasattr(text, '_text') else str(text)):
            char_w = cell_len(ch) if ch != '\n' else 0
            if line_width + char_w > width and line_width > 0:
                if _is_wide(ch) or fold:
                    divides.add(i)
                    line_width = char_w
                    continue
            line_width += char_w
            if ch == '\n':
                line_width = 0
        # Merge with original for non-CJK content
        try:
            orig_divides = orig_divide(text, width, fold)
            divides.update(orig_divides)
        except Exception:
            pass
        return sorted(divides)

    try:
        wrap_mod.divide_line = _patched_divide_line
        log.info("CJK wrap patch installed for Rich %s", _rich_version())
        return True
    except Exception as e:
        log.warning("CJK patch failed: %s", e)
        return False


def _rich_version() -> str:
    try:
        from importlib.metadata import version
        return version('rich')
    except Exception:
        return '?'


# ────────────────────────────────────────────────────────────────────────────
# clipboard: cross-platform copy/paste via native tools
# ────────────────────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)

_TEMP_DIR = os.path.join(tempfile.gettempdir(), 'genericagent_tui')
_platform = sys.platform
_HAS_WAYLAND = bool(os.environ.get('WAYLAND_DISPLAY'))


def _run(cmd: list[str], input: bytes | None = None, timeout: float = 3.0) -> bytes | None:
    try:
        r = subprocess.run(cmd, input=input, capture_output=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        log.debug("clipboard cmd %s failed: %s", cmd, e)
        return None


def copy(text: str) -> bool:
    data = text.encode('utf-8')
    if _platform == 'darwin':
        return _run(['pbcopy'], input=data) is not None
    if _platform == 'win32':
        return _run(['clip.exe'], input=data) is not None
    if _HAS_WAYLAND and shutil.which('wl-copy'):
        return _run(['wl-copy'], input=data) is not None
    if shutil.which('xclip'):
        return _run(['xclip', '-selection', 'clipboard'], input=data) is not None
    if shutil.which('xsel'):
        return _run(['xsel', '--clipboard', '--input'], input=data) is not None
    log.warning("No clipboard tool found")
    return False


def paste() -> str | None:
    out: bytes | None = None
    if _platform == 'darwin':
        out = _run(['pbpaste'])
    elif _platform == 'win32':
        out = _run(['powershell', '-NoProfile', '-Command', 'Get-Clipboard'])
    elif _HAS_WAYLAND and shutil.which('wl-paste'):
        out = _run(['wl-paste', '--no-newline'])
    elif shutil.which('xclip'):
        out = _run(['xclip', '-selection', 'clipboard', '-o'])
    elif shutil.which('xsel'):
        out = _run(['xsel', '--clipboard', '--output'])
    if out is not None:
        return out.decode('utf-8', errors='replace')
    return None


def paste_image() -> str | None:
    """Save clipboard image to temp file, return path or None."""
    os.makedirs(_TEMP_DIR, exist_ok=True)
    import time
    path = os.path.join(_TEMP_DIR, f'clip_{int(time.time()*1000)}.png')
    ok = False
    if _platform == 'darwin':
        script = (
            'use framework "AppKit"\n'
            'set pb to current application\'s NSPasteboard\'s generalPasteboard()\n'
            'set imgData to pb\'s dataForType:"public.png"\n'
            'if imgData is missing value then error "no image"\n'
            'imgData\'s writeToFile:"' + path + '" atomically:true\n'
        )
        ok = _run(['osascript', '-e', script], timeout=5.0) is not None
    elif _HAS_WAYLAND and shutil.which('wl-paste'):
        data = _run(['wl-paste', '-t', 'image/png'])
        if data:
            with open(path, 'wb') as f:
                f.write(data)
            ok = True
    elif shutil.which('xclip'):
        data = _run(['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'])
        if data and len(data) > 8:
            with open(path, 'wb') as f:
                f.write(data)
            ok = True
    return path if ok and os.path.isfile(path) else None


def _cleanup():
    if os.path.isdir(_TEMP_DIR):
        shutil.rmtree(_TEMP_DIR, ignore_errors=True)

atexit.register(_cleanup)


# ────────────────────────────────────────────────────────────────────────────
# renderer: markdown / ANSI sanitisation / fold
# ────────────────────────────────────────────────────────────────────────────

# Comprehensive ANSI sanitization — matches v2's thoroughness
_ANSI_INCOMPLETE_RE = re.compile(r'\x1b\[[0-9;]*$')
_ANSI_DEC_PRIVATE_RE = re.compile(r'\x1b\[\?[0-9;]*[a-zA-Z]')
_ANSI_OSC_RE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?')
_ANSI_MODE_SET_RE = re.compile(r'\x1b[=>][0-9]*')
# Keep SGR (color) codes, strip everything else
_ANSI_SGR_RE = re.compile(r'\x1b\[[0-9;]*m')

_TURN_MARKER_RE = re.compile(r'\*\*LLM Running \(Turn (\d+)\).*?\*\*')
_META_TAG_RE = re.compile(r'<(?:thinking|summary|tool_use|file_content)>.*?</(?:thinking|summary|tool_use|file_content)>', re.DOTALL)
_TOOL_USE_BLOCK_RE = re.compile(r'```json\s*\{[^}]*"tool_name"[^}]*\}\s*```', re.DOTALL)
_TOOL_USE_TAG_RE = re.compile(r'<tool_use>\s*\{.*?"tool_name"\s*:\s*"([^"]+)".*?\}\s*</tool_use>', re.DOTALL)
_SUMMARY_RE = re.compile(r'<summary>\s*(.*?)\s*</summary>', re.DOTALL)
_QUAD_BACKTICK_RE = re.compile(r'(`{4,})')
_ASK_USER_RE = re.compile(r'"tool_name"\s*:\s*"ask_user".*?"question"\s*:\s*"([^"]*)"', re.DOTALL)


@dataclass
class FoldSegment:
    title: str
    body: str
    turn: int
    is_last: bool = False


@dataclass
class Block:
    """A unit of finalized scrollback history, stored as SOURCE (not rendered
    lines). Resize replays each block through its renderer at the new width,
    so width-baked structures (chip boxes, banner box) reflow correctly. The
    actual scrollback bytes above the viewport stay frozen at the old width —
    that's a terminal physics constraint — but the viewport and everything
    new flows correctly."""
    kind: str          # 'user' | 'assistant' | 'plain' | 'banner'
    source: str        # source text (or '' for banner — regenerated on demand)
    tool_n: int = 0    # tool count cached at last render (for stable tids)


def sanitize_ansi(text: str) -> str:
    """Strip non-SGR ANSI escapes and incomplete sequences from streaming chunks."""
    text = _ANSI_DEC_PRIVATE_RE.sub('', text)
    text = _ANSI_OSC_RE.sub('', text)
    text = _ANSI_MODE_SET_RE.sub('', text)
    text = _ANSI_INCOMPLETE_RE.sub('', text)
    return text


def _render_checkboxes(text: str) -> str:
    """Convert markdown task lists to visual checkboxes."""
    text = re.sub(r'^(\s*[-*+]\s)\[ \]', r'\1☐', text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*[-*+]\s)\[x\]', r'\1☑', text, flags=re.MULTILINE | re.IGNORECASE)
    return text


def strip_meta_tags(text: str) -> str:
    """Strip internal tags, render tool_use as readable summaries."""
    def _tool_replace(m):
        name = m.group(1)
        if name == 'ask_user':
            q_match = _ASK_USER_RE.search(m.group(0))
            if q_match:
                return f'> {q_match.group(1)}'
        return f'🔧 {name}'
    text = _TOOL_USE_TAG_RE.sub(_tool_replace, text)
    text = _META_TAG_RE.sub('', text)
    text = _TOOL_USE_BLOCK_RE.sub('', text)
    text = _render_checkboxes(text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _extract_title(text: str, max_len: int = 72) -> str:
    m = _SUMMARY_RE.search(text)
    if m:
        title = m.group(1).strip()
    else:
        first = text.strip().split('\n')[0] if text.strip() else ''
        title = re.sub(r'^[#*>\-\s]+', '', first).strip()
    if len(title) > max_len:
        title = title[:max_len - 1] + '…'
    return title or '...'


def fold_segments(text: str) -> list[FoldSegment]:
    """Split agent response into per-turn fold segments."""
    if not text:
        return []
    cleaned = _QUAD_BACKTICK_RE.sub(lambda m: '~' * len(m.group(1)), text)
    parts = _TURN_MARKER_RE.split(cleaned)
    if len(parts) <= 1:
        return [FoldSegment(title=_extract_title(text), body=text, turn=1, is_last=True)]
    segments: list[FoldSegment] = []
    if parts[0].strip():
        segments.append(FoldSegment(title=_extract_title(parts[0]), body=parts[0], turn=0))
    for i in range(1, len(parts), 2):
        turn_num = int(parts[i]) if i < len(parts) else len(segments) + 1
        body = parts[i + 1] if i + 1 < len(parts) else ''
        body = body.replace('~' * 4, '````')
        segments.append(FoldSegment(title=_extract_title(body), body=body, turn=turn_num))
    if segments:
        segments[-1].is_last = True
    return segments


# Render cache: (content_hash, width) -> rendered object
_render_cache: dict[tuple[int, int], object] = {}
_CACHE_MAX = 200


class HardBreakMarkdown(Markdown):
    """Markdown that treats softbreaks as hardbreaks, preserving code blocks."""
    def __init__(self, markup: str, **kwargs):
        lines = []
        in_code = False
        for line in markup.split('\n'):
            stripped = line.strip()
            if stripped.startswith('```'):
                in_code = not in_code
            if in_code:
                lines.append(line)
            else:
                lines.append(line + '  ')
        super().__init__('\n'.join(lines), **kwargs)


def _markdown_to_text(cleaned: str, width: int) -> Text:
    """Render Markdown to a CONCRETE Text (v2 approach). A Textual Static holding
    a live rich.markdown.Markdown does not re-composite reliably when scrolled
    past the viewport (height measurement is unstable → frozen/blank scroll);
    a pre-rendered Text has a fixed line count and scrolls correctly."""
    from io import StringIO
    from rich.console import Console
    buf = StringIO()
    Console(file=buf, width=max(1, width), force_terminal=True,
            color_system='truecolor', legacy_windows=False
            ).print(HardBreakMarkdown(cleaned), end='')
    return Text.from_ansi(buf.getvalue().rstrip('\n'))


def render_message(text: str, role: str = 'assistant', width: int = 0) -> Text:
    """Render a message to a concrete Text. width<=0 → provisional plain text
    (the widget re-renders via on_resize once its real width is known)."""
    cleaned = strip_meta_tags(text) if role == 'assistant' else text
    if not cleaned.strip():
        cleaned = '...'
    if role == 'system':
        return Text(cleaned, style='dim')
    if width <= 0:
        return Text(cleaned)
    key = (hash(cleaned), width)
    cached = _render_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = _markdown_to_text(cleaned, width)
    except Exception:
        result = Text(cleaned)
    if len(_render_cache) >= _CACHE_MAX:
        for k in list(_render_cache.keys())[:_CACHE_MAX // 4]:
            _render_cache.pop(k, None)
    _render_cache[key] = result
    return result


# ────────────────────────────────────────────────────────────────────────────
# protocol: AgentBridge + typed events over display_queue
# ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StreamEvent:
    text: str
    turn: int = 0
    source: str = "user"

@dataclass(frozen=True)
class DoneEvent:
    text: str
    turn: int = 0
    source: str = "user"
    outputs: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class AskUserEvent:
    question: str
    candidates: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class SystemEvent:
    text: str

@dataclass(frozen=True)
class ErrorEvent:
    message: str
    exception: Exception | None = None

AgentEvent = StreamEvent | DoneEvent | AskUserEvent | SystemEvent | ErrorEvent

_HOOK_KEY = '_tui_v3_ask_user'


def _extract_ask_user(ctx: dict | None) -> AskUserEvent | None:
    er = (ctx or {}).get('exit_reason') or {}
    if er.get('result') != 'EXITED':
        return None
    payload = er.get('data') or {}
    if payload.get('status') != 'INTERRUPT' or payload.get('intent') != 'HUMAN_INTERVENTION':
        return None
    data = payload.get('data') or {}
    return AskUserEvent(
        question=data.get('question', ''),
        candidates=data.get('candidates', []),
    )


class AgentBridge:
    """Wraps GenericAgent for the TUI. One bridge per session."""

    def __init__(self, llm_no: int = 0):
        self.agent = GeneraticAgent()
        self.agent.llm_no = llm_no
        if llm_no and hasattr(self.agent, 'llmclients') and self.agent.llmclients:
            self.agent.llmclient = self.agent.llmclients[llm_no % len(self.agent.llmclients)]
        self.agent.inc_out = True
        self.agent.verbose = True
        self.ask_user_queue: queue.Queue[AskUserEvent] = queue.Queue()
        self._install_hook()
        self._healthy = True
        self._init_error: str | None = None
        if not getattr(self.agent, 'llmclient', None):
            self._healthy = False
            self._init_error = 'No LLM configured — check mykey.py'
        self._runner = threading.Thread(target=self._run_safe, daemon=True, name=f'ga-tui-agent')
        self._runner.start()

    def _run_safe(self):
        try:
            self.agent.run()
        except Exception as e:
            self._healthy = False
            self._init_error = str(e)

    def _install_hook(self):
        if not hasattr(self.agent, '_turn_end_hooks'):
            self.agent._turn_end_hooks = {}
        self.agent._turn_end_hooks[_HOOK_KEY] = self._on_turn_end

    def _on_turn_end(self, ctx: dict):
        ev = _extract_ask_user(ctx)
        if ev:
            self.ask_user_queue.put(ev)

    def submit(self, query: str, images: list | None = None) -> queue.Queue:
        return self.agent.put_task(query, source='user', images=images)

    def abort(self):
        self.agent.abort()

    @property
    def is_running(self) -> bool:
        return self.agent.is_running

    @property
    def llm_name(self) -> str:
        try:
            return self.agent.get_llm_name()
        except Exception:
            return '?'

    def list_llms(self) -> list[tuple[int, str, bool]]:
        return self.agent.list_llms()

    def switch_llm(self, n: int):
        self.agent.next_llm(n)

    def drain_display_queue(self, dq: queue.Queue, timeout: float = 0.25):
        """Generator: yields typed events from a display_queue."""
        while True:
            try:
                item = dq.get(timeout=timeout)
            except queue.Empty:
                yield None
                continue
            if not isinstance(item, dict):
                continue
            if 'done' in item:
                yield DoneEvent(
                    text=item['done'],
                    turn=item.get('turn', 0),
                    source=item.get('source', 'user'),
                    outputs=item.get('outputs', []),
                )
                break
            if 'next' in item:
                yield StreamEvent(
                    text=item['next'],
                    turn=item.get('turn', 0),
                    source=item.get('source', 'user'),
                )


# ────────────────────────────────────────────────────────────────────────────
# sb: scrollback-first TUI core (input, paint, flow, ask, /verbose, …)
# ────────────────────────────────────────────────────────────────────────────

# Prose hierarchy via ATTRIBUTES only (bold/italic/underline) — NO dim for body
# content (dim on white = unreadable grey). Code keeps a LIGHT syntax theme so
# it stays dark/legible on the white assistant surface.
_MD_THEME = Theme({
    'markdown.h1': 'bold underline', 'markdown.h2': 'bold underline',
    'markdown.h3': 'bold', 'markdown.h4': 'bold',
    'markdown.h5': 'bold', 'markdown.h6': 'bold',
    'markdown.strong': 'bold', 'markdown.em': 'italic',
    'markdown.code': 'reverse', 'markdown.code_block': 'none',
    'markdown.block_quote': 'italic', 'markdown.hr': 'none',
    'markdown.link': 'underline', 'markdown.link_url': 'underline',
    'markdown.item.bullet': 'bold',
}, inherit=True)


PROMPT = '❯ '
CONT = '  '
# macOS Terminal.app quantises ALL truecolor escapes to their nearest 256-color
# slot, and the slot it picks for #5e6ad2 (iTerm lavender) is 62/#5f5fd7 — that's
# the "blue" border the user sees. It also renders \x1b[2m as a heavy 30%-opacity
# multiply instead of the gentle blend iTerm does — that's the "heavy shadow".
# Branching on TERM_PROGRAM lets iTerm keep its truecolor + dim look, while
# Apple_Terminal uses pinned 256-color slots that match iTerm's RENDERED result.
_IS_APPLE_TERMINAL = os.environ.get('TERM_PROGRAM') == 'Apple_Terminal'
_RST = '\x1b[0m'
if _IS_APPLE_TERMINAL:
    _DIM = '\x1b[38;5;244m'              # mid-gray — no \x1b[2m, no "shadow"
    _ACCENT = '\x1b[38;5;105m'           # 256-slot light purple, closest to iTerm rendered look
    _BORDER = '\x1b[38;5;146m'           # light lavender
else:
    _DIM = '\x1b[2m'
    _ACCENT = '\x1b[38;2;94;106;210m'    # Linear lavender #5e6ad2
    _BORDER = '\x1b[38;5;146m'
_INK_U = '\x1b[38;5;234m'                # user ink — near-black, strong (as requested)
# Linear surface ladder: user gets its own panel; AI = plain white surface.
_TILE_U = '\x1b[48;5;251m' + _INK_U      # user panel (near-black ink)
_MARK = _ACCENT + '❯' + _RST             # prompt mark — the single accent
_BG_TOK = {str(n) for n in list(range(40, 48)) + [49] + list(range(100, 108))}
_SGR_RE = re.compile(r'\x1b\[([0-9;]*)m')
_CSI_ERASE_RE = re.compile(r'\x1b\[[0-9;?]*[JK]')
_SGR_TOKEN_RE = re.compile(r'\x1b\[[0-9;]*m')


def _tile(s: str, style: str) -> str:
    # re-assert style after every reset so muted-markdown \x1b[0m can't punch
    # a hole in the block; \x1b[K fills to the edge (CJK-safe full-width tile).
    return style + s.replace(_RST, _RST + style) + '\x1b[K' + _RST


def _border(left: str, right: str, width: int, style: str = _BORDER) -> str:
    width = max(1, width)
    if width == 1:
        return style + left + _RST
    return style + left + '─' * max(0, width - 2) + right + _RST


def _strip_bg(s: str) -> str:
    """Drop only BACKGROUND SGR — keep foreground colour (curated syntax/diff
    stays, Linear-style functional colour) but no ugly box behind code."""
    def repl(m: re.Match) -> str:
        toks = m.group(1).split(';') if m.group(1) else ['0']
        out, i = [], 0
        while i < len(toks):
            t = toks[i]
            if t == '48':
                i += 3 if (i + 1 < len(toks) and toks[i + 1] == '5') else \
                     5 if (i + 1 < len(toks) and toks[i + 1] == '2') else 1
                continue
            if t in _BG_TOK:
                i += 1; continue
            out.append(t); i += 1
        return '\x1b[' + ';'.join(out) + 'm' if out else '\x1b[0m'
    return _SGR_RE.sub(repl, s)
_ESC_RE = re.compile(rb'\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b.')
_FILE_REF_RE = re.compile(r'@([\w./\-~]+)')
_PASTE_PH_RE = re.compile(r'\[Pasted text #(\d+) \+\d+ lines\]')
_TURN_MK_RE = re.compile(
    r'\*\*LLM Running \(Turn \d+\)[^\n]*\*\*'   # native live-format marker
    r'|^[ \t]*Turn \d+\s*\.{3,}[ \t]*$',         # plain subagent form on its own line
    re.M)
_TOOL_RE = re.compile(
    r'🛠️ Tool: `([^`]+)`[^\n]*\n'                    # 1 = name
    r'(`{3,})[^\n]*\n(.*?)\n\2[ \t]*\n*'              # 2 = fence delim, 3 = args body
    r'(?:'
    r'(`{5,})[^\n]*\n(.*?)\n\4[ \t]*\n*'              # 4 = result fence (5-bt), 5 = body
    r'|'                                              # ─ OR ─
    r'(.*?)(?=^🛠️ Tool: `|^\*\*LLM Running|^<summary>|\Z)'  # 6 = live exec trace
    r')',
    re.DOTALL | re.MULTILINE)
# Prompted-style tool wrappers GA models emit AS TEXT in saved logs (no
# structured tool_use block). Fold them into chips too so /continue replays
# match live mode. Whitelist = every name in assets/tools_schema.json + the
# native metadata wrappers; user HTML (<div>/<svg>/<a>/<p>/<script>…) stays
# untouched on purpose.
_XML_TOOL_RE = re.compile(
    r'<('
    r'code_run|file_read|file_write|file_patch|'
    r'web_scan|web_execute_js|web_search|'
    r'update_working_checkpoint|start_long_term_update|ask_user|'
    r'tool_use|tool_result|tool_call|all_urls'
    r')>(.*?)</\1>',
    re.DOTALL)


_ACTION_RE = re.compile(
    r'^[ \t]*\[(?:Action|Status|Info|Debug|Warn|Warning|Error)\][ \t]*', re.M)


@dataclass
class ToolRecord:
    id: int
    name: str
    args: str = ''
    result: str = ''
    status: str = '?'          # ok | error | ? — GA emits ✅/❌; no duration
    raw: str = ''


def _tool_status(result: str, trailing: str) -> str:
    """Infer status from GA's emitted markers ONLY. Read-tool results can
    contain ❌ or the word 'error' as ordinary content (a doc on coding rules,
    plan_sop with ⛔/❌ markers, etc.) — those MUST NOT flag the chip red."""
    s = result + trailing
    if re.search(r'^\[(?:Status|Error)\][^\n]*(?:fail|error|❌)', s, re.I | re.M):
        return 'error'
    if re.match(r'^(?:Error[:\s]|Exception[:\s]|Traceback|❌|⛔)', s.lstrip(), re.I):
        return 'error'
    if '✅' in s or '成功' in s or s.strip():
        return 'ok'
    return '?'


_BOLD = '\x1b[1m'
_OK = '\x1b[38;5;71m'      # functional green (Linear-muted)
_ERR = '\x1b[38;5;167m'    # functional red
_CHIP_RE = re.compile(r'^▸ t(\d+) (.+?) · (ok|error|\?)$')


def _arg_hint(name: str, args: str, body: str) -> str:
    """Pluck a useful one-line hint from a tool's args. agent_loop:40's
    `.replace('\\n','\n')` un-escapes newlines inside JSON string values so
    json.loads fails on multi-line scripts; regex fallback extracts the first
    priority field. When args parse to empty/no-useful-field, return '' —
    DON'T fall to body; the chip's result preview handles that and showing
    `{"status":…}` as a hint is just noise."""
    src = ''
    if args:
        try:
            d = json.loads(args)
            if isinstance(d, dict):
                for k in ('command', 'script', 'path', 'file_path', 'url', 'query', 'question'):
                    v = d.get(k)
                    if isinstance(v, str) and v.strip(): src = v; break
                if not src:
                    for v in d.values():
                        if isinstance(v, str) and v.strip(): src = v; break
        except Exception:                                  # un-escaped \n → invalid JSON
            m = re.search(
                r'"(command|script|path|file_path|url|query|question)"\s*:\s*"([^"\n]*)',
                args)
            if m: src = m.group(2)
    elif body:                                              # only when args is empty
        src = body                                          # (xrepl path for XML tools)
    src = src.split('\n', 1)[0].strip()
    if name in ('file_read', 'file_write', 'file_patch') and '/' in src:
        src = '…/' + src.rsplit('/', 1)[1]
    return src[:60]


_CHIP_PLACEHOLDER_RE = re.compile(r'(?:^|\n)▸ t(\d+) ([^\n]+?) · (ok|error|\?)(?:\n|$)')
_META_LINE_RE = re.compile(
    r'^[ \t]*\[(?:Action|Status|Info|Debug|Warn|Warning|Error|Stdout|Stderr)\]')


def _result_preview(result: str, max_rows: int, row_w: int) -> list[str]:
    """First few content lines from a tool result (cc-style hanging content
    preview), skipping GA's [Action]/[Status]/[Stdout] meta markers. If the
    result is a JSON envelope (common in replayed code_run/web_* results),
    unwrap the meaningful field so the preview shows the actual content
    instead of `{"status": ...}` serialization noise. Each returned line is
    ≤ row_w cells — long lines truncated with '…' (one physical row each)."""
    if not result:
        return []
    s = result.strip()
    if s.startswith('{') and s.endswith('}'):
        try:
            d = json.loads(s)
            if isinstance(d, dict):
                for k in ('stdout', 'output', 'result', 'content', 'text'):
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        result = v
                        break
        except Exception:
            pass
    lines = [ln for ln in result.split('\n') if not _META_LINE_RE.match(ln)]
    while lines and not lines[0].strip(): lines.pop(0)
    while lines and not lines[-1].strip(): lines.pop()
    if not lines:
        return []
    out = []
    for ln in lines[:max_rows]:
        ln = _term_safe_text(ln)
        if row_w and cell_len(ln) > row_w:
            ln = _clip_cells(ln, max(1, row_w - 1)) + '…'
        out.append(ln)
    rest = len(lines) - max_rows
    if rest > 0:
        out.append(f'… +{rest} more')
    return out


def _chip_box(tid_str: str, combo: str, st: str, w: int, result: str = '') -> list[str]:
    """Tool chip rendered as a fully-enclosed Linear-ish box:
       ╭─ name  ✓ ok  ·tN ─────────╮
       │ hint chunk (CJK-safe wrap) │
       │ chunk 2 if it wraps        │
       ╰────────────────────────────╯
    Every emitted string has visible width == inner (one physical terminal
    row, no soft-wrap drift). fg-only SGR so _strip_bg / native copy stay
    clean. Caller MUST bypass Rich Markdown for these — see _render_assistant."""
    parts = combo.split(' ', 1)
    name = parts[0]
    hint = parts[1].strip() if len(parts) > 1 else ''
    sti, stcol = (('✓ ok', _OK) if st == 'ok' else
                  ('✕ error', _ERR) if st == 'error' else ('· …', _DIM))
    tag = f'·t{tid_str}'
    inner = max(1, w)
    if inner < 24:
        head = f'{name} {sti} {tag}'
        out = [stcol + _clip_cells(head, inner) + _RST]
        body_rows: list[str] = []
        if hint:
            body_rows.extend(_wrap_cells(hint, inner) or [''])
        body_rows.extend(_result_preview(result, 3, inner))
        out.extend(_DIM + _clip_cells(row, inner) + _RST for row in body_rows)
        return out
    name_max = max(1, inner - 10 - cell_len(sti) - cell_len(tag))
    if cell_len(name) > name_max:
        name = _clip_cells(name, name_max)
    header_plain = f' {name}  {sti}  {tag} '
    fill = max(1, inner - 3 - cell_len(header_plain))
    header_c = (' ' + _BOLD + name + _RST + '  ' + stcol + sti + _RST +
                '  ' + _DIM + tag + _RST + ' ')
    top = _ACCENT + '╭─' + _RST + header_c + _ACCENT + '─' * fill + '╮' + _RST
    bot = _border('╰', '╯', inner, _ACCENT)
    content_w = max(1, inner - 4)
    body_rows: list[str] = []
    if hint:                                  # what was called (args)
        body_rows.extend(_wrap_cells(hint, content_w) or [''])
    body_rows.extend(_result_preview(result, 4, content_w))   # what came back
    if not body_rows:
        return [top, bot]
    out = [top]
    for ch in body_rows:
        pad = content_w - cell_len(ch)
        out.append(_ACCENT + '│' + _RST + ' ' + _DIM + ch + _RST +
                   ' ' * pad + ' ' + _ACCENT + '│' + _RST)
    out.append(bot)
    return out


# Slash-command spec for the `/` hint + Tab completion (only commands _cmd
# actually services). Kept here so the hint never drifts from the dispatcher.
_CMDS = [
    ('/help', '', '命令一览'),
    ('/llm', '[N]', '列出/切换 LLM'),
    ('/btw', '<问>', '旁问·不污染主上下文'),
    ('/review', '[范围]', '代码审查'),
    ('/rewind', '[N]', '回退 N 轮上下文'),
    ('/continue', '[N]', '列出/恢复历史会话'),
    ('/clear', '', '清空上下文'),
    ('/cost', '', 'token 用量'),
    ('/verbose', '', '工具调用审计'),
    ('/export', '', '导出最后回答'),
    ('/stop', '', '中止当前任务'),
    ('/quit', '', '退出'),
]


def _heat(el: float) -> str:
    """Patience heat for the running spinner (ported from v2 _HEAT_RAMP):
    cool mint → amber → orange → red as the wait grows."""
    return ('\x1b[38;2;170;232;170m' if el < 20 else
            '\x1b[38;2;212;167;44m' if el < 60 else
            '\x1b[38;2;220;107;31m' if el < 180 else
            '\x1b[1m\x1b[38;2;255;44;44m')


# Rotating gerund pool — the spinner's word cycles every ~6 s so a long wait
# feels alive (small-pet companion vibe) instead of stuck on one phrase.
_GERUNDS = ('思考中', '推敲中', '琢磨中', '梳理中', '拆解中', '校对中',
            '回想中', '揣摩中', '探查中', '抽丝剥茧', '串珠成链',
            '蒸馏提纯', '拨云见日', '排兵布阵', '溯本求源', '修桥铺路')


def _gerund(el: float) -> str:
    return _GERUNDS[int(el // 6) % len(_GERUNDS)]


# Pet faces, 4-frame cycle per heat tier so the face blinks/winks every ~1.6s
# (frame ticks every 0.4s in _ticker). Mood escalates with patience burn:
# happy → focused → sleepy → stressed.
_PETS = (
    ('(•‿•)', '(•‿•)', '(•‿•)', '(-‿-)'),   # <20s   calm, occasional blink
    ('(•_•)', '(•_-)', '(•_•)', '(-_•)'),   # <60s   focused, alternating wink
    ('(˘_˘)', '(˘_˘)', '(-_-)', '(˘_˘)'),   # <180s  sleepy, half-closed
    ('(>_<)', '(@_@)', '(>_<)', '(T_T)'),   # ≥180s  stressed (concerned!)
)


def _pet(el: float, frame: int) -> str:
    tier = 0 if el < 20 else 1 if el < 60 else 2 if el < 180 else 3
    pool = _PETS[tier]
    return pool[frame % len(pool)]
_BP_START = b'\x1b[200~'
_BP_END = b'\x1b[201~'
_SPIN = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _w(s: str) -> None:
    os.write(1, s.encode('utf-8', 'replace'))


def _esc_repl(m: re.Match) -> bytes:
    s = m.group(0)
    if s == b'\x1b[A':
        return b'\x10'   # ↑ → internal prev-history / cursor-up
    if s == b'\x1b[B':
        return b'\x0e'   # ↓ → internal next-history / cursor-down
    if s == b'\x1b[D':
        return b'\x02'   # ← → internal cursor-left
    if s == b'\x1b[C':
        return b'\x06'   # → → internal cursor-right
    if s == b'\x1b[1;2D':
        return b'\x1e'   # Shift+← → extend selection left
    if s == b'\x1b[1;2C':
        return b'\x1f'   # Shift+→ → extend selection right
    if s == b'\x1b[1;2A':
        return b'\x1c'   # Shift+↑ → extend selection up
    if s == b'\x1b[1;2B':
        return b'\x1d'   # Shift+↓ → extend selection down
    if s in (b'\x1b[27;2;13~', b'\x1b[13;2u'):
        return b'\n'      # Shift+Enter (modifyOtherKeys / kitty) → newline
    return b''            # swallow every other escape sequence


def _holdback(rb: bytes, marker: bytes) -> int:
    """Length of the trailing suffix of rb that is a strict prefix of marker."""
    for k in range(min(len(marker) - 1, len(rb)), 0, -1):
        if marker.startswith(rb[-k:]):
            return k
    return 0


def _term() -> tuple[int, int]:
    try:
        c = os.get_terminal_size(1); return max(1, c.columns), max(3, c.lines)
    except OSError:
        return 80, 24


def _render(text: str, width: int, markdown: bool) -> list[str]:
    width = max(1, width)
    buf = StringIO()
    Console(file=buf, width=width, force_terminal=True, color_system='truecolor',
            legacy_windows=False, theme=_MD_THEME).print(
        HardBreakMarkdown(text, code_theme='xcode') if markdown else Text(text),
        end='')
    out = _strip_bg(buf.getvalue()).split('\n')
    if out and out[-1] == '':
        out.pop()
    return out or ['']


def _fit_rows(line: str, width: int) -> list[str]:
    """Fold an already-rendered ANSI line without changing its SGR styling."""
    width = max(1, width)
    erase = '\x1b[K' if _CSI_ERASE_RE.search(line) else ''
    safe = _CSI_ERASE_RE.sub('', _term_safe_text(line))
    rows: list[str] = []
    cur = ''
    cur_w = 0
    active = ''
    parts = _SGR_TOKEN_RE.split(safe)
    sgrs = _SGR_TOKEN_RE.findall(safe)
    for idx, part in enumerate(parts):
        for ch in part:
            ch_w = cell_len(ch)
            if ch_w > width:
                ch = '·'
                ch_w = 1
            if cur_w + ch_w > width and cur_w > 0:
                rows.append(cur + erase + (_RST if active else ''))
                cur = active
                cur_w = 0
            cur += ch
            cur_w += ch_w
        if idx < len(sgrs):
            code = sgrs[idx]
            cur += code
            active = '' if code == _RST else active + code
    rows.append(cur + erase)
    return rows or ['']


def _clip_ansi_cells(s: str, width: int) -> str:
    width = max(0, width)
    if width == 0:
        return ''
    safe = _CSI_ERASE_RE.sub('', _term_safe_text(s))
    cur = ''
    cur_w = 0
    active = ''
    parts = _SGR_TOKEN_RE.split(safe)
    sgrs = _SGR_TOKEN_RE.findall(safe)
    for idx, part in enumerate(parts):
        for ch in part:
            ch_w = cell_len(ch)
            if ch_w > width:
                ch = '·'
                ch_w = 1
            if cur_w + ch_w > width:
                return cur + (_RST if active else '')
            cur += ch
            cur_w += ch_w
        if idx < len(sgrs):
            code = sgrs[idx]
            cur += code
            active = '' if code == _RST else active + code
    return cur


def _tail_fit_rows(lines: list[str], width: int, budget: int) -> list[str]:
    if budget <= 0:
        return []
    out: list[str] = []
    for ln in reversed(lines):
        rows = _fit_rows(ln, width)
        room = budget - len(out)
        if room <= 0:
            break
        if len(rows) > room:
            out[0:0] = rows[-room:]
            break
        out[0:0] = rows
    return out


def _elapsed(s: float) -> str:
    if s < 60:
        return f'{s:.1f}s'
    m, sec = divmod(int(s), 60); return f'{m}:{sec:02d}'


def _human(n: int) -> str:
    return f'{n / 1e6:.1f}M' if n >= 1e6 else f'{n / 1e3:.1f}k' if n >= 1000 else str(n)


def _wrap_cells(s: str, width: int) -> list[str]:
    """Hard-wrap by DISPLAY width (CJK = 2 cells). Each chunk ≤ width so one
    emitted line == exactly one physical terminal row → row accounting stays
    exact, no soft-wrap drift / ghosting."""
    s = _term_safe_text(s)
    out, cur, cw = [], '', 0
    for ch in s:
        c = cell_len(ch)
        if cw + c > width and cur:
            out.append(cur); cur, cw = ch, c
        else:
            cur += ch; cw += c
    out.append(cur)
    return out


def _clip_cells(s: str, width: int) -> str:
    """Truncate to width display-cells so the line is always one physical row."""
    s = _term_safe_text(s)
    if cell_len(s) <= width:
        return s
    out, cw = '', 0
    for ch in s:
        c = cell_len(ch)
        if cw + c > width:
            break
        out += ch; cw += c
    return out


def _term_safe_text(s: str) -> str:
    """Normalize control chars whose terminal geometry is stateful.

    A literal tab expands according to the current cursor column, while
    ``cell_len("\t")`` reports one cell. That mismatch made tool chips with
    outputs such as ``git remote -v`` physically wrap even though the renderer
    believed each row fit. Keep source text in ToolRecord; normalize only the
    display path.
    """
    return s.replace('\r', '').replace('\t', '    ')


def _indent_rows(rows: list[str], width: int) -> list[str]:
    if width <= 1:
        return rows
    return [' ' + row for row in rows]


def _cost_str(agent) -> str:
    """Context-window usage view (cc/v2 style): used / cap of context_win*3."""
    try:
        from frontends import cost_tracker
        be = agent.llmclient.backend
        cap = cost_tracker.context_window_chars(be)
        used = cost_tracker.current_input_chars(be)
        if cap <= 0:
            return ''
        pct = min(100, used * 100 // cap)
        n = round(pct / 100 * 8)
        bar = '▰' * n + '▱' * (8 - n)
        tot = sum(t.total_tokens for t in cost_tracker.all_trackers().values())
        tok = f' · {_human(tot)} tok' if tot else ''
        return f' │ ctx {bar} {pct}% ({_human(used)}/{_human(cap)}){tok}'
    except Exception:
        return ''


def _rel(mt: float) -> str:
    d = max(0, time.time() - mt)
    if d < 3600:
        return f'{int(d // 60)}m'
    if d < 86400:
        return f'{int(d // 3600)}h'
    return f'{int(d // 86400)}d'


class SB:
    def __init__(self) -> None:
        self.buf = ''; self.pos = 0; self._fd = 0; self._old = None
        self._lk = threading.Lock()
        self._live_rows = 0
        self._stream = ''
        self._sent = 0                  # rendered lines of this msg already in scrollback
        self._live_tail: list[str] = []  # small volatile tail still being redrawn
        self._tools: dict[int, ToolRecord] = {}   # structured tool audit log
        self._tool_base = 0             # id offset; ids fixed at stream time (scrollback immutable)
        self._last_tool_n = 0           # tools seen in the current message render
        self._cur = (0, 1)               # (row in live region, 1-based column) of caret
        self._parked_up = 0              # rows the caret was parked above region bottom
        self._running = False
        self._bridge: AgentBridge | None = None
        self._resized = False
        self._rb = b''; self._tail = b''; self._bp = False; self._pbytes = b''
        self.hist: list[str] = []; self._hi = -1
        self._cwd = os.path.join(os.getcwd(), 'temp')
        self._pstore: dict[int, str] = {}; self._imgs: list[str | None] = []; self._pc = 0
        self._t0 = 0.0; self._spin = 0
        self._painted: list[str] = []
        self._blocks: list[Block] = []                  # block-based scrollback history;
        self._streaming_block: Block | None = None     # the in-flight assistant block
        # Self-pipe for SIGWINCH delivery. PEP 475 makes Python auto-retry
        # os.read on EINTR even with siginterrupt(SIGWINCH, True) — especially
        # under iTerm split panes where the signal can be delivered while the
        # read is mid-syscall and silently dropped. The signal handler writes
        # a byte to this pipe; the main select() polls both stdin and the
        # pipe, so a resize always wakes the loop within select's timeout.
        sr, sw = os.pipe()
        import fcntl as _fcntl
        for fd in (sr, sw):
            fl = _fcntl.fcntl(fd, _fcntl.F_GETFL)
            _fcntl.fcntl(fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
        self._sig_r, self._sig_w = sr, sw
        self._last_render = 0.0
        self._asking: AskUserEvent | None = None
        self._quit = False
        self._cc_t = 0.0                # last bare-Ctrl+C time (arm-to-quit window)
        self._epend = b''               # held trailing ESC (split-read disambiguation)
        self._undo: list[tuple[str, int]] = []   # buffer-edit history for Ctrl+Z
        self._redo: list[tuple[str, int]] = []   # cleared on any new edit
        self._sel: int | None = None             # selection anchor (None=no selection)

    # ── live region ──

    def _goto_top(self) -> None:
        if self._parked_up:                       # undo the caret park first so the
            _w(f'\x1b[{self._parked_up}B')        # 'cursor at region bottom' invariant
            self._parked_up = 0                   # _goto_top relies on holds again
        _w('\r')
        if self._live_rows > 1:
            _w(f'\x1b[{self._live_rows - 1}A')

    def _paint(self, lines: list[str]) -> bool:   # True if it actually repainted
        if lines == self._painted:
            return False
        old = self._live_rows
        self._goto_top()
        last = len(lines) - 1
        for i, ln in enumerate(lines):
            _w('\x1b[2K' + ln + ('\r\n' if i != last else ''))
        if old > len(lines):
            _w('\x1b[J')                       # only when the region shrank
        self._painted = list(lines)
        self._live_rows = len(lines)
        return True

    def _status_line(self, w: int) -> str:
        name = self._bridge.llm_name if self._bridge else '?'
        if self._asking:
            state = '◉ 待答 · Esc 撤回提问'
        elif self._running:
            el = time.time() - self._t0
            tps = ''
            if el >= 1 and self._stream:
                r = len(self._stream) / 4 / el        # ~chars→tokens, rough live rate
                if r >= 0.5:
                    tps = f' · {r:.0f} tok/s'
            state = f'{_gerund(el)} {_elapsed(el)}{tps} · Esc 停'
        elif 0 < time.time() - self._cc_t < 2:
            state = '○ 再按 Ctrl+C 退出'
        else:
            state = '○ 就绪'
        cost = _cost_str(self._bridge.agent) if self._bridge else ''
        return f'[main] {name} │ {state}{cost}'

    def _plan_line(self) -> str | None:
        try:
            from frontends import plan_state
            if not self._bridge or not plan_state.is_active(self._bridge.agent):
                return None
            p = plan_state.resolve_path(self._bridge.agent)
            if not p or not os.path.isfile(p):
                return None
            with open(p, encoding='utf-8', errors='replace') as f:
                items = plan_state.extract(f.read())
            d, tot = plan_state.summary(items)
            return f'Plan {d}/{tot} · {os.path.basename(p)}' if tot else None
        except Exception:
            return None

    @staticmethod
    def _boxln(plain: str, colored: str, w: int) -> str:
        if w < 4:
            return _clip_cells(plain, max(1, w))
        inner = max(0, w - 4)
        plain_fit = _clip_cells(plain, inner)
        colored_fit = _clip_ansi_cells(colored, inner)
        pad = max(0, inner - cell_len(plain_fit))   # cell_len → CJK-safe alignment
        return _BORDER + '│ ' + _RST + colored_fit + ' ' * pad + _BORDER + ' │' + _RST

    def _segs(self, iw: int) -> list[tuple[int, str]]:
        """Flatten buf into visual rows: (abs char start in buf, chunk text).
        One source of truth for both caret math and ←→↑↓ navigation."""
        segs, p = [], 0
        for line in self.buf.split('\n'):
            for ch in _wrap_cells(line, iw) or ['']:
                segs.append((p, ch)); p += len(ch)
            p += 1                              # the '\n' separator
        return segs

    def _seg_at(self, segs: list[tuple[int, str]]) -> tuple[int, int]:
        """(visual row index, char offset within its chunk) for self.pos."""
        for i, (st, ch) in enumerate(segs):
            end = st + len(ch)
            eol = i + 1 == len(segs) or segs[i + 1][0] != end   # \n gap ⇒ row ends here
            if st <= self.pos and (self.pos < end or (self.pos == end and eol)):
                return i, self.pos - st
        return len(segs) - 1, len(segs[-1][1])

    def _cur_v(self, d: int) -> None:
        """↑/↓ roam by VISUAL row (a long single-line paste wraps to many rows
        yet stays one logical line — must still roam). Fall through to history
        only at the text extremes, and only for a single-line draft."""
        segs = self._segs(max(1, _term()[0] - 6))
        i, off = self._seg_at(segs); ni = i + d
        if not 0 <= ni < len(segs):
            if '\n' not in self.buf:
                self._nav_hist(d)
            return
        tcol = cell_len(segs[i][1][:off])       # keep display column
        st, ch = segs[ni]
        o = cw = 0
        for c in ch:
            if cw >= tcol:
                break
            cw += cell_len(c); o += 1
        self.pos = st + o

    def _cmd_matches(self, prefix: str) -> list[tuple[str, str, str]]:
        p = prefix.strip().lower()
        return [c for c in _CMDS if c[0].startswith(p)]

    def _hint_lines(self, w: int) -> list[str]:
        """Live `/`-command suggestion list (v2 palette, scrollback-style)."""
        if self._asking is not None or '\n' in self.buf or not self.buf.startswith('/'):
            return []
        ms = self._cmd_matches(self.buf)
        if not ms or (len(ms) == 1 and ms[0][0] == self.buf.strip()):
            return []
        out = [_DIM + _clip_cells(f'  {n:<10}{a:<7} {d}', w) + _RST for n, a, d in ms[:6]]
        out.append(_DIM + (f'  … 还有 {len(ms) - 6} 个' if len(ms) > 6 else
                           '  Tab 补全 · Enter 执行 · Esc 清空') + _RST)
        return out

    def _tab(self) -> None:
        if self._asking is not None or '\n' in self.buf or not self.buf.startswith('/'):
            return
        ms = self._cmd_matches(self.buf)
        if not ms:
            return
        if len(ms) == 1:
            n, a, _ = ms[0]; self.buf = n + (' ' if a else '')
        else:
            lcp = os.path.commonprefix([m[0] for m in ms])
            if len(lcp) <= len(self.buf):
                return
            self.buf = lcp
        self.pos = len(self.buf)

    def _esc_back(self) -> None:
        """Universal back: cancel ask → clear draft → stop running. Esc has
        NO exit capability — quitting is Ctrl+C×2 or Ctrl+D only. Draft-clear
        comes before running-stop so typing the next prompt mid-run and
        pressing Esc just discards what you typed (no surprise abort); a
        second Esc on the now-empty buffer is what stops the agent."""
        if self._asking is not None:
            if self._running and self._bridge:
                self._bridge.abort()
            if self._bridge:                         # drop any queued ask so _drain
                q = self._bridge.ask_user_queue       # can't re-enter ask-mode after
                try:                                  # the user already cancelled
                    while True:
                        q.get_nowait()
                except queue.Empty:
                    pass
            self._asking = None; self._running = False; self.buf = ''; self.pos = 0
            self._undo.clear(); self._redo.clear(); self._sel = None
            self.commit([_DIM + '✗ 已撤回提问 · 可直接输入或重新发问' + _RST]); return
        if self.buf:
            self._snap()                              # let Ctrl+Z restore the draft
            self.buf = ''; self.pos = 0; self._sel = None; return
        if self._running and self._bridge:
            self._bridge.abort()
            self.commit([_DIM + '⏹ 已请求中止 · Esc' + _RST]); return

    def _ask_card(self, w: int) -> tuple[list[str], int, int]:
        """Single unified card for ask_user: question + candidates + INLINE
        input + hint all inside one accent-bordered box. Returns the same
        triple as _input_box (lines, caret_row_within_lines, caret_col) so
        the caller treats it uniformly."""
        ae = self._asking
        if w < 24:
            rows: list[str] = []
            for ln in (ae.question or '请回答:').strip().split('\n'):
                rows.extend(_DIM + _clip_cells(x, w) + _RST for x in _wrap_cells(ln, w))
            for i, c in enumerate((ae.candidates or [])[:3], 1):
                rows.extend(_clip_cells(x, w) for x in _wrap_cells(f'{i}. {c}', w))
            iw = max(1, w - 2)
            segs = self._segs(iw)
            ci, coff = self._seg_at(segs)
            input_start = len(rows)
            for i, (_st, ch) in enumerate(segs):
                pre = '❯ ' if i == 0 and w >= 3 else '❯' if i == 0 else ''
                rows.append(_clip_cells(pre + ch, w))
            ccol = min(max(1, w), cell_len(('❯ ' if ci == 0 and w >= 3 else '❯' if ci == 0 else '') + segs[ci][1][:coff]) + 1)
            return rows or [''], input_start + ci, ccol
        inner = max(8, w)
        content_w = max(1, inner - 4)
        pending = self._bridge.ask_user_queue.qsize() if self._bridge else 0
        label = '◉ 请回答' + (f'  +{pending} 待答' if pending else '')
        label_max = max(1, inner - 5)
        if cell_len(label) > label_max:
            label = _clip_cells(label, label_max)
        fill = max(1, inner - 3 - cell_len(' ' + label + ' '))
        top = (_ACCENT + '╭─' + _RST + ' ' + _BOLD + _ACCENT + label + _RST +
               ' ' + _ACCENT + '─' * fill + '╮' + _RST)
        bot = _border('╰', '╯', inner, _ACCENT)

        def row(text: str, style: str = '') -> list[str]:
            r = []
            for ch in (_wrap_cells(text, content_w) or ['']):
                pad = content_w - cell_len(ch)
                r.append(_ACCENT + '│' + _RST + ' ' + style + ch + _RST +
                         ' ' * pad + ' ' + _ACCENT + '│' + _RST)
            return r

        rows = [top]
        for ln in (ae.question or '请回答:').strip().split('\n'):
            rows.extend(row(ln, _BOLD))
        if ae.candidates:
            rows.extend(row(''))
            for i, c in enumerate(ae.candidates, 1):
                rows.extend(row(f'  {i}. {c}'))
        rows.extend(row(''))                        # gap between info & input

        # Inline input area (same wrap math as the regular input box: `❯ chunk`
        # inside `│ ... │`, caret column = cell_len(prefix+chunk[:off])+3).
        iw = content_w - 2
        segs = self._segs(iw)
        ci, coff = self._seg_at(segs)
        sel = self._sel_range()
        crow, ccol = len(rows), cell_len('❯ ') + 3
        for i, (st, ch) in enumerate(segs):
            first = i == 0
            pre_p = '❯ ' if first else '  '
            pre_c = (_ACCENT + '❯' + _RST + ' ') if first else '  '
            disp = ch
            if sel:
                lo = max(sel[0] - st, 0); hi = min(sel[1] - st, len(ch))
                if lo < hi:
                    disp = ch[:lo] + '\x1b[7m' + ch[lo:hi] + '\x1b[27m' + ch[hi:]
            pad = content_w - cell_len(pre_p + ch)
            rows.append(_ACCENT + '│' + _RST + ' ' + pre_c + disp +
                        ' ' * pad + ' ' + _ACCENT + '│' + _RST)
            if i == ci:
                crow = len(rows) - 1
                ccol = cell_len(pre_p + ch[:coff]) + 3

        rows.extend(row(''))
        rows.extend(row('↳ 数字选择 / 自由输入 · Esc 撤回', _DIM))
        rows.append(bot)
        return rows, crow, ccol

    def _input_box(self, w: int) -> list[str]:
        """A full-width bordered, padded input box (cc-style). Lives in the
        redraw region only — border glyphs never reach scrollback/copy. The
        caret (row/col) is derived from self.pos so ←→↑↓ edit in place. In
        ask-mode the answer is typed INSIDE the question card itself (one
        unified component) — short-circuit to _ask_card."""
        if self._asking is not None:
            return self._ask_card(w)
        if w < 8:
            iw = max(1, w - 2)
            segs = self._segs(iw)
            ci, coff = self._seg_at(segs)
            rows = []
            for i, (_st, ch) in enumerate(segs):
                pre = '❯ ' if i == 0 and w >= 3 else '❯' if i == 0 else ''
                rows.append(_clip_cells(pre + ch, w))
            ccol = min(max(1, w), cell_len(('❯ ' if ci == 0 and w >= 3 else '❯' if ci == 0 else '') + segs[ci][1][:coff]) + 1)
            return rows or [''], ci, ccol
        top = _border('╭', '╮', w)
        bot = _border('╰', '╯', w)
        segs = self._segs(max(1, w - 6))
        ci, coff = self._seg_at(segs)
        sel = self._sel_range()
        rows = []
        for i, (st, ch) in enumerate(segs):
            first = i == 0
            pre_p = '❯ ' if first else '  '
            pre_c = (_ACCENT + '❯' + _RST + ' ') if first else '  '
            disp = ch
            if sel:                              # reverse-video the selected slice
                lo = max(sel[0] - st, 0); hi = min(sel[1] - st, len(ch))
                if lo < hi:
                    disp = ch[:lo] + '\x1b[7m' + ch[lo:hi] + '\x1b[27m' + ch[hi:]
            rows.append(self._boxln(pre_p + ch, pre_c + disp, w))
        pre = '❯ ' if ci == 0 else '  '
        crow, ccol = ci, cell_len(pre + segs[ci][1][:coff]) + 3
        box = [top] + rows + [bot]
        caret_row = crow + 1                      # +1 for the top border row
        return box, caret_row, ccol

    def _live_lines(self) -> list[str]:
        # Live region MUST fit in (terminal_height − 1). If it overflows, the
        # terminal scrolls and pushes header rows (chip tops, etc.) into the
        # immutable scrollback — they accumulate as visible duplicates because
        # \x1b[J can only clear at/below the cursor, not above. So we build the
        # fixed "after-tail" block first (pet + input box + hint + status + plan),
        # then size the volatile tail to the remaining budget.
        w, h = _term()
        after: list[str] = []
        if self._running and self._asking is None:
            el = time.time() - self._t0
            after.append(' ' + _heat(el) + _pet(el, self._spin) + _RST +
                         '  ' + _DIM + _gerund(el) + '…' + _RST)
        box_start = len(after)
        box, caret_row, caret_col = self._input_box(w)
        after += box
        after += self._hint_lines(w)
        if self._running and self._asking is None:
            lead = _heat(time.time() - self._t0) + _SPIN[self._spin % len(_SPIN)] + ' ' + _RST
            after.append(lead + _DIM + _clip_cells(self._status_line(w), max(2, w - 2)) + _RST)
        else:
            after.append(_DIM + _clip_cells(self._status_line(w), w) + _RST)
        pl = self._plan_line()
        if pl:
            after.append(_DIM + _clip_cells(pl, w) + _RST)
        max_live = max(1, h - 1)
        cur_row = box_start + caret_row
        if len(after) > max_live:
            drop = len(after) - max_live
            after = after[drop:]
            cur_row = max(0, cur_row - drop)
        budget = max(0, max_live - len(after))
        tail = _tail_fit_rows(self._live_tail, w, budget)
        self._cur = (min(len(tail) + cur_row, len(tail) + len(after) - 1), caret_col)
        return tail + after

    def _render_live(self) -> None:
        L = self._live_lines()
        painted = self._paint(L)
        # Always re-park the caret to _cur — even when paint was skipped (a
        # trailing space merges into padding so the line is byte-identical, yet
        # the caret must still advance). _paint→_goto_top already un-parked on
        # the repaint path; on skip the caret is still parked, so come back down.
        if not painted and self._parked_up:
            _w(f'\x1b[{self._parked_up}B')
        row, col = self._cur
        up = (len(L) - 1) - row
        _w('\r' + (f'\x1b[{up}A' if up > 0 else '') + f'\x1b[{col}G')
        self._parked_up = up

    def commit(self, content) -> None:
        """Append finalized history. Accepts either a Block (preferred — keeps
        the source so resize can re-render at the new width) or a pre-rendered
        list[str] (legacy: wrapped as a 'plain' block, which can reflow only
        through _fit_rows — no un-rendering of width-baked structures). For
        assistant blocks, _tool_base is anchored to the cumulative tool count
        of prior blocks so chip tids continue the global sequence and stay
        stable across resize repaints."""
        w = _term()[0]
        if isinstance(content, Block):
            blk = content
            if blk.kind == 'assistant':
                self._tool_base = sum(b.tool_n for b in self._blocks)
            self._blocks.append(blk)
            self._cap_blocks()
            lines = self._render_block(blk, w)
            if blk.kind == 'assistant':
                self._tool_base += blk.tool_n            # advance for next message
        else:
            blk = Block('plain', '\n'.join(content))
            self._blocks.append(blk)
            self._cap_blocks()
            lines = list(content)
        self._emit_lines(lines, w)

    def _cap_blocks(self) -> None:
        if len(self._blocks) > 4000:
            self._blocks = self._blocks[-3000:]
            # streaming block (if any) is the last element by construction —
            # the cap preserves it. Pre-streaming tool_base recompute will pick
            # up the surviving blocks correctly.

    def _emit_lines(self, lines: list[str], w: int) -> None:
        """Write lines to scrollback, wiping any live region currently below."""
        if not lines:
            self._render_live(); return
        emit: list[str] = []
        for ln in lines:
            emit.extend(_fit_rows(ln, w))
        self._goto_top()
        _w('\x1b[J')
        _w('\r\n'.join(emit) + '\r\n')
        self._painted = []; self._live_rows = 0
        self._render_live()

    def _render_block(self, b: Block, w: int) -> list[str]:
        """Render one block at width w. Mutates self._last_tool_n for
        assistant blocks; callers needing stable tids must set _tool_base
        before calling (see _render_all_blocks / _flow)."""
        if b.kind == 'user':
            parts = b.source.split('\n')
            raw = [_MARK + ' ' + parts[0]] + [CONT + p for p in parts[1:]]
            lines = [_tile(' ' + x, _TILE_U) for x in raw]
            lines.append('')
            return lines
        if b.kind == 'assistant':
            body = self._render_assistant(b.source, max(1, w - 2))
            b.tool_n = self._last_tool_n            # cache for tool_base recompute
            return _indent_rows(body, w) + ['']
        if b.kind == 'banner':
            return self._make_banner_lines(w)
        # 'plain': pre-formatted ANSI (system messages, dividers, /help text…)
        out: list[str] = []
        for ln in b.source.split('\n'):
            out.extend(_fit_rows(ln, w))
        return out

    def _render_all_blocks(self, w: int) -> list[str]:
        """Re-render every finalized block at width w with stable tool ids.
        Tool ids are assigned per-block from a running tool_base, so a chip's
        tid stays the same across resize repaints (otherwise /verbose would
        de-sync from what the user sees)."""
        out: list[str] = []
        saved_base = self._tool_base
        tool_base = 0
        for blk in self._blocks:
            if blk.kind == 'assistant':
                self._tool_base = tool_base
                out.extend(self._render_block(blk, w))
                tool_base += blk.tool_n
            else:
                out.extend(self._render_block(blk, w))
        self._tool_base = saved_base
        return out

    def _pre_streaming_tool_base(self) -> int:
        """Cumulative tool count from blocks before the streaming block."""
        total = 0
        for blk in self._blocks:
            if blk is self._streaming_block:
                break
            total += blk.tool_n
        return total

    def _make_banner_lines(self, w: int) -> list[str]:
        """Regenerate the startup banner at the given width — called once at
        run-start AND again on every resize via the 'banner' block kind."""
        d, r = _DIM, _RST
        cwd = os.getcwd().replace(os.path.expanduser('~'), '~')
        name = self._bridge.llm_name if self._bridge else '?'
        rows = [(_ACCENT + '>_' + _RST + ' GenericAgent', '>_ GenericAgent'),
                ('', ''),
                (f'{d}model:{r}       {name}   {d}/llm 切换{r}',
                 f'model:       {name}   /llm 切换'),
                (f'{d}directory:{r}   {cwd}', f'directory:   {cwd}'),
                (f'{d}session:{r}     单会话 · scrollback', 'session:     单会话 · scrollback')]
        top = _border('╭', '╮', w)
        bot = _border('╰', '╯', w)
        lines = ['', top]
        lines += [self._boxln(p, c, w) for c, p in rows]
        lines += [bot, '',
                  f'  {d}Tip: Enter 发送 · Shift+Enter/Ctrl+J 换行 · ↑↓ 历史 · '
                  f'cmd+⌫ 清行 · /help 全部命令{r}', '']
        if self._bridge and not self._bridge._healthy:
            lines.append(f'  {d}⚠ {self._bridge._init_error}{r}'); lines.append('')
        return lines

    def _repaint_screen(self) -> None:
        """Wipe BOTH viewport and scrollback, then replay ALL blocks at the
        current width. Lines that overflow the viewport scroll naturally into
        the fresh scrollback at the new width — so the entire history reflows,
        not just what's visible. \\x1b[3J (clear scrollback) is iTerm/xterm
        specific but widely supported; on terminals that ignore it, viewport
        still re-renders correctly and old scrollback simply stays put.

        The in-flight stream's open portion (after the streaming block's safe
        boundary) re-renders into _live_tail too so mid-stream resize snaps
        to the new width."""
        w, h = _term()
        if self._stream and self._streaming_block is not None:
            safe_src = self._streaming_block.source
            open_src = sanitize_ansi(self._stream)[len(safe_src):]
            saved_base = self._tool_base
            self._tool_base = self._pre_streaming_tool_base() + self._streaming_block.tool_n
            open_body = self._render_assistant(open_src, max(1, w - 2)) if open_src.strip() else []
            self._tool_base = saved_base
            self._live_tail = _indent_rows(open_body[-8:], w)
        live = self._live_lines()
        hist_all = self._render_all_blocks(w)
        # Fold each rendered line to terminal width — long ANSI lines (e.g.
        # plain blocks) reflow via _fit_rows so no soft-wrap drift.
        hist_fit: list[str] = []
        for ln in hist_all:
            hist_fit.extend(_fit_rows(ln, w))
        _w('\x1b[3J\x1b[2J\x1b[H')                # wipe scrollback + viewport
        for ln in hist_fit:                        # write all history; overflow
            _w('\x1b[2K' + ln + '\r\n')           # naturally scrolls to new scrollback
        last = len(live) - 1
        for i, ln in enumerate(live):
            _w('\x1b[2K' + ln + ('\r\n' if i != last else ''))
        self._painted = list(live)
        self._live_rows = len(live)
        row, col = self._cur
        up = (len(live) - 1) - row
        _w('\r' + (f'\x1b[{up}A' if up > 0 else '') + f'\x1b[{col}G')
        self._parked_up = up

    # ── input / paste ──

    # ── undo / selection ──

    def _snap(self) -> None:
        """Push current (buf, pos) onto undo stack before a mutation. Any new
        edit invalidates the redo stack — standard editor behavior."""
        snap = (self.buf, self.pos)
        if not self._undo or self._undo[-1] != snap:
            self._undo.append(snap)
            if len(self._undo) > 200:
                self._undo.pop(0)
        self._redo.clear()

    def _do_undo(self) -> None:
        if not self._undo:
            return
        self._redo.append((self.buf, self.pos))
        self.buf, self.pos = self._undo.pop()
        self._sel = None

    def _do_redo(self) -> None:
        if not self._redo:
            return
        self._undo.append((self.buf, self.pos))
        self.buf, self.pos = self._redo.pop()
        self._sel = None

    def _sel_range(self) -> tuple[int, int] | None:
        if self._sel is None or self._sel == self.pos:
            return None
        return (min(self._sel, self.pos), max(self._sel, self.pos))

    def _sel_start(self) -> None:                  # arm selection at current pos
        if self._sel is None:
            self._sel = self.pos

    def _kill_sel(self) -> bool:
        """Delete the selected range (if any). Returns True if it deleted."""
        r = self._sel_range()
        if not r:
            self._sel = None; return False
        self._snap()
        a, b = r
        self.buf = self.buf[:a] + self.buf[b:]; self.pos = a; self._sel = None
        return True

    def _sel_v(self, d: int) -> None:              # Shift+↑/↓ → extend by visual row
        self._sel_start()
        segs = self._segs(max(1, _term()[0] - 6))
        i, off = self._seg_at(segs); ni = i + d
        if not 0 <= ni < len(segs):
            return                                  # don't fall through to history
        tcol = cell_len(segs[i][1][:off])
        st, ch = segs[ni]
        o = cw = 0
        for c in ch:
            if cw >= tcol: break
            cw += cell_len(c); o += 1
        self.pos = st + o

    def _insert(self, s: str) -> None:
        if not self._kill_sel():                  # _kill_sel snaps when it deletes;
            self._snap()                           # only snap here when it didn't,
        self.buf = self.buf[:self.pos] + s + self.buf[self.pos:]; self.pos += len(s)

    def _handle_clip_paste(self) -> None:
        img = clip.paste_image()
        if img:
            self._pc += 1; self._imgs.append(img); self._insert(f'[Image #{self._pc}]'); return
        txt = clip.paste()
        if txt:
            self._paste_text(txt)

    def _paste_text(self, txt: str) -> None:
        lines = txt.count('\n') + 1
        if lines > 2 or len(txt) > 240:        # fold long / multi-line paste (v2 parity)
            self._pc += 1; self._imgs.append(None); self._pstore[self._pc] = txt
            self._insert(f'[Pasted text #{self._pc} +{lines} lines]')
        else:
            self._insert(txt)

    def _nav_hist(self, d: int) -> None:
        if '\n' in self.buf or not self.hist:
            return
        if self._hi == -1:
            if d == -1:
                self._hi = len(self.hist) - 1
            else:
                return
        else:
            self._hi += d
        if self._hi < 0:
            self._hi = 0
        self._snap()                                  # let Ctrl+Z undo a history recall
        if self._hi >= len(self.hist):
            self._hi = -1; self.buf = ''; self.pos = 0; return
        self.buf = self.hist[self._hi]; self.pos = len(self.buf)

    def _expand(self, raw: str) -> str:
        t = raw
        if '@' in t:
            def _r(m):
                p = m.group(1)
                if os.path.isabs(p) or p.startswith('~'):
                    return m.group(0)
                fp = os.path.normpath(os.path.join(self._cwd, p))
                if not fp.startswith(_ROOT) or not os.path.isfile(fp):
                    return m.group(0)
                with open(fp, encoding='utf-8', errors='replace') as f:
                    return f'[File: {p}]\n{f.read(100_000)}\n[/File]'
            t = _FILE_REF_RE.sub(_r, t)
        for num, content in self._pstore.items():
            t = _PASTE_PH_RE.sub(lambda m: content if int(m.group(1)) == num else m.group(0), t)
        return t

    def _on_enter(self) -> None:
        if self._asking is not None:
            ae = self._asking
            ans = self.buf.strip()
            if ans.isdigit() and 1 <= int(ans) <= len(ae.candidates):
                ans = ae.candidates[int(ans) - 1]
            if not ans:
                return
            self.buf = ''; self.pos = 0; self._asking = None
            self._undo.clear(); self._redo.clear(); self._sel = None
            self._commit_user(f'[答] {ans}')
            self._submit(ans, [])
            try:                                              # parallel sub-agent asks:
                self._asking = self._bridge.ask_user_queue.get_nowait()
            except queue.Empty:                                # if more were queued behind
                pass                                            # this one, surface the next
            return                                              # immediately so the user
                                                                # can answer them in series
        raw = self.buf.strip()
        if not raw:
            return
        self.buf = ''; self.pos = 0; self._hi = -1
        self._undo.clear(); self._redo.clear(); self._sel = None
        if len(self.hist) >= 500:
            self.hist = self.hist[-250:]
        self.hist.append(raw)
        if raw.startswith('/'):
            self._commit_user(raw); self._cmd(raw); return
        if self._running:
            return
        imgs = [p for p in self._imgs if p]
        expanded = self._expand(raw)               # expand paste/file refs FIRST so
        self._commit_user(expanded)                # scrollback shows exactly what
        self._submit(expanded, imgs)               # the agent receives, not the
        self._pstore.clear(); self._imgs.clear()   # `[Pasted text #N]` placeholder

    def _cmd(self, raw: str) -> None:
        assert self._bridge is not None
        parts = raw[1:].split(None, 1)
        name = parts[0].lower() if parts else ''
        arg = parts[1].strip() if len(parts) > 1 else ''
        ag = self._bridge.agent
        idle_only = {'clear', 'export', 'btw', 'review', 'rewind', 'continue'}
        if name in idle_only and self._running:
            self.commit(['运行中,先 /stop 再用该命令']); return
        if name in ('q', 'quit', 'exit'):
            self._quit = True
        elif name in ('stop', 'abort'):
            if self._running:
                self._bridge.abort()
            self.commit(['⏹ 已请求中止' if self._running else '（空闲，无任务）'])
        elif name in ('new', 'switch', 'close', 'rename', 'sessions', 'branch'):
            self.commit([f'/{name}:单会话模式暂不支持(会话管理已暂缓)'])
        elif name == 'continue':
            from frontends import continue_cmd
            sess = continue_cmd.list_sessions(exclude_pid=os.getpid())
            if not arg:
                if not sess:
                    self.commit([_DIM + '  没有可恢复的历史会话' + _RST]); return
                w = _term()[0]
                rows = ['', _DIM + '  恢复历史会话   /continue N 进入' + _RST, '']
                for n, (_p, mt, prev, rnd) in enumerate(sess[:20], 1):
                    body = (prev or '').replace('\n', ' ')[:max(20, w - 22)]
                    rows.append(_DIM + f'{n:>4}  {_rel(mt):>4}  {rnd:>3}轮  ' + _RST + body)
                if len(sess) > 20:
                    rows.append(_DIM + f'     … 另有 {len(sess) - 20} 个较早会话' + _RST)
                rows.append('')
                self.commit(rows); return
            if not arg.isdigit():
                self.commit(['用法: /continue 或 /continue N']); return
            i = int(arg) - 1
            if not (0 <= i < len(sess)):
                self.commit([f'❌ 索引越界(有效 1-{len(sess)})']); return
            path = sess[i][0]
            msg, _ = continue_cmd.restore(ag, path)   # swaps backend.history (full)
            self.commit([_DIM + f'┄┄ 载入 {os.path.basename(path)},以下为完整上文 ┄┄' + _RST])
            for mm in continue_cmd.extract_ui_messages(path):
                c = (mm.get('content') or '').strip()
                if not c:
                    continue
                if mm.get('role') == 'user':
                    self._commit_user(c)
                else:
                    self._commit_assistant(c)
            self.commit([_DIM + f'┄┄ {msg} · 接着说即可 ┄┄' + _RST])
        elif name == 'clear':
            from frontends import continue_cmd
            continue_cmd.reset_conversation(ag)
            _w('\x1b[2J\x1b[H'); self._painted = []; self._live_rows = 0
            self._blocks = []; self._streaming_block = None; self._sent = 0
            self._tool_base = 0; self._tools = {}
            self.commit([_DIM + '🆕 新对话 · 上下文已清空' + _RST])
        elif name == 'rewind':
            n = int(arg) if arg.isdigit() else 1
            be = getattr(getattr(ag, 'llmclient', None), 'backend', None)
            done = 0
            if be is not None and getattr(be, 'history', None):
                while done < n and len(be.history) >= 2:
                    be.history.pop(); be.history.pop(); done += 1
            self.commit([f'↩ 回退 {done} 轮(上下文已退;scrollback 不可改,以此为界)'])
        elif name == 'btw':
            if not arg:
                self.commit(['用法: /btw <旁问>(不污染主上下文)']); return
            threading.Thread(target=self._btw, args=(raw,), daemon=True).start()
            threading.Thread(target=self._ticker, daemon=True).start()
            self._running = True; self._t0 = time.time()
        elif name == 'review':
            from frontends import review_cmd
            dq = queue.Queue()
            prompt = review_cmd.handle(ag, arg, dq)
            if prompt:
                self._submit(prompt, [])
            else:
                try:
                    text = dq.get_nowait().get('done', '')
                    self.commit(Block('assistant', text))   # markdown re-renders on resize
                except queue.Empty:
                    self.commit(['(review 无输出)'])
        elif name == 'llm':
            if arg:
                self._bridge.switch_llm(int(arg) if arg.isdigit() else -1)
                self.commit([f'LLM → {self._bridge.llm_name}'])
            else:
                out = ['LLM 列表(/llm N 切换):']
                for it in self._bridge.list_llms():
                    out.append(f'  {it[0]}. {it[1]}' + ('  ←当前' if len(it) > 2 and it[2] else ''))
                self.commit(out)
        elif name == 'cost':
            from frontends import cost_tracker
            out = ['Token 用量:']
            for tn, st in cost_tracker.all_trackers().items():
                out.append(f'  {tn}: {st}')
            self.commit(out if len(out) > 1 else ['（暂无统计）'])
        elif name == 'export':
            from frontends import export_cmd
            txt = export_cmd.last_assistant_text(ag)
            if not txt:
                self.commit(['（没有可导出的回答）']); return
            p = export_cmd.export_to_temp(txt, 'tui')
            self.commit([f'已导出: {p}'])
        elif name in ('verbose', 'tools', 'trace'):
            self._verbose_view()
        elif name == 'help':
            self.commit(['命令:',
                         '  /help                这个',
                         '  /llm [N]             列出 / 切换 LLM',
                         '  /btw <问>            旁问(不污染主上下文)',
                         '  /review [范围]       代码审查',
                         '  /rewind [N]          回退 N 轮上下文(默认1)',
                         '  /continue [N]        列出 / 恢复历史会话',
                         '  /clear               清空上下文',
                         '  /cost                token 用量',
                         '  /verbose             工具调用审计(↑↓选 Enter切换 c复制 q退)',
                         '  /export              导出最后回答到 temp',
                         '  /stop                中止当前任务',
                         '  /quit                退出',
                         '  Esc                  撤回提问 · 清草稿 · 停任务(不退出)',
                         '  Ctrl+C × 2           退出(空闲时;运行中只 abort 任务)',
                         '  Ctrl+L               强制重画(睡眠唤醒后修复)',
                         '  Ctrl+Z / Ctrl+Y      撤销 / 重做 输入框编辑',
                         '  Shift+←→↑↓           选中文字 (Ctrl+C 复制 / Ctrl+X 剪切 / Ctrl+A 全选)',
                         '  会话类(/new /switch /branch …):单会话已暂缓'])
        else:
            self.commit([f'未知命令 /{name} — /help 看可用命令'])

    def _btw(self, raw: str) -> None:
        from frontends import btw_cmd
        try:
            ans = btw_cmd.handle_frontend_command(self._bridge.agent, raw)
        finally:
            self._running = False
        with self._lk:
            self.commit(Block('assistant', ans or '(无回答)'))   # markdown re-renders on resize

    def _verbose_view(self) -> None:
        """Tool-call audit on a TEMP alt-screen — main scrollback is never
        touched. Data is the already-captured ToolRecord log (self._tools)."""
        recs = [self._tools[k] for k in sorted(self._tools)]
        if not recs:
            self.commit([_DIM + '  (暂无工具调用记录)' + _RST]); return
        sel, mode, scroll = 0, 0, 0
        fields = ('result', 'args', 'raw')
        _w('\x1b[?1049h\x1b[?2004l')          # alt-screen; pause bracketed paste here
        try:
            while True:
                w, h = _term()
                r = recs[sel]
                lines: list[str] = []
                for ln in (getattr(r, fields[mode]) or '(空)').split('\n'):
                    lines += _wrap_cells(ln, w - 2) or ['']
                avail = max(2, h - 4)               # rows shared by list + detail
                list_h = min(len(recs), max(3, avail // 3))
                body_h = max(1, avail - list_h)
                lo = max(0, min(sel - list_h // 2, len(recs) - list_h))
                scroll = max(0, min(scroll, max(0, len(lines) - body_h)))
                out = ['\x1b[2J\x1b[H', _BOLD + '  Tool Trace' + _RST + _DIM +
                       f'   ↑↓ 选 · PgUp/Dn 滚 · Enter 切换[{fields[mode]}]'
                       ' · c 复制 · e 导出 · q 退' + _RST, '']
                for t in recs[lo:lo + list_h]:
                    mk = _ACCENT + '▌' + _RST if t is r else ' '
                    stc = (_OK + 'ok' if t.status == 'ok' else
                           _ERR + 'error' if t.status == 'error' else _DIM + '?')
                    out.append(f'{mk} {_BOLD}t{t.id}{_RST} {t.name}  {stc}{_RST}')
                out.append('')
                detail_prefix = _DIM + ('│ ' if w >= 3 else '|' if w >= 1 else '') + _RST
                detail_w = max(1, w - cell_len('│ ' if w >= 3 else '|' if w >= 1 else ''))
                out += [detail_prefix + _clip_cells(ln, detail_w)
                        for ln in lines[scroll:scroll + body_h]]
                _w('\r\n'.join(out))
                d = os.read(self._fd, 32)
                if d in (b'q', b'\x1b', b'\x03', b'\x04'):
                    break
                elif d in (b'\x1b[A', b'k'):
                    sel = max(0, sel - 1); scroll = 0
                elif d in (b'\x1b[B', b'j'):
                    sel = min(len(recs) - 1, sel + 1); scroll = 0
                elif d == b'\x1b[5~':
                    scroll -= body_h
                elif d == b'\x1b[6~':
                    scroll += body_h
                elif d == b'\r':
                    mode = (mode + 1) % 3; scroll = 0
                elif d == b'c':
                    clip.copy(getattr(r, fields[mode]) or '')
                elif d == b'e':
                    from frontends import export_cmd
                    export_cmd.export_to_temp(getattr(r, fields[mode]) or '',
                                              f'tool_t{r.id}_{fields[mode]}')
        finally:
            _w('\x1b[?1049l\x1b[?2004h')       # leave alt-screen; resume bracketed paste
            self._goto_top(); _w('\x1b[J')
            self._painted = []; self._live_rows = 0
            self._render_live()

    # ── agent ──

    def _submit(self, query: str, images: list) -> None:
        assert self._bridge is not None
        self._running = True; self._t0 = time.time()
        self._stream = ''; self._sent = 0; self._live_tail = []
        dq = self._bridge.submit(query, images=images or None)
        threading.Thread(target=self._drain, args=(dq,), daemon=True).start()
        threading.Thread(target=self._ticker, daemon=True).start()

    def _ticker(self) -> None:
        while self._running:
            time.sleep(0.4)
            with self._lk:
                if self._running:
                    self._spin += 1; self._render_live()

    def _poll_ask(self, grace: float = 0.0) -> AskUserEvent | None:
        """Only pull a queued ask when none is currently being shown.
        Otherwise an already-active card would be overwritten before the
        user answered it (parallel sub-agent asks pile up in the queue;
        each entry stays there until the previous one is dispatched)."""
        assert self._bridge is not None
        end = time.time() + grace
        while True:
            with self._lk:
                if self._asking is not None:
                    return None
                try:
                    return self._bridge.ask_user_queue.get_nowait()
                except queue.Empty:
                    pass
            if time.time() >= end:
                return None
            time.sleep(0.02)

    def _drain(self, dq) -> None:
        assert self._bridge is not None
        for ev in self._bridge.drain_display_queue(dq):
            if ev is None:
                ae = self._poll_ask()
                if ae:
                    with self._lk:
                        self._enter_ask(ae)
                    return
                continue
            if isinstance(ev, DoneEvent):
                ae = self._poll_ask(grace=0.4)  # ask hook may land around turn end
                with self._lk:
                    self._enter_ask(ae) if ae else self._finalize(ev.text)
                break
            with self._lk:
                if isinstance(ev, StreamEvent):
                    self._stream += ev.text
                    now = time.time()
                    if now - self._last_render > 0.08:   # throttle: ≤~12 fps
                        self._last_render = now; self._flow()
                elif isinstance(ev, (SystemEvent, ErrorEvent)):
                    self._finalize(getattr(ev, 'text', None) or getattr(ev, 'message', '')); break
        self._running = False
        with self._lk:
            self._flow(final=True) if self._stream else self._render_live()

    def _enter_ask(self, ae: AskUserEvent) -> None:
        if self._stream.strip():
            self._flow(final=True)         # land the assistant lead-up in scrollback
        self._stream = ''; self._sent = 0; self._live_tail = []
        self._asking = ae; self._running = False; self.buf = ''; self.pos = 0
        self._undo.clear(); self._redo.clear(); self._sel = None
        self._render_live()

    def _commit_user(self, text: str) -> None:
        self.commit(Block('user', text))

    def _compress(self, t: str) -> str:
        """Capture each tool call as a structured ToolRecord (ids fixed at
        stream time — scrollback is immutable) and replace it with a quiet
        chip; then drop turn markers / status chatter / meta."""
        idx = 0

        def repl(m: re.Match) -> str:
            nonlocal idx
            idx += 1
            tid = self._tool_base + idx
            name = m.group(1)
            args = (m.group(3) or '').strip()           # args body (after fence-delim group 2)
            result = (m.group(5) or m.group(6) or '').strip()  # replay-fenced OR live trace
            st = _tool_status(result, '')
            hint = _arg_hint(name, args, result)
            self._tools[tid] = ToolRecord(tid, name, args, result, st, m.group(0))
            return f'\n▸ t{tid} {name}{(" " + hint) if hint else ""} · {st}\n'

        out = _TOOL_RE.sub(repl, t)

        def xrepl(m: re.Match) -> str:           # prompted-XML form: body IS the result
            nonlocal idx                          # no separate hint — the chip's preview
            idx += 1                              # shows the body directly (otherwise hint
            tid = self._tool_base + idx           # would duplicate preview line 1)
            name = m.group(1)
            body = (m.group(2) or '').strip()
            st = _tool_status(body, '')
            self._tools[tid] = ToolRecord(tid, name, '', body, st, m.group(0))
            return f'\n▸ t{tid} {name} · {st}\n'

        out = _XML_TOOL_RE.sub(xrepl, out)
        self._last_tool_n = idx
        out = _ACTION_RE.sub('· ', _TURN_MK_RE.sub('', out))
        return strip_meta_tags(out)        # empty when fully meta — render nothing,
                                            # else early '...' placeholders pollute _sent

    def _render_assistant(self, text: str, w: int) -> list[str]:
        """Compress, then alternately render prose (markdown) and emit chip
        boxes DIRECTLY — Rich Markdown is never asked to render a chip
        placeholder. Bypassing markdown is what guarantees the box stays
        closed (top/right/bottom/left); otherwise Rich would wrap-break the
        placeholder line and the box renders without its right/bottom edges."""
        compressed = self._compress(text)
        out: list[str] = []
        last = 0
        for m in _CHIP_PLACEHOLDER_RE.finditer(compressed):
            prose = compressed[last:m.start()]
            if prose.strip():
                out.extend(_render(prose, w, markdown=True))
            rec = self._tools.get(int(m.group(1)))
            out.extend(_chip_box(m.group(1), m.group(2), m.group(3), w,
                                  rec.result if rec else ''))
            last = m.end()
        tail = compressed[last:]
        if tail.strip():
            out.extend(_render(tail, w, markdown=True))
        return out

    def _commit_assistant(self, text: str) -> None:
        self.commit(Block('assistant', text))   # commit() handles _tool_base

    def _safe_pos(self, stream: str) -> int:
        """Position up to which the stream is STRUCTURALLY stable — past this
        point any commit risks duplication when the regex later matches and
        reshapes body. Detects in-flight `🛠️ Tool:` (no closing boundary
        yet), `**LLM Running` (no closing `**`), `<summary>` / `<thinking>`
        (no closing tag). Falls back to last `\\n\\n` paragraph boundary."""
        unsafe = []
        for m in re.finditer(r'🛠️ Tool:', stream):
            if not re.search(r'(?:^|\n)(?:\*\*LLM Running|🛠️ Tool:)', stream[m.end():]):
                unsafe.append(m.start())
        for m in re.finditer(r'\*\*LLM Running', stream):
            if '**' not in stream[m.end():]:
                unsafe.append(m.start())
        for tag in ('summary', 'thinking'):
            for m in re.finditer(f'<{tag}>', stream):
                if f'</{tag}>' not in stream[m.end():]:
                    unsafe.append(m.start())
        if unsafe:
            return min(unsafe)
        sep = stream.rfind('\n\n')
        return sep + 2 if sep > 0 else 0

    def _flow(self, final: bool = False) -> None:
        """cc-style flow with structural-boundary commit safety.

        Split the stream at `_safe_pos` (last position with no in-flight
        regex-matchable structure). Closed half renders & commits; open half
        stays VOLATILE in the live tail. Without this, an in-flight tool
        block (args fence still streaming) leaks its raw `🛠️ Tool:` header
        into scrollback — then once the fence closes and `_TOOL_RE` matches,
        the chip commits AFTER, leaving orphan headers. agent_loop emits a
        following `**LLM Running` or next `🛠️ Tool:` once a tool's result
        finishes, so detection of those markers gates the commit."""
        w = _term()[0]
        stream = sanitize_ansi(self._stream)

        if self._streaming_block is None and (stream.strip() or final):
            self._streaming_block = Block('assistant', '')
            self._blocks.append(self._streaming_block)
            self._cap_blocks()
            self._sent = 0

        if final:
            if self._streaming_block is not None:
                self._streaming_block.source = stream
            base = self._pre_streaming_tool_base()
            saved_base = self._tool_base; self._tool_base = base
            body = self._render_assistant(stream, max(1, w - 2))
            if self._streaming_block is not None:
                self._streaming_block.tool_n = self._last_tool_n
            self._tool_base = saved_base + self._last_tool_n   # legacy tracker advance
            full_lines = _indent_rows(body, w) + ['']
            new = full_lines[self._sent:]
            self._live_tail = []
            self._emit_lines(new, w)
            self._streaming_block = None
            self._stream = ''; self._sent = 0; self._live_tail = []
            return

        safe = self._safe_pos(stream)
        closed_text = stream[:safe]
        open_text = stream[safe:]

        if self._streaming_block is not None:
            self._streaming_block.source = closed_text         # block tracks committed src

        base = self._pre_streaming_tool_base()
        saved_base, saved_n = self._tool_base, self._last_tool_n
        self._tool_base = base
        closed_body = self._render_assistant(closed_text, max(1, w - 2)) if closed_text.strip() else []
        closed_n = self._last_tool_n
        if self._streaming_block is not None:
            self._streaming_block.tool_n = closed_n
        if open_text.strip():
            self._tool_base = base + closed_n                   # open tids don't collide
            open_body = self._render_assistant(open_text, max(1, w - 2))
        else:
            open_body = []
        self._tool_base = saved_base
        self._last_tool_n = saved_n                             # finalize uses closed_n

        closed_lines = _indent_rows(closed_body, w)
        new = closed_lines[self._sent:]
        self._sent = len(closed_lines)
        self._live_tail = _indent_rows(open_body[-8:], w)        # cap volatile region —
                                                                  # any larger and a growing
                                                                  # live region scrolls past
                                                                  # viewport, pushing old
                                                                  # paints into scrollback as
                                                                  # un-erasable "duplicates"
        if new:
            self._emit_lines(new, w)
        else:
            self._render_live()

    def _finalize(self, text: str) -> None:
        if text and not self._stream:
            self._stream = text           # system/error: nothing was streamed
        self._flow(final=True)

    # ── byte feed ──

    def _ingest(self, data: bytes):
        """Yield ('paste', str) and ('keys', bytes), holding partial markers."""
        self._rb += data
        while self._rb:
            if self._bp:
                i = self._rb.find(_BP_END)
                if i == -1:
                    hold = _holdback(self._rb, _BP_END)
                    self._pbytes += self._rb[:len(self._rb) - hold]
                    self._rb = self._rb[len(self._rb) - hold:]
                    return
                self._pbytes += self._rb[:i]; self._rb = self._rb[i + len(_BP_END):]
                self._bp = False
                yield ('paste', self._pbytes.decode('utf-8', 'replace')); self._pbytes = b''
            else:
                i = self._rb.find(_BP_START)
                if i == -1:
                    hold = _holdback(self._rb, _BP_START)
                    emit = self._rb[:len(self._rb) - hold]
                    self._rb = self._rb[len(self._rb) - hold:]
                    if emit:
                        yield ('keys', emit)
                    return
                if i:
                    yield ('keys', self._rb[:i])
                self._rb = self._rb[i + len(_BP_START):]
                self._bp = True

    def _keys(self, data: bytes) -> None:
        # escape-delay disambiguation: a lone trailing \x1b is held until the next
        # read (~40ms later via select gate in run()) — distinguishes a bare Esc
        # from the first byte of a split arrow `\x1b[A`. A `\x1b` followed by a
        # non-`[`/`O` byte means a real bare Esc + a separate key.
        data = self._epend + data; self._epend = b''
        if data.startswith(b'\x1b') and len(data) >= 2 and data[1:2] not in (b'[', b'O'):
            self._esc_back(); data = data[1:]
        if data == b'\x1b':
            self._epend = b'\x1b'; return
        if data.endswith(b'\x1b'):
            self._epend = b'\x1b'; data = data[:-1]
        if not data:
            return
        self._tail += _ESC_RE.sub(_esc_repl, data)
        try:
            text = self._tail.decode('utf-8'); self._tail = b''
        except UnicodeDecodeError as e:
            text = self._tail[:e.start].decode('utf-8', 'ignore'); self._tail = self._tail[e.start:]
        for ch in text:
            o = ord(ch)
            if ch == '\r':
                self._on_enter()
            elif ch == '\n':
                self._insert('\n')
            elif o == 0x10:                       # ↑ visual-row up (history at top)
                self._sel = None; self._cur_v(-1)
            elif o == 0x0e:                       # ↓ visual-row down (history at bottom)
                self._sel = None; self._cur_v(1)
            elif o == 0x02:                       # ← caret left
                self._sel = None; self.pos = max(0, self.pos - 1)
            elif o == 0x06:                       # → caret right
                self._sel = None; self.pos = min(len(self.buf), self.pos + 1)
            elif o == 0x1e:                       # Shift+← extend selection left
                self._sel_start(); self.pos = max(0, self.pos - 1)
            elif o == 0x1f:                       # Shift+→ extend selection right
                self._sel_start(); self.pos = min(len(self.buf), self.pos + 1)
            elif o == 0x1c:                       # Shift+↑ extend selection up
                self._sel_v(-1)
            elif o == 0x1d:                       # Shift+↓ extend selection down
                self._sel_v(1)
            elif o == 0x1a:                       # Ctrl+Z — undo
                self._do_undo()
            elif o == 0x19:                       # Ctrl+Y — redo
                self._do_redo()
            elif o == 0x01:                       # Ctrl+A — select all
                if self.buf:
                    self._sel = 0; self.pos = len(self.buf)
            elif o == 0x18:                       # Ctrl+X — cut selection
                r = self._sel_range()
                if r:
                    clip.copy(self.buf[r[0]:r[1]]); self._kill_sel()
            elif o == 0x1b:                       # Esc — universal back
                self._esc_back()
            elif o == 0x09:                       # Tab — slash-command completion
                self._tab()
            elif o == 0x0c:                       # Ctrl+L — force redraw (sleep/wake recovery)
                self._redraw()
            elif o == 0x16:                       # Ctrl+V
                self._handle_clip_paste()
            elif o == 0x15:                       # Cmd+⌫ / Ctrl+U: kill to line start
                if not self._kill_sel():
                    self._snap()
                    ls = self.buf.rfind('\n', 0, self.pos) + 1
                    self.buf = self.buf[:ls] + self.buf[self.pos:]; self.pos = ls
            elif o in (0x7f, 0x08):
                if not self._kill_sel():
                    if self.pos:
                        self._snap()
                        self.buf = self.buf[:self.pos - 1] + self.buf[self.pos:]; self.pos -= 1
            elif o >= 0x20:
                self._insert(ch)

    def _redraw(self) -> None:              # caller must hold self._lk
        """Force a clean live-region repaint. Recovers from mac-sleep/wake
        ghosting (two-box overlap), terminal resize, and any state where the
        skip-identical _paint cache disagrees with what's actually on screen."""
        self._painted = []; self._live_rows = 0; self._parked_up = 0
        self._repaint_screen()

    def _flush_esc(self) -> None:           # called from run() when the 40ms gate expires
        with self._lk:
            if self._rb and not self._bp:        # bracketed-paste holdback held a lone
                data = self._rb; self._rb = b''   # \x1b (prefix of \x1b[200~); release it
                self._keys(data)                  # so a bare Esc isn't invisibly stuck
            if self._epend:
                self._epend = b''; self._esc_back()
            if self._resized:
                self._resized = False; self._redraw()
            else:
                self._render_live()

    def _feed(self, data: bytes) -> bool:  # False → quit
        if b'\x04' in data and not self._bp:
            return False
        if b'\x03' in data and not self._bp:
            r = self._sel_range()                # Ctrl+C with a selection = copy
            if r:                                 # (preserves abort/exit semantics
                with self._lk:                    #  when there is nothing selected)
                    clip.copy(self.buf[r[0]:r[1]])
                    self._sel = None
                    self._render_live()
                return True
            if self._running and self._bridge:    # running task → abort (single press)
                self._bridge.abort(); return True
            if time.time() - self._cc_t < 2:      # idle: arm-to-quit; second press
                return False                       # within the window actually exits
            self._cc_t = time.time()              # first press arms + shows hint
            with self._lk:
                self._render_live()
            return True
        for kind, chunk in self._ingest(data):
            with self._lk:
                if self._resized:
                    self._resized = False; self._redraw()
                if kind == 'paste':
                    self._paste_text(chunk)
                else:
                    self._keys(chunk)
                self._render_live()
            if self._quit:
                return False
        return True

    def _on_resize(self, *_a) -> None:
        self._resized = True
        try:
            os.write(self._sig_w, b'r')   # wake the select() in run()
        except (BlockingIOError, OSError):
            pass                           # pipe full = pending wake already queued

    def run(self) -> None:
        self._bridge = AgentBridge()
        try:
            from frontends import cost_tracker
            cost_tracker.install()        # without this _trackers stays empty → no cost
        except Exception:
            pass
        self._old = termios.tcgetattr(self._fd)
        signal.signal(signal.SIGWINCH, self._on_resize)
        signal.siginterrupt(signal.SIGWINCH, True)   # don't auto-retry os.read — let
                                                      # SIGWINCH wake the read so a
                                                      # resize repaints immediately
                                                      # (otherwise stale until keypress)
        os.makedirs(self._cwd, exist_ok=True)
        logf = open(os.path.join(self._cwd, 'sb_agent.log'), 'w', buffering=1)
        so, se = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = logf  # agent chatter → log, not the terminal
        try:
            tty.setraw(self._fd)
            _w('\x1b[?2004h')  # bracketed paste: multi-line paste won't pre-submit
            _w('\x1b[>4;1m')   # modifyOtherKeys: Shift+Enter becomes distinguishable
            _w('\x1b[2J\x1b[H')  # one-time fresh page (NOT alt-screen; scrollback intact)
            self.commit(Block('banner', ''))
            while True:
                # Always select on BOTH stdin and the SIGWINCH self-pipe — under
                # iTerm split panes, signal-driven InterruptedError on os.read
                # is unreliable (PEP 475 auto-retries; on some macOS builds the
                # signal can be coalesced/dropped during the read syscall). The
                # self-pipe trick wakes select() deterministically whenever
                # SIGWINCH fires, so a resize ALWAYS repaints within ~40ms even
                # if the user never touches a key.
                gated = self._epend or (self._rb and not self._bp)
                timeout = 0.04 if gated else None
                r, _, _ = select.select([self._fd, self._sig_r], [], [], timeout)
                if self._sig_r in r:
                    try: os.read(self._sig_r, 4096)
                    except OSError: pass               # drain pending wake bytes
                if self._resized:
                    with self._lk:
                        self._resized = False
                        self._redraw()
                if not r:
                    self._flush_esc(); continue
                if self._fd in r:
                    try:
                        data = os.read(self._fd, 4096)
                    except InterruptedError:
                        continue
                    if not data or not self._feed(data):
                        break
        finally:
            _w('\x1b[>4;0m')   # restore default key reporting
            _w('\x1b[?2004l')
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            sys.stdout, sys.stderr = so, se
            logf.close()
            _w('\r\x1b[J'); os.write(1, b'\n')


# sb.py's original `main()` and __main__ guard intentionally dropped — the
# unified entry point lives below (combines __init__.py + __main__.py).


# ────────────────────────────────────────────────────────────────────────────
# entry: equivalent of frontends/tui/__init__.py + __main__.py
# ────────────────────────────────────────────────────────────────────────────

def _ensure_deps():
    try:
        import rich  # noqa: F401
    except ImportError:
        print("Error: rich is not installed.")
        print("Install with: pip install rich")
        sys.exit(2)


def main():
    _ensure_deps()
    install_cjk_wrap()
    if not sys.stdin.isatty():
        print('tui_v3: needs a real TTY (run it in iTerm directly)'); return
    SB().run()


if __name__ == '__main__':
    main()
