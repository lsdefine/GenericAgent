"""tui_v3 — scrollback-first TUI for GenericAgent, consolidated.

Merged from frontends/tui/ (cjk, clipboard, renderer, protocol, core/sb)
into a single file so the v3 frontend ships as one drop-in module.
Run: `python -m frontends.tui_v3` or `python frontends/tui_v3.py`.
"""
from __future__ import annotations

import asyncio, atexit, json, locale, logging, os, queue, random, re, select, shutil, signal, subprocess
import sys, tempfile, threading, time

_IS_WINDOWS = os.name == 'nt'


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

# ════════════════════════════════════════════════════════════════════════════
# i18n — minimal dict-based zh/en translation layer (inlined; was tui_v3_i18n.py)
#
# - Single nested dict `_I18N[lang][key]` → format string.
# - `t(key, **fmt)` returns the formatted string for the current language;
#   falls back to English, then to the key itself (so missing keys are visible).
# - Language detection: persisted user choice > system locale > 'en'.
# - Persistence: temp/tui_v3_settings.json (workspace-local, matches v2 pattern).
#
# Strings that intentionally stay single-language (English):
# - Spinner gerunds (Pondering/Brewing/...) — ported from v2.
# - Tech jargon embedded in zh strings: 'tokens', 'ctx', 'model', 'session', …
# ════════════════════════════════════════════════════════════════════════════

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "temp", "tui_v3_settings.json"
)

_SUPPORTED = ('zh', 'en')
_DEFAULT = 'en'

_LANG: str = _DEFAULT


# ---------------- spinner gerunds (English only, from v2) ----------------

SPINNER_GERUNDS = (
    "Pondering", "Reticulating", "Sleuthing", "Hatching", "Pouncing",
    "Brewing", "Sharpening", "Untangling", "Compiling", "Unraveling",
    "Distilling", "Calibrating", "Marinating", "Conjuring", "Foraging",
    "Spelunking", "Synthesizing", "Refactoring thoughts", "Tracing breadcrumbs",
    "Following the rabbit hole",
    "Routing", "Threading", "Polling", "Spinning", "Hooking",
    "Patching", "Caching", "Yielding", "Hydrating", "Folding",
    "Streaming", "Resolving", "Reaping", "Tuning",
)


# Language display names (always shown in their own script — never translated,
# so users always see them in a form they recognize).
LANG_LABELS = {
    'zh': '简体中文',
    'en': 'English',
}


# Rotating usage tips — one picked per launch, shown in the banner (v2 _TIPS).
# Only covers features v3 has actually adapted; the en/zh lists run parallel.
_TIPS = {
    'en': [
        "Tip: press / to open the command palette — arrow keys to pick, Enter drops it into the input box.",
        "Tip: pasted images / files fold into [Image #N] / [File #N] placeholders; backspace deletes the whole block.",
        "Tip: /btw <question> lets a side-agent answer without interrupting the main task.",
        "Tip: /rewind [n] rewinds the last n turns; /stop aborts the current task.",
        "Tip: /continue lists past sessions — arrow keys to pick, Enter to restore.",
        "Tip: Ctrl+J / Shift+Enter inserts a newline in multi-line input; Enter sends.",
        "Tip: put [multi-select] in an ask_user prompt to switch to a multi-pick picker.",
        "Tip: /cost shows token usage; /llm views / switches the model.",
        "Tip: /new [name] starts a fresh session; /language switches the interface language.",
        "Tip: /export clip copies the last reply to your system clipboard; /export all prints the log path.",
        "Tip: Ctrl+O folds / unfolds all completed tool chips — each fold collapses to one line.",
    ],
    'zh': [
        "Tip: 按 / 唤起命令面板 —— 方向键选择，Enter 落入输入框。",
        "Tip: 粘贴图片 / 文件会折叠成 [Image #N] / [File #N] 占位符，退格可整块删除。",
        "Tip: /btw <问题> 让 side-agent 回答而不打断主任务。",
        "Tip: /rewind [n] 回退最近 n 轮对话；/stop 中止当前任务。",
        "Tip: /continue 列出历史会话 —— 方向键选择，Enter 恢复。",
        "Tip: 多行输入用 Ctrl+J / Shift+Enter 换行；Enter 直接发送。",
        "Tip: ask_user 题目里写 [多选] 会自动切到多选 picker。",
        "Tip: /cost 查看 token 用量；/llm 查看 / 切换模型。",
        "Tip: /new [name] 新建会话；/language 切换界面语言。",
        "Tip: /export clip 把最后回复复制到系统剪贴板；/export all 打印日志路径。",
        "Tip: Ctrl+O 折叠 / 展开所有已完成的工具 chip —— 每个 chip 折叠成一行。",
    ],
}


# ---------------- translations ----------------
# Keys are dot-namespaced. Format placeholders use {name}.

_I18N: dict[str, dict[str, str]] = {
    'en': {
        # /help intro & rows — phrasing mirrors v2's COMMANDS table.
        'help.title':           'Commands:',
        'help.help':            '  /help                Show help',
        'help.status':          '  /status              View session status',
        'help.sessions':        '  /sessions            List all sessions',
        'help.llm':             '  /llm [n]             View / switch model',
        'help.btw':             '  /btw <question>      Side question — does not interrupt main agent',
        'help.review':          '  /review [request]    In-session code review (report inline)',
        'help.rewind':          '  /rewind [n]          Rewind the last n rounds',
        'help.continue':        '  /continue [n|name]   List / restore historical sessions',
        'help.new':             '  /new [name]          Start a new session (clears the current one)',
        'help.rename':          '  /rename <name>       Rename the current session',
        'help.clear':           '  /clear               Clear display (does not touch LLM history)',
        'help.cost':            '  /cost                Token usage for the current session',
        'help.verbose':         '  /verbose             Tool-call audit (↑↓ select · Enter switch · c copy · q quit)',
        'help.export':          '  /export [sub]        Export last reply: clip / file [name] / all',
        'help.stop':            '  /stop                Abort current task',
        'help.language':        '  /language [code]     View / switch interface language',
        'help.quit':            '  /quit                Quit',
        'help.esc':             '  Esc                  Cancel ask · clear draft · stop task (no exit)',
        'help.cc':              '  Ctrl+C × 2           Quit (when idle; only aborts the task while running)',
        'help.cl':              '  Ctrl+L               Force repaint (recover from sleep/wake)',
        'help.cz':              '  Ctrl+Z / Ctrl+Y      Undo / redo input edits',
        'help.shift_arrow':     '  Shift+←→↑↓           Select text (Ctrl+C copy / Ctrl+X cut / Ctrl+A all)',

        # _CMDS palette entries — same wording as /help, condensed for one-line hint.
        'cmd.help.desc':        'Show help',
        'cmd.status.desc':      'View session status',
        'cmd.llm.desc':         'View / switch model',
        'cmd.btw.desc':         'Side question — does not interrupt main agent',
        'cmd.review.desc':      'In-session code review',
        'cmd.rewind.desc':      'Rewind the last n rounds',
        'cmd.continue.desc':    'List / restore historical sessions',
        'cmd.new.desc':         'Start a new session',
        'cmd.rename.desc':      'Rename the current session',
        'cmd.clear.desc':       'Clear display (LLM history untouched)',
        'cmd.cost.desc':        'Token usage for the current session',
        'cmd.verbose.desc':     'Tool-call audit',
        'cmd.export.desc':      'Export the last reply (clip/file/all)',
        'cmd.stop.desc':        'Abort current task',
        'cmd.language.desc':    'View / switch interface language',
        'cmd.quit.desc':        'Quit',

        # _CMDS arg hints — mirror v2 (lowercase n, full word "question").
        'cmd.llm.arg':          '[n]',
        'cmd.btw.arg':          '<question>',
        'cmd.review.arg':       '[request]',
        'cmd.rewind.arg':       '[n]',
        'cmd.continue.arg':     '[n|name]',
        'cmd.new.arg':          '[name]',
        'cmd.rename.arg':       '<name>',
        'cmd.export.arg':       '[clip|file|all]',
        'cmd.language.arg':     '[code]',

        # status line (one-liner above input box)
        'status.asking':        '◉ waiting · Esc cancel',
        'status.running.tail':  ' · Esc stop',
        'status.tps':           ' · {rate:.0f} tok/s',
        'status.cc_confirm':    'Press Ctrl+C again to quit',
        'status.ready':         '○ ready',

        # /status output rows
        'status.title':         '  Session status',
        'status.label.model':   'model:',
        'status.label.state':   'state:',
        'status.label.rounds':  'rounds:',
        'status.label.context': 'context:',
        'status.label.cwd':     'cwd:',
        'status.state.running': 'running · {verb} {elapsed}',
        'status.state.waiting': 'waiting · ask_user pending',
        'status.state.idle':    'idle',
        'status.ctx.unknown':   'n/a',
        'status.ctx.fmt':       '{used:,} / {cap:,} ctx',

        # banner
        'banner.label.model':       'model:',
        'banner.label.directory':   'directory:',
        'banner.label.session':     'session:',
        'banner.session.single':    'single · scrollback',
        'banner.llm_hint':          '/llm switch',

        # messages — success / status
        'msg.ask_cancelled':    '✗ ask cancelled · type freely or ask again',
        'msg.abort_requested':  '⏹ abort requested · Esc',
        'msg.abort_done':       '⏹ abort requested',
        'msg.idle_no_task':     '(idle, no task)',
        'msg.cleared':          'new conversation · context cleared',
        'msg.new_session':      'new session · previous conversation cleared',
        'msg.new_session_named': 'new session "{name}" · previous conversation cleared',
        'msg.renamed':          '✎ session renamed to "{name}"',
        'msg.rewind':           '↩ rewound {n} turn(s) (removed {removed} history entries; scrollback is not editable)',
        'msg.no_rewindable':    'no rewindable turns',
        'msg.continue_loading': '┄┄ loaded {name}, full context above ┄┄',
        'msg.continue_ready':   '┄┄ {msg} · continue typing ┄┄',
        'msg.llm_switched':     'LLM → {name}',
        'msg.export_done':      'exported: {path}',
        'msg.export_clipped':   'copied to clipboard ({n} chars)',
        'msg.export_clip_failed': '❌ copy failed: no clipboard tool found',
        'msg.export_all':       'full log:\n{path}',
        'msg.export_all_missing': 'no log file yet',
        'msg.review_empty':     '(review produced no output)',
        'msg.no_export':        '(no reply to export)',
        'msg.no_tracker':       '(no stats yet)',
        'msg.no_history':       '  no restorable historical sessions',
        'msg.no_llms':          '(no LLMs available)',
        'msg.no_tools':         '  (no tool-call records)',
        'msg.lang_current':     'Current language: {label} ({code})',
        'msg.lang_switched':    'Language → {label}',
        'msg.btw_no_answer':    '(no answer)',
        'btw.title':            'side-questions · Esc to clear',
        'btw.querying':         '  ⋯ querying…',

        # plan card
        'plan.header':          'Plan ({done}/{total})',
        'plan.complete':        '✓ Plan complete ({n}/{n})',
        'plan.placeholder':     'Plan mode activated',
        'plan.waiting':         'waiting for {path} …',
        'plan.overflow':        '+{n} more',

        # errors
        'err.running_blocked':  'busy — /stop before using this command',
        'err.continue_usage':   'usage: /continue or /continue N',
        'err.index_oob':        '❌ index out of range (valid: 1-{max})',
        'err.btw_usage':        'usage: /btw <question> (does not pollute main context)',
        'err.rewind_usage':     'usage: /rewind <n>',
        'err.rename_usage':     'usage: /rename <name>',
        'err.rewind_range':     '❌ rewind failed: n must be 1-{max}',
        'err.lang_usage':       'usage: /language [code]   (codes: {available})',
        'err.lang_unknown':     'unknown language code: {code}  (available: {available})',
        'err.unknown_cmd':      'unknown command /{name} — /help to list',
        'err.multi_session':    '/{name}: multi-session backend not wired yet; command reserved',
        'err.menu_cb':          '❌ menu callback failed: {err}',
        'err.no_llm':           'No LLM configured — check mykey.py',
        'err.no_tty':           'tui_v3: needs a real TTY (run it in iTerm directly)',
        'err.dep_missing':      'Error: {name} is not installed.',
        'err.dep_install':      'Install with: pip install rich prompt_toolkit',

        # menu / picker / palette
        'menu.default_title':   'Pick',
        'menu.hint':            '↑↓ pick · Enter confirm · Esc cancel',
        'ask.default_q':        'answer:',
        'ask.title':            '◉ answer',
        'ask.pending':          '  +{n} pending',
        'ask.hint.multi':       '↳ ↑↓ move · Space toggle · Enter submit · Esc cancel',
        'ask.hint.single':      '↳ ↑↓ navigate (options ⇄ input) · Enter confirm · Esc cancel',
        'ask.hint.freetext':    '↳ ↑↓ back to options · type to input · Enter submit · Esc cancel',

        # continue picker
        'continue.title':       'Restore historical session',
        'continue.row.fmt':     '{rel:>4}  {rounds:>3}r  {preview}',
        'continue.unit.round':  'r',

        # llm picker
        'llm.title':            'Switch LLM',

        # export picker
        'export.title':         'Export the last reply',
        'export.opt.clip':      'Copy to clipboard',
        'export.opt.file':      'Save to file (temp/)',
        'export.opt.all':       'Show full log path',

        # rewind picker
        'rewind.title':         'Rewind to which turn',
        'rewind.option':        'rewind {n} turn(s) · {preview}',

        # language picker
        'lang.title':           'Switch interface language',

        # verbose
        'verbose.title':        '  Tool Trace',
        'verbose.hint':         '   ↑↓ pick · PgUp/Dn scroll · Enter switch[{field}] · c copy · e export · q quit',
        'verbose.empty':        '(empty)',

        # answer prefix when committing user reply to ask_user
        'msg.answer_prefix':    '[ans] {text}',
    },

    'zh': {
        # /help intro & rows — 措辞与 v2 COMMANDS 表对齐。
        'help.title':           '命令:',
        'help.help':            '  /help                显示帮助',
        'help.status':          '  /status              查看会话状态',
        'help.sessions':        '  /sessions            列出所有会话',
        'help.llm':             '  /llm [n]             查看 / 切换模型',
        'help.btw':             '  /btw <question>      旁问 — 不打断主 agent',
        'help.review':          '  /review [request]    in-session 代码审查（直接输出报告）',
        'help.rewind':          '  /rewind [n]          回退最近 n 轮',
        'help.continue':        '  /continue [n|name]   列出 / 恢复历史会话',
        'help.new':             '  /new [name]          新建会话（清空当前会话）',
        'help.rename':          '  /rename <name>       重命名当前会话',
        'help.clear':           '  /clear               清空显示（不动 LLM 历史）',
        'help.cost':            '  /cost                显示当前会话 token 用量',
        'help.verbose':         '  /verbose             工具调用审计（↑↓ 选 · Enter 切换 · c 复制 · q 退）',
        'help.export':          '  /export [sub]        导出最后回复：clip / file [name] / all',
        'help.stop':            '  /stop                中止当前任务',
        'help.language':        '  /language [code]     查看 / 切换界面语言',
        'help.quit':            '  /quit                退出',
        'help.esc':             '  Esc                  撤回提问 · 清草稿 · 停任务（不退出）',
        'help.cc':              '  Ctrl+C × 2           退出（空闲时；运行中只 abort 任务）',
        'help.cl':              '  Ctrl+L               强制重画（睡眠唤醒后修复）',
        'help.cz':              '  Ctrl+Z / Ctrl+Y      撤销 / 重做 输入框编辑',
        'help.shift_arrow':     '  Shift+←→↑↓           选中文字（Ctrl+C 复制 / Ctrl+X 剪切 / Ctrl+A 全选）',

        # _CMDS palette entries — 与 /help 同源，命令面板单行显示。
        'cmd.help.desc':        '显示帮助',
        'cmd.status.desc':      '查看会话状态',
        'cmd.llm.desc':         '查看 / 切换模型',
        'cmd.btw.desc':         '旁问 — 不打断主 agent',
        'cmd.review.desc':      'in-session 代码审查',
        'cmd.rewind.desc':      '回退最近 n 轮',
        'cmd.continue.desc':    '列出 / 恢复历史会话',
        'cmd.new.desc':         '新建会话',
        'cmd.rename.desc':      '重命名当前会话',
        'cmd.clear.desc':       '清空显示（不动 LLM 历史）',
        'cmd.cost.desc':        '显示当前会话 token 用量',
        'cmd.verbose.desc':     '工具调用审计',
        'cmd.export.desc':      '导出最后回复（剪贴板/文件/日志路径）',
        'cmd.stop.desc':        '中止当前任务',
        'cmd.language.desc':    '查看 / 切换界面语言',
        'cmd.quit.desc':        '退出',

        # arg hints — 与 v2 对齐：小写 n、完整的 question 等。
        'cmd.llm.arg':          '[n]',
        'cmd.btw.arg':          '<question>',
        'cmd.review.arg':       '[request]',
        'cmd.rewind.arg':       '[n]',
        'cmd.continue.arg':     '[n|name]',
        'cmd.new.arg':          '[name]',
        'cmd.rename.arg':       '<name>',
        'cmd.export.arg':       '[clip|file|all]',
        'cmd.language.arg':     '[code]',

        # status line
        'status.asking':        '◉ 待答 · Esc 撤回提问',
        'status.running.tail':  ' · Esc 停',
        'status.tps':           ' · {rate:.0f} tok/s',
        'status.cc_confirm':    '再按 Ctrl+C 退出',
        'status.ready':         '○ 就绪',

        # /status
        'status.title':         '  会话状态',
        'status.label.model':   'model:',
        'status.label.state':   'state:',
        'status.label.rounds':  'rounds:',
        'status.label.context': 'context:',
        'status.label.cwd':     'cwd:',
        'status.state.running': 'running · {verb} {elapsed}',
        'status.state.waiting': 'waiting · ask_user pending',
        'status.state.idle':    'idle',
        'status.ctx.unknown':   'n/a',
        'status.ctx.fmt':       '{used:,} / {cap:,} ctx',

        # banner
        'banner.label.model':       'model:',
        'banner.label.directory':   'directory:',
        'banner.label.session':     'session:',
        'banner.session.single':    '单会话 · scrollback',
        'banner.llm_hint':          '/llm 切换',

        # messages
        'msg.ask_cancelled':    '✗ 已撤回提问 · 可直接输入或重新发问',
        'msg.abort_requested':  '⏹ 已请求中止 · Esc',
        'msg.abort_done':       '⏹ 已请求中止',
        'msg.idle_no_task':     '（空闲，无任务）',
        'msg.cleared':          '新对话 · 上下文已清空',
        'msg.new_session':      '新会话 · 上一段对话已清空',
        'msg.new_session_named': '新会话「{name}」· 上一段对话已清空',
        'msg.renamed':          '✎ 会话已重命名为「{name}」',
        'msg.rewind':           '↩ 回退 {n} 轮（移除 {removed} 条历史；scrollback 不可改，以此为界）',
        'msg.no_rewindable':    '没有可回退的轮次',
        'msg.continue_loading': '┄┄ 载入 {name}，以下为完整上文 ┄┄',
        'msg.continue_ready':   '┄┄ {msg} · 接着说即可 ┄┄',
        'msg.llm_switched':     'LLM → {name}',
        'msg.export_done':      '已导出: {path}',
        'msg.export_clipped':   '已复制到剪贴板（{n} 字符）',
        'msg.export_clip_failed': '❌ 复制失败：未找到剪贴板工具',
        'msg.export_all':       '完整日志:\n{path}',
        'msg.export_all_missing': '尚无日志文件',
        'msg.review_empty':     '(review 无输出)',
        'msg.no_export':        '（没有可导出的回答）',
        'msg.no_tracker':       '（暂无统计）',
        'msg.no_history':       '  没有可恢复的历史会话',
        'msg.no_llms':          '(无可用 LLM)',
        'msg.no_tools':         '  (暂无工具调用记录)',
        'msg.lang_current':     '当前界面语言：{label}（{code}）',
        'msg.lang_switched':    '界面语言 → {label}',
        'msg.btw_no_answer':    '(无回答)',
        'btw.title':            '旁问 · Esc 清空',
        'btw.querying':         '  ⋯ 查询中…',

        # plan card
        'plan.header':          '计划 ({done}/{total})',
        'plan.complete':        '✓ 计划完成 ({n}/{n})',
        'plan.placeholder':     '计划模式已激活',
        'plan.waiting':         '等待写入 {path} …',
        'plan.overflow':        '还有 {n} 项',

        # errors
        'err.running_blocked':  '运行中，先 /stop 再用该命令',
        'err.continue_usage':   '用法: /continue 或 /continue N',
        'err.index_oob':        '❌ 索引越界（有效 1-{max}）',
        'err.btw_usage':        '用法: /btw <旁问>（不污染主上下文）',
        'err.rewind_usage':     '用法：/rewind <n>',
        'err.rename_usage':     '用法：/rename <name>',
        'err.rewind_range':     '❌ 回退失败：n 应在 1-{max}',
        'err.lang_usage':       '用法：/language [code]   （可选 code：{available}）',
        'err.lang_unknown':     '未知语言代码：{code}  （可选：{available}）',
        'err.unknown_cmd':      '未知命令 /{name} — /help 看可用命令',
        'err.multi_session':    '/{name}：多会话后端尚未接入，命令已预留但暂未实现',
        'err.menu_cb':          '❌ 菜单回调失败: {err}',
        'err.no_llm':           'No LLM configured — check mykey.py',
        'err.no_tty':           'tui_v3: needs a real TTY (run it in iTerm directly)',
        'err.dep_missing':      'Error: {name} is not installed.',
        'err.dep_install':      'Install with: pip install rich prompt_toolkit',

        # menu / picker / palette
        'menu.default_title':   '选择',
        'menu.hint':            '↑↓ 选 · Enter 确认 · Esc 取消',
        'ask.default_q':        '请回答:',
        'ask.title':            '◉ 请回答',
        'ask.pending':          '  +{n} 待答',
        'ask.hint.multi':       '↳ ↑↓ 移动 · Space 标记 · Enter 提交 · Esc 撤回',
        'ask.hint.single':      '↳ ↑↓ 切换（选项 ⇄ 输入框）· Enter 确认 · Esc 撤回',
        'ask.hint.freetext':    '↳ ↑↓ 回到选项 · 输字符输入 · Enter 提交 · Esc 撤回',

        # continue picker
        'continue.title':       '恢复历史会话',
        'continue.row.fmt':     '{rel:>4}  {rounds:>3}轮  {preview}',
        'continue.unit.round':  '轮',

        # llm picker
        'llm.title':            '切换 LLM',

        # export picker
        'export.title':         '导出最后回复',
        'export.opt.clip':      '复制到剪贴板',
        'export.opt.file':      '保存到文件（temp/）',
        'export.opt.all':       '显示完整日志路径',

        # rewind picker
        'rewind.title':         '选择回退到的轮次',
        'rewind.option':        '回退 {n} 轮 · {preview}',

        # language picker
        'lang.title':           '切换界面语言',

        # verbose
        'verbose.title':        '  Tool Trace',
        'verbose.hint':         '   ↑↓ 选 · PgUp/Dn 滚 · Enter 切换[{field}] · c 复制 · e 导出 · q 退',
        'verbose.empty':        '(空)',

        # answer prefix
        'msg.answer_prefix':    '[答] {text}',
    },
}


def t(key: str, **fmt) -> str:
    """Translate `key` to current language; fall back to en then to key itself.
    Missing format fields raise KeyError — caller bug, not i18n bug."""
    val = _I18N.get(_LANG, {}).get(key)
    if val is None and _LANG != 'en':
        val = _I18N.get('en', {}).get(key)
    if val is None:
        val = key                                       # visible breadcrumb for missing keys
    if fmt:
        try:
            return val.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return val
    return val


def tip_count() -> int:
    """Number of rotating banner tips (same for every language)."""
    return len(_TIPS['en'])


def tip(idx: int) -> str:
    """Banner tip at `idx`, resolved in the current language so a /language
    switch relabels it on the next banner repaint."""
    pool = _TIPS.get(_LANG) or _TIPS['en']
    return pool[idx % len(pool)] if pool else ''


def get_lang() -> str:
    return _LANG


def set_lang(code: str) -> bool:
    """Switch active language and persist. Returns True on success."""
    global _LANG
    if code not in _SUPPORTED:
        return False
    _LANG = code
    _save_settings({'lang': code})
    return True


def supported() -> tuple[str, ...]:
    return _SUPPORTED


def _detect_system_lang() -> str:
    """System language: check LC_ALL → LC_MESSAGES → LANG → locale.getlocale().
    Prefix `zh` → 'zh', else 'en'."""
    for env in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        v = os.environ.get(env)
        if v:
            if v.lower().startswith('zh'):
                return 'zh'
            return 'en'
    try:
        loc = locale.getlocale()[0] or ''
        if loc.lower().startswith('zh'):
            return 'zh'
    except Exception:
        pass
    return _DEFAULT


def _load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(patch: dict) -> None:
    cur = _load_settings()
    cur.update(patch)
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(cur, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def init_lang() -> str:
    """Resolve and install initial language: persisted > system > default.
    Call once at startup; returns the resolved code."""
    global _LANG
    saved = _load_settings().get('lang')
    if saved in _SUPPORTED:
        _LANG = saved
    else:
        _LANG = _detect_system_lang()
    return _LANG


# `_t` alias kept so the hundreds of existing `_t(...)` call sites are untouched.
_t = t

# Resolve language once on import so any module-level string (banner, _CMDS,
# /help) sees the right locale.
init_lang()
# ════════════════════════════════════════════════════════════════════════════


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


def _enable_windows_vt_mode() -> None:
    """Enable UTF-8 + ANSI escape processing on Windows consoles when possible."""
    if not _IS_WINDOWS:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Make classic conhost/cmd decode UTF-8 bytes written by _w().  This is
        # harmless in mintty/Git Bash where these calls usually fail because the
        # std handles are pipes/ptys rather than Win32 console handles.
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        enable_vt = 0x0004
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | enable_vt)
    except Exception:
        # Safe fallback: modern terminals usually already support ANSI/UTF-8;
        # older conhost may render escape codes, but the TUI should not crash.
        pass


def _enter_utf8_charset() -> None:
    """Ask VT-compatible terminals to interpret subsequent bytes as UTF-8."""
    # ESC % G is the ISO-2022/VT sequence for selecting UTF-8.  It fixes some
    # mintty/Git-Bash launches where the child process inherits a legacy locale
    # and mojibakes UTF-8 box drawing/CJK into CP936-looking text.
    _w('\x1b%G')


def _ptk_keypress_to_bytes(kp) -> bytes:
    """Map prompt_toolkit KeyPress objects to tui_v3's internal byte protocol.

    prompt_toolkit normalizes platform-specific console input (Win32 console,
    ConPTY, mintty/msys pty) into symbolic Keys.  Keep the editor core small by
    translating those symbols back to the bytes already handled by _feed/_keys.
    """
    try:
        from prompt_toolkit.keys import Keys
    except Exception:
        Keys = None  # type: ignore[assignment]

    key = getattr(kp, 'key', None)
    data = getattr(kp, 'data', '') or ''

    # Printable text and paste chunks.  PTK may deliver a multi-character data
    # string for bracketed paste/typeahead; forwarding UTF-8 preserves CJK/emoji.
    if isinstance(data, str) and data and (len(data) > 1 or (len(data) == 1 and ord(data) >= 0x20 and data != '\x7f')):
        return data.encode('utf-8', 'replace')

    name = getattr(key, 'name', str(key))
    key_s = str(key)
    norm = name.lower().replace('_', '-').replace('keys.', '')
    norm_s = key_s.lower().replace('_', '-').replace('keys.', '')
    aliases = {norm, norm_s}

    def has(*needles: str) -> bool:
        return any(n in a for a in aliases for n in needles)

    # Enter submits; Ctrl+J / Shift+Enter insert newline when PTK can distinguish.
    if has('controlm', 'c-m') or key_s in ('\r', '\n'):
        return b'\r'
    if has('controlj', 'c-j', 's-enter', 'shift-enter'):
        return b'\n'

    # Navigation.  Existing _keys() uses these small control bytes.
    if has('up') and has('shift'):
        return b'\x1c'
    if has('down') and has('shift'):
        return b'\x1d'
    if has('left') and has('shift'):
        return b'\x1e'
    if has('right') and has('shift'):
        return b'\x1f'
    if has('up'):
        return b'\x10'
    if has('down'):
        return b'\x0e'
    if has('left'):
        return b'\x02'
    if has('right'):
        return b'\x06'
    if has('home'):
        return b'\x01'
    if has('end'):
        return b'\x05'
    if has('delete'):
        return b'\x7f'
    if has('backspace') or data == '\x7f' or data == '\x08':
        return b'\x7f'
    if has('escape') or data == '\x1b':
        return b'\x1b'

    ctrl = {
        'controla': b'\x01', 'c-a': b'\x01',
        'controlb': b'\x02', 'c-b': b'\x02',
        'controlc': b'\x03', 'c-c': b'\x03',
        'controld': b'\x04', 'c-d': b'\x04',
        'controle': b'\x05', 'c-e': b'\x05',
        'controlf': b'\x06', 'c-f': b'\x06',
        'controlh': b'\x7f', 'c-h': b'\x7f',
        'controlj': b'\n',   'c-j': b'\n',
        'controlk': b'\x0b', 'c-k': b'\x0b',
        'controll': b'\x0c', 'c-l': b'\x0c',
        'controln': b'\x0e', 'c-n': b'\x0e',
        'controlp': b'\x10', 'c-p': b'\x10',
        'controlu': b'\x15', 'c-u': b'\x15',
        'controlv': b'\x16', 'c-v': b'\x16',
        'controlx': b'\x18', 'c-x': b'\x18',
        'controly': b'\x19', 'c-y': b'\x19',
        'controlz': b'\x1a', 'c-z': b'\x1a',
    }
    for a in aliases:
        if a in ctrl:
            return ctrl[a]

    if isinstance(data, str) and data:
        return data.encode('utf-8', 'replace')
    return b''


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


def _grab_clipboard_file() -> tuple[str, bool] | None:
    """Return (path, is_image) from the clipboard via PIL — ported from v2.

    PIL.ImageGrab.grabclipboard() is the one cross-platform path that also
    works on Windows (osascript/xclip/wl-paste below don't).  It handles two
    shapes: a list of copied file paths, or a raw bitmap Image (saved to a
    temp PNG).  is_image distinguishes images (→ `[Image #N]`, sent to the
    model) from any other file (→ `[File #N]`, expanded to its path)."""
    try:
        from PIL import ImageGrab, Image
        data = ImageGrab.grabclipboard()
    except Exception:
        return None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str) and os.path.isfile(item):
                return (item, os.path.splitext(item)[1].lower() in _IMAGE_EXTS)
        return None
    if isinstance(data, Image.Image):
        try:
            os.makedirs(_TEMP_DIR, exist_ok=True)
            path = os.path.join(_TEMP_DIR, f'clip_{int(time.time() * 1000)}.png')
            data.save(path, 'PNG')
            return (path, True)
        except Exception:
            return None
    return None


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

# v2 fold_turns helpers (tuiapp_v2.py:240-267).  4-fence stash keeps a tool
# result's `` ``` `` from being misread as a turn boundary; the per-turn
# `<summary>` regex uses a negative lookahead so two adjacent summaries don't
# merge; the title cleaner strips fenced code + thinking before extraction.
_FENCE4_STASH_RE = re.compile(r'^`{4,}.*?^`{4,}\n?', re.DOTALL | re.MULTILINE)
_TURN_SPLIT_FOLD_RE = re.compile(r'(\*\*LLM Running \(Turn \d+\) \.\.\.\*\*)')
_SUMMARY_PERTURN_RE = re.compile(r'<summary>\s*((?:(?!<summary>).)*?)\s*</summary>', re.DOTALL)
_TITLE_CLEAN_RE = re.compile(r'`{3,}.*?`{3,}|<thinking>.*?</thinking>', re.DOTALL)
_TITLE_ARGS_TAIL_RE = re.compile(r',?\s*args:.*$')


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
            self._init_error = _t('err.no_llm')
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
# content (dim on white = unreadable grey). Keep normal prose inherited from the
# surrounding tile; avoid Rich's inline-code reverse without pinning prose dark.
_MD_THEME = Theme({
    'markdown.h1': 'bold underline', 'markdown.h2': 'bold underline',
    'markdown.h3': 'bold', 'markdown.h4': 'bold',
    'markdown.h5': 'bold', 'markdown.h6': 'bold',
    'markdown.strong': 'bold', 'markdown.em': 'italic',
    # Rich's default inline-code ``reverse`` can vanish on themed tiles; keep it
    # bold but inherited so it stays readable on both light and dark surfaces.
    'markdown.code': 'bold', 'markdown.code_block': 'none',
    'markdown.block_quote': 'italic', 'markdown.hr': 'none',
    'markdown.link': 'underline', 'markdown.link_url': 'underline',
    # Bullet inherits the surrounding foreground (a pinned dark hue vanished on
    # dark terminals); bold alone keeps it visible on any background.
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
_FILE_PH_RE = re.compile(r'\[File #(\d+)\]')
_IMG_PH_RE = re.compile(r'\[Image #(\d+)\]')
# All paste placeholders — used for whole-block delete (v2 parity): backspace
# flush against any of these wipes the entire placeholder, not one char.
_PLACEHOLDER_RES = (_PASTE_PH_RE, _IMG_PH_RE, _FILE_PH_RE)
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico'}
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


_FINAL_MARKER_RE = re.compile(
    r'\n*(?:`{3,5}\n*)?\[Info\]\s*Final response to user\.\n*(?:`{3,5})?\s*$')


def _strip_final_marker(text: str) -> str:
    """Drop the trailing `[Info] Final response to user.` marker (emitted by
    ga.do_no_tool, optionally fenced).  It's a conductor protocol signal, not
    user-facing content — desktop_bridge / app.js strip it the same way."""
    return _FINAL_MARKER_RE.sub('', text)


def _extract_user_text(entry) -> str:
    """Pull the plain user text out of a backend.history entry (str content
    or a content-block list). Ported from v2 — used to prefill the input box
    after /rewind."""
    c = entry.get('content') if isinstance(entry, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = [b.get('text', '') for b in c
                 if isinstance(b, dict) and b.get('type') == 'text']
        return '\n'.join(p for p in parts if p)
    return ''


# Slash-command spec for the `/` hint + Tab completion (only commands _cmd
# actually services). Built dynamically so /language switches relabel the
# palette and /help on the next render.
def _cmds() -> list[tuple[str, str, str]]:
    return [
        ('/help',     '',                       _t('cmd.help.desc')),
        ('/status',   '',                       _t('cmd.status.desc')),
        ('/llm',      _t('cmd.llm.arg'),        _t('cmd.llm.desc')),
        ('/btw',      _t('cmd.btw.arg'),        _t('cmd.btw.desc')),
        ('/review',   _t('cmd.review.arg'),     _t('cmd.review.desc')),
        ('/rewind',   _t('cmd.rewind.arg'),     _t('cmd.rewind.desc')),
        ('/continue', _t('cmd.continue.arg'),   _t('cmd.continue.desc')),
        ('/new',      _t('cmd.new.arg'),        _t('cmd.new.desc')),
        ('/rename',   _t('cmd.rename.arg'),     _t('cmd.rename.desc')),
        ('/clear',    '',                       _t('cmd.clear.desc')),
        ('/cost',     '',                       _t('cmd.cost.desc')),
        ('/verbose',  '',                       _t('cmd.verbose.desc')),
        ('/export',   _t('cmd.export.arg'),     _t('cmd.export.desc')),
        ('/stop',     '',                       _t('cmd.stop.desc')),
        ('/language', _t('cmd.language.arg'),   _t('cmd.language.desc')),
        ('/quit',     '',                       _t('cmd.quit.desc')),
    ]


def _heat(el: float) -> str:
    """Patience heat for the running spinner (ported from v2 _HEAT_RAMP):
    cool mint → amber → orange → red as the wait grows."""
    return ('\x1b[38;2;170;232;170m' if el < 20 else
            '\x1b[38;2;212;167;44m' if el < 60 else
            '\x1b[38;2;220;107;31m' if el < 180 else
            '\x1b[1m\x1b[38;2;255;44;44m')


# Spinner gerund pool — English only (ported from v2 _SPINNER_GERUNDS).
# Rotates every ~6 s so a long wait feels alive instead of stuck on one phrase.
_GERUNDS = SPINNER_GERUNDS


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


# Phrasing-based opt-in for multi-select picker — matches v2's _MULTI_RE so a
# question containing `[多选]`, `multi-select`, `select all` etc. (anywhere in
# the prompt) switches the inline picker from single- to multi-mode.
_MULTI_RE = re.compile(r"\[?(?:多选|multi(?:[-_ ]?select)?|select all)\]?", re.IGNORECASE)


def _visible_text(s: str) -> str:
    """Strip SGR escapes for display-width measurement.  sanitize_ansi keeps SGR
    intentionally, so PTK's ANSI parser can colorize; for cell-width math we
    need the bare visible characters."""
    return _ANSI_SGR_RE.sub('', sanitize_ansi(s))


def _ptk_x_from_cell(line: str, cell_x: int) -> int:
    """Convert a 0-based terminal cell column to PTK's character-index x.

    SB computes cursor columns in terminal cells, where CJK glyphs occupy two
    columns.  FormattedTextControl/ANSI cursor positions are indexes in the
    formatted-text line, where the same CJK glyph is one character/fragment.
    Feeding cell columns directly makes PTK place the cursor too far right and
    it overwrites/clears cells around wide characters."""
    target = max(0, int(cell_x))
    acc = 0
    idx = 0
    for ch in _visible_text(line):
        ch_w = max(1, cell_len(ch))
        if acc + ch_w > target:
            break
        acc += ch_w
        idx += 1
    return idx


def _is_mouse_or_scroll_keypress(kp) -> bool:
    """Filter out mouse/scroll events from PTK's key sequence so they don't
    feed into SB's Up/Down history navigation path."""
    key = getattr(kp, 'key', None)
    data = getattr(kp, 'data', '') or ''
    name = getattr(key, 'name', '')
    probe = f'{name} {key}'.lower()
    if 'mouse' in probe or 'scroll' in probe:
        return True
    if isinstance(data, str) and (data.startswith('\x1b[<') or data.startswith('\x1b[M')):
        return True
    return False


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
        HardBreakMarkdown(text, code_theme='monokai') if markdown else Text(text),
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
        return f'{int(s)}s'
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
        # Reentrant: helpers like _flush_esc lock internally yet are also called
        # from already-locked contexts (the maintenance loop). A plain Lock
        # deadlocks the whole TUI on a bare Esc; RLock lets the same thread
        # re-enter while still excluding the agent-runner thread.
        self._lk = threading.RLock()
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
        self._hist_stash = ''           # live draft preserved while browsing history
        self._session_name = ''         # set by /new <name>; shown in banner / status
        self._tip_idx = random.randrange(max(1, tip_count()))  # banner tip, fixed per launch
        self._btws: list[list] = []     # [question, answer|None] — answer None while in flight
        # Plan card state (v2 parity).  `_plan_items` is the last seen items;
        # `_plan_complete_since` / `_plan_lost_since` track grace periods to
        # avoid flicker on agent rewrites.  `_plan_path` / `_plan_mtime` cache
        # the last read so the 30ms spinner tick skips redundant file IO.
        self._plan_items: list[tuple[str, str]] = []
        self._plan_complete_since: float | None = None
        self._plan_lost_since: float | None = None
        self._plan_path: str = ''
        self._plan_mtime: float = 0.0
        self._fold_all = True           # Ctrl+O toggles: when True, assistant blocks with a
                                        # <summary> render as one `▸ {summary}` header in
                                        # scrollback; the full source replays when flipped off.
        self._cwd = os.path.join(os.getcwd(), 'temp')
        # All three keyed by paste id (_pc): _pstore text-paste id→content,
        # _fstore file-paste id→path, _imgs image-paste id→path.  Keying by id
        # lets a whole-block delete pop the right entry.
        self._pstore: dict[int, str] = {}; self._fstore: dict[int, str] = {}
        self._imgs: dict[int, str] = {}; self._pc = 0
        self._t0 = 0.0; self._spin = 0
        self._t0_anchor = 0.0           # frozen anchor for elapsed; resets only on state changes
        self._painted: list[str] = []
        self._prev_term_size: tuple[int, int] | None = None
        self._blocks: list[Block] = []                  # block-based scrollback history;
        self._streaming_block: Block | None = None     # the in-flight assistant block
        self._stream_turn_seen = 0     # turn-marker count last seen in current stream;
                                       # bumps trigger an incremental fold-repaint so
                                       # turn N collapses the moment turn N+1 marker
                                       # arrives (v2-style live folding).
        # Self-pipe for SIGWINCH delivery. PEP 475 makes Python auto-retry
        # os.read on EINTR even with siginterrupt(SIGWINCH, True) — especially
        # under iTerm split panes where the signal can be delivered while the
        # read is mid-syscall and silently dropped. The signal handler writes
        # a byte to this pipe; the main select() polls both stdin and the
        # pipe, so a resize always wakes the loop within select's timeout.
        sr, sw = os.pipe()
        if not _IS_WINDOWS:
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
        # PTK Application state (populated by _run_prompt_toolkit_application)
        self._ptk_app = None                     # prompt_toolkit.application.Application
        self._ptk_loop: asyncio.AbstractEventLoop | None = None
        self._ptk_cursor = None                  # prompt_toolkit Point set per render
        # Scrollback emit queue: lines waiting to be print_text()'d above the
        # PTK render area.  Populated by _emit_lines, drained by the async
        # maintenance loop via run_in_terminal(print_text).
        self._sbq: list[str] = []
        self._sbq_lk = threading.Lock()
        # When set, the next drain wipes screen+scrollback and re-prints the
        # entire rendered history at the current width.  Toggled by
        # _repaint_screen so banner/box borders reflow on terminal resize
        # instead of leaving stale rows in scrollback.
        self._pending_repaint = False
        # Per-render live-region cache so PTK's preferred_height query and the
        # text getter see the same content within a single render pass.
        self._live_cache: list[str] = ['']
        self._live_cache_w = -1
        self._live_cache_h = -1
        # ask_user picker state.  None = no picker (free text), 'single' =
        # arrow keys move highlight + Enter submits one, 'multi' = Space
        # toggles + Enter submits the joined set.  Any visible char typed
        # while a picker is active switches it back to None (free-text
        # escape hatch — the v2 "Type something" affordance).
        self._picker_mode: str | None = None
        self._picker_sel: int = 0
        self._picker_checked: set[int] = set()
        # Local menu picker — used by /llm, /continue, etc. to present an
        # arrow-key selectable list in place of the input box.  Distinct from
        # the ask_user picker (which sits inside an ask_card with a question
        # header and a free-text input field).  When _menu_active, the live
        # region renders _menu_card instead of _input_box; ↑↓/Enter/Esc are
        # captured before the normal input pipeline.
        self._menu_active: bool = False
        self._menu_options: list[str] = []
        self._menu_title: str = ''
        self._menu_hint: str = ''
        self._menu_sel: int = 0
        self._menu_scroll: int = 0          # index of the first visible row in the viewport
        self._menu_on_submit = None        # Callable[[int], None] | None
        self._menu_on_cancel = None        # Callable[[], None] | None
        # Interactive command palette: index into _cmd_matches output when
        # buf starts with `/`.  ↑↓ steer the highlight, Tab completes the
        # highlighted command, Enter still executes whatever is in buf.
        self._palette_sel: int = 0
        self._palette_scroll: int = 0       # viewport offset into the matches list

    # ── live region ──
    #
    # The live region is now owned by PTK's Application renderer.  See
    # _build_live_lines / _get_ptk_text / _get_live_height further down.
    # The old _paint / _goto_top helpers wrote ANSI to stdout directly; they
    # are removed.  Any remaining _painted/_live_rows/_parked_up writes left
    # in callers are harmless legacy resets (they zero state PTK ignores).

    def _status_line(self, w: int) -> str:
        name = self._bridge.llm_name if self._bridge else '?'
        if self._asking:
            state = _t('status.asking')
        elif self._running:
            el = time.time() - self._t0_anchor
            tps = ''
            if el >= 1 and self._stream:
                r = len(self._stream) / 4 / el        # ~chars→tokens, rough live rate
                if r >= 0.5:
                    tps = _t('status.tps', rate=r)
            state = f'{_gerund(el)} {_elapsed(el)}{tps}' + _t('status.running.tail')
        else:
            state = _t('status.ready')
        cost = _cost_str(self._bridge.agent) if self._bridge else ''
        return f'[main] {name} │ {state}{cost}'

    # v2-style plan card budget: 5 rows max — header(1) + optional step(1) +
    # tasks(rest) + optional overflow(1).  Grace periods avoid flicker when the
    # agent rewrites plan.md (transient empty read) or completes (auto-hide).
    _PLAN_GRACE_SEC = 3.0       # show "✓ complete" for this long, then hide
    _PLAN_LOST_GRACE_SEC = 5.0  # keep prior items visible during agent rewrites
                                # / brief working-state clears (longer than v2's
                                # 1.5s because v3 polls only on render, not on
                                # turn boundaries — and ga.py auto-exits plan
                                # mode whenever plan.md momentarily has 0 `[ ]`)

    def _agent_msgs(self, ag) -> list[str]:
        """Extract a list of text-content strings from agent history — what
        `plan_state.current_step` / `find_path_in_messages` consume.  History
        entries can be dicts (raw backend) or objects with `.content`."""
        hist = getattr(getattr(ag, 'llmclient', None), 'backend', None)
        hist = getattr(hist, 'history', None) or []
        out: list[str] = []
        for h in hist:
            c = h.get('content') if isinstance(h, dict) else getattr(h, 'content', None)
            if isinstance(c, list):
                c = '\n'.join(b.get('text', '') for b in c
                              if isinstance(b, dict) and b.get('type') == 'text')
            if isinstance(c, str) and c:
                out.append(c)
        return out

    def _plan_card(self, w: int) -> list[str]:
        """Render the plan/todo card above the input box (v2 parity, port of
        tuiapp_v2._refresh_planbar).  Returns [] when not in plan mode.

        Layout (5 rows max):
          📋 Plan (n_done/n_total)              ← header
            ▸ current step…                     ← optional, from `当前步骤：`
            ✔ done item                         ← undone first, then done
            ☐ open item
            ⋮ +N more                           ← when overflowing

        Cache file reads via mtime so the 30ms spinner tick doesn't open the
        plan file every frame."""
        if not self._bridge:
            return []
        ag = self._bridge.agent
        try:
            from frontends import plan_state
        except Exception:
            return []

        # Fresh read (mtime-gated to skip redundant IO).  Messages fallback
        # (v2 parity) so the card survives even when the agent transiently
        # pops `working['in_plan_mode']` — `plan_state.resolve_path` will
        # walk the message history for the most recent `plan_*/plan.md`.
        msgs_for_resolve = self._agent_msgs(ag)
        path = plan_state.resolve_path(ag, messages=msgs_for_resolve)
        active = plan_state.is_active(ag, messages=msgs_for_resolve)
        new_items: list = self._plan_items
        if path and os.path.isfile(path):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
            if path != self._plan_path or mtime != self._plan_mtime:
                self._plan_path = path
                self._plan_mtime = mtime
                try:
                    with open(path, encoding='utf-8', errors='replace') as f:
                        new_items = plan_state.extract(f.read())
                except OSError:
                    new_items = []
        elif not active:
            new_items = []

        # Grace tracking: detect complete edge + handle transient disappearance.
        now = time.time()
        prev = self._plan_items
        now_complete = bool(new_items) and plan_state.is_complete(new_items)
        was_complete = bool(prev) and plan_state.is_complete(prev)
        if now_complete and not was_complete:
            self._plan_complete_since = now
        elif not now_complete:
            self._plan_complete_since = None
        if not new_items and prev:
            if self._plan_lost_since is None:
                self._plan_lost_since = now
        elif new_items:
            self._plan_lost_since = None
            self._plan_items = new_items

        # Apply lost-grace expiry.
        items = self._plan_items
        if self._plan_lost_since is not None and now - self._plan_lost_since >= self._PLAN_LOST_GRACE_SEC:
            self._plan_items = []
            self._plan_lost_since = None
            items = []

        # Plan mode armed but no items written yet → placeholder card.
        if not items:
            if active:
                return self._plan_placeholder(w, ag)
            return []

        n_done, n_total = plan_state.summary(items)
        complete = plan_state.is_complete(items)
        if complete and self._plan_complete_since is not None:
            if now - self._plan_complete_since >= self._PLAN_GRACE_SEC:
                return []

        msgs = self._agent_msgs(ag)
        step = plan_state.current_step(msgs) if msgs else ''

        # 5-row budget allocation (matches v2 _refresh_planbar).
        budget = 4 - (1 if step else 0)
        ordered = ([x for x in items if x[1] != 'done'] +
                   [x for x in items if x[1] == 'done'])
        body_lines = budget - 1 if len(ordered) > budget else budget
        shown = ordered[:body_lines]
        overflow = max(0, len(ordered) - body_lines)

        head = (_t('plan.complete', n=n_total) if complete
                else _t('plan.header', done=n_done, total=n_total))
        rows = [_BOLD + _ACCENT + head + _RST]
        if step:
            rows.append(_ACCENT + '  ▸ ' + _RST + _DIM + step[:120] + _RST)
        for c, st in shown:
            if st == 'done':
                rows.append(_ACCENT + '  ✔ ' + _RST + _DIM + c + _RST)
            else:
                rows.append(_DIM + '  ☐ ' + _RST + c)
        if overflow:
            rows.append(_DIM + '  ⋮ ' + _t('plan.overflow', n=overflow) + _RST)
        # Clip each row to width and prepend the same left indent the btw card
        # uses, so plan + btw share a visual margin.
        out: list[str] = []
        for r in rows:
            out.append(' ' + _clip_cells(r, max(1, w - 1)))
        return out

    def _plan_placeholder(self, w: int, ag) -> list[str]:
        """Card shown when plan mode is armed but plan.md hasn't been written
        yet — covers the enter_plan_mode → first write gap."""
        try:
            from frontends import plan_state
        except Exception:
            return []
        msgs = self._agent_msgs(ag)
        path = (plan_state._stashed_plan_path(ag)
                or plan_state.find_path_in_messages(msgs)
                or '')
        hint = ('/'.join(path.replace('\\', '/').rstrip('/').split('/')[-2:])
                if path else 'plan.md')
        step = plan_state.current_step(msgs) if msgs else ''
        rows = [_BOLD + _ACCENT + _t('plan.placeholder') + _RST]
        if step:
            rows.append(_ACCENT + '  ▸ ' + _RST + _DIM + step[:120] + _RST)
        rows.append(_DIM + '  ' + _t('plan.waiting', path=hint) + _RST)
        out: list[str] = []
        for r in rows:
            out.append(' ' + _clip_cells(r, max(1, w - 1)))
        return out

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
        yet stays one logical line — must still roam). At the top/bottom visual
        row, one more ↑/↓ falls through to input history — including for a
        multi-line draft (v2 parity)."""
        segs = self._segs(max(1, _term()[0] - 6))
        i, off = self._seg_at(segs); ni = i + d
        if not 0 <= ni < len(segs):
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

    def _picker_init(self, ae) -> None:
        """Initialize picker state for a fresh ask_user event.  Pickers only
        activate when the event has candidates; otherwise this is a no-op and
        the user just types free text."""
        if ae is None or not getattr(ae, 'candidates', None):
            self._picker_mode = None
            self._picker_sel = 0
            self._picker_checked = set()
            return
        q = ae.question or ''
        self._picker_mode = 'multi' if _MULTI_RE.search(q) else 'single'
        self._picker_sel = 0
        self._picker_checked = set()

    def _picker_reset(self) -> None:
        self._picker_mode = None
        self._picker_sel = 0
        self._picker_checked = set()

    def _show_menu(self, title: str, options: list[str], on_submit,
                   hint: str | None = None, on_cancel=None) -> None:
        """Open a modal arrow-key menu in place of the input box.

        The menu takes over the live region; ↑↓ move the highlight, Enter
        invokes `on_submit(idx)`, Esc invokes `on_cancel()` (if provided).
        Submission auto-closes the menu before invoking the callback so the
        callback is free to open another menu / commit / start a task."""
        if not options:
            return
        self._menu_active = True
        self._menu_options = list(options)
        self._menu_title = title
        self._menu_hint = hint if hint is not None else _t('menu.hint')
        self._menu_sel = 0
        self._menu_scroll = 0
        self._menu_on_submit = on_submit
        self._menu_on_cancel = on_cancel
        self._render_live()

    def _close_menu(self) -> None:
        self._menu_active = False
        self._menu_options = []
        self._menu_title = ''
        self._menu_hint = ''
        self._menu_sel = 0
        self._menu_scroll = 0
        self._menu_on_submit = None
        self._menu_on_cancel = None

    @staticmethod
    def _scroll_window(sel: int, total: int, visible: int, scroll: int) -> int:
        """Adjust `scroll` so that `sel` stays within the visible window of
        size `visible`.  Returns the new scroll offset."""
        if total <= visible:
            return 0
        if sel < scroll:
            return max(0, sel)
        if sel >= scroll + visible:
            return min(total - visible, sel - visible + 1)
        return max(0, min(total - visible, scroll))

    def _menu_submit(self) -> None:
        cb = self._menu_on_submit
        sel = self._menu_sel
        if not self._menu_active:
            return
        self._close_menu()
        if cb is not None:
            try:
                cb(sel)
            except Exception as e:
                self.commit([_t('err.menu_cb', err=str(e))])

    def _menu_cancel(self) -> None:
        cb = self._menu_on_cancel
        if not self._menu_active:
            return
        self._close_menu()
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _picker_submit(self) -> str | None:
        """Return the answer text for the current picker selection, or None
        if picker is inactive or selection is empty."""
        ae = self._asking
        if not ae or not ae.candidates or not self._picker_mode:
            return None
        if self._picker_mode == 'multi':
            if not self._picker_checked:
                # treat Enter on empty multi as picking the highlighted row
                return ae.candidates[self._picker_sel] if 0 <= self._picker_sel < len(ae.candidates) else None
            picked = [ae.candidates[i] for i in sorted(self._picker_checked) if 0 <= i < len(ae.candidates)]
            return '; '.join(picked) if picked else None
        # single
        if 0 <= self._picker_sel < len(ae.candidates):
            return ae.candidates[self._picker_sel]
        return None

    def _cmd_matches(self, prefix: str) -> list[tuple[str, str, str]]:
        p = prefix.strip().lower()
        return [c for c in _cmds() if c[0].startswith(p)]

    def _palette_visible(self) -> bool:
        """True when the live `/`-command palette should appear and own ↑↓/Tab."""
        if self._asking is not None or self._menu_active:
            return False
        if '\n' in self.buf or not self.buf.startswith('/'):
            return False
        ms = self._cmd_matches(self.buf)
        if not ms:
            return False
        if len(ms) == 1 and ms[0][0] == self.buf.strip():
            return False
        return True

    def _hint_lines(self, w: int) -> list[str]:
        """Live `/`-command palette: scrollback-style list with an arrow-key
        highlight + scrolling viewport.  ↑↓ move the highlight (handled in
        `_keys`), Tab completes the highlighted command, Enter completes into
        the input box.  Long match lists scroll the visible window as sel walks
        past the edges (no wrap-around, no "N more" chrome)."""
        if not self._palette_visible():
            return []
        ms = self._cmd_matches(self.buf)
        total = len(ms)
        # Cap palette viewport to 6 rows so it doesn't squeeze the input box.
        visible = min(total, 6)
        # Clamp sel + slide scroll so sel is in-window.
        if self._palette_sel < 0 or self._palette_sel >= total:
            self._palette_sel = 0
        self._palette_scroll = self._scroll_window(self._palette_sel, total, visible, self._palette_scroll)
        start = self._palette_scroll
        end = min(total, start + visible)
        out: list[str] = []
        for i in range(start, end):
            n, a, d = ms[i]
            row = f'  {n:<10}{a:<7} {d}'
            if i == self._palette_sel:
                out.append(_ACCENT + _BOLD + _clip_cells(row, w) + _RST)
            else:
                out.append(_DIM + _clip_cells(row, w) + _RST)
        return out

    def _tab(self) -> None:
        if self._asking is not None or self._menu_active:
            return
        if '\n' in self.buf or not self.buf.startswith('/'):
            return
        ms = self._cmd_matches(self.buf)
        if not ms:
            return
        if len(ms) == 1:
            n, a, _ = ms[0]; self.buf = n + (' ' if a else '')
        else:
            # Tab always completes to whichever entry the palette currently
            # highlights (defaults to 0 = first match).  Use the full match
            # list — the palette's scrolling viewport may have walked past
            # the first 6 items, so a raw `ms[:6]` index would be stale.
            idx = self._palette_sel if 0 <= self._palette_sel < len(ms) else 0
            n, a, _ = ms[idx]
            self.buf = n + (' ' if a else '')
        self.pos = len(self.buf)
        self._palette_sel = 0
        self._palette_scroll = 0
        self.pos = len(self.buf)

    def _esc_back(self) -> None:
        """Universal back: cancel menu → cancel ask → clear btw panel → clear
        draft → stop running. Esc has NO exit capability — quitting is Ctrl+C×2
        or Ctrl+D only. The btw panel is cleared outright (no history kept); an
        in-flight side-question then lands on an orphan and never reappears.
        Draft-clear comes before running-stop so typing the next prompt mid-run
        and pressing Esc just discards what you typed."""
        if self._menu_active:
            self._menu_cancel(); return
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
            self._picker_reset()
            self.commit([_DIM + _t('msg.ask_cancelled') + _RST]); return
        if self._btws:                                # clear the side-question panel
            self._btws = []                           # in-flight answers land on orphans
            return
        if self.buf:
            self._snap()                              # let Ctrl+Z restore the draft
            self.buf = ''; self.pos = 0; self._sel = None; return
        if self._running and self._bridge:
            self._bridge.abort()
            self.commit([_DIM + _t('msg.abort_requested') + _RST]); return

    def _ask_card(self, w: int) -> tuple[list[str], int, int]:
        """Single unified card for ask_user: question + candidates + INLINE
        input + hint all inside one accent-bordered box. Returns the same
        triple as _input_box (lines, caret_row_within_lines, caret_col) so
        the caller treats it uniformly."""
        ae = self._asking
        if w < 24:
            rows: list[str] = []
            for ln in (ae.question or _t('ask.default_q')).strip().split('\n'):
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
        label = _t('ask.title') + (_t('ask.pending', n=pending) if pending else '')
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
        for ln in (ae.question or _t('ask.default_q')).strip().split('\n'):
            rows.extend(row(ln, _BOLD))
        if ae.candidates:
            rows.extend(row(''))
            # Render each candidate.  Picker mode adds a highlight on the
            # current row and (in multi) a [ ]/[x] marker; in free-text mode
            # candidates show only as numbered hints — typing the number
            # still picks that row at submit time.
            multi = self._picker_mode == 'multi'
            for i, c in enumerate(ae.candidates):
                if multi:
                    mark = '[x]' if i in self._picker_checked else '[ ]'
                    body = f'  {mark} {i + 1}. {c}'
                else:
                    body = f'  {i + 1}. {c}'
                if self._picker_mode and i == self._picker_sel:
                    rows.extend(row(body, _ACCENT + _BOLD))
                else:
                    rows.extend(row(body))
        # Multi mode is "checkbox-only" — no input box.  Free-text doesn't
        # combine naturally with multi-pick semantics, and hiding the input
        # keeps the candidate list (with its [x]/[ ] marks) always visible.
        # Single mode keeps the input box for the focus-cycle UX.
        if multi:
            crow, ccol = len(rows) - 1, 0       # cursor is hidden in picker mode
        else:
            rows.extend(row(''))                # gap between info & input

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
        if self._picker_mode == 'multi':
            hint = _t('ask.hint.multi')
        elif self._picker_mode == 'single':
            hint = _t('ask.hint.single')
        else:
            hint = _t('ask.hint.freetext')
        rows.extend(row(hint, _DIM))
        rows.append(bot)
        return rows, crow, ccol

    def _menu_visible_count(self, h: int) -> int:
        """How many menu rows fit in the current viewport.  Leaves room for
        title + bottom border + gap + hint + status line."""
        # Budget: title 1 + bottom border 1 + gap 1 + hint 1 + status 2 ≈ 6
        return max(3, h - 6)

    def _menu_card(self, w: int) -> tuple[list[str], int, int]:
        """Modal arrow-key menu rendered in place of the input box.

        Layout mirrors _ask_card's accent-bordered box: title at the top, one
        row per option with the highlighted row shown in bold accent, a hint
        line at the bottom.  Long lists use a scrolling viewport — sel stays
        within the visible window, scrolling adjusts as ↑↓ walk past edges.

        Returns (lines, caret_row, caret_col) to match _input_box's signature;
        caret column is set to (0, 1) so PTK hides the block cursor (no
        visible caret while a menu is open)."""
        total = len(self._menu_options)
        # Use PTK's current viewport height (set on SB._h by the render loop).
        h = max(8, getattr(self, '_h', 24))
        visible = min(total, self._menu_visible_count(h))
        # Clamp sel and recompute scroll so sel is in-window.
        self._menu_sel = max(0, min(total - 1, self._menu_sel)) if total else 0
        self._menu_scroll = self._scroll_window(self._menu_sel, total, visible, self._menu_scroll)
        start = self._menu_scroll
        end = min(total, start + visible)

        if w < 24:
            rows = [_clip_cells(self._menu_title, w)]
            for i in range(start, end):
                marker = '▌' if i == self._menu_sel else ' '
                rows.append(_clip_cells(f'{marker} {self._menu_options[i]}', w))
            return rows, 0, 1
        inner = max(8, w)
        content_w = max(1, inner - 4)
        label = self._menu_title or _t('menu.default_title')
        scroll_tag = f'  {self._menu_sel + 1}/{total}' if total > visible else ''
        full_label = label + (_DIM + scroll_tag + _RST if scroll_tag else '')
        label_max = max(1, inner - 5)
        # cell_len ignores ANSI so this measures real visible width
        if cell_len(_visible_text(full_label)) > label_max:
            full_label = _clip_cells(full_label, label_max)
        fill = max(1, inner - 3 - cell_len(_visible_text(' ' + full_label + ' ')))
        top = (_ACCENT + '╭─' + _RST + ' ' + _BOLD + _ACCENT + full_label + _RST +
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
        # Viewport scrolls as sel walks past the edges; the title's N/total tag
        # signals position, so no "N more" indicator rows.
        for i in range(start, end):
            style = (_ACCENT + _BOLD) if i == self._menu_sel else ''
            rows.extend(row(self._menu_options[i], style))
        rows.extend(row(''))
        rows.extend(row(self._menu_hint or _t('menu.hint'), _DIM))
        rows.append(bot)
        return rows, 0, 1

    def _btw_card(self, w: int) -> list[str]:
        """Ephemeral side-question panel above the input box: every /btw and
        its answer, newest last.  The question shows immediately (answer area
        reads `querying…` until it lands).  Lives only in the live region
        (never scrollback); Esc clears it.  Earlier replies are NOT folded."""
        if not self._btws:
            return []
        # Side panel — left-aligned but inset a few columns from the margin,
        # and narrower than the full input box, so it reads as an aside.
        indent = 3
        inner = max(8, min(w - indent, 72))
        content_w = max(1, inner - 4)
        n = len(self._btws)
        label = _t('btw.title') + (_DIM + f'  ×{n}' + _RST if n > 1 else '')
        label_max = max(1, inner - 5)
        if cell_len(_visible_text(label)) > label_max:
            label = _clip_cells(label, label_max)
        fill = max(1, inner - 3 - cell_len(_visible_text(' ' + label + ' ')))
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

        out = [top]
        for i, (q, a) in enumerate(self._btws):
            if i:
                out.extend(row(''))                  # blank gap between entries
            if a is None:                            # still in flight
                out.extend(row(f'> /btw {q}', _DIM))
                out.extend(row(_t('btw.querying'), _ACCENT))
            else:
                for ln in a.split('\n'):
                    out.extend(row(ln, _DIM))
        out.append(bot)
        # Small left indent so the panel doesn't sit flush against the margin.
        if indent and inner + indent <= w:
            out = [' ' * indent + ln for ln in out]
        return out

    def _input_box(self, w: int) -> list[str]:
        """A full-width bordered, padded input box (cc-style). Lives in the
        redraw region only — border glyphs never reach scrollback/copy. The
        caret (row/col) is derived from self.pos so ←→↑↓ edit in place. In
        ask-mode the answer is typed INSIDE the question card itself (one
        unified component) — short-circuit to _ask_card.  When a modal
        menu (e.g. /llm picker) is active, _menu_card replaces the input box."""
        if self._menu_active:
            return self._menu_card(w)
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
        max_live = max(1, h - 1)
        after: list[str] = []
        if self._running and self._asking is None:
            el = time.time() - self._t0_anchor
            after.append(' ' + _heat(el) + _pet(el, self._spin) + _RST +
                         '  ' + _DIM + _gerund(el) + '…' + _RST)
        # Plan card sits above the btw card — it's longer-lived context and
        # belongs further from the input area than transient side-questions.
        # Hidden while a modal menu owns the live region.
        if not self._menu_active:
            plan_rows = self._plan_card(w)
            if plan_rows:
                after += plan_rows
        # Side-question panel sits just above the input box (hidden while a
        # modal menu owns the live region).
        if self._btws and not self._menu_active:
            after += self._btw_card(w)
        box_start = len(after)
        box, caret_row, caret_col = self._input_box(w)
        after += box
        after += self._hint_lines(w)
        # A modal menu picker or the live `/`-command palette owns the live
        # region — drop the status line so the list isn't crowded by the
        # [main] … chrome.
        if not self._menu_active and not self._palette_visible():
            if 0 < time.time() - self._cc_t < 1:
                # Ctrl+C armed: clear the status bar down to just the quit
                # prompt so it stands out (v2 parity).  Uses the input box's
                # accent color so the prompt reads as part of that component.
                after.append(_BOLD + _ACCENT + _clip_cells('  ' + _t('status.cc_confirm'), w) + _RST)
            elif self._running and self._asking is None:
                lead = _heat(time.time() - self._t0_anchor) + _SPIN[self._spin % len(_SPIN)] + ' ' + _RST
                after.append(lead + _DIM + _clip_cells(self._status_line(w), max(2, w - 2)) + _RST)
            else:
                after.append(_DIM + _clip_cells(self._status_line(w), w) + _RST)
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
        """Request a live-region repaint.  PTK Application owns the live region
        now — this method just invalidates the app so PTK rebuilds the cache and
        rerenders.  The old stdout-based paint/cursor-park logic is gone."""
        self._invalidate_ptk()

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
        """Queue finalized lines for emission to the terminal's native scrollback.

        Old behavior wrote ANSI directly via _w() and competed with PTK's
        renderer for stdout.  Now lines are queued and the async maintenance
        loop drains them via run_in_terminal(app.print_text), which moves PTK
        out of the way, prints into scrollback above the live region, then lets
        PTK re-render its area on top."""
        if not lines:
            self._invalidate_ptk()
            return
        out: list[str] = []
        for ln in lines:
            out.extend(_fit_rows(ln, w))
        with self._sbq_lk:
            self._sbq.extend(out)
        # Reset legacy paint state — PTK owns the live region; these counters
        # are kept as zero so any stray legacy code path that reads them sees
        # "nothing painted" rather than ghost positions.
        self._painted = []; self._live_rows = 0; self._parked_up = 0
        self._schedule_drain()
        self._invalidate_ptk()

    # ── PTK presentation plumbing ──

    def _invalidate_ptk(self) -> None:
        """Tell PTK to schedule a re-render of the live region."""
        app = self._ptk_app
        if app is not None:
            app.invalidate()

    def _ptk_size(self) -> tuple[int, int]:
        """Current terminal size, preferring PTK's view of it (which can differ
        from os.get_terminal_size on Windows ConPTY mid-resize)."""
        app = self._ptk_app
        if app is not None:
            try:
                sz = app.output.get_size()
                return max(1, int(sz.columns)), max(1, int(sz.rows))
            except Exception:
                pass
        return _term()

    def _schedule_drain(self) -> None:
        """Wake the scrollback drain task from any thread."""
        loop = self._ptk_loop
        app = self._ptk_app
        if loop is None or app is None:
            return
        loop.call_soon_threadsafe(self._kick_drain)

    def _kick_drain(self) -> None:
        app = self._ptk_app
        if app is None:
            return
        app.create_background_task(self._drain_async())

    async def _drain_async(self) -> None:
        """Drain the scrollback queue (or handle a pending repaint).

        Resize path: when _pending_repaint is set, wipe screen+scrollback and
        re-emit all rendered blocks at the current width — old scrollback
        content was baked at the previous width and can't reflow on its own."""
        from prompt_toolkit.application import run_in_terminal
        from prompt_toolkit.formatted_text import ANSI as _ANSI
        app = self._ptk_app
        if app is None:
            return

        if self._pending_repaint:
            w = self._ptk_size()[0]
            with self._lk:
                self._pending_repaint = False
                # Drop queued items — they are about to be re-rendered as part
                # of the full history below.  Holding both would double-print.
                with self._sbq_lk:
                    self._sbq = []
                hist_all = self._render_all_blocks(w)
            hist_fit: list[str] = []
            for ln in hist_all:
                hist_fit.extend(_fit_rows(ln, w))
            body = '\r\n'.join(hist_fit) + ('\r\n' if hist_fit else '')
            # \x1b[3J clears scrollback (xterm/iTerm/wt/most modern terms);
            # \x1b[2J clears viewport; \x1b[H homes cursor.  Combined they
            # reset both regions so we can replay history from scratch.
            payload = '\x1b[3J\x1b[2J\x1b[H' + body

            def _do_repaint() -> None:
                try:
                    app.output.write_raw(payload)
                    app.output.flush()
                except Exception:
                    pass

            try:
                await run_in_terminal(_do_repaint)
            except Exception:
                pass
            self._invalidate_ptk()
            return

        with self._sbq_lk:
            if not self._sbq:
                return
            batch = self._sbq
            self._sbq = []
        text = '\n'.join(batch) + '\n'

        def _do_print() -> None:
            try:
                app.print_text(_ANSI(text))
            except Exception:
                pass

        try:
            await run_in_terminal(_do_print)
        except Exception:
            pass

    def _build_live_lines(self) -> list[str]:
        """Build the live region (input box + status + spinner + plan + open
        stream tail) at PTK's current size and cache the result.  Same content
        feeds both PTK's height query and its text getter within a render
        pass."""
        w, h = self._ptk_size()
        with self._lk:
            # _live_lines uses _term() internally; SB.{_w,_h} feed into
            # _input_box width math.  Sync both before building so a resize
            # shows up in this very render pass.
            try:
                self._w, self._h = w, h  # type: ignore[attr-defined]
            except Exception:
                pass
            if self._stream and self._streaming_block is not None:
                safe_src = self._streaming_block.source
                open_src = sanitize_ansi(self._stream)[len(safe_src):]
                saved_base = self._tool_base
                self._tool_base = self._pre_streaming_tool_base() + self._streaming_block.tool_n
                open_body = self._render_assistant(open_src, max(1, w - 2)) if open_src.strip() else []
                self._tool_base = saved_base
                self._live_tail = _indent_rows(open_body[-8:], w)

            # _live_lines reads _term() for its budget; redirect it to PTK's
            # size so the input-box border math matches the actual viewport.
            this_mod = sys.modules[__name__]
            saved_term = this_mod._term
            this_mod._term = lambda: (w, h)
            try:
                live = self._live_lines()
            finally:
                this_mod._term = saved_term

            clipped: list[str] = []
            for ln in live:
                visible = _visible_text(ln)
                if cell_len(visible) > w:
                    clipped.append(_clip_ansi_cells(ln, w))
                else:
                    clipped.append(ln)

            from prompt_toolkit.data_structures import Point as _Point
            row, col = self._cur
            cy = max(0, min(max(0, len(clipped) - 1), row))
            cell_cx = max(0, min(max(0, w - 1), col - 1))
            cursor_line = clipped[cy] if 0 <= cy < len(clipped) else ''
            self._ptk_cursor = _Point(x=_ptk_x_from_cell(cursor_line, cell_cx), y=cy)

            self._live_cache = clipped if clipped else ['']
            self._live_cache_w = w
            self._live_cache_h = h
            return self._live_cache

    def _ensure_live_cache(self) -> list[str]:
        """Return _live_cache, rebuilding if the cached size doesn't match the
        current terminal.  Safety net for code paths that touch the getters
        outside the normal render cycle."""
        w, h = self._ptk_size()
        if (self._live_cache_w != w or self._live_cache_h != h or not self._live_cache):
            return self._build_live_lines()
        return self._live_cache

    def _get_ptk_text(self):
        from prompt_toolkit.formatted_text import ANSI as _ANSI
        return _ANSI('\n'.join(self._ensure_live_cache()))

    def _get_ptk_cursor(self):
        return self._ptk_cursor

    def _get_live_height(self):
        from prompt_toolkit.layout.dimension import Dimension as _Dimension
        cache = self._ensure_live_cache()
        n = max(1, len(cache))
        return _Dimension(min=1, max=n, preferred=n)

    def _fold_turns(self, text: str) -> list[dict]:
        """Split assistant text into fold/text segments (v2 fold_turns port,
        tuiapp_v2.py:240-267).  In v2 a fold unit is a TURN (which may contain
        one or more tool calls), not a single tool — but in this agent's
        format every turn is typically `<summary>…</summary> + 🛠️ Tool: …`,
        so per-turn ≈ per-tool in practice.

        Returns:
            [{'type': 'text', 'content': str}, ...]  - prose / final-turn body
            [{'type': 'fold', 'title': str, 'content': str}, ...]  - foldable turn
        """
        placeholders: list[str] = []
        def stash(m):
            placeholders.append(m.group(0))
            return f'\x00PH{len(placeholders) - 1}\x00'
        safe = _FENCE4_STASH_RE.sub(stash, text)
        parts = _TURN_SPLIT_FOLD_RE.split(safe)
        parts = [re.sub(r'\x00PH(\d+)\x00',
                        lambda m: placeholders[int(m.group(1))], p) for p in parts]
        if len(parts) < 4:                                  # 0 or 1 turn marker
            return [{'type': 'text', 'content': text}]
        segs: list[dict] = []
        if parts[0].strip():
            segs.append({'type': 'text', 'content': parts[0]})
        turns = [(parts[i], parts[i + 1] if i + 1 < len(parts) else '')
                 for i in range(1, len(parts), 2)]
        for idx, (marker, content) in enumerate(turns):
            if idx == len(turns) - 1:                       # final turn = text
                segs.append({'type': 'text', 'content': marker + content})
                continue
            cleaned = _TITLE_CLEAN_RE.sub('', content)
            ms = _SUMMARY_PERTURN_RE.findall(cleaned)
            if ms:
                title = ms[0].strip().split('\n', 1)[0]
            else:
                first = cleaned.strip().split('\n', 1)[0] or marker.strip('*')
                title = _TITLE_ARGS_TAIL_RE.sub('', first)
            if len(title) > 72:
                title = title[:72] + '...'
            segs.append({'type': 'fold', 'title': title, 'content': content})
        return segs

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
            if self._fold_all:
                # v2-parity per-turn fold (tuiapp_v2.py:fold_turns).  Each non-
                # last turn collapses to one `▸ {summary}` header; the final
                # turn (current reply) stays as text.  Fold-seg bodies are
                # rendered internally and discarded — keeps tid counting
                # exact so /verbose tids don't shift when Ctrl+O toggles.
                segs = self._fold_turns(b.source)
                if any(s['type'] == 'fold' for s in segs):
                    out: list[str] = []
                    saved_base = self._tool_base
                    total_tool_n = 0
                    for seg in segs:
                        self._tool_base = saved_base + total_tool_n
                        body = self._render_assistant(seg['content'], max(1, w - 2))
                        total_tool_n += self._last_tool_n
                        if seg['type'] == 'fold':
                            head = _ACCENT + '▸ ' + _RST + _DIM + seg['title'] + _RST
                            out.extend(_indent_rows([head], w))
                        else:
                            out.extend(_indent_rows(body, w))
                    self._tool_base = saved_base
                    self._last_tool_n = total_tool_n
                    b.tool_n = total_tool_n
                    return out + ['']
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
        lbl_model = _t('banner.label.model')
        lbl_dir = _t('banner.label.directory')
        lbl_sess = _t('banner.label.session')
        sess_val = self._session_name or _t('banner.session.single')
        llm_hint = _t('banner.llm_hint')
        rows = [(_ACCENT + '>_' + _RST + ' GenericAgent', '>_ GenericAgent'),
                ('', ''),
                (f'{d}{lbl_model}{r}       {name}   {d}{llm_hint}{r}',
                 f'{lbl_model}       {name}   {llm_hint}'),
                (f'{d}{lbl_dir}{r}   {cwd}', f'{lbl_dir}   {cwd}'),
                (f'{d}{lbl_sess}{r}     {sess_val}', f'{lbl_sess}     {sess_val}')]
        top = _border('╭', '╮', w)
        bot = _border('╰', '╯', w)
        lines = ['', top]
        lines += [self._boxln(p, c, w) for c, p in rows]
        lines += [bot, '',
                  f'  {d}{tip(self._tip_idx)}{r}', '']
        if self._bridge and not self._bridge._healthy:
            lines.append(f'  {d}⚠ {self._bridge._init_error}{r}'); lines.append('')
        return lines

    def _repaint_screen(self) -> None:
        """Schedule a full repaint of viewport + scrollback at current width.

        scrollback can't reflow on its own — once a banner is in the terminal
        history buffer at width W1, resizing to W2 leaves it stretched.  We
        flip _pending_repaint and let the async drain wipe the screen and
        replay all blocks at the new width.  The in-flight stream tail is also
        re-rendered into _live_tail so a mid-stream resize snaps to the new
        width on the next PTK redraw."""
        w, _h = self._ptk_size()
        if self._stream and self._streaming_block is not None:
            safe_src = self._streaming_block.source
            open_src = sanitize_ansi(self._stream)[len(safe_src):]
            saved_base = self._tool_base
            self._tool_base = self._pre_streaming_tool_base() + self._streaming_block.tool_n
            open_body = self._render_assistant(open_src, max(1, w - 2)) if open_src.strip() else []
            self._tool_base = saved_base
            self._live_tail = _indent_rows(open_body[-8:], w)
        self._pending_repaint = True
        self._schedule_drain()
        self._invalidate_ptk()

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

    def _placeholder_at(self, side: str) -> tuple[int, int, int] | None:
        """If a paste placeholder sits flush against the caret, return
        (start, end, sid).  `side='left'` → the placeholder *ends* at the caret
        (backspace target).  Mirrors v2's `_placeholder_adjacent`."""
        if self._sel is not None:
            return None
        for pat in _PLACEHOLDER_RES:
            for m in pat.finditer(self.buf):
                edge = m.end() if side == 'left' else m.start()
                if edge == self.pos:
                    return (m.start(), m.end(), int(m.group(1)))
        return None

    def _handle_paste(self, text: str = '') -> None:
        """Unified paste entry.  Bracketed paste passes the payload `text`;
        Ctrl+V passes nothing so we read the clipboard ourselves.

        v2 order: a copied file / bitmap on the clipboard wins over text — so
        an image paste still works even when the terminal delivers an (empty)
        bracketed-paste event instead of a raw Ctrl+V key."""
        grab = _grab_clipboard_file()              # PIL: copied file or bitmap
        if grab:
            self._add_clip_file(*grab); return
        if text:
            self._paste_text(text); return
        # No text payload → Ctrl+V, or an empty bracketed paste with an image
        # on the clipboard.  Try the legacy bitmap grabber, then clipboard text.
        img = clip.paste_image()                   # legacy fallback (osascript/xclip)
        if img:
            self._pc += 1; self._imgs[self._pc] = img
            self._insert(f'[Image #{self._pc}]'); return
        txt = clip.paste()
        if txt:
            self._paste_text(txt)

    def _handle_clip_paste(self) -> None:
        self._handle_paste()

    def _add_clip_file(self, path: str, is_image: bool) -> None:
        """Fold a pasted file/image into a placeholder (v2 parity).  Images go
        through `_imgs` (sent to the model); other files get a `[File #N]`
        placeholder that `_expand` later swaps for the path."""
        self._pc += 1
        if is_image:
            self._imgs[self._pc] = path
            self._insert(f'[Image #{self._pc}]')
        else:
            self._fstore[self._pc] = path
            self._insert(f'[File #{self._pc}]')

    def _try_paste_path(self, raw: str) -> bool:
        """Git-bash / mintty fallback (v2 `_paste_file_from_text`): some
        screenshot tools put the file *path* on the clipboard as plain text.
        A single-line, on-disk path is treated as a file/image paste."""
        path = raw.strip().strip('"').strip("'")
        if not path or '\n' in path or '\r' in path or len(path) > 1024:
            return False
        if not os.path.isfile(path):
            return False
        self._add_clip_file(path, os.path.splitext(path)[1].lower() in _IMAGE_EXTS)
        return True

    def _paste_text(self, txt: str) -> None:
        txt = txt.replace('\r\n', '\n').replace('\r', '\n')
        if self._try_paste_path(txt):              # a pasted file path → file paste
            return
        lines = len(txt.splitlines()) or 1
        if lines > 2:                              # fold multi-line paste (v2: >2 lines)
            self._pc += 1; self._pstore[self._pc] = txt
            self._insert(f'[Pasted text #{self._pc} +{lines} lines]')
        else:
            self._insert(txt)

    def _nav_hist(self, d: int) -> None:
        # v2 parity: a multi-line draft can still reach history (no '\n' guard);
        # the live draft is stashed on entry and restored when walking back
        # past the newest entry.
        if not self.hist:
            return
        if self._hi == -1:
            if d == -1:
                self._hist_stash = self.buf           # preserve the live draft
                self._hi = len(self.hist) - 1
            else:
                return
        else:
            self._hi += d
        if self._hi < 0:
            self._hi = 0
        self._snap()                                  # let Ctrl+Z undo a history recall
        if self._hi >= len(self.hist):                # walked past newest → restore draft
            self._hi = -1
            self.buf = self._hist_stash; self.pos = len(self.buf)
            return
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
        # `[File #N]` / `[Image #N]` placeholders expand to the real path inline
        # (v2 parity) — that's how the model actually sees the file/image; the
        # bare `[Image #N]` block alone tells it nothing.
        for num, path in self._fstore.items():
            t = _FILE_PH_RE.sub(lambda m: path if int(m.group(1)) == num else m.group(0), t)
        for num, path in self._imgs.items():
            t = _IMG_PH_RE.sub(lambda m: path if int(m.group(1)) == num else m.group(0), t)
        return t

    def _on_enter(self) -> None:
        if self._asking is not None:
            ae = self._asking
            ans = self.buf.strip()
            # Focus model: picker mode active → submit the highlighted
            # candidate (or multi-pick `;`-join), ignoring whatever's in the
            # buf draft.  The user can switch focus to the input via ↑↓ /
            # printable char first if they want their typed text to win.
            if self._picker_mode:
                picked = self._picker_submit()
                if picked is not None:
                    ans = picked
            elif ans.isdigit() and 1 <= int(ans) <= len(ae.candidates):
                ans = ae.candidates[int(ans) - 1]
            if not ans:
                return
            self.buf = ''; self.pos = 0; self._asking = None
            self._undo.clear(); self._redo.clear(); self._sel = None
            self._picker_reset()
            self._commit_user(_t('msg.answer_prefix', text=ans))
            self._submit(ans, [])
            try:                                              # parallel sub-agent asks:
                self._asking = self._bridge.ask_user_queue.get_nowait()
                self._picker_init(self._asking)
            except queue.Empty:                                # if more were queued behind
                self._picker_reset()                            # this one, surface the next
            return                                              # immediately so the user
                                                                # can answer them in series
        # Interactive command palette: Enter completes the highlighted match
        # into the input box and stops — it does NOT dispatch.  The user then
        # reviews / edits the command and presses Enter again to run it (the
        # palette is hidden once buf is an exact command name).
        if self._palette_visible():
            self._tab()
            return
        raw = self.buf.strip()
        if not raw:
            return
        self.buf = ''; self.pos = 0; self._hi = -1; self._hist_stash = ''
        self._undo.clear(); self._redo.clear(); self._sel = None
        if len(self.hist) >= 500:
            self.hist = self.hist[-250:]
        if not self.hist or self.hist[-1] != raw:   # v2: skip consecutive dupes
            self.hist.append(raw)
        if raw.startswith('/'):
            # /btw owns its own live-region panel — keep the command itself
            # out of the main scrollback.
            cmd0 = (raw[1:].split(None, 1)[0] or '').lower()
            if cmd0 != 'btw':
                self._commit_user(raw)
            self._cmd(raw); return
        if self._running:
            return
        # Collect images whose `[Image #N]` placeholder is still in the draft,
        # in placeholder order — a block-deleted placeholder drops its image.
        imgs = [self._imgs[i] for i in
                (int(m.group(1)) for m in _IMG_PH_RE.finditer(raw)) if i in self._imgs]
        expanded = self._expand(raw)               # expand paste/file refs FIRST so
        self._commit_user(expanded)                # scrollback shows exactly what
        self._submit(expanded, imgs)               # the agent receives, not the
        self._pstore.clear(); self._fstore.clear(); self._imgs.clear()   # drop placeholders

    def _cost_section(self, tname: str, t, be) -> list[str]:
        """A v2-style /cost block for one token tracker — total / cache /
        context-window / requests.  Labels stay English (jargon)."""
        from frontends import cost_tracker
        k = _human
        model = self._bridge.llm_name if self._bridge else '?'
        label = self._session_name or tname           # show the session name when set
        rows = [f'{label}  ·  model: {model}  ·  elapsed: {_elapsed(t.elapsed_seconds())}']
        rows.append(f'  Token usage:     {k(t.total_tokens()):>8} total  '
                    f'({k(t.total_input_side())} input + {k(t.output)} output)')
        if t.cache_read or t.cache_create:
            rows.append(f'  Cache:           {k(t.cache_read):>8} read  ·  '
                        f'{k(t.cache_create)} created  ·  {t.cache_hit_rate():.1f}% hit')
        cap = cost_tracker.context_window_chars(be) if be else 0
        used = cost_tracker.current_input_chars(be) if be else 0
        if cap > 0:
            pct = max(0.0, (cap - used) / cap * 100.0)
            rows.append(f'  Context window:  {pct:>7.0f}% left  '
                        f'({k(used)} chars used / {k(cap)} cap)')
        rows.append(f'  Requests:        {t.requests:>8}')
        return rows

    def _set_session_name(self, ag, name: str) -> None:
        """Persist the session name (keyed by the agent's log file) so a later
        /continue surfaces it — mirrors v2's session_names integration."""
        try:
            from frontends import session_names
            lp = getattr(ag, 'log_path', '') or ''
            if lp:
                session_names.set_name(lp, name)
        except Exception:
            pass

    def _reset_session(self, ag) -> None:
        """Wipe the conversation: drop LLM history, clear the screen and every
        rendered block.  Shared by /clear and /new."""
        from frontends import continue_cmd
        continue_cmd.reset_conversation(ag)
        _w('\x1b[2J\x1b[H'); self._painted = []; self._live_rows = 0
        self._blocks = []; self._streaming_block = None; self._sent = 0
        self._tool_base = 0; self._tools = {}

    def _cmd(self, raw: str) -> None:
        assert self._bridge is not None
        parts = raw[1:].split(None, 1)
        name = parts[0].lower() if parts else ''
        arg = parts[1].strip() if len(parts) > 1 else ''
        ag = self._bridge.agent
        # /btw is deliberately NOT idle-only — a side question must be fireable
        # while the main agent runs (that's its whole purpose).
        idle_only = {'clear', 'export', 'review', 'rewind', 'continue'}
        if name in idle_only and self._running:
            self.commit([_t('err.running_blocked')]); return
        if name in ('q', 'quit', 'exit'):
            self._quit = True
        elif name in ('stop', 'abort'):
            if self._running:
                self._bridge.abort()
            self.commit([_t('msg.abort_done') if self._running else _t('msg.idle_no_task')])
        elif name in ('status', 'sessions'):
            # /status: full snapshot of the current session.
            # /sessions: same output (v3 is single-session; multi-session listing
            # is the same data as a 1-row table).
            be = getattr(getattr(ag, 'llmclient', None), 'backend', None)
            rounds = 0
            try:
                if be is not None and getattr(be, 'history', None):
                    rounds = sum(1 for m in be.history if m.get('role') == 'user')
            except Exception:
                pass
            llm = self._bridge.llm_name if self._bridge else '?'
            if self._running:
                el = time.time() - self._t0_anchor
                state = _t('status.state.running', verb=_gerund(el), elapsed=_elapsed(el))
            elif self._asking is not None:
                state = _t('status.state.waiting')
            else:
                state = _t('status.state.idle')
            try:
                from frontends import cost_tracker as _ct
                cap = _ct.context_window_chars(be) if be is not None else 0
                used = _ct.context_chars_used(be) if be is not None else 0
                ctx_use = _t('status.ctx.fmt', used=used, cap=cap * 3) if cap else _t('status.ctx.unknown')
            except Exception:
                ctx_use = _t('status.ctx.unknown')
            cwd = os.getcwd().replace(os.path.expanduser('~'), '~')
            rows = ['',
                    _DIM + _t('status.title') + _RST,
                    '',
                    f'  {_DIM}{_t("status.label.model"):<9}{_RST} {llm}',
                    f'  {_DIM}{_t("status.label.state"):<9}{_RST} {state}',
                    f'  {_DIM}{_t("status.label.rounds"):<9}{_RST} {rounds}',
                    f'  {_DIM}{_t("status.label.context"):<9}{_RST} {ctx_use}',
                    f'  {_DIM}{_t("status.label.cwd"):<9}{_RST} {cwd}',
                    '']
            if self._bridge and not self._bridge._healthy:
                rows.append(f'  {_DIM}⚠ {self._bridge._init_error}{_RST}')
                rows.append('')
            self.commit(rows)
        elif name == 'new':
            # New session = wipe the current conversation and start fresh.
            # Keeping prior sessions around (multi-session) is a separate
            # workstream — see temp/plan_tui_v3_refactor/TODO.md.
            self._reset_session(ag)
            self._session_name = arg or ''
            if arg:
                self._set_session_name(ag, arg)
            self.commit(Block('banner', ''))       # fresh banner shows the new name
            self.commit([_DIM + (_t('msg.new_session_named', name=arg) if arg
                                 else _t('msg.new_session')) + _RST])
        elif name == 'rename':
            if not arg:
                self.commit([_t('err.rename_usage')]); return
            self._session_name = arg
            self._set_session_name(ag, arg)
            self.commit([_DIM + _t('msg.renamed', name=arg) + _RST])
        # /switch /close /branch — 多会话后端尚未接入，命令未实现，先注释掉。
        # elif name in ('switch', 'close', 'branch'):
        #     self.commit([_t('err.multi_session', name=name)])
        elif name == 'continue':
            from frontends import continue_cmd
            sess = continue_cmd.list_sessions(exclude_pid=os.getpid())
            if not sess:
                self.commit([_DIM + _t('msg.no_history') + _RST]); return

            def _do_restore(path: str) -> None:
                msg, _ = continue_cmd.restore(ag, path)
                self.commit([_DIM + '┄┄ ' + _t('msg.continue_loading', name=os.path.basename(path)) + ' ┄┄' + _RST])
                for mm in continue_cmd.extract_ui_messages(path):
                    c = (mm.get('content') or '').strip()
                    if not c:
                        continue
                    if mm.get('role') == 'user':
                        self._commit_user(c)
                    else:
                        self._commit_assistant(c)
                self.commit([_DIM + '┄┄ ' + _t('msg.continue_ready', msg=msg) + ' ┄┄' + _RST])

            if arg:
                # Direct numeric argument still supported for power users / scripts.
                if not arg.isdigit():
                    self.commit([_t('err.continue_usage')]); return
                i = int(arg) - 1
                if not (0 <= i < len(sess)):
                    self.commit([_t('err.index_oob', max=len(sess))]); return
                _do_restore(sess[i][0]); return

            # No arg → arrow-key menu.  Show every session; the menu picker's
            # scrolling viewport (↑/↓ slides the window) reaches older entries
            # without needing /continue N as a fallback.
            w = _term()[0]
            try:
                from frontends import session_names as _sn
            except Exception:
                _sn = None
            options: list[str] = []
            unit = _t('continue.unit.round')
            for _p, mt, prev, rnd in sess:
                nm = ''
                if _sn is not None:
                    try:
                        nm = _sn.name_for(_p)
                    except Exception:
                        nm = ''
                # Uniform 3-part row `{age} · {n}轮 · {text}` — a named session
                # shows its name in the text slot, an unnamed one its preview,
                # so the columns line up either way.
                text = nm or (prev or '').replace('\n', ' ').strip()[:max(20, w - 30)]
                options.append(f'{_rel(mt)} · {rnd}{unit} · {text}')

            def _pick_session(idx: int) -> None:
                _do_restore(sess[idx][0])

            self._show_menu(_t('continue.title'), options, _pick_session)
        elif name == 'clear':
            self._reset_session(ag)
            self.commit([_DIM + _t('msg.cleared') + _RST])
        elif name == 'rewind':
            be = getattr(getattr(ag, 'llmclient', None), 'backend', None)
            turns = self._rewindable_turns(be)
            if not turns:
                self.commit([_t('msg.no_rewindable')]); return
            if arg:
                # Direct numeric form: /rewind N.
                if not arg.isdigit():
                    self.commit([_t('err.rewind_usage')]); return
                n = int(arg)
                if not (1 <= n <= len(turns)):
                    self.commit([_t('err.rewind_range', max=len(turns))]); return
                msg, prefill = self._do_rewind(be, n)
                self.commit([msg])
                if prefill:
                    self.buf = prefill; self.pos = len(prefill)
                return
            # No arg → menu picker, one row per rewindable turn (recent first,
            # capped at 20 like v2) with a content preview.
            LIMIT = 20
            recent = list(reversed(turns))[:LIMIT]
            options: list[str] = []
            for offset, (_idx, prev) in enumerate(recent, 1):
                preview = (prev or '').replace('\n', ' ').strip()[:60]
                options.append(_t('rewind.option', n=offset, preview=preview))

            def _pick_rewind(idx: int) -> None:
                msg, prefill = self._do_rewind(be, idx + 1)
                self.commit([msg])
                if prefill:
                    self.buf = prefill; self.pos = len(prefill)

            self._show_menu(_t('rewind.title'), options, _pick_rewind)
        elif name == 'btw':
            if not arg:
                self.commit([_t('err.btw_usage')]); return
            # Background side question — does NOT touch self._running, so it
            # never blocks idle-only commands nor makes /stop think the main
            # agent is busy.  Concurrent /btw is allowed.  The entry shows in
            # the panel immediately (answer slot None → `querying…`).
            entry: list = [arg, None]
            self._btws.append(entry)
            threading.Thread(target=self._btw, args=(entry,), daemon=True).start()
            self._render_live()
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
                    self.commit([_t('msg.review_empty')])
        elif name == 'llm':
            if arg:
                self._bridge.switch_llm(int(arg) if arg.isdigit() else -1)
                self.commit([_t('msg.llm_switched', name=self._bridge.llm_name)])
            else:
                items = self._bridge.list_llms()
                if not items:
                    self.commit([_t('msg.no_llms')]); return
                options: list[str] = []
                current = 0
                for n, it in enumerate(items):
                    cur = len(it) > 2 and it[2]
                    if cur:
                        current = n
                    options.append(('● ' if cur else '  ') + f'{it[0]}. {it[1]}')

                def _pick_llm(idx: int) -> None:
                    target = items[idx]
                    self._bridge.switch_llm(int(target[0]) if str(target[0]).isdigit() else -1)
                    self.commit([_t('msg.llm_switched', name=self._bridge.llm_name)])

                self._show_menu(_t('llm.title'), options, _pick_llm)
                self._menu_sel = current
        elif name == 'cost':
            from frontends import cost_tracker
            trackers = cost_tracker.all_trackers()
            if not trackers:
                self.commit([_t('msg.no_tracker')]); return
            # A mixin model spreads LLM calls across worker threads → many
            # trackers for one logical session.  Aggregate into one block.
            agg = cost_tracker.TokenStats()
            agg.started_at = min((t.started_at for t in trackers.values()),
                                 default=agg.started_at)
            for t in trackers.values():
                agg.requests += t.requests
                agg.input += t.input
                agg.output += t.output
                agg.cache_create += t.cache_create
                agg.cache_read += t.cache_read
            be = getattr(getattr(ag, 'llmclient', None), 'backend', None)
            self.commit(['✦ Token usage']
                        + self._cost_section(self._session_name or 'session', agg, be))
        elif name == 'export':
            from frontends import export_cmd
            parts = arg.split(None, 1) if arg else []
            head = parts[0].lower() if parts else ''
            rest = parts[1] if len(parts) > 1 else ''

            def _do_clip() -> None:
                txt = export_cmd.last_assistant_text(ag)
                if not txt:
                    self.commit([_t('msg.no_export')]); return
                wrapped = export_cmd.wrap_for_clipboard(txt)
                if copy(wrapped):
                    self.commit([_t('msg.export_clipped', n=len(wrapped))])
                else:
                    self.commit([_t('msg.export_clip_failed')])

            def _do_all() -> None:
                lp = getattr(ag, 'log_path', '') or ''
                if lp and os.path.isfile(lp):
                    self.commit([_t('msg.export_all', path=lp)])
                else:
                    self.commit([_t('msg.export_all_missing')])

            def _do_file(fname: str = '') -> None:
                txt = export_cmd.last_assistant_text(ag)
                if not txt:
                    self.commit([_t('msg.no_export')]); return
                if not fname:
                    from datetime import datetime as _dt
                    fname = 'export-' + _dt.now().strftime('%Y%m%d-%H%M%S') + '.md'
                p = export_cmd.export_to_temp(txt, fname)
                self.commit([_t('msg.export_done', path=p)])

            def _prefill_file() -> None:
                # v2 parity: picker → file fills the input with a default name
                # so the user can edit before committing.
                from datetime import datetime as _dt
                default = 'export-' + _dt.now().strftime('%Y%m%d-%H%M%S') + '.md'
                text = '/export ' + default
                self.buf = text
                self.pos = len(text)
                self._sel = None
                self._render_live()

            if not head:
                opts = [_t('export.opt.clip'),
                        _t('export.opt.file'),
                        _t('export.opt.all')]
                actions = (_do_clip, _prefill_file, _do_all)
                self._show_menu(_t('export.title'), opts,
                                lambda i: actions[i]())
            elif head in ('clip', 'copy'):
                _do_clip()
            elif head == 'all':
                _do_all()
            elif head == 'file':
                _do_file(rest)
            else:
                # legacy: /export <name> → file with that name
                _do_file(arg)
        elif name in ('verbose', 'tools', 'trace'):
            self._verbose_view()
        elif name == 'language':
            self._cmd_language(arg)
        elif name == 'help':
            self.commit([_t('help.title'),
                         _t('help.help'),
                         _t('help.status'),
                         _t('help.sessions'),
                         _t('help.llm'),
                         _t('help.btw'),
                         _t('help.review'),
                         _t('help.rewind'),
                         _t('help.continue'),
                         _t('help.new'),
                         _t('help.rename'),
                         _t('help.clear'),
                         _t('help.cost'),
                         _t('help.verbose'),
                         _t('help.export'),
                         _t('help.stop'),
                         _t('help.language'),
                         _t('help.quit'),
                         _t('help.esc'),
                         _t('help.cc'),
                         _t('help.cl'),
                         _t('help.cz'),
                         _t('help.shift_arrow')])
        else:
            self.commit([_t('err.unknown_cmd', name=name)])

    def _btw(self, entry: list) -> None:
        """Answer a side question and fill `entry[1]` in place.  If Esc cleared
        the panel meanwhile, `entry` is just an orphan — the mutation is
        invisible and the panel renders the current (empty) list."""
        from frontends import btw_cmd
        question = entry[0]
        try:
            ans = btw_cmd.handle_frontend_command(self._bridge.agent, '/btw ' + question)
        except Exception as e:
            ans = f'> /btw {question}\n\n❌ {type(e).__name__}: {e}'
        # btw_cmd's formatter prefixes the header with a 🟡 glyph — drop it.
        ans = (ans or '').replace('🟡 ', '').replace('🟡', '').strip()
        with self._lk:
            entry[1] = ans or f'> /btw {question}\n\n{_t("msg.btw_no_answer")}'
            self._render_live()

    def _cmd_language(self, arg: str) -> None:
        """`/language` — arrow-key picker (like /llm); `/language <code>` — direct switch."""
        codes = supported()
        labels = LANG_LABELS
        cur = get_lang()
        if arg:
            code = arg.strip().lower()
            if code not in codes:
                avail = ', '.join(f'{c} ({labels.get(c, c)})' for c in codes)
                self.commit([_t('err.lang_unknown', code=arg, available=avail)]); return
            set_lang(code)
            self.commit([_t('msg.lang_switched', label=labels.get(code, code))])
            self._repaint_screen()
            return

        # No arg → menu picker.  Build options in stable code order; a leading
        # ● marks the active language (the ↑↓ highlight marks the cursor row).
        options: list[str] = []
        current_idx = 0
        for i, code in enumerate(codes):
            if code == cur:
                current_idx = i
            options.append(('● ' if code == cur else '  ')
                           + f'{labels.get(code, code)}  ({code})')

        def _pick_lang(idx: int) -> None:
            code = codes[idx]
            if code == get_lang():
                # No-op pick — still report current so the user sees confirmation.
                self.commit([_t('msg.lang_current', label=labels.get(code, code), code=code)])
                return
            set_lang(code)
            self.commit([_t('msg.lang_switched', label=labels.get(code, code))])
            self._repaint_screen()

        self._show_menu(_t('lang.title'), options, _pick_lang)
        self._menu_sel = current_idx

    def _rewindable_turns(self, be) -> list[tuple[int, str]]:
        """v2-parity turn detector: scan backend.history and return
        (history_index, preview) for every *real* user turn.  A user message
        whose content is a tool_result block is skipped — otherwise a single
        tool round-trip would be miscounted as an extra rewindable turn."""
        turns: list[tuple[int, str]] = []
        hist = getattr(be, 'history', None) or []
        for i, m in enumerate(hist):
            if not isinstance(m, dict) or m.get('role') != 'user':
                continue
            c = m.get('content')
            if isinstance(c, str):
                turns.append((i, c[:60])); continue
            if isinstance(c, list):
                if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c):
                    continue
                texts = [b.get('text', '') for b in c
                         if isinstance(b, dict) and b.get('type') == 'text']
                if texts and any(t.strip() for t in texts):
                    turns.append((i, texts[0][:60]))
        return turns

    def _do_rewind(self, be, n: int) -> tuple[str, str]:
        """Cut backend.history back `n` real user turns.  Returns
        (report_line, prefill_text) — prefill is the user text of the turn
        rewound *to*, so the caller can drop it back into the input box."""
        turns = self._rewindable_turns(be)
        if not (1 <= n <= len(turns)):
            return _t('err.rewind_range', max=len(turns)), ''
        hist = be.history
        cut = turns[-n][0]
        prefill = _extract_user_text(hist[cut]) if cut < len(hist) else ''
        removed = len(hist) - cut
        hist[:] = hist[:cut]
        return _t('msg.rewind', n=n, removed=removed), prefill

    def _verbose_view(self) -> None:
        """Tool-call audit on a TEMP alt-screen — main scrollback is never
        touched. Data is the already-captured ToolRecord log (self._tools)."""
        recs = [self._tools[k] for k in sorted(self._tools)]
        if not recs:
            self.commit([_DIM + _t('msg.no_tools') + _RST]); return
        sel, mode, scroll = 0, 0, 0
        fields = ('result', 'args', 'raw')
        _w('\x1b[?1049h\x1b[?2004l')          # alt-screen; pause bracketed paste here
        try:
            while True:
                w, h = _term()
                r = recs[sel]
                lines: list[str] = []
                for ln in (getattr(r, fields[mode]) or _t('verbose.empty')).split('\n'):
                    lines += _wrap_cells(ln, w - 2) or ['']
                avail = max(2, h - 4)               # rows shared by list + detail
                list_h = min(len(recs), max(3, avail // 3))
                body_h = max(1, avail - list_h)
                lo = max(0, min(sel - list_h // 2, len(recs) - list_h))
                scroll = max(0, min(scroll, max(0, len(lines) - body_h)))
                out = ['\x1b[2J\x1b[H', _BOLD + _t('verbose.title') + _RST + _DIM +
                       _t('verbose.hint', field=fields[mode]) + _RST, '']
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
            # NOTE: this /verbose alt-screen viewer reads keys via os.read(self._fd),
            # which conflicts with PTK's input loop.  In PTK Application mode the
            # viewer is currently broken; a future rewrite should wrap it in
            # app.run_in_terminal and use PTK's input pipeline.  For now we just
            # invalidate so PTK redraws the live region after we exit alt-screen.
            self._painted = []; self._live_rows = 0; self._parked_up = 0
            self._pending_repaint = True
            self._schedule_drain()
            self._invalidate_ptk()

    # ── agent ──

    def _submit(self, query: str, images: list) -> None:
        assert self._bridge is not None
        self._running = True; self._t0 = self._t0_anchor = time.time()
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
        self._picker_init(ae)
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
                                                # and _render_block does the fold

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
        stream = _strip_final_marker(sanitize_ansi(self._stream))

        if self._streaming_block is None and (stream.strip() or final):
            self._streaming_block = Block('assistant', '')
            self._blocks.append(self._streaming_block)
            self._cap_blocks()
            self._sent = 0
            self._stream_turn_seen = 0   # new response → reset incremental fold tracker

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
            # Per-turn fold only kicks in with ≥2 turn markers (see _fold_turns).
            # Anything less stays expanded and doesn't need a repaint — saves a
            # screen flash on simple Q&A.
            multi_turn = len(_TURN_SPLIT_FOLD_RE.findall(stream)) >= 2
            self._streaming_block = None
            self._stream = ''; self._sent = 0; self._live_tail = []
            self._stream_turn_seen = 0   # response done → reset for next stream
            # Auto-collapse after generation: streamed body was already pushed
            # to scrollback above; trigger a full repaint so it gets replaced
            # by per-turn folded headers (scrollback-first can't unwrite, full
            # repaint is the only knob).
            if multi_turn and self._fold_all:
                self._repaint_screen()
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
        # Incremental fold (v2 live-fold parity): the moment a new turn marker
        # arrives, the PREVIOUS turn body is complete and can collapse into a
        # `▸ {summary}` header.  Trigger a full repaint each time the marker
        # count climbs — already-committed expanded lines get cleared and
        # replaced with the folded form.  Without this users see every turn
        # expanded all the way through the response and only fold at the very
        # end (final=True), which feels bulk-and-flash.
        turn_count = len(_TURN_SPLIT_FOLD_RE.findall(stream))
        if (self._fold_all and turn_count > self._stream_turn_seen
                and turn_count >= 2):
            self._stream_turn_seen = turn_count
            self._repaint_screen()

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
            # ── menu picker key intercept (modal: blocks all input editing) ─
            # /llm, /continue, … open an arrow-key menu.  ↑↓ move highlight
            # (saturating at endpoints — no wrap), Enter submits, Esc cancels.
            # Other keys are swallowed — no free-text typing while a menu is up.
            if self._menu_active:
                n = len(self._menu_options)
                if o == 0x10:                                # ↑
                    if n:
                        self._menu_sel = max(0, self._menu_sel - 1)
                    self._render_live(); continue
                if o == 0x0e:                                # ↓
                    if n:
                        self._menu_sel = min(n - 1, self._menu_sel + 1)
                    self._render_live(); continue
                if ch == '\r':                               # Enter
                    self._menu_submit(); continue
                if o == 0x1b:                                # Esc
                    self._menu_cancel(); continue
                # swallow everything else while the menu is up
                continue
            # ── ask_user picker key intercept ───────────────────────────────
            # Single mode: focus cycles [cand0..candN-1, input].  ↑↓ moves
            #   through candidates and the input box; printable chars switch
            #   focus to input and insert.
            # Multi mode: NO input box (rendering skips it too).  ↑↓ wrap
            #   inside candidates only; Space toggles current checkbox;
            #   non-Enter/Esc printable chars are swallowed (free-text would
            #   break the "submit checked items" semantics).
            if self._asking is not None:
                ae = self._asking
                n = len(ae.candidates) if getattr(ae, 'candidates', None) else 0
                if self._picker_mode == 'multi':
                    if o == 0x10 and n > 0:                  # ↑ wrap in multi
                        self._picker_sel = (self._picker_sel - 1) % n
                        self._render_live(); continue
                    if o == 0x0e and n > 0:                  # ↓ wrap in multi
                        self._picker_sel = (self._picker_sel + 1) % n
                        self._render_live(); continue
                    if ch == ' ':                            # Space toggle
                        i = self._picker_sel
                        if i in self._picker_checked:
                            self._picker_checked.discard(i)
                        else:
                            self._picker_checked.add(i)
                        self._render_live(); continue
                    if o >= 0x20:                            # swallow other printables
                        continue
                elif o in (0x10, 0x0e) and n > 0:            # ↑ / ↓ in single
                    self._sel = None
                    if not self._picker_mode:
                        # Input → picker.  ↑ enters at bottom, ↓ enters at top.
                        self._picker_mode = 'single'
                        self._picker_sel = (n - 1) if o == 0x10 else 0
                    elif o == 0x10:                          # ↑ inside picker
                        if self._picker_sel <= 0:            # top edge → input
                            self._picker_mode = None
                        else:
                            self._picker_sel -= 1
                    else:                                     # ↓ inside picker
                        if self._picker_sel >= n - 1:        # bottom edge → input
                            self._picker_mode = None
                        else:
                            self._picker_sel += 1
                    self._render_live(); continue
                if self._picker_mode == 'single' and o >= 0x20:
                    self._picker_mode = None                   # keep sel alive
                    # fall through to normal insert below
            if ch == '\r':
                self._on_enter()
            elif ch == '\n':
                self._insert('\n')
            elif o == 0x10:                       # ↑ visual-row up (history at top)
                if self._palette_visible():
                    self._palette_sel = max(0, self._palette_sel - 1)
                else:
                    self._sel = None; self._cur_v(-1)
            elif o == 0x0e:                       # ↓ visual-row down (history at bottom)
                if self._palette_visible():
                    n = len(self._cmd_matches(self.buf))
                    self._palette_sel = min(n - 1, self._palette_sel + 1) if n else 0
                else:
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
            elif o == 0x0f:                       # Ctrl+O — silent toggle: fold/unfold tool chips
                self._fold_all = not self._fold_all
                self._repaint_screen()
            elif o == 0x16:                       # Ctrl+V
                self._handle_clip_paste()
            elif o == 0x15:                       # Cmd+⌫ / Ctrl+U: kill to line start
                if not self._kill_sel():
                    self._snap()
                    ls = self.buf.rfind('\n', 0, self.pos) + 1
                    self.buf = self.buf[:ls] + self.buf[self.pos:]; self.pos = ls
            elif o in (0x7f, 0x08):
                if not self._kill_sel():
                    hit = self._placeholder_at('left')
                    if hit:                       # backspace flush against a
                        st, end, sid = hit         # placeholder → wipe the block
                        self._snap()
                        self.buf = self.buf[:st] + self.buf[end:]; self.pos = st
                        self._pstore.pop(sid, None)
                        self._fstore.pop(sid, None)
                        self._imgs.pop(sid, None)
                    elif self.pos:
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
                self._bridge.abort()
                self._running = False             # stop the spinner/pet animation now
                with self._lk:
                    self._render_live()
                return True
            if time.time() - self._cc_t < 1:      # idle: arm-to-quit; second press
                return False                       # within the window actually exits
            with self._lk:
                if self.buf:                      # v2: first press clears the draft
                    self._snap()
                    self.buf = ''; self.pos = 0; self._sel = None
                self._cc_t = time.time()          # arm: second press quits + shows hint
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

    def _run_prompt_toolkit(self) -> None:
        """prompt_toolkit Application backend (scrollback-first).

        PTK owns: raw mode, key dispatch, resize polling, async lifecycle, and
        rendering of the *live region only* (input box + status + spinner +
        plan + open stream tail).  The Window has dynamic height that follows
        content, so PTK reserves only the live region's rows at the bottom of
        the terminal.

        Finalized history is pushed above the PTK render area via
        app.print_text() wrapped in run_in_terminal() — the terminal's native
        scrollback owns the conversation and the mouse wheel scrolls it.
        """
        from prompt_toolkit.application import Application
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.output.defaults import create_output

        self._bridge = AgentBridge()
        try:
            from frontends import cost_tracker
            cost_tracker.install()
        except Exception:
            pass

        os.makedirs(self._cwd, exist_ok=True)
        logf = open(os.path.join(self._cwd, 'sb_agent.log'), 'w', buffering=1,
                    encoding='utf-8')
        so, se = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = logf

        kb = KeyBindings()
        last_size: list[tuple[int, int] | None] = [None]

        def _handle_key(event) -> None:
            for kp in event.key_sequence:
                if _is_mouse_or_scroll_keypress(kp):
                    continue
                # Bracketed paste: PTK parses `\x1b[200~…\x1b[201~` into a
                # single keypress whose `data` is the whole payload.  Route it
                # straight to the paste handler — otherwise the payload's
                # newlines fall through `_keys` as Enter presses (premature
                # submit) and multi-line / file / image folding never runs.
                if getattr(kp, 'key', None) == Keys.BracketedPaste:
                    # A modal menu picker owns the live region — no input box
                    # to paste into, so swallow the paste.
                    if not self._menu_active:
                        with self._lk:
                            self._handle_paste(getattr(kp, 'data', '') or '')
                            self._render_live()
                    event.app.invalidate()
                    continue
                data = _ptk_keypress_to_bytes(kp)
                # PTK has already disambiguated a bare Escape from arrow-key
                # sequences (arrows arrive as Keys.Up/… → distinct bytes), so a
                # b'\x1b' here is unambiguously Esc.  Handle it directly instead
                # of routing through _keys, whose raw-terminal escape-delay
                # hold (~30ms) would otherwise lag every menu/ask cancel.
                if data == b'\x1b':
                    with self._lk:
                        self._esc_back()
                        self._render_live()
                    event.app.invalidate()
                    continue
                if data and not self._feed(data):
                    event.app.exit()
                    return
            event.app.invalidate()

        kb.add(Keys.Any, eager=True)(_handle_key)

        control = FormattedTextControl(
            text=self._get_ptk_text,
            focusable=True,
            show_cursor=True,
            get_cursor_position=self._get_ptk_cursor,
        )
        # dont_extend_height + dynamic height makes PTK reserve only the live
        # region's rows at the bottom of the terminal.  Anything written via
        # run_in_terminal/print_text scrolls above into native scrollback.
        root = Window(
            content=control,
            wrap_lines=False,
            # Hide the caret when focus is owned elsewhere:
            #  - a modal menu picker (no text field at all)
            #  - the ask card with picker mode active (focus on a candidate row)
            # Free-text mode in the ask card (_picker_mode=None) keeps the
            # cursor visible so the user can see where their typing lands.
            always_hide_cursor=Condition(
                lambda: self._menu_active
                or (self._asking is not None and self._picker_mode is not None)
            ),
            height=self._get_live_height,
            dont_extend_height=True,
        )
        layout = Layout(root, focused_element=control)

        def _before_render(app: Application) -> None:
            ts = self._ptk_size()
            size_changed = last_size[0] != ts
            if size_changed:
                last_size[0] = ts
                with self._lk:
                    self._resized = False
                    self._repaint_screen()
            # Rebuild the live-region cache every frame so the height query
            # (PTK calls preferred_height before the text getter) and the text
            # getter see exactly the same content — even when streaming
            # mutates state between renders without a size change.
            self._build_live_lines()

        async def _maintenance_loop() -> None:
            while True:
                await asyncio.sleep(0.03)
                dirty = False
                if self._running and self._asking is None:
                    # spinner / elapsed text is time-based
                    dirty = True
                if 0 < time.time() - self._cc_t < 1.1:
                    # Ctrl+C armed: keep re-rendering so the status line
                    # restores itself once the 1s window lapses (the extra
                    # 0.1s margin guarantees one render past expiry).
                    dirty = True
                if self._epend or (self._rb and not self._bp):
                    with self._lk:
                        self._flush_esc()
                    dirty = True
                with self._sbq_lk:
                    has_q = bool(self._sbq)
                if (has_q or self._pending_repaint) and self._ptk_app is not None:
                    self._ptk_app.create_background_task(self._drain_async())
                if dirty and self._ptk_app is not None:
                    self._ptk_app.invalidate()

        def _pre_run() -> None:
            self._ptk_loop = asyncio.get_event_loop()
            app = self._ptk_app
            assert app is not None
            app.create_background_task(_maintenance_loop())
            _enable_windows_vt_mode()
            _enter_utf8_charset()
            _w('\x1b[?1007l')   # disable alt-scroll so wheel scrolls scrollback
            _w('\x1b[?2004h')   # enable bracketed paste
            _w('\x1b[>4;1m')    # ask supporting terminals to distinguish Shift+Enter
            self.commit(Block('banner', ''))

        app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=False,
            erase_when_done=False,
            # No refresh_interval: each auto-refresh re-positions PTK's cursor
            # to the live region, which makes the terminal auto-scroll to the
            # bottom — destroying the user's scrollback position.  Maintenance
            # loop invalidates explicitly only when running (spinner anim).
            terminal_size_polling_interval=0.2,
            mouse_support=False,
            before_render=_before_render,
            output=create_output(stdout=so),
        )
        self._ptk_app = app

        try:
            app.run(pre_run=_pre_run, handle_sigint=False)
        finally:
            _w('\x1b[>4;0m')
            _w('\x1b[?2004l')
            _w('\x1b[?1007h')
            self._ptk_app = None
            self._ptk_loop = None
            sys.stdout, sys.stderr = so, se
            logf.close()
            try:
                os.write(1, b'\n')
            except Exception:
                pass

    def run(self) -> None:
        return self._run_prompt_toolkit()


# sb.py's original `main()` and __main__ guard intentionally dropped — the
# unified entry point lives below (combines __init__.py + __main__.py).


# ────────────────────────────────────────────────────────────────────────────
# entry: equivalent of frontends/tui/__init__.py + __main__.py
# ────────────────────────────────────────────────────────────────────────────

def _ensure_deps():
    try:
        import rich  # noqa: F401
        import prompt_toolkit  # noqa: F401
    except ImportError as e:
        import sys
        print(_t('err.dep_missing', name=e.name))
        print(_t('err.dep_install'))
        sys.exit(2)


def main():
    _ensure_deps()
    install_cjk_wrap()
    if not sys.stdin.isatty():
        print(_t('err.no_tty')); return
    SB().run()


if __name__ == '__main__':
    main()
