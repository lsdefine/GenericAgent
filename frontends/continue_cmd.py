"""`/continue` command: list & restore past model_responses sessions.
Pure functions + one `install(cls)` monkey-patch entry. No side effects at import.
"""
import ast, atexit, glob, json, os, random, re, shutil, threading, time
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'temp', 'model_responses')
_LOG_GLOB = os.path.join(_LOG_DIR, 'model_responses_*.txt')
_BLOCK_RE = re.compile(r'^=== (Prompt|Response) ===.*?\n(.*?)(?=^=== (?:Prompt|Response) ===|\Z)',
                       re.DOTALL | re.MULTILINE)
_SUMMARY_RE = re.compile(r'<summary>\s*(.*?)\s*</summary>', re.DOTALL)
_ROUND_HEADER_RE = re.compile(rb'^=== (Prompt|Response) ===', re.MULTILINE)
_ROUNDS_CACHE_PATH = os.path.join(os.path.expanduser('~'), '.genericagent', 'continue_rounds_cache.json')
_ROUNDS_CACHE_VERSION = 1
_rounds_cache = None
_rounds_cache_dirty = False

def _rel_time(mtime):
    d = int(time.time() - mtime)
    if d < 60: return f'{d}秒前'
    if d < 3600: return f'{d // 60}分前'
    if d < 86400: return f'{d // 3600}小时前'
    return f'{d // 86400}天前'

def _pairs(content):
    blocks, pairs, pending = _BLOCK_RE.findall(content or ''), [], None
    for label, body in blocks:
        if label == 'Prompt': pending = body.strip()
        elif pending is not None:
            pairs.append((pending, body.strip())); pending = None
    return pairs

def _first_user(pairs):
    for p, _ in pairs:
        try: msg = json.loads(p)
        except Exception: continue
        if not isinstance(msg, dict): continue
        for blk in msg.get('content', []) or []:
            if isinstance(blk, dict) and blk.get('type') == 'text':
                t = strip_project_mode(blk.get('text') or '').strip()
                if t and '<history>' not in t and not t.startswith('### [WORKING MEMORY]'):
                    return t
    for p, _ in pairs[:1]:
        for line in p.splitlines():
            s = line.strip()
            if s and not s.startswith('###'): return s
    return ''


def _last_user(text):
    """Last real user prompt. Scans `=== Prompt ===` blocks directly (no
    Prompt/Response pairing, so response-less/aborted sessions still preview),
    newest-first, returning the first one `_user_text` accepts (it drops
    tool_result continuations + all _INJECT_MARKERS). Better preview anchor than
    the first prompt — reflects what the session was most recently about."""
    for label, body in reversed(_BLOCK_RE.findall(text or '')):
        if label == 'Prompt':
            t = _user_text(body)
            if t:
                return t
    return ''


def _last_summary(pairs):
    for _, response_body in reversed(pairs):
        try:
            blocks = ast.literal_eval(response_body)
        except Exception:
            continue
        if not isinstance(blocks, list):
            continue
        text_parts = []
        for block in blocks:
            if isinstance(block, dict) and block.get('type') == 'text':
                text = block.get('text', '')
                if isinstance(text, str) and text:
                    text_parts.append(text)
        match = _SUMMARY_RE.search('\n'.join(text_parts))
        if match:
            summary = match.group(1).strip()
            if summary:
                return summary
    return ''


def _preview_text(pairs):
    return _last_summary(pairs) or _first_user(pairs)

def _recent_context(my_pid, n=5):
    """扫描最近 n 个 model_response 文件（排除自身），提取 lastQ / lastA。"""
    out = []
    for f in sorted(glob.glob(_LOG_GLOB), key=os.path.getmtime, reverse=True):
        m = re.search(r'model_responses_(\d+)', os.path.basename(f))
        if not m or m.group(1) == str(my_pid): continue
        try: c = open(f, encoding='utf-8', errors='ignore').read()
        except Exception: continue
        q = s = ""
        for hm in re.finditer(r'<history>(.*?)</history>', c, re.DOTALL):
            u = re.search(r'\[USER\]:\s*(.+?)(?:\\n|<)', hm.group(1))
            if u: q = u.group(1)
        sm = _SUMMARY_RE.search(c)
        if sm: s = sm.group(1).strip()
        q, s = q[:60].strip(), s[:60].replace('\n', ' ').strip()
        out.append(f'· {m.group(1)} | lastQ: {q or "-"} | lastA: {s or "-"}')
        if len(out) >= n: break
    return ('[RecentContext] 近期并行会话（非当前）:\n' + '\n'.join(out) + '\n[/RecentContext]') if out else ""

def _parse_native_history(pairs):
    history = []
    for p, r in pairs:
        try: user_msg = json.loads(p)
        except Exception: return None
        try: blocks = ast.literal_eval(r)
        except Exception: return None
        if not (isinstance(user_msg, dict) and user_msg.get('role') == 'user'): return None
        if not isinstance(blocks, list): return None
        history.append(user_msg)
        history.append({'role': 'assistant', 'content': blocks})
    return history


_PREVIEW_WIN = 32 * 1024

# Content-grep budget for `/continue` search box: read at most this many bytes
# per session (head window) so 17MB files don't stall the UI. Empirically the
# user-typed prompt + first model reply + early summaries live in the first MB,
# which is what users actually want to recall sessions by.
_GREP_WIN = 1 * 1024 * 1024


def file_contains_all(path, terms, max_bytes=_GREP_WIN):
    """True iff every lowercase term in `terms` appears in the first
    `max_bytes` of `path` (case-insensitive). Empty `terms` returns True so
    callers can short-circuit. Reads as bytes + .lower() to avoid utf-8 cost
    and stays within a fixed memory envelope regardless of file size.
    """
    if not terms:
        return True
    try:
        with open(path, 'rb') as fh:
            buf = fh.read(max_bytes)
    except OSError:
        return False
    if not buf:
        return False
    hay = buf.lower()
    for t in terms:
        if t and t.encode('utf-8', errors='ignore') not in hay:
            return False
    return True


def search_sessions(query, sessions, max_bytes=_GREP_WIN):
    """Filter `sessions` ([(path, mtime, preview, n), ...]) by content grep.

    `query` is whitespace-split into AND terms (case-insensitive). Each
    session is kept iff its path/preview already match OR the first
    `max_bytes` of its file contain every term. Order is preserved.
    Empty/whitespace query returns the list as-is.
    """
    q = (query or '').strip().lower()
    if not q:
        return list(sessions or [])
    terms = [t for t in q.split() if t]
    if not terms:
        return list(sessions or [])
    out = []
    for item in sessions or []:
        path = item[0] if len(item) > 0 else ''
        preview = item[2] if len(item) > 2 else ''
        meta = (os.path.basename(path) + '\n' + (preview or '')).lower()
        if all(t in meta for t in terms):
            out.append(item)
            continue
        if file_contains_all(path, terms, max_bytes=max_bytes):
            out.append(item)
    return out


def _preview_from_file(path):
    """Cheap preview: last <summary> in tail window, else first user line in head window."""
    try:
        sz = os.path.getsize(path)
        with open(path, 'rb') as fh:
            if sz <= _PREVIEW_WIN * 2:
                head = tail = fh.read()
            else:
                head = fh.read(_PREVIEW_WIN)
                fh.seek(-_PREVIEW_WIN, 2); tail = fh.read()
    except OSError: return ''
    tail_s = tail.decode('utf-8', errors='replace')
    # Use only the latest <summary>, and reject it if dirty. Models sometimes emit
    # an unclosed <summary>, so the non-greedy DOTALL match pairs it with a far-away
    # </summary> and swallows === block headers / JSON across rounds. Treat such a
    # match as invalid and fall through to the last user prompt (don't dig older ones).
    cands = _SUMMARY_RE.findall(tail_s)
    if cands:
        s = ' '.join(cands[-1].split())
        if s and '=== ' not in s and '"role"' not in s and len(s) <= 200:
            return s
    # Summary invalid/absent -> last real user prompt (JSON-aware, skips anchors;
    # scans Prompt blocks directly so response-less sessions still preview).
    lu = _last_user(tail_s) or _last_user(head.decode('utf-8', errors='replace'))
    if lu:
        return ' '.join(lu.split())[:120]
    return ''


def _rounds_cache_key(path):
    return os.path.normcase(os.path.abspath(path))


def _load_rounds_cache():
    """Load lazy mtime/size keyed round-count cache for /continue.

    Cache is intentionally triggered only by list_sessions(): no TUI startup cost,
    no logging-path coupling.  Missing/stale entries are recomputed on demand.
    """
    global _rounds_cache
    if _rounds_cache is not None:
        return _rounds_cache
    _rounds_cache = {}
    try:
        with open(_ROUNDS_CACHE_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get('version') == _ROUNDS_CACHE_VERSION:
            items = data.get('items')
            if isinstance(items, dict):
                _rounds_cache = items
    except Exception:
        _rounds_cache = {}
    return _rounds_cache


def _save_rounds_cache(valid_keys=None):
    global _rounds_cache_dirty
    if not _rounds_cache_dirty or _rounds_cache is None:
        return
    try:
        if valid_keys is not None:
            keep = set(valid_keys)
            for k in list(_rounds_cache.keys()):
                if k not in keep:
                    _rounds_cache.pop(k, None)
        os.makedirs(os.path.dirname(_ROUNDS_CACHE_PATH), exist_ok=True)
        tmp = _ROUNDS_CACHE_PATH + '.tmp'
        data = {'version': _ROUNDS_CACHE_VERSION, 'items': _rounds_cache}
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, _ROUNDS_CACHE_PATH)
        _rounds_cache_dirty = False
    except Exception:
        # Cache is a performance hint only; never break /continue on cache I/O.
        pass


def _count_complete_rounds_from_file(path):
    """Count completed Prompt→Response pairs using only block headers.

    Counting Prompt headers alone overcounts an in-flight/incomplete last round.
    Header-pair counting matched `_pairs()` on sampled real logs while avoiding
    expensive UTF-8 decode / body regex parsing.
    """
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError:
        return 0
    pending = False
    rounds = 0
    for m in _ROUND_HEADER_RE.finditer(data):
        if m.group(1) == b'Prompt':
            pending = True
        elif pending:
            rounds += 1
            pending = False
    return rounds


def _rounds_for_file(path, st):
    global _rounds_cache_dirty
    cache = _load_rounds_cache()
    key = _rounds_cache_key(path)
    size = int(getattr(st, 'st_size', 0))
    mtime_ns = int(getattr(st, 'st_mtime_ns', int(getattr(st, 'st_mtime', 0) * 1_000_000_000)))
    ent = cache.get(key)
    if isinstance(ent, dict) and ent.get('size') == size and ent.get('mtime_ns') == mtime_ns:
        try:
            return int(ent.get('rounds', 0)), key
        except Exception:
            pass
    n = _count_complete_rounds_from_file(path)
    cache[key] = {'size': size, 'mtime_ns': mtime_ns, 'rounds': int(n)}
    _rounds_cache_dirty = True
    return n, key


def list_sessions(exclude_pid=None, exclude_log=None):
    """Newest-first list of (path, mtime, preview_text, n_rounds). Preview uses head/tail window only.

    `exclude_log` (basename, e.g. 'model_responses_123456.txt') drops the caller's
    OWN current session — preferred over `exclude_pid`, which assumed the log file
    was named by PID (it isn't: agentmain mints a random 6-digit logid), so the
    pid tag never matched and the current session leaked into its own list."""
    files = glob.glob(_LOG_GLOB)
    if exclude_pid is not None:
        tag = f'model_responses_{exclude_pid}.txt'
        files = [f for f in files if not f.endswith(tag)]
    if exclude_log:
        files = [f for f in files if os.path.basename(f) != exclude_log]
    out = []
    valid_keys = []
    for f in files:
        try:
            st = os.stat(f)
            mtime, sz = st.st_mtime, st.st_size
        except OSError:
            continue
        if sz < 32:
            continue
        preview = _preview_from_file(f)
        if not preview:
            continue
        rounds, key = _rounds_for_file(f, st)
        valid_keys.append(key)
        out.append((f, mtime, preview, rounds))
    _save_rounds_cache(valid_keys)
    out.sort(key=lambda x: x[1], reverse=True)
    return out
_MD_ESCAPE_RE = re.compile(r'([\\`*_\[\]])')
def _escape_md(s): return _MD_ESCAPE_RE.sub(r'\\\1', s)


def _agent_clients(agent):
    clients = []
    for client in getattr(agent, 'llmclients', []) or []:
        if client not in clients:
            clients.append(client)
    current = getattr(agent, 'llmclient', None)
    if current is not None and current not in clients:
        clients.insert(0, current)
    return clients


def _replace_backend_history(agent, history):
    backend = getattr(getattr(agent, 'llmclient', None), 'backend', None)
    if backend is not None and hasattr(backend, 'history'):
        backend.history = list(history or [])


def _current_log_path(pid=None):
    pid = os.getpid() if pid is None else pid
    return os.path.join(_LOG_DIR, f'model_responses_{pid}.txt')


def _snapshot_current_log(pid=None):
    """Persist current PID log as a standalone recoverable snapshot, then clear it."""
    path = _current_log_path(pid)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            content = fh.read()
    except Exception:
        return None
    if not _pairs(content):
        return None
    os.makedirs(_LOG_DIR, exist_ok=True)
    pid = os.getpid() if pid is None else pid
    stamp = time.strftime('%Y%m%d_%H%M%S')
    snapshot = os.path.join(_LOG_DIR, f'model_responses_snapshot_{pid}_{stamp}_{time.time_ns() % 1_000_000_000:09d}.txt')
    with open(snapshot, 'w', encoding='utf-8', errors='replace') as fh:
        fh.write(content)
    with open(path, 'w', encoding='utf-8', errors='replace'):
        pass
    return snapshot


def reset_conversation(agent, message='🆕 已开启新对话，当前上下文已清空'):
    """Abort current work and clear all known frontend-visible conversation state."""
    try:
        agent.abort()
    except Exception:
        pass
    _snapshot_current_log()
    if hasattr(agent, 'history'):
        agent.history = []
    for client in _agent_clients(agent):
        backend = getattr(client, 'backend', None)
        if backend is not None and hasattr(backend, 'history'):
            backend.history = []
        if hasattr(client, 'last_tools'):
            client.last_tools = ''
    if hasattr(agent, 'handler'):
        agent.handler = None
    return message

def format_list(sessions, limit=20):
    if not sessions: return '❌ 没有可恢复的历史会话'
    lines = ['**可恢复会话**（输入 `/continue N` 恢复第 N 个）：', '']
    for i, (_, mtime, first, n) in enumerate(sessions[:limit], 1):
        preview = _escape_md((first or '（无法预览）').replace('\n', ' ')[:60])
        lines.append(f'{i}. `{_rel_time(mtime)}` · **{n} 轮** · {preview}')
    return '\n'.join(lines)

def restore(agent, path):
    """Restore session at path. Returns (msg, is_full)."""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            content = fh.read()
    except Exception as e: return f'❌ 读取失败: {e}', False
    pairs = _pairs(content)
    if not pairs: return f'❌ {os.path.basename(path)} 为空或格式不符', False
    history = _parse_native_history(pairs)
    name = os.path.basename(path)
    if history is not None:
        agent.abort()
        _replace_backend_history(agent, history)
        return f'✅ 已恢复 {len(pairs)} 轮完整对话（{name}）\n(已写入 backend.history，可直接继续)', True
    from chatapp_common import _restore_native_history, _restore_text_pairs
    summary = _restore_text_pairs(content) or _restore_native_history(content)
    if not summary: return f'❌ {name} 无法解析（非 native 且无摘要可提取）', False
    agent.abort()
    agent.history.extend(summary)
    n = sum(1 for l in summary if l.startswith('[USER]: '))
    return f'⚠️ 非 native 格式，已降级恢复 {n} 轮摘要（{name}）\n(请输入新问题继续)', False

def handle(agent, query, display_queue):
    """Dispatch /continue or /continue N. Returns None if consumed else original query."""
    s = (query or '').strip()
    if s == '/continue':
        display_queue.put({'done': format_list(list_sessions(exclude_pid=os.getpid())), 'source': 'system'})
        return None
    m = re.match(r'/continue\s+(\d+)\s*$', s)
    if m:
        sessions = list_sessions(exclude_pid=os.getpid())
        idx = int(m.group(1)) - 1
        if not (0 <= idx < len(sessions)):
            display_queue.put({'done': f'❌ 索引越界（有效范围 1-{len(sessions)}）', 'source': 'system'})
            return None
        reset_conversation(agent, message=None)
        msg, _ = restore(agent, sessions[idx][0])
        display_queue.put({'done': msg, 'source': 'system'})
        return None
    return query


_INJECT_MARKERS = ('### [WORKING MEMORY]', '[SYSTEM TIPS]', '[SYSTEM]', '[System]',
                   '[DANGER]', '### [总结提炼经验]')

# project_mode 插件把 `\n\n---\n[PROJECT MODE: <name>]\n…\n---` 追加在用户消息末尾
# (见 plugins/project_mode._build_injection)。它会进日志,所以 /continue 重建 UI 时
# 必须从显示文本里剔除,只留用户原话。不能加进 _INJECT_MARKERS——那会把整块(连用户
# 原话)一起丢弃;这里只剜掉注入这一段后缀。
_PM_BLOCK_RE = re.compile(r"\n*-{3,}\n\[PROJECT MODE:.*?\n-{3,}\s*$", re.DOTALL)


def strip_project_mode(text: str) -> str:
    """剔除用户文本尾部的 project-mode 注入块。"""
    return _PM_BLOCK_RE.sub("", text or "")


def _user_text(prompt_body):
    """User-typed text from a prompt JSON; '' if this is an agent auto-continuation.

    A Prompt is auto-continue when *either* (a) it carries any tool_result block
    (so it's the next round of an in-flight LLM call), or (b) its text blocks all
    match known injection prefixes ([WORKING MEMORY], [SYSTEM TIPS], [System]
    regenerate prompts, [DANGER] guards, etc.). Real first-prompts only contain
    one plain text block with no injection markers.
    """
    try: msg = json.loads(prompt_body)
    except Exception: return ''
    if not isinstance(msg, dict): return ''
    blocks = msg.get('content', []) or []
    if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in blocks):
        return ''
    for blk in blocks:
        if isinstance(blk, dict) and blk.get('type') == 'text':
            t = strip_project_mode(blk.get('text') or '').strip()
            if t and not any(mk in t for mk in _INJECT_MARKERS): return t
    return ''


def _assistant_text(response_body):
    """Joined plain text from a response blocks repr; '' on parse failure.
    Used by /export to grab the model's prose only, without tool noise.
    """
    try: blocks = ast.literal_eval(response_body)
    except Exception: return ''
    if not isinstance(blocks, list): return ''
    return '\n'.join(b['text'] for b in blocks
                     if isinstance(b, dict) and b.get('type') == 'text'
                     and isinstance(b.get('text'), str) and b['text'].strip())


def _format_tool_use(block):
    """Match agent_loop.py:78 verbose tool-call header byte-for-byte.

    MUST use agent_loop's `get_pretty_json`, not a plain `json.dumps`: the
    former rewrites a `script` arg's `"; "` into `";\\n  "`, so for tools
    carrying `script` (code_run, web_execute_js) a plain dumps produces a
    *different* fence body. The TUI's write/read/code cards content-address
    their captures by `hash(get_pretty_json(args))`; a mismatched fence here
    means the hash misses and the card silently falls back to the raw block."""
    name = block.get('name', '?')
    args = block.get('input', {})
    try:
        from agent_loop import get_pretty_json
        pretty = get_pretty_json(args)
    except Exception:
        try: pretty = json.dumps(args, indent=2, ensure_ascii=False).replace('\\n', '\n')
        except Exception: pretty = str(args)
    return f"🛠️ Tool: `{name}`  📥 args:\n````text\n{pretty}\n````\n"


def _format_tool_result(content):
    """Match agent_loop.py:79-81 five-backtick fence around tool output."""
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get('type') == 'text':
                parts.append(b.get('text', '') or '')
            elif isinstance(b, str):
                parts.append(b)
        body = '\n'.join(parts)
    else:
        body = '' if content is None else str(content)
    return f"`````\n{body}\n`````\n"


def _tool_results_from_prompt(prompt_body):
    """Return {tool_use_id: formatted_fence} from a Prompt JSON's content blocks."""
    try: msg = json.loads(prompt_body)
    except Exception: return {}
    if not isinstance(msg, dict): return {}
    out = {}
    for blk in msg.get('content', []) or []:
        if isinstance(blk, dict) and blk.get('type') == 'tool_result':
            tid = blk.get('tool_use_id') or ''
            if tid: out[tid] = _format_tool_result(blk.get('content'))
    return out


def _format_response_segment(response_body, tool_results):
    """Rebuild one LLM call's transcript slice: text blocks + tool_use headers +
    matching tool_result fences. Mirrors agent_loop verbose output so fold_turns
    sees the same string shape as live mode.
    """
    try: blocks = ast.literal_eval(response_body)
    except Exception: return ''
    if not isinstance(blocks, list): return ''
    texts, tool_parts = [], []
    for b in blocks:
        if not isinstance(b, dict): continue
        t = b.get('type')
        if t == 'text':
            s = b.get('text', '')
            if isinstance(s, str) and s.strip(): texts.append(s)
        elif t == 'tool_use':
            tool_parts.append(_format_tool_use(b))
            tid = b.get('id') or ''
            if tid and tid in tool_results: tool_parts.append(tool_results[tid])
    return '\n\n'.join(p for p in ['\n\n'.join(texts), '\n'.join(tool_parts)] if p)


_PLAN_ENTRY_RE = re.compile(r'enter_plan_mode\(\s*[\'"]([^\'"]+plan\.md)[\'"]')


def find_plan_entry(path):
    """Last `enter_plan_mode("…plan.md")` call in a model_responses log.

    Plan mode has exactly one entry point (plan_sop.md): a `code_run` tool call
    whose inline_eval script invokes `handler.enter_plan_mode(...)`. That call
    survives in the log as a structured `tool_use` block — unlike a plan path
    merely *mentioned* in chat text, it cannot be produced by the user typing
    a filename. Scanning these blocks is therefore the restore criterion for
    the plan card; the last match wins so re-entered plans track the newest.

    Returns the plan.md path string as written in the script, or None.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return None
    last = None
    for _prompt, response in _pairs(content):
        try:
            blocks = ast.literal_eval(response)
        except Exception:
            continue
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not (isinstance(b, dict) and b.get('type') == 'tool_use'
                    and b.get('name') == 'code_run'):
                continue
            m = _PLAN_ENTRY_RE.search(str((b.get('input') or {}).get('script') or ''))
            if m:
                last = m.group(1)
    return last


def iter_write_captures(path):
    """Replay a log's file_write/file_patch/file_read calls into capture dicts
    the TUI can feed to its card renderers (`_WRITE_CAP`), keyed later by
    hash(get_pretty_json).

    Live mode fills `_WRITE_CAP` from tool_before/tool_after hooks (with a real
    pre-write disk snapshot); on /continue that history is gone, but the
    structured `tool_use.input` survives in the log — clean, complete args. We
    also track each path's content *within this session* so a file
    written/patched several times shows real old→new diffs (not N× full "new
    file"). Files first touched by an untracked on-disk state still fall back
    to a full-content block.

    Returns write entries `{"name", "args", "existed", "old", "status", "msg"}`
    and read entries `{"name", "args", "content"}` in call order. `status`/`msg`
    come from the matching tool_result so the header can show ✗ on a failed
    write; a read's `content` is the raw tool_result text (the read card strips
    its LLM-facing chrome itself).
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return []
    pairs = _pairs(content)
    # tool_use_id -> (status, msg) from any prompt's tool_result blocks (the
    # result lands in the *next* round's Prompt as a tool_result whose content
    # is the json-dumped outcome.data, e.g. {"status":"success","msg":...}).
    # tr_raw keeps the undecoded text — a file_read result is plain text.
    tr_status, tr_raw = {}, {}
    for prompt, _ in pairs:
        try:
            msg_obj = json.loads(prompt)
        except Exception:
            continue
        if not isinstance(msg_obj, dict):
            continue
        for blk in msg_obj.get('content', []) or []:
            if not (isinstance(blk, dict) and blk.get('type') == 'tool_result'):
                continue
            tid = blk.get('tool_use_id')
            c = blk.get('content')
            if isinstance(c, list):
                c = ''.join(b.get('text', '') for b in c
                            if isinstance(b, dict) and b.get('type') == 'text')
            if tid and isinstance(c, str):
                tr_raw[tid] = c
            try:
                d = json.loads(c) if isinstance(c, str) else None
            except Exception:
                d = None
            if tid and isinstance(d, dict):
                tr_status[tid] = (d.get('status'), str(d.get('msg') or ''))

    out, state = [], {}
    for _prompt, response in pairs:
        try:
            blocks = ast.literal_eval(response)
        except Exception:
            continue
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not (isinstance(b, dict) and b.get('type') == 'tool_use'):
                continue
            name = b.get('name')
            if name not in ('file_write', 'file_patch', 'file_read', 'code_run'):
                continue
            args = b.get('input') or {}
            p = args.get('path')
            if name == 'file_read':
                out.append({'name': name, 'args': args,
                            'content': tr_raw.get(b.get('id'))})
                continue
            if name == 'code_run':
                # data = the tool_result text; a dict result is JSON, an
                # inline_eval / code-missing result is plain text. Pass the
                # parsed dict when possible so the card reads exit_code/stdout;
                # else the raw string (the card handles both).
                raw = tr_raw.get(b.get('id'))
                d = raw
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else None
                    if isinstance(parsed, dict):
                        d = parsed
                except Exception:
                    pass
                out.append({'name': name, 'args': args, 'data': d})
                continue
            st, mg = tr_status.get(b.get('id'), (None, ''))
            if name == 'file_patch':
                # If this file's content is tracked within the session, pass it as
                # the pre-write full file so the renderer can do a whole-file diff
                # (real line numbers + context); else fall back to the fragment.
                pre = state.get(p, '')
                out.append({'name': name, 'args': args,
                            'existed': p in state, 'old': pre,
                            'status': st, 'msg': mg})
                if st == 'error':
                    continue  # failed call left the disk untouched — don't book it
                old = args.get('old_content') or ''
                if p in state and old:
                    state[p] = state[p].replace(old, args.get('new_content') or '', 1)
            else:  # file_write
                existed = p in state
                old = state.get(p, '')
                new = str(args.get('content') or '')
                mode = str(args.get('mode') or 'overwrite')
                out.append({'name': name, 'args': args, 'existed': existed, 'old': old,
                            'status': st, 'msg': mg})
                if st == 'error':
                    continue  # failed call left the disk untouched — don't book it
                if mode == 'append':
                    state[p] = old + new
                elif mode == 'prepend':
                    state[p] = new + old
                else:
                    state[p] = new
    return out


def extract_ui_messages(path):
    """Parse a model_responses log into [{role, content}, ...] for UI replay.

    Each user-initiated round becomes one user bubble plus one assistant bubble.
    Auto-continuation LLM calls are concatenated into the same assistant bubble,
    separated by ``**LLM Running (Turn N) ...**`` markers. Tool calls and their
    results are rendered into the assistant content using the same string format
    that agent_loop yields live, so fold_turns can fold them identically.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f: content = f.read()
    except Exception: return []
    pairs = _pairs(content)
    if not pairs: return []
    # tool_results live in the *next* Prompt's content; index look-ahead.
    next_tr = [{} for _ in pairs]
    for i in range(len(pairs) - 1):
        next_tr[i] = _tool_results_from_prompt(pairs[i + 1][0])

    out, assistant, round_turn = [], None, 0
    for i, (prompt, response) in enumerate(pairs):
        user = _user_text(prompt)
        seg = _format_response_segment(response, next_tr[i])
        if user:
            if assistant is not None: out.append(assistant)
            out.append({'role': 'user', 'content': user})
            # Turn 1 marker too — agent_loop yields one per LLM call, including the
            # first, so fold_turns treats every non-last call uniformly as a fold.
            assistant = {'role': 'assistant',
                         'content': f"\n\n**LLM Running (Turn 1) ...**\n\n{seg}"}
            round_turn = 1
        else:
            if assistant is None:
                assistant = {'role': 'assistant', 'content': ''}
                round_turn = 1
            round_turn += 1
            marker = f"\n\n**LLM Running (Turn {round_turn}) ...**\n\n"
            assistant['content'] = (assistant['content'] or '') + marker + seg
    if assistant is not None: out.append(assistant)
    return [m for m in out if (m.get('content') or '').strip()]


def handle_frontend_command(agent, query, exclude_pid=None):
    """Frontend-friendly /continue entry that returns text directly."""
    s = (query or '').strip()
    exclude_pid = os.getpid() if exclude_pid is None else exclude_pid
    if s == '/continue':
        return format_list(list_sessions(exclude_pid=exclude_pid))
    m = re.match(r'/continue\s+(\d+)\s*$', s)
    if not m:
        return '用法: /continue 或 /continue N'
    sessions = list_sessions(exclude_pid=exclude_pid)
    idx = int(m.group(1)) - 1
    if not (0 <= idx < len(sessions)):
        return f'❌ 索引越界（有效范围 1-{len(sessions)}）'
    reset_conversation(agent, message=None)
    msg, _ = restore(agent, sessions[idx][0])
    return msg


# ===========================================================================
# 原地复原(in-place continue)共享层 —— 仅供 TUI(tui_v2/tui_v3 及其 rewind 副本)
# 调用;其它前端(IM/qt/streamlit…)不调用这些函数,行为完全不受影响。
#
# 模型:每个会话 = 一个 `model_responses_<logid>.txt`,身份就是文件本身。
#   · 原地续 X = 把 agent 的 log_path 指回 X,之后的轮次追加到 X 本身(同一会话延续)。
#   · 拷贝续 X = 铸一个新 logid、把 X 拷进去,在副本上续;X 原件不动(并发安全)。
#   · 切走/新对话 = 释放当前锁、旧日志原样留作"空闲会话"(不存快照、不清空),新对话铸新 logid。
#
# 独占:每个 TUI 会话出生即持有自己日志的一把锁(`.locks/<logid>.lock`);
#   整进程共用一个心跳线程,每 ~5s touch 锁文件 mtime(无 fsync)。
#   判活 = 锁 mtime 在 30s 内新鲜;超 30s 视为持锁者已死,可被接管。
#   抢锁用原子 O_EXCL;锁基础设施任何故障都降级为"假定空闲、放行续接",绝不阻断 /continue。
# ===========================================================================

_LOCK_DIR = os.path.join(_LOG_DIR, '.locks')
_HB_INTERVAL = 5.0       # 心跳间隔(秒)
_STALE_AFTER = 30.0      # 超过这么久无心跳 → 持锁者视为已死,可接管
_held_locks = set()      # 本进程当前持有的 log_path 集合
_hb_lock = threading.Lock()
_hb_thread = None


def _lock_path(log_path):
    base = os.path.splitext(os.path.basename(log_path))[0]
    return os.path.join(_LOCK_DIR, base + '.lock')


def _read_lock(lock_file):
    try:
        with open(lock_file, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def _lock_fresh(lock_file):
    """心跳新鲜度 = 锁文件 mtime 距今 < _STALE_AFTER。"""
    try:
        return (time.time() - os.path.getmtime(lock_file)) < _STALE_AFTER
    except OSError:
        return False


def session_occupant(log_path):
    """若 `log_path` 正被一个活着的(心跳新鲜)进程持有,返回其 owner 元数据 dict;
    否则返回 None(空闲,或锁已过期可接管)。供 TUI 判断"原地 / 弹窗拷贝"。"""
    lf = _lock_path(log_path)
    meta = _read_lock(lf)
    if meta is not None and _lock_fresh(lf):
        return meta
    return None


def acquire_lock(log_path, agent_id=None):
    """尝试独占 `log_path`。成功(或锁设施故障降级)返回 True;
    仅当被另一活进程(心跳新鲜)持有时返回 False。"""
    try:
        os.makedirs(_LOCK_DIR, exist_ok=True)
        lf = _lock_path(log_path)
        meta = {'pid': os.getpid(), 'agent_id': agent_id,
                'log': os.path.basename(log_path),
                'started': time.time()}
        blob = json.dumps(meta, ensure_ascii=False)
        try:
            fd = os.open(lf, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(blob)
        except FileExistsError:
            cur = _read_lock(lf)
            if cur and cur.get('pid') != os.getpid() and _lock_fresh(lf):
                return False                      # 被另一活进程持有
            # 过期锁 / 本进程自己的 → 接管(覆盖)。小竞态窗口可接受。
            try: os.remove(lf)
            except OSError: pass
            try:
                fd = os.open(lf, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                    fh.write(blob)
            except FileExistsError:
                cur2 = _read_lock(lf)
                if cur2 and cur2.get('pid') != os.getpid() and _lock_fresh(lf):
                    return False                  # 抢锁竞态输了
                with open(lf, 'w', encoding='utf-8') as fh:
                    fh.write(blob)
        with _hb_lock:
            _held_locks.add(log_path)
        _ensure_hb_thread()
        return True
    except Exception:
        # 锁设施故障绝不阻断续接 —— 降级为"假定空闲、放行"。
        return True


def release_lock(log_path):
    """释放本进程对 `log_path` 的锁(只删自己持有/无主的锁文件)。"""
    with _hb_lock:
        _held_locks.discard(log_path)
    try:
        lf = _lock_path(log_path)
        cur = _read_lock(lf)
        if cur is None or cur.get('pid') == os.getpid():
            os.remove(lf)
    except Exception:
        pass


def _hb_tick():
    now = time.time()
    with _hb_lock:
        items = list(_held_locks)
    for lp in items:
        try:
            os.utime(_lock_path(lp), (now, now))   # 仅更新 mtime,无 fsync
        except OSError:
            pass


def _hb_loop():
    while True:
        time.sleep(_HB_INTERVAL)
        try:
            _hb_tick()
        except Exception:
            pass


def _ensure_hb_thread():
    global _hb_thread
    with _hb_lock:
        if _hb_thread is None:
            _hb_thread = threading.Thread(target=_hb_loop,
                                          name='ga-session-heartbeat', daemon=True)
            _hb_thread.start()


@atexit.register
def _release_all_locks():
    for lp in list(_held_locks):
        release_lock(lp)


def _new_log_path():
    """铸一个新的 6 位 logid 日志路径(与 agentmain 同公式)。"""
    logid = f'{(time.time_ns() + random.randrange(1_000_000)) % 1_000_000:06d}'
    return os.path.join(_LOG_DIR, f'model_responses_{logid}.txt')


def _retarget_log(agent, new_path):
    """把 agent(及其所有 llmclient)的日志写入点切到 new_path —— 之后的轮次写这里。"""
    try:
        agent.log_path = new_path
    except Exception:
        pass
    for client in _agent_clients(agent):
        try: client.log_path = new_path
        except Exception: pass


def is_snapshot(path):
    """遗留快照存档(model_responses_snapshot_*.txt)。这类只能拷贝续,不参与原地
    (provisional,待 worktree 复审)。"""
    return os.path.basename(path).startswith('model_responses_snapshot_')


def _clear_conversation_state(agent):
    """清空对话状态(对齐 reset_conversation,但不碰日志文件)。"""
    if hasattr(agent, 'history'):
        agent.history = []
    for client in _agent_clients(agent):
        backend = getattr(client, 'backend', None)
        if backend is not None and hasattr(backend, 'history'):
            backend.history = []
        if hasattr(client, 'last_tools'):
            client.last_tools = ''
    if hasattr(agent, 'handler'):
        agent.handler = None


def acquire_birth_lock(agent, agent_id=None):
    """会话出生时持有自己当前日志的锁(新 logid 必然抢到)。TUI 在建会话时调用,
    使本会话对"占用检测"可见 —— 别的会话才能据此判定它是否还活着。"""
    lp = getattr(agent, 'log_path', '') or ''
    if lp:
        acquire_lock(lp, agent_id)


def release_current(agent):
    """切走:释放 agent 当前日志的锁,旧日志原样留作"空闲会话"(不存快照、不清空)。"""
    lp = getattr(agent, 'log_path', '') or ''
    if lp:
        release_lock(lp)


def begin_fresh_session(agent, agent_id=None):
    """新对话 / clear:释放当前锁(旧日志留作空闲会话)→ 铸新 logid 重指 → 持新锁 →
    清空对话状态。**替代 TUI 里的 reset_conversation**(不再存快照/清空旧日志)。"""
    try: agent.abort()
    except Exception: pass
    release_current(agent)
    newp = _new_log_path()
    _retarget_log(agent, newp)
    acquire_lock(newp, agent_id)
    _clear_conversation_state(agent)


def _load_history_into(agent, path):
    """把 `path` 解析进 backend.history(native;否则降级摘要)。镜像 restore() 的解析,
    但不 abort/不快照(日志重指由调用方先做好)。返回 (msg, is_full)。"""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            content = fh.read()
    except Exception as e:
        return f'❌ 读取失败: {e}', False
    pairs = _pairs(content)
    if not pairs:
        return f'❌ {os.path.basename(path)} 为空或格式不符', False
    history = _parse_native_history(pairs)
    name = os.path.basename(path)
    if history is not None:
        _replace_backend_history(agent, history)
        return f'✅ 已恢复 {len(pairs)} 轮完整对话（{name}）', True
    from chatapp_common import _restore_native_history, _restore_text_pairs
    summary = _restore_text_pairs(content) or _restore_native_history(content)
    if not summary:
        return f'❌ {name} 无法解析（非 native 且无摘要可提取）', False
    if hasattr(agent, 'history'):
        agent.history.extend(summary)
    n = sum(1 for l in summary if l.startswith('[USER]: '))
    return f'⚠️ 非 native 格式，降级恢复 {n} 轮摘要（{name}）', False


def continue_inplace(agent, path, agent_id=None):
    """原地续:把 agent 的日志指回 `path` 本身,之后轮次追加到 X,延续同一会话。
    调用方应已确认空闲(session_occupant 为 None);抢锁失败(被占)返回错误。
    返回 (msg, ok)。"""
    try: agent.abort()
    except Exception: pass
    if not acquire_lock(path, agent_id):       # 先抢到目标锁;失败则保持现状,不丢自己的锁
        return '❌ 会话已被占用，无法原地接管', False
    cur = getattr(agent, 'log_path', '') or ''
    if cur and os.path.basename(cur) != os.path.basename(path):
        release_lock(cur)                       # 目标到手,旧会话释放为空闲(同一文件则不放)
    _retarget_log(agent, path)
    return _load_history_into(agent, path)


def continue_copy(agent, path, agent_id=None):
    """拷贝续:铸新 logid、把 `path` 内容拷进去,在副本上续;`path` 原件不动。
    用于"被占用→用户选拷贝"以及快照源。返回 (msg, ok)。"""
    try: agent.abort()
    except Exception: pass
    release_current(agent)
    newp = _new_log_path()
    try:
        shutil.copyfile(path, newp)
    except Exception:
        pass
    acquire_lock(newp, agent_id)
    _retarget_log(agent, newp)
    return _load_history_into(agent, newp)


def install(cls):
    """Wrap cls._handle_slash_cmd so /continue is handled before original dispatch."""
    orig = cls._handle_slash_cmd
    if getattr(orig, '_continue_patched', False): return
    def patched(self, raw_query, display_queue):
        if (raw_query or '').startswith('/continue'):
            r = handle(self, raw_query, display_queue)
            if r is None: return None
        return orig(self, raw_query, display_queue)
    patched._continue_patched = True
    cls._handle_slash_cmd = patched
