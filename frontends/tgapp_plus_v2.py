import os, sys, re, threading, asyncio, queue as Q, time, random, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp')
from agentmain import GeneraticAgent
try:
    from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Message
    from telegram.constants import ChatType, MessageLimit, ParseMode
    from telegram.error import RetryAfter
    from telegram.ext import ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters, ContextTypes
    from telegram.request import HTTPXRequest
except:
    print("Please ask the agent install python-telegram-bot to use telegram module.")
    sys.exit(1)
from chatapp_common import (
    FILE_HINT,
    HELP_TEXT,
    TELEGRAM_MENU_COMMANDS,
    clean_reply,
    ensure_single_instance,
    extract_files,
    format_restore,
    redirect_log,
    require_runtime,
    split_text,
)
from continue_cmd import handle_frontend_command, reset_conversation
from btw_cmd import handle_frontend_command as handle_btw_frontend_command
from review_cmd import handle as handle_review_command
from llmcore import mykeys

agent = GeneraticAgent()
agent.verbose = False
agent.inc_out = True
ALLOWED = set(mykeys.get('tg_allowed_users', []))

_DRAFT_HINT = "thinking..."
_STREAM_SUFFIX = " ⏳"
_STREAM_SEGMENT_LIMIT = max(1200, MessageLimit.MAX_TEXT_LENGTH - 256)
_STREAM_UPDATE_INTERVAL_SECONDS = 2.0
_STREAM_MIN_UPDATE_CHARS = 400
_RETRY_AFTER_MARGIN_SECONDS = 1.0
_QUEUE_WAIT_SECONDS = 1
_ASK_USER_HOOK_KEY = "telegram_ask_user_menu"
_ASK_CALLBACK_PREFIX = "ask:"
_LLM_CALLBACK_PREFIX = "llm:"
_ASK_CANCEL_ACTION = "none"
_ASK_MULTI_DONE_ACTION = "done"
_ASK_TOGGLE_ACTION = "toggle"
_ASK_CANCEL_LABEL = "none of these above"
_ASK_CANCEL_PROMPT = "已取消选择，请直接发送下一步操作。"
_ASK_MULTI_HINT = "可多选：点选项目后点击 Done 提交。"
_ASK_MULTI_EMPTY_HINT = "请至少选择一项，或选择 none of these above。"
_LLM_MENU_PROMPT = "请选择要切换的 LLM："
_ask_menu_events = Q.Queue()
_ask_menu_store = {}
_llm_menu_store = {}
_MULTI_SELECT_RE = re.compile(r"\[?(?:多选|multi(?:[-_ ]?select)?|select all)\]?", re.IGNORECASE)
_TURN_MARKER_RE = re.compile(r"^\*{0,2}LLM Running \(Turn (\d+)\) \.\.\.\*{0,2}\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*(`{3,})(.*)$")
_TURN_SUMMARY_LIMIT = 160

# ============================================================================
# Hermes-style 富文本格式化（参考 nousresearch/hermes-agent）
# 双路径：
#   1) Legacy MarkdownV2：format_message() 把 Markdown 转成 Telegram MarkdownV2，
#      用 ParseMode.MARKDOWN_V2 发送/编辑（普通文本走此路径）。
#   2) Rich Messages（Bot API 10.1）：含表格 / task-list / <details> / 块级公式 $$ 的内容，
#      用 sendRichMessage / editMessageText+rich_message 原生渲染（表格、任务列表原生支持）。
#      Rich 失败（旧端点 / BadRequest）自动降级到 MarkdownV2。
# ============================================================================

# --- MarkdownV2 转义 ---------------------------------------------------------
# MarkdownV2 要求在 code span / fenced code 之外对这些字符反斜杠转义
_MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#\+\-=|{}.!\\])')


def _escape_mdv2(text):
    """转义 Telegram MarkdownV2 特殊字符。"""
    return _MDV2_ESCAPE_RE.sub(r'\\\1', text or "")


def _strip_mdv2(text):
    """去除 MarkdownV2 转义反斜杠 + 格式标记，得到干净纯文本（降级纯文本发送用）。"""
    cleaned = re.sub(r'\\([_*\[\]()~`>#\+\-=|{}.!\\])', r'\1', text or "")
    cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)          # **bold** → text
    cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)              # MarkdownV2 bold *text*
    cleaned = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'\1', cleaned)    # _italic_（避免破坏 snake_case）
    cleaned = re.sub(r'~([^~]+)~', r'\1', cleaned)                 # ~strikethrough~
    cleaned = re.sub(r'\|\|([^|]+)\|\|', r'\1', cleaned)          # ||spoiler||
    return cleaned


# --- GFM 表格 → 粗体标题 + 列表（MarkdownV2 无表格语法，竖排比裸 |...| 清晰）---
_TABLE_SEPARATOR_RE = re.compile(r'^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*){1,}\|?\s*$')


def _split_table_row(line):
    """拆分 GFM 表格行，返回去空白后的单元格列表。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _render_table_block(table_block):
    """把检测到的 GFM 表格渲染成 粗体标题行 + bullet 分组。"""
    if len(table_block) < 3:
        return "\n".join(table_block)
    headers = _split_table_row(table_block[0])
    if len(headers) < 2:
        return "\n".join(table_block)
    first_data_row = _split_table_row(table_block[2]) if len(table_block) > 2 else []
    has_row_label_col = len(first_data_row) == len(headers) + 1
    rendered_groups = []
    for index, row in enumerate(table_block[2:], start=1):
        cells = _split_table_row(row)
        if has_row_label_col:
            heading = cells[0] if cells and cells[0] else f"Row {index}"
            data_cells = cells[1:]
        else:
            heading = next((cell for cell in cells if cell), f"Row {index}")
            data_cells = cells
        if len(data_cells) < len(headers):
            data_cells.extend([""] * (len(headers) - len(data_cells)))
        elif len(data_cells) > len(headers):
            data_cells = data_cells[:len(headers)]
        bullets = []
        for header, value in zip(headers, data_cells):
            if not has_row_label_col and value == heading:
                continue
            bullets.append(f"• {header}: {value}")
        group_lines = [f"**{heading}**", *bullets]
        rendered_groups.append("\n".join(group_lines))
    return "\n\n".join(rendered_groups)


def _wrap_markdown_tables(text):
    """把整段 markdown 中的 GFM 管道表格重写成 粗体标题 + bullet 分组。"""
    lines = (text or "").split("\n")
    out = []
    i, n = 0, len(lines)
    while i < n:
        if (
            i + 1 < n
            and "|" in lines[i]
            and _TABLE_SEPARATOR_RE.match(lines[i + 1])
        ):
            table_block = [lines[i], lines[i + 1]]
            j = i + 2
            while j < n and "|" in lines[j].strip():
                table_block.append(lines[j])
                j += 1
            out.append(_render_table_block(table_block))
            i = j
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def format_message(content):
    """把标准 Markdown 转成 Telegram MarkdownV2。

    受保护区域（代码块 / 行内代码）先抽取为占位符，再转换其余 Markdown 结构
    （标题/粗体/斜体/链接），最后对剩余特殊字符转义，倒序还原占位符。
    参考 Hermes format_message() 的 12 步占位符保护法。
    """
    if not content:
        return content

    placeholders = {}
    counter = [0]

    def _ph(value):
        key = f"\x00PH{counter[0]}\x00"
        counter[0] += 1
        placeholders[key] = value
        return key

    text = content

    # 0) GFM 表格 → 粗体标题 + bullets（MarkdownV2 无表格语法）
    text = _wrap_markdown_tables(text)

    # 1) 保护 fenced code block（```...```），内部 \ 与 ` 需转义
    def _protect_fenced(m):
        raw = m.group(0)
        open_end = raw.index('\n') + 1 if '\n' in raw[3:] else 3
        opening = raw[:open_end]
        body_and_close = raw[open_end:]
        body = body_and_close[:-3]
        body = body.replace('\\', '\\\\').replace('`', '\\`')
        return _ph(opening + body + '```')

    text = re.sub(r'(```(?:[^\n]*\n)?[\s\S]*?```)', _protect_fenced, text)

    # 2) 保护 inline code（`...`），内部 \ 需转义
    text = re.sub(r'(`[^`]+`)', lambda m: _ph(m.group(0).replace('\\', '\\\\')), text)

    # 3) 链接 [text](url)：显示文本转义，URL 仅转义 ) 与 \
    def _convert_link(m):
        display = _escape_mdv2(m.group(1))
        url = m.group(2).replace('\\', '\\\\').replace(')', '\\)')
        return _ph(f'[{display}]({url})')

    text = re.sub(r'\[([^\]]+)\]\(([^()]*(?:\([^()]*\)[^()]*)*)\)', _convert_link, text)

    # 4) 标题 ## Title → *Title*（MarkdownV2 bold）
    def _convert_header(m):
        inner = m.group(1).strip()
        inner = re.sub(r'\*\*(.+?)\*\*', r'\1', inner)
        return _ph(f'*{_escape_mdv2(inner)}*')

    text = re.sub(r'^#{1,6}\s+(.+)$', _convert_header, text, flags=re.MULTILINE)

    # 5) 粗体 **text** → *text*
    text = re.sub(r'\*\*(.+?)\*\*', lambda m: _ph(f'*{_escape_mdv2(m.group(1))}*'), text)

    # 6) 斜体 *text*（单星号）→ _text_，不跨行（避免破坏用 * 的 bullet 列表）
    text = re.sub(r'\*([^*\n]+)\*', lambda m: _ph(f'_{_escape_mdv2(m.group(1))}_'), text)

    # 7) 删除线 ~~text~~ → ~text~
    text = re.sub(r'~~(.+?)~~', lambda m: _ph(f'~{_escape_mdv2(m.group(1))}~'), text)

    # 8) 折叠 ||text|| → ||text||（保护 | 不被转义）
    text = re.sub(r'\|\|(.+?)\|\|', lambda m: _ph(f'||{_escape_mdv2(m.group(1))}||'), text)

    # 9) 引用块 > / >> / **>（expandable）
    def _convert_blockquote(m):
        prefix = m.group(1)
        content_q = m.group(2)
        if prefix.startswith('**') and content_q.endswith('||'):
            return _ph(f'{prefix} {_escape_mdv2(content_q[:-2])}||')
        return _ph(f'{prefix} {_escape_mdv2(content_q)}')

    text = re.sub(r'^((?:\*\*)?>{1,3}) (.+)$', _convert_blockquote, text, flags=re.MULTILINE)

    # 10) 转义剩余特殊字符
    text = _escape_mdv2(text)

    # 11) 倒序还原占位符
    for key in reversed(list(placeholders.keys())):
        text = text.replace(key, placeholders[key])

    # 12) 安全网：拆分 code / non-code，转义裸 ( ) { }（链接除外）
    _code_split = re.split(r'(```[\s\S]*?```|`[^`]+`)', text)
    _safe_parts = []
    for _idx, _seg in enumerate(_code_split):
        if _idx % 2 == 1:
            _safe_parts.append(_seg)
        else:
            def _esc_bare(m, _seg=_seg):
                s = m.start()
                ch = m.group(0)
                if s > 0 and _seg[s - 1] == '\\':
                    return ch
                if ch == '(' and s > 0 and _seg[s - 1] == ']':
                    return ch
                if ch == ')':
                    before = _seg[:s]
                    if '](http' in before or '](' in before:
                        depth = 0
                        for j in range(s - 1, max(s - 2000, -1), -1):
                            if _seg[j] == '(':
                                depth -= 1
                                if depth < 0:
                                    if j > 0 and _seg[j - 1] == ']':
                                        return ch
                                    break
                            elif _seg[j] == ')':
                                depth += 1
                return '\\' + ch
            _safe_parts.append(re.sub(r'[(){}]', _esc_bare, _seg))
    text = ''.join(_safe_parts)
    return text


# --- Rich Messages（Bot API 10.1）-------------------------------------------
_RICH_MESSAGE_MAX_CHARS = 32768

# 受保护区域：fenced code / GFM 表格块（内部换行保持原样，不注入硬换行）
_RICH_PROTECTED_REGION_RE = re.compile(
    r'(?:```[^\n]*\n[\s\S]*?```)'
    r'|(?:^[^\n]*\|[^\n]*\n'
    r'[ \t]*\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)+\|?[ \t]*'
    r'(?:\n[^\n]*\|[^\n]*)*)',
    re.MULTILINE,
)


def _rich_normalize_linebreaks(text):
    """rich 路径：单 \\n → 硬换行（两空格+\\n），保护代码块 / 表格区域。"""
    if not text or '\n' not in text:
        return text
    out = []
    pos = 0
    for m in _RICH_PROTECTED_REGION_RE.finditer(text):
        prose = text[pos:m.start()]
        out.append(re.sub(r'(?<!\n)\n(?!\n)', '  \n', prose))
        out.append(m.group(0))
        pos = m.end()
    tail = text[pos:]
    out.append(re.sub(r'(?<!\n)\n(?!\n)', '  \n', tail))
    return ''.join(out)


def _rich_message_payload(content, skip_entity_detection=False):
    """构建 InputRichMessage 的 {markdown: ...}。绝不能传入 format_message 后的内容。"""
    payload = {"markdown": _rich_normalize_linebreaks(content)}
    if skip_entity_detection:
        payload["skip_entity_detection"] = True
    return payload


# --- Rich 触发检测 + TDesktop 崩溃保护 --------------------------------------
_RICH_DETAILS_RE = re.compile(r"<details\b[^>]*>.*?</details>", re.IGNORECASE | re.DOTALL)
_RICH_MATH_IN_DETAILS_RE = re.compile(
    r"(\$\$.*?\$\$|"
    r"\\\[.*?\\\]|"
    r"\\\(.*?\\\)|"
    r"\\(?:sum|frac|alpha|beta|gamma|delta|theta|lambda|mu|pi|sigma|"
    r"int|prod|sqrt|lim|infty|begin\{(?:equation|align|matrix|cases)\}))",
    re.IGNORECASE | re.DOTALL,
)
_RICH_CJK_RE = re.compile(
    "["
    "\u3040-\u30ff"
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uac00-\ud7af"
    "\uf900-\ufaff"
    "\U00020000-\U000323af"
    "]"
)


def _needs_rich_rendering(content):
    """表格 / task-list / <details> / 块级公式 $$ → 走 rich 原生渲染。"""
    if not content:
        return False
    if any(_TABLE_SEPARATOR_RE.match(line) for line in content.splitlines()):
        return True
    if re.search(r"(?m)^\s*[-*]\s+\[[ xX]\]\s+", content):
        return True
    if re.search(r"(?m)^<details\b|^</details>|^<summary\b|^</summary>", content):
        return True
    if "$$" in content:
        return True
    return False


def _has_telegram_desktop_details_math_crash_shape(content):
    """details 内含公式会令 TDesktop 6.9.1 崩溃 → 跳过 rich。"""
    if not content:
        return False
    for details_block in _RICH_DETAILS_RE.findall(content):
        if _RICH_MATH_IN_DETAILS_RE.search(details_block):
            return True
    return False


def _has_telegram_desktop_cjk_rich_garble_shape(content):
    """CJK 文本在当前 TDesktop rich 渲染会乱码重叠 → 跳过 rich 走 MarkdownV2。"""
    return bool(content and _RICH_CJK_RE.search(content))


def _rich_eligible(content):
    """内容是否适合走 rich 路径（details+math 崩溃保护 + 长度限制）。
    CJK 内容默认仍走 rich（已实测本端点中文 rich 渲染正常）；如需对齐 Hermes
    原版"CJK 跳过 rich"行为，设环境变量 TG_RICH_SKIP_CJK=1。"""
    if not content or not content.strip() or not _needs_rich_rendering(content):
        return False
    if _has_telegram_desktop_details_math_crash_shape(content):
        return False
    if len(content) > _RICH_MESSAGE_MAX_CHARS:
        return False
    if os.getenv("TG_RICH_SKIP_CJK", "0") in {"1", "true", "yes", "on"}:
        if _has_telegram_desktop_cjk_rich_garble_shape(content):
            return False
    return True


def _is_bad_request_error(error):
    name = error.__class__.__name__.lower()
    if name == "badrequest" or name.endswith("badrequest"):
        return True
    try:
        from telegram.error import BadRequest
        return isinstance(error, BadRequest)
    except ImportError:
        return False


def _is_rich_capability_error(exc):
    """True ⇒ rich 端点本身不可用（旧 PTB / 旧服务器）→ 永久关闭 rich。"""
    name = exc.__class__.__name__.lower()
    if name in {"endpointnotfound", "invalidtoken"}:
        return True
    if isinstance(exc, (AttributeError, TypeError, NotImplementedError)):
        return True
    if getattr(exc, "error_code", None) == 404:
        return True
    s = str(exc).lower()
    if ("method" in s or "endpoint" in s) and ("not found" in s or "does not exist" in s):
        return True
    return "no such method" in s


def _is_rich_fallback_error(exc):
    """True ⇒ 可安全降级到 legacy（BadRequest / capability / unsupported）。"""
    if _is_bad_request_error(exc):
        return True
    if _is_rich_capability_error(exc):
        return True
    s = str(exc).lower()
    return "unsupported" in s or "not implemented" in s


# Rich 能力 latch（capability error 后永久关闭，避免每次发送都付一次失败往返）
_RICH_SEND_DISABLED = False
_RICH_EDIT_DISABLED = False
_RICH_DRAFT_DISABLED = False

# --- Rich 消息 blocks → 文本提取（用于「引用消息」取回 bot 自发 Rich 消息的内容）---
def _rich_inline_to_text(node):
    """把 Rich inline 节点（str / list / dict）还原成 Markdown 文本。"""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_rich_inline_to_text(n) for n in node)
    if isinstance(node, dict):
        inner = _rich_inline_to_text(node.get("text", ""))
        nt = node.get("type", "")
        if nt == "bold":
            return f"**{inner}**"
        if nt == "italic":
            return f"*{inner}*"
        if nt == "strikethrough":
            return f"~~{inner}~~"
        if nt == "code":
            return f"`{inner}`"
        if nt == "spoiler":
            return f"||{inner}||"
        if nt == "url":
            return f"[{inner}]({node.get('url', '')})"
        return inner
    return str(node)


def _rich_blocks_to_text(blocks):
    """把 Rich message 的 blocks（table/paragraph/list/blockquote 等）还原成 Markdown。"""
    lines = []
    for b in blocks or []:
        bt = b.get("type", "")
        if bt == "table":
            cells = b.get("cells", [])
            if cells:
                header = cells[0]
                rows = cells[1:]
                ncol = len(header)
                lines.append("| " + " | ".join(_rich_inline_to_text(c.get("text", "")) for c in header) + " |")
                lines.append("|" + "|".join(["---"] * ncol) + "|")
                for r in rows:
                    lines.append("| " + " | ".join(_rich_inline_to_text(c.get("text", "")) for c in r) + " |")
            lines.append("")
        elif bt == "paragraph":
            lines.append(_rich_inline_to_text(b.get("text", "")))
            lines.append("")
        elif bt == "list":
            for it in b.get("items", []):
                ib = it.get("blocks", [])
                txt = _rich_inline_to_text(ib[0].get("text", "")) if ib else ""
                if it.get("has_checkbox"):
                    lines.append(f"- [{'x' if it.get('is_checked') else ' '}] {txt}")
                else:
                    lines.append(f"{it.get('label', '•')} {txt}")
            lines.append("")
        elif bt == "blockquote":
            sub = _rich_blocks_to_text(b.get("blocks", []))
            lines.append("\n".join("> " + l for l in sub.splitlines()))
            lines.append("")
        else:
            lines.append(_rich_inline_to_text(b.get("text", "")))
            lines.append("")
    return "\n".join(lines).strip()


def _rich_message_text(msg):
    """从消息的 api_kwargs['rich_message'].blocks 提取纯文本。失败返回 None。"""
    try:
        # 注意：PTB 的 api_kwargs 是 mappingproxy（非 dict），用 .get 兼容。
        ak = getattr(msg, "api_kwargs", None)
        if not ak:
            return None
        rm = ak.get("rich_message")
        if isinstance(rm, dict) and rm.get("blocks"):
            return _rich_blocks_to_text(rm["blocks"]) or None
    except Exception:
        pass
    return None

def _make_draft_id():
    return random.randint(1, 2**31 - 1)

def _visible_segments(text):
    text = (text or "").strip()
    if not text:
        return []
    segments = []
    for part in split_text(text, _STREAM_SEGMENT_LIMIT):
        segments.extend(_markdown_safe_segments(part))
    return segments

def _markdown_safe_segments(text, limit=None):
    limit = limit or MessageLimit.MAX_TEXT_LENGTH
    text = (text or "").strip()
    if not text:
        return []
    # 用 format_message 的输出长度估算（MarkdownV2 转义会膨胀，比 len(text) 更贴近实际）
    if len(format_message(text)) <= limit:
        return [text]
    parts = []
    remaining = text
    while remaining:
        if len(format_message(remaining)) <= limit:
            parts.append(remaining)
            break
        low, high, best = 1, len(remaining), 1
        while low <= high:
            mid = (low + high) // 2
            if len(format_message(remaining[:mid].rstrip() or remaining[:mid])) <= limit:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        cut = remaining.rfind("\n", 0, best)
        if cut < max(1, best * 0.6):
            cut = best
        chunk = remaining[:cut].rstrip() or remaining[:best]
        parts.append(chunk)
        remaining = remaining[len(chunk):].lstrip()
    return parts

def _line_complete(line):
    return (line or "").endswith(("\n", "\r"))

def _turn_marker_number(line):
    match = _TURN_MARKER_RE.fullmatch((line or "").strip())
    return int(match.group(1)) if match else None

def _maybe_partial_turn_marker(line):
    text = (line or "").strip().lstrip("*")
    if not text:
        return False
    marker_head = "LLM Running (Turn "
    return marker_head.startswith(text) or text.startswith(marker_head)

def _maybe_partial_code_fence(line):
    return bool(re.match(r"^\s*`{1,}[^`\r\n]*$", line or ""))

# 需用 ```代码块``` 包裹展示的标签（内容保留可见，而非被 clean_reply 剥离丢弃）
_CODE_WRAP_TAGS = ("tool", "tool_use", "reflection", "answer", "file_content")
_CODE_WRAP_RE = re.compile(
    r"<(" + "|".join(_CODE_WRAP_TAGS) + r")>\s*([\s\S]*?)\s*</\1>",
    re.DOTALL,
)

def _preprocess_extra_tags(raw_text):
    """clean_reply 之前预处理：把 tool / reflection 等标签内容用代码块包裹。
    这样其内容原样保留可见（渲染为 <pre><code>），而非被 clean_reply 剥离丢弃。
    <summary>/<thinking> 不在此处理 —— 它们走 _extract_turn_summary 摘要展示。"""
    if not (raw_text or "").strip():
        return raw_text or ""
    def _wrap(m):
        tag, body = m.group(1), m.group(2).strip()
        if not body:
            return f"\n```{tag}\n\n```\n"
        return f"\n```{tag}\n{body}\n```\n"
    return _CODE_WRAP_RE.sub(_wrap, raw_text)

def _extract_turn_summary(raw_text):
    """提取本轮摘要。优先取 <summary>，无则退而取 <thinking> 内容。
    代码块（```...```）内容不参与提取，避免误抓。"""
    search_text = (raw_text or "").strip()
    # 先剔除代码块，避免代码里的 <summary>/<thinking> 被误抓
    search_text = re.sub(r"`{3,}[\s\S]*?`{3,}", "", search_text)
    for pat in (r"<summary>\s*(.*?)\s*</summary>", r"<thinking>\s*(.*?)\s*</thinking>"):
        match = re.search(pat, search_text, re.DOTALL)
        if match:
            summary = re.sub(r"\s+", " ", match.group(1)).strip()
            if not summary:
                continue
            if len(summary) > _TURN_SUMMARY_LIMIT:
                summary = summary[:_TURN_SUMMARY_LIMIT - 3].rstrip() + "..."
            return summary
    return ""

def _inject_turn_summary(body, summary):
    """把 turn 摘要以 MarkdownV2 引用块形式注入到正文顶部。
    摘要引用直接写成 markdown `> ` / 可折叠 `**> ...||` 形式，供 format_message 渲染。"""
    if not (body or "").strip() or not (summary or "").strip():
        return body
    lines = (body or "").splitlines()
    if not lines or _turn_marker_number(lines[0]) is None:
        return body
    title = lines[0].strip()
    rest = "\n".join(lines[1:]).strip()
    # 摘要引用：始终默认展开（force_expand=True → 普通引用块，不折叠）
    summary_block = _summary_quote_md(summary, force_expand=True)
    if rest:
        return f"{title}\n\n{summary_block}\n\n{rest}"
    return f"{title}\n\n{summary_block}"

def _resolve_files(paths):
    files, seen = [], set()
    for fpath in paths:
        if not os.path.isabs(fpath):
            fpath = os.path.join(_TEMP_DIR, fpath)
        if fpath in seen or not os.path.exists(fpath):
            continue
        files.append(fpath)
        seen.add(fpath)
    return files


def _render_file_markers(text):
    def repl(match):
        return os.path.basename(match.group(1))
    return re.sub(r"\[FILE:([^\]]+)\]", repl, text or "").strip()

def _files_from_text(text):
    cleaned = clean_reply(text) if (text or "").strip() else ""
    return _resolve_files(extract_files(cleaned))


def _clean_last_turn_body(body):
    """从单轮文本中去掉 marker 行与工具块（🛠️ 头及紧随的 4/5 反引号代码块），只保留 LLM 给用户的纯正文。"""
    if not body:
        return ""
    lines = body.split("\n")
    kept = []
    i = 0
    n = len(lines)

    def _skip_fenced(idx):
        """从 idx（应为一个代码围栏开行）开始，跳过该完整围栏对，返回围栏结束后的下一行索引。"""
        if idx >= n:
            return idx
        m = _CODE_FENCE_RE.match(lines[idx])
        if not m:
            return idx + 1
        backticks = m.group(1)
        j = idx + 1
        while j < n:
            mj = _CODE_FENCE_RE.match(lines[j])
            if mj and mj.group(1) >= backticks:
                return j + 1
            j += 1
        return j

    while i < n:
        line = lines[i]
        if _TURN_MARKER_RE.match(line.strip()):
            i += 1
            continue
        if line.lstrip().startswith("🛠️"):
            # [patch] 工具调用可视化：保留 🛠️ 头 + 其后紧随的 4/5 反引号代码块（含参数与结果），
            #         不再删除。逐行 kept，遇到 fence 时整体保留而不拆分。
            kept.append(line)
            i += 1
            while i < n:
                if _CODE_FENCE_RE.match(lines[i]):
                    j = _skip_fenced(i)
                    kept.extend(lines[i:j])
                    i = j
                elif lines[i].lstrip().startswith("🛠️"):
                    kept.append(lines[i])
                    i += 1
                else:
                    break
            continue
        kept.append(line)
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _extract_last_turn_reply(full_resp, outputs=None):
    """提取最后一轮 LLM 给用户的纯正文回复。优先用 outputs（按轮切分），回退解析 full_resp。"""
    if outputs:
        for item in reversed(outputs):
            if not isinstance(item, str):
                continue
            body = _clean_last_turn_body(clean_reply(item))
            if body and body != "...":
                return body
    text = full_resp or ""
    if text:
        body = _clean_last_turn_body(clean_reply(text))
        if body and body != "...":
            return body
    return text

async def _send_files(root_msg, files):
    for fpath in files:
        if fpath.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            try:
                with open(fpath, "rb") as fp:
                    await root_msg.reply_photo(fp)
            except Exception:
                pass
        else:
            try:
                with open(fpath, "rb") as fp:
                    await root_msg.reply_document(fp)
            except Exception:
                pass

async def _send_files_from_text(root_msg, text):
    await _send_files(root_msg, _files_from_text(text))

def _is_not_modified_error(exc):
    return "not modified" in str(exc).lower()

# turn-summary 摘要引用：在 MarkdownV2 里用 `> 引用` 语法呈现。
# short：始终默认展开的短引用；long：可折叠（**> ... ||，MarkdownV2 expandable blockquote）。
def _summary_quote_md(summary, force_expand=False):
    """把摘要文本转成 MarkdownV2 blockquote 行。
    force_expand=True 时用普通引用（默认展开）；长摘要且未强制展开时用可折叠引用。"""
    raw = (summary or "").strip()
    if not raw:
        return ""
    # 摘要可能含换行，逐行转义后用引用前缀串起
    escaped_lines = [_escape_mdv2(ln) for ln in raw.split("\n")]
    body = "\n".join(escaped_lines)
    if force_expand or len(raw) <= 80:
        # 普通引用块：每行以 > 开头
        return "\n".join(f"> {ln}" for ln in escaped_lines)
    # 可折叠引用：**> 起始，|| 结束（MarkdownV2 expandable blockquote）
    return f"**> {body}||"

def _extract_ask_user_event(ctx):
    exit_reason = (ctx or {}).get("exit_reason") or {}
    if exit_reason.get("result") != "EXITED":
        return None
    payload = exit_reason.get("data")
    if not isinstance(payload, dict):
        return None
    if payload.get("status") != "INTERRUPT" or payload.get("intent") != "HUMAN_INTERVENTION":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    raw_candidates = data.get("candidates") or []
    if not isinstance(raw_candidates, (list, tuple)):
        return None
    candidates = []
    for candidate in raw_candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            candidates.append(text)
    if not candidates:
        return None
    question = str(data.get("question") or "请选择下一步操作：").strip() or "请选择下一步操作："
    return {
        "question": question,
        "candidates": candidates,
        "multi": bool(_MULTI_SELECT_RE.search(question)),
    }

def _register_ask_user_hook():
    if not hasattr(agent, "_turn_end_hooks"):
        agent._turn_end_hooks = {}
    def _hook(ctx):
        event = _extract_ask_user_event(ctx)
        if event:
            _ask_menu_events.put(event)
    agent._turn_end_hooks[_ASK_USER_HOOK_KEY] = _hook

def _drain_latest_ask_user_event():
    latest = None
    while True:
        try:
            latest = _ask_menu_events.get_nowait()
        except Q.Empty:
            break
    return latest

def _build_ask_user_markup(menu_id, candidates, multi=False, selected_indexes=None):
    selected_indexes = set(selected_indexes or [])
    rows = []
    for idx, candidate in enumerate(candidates):
        if multi:
            label = f"✓ {candidate}" if idx in selected_indexes else candidate
            action = f"{_ASK_TOGGLE_ACTION}:{idx}"
        else:
            label = candidate
            action = str(idx)
        rows.append([
            InlineKeyboardButton(label, callback_data=f"{_ASK_CALLBACK_PREFIX}{menu_id}:{action}")
        ])
    if multi:
        rows.append([
            InlineKeyboardButton("Done", callback_data=f"{_ASK_CALLBACK_PREFIX}{menu_id}:{_ASK_MULTI_DONE_ACTION}")
        ])
    rows.append([
        InlineKeyboardButton(_ASK_CANCEL_LABEL, callback_data=f"{_ASK_CALLBACK_PREFIX}{menu_id}:{_ASK_CANCEL_ACTION}")
    ])
    return InlineKeyboardMarkup(rows)

def _build_llm_markup(menu_id, llms):
    rows = []
    for idx, name, current in llms:
        label = f"→ [{idx}] {name}" if current else f"[{idx}] {name}"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"{_LLM_CALLBACK_PREFIX}{menu_id}:{idx}")
        ])
    return InlineKeyboardMarkup(rows)

def _parse_menu_callback_data(data, prefix):
    if not (data or "").startswith(prefix):
        return None, None
    payload = data[len(prefix):]
    menu_id, sep, action = payload.partition(":")
    if not sep or not menu_id or not action:
        return None, None
    return menu_id, action

def _parse_ask_callback_data(data):
    return _parse_menu_callback_data(data, _ASK_CALLBACK_PREFIX)

_QUOTE_MAX_CHARS = 2000


def _extract_quoted_content(message):
    """从用户消息中提取被引用的内容。返回 (kind, text) 或 None。
    kind: 'quote'=用户选中的部分引用 | 'reply'=完整被回复消息。
    bot 自发的 Rich 消息被引用时 text/caption 为 None，直接从 Telegram
    下发的 reply_to_message 快照里 api_kwargs['rich_message'].blocks 取回。"""
    if message is None:
        return None

    def _take(q):
        if q is None:
            return None
        t = getattr(q, "text", None)
        return t if t else None

    # 1) 部分引用（用户选中的文本）—— 优先，最贴近"我引用了什么"
    qtext = _take(getattr(message, "quote", None))
    if qtext:
        return ("quote", qtext)
    # 2) 跨会话/话题回复的外部引用
    ext = getattr(message, "external_reply", None)
    if ext is not None:
        eqtext = _take(getattr(ext, "quote", None))
        if eqtext:
            return ("quote", eqtext)
    # 3) 完整被回复消息
    rtm = getattr(message, "reply_to_message", None)
    if rtm is not None:
        text = getattr(rtm, "text", None) or getattr(rtm, "caption", None)
        if text:
            return ("reply", text)
        # Rich 消息：text/caption 为 None，从快照 rich_message.blocks 还原
        rich = _rich_message_text(rtm)
        if rich:
            return ("reply", rich)
    return None


def _compose_prompt_with_quote(message, user_text):
    """把被引用内容拼到用户消息前，供 LLM 看到"引用了什么"。无引用则原样返回。"""
    quoted = _extract_quoted_content(message)
    if not quoted:
        return user_text or ""
    kind, content = quoted
    content = (content or "").strip()
    if not content:
        return user_text or ""
    if len(content) > _QUOTE_MAX_CHARS:
        content = content[:_QUOTE_MAX_CHARS].rstrip() + "\n…（引用内容过长，已截断）"
    label = "引用（选中部分）" if kind == "quote" else "引用消息"
    quoted_block = "\n".join(f"> {line}" if line else ">" for line in content.splitlines())
    return f"【{label}】\n{quoted_block}\n\n{user_text or ''}"


def _build_text_prompt(text):
    # 用户约定(B)：不再自动注入 FILE_HINT；仅当回复含 [FILE:...] 时才会被解析发送文件
    return text

def _normalize_ask_menu_event(stored):
    if isinstance(stored, dict):
        candidates = stored.get("candidates") or []
        return {
            "question": str(stored.get("question") or "请选择下一步操作：").strip() or "请选择下一步操作：",
            "candidates": [str(candidate).strip() for candidate in candidates if str(candidate).strip()],
            "multi": bool(stored.get("multi")),
            "selected": [int(idx) for idx in stored.get("selected", []) if isinstance(idx, int)],
        }
    if isinstance(stored, (list, tuple)):
        return {
            "question": "请选择下一步操作：",
            "candidates": [str(candidate).strip() for candidate in stored if str(candidate).strip()],
            "multi": False,
            "selected": [],
        }
    return None

def _render_ask_user_result(event, selected=None, cancelled=False):
    question = str(event.get("question") or "请选择下一步操作：").strip() or "请选择下一步操作："
    candidates = event.get("candidates") or []
    lines = [question, "", "选项："]
    for idx, candidate in enumerate(candidates, start=1):
        lines.append(f"{idx}. {candidate}")
    lines.append(f"{len(candidates) + 1}. {_ASK_CANCEL_LABEL}")
    lines.append("")
    if cancelled:
        lines.append(f"已取消：{_ASK_CANCEL_LABEL}")
    elif selected:
        lines.append(f"已选择：{selected}")
    text = "\n".join(lines)
    if len(text) > MessageLimit.MAX_TEXT_LENGTH:
        text = text[:MessageLimit.MAX_TEXT_LENGTH - 18].rstrip() + "\n...[truncated]"
    return text

async def _clear_ask_reply_markup(query):
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as exc:
        print(f"[TG ask_user menu cleanup] {type(exc).__name__}: {exc}", flush=True)

async def _edit_ask_user_result(query, event, selected=None, cancelled=False):
    try:
        await query.edit_message_text(
            _render_ask_user_result(event, selected=selected, cancelled=cancelled),
            reply_markup=None,
        )
    except Exception as exc:
        print(f"[TG ask_user menu edit] {type(exc).__name__}: {exc}", flush=True)
        await _clear_ask_reply_markup(query)

async def _send_ask_user_menu(root_msg, event):
    menu_id = uuid.uuid4().hex[:16]
    candidates = event["candidates"]
    multi = bool(event.get("multi"))
    _ask_menu_store[menu_id] = {
        "question": event["question"],
        "candidates": list(candidates),
        "multi": multi,
        "selected": [],
    }
    prompt = f"{event['question']}\n\n{_ASK_MULTI_HINT}" if multi else event["question"]
    try:
        await root_msg.reply_text(
            prompt,
            reply_markup=_build_ask_user_markup(menu_id, candidates, multi=multi),
        )
    except Exception as exc:
        _ask_menu_store.pop(menu_id, None)
        print(f"[TG ask_user menu error] {type(exc).__name__}: {exc}", flush=True)
        fallback = event["question"] + "\n" + "\n".join(f"- {candidate}" for candidate in candidates)
        await root_msg.reply_text(fallback)

class _TelegramStreamSession:
    def __init__(self, root_msg):
        self.root_msg = root_msg
        self.private_chat = getattr(getattr(root_msg, "chat", None), "type", "") == ChatType.PRIVATE
        self.can_use_draft = self.private_chat   # update tg client!
        self.draft_id = _make_draft_id()
        self.live_msg = None
        self.raw_text = ""
        self.files = []
        self.sent_segments = 0
        self.active_display = ""
        self.pending_display = ""
        self._edit_overflow_msgs = {}
        self.retry_until = 0.0
        self.last_update_at = 0.0
        self.last_update_raw_len = 0
        self.single_live = False

    def _now(self):
        return time.monotonic()

    def _retry_after_seconds(self, exc):
        retry_after = getattr(exc, "_retry_after", None)
        if retry_after is None:
            retry_after = getattr(exc, "retry_after", 0) or 0
        if hasattr(retry_after, "total_seconds"):
            retry_after = retry_after.total_seconds()
        try:
            return max(0.0, float(retry_after))
        except (TypeError, ValueError):
            return 0.0

    def _set_retry_after(self, exc):
        wait_seconds = self._retry_after_seconds(exc) + _RETRY_AFTER_MARGIN_SECONDS
        self.retry_until = max(self.retry_until, self._now() + wait_seconds)

    def _is_retrying(self):
        return self._now() < self.retry_until

    async def _wait_for_retry(self):
        remaining = self.retry_until - self._now()
        if remaining > 0:
            await asyncio.sleep(remaining)

    def _should_stream_update(self, display):
        if display == self.active_display:
            return False
        if self.last_update_at <= 0:
            return True
        elapsed = self._now() - self.last_update_at
        raw_delta = len(self.raw_text) - self.last_update_raw_len
        return elapsed >= _STREAM_UPDATE_INTERVAL_SECONDS or raw_delta >= _STREAM_MIN_UPDATE_CHARS

    def _mark_stream_update(self, display):
        self.active_display = display
        self.pending_display = ""
        self.last_update_at = self._now()
        self.last_update_raw_len = len(self.raw_text)

    def _stream_display(self, text):
        base = (text or _DRAFT_HINT).strip() or _DRAFT_HINT
        safe_parts = _markdown_safe_segments(base)
        base = safe_parts[-1] if safe_parts else _DRAFT_HINT
        if base == _DRAFT_HINT:
            return base
        display = base + _STREAM_SUFFIX
        if len(format_message(display)) <= MessageLimit.MAX_TEXT_LENGTH:
            return display
        return base

    async def prime(self):
        if self.can_use_draft:
            draft_result = await self._send_draft(_DRAFT_HINT)
            if draft_result is True:
                self.active_display = _DRAFT_HINT
                return
            if draft_result is None:
                self.active_display = _DRAFT_HINT
                return
        try:
            await self._upsert_live_message(_DRAFT_HINT, wait_retry=False)
        except RetryAfter:
            self.active_display = _DRAFT_HINT
            return
        self.active_display = _DRAFT_HINT

    async def add_chunk(self, chunk):
        if not chunk:
            return
        self.raw_text += chunk
        await self._refresh(done=False, send_files=False)

    async def finalize(self, full_text=None, send_files=True):
        if full_text is not None:
            self.raw_text = full_text
        await self._refresh(done=True, send_files=send_files)

    async def finish_with_notice(self, notice):
        if self.raw_text.strip():
            await self.finalize(send_files=False)
            await self._reply_text(notice)
            return
        if self.live_msg is not None:
            await self._edit_text(self.live_msg, notice)
            self.live_msg = None
            self.active_display = ""
            return
        await self._reply_text(notice)
        self.active_display = ""

    async def _refresh(self, done, send_files):
        # 预处理：tool / reflection 等标签内容转代码块包裹（内容保留可见）
        _raw = _preprocess_extra_tags(self.raw_text)
        summary = _extract_turn_summary(_raw)
        cleaned = clean_reply(_raw) if self.raw_text.strip() else ""
        self.files = _files_from_text(cleaned)
        body = _inject_turn_summary(_render_file_markers(cleaned), summary)
        if done and not body and self.files:
            body = "已生成附件"
        elif done and not body:
            body = "..."
        segments = _visible_segments(body)
        if not self.single_live:
            finalized_target = len(segments) if done else max(len(segments) - 1, 0)
            while self.sent_segments < finalized_target:
                await self._finalize_segment(segments[self.sent_segments])
                self.sent_segments += 1
        if done:
            if self.single_live:
                # single_live 模式流式期间用 live_msg 单条预览，完成时需把最终完整内容刷入，
                # 否则末段（超过单条上限需溢出的部分）会停留在最后一次流式预览而丢失。
                await self._upsert_live_message(body)
            if send_files:
                await self._send_files()
            return
        active_text = segments[-1] if segments else _DRAFT_HINT
        await self._stream_active(active_text)

    async def _stream_active(self, text):
        display = self._stream_display(text)
        if display == self.active_display:
            return
        self.pending_display = display
        if self._is_retrying() or not self._should_stream_update(display):
            return
        try:
            if self.can_use_draft:
                draft_result = await self._send_draft(display)
                if draft_result is True:
                    self._mark_stream_update(display)
                    return
                if draft_result is None:
                    return
            await self._upsert_live_message(display, wait_retry=False)
            self._mark_stream_update(display)
        except RetryAfter:
            return

    async def _finalize_segment(self, text):
        final_text = (text or "").strip() or "..."
        if self.live_msg is not None:
            await self._edit_text(self.live_msg, final_text)
            self.live_msg = None
        else:
            await self._reply_text(final_text)
        self.active_display = ""
        if self.can_use_draft:
            self.draft_id = _make_draft_id()

    async def _send_files(self):
        await _send_files(self.root_msg, self.files)

    async def _send_draft(self, text):
        # draft 不支持 rich：走 MarkdownV2（format_message 转义后输出）
        try:
            await self.root_msg.reply_text_draft(
                self.draft_id,
                format_message(text),
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return True
        except RetryAfter as exc:
            self._set_retry_after(exc)
            return None
        except Exception as exc:
            if _is_not_modified_error(exc):
                return True
            print(f"[TG draft fallback] {type(exc).__name__}: {exc}", flush=True)
            self.can_use_draft = False
            self.draft_id = _make_draft_id()
            return False

    async def _retry_call(self, func, *args):
        while True:
            await self._wait_for_retry()
            try:
                return await func(*args)
            except RetryAfter as exc:
                self._set_retry_after(exc)

    def _bot(self):
        try:
            return self.root_msg.get_bot()
        except Exception:
            return None

    async def _try_send_rich(self, text, reply_to_message_id=None):
        """走 Bot API 10.1 sendRichMessage 原生渲染（表格/task-list/details/公式）。
        返回 Message 或 None（不可用/失败）。失败时按错误类型 latch。"""
        global _RICH_SEND_DISABLED
        if _RICH_SEND_DISABLED or not _rich_eligible(text):
            return None
        bot = self._bot()
        if bot is None:
            return None
        chat_id = getattr(getattr(self.root_msg, "chat", None), "id", None)
        if chat_id is None:
            return None
        api_kwargs = {
            "chat_id": chat_id,
            "rich_message": _rich_message_payload(text),
        }
        if reply_to_message_id is not None:
            api_kwargs["reply_parameters"] = {"message_id": reply_to_message_id}
        elif getattr(self.root_msg, "message_id", None) is not None:
            api_kwargs["reply_parameters"] = {"message_id": self.root_msg.message_id}
        try:
            sent = await bot.do_api_request(
                "sendRichMessage",
                api_kwargs=api_kwargs,
                return_type=Message,
            )
            return sent
        except Exception as exc:
            if _is_rich_capability_error(exc):
                _RICH_SEND_DISABLED = True
            elif _is_rich_fallback_error(exc):
                pass
            print(f"[TG rich send fallback] {type(exc).__name__}: {exc}", flush=True)
            return None

    async def _try_edit_rich(self, msg, text):
        """编辑为 rich 消息（editMessageText + rich_message）。返回 Message 或 None。"""
        global _RICH_EDIT_DISABLED
        if _RICH_EDIT_DISABLED or not _rich_eligible(text):
            return None
        bot = self._bot()
        if bot is None:
            return None
        chat_id = getattr(getattr(msg, "chat", None), "id", None)
        message_id = getattr(msg, "message_id", None)
        if chat_id is None or message_id is None:
            return None
        api_kwargs = {
            "chat_id": chat_id,
            "message_id": message_id,
            "rich_message": _rich_message_payload(text),
        }
        try:
            updated = await bot.do_api_request(
                "editMessageText",
                api_kwargs=api_kwargs,
                return_type=Message,
            )
            result = updated if hasattr(updated, "edit_text") else msg
            return result
        except Exception as exc:
            if _is_not_modified_error(exc):
                return msg
            if _is_rich_capability_error(exc):
                _RICH_EDIT_DISABLED = True
            elif _is_rich_fallback_error(exc):
                pass
            print(f"[TG rich edit fallback] {type(exc).__name__}: {exc}", flush=True)
            return None

    async def _reply_text_once(self, text):
        # 1) Rich（表格/task-list/details/公式原生渲染）→ 2) MarkdownV2 → 3) 纯文本
        if _rich_eligible(text):
            rich_msg = await self._try_send_rich(text)
            if rich_msg is not None:
                return rich_msg
        markdown = format_message(text)
        try:
            return await self.root_msg.reply_text(markdown, parse_mode=ParseMode.MARKDOWN_V2)
        except RetryAfter as exc:
            self._set_retry_after(exc)
            raise
        except Exception as exc:
            if _is_not_modified_error(exc):
                return None
            # MarkdownV2 解析失败 → 纯文本兜底
            try:
                return await self.root_msg.reply_text(_strip_mdv2(markdown))
            except RetryAfter as retry_exc:
                self._set_retry_after(retry_exc)
                raise

    async def _reply_text(self, text, wait_retry=True):
        last_msg = None
        for segment in _markdown_safe_segments(text) or ["..."]:
            if wait_retry:
                last_msg = await self._retry_call(self._reply_text_once, segment)
            else:
                last_msg = await self._reply_text_once(segment)
        return last_msg

    async def _edit_text_once(self, msg, text):
        # 1) Rich edit → 2) MarkdownV2 edit → 3) 纯文本 edit
        if _rich_eligible(text):
            rich_msg = await self._try_edit_rich(msg, text)
            if rich_msg is not None:
                return rich_msg
        markdown = format_message(text)
        try:
            updated = await msg.edit_text(markdown, parse_mode=ParseMode.MARKDOWN_V2)
        except RetryAfter as exc:
            self._set_retry_after(exc)
            raise
        except Exception as exc:
            if _is_not_modified_error(exc):
                return msg
            # MarkdownV2 解析失败 → 纯文本兜底
            try:
                updated = await msg.edit_text(_strip_mdv2(markdown))
            except RetryAfter as retry_exc:
                self._set_retry_after(retry_exc)
                raise
        return updated if hasattr(updated, "edit_text") else msg

    def _message_key(self, msg):
        chat_id = getattr(getattr(msg, "chat", None), "id", None)
        message_id = getattr(msg, "message_id", None)
        if chat_id is not None and message_id is not None:
            return (chat_id, message_id)
        if message_id is not None:
            return ("message", message_id)
        return ("object", id(msg))

    async def _delete_text_once(self, msg):
        delete = getattr(msg, "delete", None)
        if delete is None:
            return
        try:
            result = delete()
            if hasattr(result, "__await__"):
                await result
        except RetryAfter as exc:
            self._set_retry_after(exc)
            raise
        except Exception as exc:
            print(f"[TG stale overflow delete error] {type(exc).__name__}: {exc}", flush=True)

    async def _delete_text(self, msg, wait_retry=True):
        if wait_retry:
            await self._retry_call(self._delete_text_once, msg)
        else:
            await self._delete_text_once(msg)

    async def _edit_text(self, msg, text, wait_retry=True):
        segments = _markdown_safe_segments(text) or ["..."]
        old_key = self._message_key(msg)
        overflow_msgs = self._edit_overflow_msgs.get(old_key, [])
        if wait_retry:
            updated = await self._retry_call(self._edit_text_once, msg, segments[0])
        else:
            updated = await self._edit_text_once(msg, segments[0])
        primary_msg = updated if hasattr(updated, "edit_text") else msg
        self._edit_overflow_msgs.pop(old_key, None)

        new_overflow_msgs = []
        for index, segment in enumerate(segments[1:]):
            if index < len(overflow_msgs):
                overflow_msg = overflow_msgs[index]
                if wait_retry:
                    edited_overflow = await self._retry_call(self._edit_text_once, overflow_msg, segment)
                else:
                    edited_overflow = await self._edit_text_once(overflow_msg, segment)
                new_overflow_msgs.append(
                    edited_overflow if hasattr(edited_overflow, "edit_text") else overflow_msg
                )
            else:
                new_overflow_msgs.append(await self._reply_text(segment, wait_retry=wait_retry))

        for stale_msg in overflow_msgs[len(new_overflow_msgs):]:
            await self._delete_text(stale_msg, wait_retry=wait_retry)

        if new_overflow_msgs:
            self._edit_overflow_msgs[self._message_key(primary_msg)] = new_overflow_msgs
        return primary_msg

    async def _upsert_live_message(self, text, wait_retry=True):
        if self.live_msg is None:
            self.live_msg = await self._reply_text(text, wait_retry=wait_retry)
        else:
            self.live_msg = await self._edit_text(self.live_msg, text, wait_retry=wait_retry)


class _TelegramTurnStreamCoordinator:
    def __init__(self, root_msg):
        self.root_msg = root_msg
        self.session = None
        self.pending_line = ""
        self.code_fence_len = 0
        self.last_turn = 0
        self.outputs = None          # done 时保存 turn_resps，用于提取最后一轮回复

    async def prime(self):
        await self._ensure_session()

    async def add_chunk(self, chunk):
        if not chunk:
            return
        text = self.pending_line + chunk
        self.pending_line = ""
        for line in text.splitlines(keepends=True):
            if _line_complete(line):
                await self._process_line(line)
            elif _maybe_partial_turn_marker(line) or _maybe_partial_code_fence(line):
                self.pending_line = line
            else:
                await self._process_line(line)

    async def finalize(self, done_text="", send_files=True):
        await self._flush_pending_line()
        # 提取最后一轮 LLM 给用户的纯正文回复作为最终展示内容
        final_reply = _extract_last_turn_reply(done_text, self.outputs)
        if self.session is None:
            if final_reply:
                # 没有任何 session（极少见）：发一条独立消息
                await self._add_to_current(final_reply)
        elif not self.session.raw_text.strip() and final_reply:
            # session 为空但有回复：编辑同一条 live_msg 为最终回复
            await self.session.finalize(final_reply, send_files=False)
            if send_files:
                await _send_files_from_text(self.root_msg, done_text)
            return
        else:
            # 用最终回复覆盖当前 session 的 raw_text，编辑同一条 live_msg
            if self.session.single_live:
                self.session.raw_text = final_reply
        if self.session is not None:
            await self.session.finalize(send_files=False)
        if send_files:
            await _send_files_from_text(self.root_msg, done_text)

    async def finish_with_notice(self, notice):
        await self._flush_pending_line()
        await self._ensure_session()
        await self.session.finish_with_notice(notice)

    async def _ensure_session(self):
        if self.session is None:
            self.session = _TelegramStreamSession(self.root_msg)
            await self.session.prime()

    async def _start_turn(self, marker):
        if self.session is not None and self.session.raw_text.strip():
            # single_live 模式：不 finalize 旧 turn，而是重置当前 session 只保留本轮进度，
            # live_msg 保持不变，继续编辑同一条消息显示最新一轮内容。
            s = self.session
            s.raw_text = ""
            s.sent_segments = 0
            s.active_display = ""
            s.pending_display = ""
            s.single_live = True
            await s.add_chunk(marker)
            return
        await self._ensure_session()
        self.session.single_live = True
        await self.session.add_chunk(marker)

    async def _add_to_current(self, text):
        if not text:
            return
        await self._ensure_session()
        await self.session.add_chunk(text)

    async def _process_line(self, line):
        turn_no = _turn_marker_number(line)
        if self.code_fence_len == 0 and turn_no == self.last_turn + 1:
            self.last_turn = turn_no
            await self._start_turn(line)
            return
        await self._add_to_current(line)
        self._update_code_fence(line)

    async def _flush_pending_line(self):
        if not self.pending_line:
            return
        line = self.pending_line
        self.pending_line = ""
        await self._add_to_current(line)

    def _update_code_fence(self, line):
        match = _CODE_FENCE_RE.match(line or "")
        if not match:
            return
        fence_len = len(match.group(1))
        if self.code_fence_len:
            if fence_len >= self.code_fence_len:
                self.code_fence_len = 0
            return
        self.code_fence_len = fence_len

async def _stream(dq, msg):
    stream = _TelegramTurnStreamCoordinator(msg)
    await stream.prime()
    try:
        while True:
            try: first = await asyncio.to_thread(dq.get, True, _QUEUE_WAIT_SECONDS)
            except Q.Empty: continue
            items = [first]
            try:
                while True: items.append(dq.get_nowait())
            except Q.Empty: pass
            done_item = None
            for item in items:
                chunk = item.get("next", "")
                if chunk:
                    await stream.add_chunk(chunk)
                if "done" in item:
                    done_item = item
                    break
            if done_item is not None:
                stream.outputs = done_item.get("outputs")
                await stream.finalize(done_item.get("done", ""))
                event = _drain_latest_ask_user_event()
                if event:
                    await _send_ask_user_menu(msg, event)
                break
    except asyncio.CancelledError:
        await stream.finish_with_notice("⏹️ 已停止")
    except RetryAfter as exc:
        print(f"[TG stream retry_after] {type(exc).__name__}: {exc}", flush=True)
        if stream.session is not None:
            stream.session._set_retry_after(exc)
    except Exception as exc:
        print(f"[TG stream error] {type(exc).__name__}: {exc}", flush=True)
        if stream.session is not None and stream.session._is_retrying():
            return
        try:
            await stream.finish_with_notice(f"❌ 输出失败: {exc}")
        except RetryAfter as retry_exc:
            print(f"[TG stream error notice retry_after] {type(retry_exc).__name__}: {retry_exc}", flush=True)

def _normalized_command(text):
    parts = (text or "").strip().split(None, 1)
    if not parts: return ''
    head = parts[0].lower()
    if head.startswith('/'): head = '/' + head[1:].split('@', 1)[0]
    return head + (f" {parts[1].strip()}" if len(parts) > 1 and parts[1].strip() else '')

def _cancel_stream_task(ctx):
    task = ctx.user_data.pop('stream_task', None)
    if task and not task.done(): task.cancel()

async def _sync_commands(application):
    await application.bot.set_my_commands([BotCommand(command, description) for command, description in TELEGRAM_MENU_COMMANDS])

async def _reply_command_text(message, text):
    for segment in _markdown_safe_segments(text) or ["..."]:
        try:
            await message.reply_text(format_message(segment), parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as exc:
            print(f"[TG command markdown fallback] {type(exc).__name__}: {exc}", flush=True)
            await message.reply_text(_strip_mdv2(format_message(segment)))

def _review_command_body(cmd):
    cmd = (cmd or "").strip()
    if cmd == "/review":
        return ""
    if cmd.startswith("/review "):
        return cmd[len("/review"):].strip()
    return ""

async def _handle_review_command(update, ctx, cmd):
    dq = Q.Queue()
    prompt = handle_review_command(agent, _review_command_body(cmd), dq)
    if not prompt:
        try:
            item = dq.get_nowait()
            return await _reply_command_text(update.message, item.get("done", ""))
        except Q.Empty:
            return await _reply_command_text(update.message, "(review 无输出)")
    _cancel_stream_task(ctx)
    task_dq = agent.put_task(prompt, source="telegram")
    task = asyncio.create_task(_stream(task_dq, update.message))
    ctx.user_data['stream_task'] = task

async def handle_msg(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED:
        return await update.message.reply_text("no")
    prompt = _compose_prompt_with_quote(update.message, _build_text_prompt(update.message.text))
    dq = agent.put_task(prompt, source="telegram")
    task = asyncio.create_task(_stream(dq, update.message))
    ctx.user_data['stream_task'] = task

async def handle_ask_callback(update, ctx):
    query = update.callback_query
    if query is None:
        return
    uid = update.effective_user.id if update.effective_user else None
    if ALLOWED and uid not in ALLOWED:
        return await query.answer("no", show_alert=True)
    menu_id, action = _parse_ask_callback_data(query.data)
    if not menu_id:
        return await query.answer("菜单无效")
    event = _normalize_ask_menu_event(_ask_menu_store.get(menu_id))
    if event is None:
        await query.answer("菜单已过期")
        return await _clear_ask_reply_markup(query)
    candidates = event["candidates"]
    if event.get("multi") and action.startswith(f"{_ASK_TOGGLE_ACTION}:"):
        try:
            selected_idx = int(action.split(":", 1)[1])
            if selected_idx < 0 or selected_idx >= len(candidates):
                raise ValueError
        except ValueError:
            return await query.answer("菜单无效")
        stored = _ask_menu_store.get(menu_id)
        if not isinstance(stored, dict):
            return await query.answer("菜单已过期")
        selected = set(stored.get("selected", []))
        if selected_idx in selected:
            selected.remove(selected_idx)
        else:
            selected.add(selected_idx)
        stored["selected"] = sorted(selected)
        await query.answer()
        return await query.edit_message_reply_markup(
            reply_markup=_build_ask_user_markup(
                menu_id,
                candidates,
                multi=True,
                selected_indexes=stored["selected"],
            )
        )
    if event.get("multi") and action == _ASK_MULTI_DONE_ACTION:
        selected_indexes = event.get("selected") or []
        if not selected_indexes:
            return await query.answer(_ASK_MULTI_EMPTY_HINT, show_alert=True)
        selected = "; ".join(candidates[idx] for idx in selected_indexes)
        _ask_menu_store.pop(menu_id, None)
        await query.answer()
        await _edit_ask_user_result(query, event, selected=selected)
        if query.message is None:
            return
        dq = agent.put_task(_build_text_prompt(selected), source="telegram")
        task = asyncio.create_task(_stream(dq, query.message))
        ctx.user_data['stream_task'] = task
        return
    if action == _ASK_CANCEL_ACTION:
        _ask_menu_store.pop(menu_id, None)
        await query.answer()
        await _edit_ask_user_result(query, event, cancelled=True)
        if query.message is not None:
            await query.message.reply_text(_ASK_CANCEL_PROMPT)
        return
    try:
        selected = candidates[int(action)]
    except (ValueError, IndexError):
        return await query.answer("菜单无效")
    _ask_menu_store.pop(menu_id, None)
    await query.answer()
    await _edit_ask_user_result(query, event, selected=selected)
    if query.message is None:
        return
    dq = agent.put_task(_build_text_prompt(selected), source="telegram")
    task = asyncio.create_task(_stream(dq, query.message))
    ctx.user_data['stream_task'] = task

async def _send_llm_menu(message):
    llms = agent.list_llms()
    if not llms:
        return await message.reply_text("没有可用模型。")
    menu_id = uuid.uuid4().hex[:16]
    _llm_menu_store[menu_id] = [idx for idx, _, _ in llms]
    lines = [f"{'→' if cur else '  '} [{idx}] {name}" for idx, name, cur in llms]
    try:
        await message.reply_text(
            _LLM_MENU_PROMPT,
            reply_markup=_build_llm_markup(menu_id, llms),
        )
    except Exception as exc:
        _llm_menu_store.pop(menu_id, None)
        print(f"[TG llm menu error] {type(exc).__name__}: {exc}", flush=True)
        await message.reply_text("LLMs:\n" + "\n".join(lines))

async def handle_llm_callback(update, ctx):
    query = update.callback_query
    if query is None:
        return
    uid = update.effective_user.id if update.effective_user else None
    if ALLOWED and uid not in ALLOWED:
        return await query.answer("no", show_alert=True)
    menu_id, action = _parse_menu_callback_data(query.data, _LLM_CALLBACK_PREFIX)
    if not menu_id:
        return await query.answer("菜单无效")
    valid_indexes = _llm_menu_store.get(menu_id)
    if valid_indexes is None:
        await query.answer("菜单已过期")
        return await _clear_ask_reply_markup(query)
    try:
        selected_idx = int(action)
    except (TypeError, ValueError):
        return await query.answer("菜单无效")
    if selected_idx not in valid_indexes:
        return await query.answer("菜单已过期", show_alert=True)
    try:
        agent.next_llm(selected_idx)
        selected_name = agent.get_llm_name()
    except Exception as exc:
        return await query.answer(f"切换失败: {exc}", show_alert=True)
    _llm_menu_store.pop(menu_id, None)
    await query.answer(f"已切换到 [{selected_idx}] {selected_name}")
    await query.edit_message_text(f"✅ 已切换到 [{selected_idx}] {selected_name}")

async def cmd_abort(update, ctx):
    _cancel_stream_task(ctx)
    agent.abort()
    await update.message.reply_text("⏹️ 正在停止...")

async def cmd_llm(update, ctx):
    args = (update.message.text or '').split()
    if len(args) > 1:
        try:
            n = int(args[1])
            agent.next_llm(n)
            await update.message.reply_text(f"✅ 已切换到 [{agent.llm_no}] {agent.get_llm_name()}")
        except (ValueError, IndexError):
            await update.message.reply_text(f"用法: /llm <0-{len(agent.list_llms())-1}>")
    else:
        await _send_llm_menu(update.message)

async def handle_photo(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED: return await update.message.reply_text("no")
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        fpath = f"tg_{photo.file_unique_id}.jpg"
        kind = "图片"
    elif update.message.document:
        doc = update.message.document
        file = await doc.get_file()
        ext = os.path.splitext(doc.file_name or '')[1] or ''
        fpath = f"tg_{doc.file_unique_id}{ext}"
        kind = "文件"
    else: return
    await file.download_to_drive(os.path.join(_TEMP_DIR, fpath))
    caption = update.message.caption
    base_prompt = f"[TIPS] 收到{kind}temp/{fpath}\n{caption}" if caption else f"[TIPS] 收到{kind}temp/{fpath}，请等待下一步指令"
    prompt = _compose_prompt_with_quote(update.message, base_prompt)
    dq = agent.put_task(prompt, source="telegram")
    task = asyncio.create_task(_stream(dq, update.message))
    ctx.user_data['stream_task'] = task

async def handle_command(update, ctx):
    uid = update.effective_user.id
    if ALLOWED and uid not in ALLOWED:
        return await update.message.reply_text("no")
    cmd = _normalized_command(update.message.text)
    op = cmd.split()[0] if cmd else ''
    if op == '/help': return await update.message.reply_text(HELP_TEXT)
    if op == '/status':
        llm = agent.get_llm_name() if agent.llmclient else '未配置'
        return await update.message.reply_text(f"状态: {'🔴 运行中' if agent.is_running else '🟢 空闲'}\nLLM: [{agent.llm_no}] {llm}")
    if op == '/stop': return await cmd_abort(update, ctx)
    if op == '/llm': return await cmd_llm(update, ctx)
    if op == '/btw':
        answer = await asyncio.to_thread(handle_btw_frontend_command, agent, cmd)
        return await _reply_command_text(update.message, answer)
    if op == '/review':
        return await _handle_review_command(update, ctx, cmd)
    if op == '/new':
        _cancel_stream_task(ctx)
        return await update.message.reply_text(reset_conversation(agent))
    if op == '/restore':
        _cancel_stream_task(ctx)
        try:
            restored_info, err = format_restore()
            if err:
                return await update.message.reply_text(err)
            restored, fname, count = restored_info
            agent.abort()
            agent.history.extend(restored)
            return await update.message.reply_text(f"✅ 已恢复 {count} 轮对话\n来源: {fname}\n(仅恢复上下文，请输入新问题继续)")
        except Exception as e:
            return await update.message.reply_text(f"❌ 恢复失败: {e}")
    if op == '/continue':
        if cmd != '/continue': _cancel_stream_task(ctx)
        return await update.message.reply_text(handle_frontend_command(agent, cmd))
    return await update.message.reply_text(HELP_TEXT)

if __name__ == '__main__':
    _LOCK_SOCK = ensure_single_instance(19527, "Telegram")
    if not ALLOWED: 
        print('[Telegram] ERROR: tg_allowed_users in mykey.py is empty or missing. Set it to avoid unauthorized access.')
        sys.exit(1)
    require_runtime(agent, "Telegram", tg_bot_token=mykeys.get("tg_bot_token"))
    redirect_log(__file__, "tgapp.log", "Telegram", ALLOWED)
    _register_ask_user_hook()
    threading.Thread(target=agent.run, daemon=True).start()
    proxy = mykeys.get('proxy')
    if proxy:
        print('proxy:', proxy)
    else:
        print('proxy: <disabled>')

    async def _error_handler(update, context: ContextTypes.DEFAULT_TYPE):
        print(f"[{time.strftime('%m-%d %H:%M')}] TG error: {context.error}", flush=True)

    while True:
        try:
            print(f"TG bot starting... {time.strftime('%m-%d %H:%M')}")
            # Recreate request and app objects on each restart to avoid stale connections
            request_kwargs = dict(read_timeout=30, write_timeout=30, connect_timeout=30, pool_timeout=30)
            if proxy:
                request_kwargs['proxy'] = proxy
            request = HTTPXRequest(**request_kwargs)
            builder = ApplicationBuilder().token(mykeys['tg_bot_token'])
            tg_base_url = mykeys.get('tg_base_url', '')
            if tg_base_url:
                builder = builder.base_url(tg_base_url)
            builder = builder.request(request).get_updates_request(request).post_init(_sync_commands)
            app = builder.build()
            app.add_handler(CallbackQueryHandler(handle_ask_callback, pattern=r"^ask:"))
            app.add_handler(CallbackQueryHandler(handle_llm_callback, pattern=r"^llm:"))
            app.add_handler(MessageHandler(filters.COMMAND, handle_command))
            app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
            app.add_handler(MessageHandler(filters.Document.ALL, handle_photo))
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
            app.add_error_handler(_error_handler)
            app.run_polling(drop_pending_updates=True, poll_interval=1.0, timeout=30)
        except Exception as e:
            print(f"[{time.strftime('%m-%d %H:%M')}] polling crashed: {e}", flush=True)
            time.sleep(10)
            asyncio.set_event_loop(asyncio.new_event_loop())
