"""`/continue` command: list & restore past model_responses sessions.
Pure functions + one `install(cls)` monkey-patch entry. No side effects at import.
"""
import ast, glob, json, os, re, time
_LOG_GLOB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'temp', 'model_responses', 'model_responses_*.txt')
_BLOCK_RE = re.compile(r'^=== (Prompt|Response) ===.*?\n(.*?)(?=^=== (?:Prompt|Response) ===|\Z)',
                       re.DOTALL | re.MULTILINE)

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
                t = (blk.get('text') or '').strip()
                if t and '<history>' not in t and not t.startswith('### [WORKING MEMORY]'):
                    return t
    for p, _ in pairs[:1]:
        for line in p.splitlines():
            s = line.strip()
            if s and not s.startswith('###'): return s
    return ''

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

def list_sessions(exclude_pid=None):
    """Newest-first list of (path, mtime, first_user_text, n_rounds)."""
    files = glob.glob(_LOG_GLOB)
    if exclude_pid is not None:
        tag = f'model_responses_{exclude_pid}.txt'
        files = [f for f in files if not f.endswith(tag)]
    out = []
    for f in files:
        try:
            content = open(f, encoding='utf-8', errors='replace').read()
        except Exception: continue
        pairs = _pairs(content)
        if not pairs: continue
        out.append((f, os.path.getmtime(f), _first_user(pairs), len(pairs)))
    out.sort(key=lambda x: x[1], reverse=True)
    return out
_MD_ESCAPE_RE = re.compile(r'([\\`*_\[\]])')
def _escape_md(s): return _MD_ESCAPE_RE.sub(r'\\\1', s)

def format_list(sessions, limit=20):
    if not sessions: return '❌ 没有可恢复的历史会话'
    lines = ['**可恢复会话**（输入 `/continue N` 恢复第 N 个）：', '']
    for i, (_, mtime, first, n) in enumerate(sessions[:limit], 1):
        preview = _escape_md((first or '（无法预览）').replace('\n', ' ')[:60])
        lines.append(f'{i}. `{_rel_time(mtime)}` · **{n} 轮** · {preview}')
    return '\n'.join(lines)

def restore(agent, path):
    """Restore session at path. Returns (msg, is_full)."""
    try: content = open(path, encoding='utf-8', errors='replace').read()
    except Exception as e: return f'❌ 读取失败: {e}', False
    pairs = _pairs(content)
    if not pairs: return f'❌ {os.path.basename(path)} 为空或格式不符', False
    history = _parse_native_history(pairs)
    name = os.path.basename(path)
    if history is not None:
        agent.abort()
        agent.llmclient.backend.history = history
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
        msg, _ = restore(agent, sessions[idx][0])
        display_queue.put({'done': msg, 'source': 'system'})
        return None
    return query
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
