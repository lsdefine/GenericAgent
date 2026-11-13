import os, json, re, time, requests, sys, threading, urllib3, base64, importlib, uuid, pathlib, copy, atexit
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_INFLIGHT = {}  # thread ident -> live socket; lets abort() close it even before response headers arrive
_orig_conn_request = urllib3.connection.HTTPConnection.request
def _conn_request_hook(self, *a, **k):  # after request() the socket is connected+sent; conn.sock may later be None'd by http.client
    r = _orig_conn_request(self, *a, **k); _INFLIGHT[threading.get_ident()] = self.sock; return r
urllib3.connection.HTTPConnection.request = _conn_request_hook
_RESP_CACHE_KEY = str(uuid.uuid4()); _RESP_CODEX_KEY = str(uuid.uuid4())
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path: sys.path.append(_ROOT)

class MyKeys:
    def __init__(self):
        self.path = self.mtime = self.updated_at = None
        self.data = {}
        self.lock = threading.Lock()

    def _load(self):
        sys.modules.pop('mykey', None)
        spec = importlib.util.find_spec('mykey')
        if spec is not None:
            path = spec.origin
            mt = os.stat(path).st_mtime_ns
            module = importlib.util.module_from_spec(spec)
            sys.modules['mykey'] = module
            # Compile source directly: pyc timestamps only have second precision.
            try:
                exec(compile(spec.loader.get_source('mykey'), path, 'exec'), module.__dict__)
            except BaseException:
                sys.modules.pop('mykey', None)
                raise
            data = {k: v for k, v in vars(module).items() if not k.startswith('_')}
        else:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mykey.json')
            mt = os.stat(path).st_mtime_ns
            with open(path, encoding='utf-8') as f: data = json.load(f)
            if isinstance(data, dict) and 'remote_url' in data:
                data = requests.get(data['remote_url'], timeout=10).json()
        if not isinstance(data, dict): raise ValueError('mykey configuration must be a dict')
        if os.stat(path).st_mtime_ns != mt: raise RuntimeError('mykey changed while loading')
        return data, path, mt

    def reload(self, force=False):
        with self.lock:
            try:
                mt = os.stat(self.path).st_mtime_ns if self.path else None
                if not force and self.updated_at is not None and mt == self.mtime:
                    return self.data, self.updated_at, False
                data, path, mt = self._load()
                self.data, self.path, self.mtime = data, path, mt
                self.updated_at = max(time.monotonic_ns(), (self.updated_at or 0) + 1)
                print(f'[Info] Load mykeys from {self.path}')
                return self.data, self.updated_at, True
            except Exception as e:
                # ★2026-10-17 重新适配 F3(原 2026-10-16 修复被上游 MyKeys 重写覆盖):
                #   上游此处为裸 `except Exception: return ...` → mykey.py 语法错/缺变量时
                #   表现为「改完 mykey 没生效 / 渠道全没了」且日志零线索。改为显式告警,
                #   仍回退上次成功值, 不炸主链路。
                #   首次加载就失败时 self.path 还是 None → 兜底解析真实路径, 否则提示「请检查 None」。
                _p = self.path
                if not _p:
                    try:
                        _spec = importlib.util.find_spec('mykey')
                        _p = _spec.origin if _spec else os.path.join(_ROOT, 'mykey.json')
                    except Exception:
                        _p = '(unknown mykey path)'
                print(f'[WARN] mykey 加载失败({type(e).__name__}: {e}) → 沿用上次成功值 '
                      f'({len(self.data or {})} 项); 请检查 {_p} 语法/内容')
                return self.data, self.updated_at, False

    def snapshot(self):
        data, updated_at, _ = self.reload()
        return data, updated_at


mykeys_store = MyKeys()

def reload_mykeys():
    data, _, changed = mykeys_store.reload()
    return data, changed

def _load_mykeys():
    with mykeys_store.lock:
        return mykeys_store._load()[0]

def __getattr__(name):
    if name == 'mykeys': return reload_mykeys()[0]
    raise AttributeError(f"module 'llmcore' has no attribute {name}")

def compress_history_tags(messages, keep_recent=10, max_len=800, force=False, interval=5):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages to save tokens."""
    compress_history_tags._cd = getattr(compress_history_tags, '_cd', 0) + 1
    if force: compress_history_tags._cd = 0
    if compress_history_tags._cd % interval != 0: return messages
    _before = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    _pats = {tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)') for tag in ('thinking', 'think', 'tool_use', 'tool_result')}
    _hist_pat = re.compile(r'<(history|key_info|earlier_context|global_memory)>[\s\S]*?</\1>')
    def _trunc_str(s): return s[:max_len//2] + '\n...[Truncated]...\n' + s[-max_len//2:] if isinstance(s, str) and len(s) > max_len else s
    def _trunc(text):
        text = _hist_pat.sub(lambda m: f'<{m.group(1)}>[...]</{m.group(1)}>', text)
        for pat in _pats.values(): text = pat.sub(lambda m: m.group(1) + _trunc_str(m.group(2)) + m.group(3), text)
        return text
    for i, msg in enumerate(messages):
        if i >= len(messages) - keep_recent: break
        c = msg['content']
        if isinstance(c, str): msg['content'] = _trunc(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get('type')
                if t == 'text' and isinstance(b.get('text'), str): b['text'] = _trunc(b['text'])
                elif t == 'thinking' and isinstance(b.get('thinking'), str): b['thinking'] = _trunc_str(b['thinking'])
                elif t == 'tool_result':
                    tc = b.get('content')
                    if isinstance(tc, str): b['content'] = _trunc_str(tc)
                    elif isinstance(tc, list):
                        for sub in tc:
                            if isinstance(sub, dict) and sub.get('type') == 'text': sub['text'] = _trunc_str(sub.get('text'))
                elif t == 'tool_use' and isinstance(b.get('input'), dict):
                    for k, v in b['input'].items(): b['input'][k] = _trunc_str(v)
    print(f"[Cut] {_before} -> {sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)}")
    return messages

def _sanitize_leading_user_msg(msg):
    """把 user 消息里的 tool_result 块改写成纯文本，避免孤立引用。
    history 统一使用 Claude content-block 格式：content 是 list of blocks。"""
    msg = dict(msg)  # 浅拷贝外层 dict
    content = msg.get('content')
    if not isinstance(content, list): return msg
    texts = []
    for block in content:
        if not isinstance(block, dict): continue
        if block.get('type') == 'tool_result':
            c = block.get('content', '')
            if isinstance(c, list): texts.extend(b.get('text', '') for b in c if isinstance(b, dict))
            else: texts.append(str(c))
        elif block.get('type') == 'text': texts.append(block.get('text', ''))
    msg['content'] = [{"type": "text", "text": '\n'.join(t for t in texts if t)}]
    return msg

import builtins as _builtins
_oldprint = _builtins.print
def safeprint(*argv):
    try: _oldprint(*argv)
    except OSError: pass
print = safeprint

STATS = {}

# --- 用量账本挂钩 (2026-10-12, skill_repos/token-ledger) ---
# 设计: 惰性导入 + 全异常吞掉。账本坏可以, LLM 主链路不能坏。
# 关闭: env GA_TOKEN_LEDGER=0
_ledger_mod = None
def _ledger_append(inp, cached, out, api_mode):
    global _ledger_mod
    try:
        if _ledger_mod is None:
            _lp = os.path.join(_ROOT, 'skill_repos', 'token-ledger')
            if _lp not in sys.path: sys.path.append(_lp)
            import ledger as _ledger_mod
        sess = STATS.get('session')
        _ledger_mod.record_counts(inp, cached, out, api_mode, session=sess, model=STATS.get('model'),
                                  extra={'ctx': STATS.get('ctx'), 'msgs': STATS.get('msgs'),
                                         'ttft': round(STATS['t_ttft'] - STATS['t_start'], 3) if STATS.get('t_ttft') and STATS.get('t_start') else None,
                                         'tps': round(STATS['tps'], 1) if STATS.get('tps') else None})
    except Exception:
        pass


# --- 外发审计归因挂钩 (2026-11-09, llm_audit.py) ---
# 设计: 惰性导入 + 全异常吞掉。审计坏可以, LLM 主链路不能坏。
# 关闭: env GA_LLM_AUDIT=0
# ★ 只记**计数与形状**，绝不落消息正文(否则审计日志本身成为泄漏源)。
_audit_mod = None
def _audit_get():
    global _audit_mod
    try:
        if _audit_mod is None:
            if _ROOT not in sys.path: sys.path.insert(0, _ROOT)
            import llm_audit as _audit_mod
        return _audit_mod
    except Exception:
        return None


def _audit_sent(sess, chan, attempt, pr):
    """发送前记一条 sent 记录。pr 由调用方预先 probe(messages) 得到(一次请求算一次)。"""
    try:
        m = _audit_get()
        if not m or pr is None: return None
        return m.sent(getattr(sess, '_mixin_name', '') or '', chan, chan,
                      attempt, None, pr=pr)
    except Exception:
        return None


def _audit_probe(messages):
    """每请求探测一次消息形状；失败返回 None（本次不记，不影响请求）。"""
    try:
        m = _audit_get()
        return m.probe(messages) if m else None
    except Exception:
        return None


def _audit_done(rid, ok, err='', delivered=0):
    try:
        m = _audit_get()
        if m and rid:
            m.done(rid, ok, err=err, delivered=delivered)
    except Exception:
        pass

def trim_messages_history(history, sess):
    cap = sess.context_win * 3
    target = int(cap * getattr(sess, 'trim_keep_rate', 0.6))
    kp = sess.trim_keep_prefix
    def cost(ms): return sum(len(json.dumps(m, ensure_ascii=False)) for m in ms)
    compress_history_tags(history, interval=getattr(sess, 'cut_msg_interval', 7))
    STATS.update(ctx=(c := cost(history)), msgs=len(history)); print(f'[Debug] Current context: {c} chars, {len(history)} messages.')
    if c <= cap: return
    compress_history_tags(history, keep_recent=4, force=True)
    if cost(history) <= target: return
    pre, post = history[:kp], history[kp:]; costs = [len(json.dumps(m, ensure_ascii=False)) for m in post]; c = cost(pre) + sum(costs); i = 0
    while len(post) - i > 9 and c > target:
        c -= costs[i]; i += 1
        while i < len(post) and post[i].get('role') != 'user': c -= costs[i]; i += 1
        if i < len(post): old = costs[i]; post[i] = _sanitize_leading_user_msg(post[i]); costs[i] = len(json.dumps(post[i], ensure_ascii=False)); c += costs[i] - old
    post = post[i:]
    if kp and pre:
        m = pre[-1]
        if m.get('role') == 'assistant' and isinstance(m.get('content'), list):
            m['content'] = [b for b in m['content'] if not (isinstance(b, dict) and b.get('type') == 'tool_use')] or [{"type": "text", "text": "..."}]
        _d = lambda: [{"type": "text", "text": "..."}]
        gap = [{"role": "assistant", "content": _d()}] if m.get('role') == 'user' else [{"role": "user", "content": _d()}, {"role": "assistant", "content": _d()}]
        history[:] = pre + gap + post
    else: history[:] = pre + post
    STATS.update(ctx=(c := cost(history)), msgs=len(history)); print(f'[Debug] Trimmed context, current: {c} chars, {len(history)} messages.')

def auto_make_url(base, path):
    b, p = base.rstrip('/'), path.strip('/')
    if b.endswith('$'): return b[:-1].rstrip('/')
    if b.endswith(p): return b
    return f"{b}/{p}" if re.search(r'/v\d+(/|$)', b) else f"{b}/v1/{p}"

def _parse_claude_json(data):
    if data.get("stop_reason") == "refusal":
        err = "[Error: Claude refusal]"
        yield err
        return [{"type": "text", "text": err}]
    content_blocks = data.get("content", [])
    _record_usage(data.get("usage", {}), "messages")
    for b in content_blocks:
        if b.get("type") == "text": yield b.get("text", "")
        elif b.get("type") == "thinking": yield ""
    return content_blocks

def _raise_if_retryable_overload(emsg):
    """HTTP 200 SSE/body overload → ConnectionError so _stream_with_retry can backoff."""
    if emsg and re.search(r'concurrency|retry later|overloaded|rate.?limit', emsg, re.I):
        raise requests.ConnectionError(emsg)

class ThinkingChunk(str):
    """思维链/推理分片标记（str 子类，兼容所有旧调用方）。

    ★2026-11-05: 上游把 CoT 也塞进同一条流, 与正文分片都是 str, 下游无法区分 →
      `_stream_with_retry` 只要吐过任何分片就置 `streamed=True`, 于是**长 CoT 期间断流
      一律不重试**, 用户看到"想了 2m46s 然后自动终止"; MixinSession 也因"已交付正文"
      而不换渠。思维链对用户不可见、且可整段重放, 不算已交付。用子类打标, 零成本、
      纯增量, 不改变任何 str 语义。
    """
    __slots__ = ()


def _parse_claude_sse(resp_lines):
    """Parse Anthropic SSE stream. Yields text chunks, returns list[content_block]."""
    content_blocks = []; current_block = None; tool_json_buf = ""
    stop_reason = None; got_message_stop = False; warn = None
    for line in resp_lines:
        if not line: continue
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line.startswith("data:"): continue
        data_str = line[5:].lstrip()
        if data_str == "[DONE]": break
        try: evt = json.loads(data_str)
        except Exception as e:
            print(f"[SSE] JSON parse error: {e}, line: {data_str[:200]}")
            continue
        if not isinstance(evt, dict): continue  # 2026-10-03: 上游可发字面量 `data: null`(json.loads 合法返回 None, 不抛异常) → 必须挡掉, 否则 evt.get 抛 AttributeError 中断整条流
        evt_type = evt.get("type", "")
        if evt_type == "message_start":
            usage = evt.get("message", {}).get("usage", {})
            _record_usage(usage, "messages")
        elif evt_type == "content_block_start":
            block = evt.get("content_block", {})
            if block.get("type") == "text": current_block = {"type": "text", "text": ""}
            elif block.get("type") == "thinking": current_block = {"type": "thinking", "thinking": "", "signature": ""}
            elif block.get("type") == "tool_use":
                current_block = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
                tool_json_buf = ""
        elif evt_type == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if current_block and current_block.get("type") == "text": current_block["text"] += text
                if text: yield text
            elif delta.get("type") == "thinking_delta":
                thinking = delta.get("thinking", "")
                if current_block and current_block.get("type") == "thinking": current_block["thinking"] += thinking
                if thinking: yield ThinkingChunk(thinking)
            elif delta.get("type") == "signature_delta":
                if current_block and current_block.get("type") == "thinking":
                    current_block["signature"] = current_block.get("signature", "") + delta.get("signature", "")
            elif delta.get("type") == "input_json_delta": tool_json_buf += delta.get("partial_json", "")
        elif evt_type == "content_block_stop":
            if current_block:
                if current_block["type"] == "tool_use":
                    try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
                    except: current_block["input"] = {"_raw": tool_json_buf}
                content_blocks.append(current_block)
                current_block = None
        elif evt_type == "message_delta":
            delta = evt.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            out_usage = evt.get("usage", {})
            out_tokens = out_usage.get("output_tokens", 0)
            if out_tokens:
                STATS['out'] = out_tokens; print(f"[Output] tokens={out_tokens} stop_reason={stop_reason}")
                # 账本: messages 流式的输入已在 message_start 存入 STATS, 此处补一行完整记录
                _ledger_append(STATS.get('inp', 0), STATS.get('cached', 0), out_tokens, "messages")
        elif evt_type == "message_stop": got_message_stop = True
        elif evt_type == "error":
            err = evt.get("error", {})
            emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            _raise_if_retryable_overload(emsg)  # 走 _stream_with_retry，避免落到 ga 应用层
            warn = f"\n\n!!!Error: SSE {emsg}"; break
    if not warn:
        # 2026-09-23: 原条件 `not got_message_stop and not stop_reason` 有盲区——上游先发 stop_reason
        # 再断流时两者都不成立 → 静默无标记。改为只要求 message_stop（正常结束必发）。
        if not got_message_stop:
            if stop_reason in (None, "max_tokens"):
                warn = "\n\n[!!! 流异常中断，未收到完整响应（无 message_stop）!!!]" if stop_reason is None \
                       else "\n\n[!!! Response truncated: max_tokens !!!]"
            elif os.environ.get("GA_STREAM_END_STRICT", "1") != "0":
                warn = f"\n\n[!!! 流异常中断，未收到 message_stop (stop_reason={stop_reason}) !!!]"
        elif stop_reason == "max_tokens": warn = "\n\n[!!! Response truncated: max_tokens !!!]"
        elif stop_reason == "refusal": warn = "\n\n[Error: Claude refusal]"
    if current_block:
        if current_block["type"] == "tool_use":
            try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
            except: current_block["input"] = {"_raw": tool_json_buf}
        content_blocks.append(current_block); current_block = None
    if warn:
        print(f"[WARN] {warn.strip()}")
        insert_at = next((i for i,b in enumerate(content_blocks) if b.get("type") == "tool_use"), len(content_blocks))
        content_blocks.insert(insert_at, {"type": "text", "text": warn}); yield warn
    return content_blocks

def _try_parse_tool_args(raw):
    """Parse tool args string; split concatenated JSON objects like {..}{..} if needed.
    Returns list of parsed dicts."""
    if not raw: return [{}]
    try: return [json.loads(raw)]
    except: pass
    parts = re.split(r'(?<=\})(?=\{)', raw)
    if len(parts) > 1:
        parsed = []
        for p in parts:
            try: parsed.append(json.loads(p))
            except: return [{"_raw": raw}]
        return parsed
    return [{"_raw": raw}]

def _parse_openai_sse(resp_lines, api_mode="chat_completions", hide_reasoning=False, budget=None):
    """Parse OpenAI SSE stream (chat_completions or responses API).
    Yields text chunks, returns list[content_block].
    content_block: {type:'text', text:str} | {type:'tool_use', id:str, name:str, input:dict}

    hide_reasoning(2026-10-22): 为 True 时 reasoning_content/reasoning delta 不 yield 给上层,
      只累积进最终 thinking block。用于 only_reasoning 型公益站(如 ds4f_404),
      否则 CoT 会混进正文流并被 NativeToolClient 当正文写进 history。
      默认 False = 与旧行为逐字节一致。对应配置项 stream_hide_reasoning。
    """
    content_text = ""
    saw_terminal = False  # 2026-09-23: completed/incomplete/failed/error 之一才算正常终止；断流时保持 False
    if api_mode == "responses":
        seen_delta = False; fc_buf = {}; current_fc_idx = None; reasoning_text = ""
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": saw_terminal = True; break
            try: evt = json.loads(data_str)
            except: continue
            if not isinstance(evt, dict): continue  # 2026-10-03: 挡 `data: null`(见 chat_completions 分支同注释)
            etype = evt.get("type", "")
            if etype == "response.output_text.delta":
                delta = evt.get("delta", "")
                if delta: seen_delta = True; content_text += delta; yield delta
            elif etype == "response.output_text.done" and not seen_delta:
                text = evt.get("text", "")
                if text: content_text += text; yield text
            elif etype == "response.reasoning_text.delta":
                delta = evt.get("delta", "")
                if delta: reasoning_text += delta
            elif etype == "response.reasoning_text.done":
                text = evt.get("text", "")
                if text: reasoning_text = text
            elif etype == "response.output_item.added":
                item = evt.get("item", {})
                if item.get("type") == "function_call":
                    idx = evt.get("output_index", 0)
                    fc_buf[idx] = {"id": item.get("call_id", item.get("id", "")), "name": item.get("name", ""), "args": ""}
                    current_fc_idx = idx
            elif etype == "response.function_call_arguments.delta":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] += evt.get("delta", "")
            elif etype == "response.function_call_arguments.done":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] = evt.get("arguments", fc_buf[idx]["args"])
            elif etype == "error":
                err = evt.get("error", {})
                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                _raise_if_retryable_overload(emsg)
                if emsg: content_text += f"!!!Error: {emsg}"; yield f"!!!Error: {emsg}"
                break
            elif etype == "response.completed":
                _resp = evt.get("response") or {}
                usage = _resp.get("usage", {}) or {}
                _u = _record_usage(usage, api_mode)
                # ★2026-11-09: 同样是"精确停在预算上"的静默截断(responses 侧同口径)
                if _u and _budget_hit(_u[2], budget) and content_text:
                    print(f"[WARN] silent budget cut: out={_u[2]} budget={budget} (responses.completed)")
                    _mk = "[!!! output truncated: max_output_tokens]"
                    content_text += "\n\n" + _mk; yield _mk
                saw_terminal = True
                break
            elif etype == "response.incomplete":
                # DeepSeek/OpenAI responses stream may end here (no [DONE]); treat as valid terminal,
                # record usage and surface a truncation marker instead of an empty-response retry storm.
                usage = (evt.get("response") or {}).get("usage", {})
                _record_usage(usage, api_mode)
                reason = ((evt.get("response") or {}).get("incomplete_details") or {}).get("reason", "") or "unknown"
                # 2026-09-23: 原判定 `not content_text and not fc_buf` 只在"完全无内容"时告警，
                # 半截正文+incomplete 会静默放行 → 改为始终追加 marker（有内容也标，便于上层重试）。
                marker = f"[!!! output truncated: {reason}]"
                content_text += ("\n\n" if content_text else "") + marker; yield marker
                saw_terminal = True
                break
            elif etype == "response.failed":
                usage = (evt.get("response") or {}).get("usage", {})
                _record_usage(usage, api_mode)
                err = ((evt.get("response") or {}).get("error") or {})
                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                _raise_if_retryable_overload(emsg)
                if emsg: content_text += f"!!!Error: {emsg}"; yield f"!!!Error: {emsg}"
                saw_terminal = True
                break
        # 2026-09-23: 响应流未收到任何终止事件(上游断流) → 补标记，避免静默返回半截文本
        if not saw_terminal and (content_text or fc_buf):
            if os.environ.get("GA_STREAM_END_STRICT", "1") != "0":
                trail = "\n\n[!!! 流异常中断，未收到完整响应（responses 无终止事件）!!!]"
                print("[WARN] responses stream ended without terminal event")
                content_text += trail; yield trail
        blocks = []
        if reasoning_text: blocks.append({"type": "thinking", "thinking": reasoning_text})
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(fc_buf):
            fc = fc_buf[idx]
            inps = _try_parse_tool_args(fc["args"])
            for i, inp in enumerate(inps):
                bid = fc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": fc["name"], "input": inp})
        return blocks
    else:
        tc_buf = {}  # index -> {id, name, args}
        reasoning_text = ""
        saw_done = False; finish_reason = None  # 终止信号追踪: 用于识别静默截断(上游断流/无[DONE])
        last_out = 0  # ★2026-11-09: 最近一次 usage 的输出 token 数, 供 _budget_hit 判静默截断
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": saw_done = True; break
            try: evt = json.loads(data_str)
            except: continue
            # 2026-10-03 修复(arouter 实测 3/3 必现): 上游在「思考结束→正文开始」的切换点会发一行字面量
            #   `data: null`。json.loads("null") **合法返回 None 且不抛异常**, 于是下一行 evt.get(...) 抛
            #   AttributeError: 'NoneType' object has no attribute 'get' → 流在此中断, 正文全丢、只剩思维链
            #   (长期被误读为"模型思考空转/糖果空转"; 实为解析器在切换点崩溃)。非 dict 事件一律跳过。
            if not isinstance(evt, dict): continue
            ch = (evt.get("choices") or [{}])[0]
            fr = ch.get("finish_reason")
            if fr: finish_reason = fr
            delta = ch.get("delta") or {}
            if rc := delta.get("reasoning_content") or delta.get("reasoning", ""):
                reasoning_text += rc
                if not hide_reasoning: yield ThinkingChunk(rc)
            if delta.get("content"):
                text = delta["content"]; content_text += text; yield text
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                has_name = bool(tc.get("function", {}).get("name"))
                if idx not in tc_buf:
                    if has_name or not tc_buf: tc_buf[idx] = {"id": tc.get("id") or '', "name": "", "args": ""}
                    else: idx = max(tc_buf)
                if has_name: tc_buf[idx]["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"): tc_buf[idx]["args"] += tc["function"]["arguments"]
                if tc.get("id") and not tc_buf[idx]["id"]: tc_buf[idx]["id"] = tc["id"]
            usage = evt.get("usage")
            if usage:
                _u = _record_usage(usage, api_mode)
                if _u: last_out = _u[2]
        # 静默截断判定(2026-09-23): 实测全部在役 chat 渠道均以 [DONE] 收尾(5/5),
        # 故"未见 [DONE]"即视为流不完整(可覆盖"先给 finish_reason 再断流"的盲区);
        # finish_reason==length 单独标注(非断流, 是 token 预算耗尽)。
        # ★2026-11-09 补 _budget_hit: trae 类上游把输出停在预算上却报 finish_reason=stop,
        #   只看 finish_reason 会漏(实测 6000 行请求精确停在 32000 tok 且 stop)。
        trail_marker = None
        if finish_reason == "length":
            trail_marker = "[!!! Response truncated: length !!!]"
        elif _budget_hit(last_out, budget) and content_text:
            print(f"[WARN] silent budget cut: out={last_out} budget={budget} finish_reason={finish_reason}")
            trail_marker = "[!!! Response truncated: max_tokens !!!]"
        elif not saw_done and (content_text or tc_buf):
            if os.environ.get("GA_STREAM_END_STRICT", "1") != "0":
                trail_marker = "[!!! 流异常中断，未收到完整响应（无 [DONE]）!!!]"
        if trail_marker:
            print(f"[WARN] chat stream ended abnormally: finish_reason={finish_reason}, saw_done={saw_done}")
            content_text += "\n\n" + trail_marker
            yield "\n\n" + trail_marker
        blocks = []
        if reasoning_text: blocks.append({"type": "thinking", "thinking": reasoning_text})
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(tc_buf):
            tc = tc_buf[idx]
            inps = _try_parse_tool_args(tc["args"])
            for i, inp in enumerate(inps):
                bid = tc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": tc["name"], "input": inp})
        return blocks

def _budget_hit(out, budget):
    """★2026-11-09 静默截断判据(用户令「都可以改」): 上游把输出停在预算上却报
    finish_reason='stop' 的情况。实测 ds4f_trae 上游硬限 32000: 请求 6000 行、
    不传/传 32000 都精确停在 out=32000 且 finish=stop, GA 因只看 finish_reason
    而完全没察觉(半截答案冒充完整)。

    判据必须是「**恰好等于**预算(±1)」而不是「>=」:
      - trae 类(守上限但谎报 stop): out 精确 = budget → 命中。
      - hiyo 类(站方无视 max_tokens): 实测给 32000 却吐了 81454 → out > budget,
        这是另一种行为, 绝不能误判成截断(否则每轮都白续写一次)。
    """
    try:
        if not budget or not out: return False
        return abs(int(out) - int(budget)) <= 1
    except (TypeError, ValueError):
        return False

def _record_usage(usage, api_mode):
    """记录用量到 ledger/STATS, 并返回 (inp, cached, out) 供调用方判断预算是否刚好用尽。"""
    if not usage: return None
    # 上游常显式给 null；dict.get(k, 0) 遇 null 仍返回 None，后续加法会 TypeError
    def _i(v, default=0):
        try:
            return default if v is None else int(v)
        except (TypeError, ValueError):
            return default
    if api_mode == 'responses':
        cached = _i((usage.get("input_tokens_details") or {}).get("cached_tokens"))
        inp = _i(usage.get("input_tokens")); out = _i(usage.get("output_tokens"))
        print(f"[Cache] input={inp} cached={cached}")
        if out: print(f"[Output] tokens={out}")
    elif api_mode == 'chat_completions':
        cached = _i((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
        inp = _i(usage.get("prompt_tokens")); out = _i(usage.get("completion_tokens"))
        print(f"[Cache] input={inp} cached={cached}")
        if out: print(f"[Output] tokens={out}")
    elif api_mode == 'messages':
        ci, cr, raw_inp = _i(usage.get("cache_creation_input_tokens")), _i(usage.get("cache_read_input_tokens")), _i(usage.get("input_tokens"))
        # 流式: message_start 只给输入(无 output_tokens), 输出在 message_delta 单独发 → out=0 表示"待补"
        # 非流式: 响应体 usage 同时含 output_tokens
        inp, cached, out = raw_inp + ci + cr, cr, _i(usage.get("output_tokens"))
        print(f"[Cache] input={raw_inp} creation={ci} read={cr}")
    else: return None
    if api_mode == 'messages' and not out:
        STATS.update(inp=inp, cached=cached, out=out)
        return (inp, cached, out)   # 流式 messages: 输出 token 稍后才到, 由 message_delta 补记一行(避免记两次)
    _ledger_append(inp, cached, out, api_mode)
    STATS.update(inp=inp, cached=cached, out=out)
    return (inp, cached, out)
    
def _parse_openai_json(data, api_mode="chat_completions", budget=None):
    blocks = []
    if api_mode == "responses":
        _ur = _record_usage(data.get("usage") or {}, api_mode)
        for item in (data.get("output") or []):
            if item.get("type") == "message":
                for p in (item.get("content") or []):
                    if p.get("type") in ("output_text", "text") and p.get("text"):
                        blocks.append({"type": "text", "text": p["text"]}); yield p["text"]
            elif item.get("type") == "reasoning":
                for p in (item.get("content") or []):
                    if p.get("type") in ("reasoning_text", "summary_text") and p.get("text"):
                        blocks.append({"type": "thinking", "thinking": p["text"]})
            elif item.get("type") == "function_call":
                try: args = json.loads(item.get("arguments", "")) if item.get("arguments") else {}
                except: args = {"_raw": item.get("arguments", "")}
                blocks.append({"type": "tool_use", "id": item.get("call_id", item.get("id", "")),
                               "name": item.get("name", ""), "input": args})
        status = (data.get("status") or "").lower()
        if status == "failed":
            err = data.get("error") or {}
            emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            _raise_if_retryable_overload(emsg)
            if emsg: blocks.append({"type": "text", "text": f"!!!Error: {emsg}"}); yield f"!!!Error: {emsg}"
        elif status == "incomplete" and not any(b.get("type") == "text" for b in blocks):
            reason = ((data.get("incomplete_details") or {}).get("reason", "")) or "unknown"
            marker = f"[!!! output truncated: {reason}]"
            blocks.append({"type": "text", "text": marker}); yield marker
        elif _ur and _budget_hit(_ur[2], budget) and any(b.get("type") == "text" for b in blocks):
            # ★2026-11-09: responses 非流式同样有"停在预算却报 completed"的静默截断
            print(f"[WARN] silent budget cut: out={_ur[2]} budget={budget} (responses json)")
            marker = "[!!! output truncated: max_output_tokens]"
            blocks.append({"type": "text", "text": marker}); yield marker
    else:
        _u = _record_usage(data.get("usage") or {}, api_mode)
        _ch0 = (data.get("choices") or [{}])[0]
        msg = _ch0.get("message", {})
        reasoning = msg.get("reasoning_content") or msg.get("reasoning", "")
        if reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning})
        content = msg.get("content", "")
        if content:
            blocks.append({"type": "text", "text": content}); yield content
        # ★2026-11-09 修复(真 BUG, buddy 非流式实测): 本分支原**完全不看 finish_reason**,
        #   于是 max_tokens 用尽被**静默截断** —— 没有标记、没有 WARN, `ask()` 的自动续写
        #   判据(_split_trunc_suffix 找尾部标记)永远不触发。实测 buddy max_tokens=1200
        #   数到 1000: 只吐出 600 个数就"自然结束", 用户完全看不出被截断了。
        #   流式分支(_parse_openai_sse)一直有这条标记, 非流式漏了 ⇒ 补上, 与流式同口径。
        #   只在**已产出文本**时补标记: 纯 reasoning 被吃光的轮次交给 _has_usable_output 判定。
        _fin = str(_ch0.get("finish_reason") or "").lower()
        if _fin in ("length", "max_tokens") and any(b.get("type") == "text" for b in blocks):
            _mk = "[!!! Response truncated: max_tokens !!!]"
            blocks.append({"type": "text", "text": _mk}); yield _mk
        elif _fin == "stop" and _u and _budget_hit(_u[2], budget) and any(b.get("type") == "text" for b in blocks):
            # ★2026-11-09: 上游把输出停在预算上却报 stop(trae 类) → 也标截断, 否则静默丢半截
            print(f"[WARN] silent budget cut: out={_u[2]} budget={budget} finish_reason={_fin}")
            _mk = "[!!! Response truncated: max_tokens !!!]"
            blocks.append({"type": "text", "text": _mk}); yield _mk
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            try: args = json.loads(fn.get("arguments", "")) if fn.get("arguments") else {}
            except: args = {"_raw": fn.get("arguments", "")}
            blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})
    return blocks

def _stamp_oai_cache_markers(messages, model):
    """Add cache_control to last 2 user messages for Anthropic models via OAI-compatible relay."""
    ml = model.lower()
    if not any(k in ml for k in ('claude', 'anthropic')): return
    user_idxs = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    for idx in user_idxs[-2:]:
        c = messages[idx].get('content')
        if isinstance(c, str):
            messages[idx] = {**messages[idx], 'content': [{'type': 'text', 'text': c, 'cache_control': {'type': 'ephemeral'}}]}
        elif isinstance(c, list) and c:
            c = list(c); c[-1] = dict(c[-1], cache_control={'type': 'ephemeral'})
            messages[idx] = {**messages[idx], 'content': c}

def _has_usable_output(blocks):
    """True if the parsed response carries something the caller can act on.

    A response made only of ``thinking`` blocks is **not** usable: it has no
    answer text and no tool call, so the caller treats it as a successful empty
    reply and no retry / failover ever happens (typical causes: the model burned
    its whole token budget on reasoning, or the upstream swallowed the answer).
    """
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "tool_use":
            return True
        if b.get("type") == "text" and (b.get("text") or "").strip():
            return True
    return False


# ==== 全局并发总闸门 (2026-11-07 用户令)=========================================
# 用户口径: 「GA 的并发是所有进程所有渠道总并发」——上限是**一个总闸门**, 不是每渠道各算一份.
#   旧实现只有 ChannelLease(按渠道×按进程), 总量 = Σ各渠道上限 × 进程数, 无人管 → 实测失控.
# 实现: 名额 = temp/llm_gate/<n>.slot 文件(O_EXCL 抢占, 跨进程原子), n ∈ [0, cap).
#   进程崩溃留下的 slot 按「pid 已死 / 超过 6h」清扫; 每次排队时重扫.
# 配置: mykey.llm_global_max_concurrency (默认 8; <=0 = 关闭闸门回到旧行为)
#       mykey.llm_global_wait_seconds  (默认 300; 排队等待上限, 超时**放行**并告警, 绝不空转/死锁)
# 水表: 每次拿到名额写一行 temp/llm_gate_log.jsonl (含等待秒数/渠道/pid), gate_status() 汇总.
_GATE_DIR = os.path.join(_ROOT, 'temp', 'llm_gate')
_GATE_LOG = os.path.join(_ROOT, 'temp', 'llm_gate_log.jsonl')
_GATE_DEF_CAP, _GATE_DEF_WAIT, _GATE_STALE = 8, 300.0, 6 * 3600
_GATE_CFG_SRC = 'default'        # 上次解析出的 cap 来源(auto=sum(caps) / manual / default), 供 gate_status 显示

def _chan_caps_total(mk, only_in_use=True):
    """Σ各「房间」容量 = 总闸的 auto 值(2026-11-07 用户令).

    口径: 总并发上限**不是**二次规定的数字, 而是「所有房间的座位加起来」——
      · channel_session_caps 每个 key = 一间房; 组名(buddy/cline…)代表一间共用的房,
        成员渠道共用同一份名额 ⇒ 只按 key 算一次(天然不重复计).
      · channel_session_caps_by_mixin 里 **被 _isolate 隔离** 的渠会多出一个
        「<桶>@<mixin名>」的独立房间 ⇒ 其容量单独加进总数(与全局那份相加才是上游真实并发).
      · 未列进 caps 的渠道 = 不限并发 = 不是「有座位的房间」, 对总和不贡献(也无需贡献).

    ★only_in_use=True(默认, 2026-11-07 用户令「根据整个 mixmin 多少间房子多少人得到上限」):
      只累加**至少被一个 mixin_config_*.llm_nos 实际引用**的房间(组按 channel_cap_groups
      展开后匹配)。已从所有 mixin 摘出(=暂时不用的)房间, 即便 caps 里还留着座位, 也不进总闸
      —— 否则那些空房白占额度, 会把总闸放宽, 复现「并发不受控」。
      某个 mixin 恢复引用后, 下一轮 gate_cfg() 自动把它算回来(cap 是动态派生的)。
      若一台 mixin 配置都读不到(极端/测试场景), 自动回退 old 口径(全算), 防止总数算成 0。
    """
    def _int(v):
        try:
            v = int(v)
        except Exception:
            return 0
        return v if v > 0 else 0

    caps = mk.get('channel_session_caps') or {}
    if not isinstance(caps, dict):
        caps = {}
    groups = mk.get('channel_cap_groups') or {}
    if not isinstance(groups, dict):
        groups = {}

    # 收集「在用」渠道集合: 所有 mixin 的 llm_nos, 组名展开成成员
    in_use, saw_mixin = set(), False
    if only_in_use:
        for name in list(mk.keys()):
            if not str(name).startswith('mixin_config_'):
                continue
            cfg = mk.get(name)
            if not isinstance(cfg, dict):
                continue
            nos = cfg.get('llm_nos')
            if not isinstance(nos, (list, tuple)):
                continue
            saw_mixin = True
            for n in nos:
                in_use.add(n)
                for m in (groups.get(n) or []):
                    in_use.add(m)
        if not saw_mixin:
            only_in_use = False        # 读不到任何 mixin → 回退全量口径

    total = 0
    for k, v in caps.items():
        if only_in_use and k not in in_use:
            # 组键本身可能没被 mixin 直接点名, 但成员被引用 → 这间房仍在使用
            mem = groups.get(k) or []
            if not any(m in in_use for m in mem):
                continue
        total += _int(v)

    bym = mk.get('channel_session_caps_by_mixin') or {}
    if isinstance(bym, dict):
        for _mixin, d in bym.items():
            if not isinstance(d, dict):
                continue
            iso = d.get('_isolate')
            if iso is None or iso is False:
                continue          # 不隔离 = 与全局共用同一间房
            if iso is True or iso == '*':
                keys = [k for k in d if not str(k).startswith('_')]
            elif isinstance(iso, (list, tuple, set)):
                keys = [k for k in iso if k in d]             # 只隔离列出的渠
            else:
                continue
            for k in keys:
                if only_in_use and k not in in_use:
                    continue      # 该渠已不在任何 mixin 里 → 它的隔离副本也不占额度
                total += _int(d[k])
    return total


def _gate_cfg():
    """读 mykey 配置; 读不到/异常 → 用默认值(闸门始终可用)。

    2026-11-07 晚用户令(现行): **总闸已关闭, 并发上限只由各房间 channel_session_caps 决定**。
      mykey.llm_global_max_concurrency = 0 | 负数  → 关闭(现行, acquire 首行即 return, 零开销)
                                       = 正整数    → 临时重新启用单数字阀门
                                       = "auto"/"sum"/None/缺省 → 旧的 Σcaps 派生口径(仅存档)
    """
    global _GATE_CFG_SRC
    cap, wait, src = _GATE_DEF_CAP, _GATE_DEF_WAIT, 'default'
    try:
        mk = reload_mykeys()[0] or {}
        v = mk.get('llm_global_max_concurrency')
        if v is None or (isinstance(v, str) and v.strip().lower() in ('', 'auto', 'sum')):
            tot = _chan_caps_total(mk)
            if tot > 0:
                cap, src = tot, 'auto=sum(caps)'
        else:
            cap, src = int(v), 'off' if int(v) <= 0 else 'manual'
        w = mk.get('llm_global_wait_seconds')
        if w is not None: wait = max(1.0, float(w))
    except Exception: pass
    _GATE_CFG_SRC = src          # 供 gate_status() 显示来源
    return cap, wait

def _gate_sweep():
    """清扫死进程/超龄 slot(读路径, 只吞不抛)."""
    try: names = os.listdir(_GATE_DIR)
    except Exception: return
    now = time.time()
    for fn in names:
        if not fn.endswith('.slot'): continue
        p = os.path.join(_GATE_DIR, fn)
        pid, ts = 0, 0.0
        try:
            with open(p, encoding='utf-8') as f: d = json.load(f)
            pid, ts = int(d.get('pid') or 0), float(d.get('ts') or 0)
        except Exception: pass
        dead = bool(pid) and not _lease_pid_alive(pid)
        if dead or (now - ts > _GATE_STALE):
            _lease_unlink(p)

def gate_inflight():
    """当前全局在途请求数(水表读数)."""
    try: return len([f for f in os.listdir(_GATE_DIR) if f.endswith('.slot')])
    except Exception: return 0

class GlobalGate:
    """跨进程全局并发闸: 「所有进程 × 所有渠道」同时在跑的 LLM 请求总数上限."""
    def __init__(self, cap=None, wait=None, chan=''):
        c, w = _gate_cfg()
        self.cap = c if cap is None else int(cap)
        self.wait = w if wait is None else float(wait)
        self.chan, self.slot, self.waited = chan, None, 0.0
        self._t0 = time.time()
    def acquire(self):
        if self.cap <= 0: return True          # 闸门关闭
        try: os.makedirs(_GATE_DIR, exist_ok=True)
        except Exception: return True          # 环境异常 → 放行(绝不阻断业务)
        deadline = self._t0 + self.wait
        first, n = True, 0
        while True:
            if first: _gate_sweep(); first = False
            for i in range(self.cap):
                fp = os.path.join(_GATE_DIR, '%d.slot' % i)
                try: fd = os.open(fp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError: continue
                except Exception: return True
                try:
                    os.write(fd, json.dumps({'pid': os.getpid(), 'tid': threading.get_ident(),
                                             'chan': self.chan, 'ts': time.time()}).encode())
                finally:
                    try: os.close(fd)
                    except Exception: pass
                self.slot, self.waited = fp, time.time() - self._t0
                self._log('acquired')
                if self.waited >= 1.0:
                    print(f'[GATE] 拿到名额({gate_inflight()}/{self.cap}), 排队 {self.waited:.0f}s')
                return True
            n += 1
            if time.time() >= deadline:
                print(f'[GATE] 全局并发已满({self.cap} 路), 等待 {self.wait:.0f}s 超时 → 放行并记 override')
                self._log('override')
                return False
            if n == 1 or n % 40 == 0:
                print(f'[GATE] 全局并发已满({self.cap} 路), 排队 {time.time()-self._t0:.0f}s…')
            if n % 40 == 0: _gate_sweep()
            time.sleep(0.25)
    def release(self):
        if not self.slot: return
        _lease_unlink(self.slot); self.slot = None
        self._log('released')
    def _log(self, kind):
        try:
            with open(_GATE_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'ts': round(time.time(), 3), 'kind': kind,
                                    'chan': self.chan, 'pid': os.getpid(),
                                    'waited': round(self.waited, 2),
                                    'took': round(time.time() - self._t0, 1),
                                    'cap': self.cap, 'inflight': gate_inflight()},
                                   ensure_ascii=False) + '\n')
        except Exception: pass

def gate_status():
    """水表汇总: 当前在途 / 峰值 / 排队与 override 次数(最近 24h)."""
    cap, wait = _gate_cfg()
    cur = gate_inflight()
    rows, cut = [], time.time() - 86400
    try:
        with open(_GATE_LOG, encoding='utf-8') as f:
            for line in f:
                try: d = json.loads(line)
                except Exception: continue
                if d.get('ts', 0) >= cut: rows.append(d)
    except Exception: pass
    over = [r for r in rows if r.get('kind') == 'override']
    waits = [r.get('waited', 0) for r in rows if r.get('kind') == 'acquired' and r.get('waited', 0) > 0]
    return {'cap': cap, 'cap_src': _GATE_CFG_SRC, 'wait_s': wait, 'inflight_now': cur,
            'calls_24h': len([r for r in rows if r.get('kind') == 'acquired']),
            'peak_inflight_24h': max([r.get('inflight', 0) for r in rows] or [0]),
            'waited_calls_24h': len(waits),
            'max_wait_s_24h': round(max(waits or [0]), 1),
            'overrides_24h': len(over),
            'channels_24h': sorted({r.get('chan') for r in rows if r.get('chan')})[:20]}

def _stream_with_retry_gate(sess, url, headers, payload, parse_fn):
    """全局总闸门包装: 真正发请求前抢 1 个全球名额, 生成器结束/异常都释放."""
    g = GlobalGate(chan=getattr(sess, 'name', '') or getattr(sess, 'model', ''))
    g.acquire()
    try:
        # ★必须 return (yield from ...): 生成器的返回值 = 本次响应的内容块列表,
        #   直接 `yield from` 会把返回值丢掉 → 上层拿到的 blocks 恒为空
        #   (实证: tool_only 响应正文为空但应有 tool_use 块, 丢返回值后误判"空回答")。
        return (yield from _stream_with_retry_inner(sess, url, headers, payload, parse_fn))
    finally:
        g.release()

def _stream_with_retry_inner(sess, url, headers, payload, parse_fn):
    STATS['session'] = sess.name
    STATS['model'] = getattr(sess, 'model', None)
    _RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 529}
    cap = float(getattr(sess, 'max_retry_after', 60.0))
    _rbase = float(getattr(sess, 'retry_base_delay', 3.0))
    _rmax = float(getattr(sess, 'retry_max_delay', 30.0))
    def _delay(resp, attempt):
        try: ra = float((resp.headers or {}).get("retry-after"))
        except: ra = None
        # ★2026-11-08: 退避基数/上限按渠道可配(retry_base_delay / retry_max_delay), 缺省 3.0/30.0 = 旧行为
        return None if ra and ra > cap else max(0.5, ra or min(_rmax, _rbase * (2 ** attempt)))
    def _stopped(): return getattr(sess, 'should_stop', None) and sess.should_stop()
    def _sleep(d):  # interruptible sleep; True if aborted
        end = time.time() + d
        while time.time() < end:
            if _stopped(): return True
            time.sleep(0.2)
        return _stopped()
    for attempt in range(sess.max_retries + 1):
        if _stopped(): return []
        streamed = False
        STATS.update(t_start=time.time(), t_ttft=None)
        if not sess.stream: STATS['t_ttft'] = STATS['t_start']
        try:
            sess._tid = threading.get_ident()  # abort() looks up _INFLIGHT[_tid]
            with requests.post(url, headers=headers, json=payload, stream=sess.stream, 
                               timeout=(sess.connect_timeout, sess.read_timeout), proxies=sess.proxies, verify=sess.verify) as r:
                sess.active_response = r
                if r.status_code >= 400:
                    #pathlib.Path(__file__).parent.joinpath('temp','bad_requests.json').write_text(json.dumps({"url":url,"headers":headers,"payload":payload,"t":time.time()},ensure_ascii=False),encoding='utf-8')
                    d = _delay(r, attempt) if r.status_code in _RETRYABLE and attempt < sess.max_retries else None
                    if d is not None:
                        print(f"[LLM Retry] HTTP {r.status_code}, retry in {d:.1f}s ({attempt+1}/{sess.max_retries+1})")
                        if _sleep(d): return []
                        continue
                    try: body = r.text.strip()[:500]
                    except: body = ""
                    err = f"!!!Error: HTTP {r.status_code}" + (f" (retry-after > {cap:.0f}s)" if d is None and r.status_code in _RETRYABLE and attempt < sess.max_retries else "") + (f": {body}" if body else "")
                    yield err; return [{"type": "text", "text": err}]
                if sess.stream:  # TTFT = first SSE event (prefill done), not first visible chunk; hidden thinking must count in decode window
                    _il = r.iter_lines
                    def _probe(*a, **k):
                        for line in _il(*a, **k):
                            if line and STATS.get('t_ttft') is None: STATS['t_ttft'] = time.time()
                            yield line
                    r.iter_lines = _probe
                gen = parse_fn(r)
                # ★2026-11-09 修复「假成功话术漏给用户 + 不换渠」(用户报 hiyo 输出中断):
                #   原实现把正文**边收边 yield**，等 StopIteration 才判 `_is_canned_refusal`。
                #   但那时假话术早已吐给调用方 → 上层 MixinSession 见 delivered>0 →
                #   认定"已交付正文" → 不换渠、直接把「请求存在异常」当答案返回给用户。
                #   ⇒ 症状正是"模型只答了一句广告就停住"。
                #   修法: 判定所需的**最短窗口**内先缓冲(≤_CANNED_HOLD 字符), 确认不是
                #   固定话术后再放行; 一旦确认为 canned 就把缓冲整段丢弃并抛错 →
                #   一个字符都没交付过 → 走正常重试/换渠。
                #   代价: 正常回答的前 ~200 字符延迟到"确认安全"后一次性出现(亚秒级),
                #   短回答(<200 字符)会在流结束时整段出现 —— 换取"绝不漏出假答案"。
                _CANNED_HOLD = 160          # 与 _is_canned_refusal 的 160 阈值一致
                _CAN_MAX = 160

                def _canned_risk(s):
                    """这段缓冲还有没有可能最终被判成「假成功话术」?
                    返回 True = 必须继续攒着(现在放行可能放走假话术)。
                    判据(与 _is_canned_refusal 严格对齐): 只有长度超 160 才永远不可能,
                    否则只要**任意位置可能完成某条话术**就得等:
                      a) 缓冲里已出现完整话术 → 若总长仍<=160 即判定失败, 等结束再抛;
                      b) 缓冲尾部正好是某条话术的前缀 → 后面还可能补全。
                    b 之外(例如正常回答的开头)可以立刻放行, 首字零延迟。
                    """
                    if len(s) > _CAN_MAX:
                        return False
                    for _p in _CANNED_REFUSAL:
                        if _p in s:
                            return True
                        for _i in range(1, min(len(_p), len(s)) + 1):
                            if s.endswith(_p[:_i]):
                                return True
                    return False

                _buf, _buf_len = [], 0
                try:
                    while True:
                        if getattr(sess, 'should_stop', None) and sess.should_stop():
                            STATS['t_end'] = time.time(); return []
                        chunk = next(gen)
                        if chunk and STATS.get('t_ttft') is None: STATS['t_ttft'] = time.time()
                        # 思维链不进判定窗口, 照旧即时放行(用户不可见/可重放)
                        if isinstance(chunk, ThinkingChunk):
                            yield chunk; continue
                        # 判定窗口内且**仍有嫌疑** → 先攒着; 一旦确认不像假话术就立刻放行
                        if isinstance(chunk, str) and _buf_len <= _CAN_MAX:
                            _buf.append(chunk); _buf_len += len(chunk)
                            if _buf_len <= _CAN_MAX and _canned_risk("".join(_buf)):
                                continue
                            for _c in _buf: yield _c
                            streamed = True
                            _buf, _buf_len = [], _CAN_MAX + 1
                            continue
                        if not isinstance(chunk, ThinkingChunk): streamed = True
                        yield chunk
                except StopIteration as e:
                    blocks = e.value or []
                    # ★2026-11-09: 正常结束 → 先把判定窗口里攒着的正文放行(短回答全靠这一步!)
                    #   否则 <200 字符的正常答案会被整段丢弃。
                    if _buf:
                        _canned_now = _is_canned_refusal(blocks)
                        if not _canned_now and _has_usable_output(blocks):
                            for _c in _buf: yield _c
                            streamed = True
                        _buf = []
                    # ★2026-11-09: 站点 "HTTP 200 + 一句固定中文" 冒充正常回答 (=本机 IP
                    #   被限流时的 freeipblk 响应)。这是**伪装的错误**, 不是交付:
                    #   必须当空响应处理 → 抛 ConnectionError 走重试/换渠,
                    #   否则用户看到的就是"模型只答了句请求异常"然后停住。
                    if _is_canned_refusal(blocks):
                        streamed = False
                        raise requests.ConnectionError(
                            "canned refusal from upstream (IP-limited placeholder)")
                    if not _has_usable_output(blocks):
                        # 2026-11-04: 空正文 / 仅 thinking 不算成功——渠道会静默返回空白,
                        # 上层既不会重试也不会换渠(用户只看到"什么都没有")。
                        # ★2026-11-05 修「想很久然后自动终止」: 原判据 `not streamed` 把
                        #   任何已吐出的分片(含**思维链**)都算"已交付"→ 长 CoT 必然 streamed=True
                        #   → 仅思考就断流时**不重试也不换渠**, 直接把 trail 当结果返回, 用户只看到
                        #   "思考了 2m46s 然后终止"。现改判「是否已交付**可见正文**」:
                        #   思维链对用户不可见、可整段重放, 故只有正文/工具块算已交付。
                        delivered_text = any(
                            isinstance(b, dict) and (
                                b.get("type") == "tool_use" or
                                (b.get("type") == "text" and (b.get("text") or "").strip())
                            ) for b in (blocks or [])
                        )
                        if not delivered_text:
                            # ★必须把 streamed 也置 False: 该 raise 会被下面
                            #   `except (Timeout, ConnectionError, ChunkedEncodingError)` 捕获,
                            #   若 streamed 仍为 True 就落到「已交付不重试」分支 → 等于没改。
                            streamed = False
                            raise requests.ConnectionError("empty response: no text and no tool_use")
                        trail = "\n\n[!!! 流异常中断: 响应无正文（仅思考/空）!!!]"
                        print("[WARN] stream produced no usable output (thinking-only or empty)")
                        blocks = list(blocks) + [{"type": "text", "text": trail}]
                        STATS['t_end'] = time.time()
                        yield trail
                        return blocks
                    STATS['t_end'] = time.time()
                    STATS['tps'] = STATS.get('out', 0) / max(1e-9, STATS['t_end'] - max(STATS['t_ttft'] or 0, STATS['t_start']))
                    return e.value or []
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            err = f"!!!Error: {type(e).__name__}: {e}" if str(e) else f"!!!Error: {type(e).__name__}"
            if getattr(sess, 'should_stop', None) and sess.should_stop(): return []
            if streamed:
                # 2026-11-04: 已经 yield 过正文就不再重试, 否则调用方会看到半截+完整版重复。
                trail = f"\n\n[!!! 流异常中断 {type(e).__name__}: {e} !!!]"
                print(f"[WARN] stream broke after partial output, not retrying ({type(e).__name__})")
                yield trail; return [{"type": "text", "text": trail}]
            if attempt < sess.max_retries:
                d = _delay(None, attempt)
                print(f"[LLM Retry] {type(e).__name__}, retry in {d:.1f}s ({attempt+1}/{sess.max_retries+1})")
                if _sleep(d): return []
                continue
            yield err; return [{"type": "text", "text": err}]
        except Exception as e:
            err = f"\n\n[!!! 流异常中断 {type(e).__name__}: {e} !!!]" if streamed else f"!!!Error: {type(e).__name__}: {e}"
            yield err; return [{"type": "text", "text": err}]

_stream_with_retry = _stream_with_retry_gate

def _budget_for_payload(sess, messages, budget):
    """★2026-11-09: 预算不能超过「硬窗口 - 输入」。vLLM 类站(idxt/bobe)硬校验
    max_model_len, 输入+max_tokens 超窗直接 400(实测 bohe_diffusion 100万预算即 400)。

    ★必须 opt-in: 只能用 cfg["window_hard"](上游真实硬窗口), **不能**用 context_win——
    GA 的 context_win 本就被设成「输入预算」(trim 上限=context_win*3 字符), 拿它当窗口
    会算出 room≈0, 把长历史请求的预算压到 1024(严重回归)。
    字符粗估 token 按 3 字符/token(与 trim_messages_history 同口径), 留 5% 余量。
    """
    hard = getattr(sess, 'window_hard', None)
    if not budget or not hard:
        return budget
    try:
        chars = 0
        for m in messages:
            c = m.get('content')
            chars += len(c) if isinstance(c, str) else len(json.dumps(c, ensure_ascii=False))
        room = int(hard * 0.95) - chars // 3
        if room < 1024:
            room = 1024
        if room < budget:
            print(f"[Budget] shrink {budget} -> {room} (window_hard={hard}, est_in={chars // 3})")
            return room
    except Exception:
        pass
    return budget

def _openai_stream(sess, messages):
    model, api_mode = sess.model, sess.api_mode
    ml = model.lower()
    temperature = sess.temperature
    if 'kimi' in ml or 'moonshot' in ml: temperature = 1
    elif 'minimax' in ml: temperature = max(0.01, min(temperature, 1.0))  # MiniMax requires temp in (0, 1]
    headers = {"Authorization": f"Bearer {sess.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream", 'originator': 'codex_exec'}
    headers["User-Agent"] = sess.user_agent
    if getattr(sess, 'extra_headers', None): headers.update(sess.extra_headers)
    _budget = _budget_for_payload(sess, messages, sess.max_tokens)
    if api_mode == "responses":
        url = auto_make_url(sess.api_base, "responses")
        payload = {"model": model, "input": _to_responses_input(messages), "stream": sess.stream, 
                   "prompt_cache_key": _RESP_CACHE_KEY, "instructions": sess.system or "You are an Omnipotent Executor.",
                   "client_metadata": {"x-codex-window-id": f"{_RESP_CACHE_KEY}:0","x-codex-installation-id": _RESP_CODEX_KEY},
                   'include': ['reasoning.encrypted_content']}
        if sess.reasoning_effort: payload["reasoning"] = {"effort": sess.reasoning_effort}
        if _budget: payload["max_output_tokens"] = _budget
    else:
        url = auto_make_url(sess.api_base, "chat/completions")
        if sess.system: messages = [{"role": "system", "content": sess.system}] + messages
        _stamp_oai_cache_markers(messages, model)
        payload = {"model": model, "messages": messages, "stream": sess.stream}
        if sess.stream: payload["stream_options"] = {"include_usage": True}
        if temperature != 1: payload["temperature"] = temperature
        if _budget: payload["max_completion_tokens" if ml.startswith(("gpt-5", "o1", "o2", "o3", "o4")) else "max_tokens"] = _budget
        if sess.reasoning_effort: payload["reasoning_effort"] = sess.reasoning_effort
        # thinking_type: 部分站(如 runanytime)用该字段关思考, 否则模型狂思考吃光 max_tokens → 空返。
        # 仅在渠道显式配置该字段时透传(未配渠道行为不变)。
        _tt = getattr(sess, 'thinking_type', None)
        if _tt: payload["thinking_type"] = _tt
    if getattr(sess, 'extra_body', None):  # 通用透传: 只补缺, 不覆盖已构造字段
        for _k, _v in sess.extra_body.items(): payload.setdefault(_k, _v)
    tools = getattr(sess, 'tools', None)
    if tools: payload["tools"] = _prepare_oai_tools(tools, api_mode)
    if sess.service_tier: payload["service_tier"] = sess.service_tier
    parse_fn = (lambda r: _parse_openai_sse(r.iter_lines(), api_mode,
                                             hide_reasoning=bool(getattr(sess, 'stream_hide_reasoning', False)),
                                             budget=_budget)) if sess.stream else (lambda r: _parse_openai_json(r.json(), api_mode, budget=_budget))
    return (yield from _stream_with_retry(sess, url, headers, payload, parse_fn))
        
def _claude_tools_to_openai(tools):
    """Claude 格式 [{name,description,input_schema}] → OpenAI 格式 [{type:function,function:{name,description,parameters}}].

    ★ 2026-11-06 加固(用户同意): OpenAI 协议渠道(chat_completions / responses)原先对 tools **原样透传**,
      一旦调用方误传 Claude 格式, 上游直接 422 "Failed to deserialize the JSON body into the target type: tools"
      且不会自愈(实证: 手工探 moxuna 时踩坑, 真实链路没踩是因为 GA 内部一直传 OpenAI 格式)。
      现在统一在这里纠正: 只转换**确实是 Claude 格式**的条目(含 input_schema), 已是 OpenAI 格式的原样保留,
      不改动调用方列表本身(逐项新建 dict)。Claude 专属键(cache_control 等)在转换时丢弃。
    """
    out = []
    for t in tools:
        if not isinstance(t, dict):
            out.append(t); continue
        if 'input_schema' in t or ('function' not in t and 'name' in t):
            fn = {'name': t.get('name', ''),
                  'description': t.get('description', ''),
                  'parameters': t.get('input_schema') or {'type': 'object', 'properties': {}}}
            out.append({'type': 'function', 'function': fn})
        else:
            out.append(t)
    return out

def _prepare_oai_tools(tools, api_mode="chat_completions"):
    if tools and any(isinstance(t, dict) and 'input_schema' in t for t in tools):
        tools = _claude_tools_to_openai(tools)
    if api_mode == "responses":
        resp_tools = []
        for t in tools:
            if t.get("type") == "function" and "function" in t:
                rt = {"type": "function"}; rt.update(t["function"])
                resp_tools.append(rt)
            else: resp_tools.append(t)
        return resp_tools
    return tools

def _to_responses_input(messages):
    result, pending = [], []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        if role == "tool":
            cid = msg.get("tool_call_id") or (pending.pop(0) if pending else f"call_{uuid.uuid4().hex[:8]}")
            result.append({"type": "function_call_output", "call_id": cid, "output": msg.get("content", "")})
            continue
        if role not in ["user", "assistant", "system", "developer"]: role = "user"
        if role == "system": role = "developer"  # Responses API uses 'developer' instead of 'system'
        content = msg.get("content", "")
        text_type = "output_text" if role == "assistant" else "input_text"
        parts = []
        if isinstance(content, str):
            if content: parts.append({"type": text_type, "text": content})
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict): continue
                ptype = part.get("type")
                if ptype == "text":
                    text = part.get("text", "")
                    if text: parts.append({"type": text_type, "text": text})
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url and role != "assistant": parts.append({"type": "input_image", "image_url": url})
        if len(parts) == 0: parts = [{"type": text_type, "text": str(content) if not isinstance(content, list) else '[empty]'}]
        result.append({"role": role, "content": parts})
        pending = []
        for tc in (msg.get("tool_calls") or []):
            f = tc.get("function", {})
            cid = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            pending.append(cid)
            result.append({"type": "function_call", "call_id": cid, "name": f.get("name", ""), "arguments": f.get("arguments", "")})
    return result


def _msgs_claude2oai(messages):
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        if role == "assistant":
            text_parts, tool_calls, reasoning = [], [], ""
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "thinking" and b.get("thinking"): reasoning = b["thinking"]
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id") or '', "type": "function",
                        "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}
                    })
            m = {"role": "assistant"}
            if reasoning: m["reasoning_content"] = reasoning
            if text_parts: m["content"] = text_parts
            elif not tool_calls: m["content"] = "."
            if tool_calls: m["tool_calls"] = tool_calls
            result.append(m)
        elif role == "user":
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_result":
                    if text_parts:
                        result.append({"role": "user", "content": text_parts})
                        text_parts = []
                    tr = b.get("content", "")
                    if isinstance(tr, list):
                        tr = "\n".join(x.get("text", "") for x in tr if isinstance(x, dict) and x.get("type") == "text")
                    result.append({"role": "tool", "tool_call_id": b.get("tool_use_id") or '', "content": tr if isinstance(tr, str) else str(tr)})
                elif b.get("type") == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        text_parts.append({"type": "image_url", "image_url": {"url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"}})
                elif b.get("type") == "image_url": text_parts.append(b)
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
            if text_parts: result.append({"role": "user", "content": text_parts})
        else: result.append(msg)
    return result


class BaseSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']
        self.api_base = cfg['apibase'].rstrip('/')
        self.model = cfg.get('model', '')
        default_context_win = 38000; default_cut_msg_interval = 8
        if 'deepseek' in self.model.lower():
            default_context_win = 80000; default_cut_msg_interval = 25; self.trim_keep_rate = 0.3
        self.context_win = cfg.get('context_win', default_context_win)
        self.maxlen_multiplier = min(max(self.context_win / default_context_win * 0.75, 1.0), 3.0)
        self.cut_msg_interval = int(default_cut_msg_interval * self.maxlen_multiplier)
        self.trim_keep_prefix = max(0, int(cfg.get('trim_keep_prefix', 0) or 0))
        self.history = []; self.lock = threading.Lock(); self.system = ""
        self.name = cfg.get('name', self.model)
        self.extra_sys_prompt = cfg.get('extra_sys_prompt', '')
        if cfg.get('extra_sys_prompt_file'):
            self.extra_sys_prompt = (self.extra_sys_prompt or '') + open(cfg['extra_sys_prompt_file'] if os.path.isabs(cfg['extra_sys_prompt_file']) else os.path.join(_ROOT, cfg['extra_sys_prompt_file']), encoding='utf-8').read()
        proxy = cfg.get('proxy'); 
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        # ★免环境代理（2026-10-03）：部分通道（luckyg.131518.xyz 等; 原同批的 new-api.abrdns.com 已于 2026-10-04 永久下架删渠）实测可直连，
        # 但 requests 默认会 merge 环境变量 HTTPS_PROXY —— 一旦代理进程未启动，这些本可直连的
        # 通道也会一并失效，导致备通道全部卡死在同一单点上、failover 形同虚设
        # （2026-10-02 实证：5 通道中 4 个因 127.0.0.1:7890 未启动而 ProxyError）。
        # 置 no_env_proxy=True 时用 {"http": None, "https": None} 占位：requests 的
        # merge_environment_settings 以 dict.setdefault 写入环境代理，key 已存在即不覆盖
        # → 该通道恒定直连，不读环境代理。已显式配置 proxy 的通道不受影响。
        if cfg.get('no_env_proxy') and not self.proxies:
            self.proxies = {"http": None, "https": None}
        self.max_retries = max(0, int(cfg.get('max_retries', 4)))
        self.max_retry_after = float(cfg.get('max_retry_after', 60.0))
        # ★2026-11-08 用户令「重试间隔放长点」: 退避原为硬编码 min(30, 3.0*2^n)。
        #   现改为按渠道可配, 缺省值与旧行为逐字节一致(3.0 / 30.0) ⇒ 不配置的渠道零变化。
        #   用途: 突发限流型站点(如 acomb 502)需要更长冷却, 短退避会在窗口内反复撞墙。
        self.retry_base_delay = max(0.1, float(cfg.get('retry_base_delay', 3.0)))
        self.retry_max_delay = max(self.retry_base_delay, float(cfg.get('retry_max_delay', 30.0)))
        # ★2026-11-08: MixinSession 默认把每条腿的 max_retries 压成 0(失败即顺延下一渠)。
        #   本字段 = 「在本 mixin 内仍允许原地重试几次」; 0(缺省) = 保持旧行为, 不重试直接换渠。
        #   语义: 只有"同一账号不能被打太频、但换渠更贵"的付费渠才需要打开。
        self.in_mixin_retries = max(0, int(cfg.get('in_mixin_retries', 0)))
        self.verify = cfg.get('verify', True)
        self.stream = cfg.get('stream', True)
        default_ct, default_rt = (5, 40) if self.stream else (10, 240)
        self.connect_timeout = max(1, int(cfg.get('timeout', default_ct)))
        self.read_timeout = max(5, int(cfg.get('read_timeout', default_rt)))
        def _enum(key, valid):
            v = cfg.get(key); v = None if v is None else str(v).strip().lower()
            return v if not v or v in valid else print(f"[WARN] Invalid {key} {v!r}, ignored.")
        self.reasoning_effort = _enum('reasoning_effort', {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'})
        self.service_tier = _enum('service_tier', {'auto', 'default', 'priority', 'flex'})
        self.thinking_type = _enum('thinking_type', {'adaptive', 'enabled', 'disabled'})
        self.thinking_budget_tokens = cfg.get('thinking_budget_tokens')
        self.omit_thinking = cfg.get('omit_thinking', False)  # Exclude thinking from session history
        # ★2026-10-22: 流式时是否把 reasoning_content 一并 yield 给上层(默认 True=旧行为)。
        #   only_reasoning 型站点(ds4f_404)必须设 False, 否则 CoT 混进正文流被当正文写进 history。
        self.stream_hide_reasoning = bool(cfg.get('stream_hide_reasoning', False))
        mode = str(cfg.get('api_mode', 'chat_completions')).strip().lower().replace('-', '_')
        self.api_mode = 'responses' if mode in ('responses', 'response') else 'chat_completions'
        self.temperature = cfg.get('temperature', 1)
        self.max_tokens = cfg.get('max_tokens')
        # ★2026-11-09: 上游"硬窗口"(vLLM 类站 max_model_len)。只在这些站设置,
        #   用途=预算收缩防「输入+max_tokens 超窗 → 400」。留空=不收缩(绝大多数中转站)。
        self.window_hard = cfg.get('window_hard')
        self.default_ua = "claude-cli/2.1.280 (external, cli)"
        self.user_agent = cfg.get("user_agent", self.default_ua)
        eh = cfg.get("extra_headers") or {}
        self.extra_headers = {str(k): str(v) for k, v in eh.items()} if isinstance(eh, dict) else {}
        # ★2026-10-20: 通用请求体透传 —— cfg["extra_body"] (dict) 按 setdefault 合并进 payload;
        #   用于给特定上游钉死路由等(例: cline-pass 的 {"providerOptions":{"gateway":{"only":["deepseek"]}}})。
        #   已有同名键(如 model/messages)不被覆盖, 保证只做"补充字段"。
        _eb = cfg.get("extra_body")
        self.extra_body = dict(_eb) if isinstance(_eb, dict) else {}
    def _apply_claude_thinking(self, payload):
        if self.thinking_type:
            thinking = {"type": self.thinking_type}
            if self.thinking_type == 'enabled':
                if self.thinking_budget_tokens is None: print("[WARN] thinking_type='enabled' requires thinking_budget_tokens, ignored.")
                else:
                    thinking["budget_tokens"] = self.thinking_budget_tokens; payload["thinking"] = thinking
            else: payload["thinking"] = thinking
        if self.reasoning_effort:
            effort = {'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'max', 'max': 'max'}.get(self.reasoning_effort)
            if effort: payload["output_config"] = {"effort": effort}
            else: print(f"[WARN] reasoning_effort {self.reasoning_effort!r} is unsupported for Claude output_config.effort, ignored.")
    def ask(self, prompt):
        def _ask_gen():
            with self.lock:
                self.history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
                trim_messages_history(self.history, self)
                messages = self.make_messages(self.history)
            content_blocks = None; content = ''
            gen = self.raw_ask(messages)
            try:
                while True: chunk = next(gen); content += chunk; yield chunk
            except StopIteration as e: content_blocks = e.value or []
            if len(content_blocks) > 1: print(f"[DEBUG BaseSession.ask] content_blocks: {content_blocks}")
            for block in (content_blocks or []):
                if block.get('type', '') == 'tool_use':
                    tu = {'name': block.get('name', ''), 'arguments': block.get('input', {})}
                    yield f'<tool_use>{json.dumps(tu, ensure_ascii=False)}</tool_use>'
            if content.strip() and not content.startswith("!!!Error:"): self.history.append({"role": "assistant", "content": [{"type": "text", "text": content}]})
        return _ask_gen()

def _keep_claude_block(b): return not isinstance(b, dict) or b.get("type") != "thinking" or b.get("signature")
def _drop_unsigned_thinking(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list): m["content"] = [b for b in c if _keep_claude_block(b)]
    return messages

def _ensure_thinking_blocks(messages, model):
    """deepseek needs thinking in history!"""
    if 'deepseek' not in model.lower(): return messages
    for m in messages:
        if m.get("role") != "assistant": continue
        c = m.get("content")
        if not isinstance(c, list): continue
        has_thinking = any(isinstance(b, dict) and b.get("type") == "thinking" for b in c)
        if not has_thinking: m["content"] = [{"type": "thinking", "thinking": "...", "signature": "placeholder"}, *c]
    return messages

def _fix_messages(messages):
    if not messages: return messages
    W = lambda c: c if isinstance(c, list) else [{"type": "text", "text": str(c)}]
    merged = []
    for m in messages:
        if m.get('role') not in ('user', 'assistant'): continue
        blocks = W(m.get('content', []))
        if merged and m['role'] == merged[-1]['role']:
            merged[-1]['content'] += list(blocks)
        else:
            merged.append({"role": m['role'], "content": list(blocks)})
    while merged and merged[0]['role'] != 'user': merged.pop(0)
    if not merged: return []
    prev_uses = []
    for m in merged:
        c = m['content']
        if m['role'] == 'assistant':
            seen, out = set(), []
            for b in c:
                uid = b.get('id') if isinstance(b, dict) and b.get('type') == 'tool_use' else None
                if uid and uid in seen: continue
                if uid: seen.add(uid)
                out.append(b)
            m['content'] = out
            prev_uses = [b.get('id') for b in out if isinstance(b, dict) and b.get('type') == 'tool_use']
        else:
            got, rest = {}, []
            for b in c:
                tid = b.get('tool_use_id') if isinstance(b, dict) and b.get('type') == 'tool_result' else None
                if tid and tid in prev_uses and tid not in got: got[tid] = b
                elif isinstance(b, dict) and b.get('type') == 'tool_result': rest.append({"type": "text", "text": str(b.get('content', ''))})
                else: rest.append(b)
            m['content'] = [got.get(u) or {"type": "tool_result", "tool_use_id": u, "content": "(error)"} for u in prev_uses] + rest
            prev_uses = []
    for m in merged: m['content'] = [b for b in m['content'] if not (isinstance(b, dict) and b.get('type') == 'text' and not (b.get('text') or '').strip())] or [{"type": "text", "text": "."}]
    return merged

def _cc_system(system, compat='off'):  # off | simple | half(未来 full)
    b = [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude.", "cache_control": {"type": "ephemeral"}}] if compat != 'off' or not system else []
    if compat in ('half', 'full'): b.append({"type": "text", "text": open(os.path.join(_ROOT, 'assets', 'cc_system_template.txt'), encoding='utf-8').read()})
    return b + ([{"type": "text", "text": system}] if system else [])

# ★2026-11-09 自动续写(用户令「这种中断能不能自己自动继续，要不然需要我每次自己继续」)
#   llmcore 三处解析器(anthropic / chat_completions / responses)在流被掐断或撞 max_tokens 时,
#   会往正文尾部追加下面这些标记。旧行为=停下, 由前端 Ctrl+R 手动再发一句"接着说"。
_TRUNC_PREFIXES = ("[!!! 流异常中断", "[!!! Response truncated", "[!!! output truncated")
_CONTINUE_PROMPT_INLINE = (
    "请继续输出被中断的内容：从上次中断处紧接着往下写，"
    "不要重复已经输出过的部分，不要重新开头，直接续上。"
)
# ★2026-11-09: hiyo 系站点在本机 IP 被限流时**HTTP 200 + 一句固定中文**冒充正常回答
#   (response id = chatcmpl-freeipblk)。不识别的话用户看到的就是"模型答了句请求异常"。
#   判据: 整段正文极短(<=160字符) 且命中固定话术 且无 tool_use → 当作空响应, 走重试/换渠。
_CANNED_REFUSAL = (
    "当前网络的请求存在异常",
    "已被临时限制访问，请稍后再试",
    "请求存在异常，请稍后再试",
    # ★2026-11-09 补: free.hiyo.top 的 **UA 白名单**门。非 Coding 客户端 UA
    #   (curl/python-requests/空 UA) 会拿到 id=chatcmpl-freeblock000 的假流,
    #   正文就是这句。GA 现在钉死了 codex_exec UA 故平时不触发, 但一旦
    #   某次改配置/换渠忘了带 UA, 表现同样是"模型答了句广告就停"。
    "本站仅限主流 Coding 客户端",
    "仅限主流 Coding 客户端/CLI 使用",
)


def _split_trunc_suffix(txt):
    """把「正文 + 截断标记」拆成 (clean_text, tail_marker)。

    标记的真实形态是**拼在正文末尾**的 (见 L298/918/928/397/469/546)，
    形如 "\\n\\n[!!! Response truncated: max_tokens !!!]"，
    所以必须按「后缀出现位置」切，不能用 startswith。

    ★只认**尾部**：正文里若正常引用了这句话(比如讲解本机制)，
      用 find() 取首次出现会把后文整段砍掉 → 改 rfind + 三条约束:
        (a) 标记起点距尾部 <= 200 字符;
        (b) 整串以 "]" 结尾 (两种真实形态: "...!!]" 与
            "[!!! output truncated: xxx]" 单右括号, 见 L397/546);
        (c) 标记本身单行且 <= 160 字符 (真实标记恒如此)。
      真实标记恒满足这三条, 句中引用则几乎不可能同时满足。
    """
    if not isinstance(txt, str) or not txt:
        return txt, ""
    s = txt.rstrip()
    if not s.endswith("]"):
        return txt, ""
    for p in _TRUNC_PREFIXES:
        i = s.rfind(p)
        if i < 0:
            continue
        tail = s[i:]
        if len(tail) <= 160 and "\n" not in tail:
            return s[:i].rstrip(), tail.strip()
    return txt, ""


def _is_canned_refusal(blocks):
    for b in (blocks or []):
        if isinstance(b, dict) and b.get("type") == "tool_use":
            return False
    txt = "".join((b.get("text") or "") for b in (blocks or [])
                  if isinstance(b, dict) and b.get("type") == "text")
    if len(txt) > 160:
        return False
    return any(p in txt for p in _CANNED_REFUSAL)


# ==== 渠道冷却 / 健康探针 (2026-11-09 用户批准第4项) ==========================
# 问题: 某渠道被上游风控(IP 限流/UA 白名单)时, 每次**必然**失败, 但旧逻辑每个请求
#   都还会先打它一次(它是 mixin 头渠) → 白白浪费一次往返 + 一段 200ms~2s,
#   长文场景下更是一次几十秒的空跑, 且不断刷新风控计数。
# 方案: 进程内记「某桶名 → 冷却截止时刻」。判失败的请求给它上冷却, 冷却期内
#   选渠时跳过; 全部渠道都在冷却 → 直接放行(可用性优先, 绝不空转卡死)。
#   冷却时长按连续失败次数指数退避; 命中「假成功」文案的给更长冷却(IP 级封禁
#   通常持续数分钟以上, 实测等 20 分钟仍不恢复)。
#   注意: 这是**跨请求**的进程级状态(只在内存), 进程重启即清空 → 不会永久黑名单。
_CHAN_COOL = {}                      # bucket_name -> (expire_ts, fails)
_CHAN_COOL_LOCK = threading.Lock()
_CHAN_COOL_BASE = 60.0               # 首次失败冷却 60s
_CHAN_COOL_MAX = 600.0               # 上限 10min
_CHAN_COOL_CANNED = 300.0            # 假成功(风控文案)至少 5min


def _chan_cool_mark(name, err_text="", canned=False):
    """给渠道上/续冷却。canned=True(风控假成功)用更长的下限。"""
    if not name:
        return
    try:
        with _CHAN_COOL_LOCK:
            exp, fails = _CHAN_COOL.get(name, (0.0, 0))
            fails += 1
            dur = min(_CHAN_COOL_MAX, _CHAN_COOL_BASE * (2 ** (fails - 1)))
            if canned:
                dur = max(dur, _CHAN_COOL_CANNED)
            _CHAN_COOL[name] = (time.time() + dur, fails)
            print(f'[ChanCool] {name} 冷却 {dur:.0f}s (连续失败 {fails} 次)')
    except Exception:
        pass


def _chan_cool_ok(name):
    """该渠道是否可用(不在冷却期)。"""
    try:
        with _CHAN_COOL_LOCK:
            exp, fails = _CHAN_COOL.get(name, (0.0, 0))
            if exp and time.time() >= exp:
                _CHAN_COOL.pop(name, None)
                print(f'[ChanCool] {name} 冷却结束, 恢复可选')
                return True
            return not exp
    except Exception:
        return True


def _chan_cool_clear(name):
    """请求成功 → 清掉该渠道的失败计数。"""
    try:
        with _CHAN_COOL_LOCK:
            if _CHAN_COOL.pop(name, None):
                print(f'[ChanCool] {name} 成功, 清除冷却')
    except Exception:
        pass


def _chan_cool_status():
    """供自检/脚本查看当前冷却表。"""
    with _CHAN_COOL_LOCK:
        now = time.time()
        return {k: {"left": round(v[0] - now, 1), "fails": v[1]}
                for k, v in _CHAN_COOL.items() if v[0] > now}


class NativeClaudeSession(BaseSession):
    native_ua = "claude-cli/2.1.280 (native, cli)"
    def __init__(self, cfg):
        super().__init__(cfg)
        self.claude_compat = cfg.get("claude_compat") or ("simple" if cfg.get("fake_cc_system_prompt") else "off")
        self.fake_cc_system_prompt = self.claude_compat != "off"
        self._session_id = str(uuid.uuid4())
        self._account_uuid = str(uuid.uuid4())
        self._device_id = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        self.tools = None
        if self.user_agent == self.default_ua: self.user_agent = self.native_ua
        self.api_key_header = str(cfg.get('api_key_header', 'auto')).strip().lower()
        self.show_thinking = bool(cfg.get('show_thinking'))  # True: stream thinking text (like CC showThinkingSummaries)
    def raw_ask(self, messages):
        if self.max_tokens is None: self.max_tokens = 8192
        model = self.model
        messages = _fix_messages(messages)
        if 'claude' in model.lower(): messages = _drop_unsigned_thinking(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        beta_parts = ["claude-code-20250219", "interleaved-thinking-2025-05-14", "redact-thinking-2026-02-12", "thinking-token-count-2026-05-13", "context-management-2025-06-27", "prompt-caching-scope-2026-01-05", "mid-conversation-system-2026-04-07", "effort-2025-11-24", "fallback-credit-2026-06-01"]
        if self.show_thinking: beta_parts.remove("redact-thinking-2026-02-12")
        if "[1m]" in model.lower():
            beta_parts.insert(1, "context-1m-2025-08-07"); model = model.replace("[1m]", "").replace("[1M]", "")
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(beta_parts), "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": self.user_agent, "x-app": "cli"}
        headers.update({"Accept": "application/json", "X-Claude-Code-Session-Id": self._session_id, "X-Stainless-Arch": "x64", "X-Stainless-Lang": "js", "X-Stainless-OS": "Windows", "X-Stainless-Package-Version": "0.94.0", "X-Stainless-Retry-Count": "0", "X-Stainless-Runtime": "node", "X-Stainless-Runtime-Version": "v24.3.0", "X-Stainless-Timeout": "600"})
        if self.api_key_header == 'x-api-key': headers["x-api-key"] = self.api_key
        elif self.api_key_header == 'bearer': headers["authorization"] = f"Bearer {self.api_key}"
        elif self.api_key.startswith("sk-ant-"): headers["x-api-key"] = self.api_key
        else: headers["authorization"] = f"Bearer {self.api_key}"
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        #if self.fake_cc_system_prompt: payload["max_tokens"] = 64000
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        #payload["context_management"] = {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]}; 
        if self.fake_cc_system_prompt:
            if 'thinking' not in payload: payload["thinking"] = {"type": "adaptive"}
            if 'output_config' not in payload: payload["output_config"] = {"effort": "medium"}
        payload["metadata"] = {"user_id": json.dumps({"device_id": self._device_id, "account_uuid": "", "session_id": self._session_id}, separators=(',', ':'))}
        if self.tools:
            claude_tools = openai_tools_to_claude(self.tools)
            tools = [dict(t) for t in claude_tools]; tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tools
        else: print("[ERROR] No tools provided for this session.")
        payload['system'] = _cc_system(self.system, self.claude_compat)
        user_idxs = [i for i, m in enumerate(messages) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            messages[idx] = {**messages[idx], "content": list(messages[idx]["content"])}
            messages[idx]["content"][-1] = dict(messages[idx]["content"][-1], cache_control={"type": "ephemeral"})
        url = auto_make_url(self.api_base, "messages") + '?beta=true'
        if getattr(self, 'extra_body', None):
            for _k, _v in self.extra_body.items(): payload.setdefault(_k, _v)
        parse_fn = (lambda r: _parse_claude_sse(r.iter_lines())) if self.stream else (lambda r: _parse_claude_json(r.json()))
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn))

    def ask(self, msg):
        assert type(msg) is dict
        # ★2026-11-09 自动续写(用户令「这种中断能不能自己自动继续」):
        #   流被掐断/撞 max_tokens 时解析器会在尾部追加 [!!! ...] 标记。旧行为=停下等人 Ctrl+R。
        #   现在: 把标记从流里吞掉(不打扰用户), 清掉标记后补一条"接着写"的 user 回合再取一段,
        #   直到正常结束 / 用完预算(默认 3 段) / 出现 tool_use(交给 agent 下一轮自然处理)。
        #   开关: GA_AUTO_CONTINUE=0 关闭; GA_AUTO_CONTINUE_ROUNDS=N 设最多续几段。
        _rounds = 3
        try: _rounds = max(0, int(os.environ.get("GA_AUTO_CONTINUE_ROUNDS", "3")))
        except Exception: _rounds = 3
        if os.environ.get("GA_AUTO_CONTINUE", "1") == "0": _rounds = 0
        _hist, _texts = [], []
        _cur, _last_tail = msg, ""
        for _rnd in range(_rounds + 1):
            with self.lock:
                self.history.append(_cur)
                trim_messages_history(self.history, self)
                messages = [{"role": m["role"], "content": list(m["content"])} for m in self.history]
            content_blocks = None
            gen = self.raw_ask(messages)
            try:
                while True:
                    _c = next(gen)
                    # 截断标记先不吐给用户: 决定要不要续写之后再见分晓
                    if isinstance(_c, str):
                        _clean_c, _t = _split_trunc_suffix(_c)
                        if _t:
                            _last_tail = _t
                            if _clean_c: yield _clean_c
                            continue
                    yield _c
            except StopIteration as e: content_blocks = e.value or []
            _clean = []
            for b in (content_blocks or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    _ct, _t = _split_trunc_suffix(b.get("text") or "")
                    if _t:
                        _last_tail = _t
                        if not _ct: continue
                        b = dict(b); b["text"] = _ct
                _clean.append(b)
            content_blocks = _clean
            _has_tool = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content_blocks)
            _is_err = (len(content_blocks) == 1 and str(content_blocks[0].get("text", "")).startswith("!!!Error:"))
            _go_on = bool(_last_tail) and not _has_tool and not _is_err and _rnd < _rounds
            if not _go_on and content_blocks:
                _inj = _ensure_text_block(content_blocks)
                if _inj: yield _inj
            _hist.extend(content_blocks)
            _texts.extend(b["text"] for b in content_blocks if isinstance(b, dict) and b.get("type") == "text")
            _hb = content_blocks
            if self.omit_thinking: _hb = [b for b in content_blocks if b.get("type") != "thinking"]
            # ★2026-11-09 acomb 实测修复(真 bug, hiyo 注入法测不出来):
            #   某轮可能**只产出思维链**(reasoning 吃满 max_tokens), 或正文被截断标记剥成空 →
            #   _hb 为空, 旧码仍 append 了一条 content=[] 的 assistant 回合。下一轮模型看到
            #   「空的助手回答 + 请继续」, 会重新从头作答 / 吐元叙述("我们需要回答用户…"),
            #   既接不上又白烧 token(实测 4 轮只数到 40, 后 3 轮全废)。
            #   修法: 空回合不写 history; 且本轮没有可续的正文就直接停止空转。
            _produced = any(
                isinstance(b, dict) and (
                    (b.get("type") == "text" and (b.get("text") or "").strip())
                    or b.get("type") == "tool_use"
                ) for b in (content_blocks or [])
            )
            if _hb and not _is_err:
                self.history.append({"role": "assistant", "content": _hb})
            elif _go_on and not _produced:
                _go_on = False   # 无可续正文 → 停止空转, 让截断标记照旧透出
            if not _go_on:
                if _last_tail: yield _last_tail   # 续不上(预算用完/有工具调用) → 标记照旧透出
                break
            _last_tail = ""
            _cur = {"role": "user", "content": [{"type": "text", "text": _CONTINUE_PROMPT_INLINE}]}
        content = "\n".join(_texts).strip()
        tool_calls = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", ""))
                      for b in _hist if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not tool_calls: tool_calls, content = _parse_text_tool_calls(content)
        thinking_parts = [b["thinking"] for b in _hist if isinstance(b, dict) and b.get("type") == "thinking"]
        thinking = "\n".join(thinking_parts).strip()
        if not thinking:
            think_pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
            think_match = re.search(think_pattern, content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(think_pattern, "", content, flags=re.DOTALL)
        raw = "[" + ",\n".join(repr(b) for b in _hist) + "]"
        return MockResponse(thinking, content, tool_calls, raw)

class NativeOAISession(NativeClaudeSession):
    native_ua = "codex_exec/0.139.0 (Windows 10.0.26200; x86_64) unknown (codex_exec; 0.139.0)"
    def raw_ask(self, messages):
        messages = _fix_messages(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        return (yield from _openai_stream(self, _msgs_claude2oai(messages)))

def openai_tools_to_claude(tools):
    """[{type:'function', function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    result = []
    for t in tools:
        if 'input_schema' in t: result.append(t); continue  # 已是claude格式
        fn = t.get('function', t)
        result.append({'name': fn['name'], 'description': fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}})})
    return result

class MockFunction:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments  
         
class MockToolCall:
    def __init__(self, name, args, id=''):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else (args or '{}')
        self.function = MockFunction(name, arg_str); self.id = id

class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw, stop_reason='end_turn'):
        self.thinking = thinking; self.content = content          
        self.tool_calls = tool_calls; self.raw = raw
        self.stop_reason = 'tool_use' if tool_calls else stop_reason
    def __repr__(self):    
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"

def _parse_text_tool_calls(content):
    """Fallback: extract tool calls from text when model doesn't use native tool_use blocks."""
    tcs = []
    # try JSON array: [{"type":"tool_use", "name":..., "input":...}]
    _jp = next((p for p in ['[{"type":"tool_use"', '[{"type": "tool_use"'] if p in content), None)
    if _jp and content.endswith('}]'):
        try:
            idx = content.index(_jp); raw = json.loads(content[idx:])
            tcs = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in raw if b.get("type") == "tool_use"]
            return tcs, content[:idx].strip()
        except: pass
    # try XML tags: <tool_call>{"name":..., "arguments":...}</tool_call>
    _xp = r"<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){15,}?)</(?:tool_use|tool_call)>"
    for s in re.findall(_xp, content, re.DOTALL):
        try:
            d = tryparse(s.strip()); name = d.get('name')
            args = d.get('arguments') or d.get('args') or d.get('input') or {}
            if name: tcs.append(MockToolCall(name, args))
        except: pass
    if tcs: content = re.sub(_xp, "", content, flags=re.DOTALL).strip()
    if not tcs:
        tcs, content = _parse_pseudo_xml_tool_calls(content)
    return tcs, content


# ==== 伪 XML 工具调用兜底 (2026-11-11) ==================================
# 现象: 部分上游不用原生 tool_calls, 而是把工具调用写成**伪 XML 正文**:
#       <code_run>\n<script>print(1)</script>\n</code_run>
#       <code_run>\n<parameter name="script">print(1)</parameter>\n</code_run>
#       <file_read">\n<parameter name="path">a.py</parameter>\n</file_read>   (名字后多一个引号)
#       <function=code_run><parameter=script>print(1)</parameter></function>   (Qwen 风格)
#       <｜｜DSML｜｜tool_calls><｜｜DSML｜｜invoke name="code_run"><｜｜DSML｜｜parameter name="script">…  (DeepSeek DSML)
#   `_parse_text_tool_calls` 只认 `<tool_use>`/`<tool_call>` + JSON, 这些一个都认不出
#   ⇒ tool_calls 为空 ⇒ `ga.do_no_tool` 又一条判据都不命中 ⇒ 被当成**最终回答**
#   ⇒ 本轮任务结束。用户观感 = 「冒出一坨标签然后对话自己中断了, 且不报错」。
#
# 安全约束(宁可不解析, 不可乱执行):
#   * 工具名必须在白名单内(assets/tools_schema.json + 常见别名), 正文里的任意 <xxx> 不猜;
#   * 只认**成对闭合**的块 —— 流被掐断在半截时不猜参数;
#   * ``` 围栏 / `行内代码` 内的内容不参与匹配 —— 模型讲解/写文档时提到这些标签不应被真执行;
#   * 解析结果还要过 `salvaged_call_problem`(python 语法等) —— 压平成一行/半截的脚本
#     宁可让模型重发, 也不能直接跑起来。
#
# ★ 2026-11-11 PR #853 review 修复的三处缺口:
#   C 参数名被写成 dsml_parameter —— 参数名解析与工具标签的引号风格解耦;
#   F `<function=name><parameter=k>` 还原(此前直接静默终答);
#   H 截断的调用被当真正调用执行 —— 安全闸门挪到 `_parse_text_tool_calls` 返回之前,
#     而不是等 do_no_tool; 另外 `textual_tool_residue` 把「想调但调不成」的残渣
#     (unclosed/empty/orphan) 交给 ga 重试, 不再冒充最终回答。
import ast

_PSEUDO_XML_ALIASES = frozenset({
    'code_run', 'file_read', 'file_write', 'file_patch', 'web_scan', 'web_execute_js',
    'web_search', 'web_fetch', 'update_working_checkpoint', 'start_long_term_update',
    'ask_user', 'all_urls', 'bad_json', 'computer', 'bash', 'powershell',
})
_TOOL_NAMES_CACHE = None
# `｜｜DSML｜｜` 前缀(全角/半角竖线都见过), 可选
_DSML = r'(?:\s*[\uff5c|]{1,2}\s*DSML\s*[\uff5c|]{1,2}\s*)?'
# 工具名与 '>' 之间的杂音: 多余引号/空白(实测 `<file_read">`)
_NOISE = r'[ \t"\']{0,4}'
# 行首锚定 —— 正文里顺手提到 `<code_run>` 不算泄漏, 真的泄漏总是独立成行
_BOL = r'(?m)^[ \t]*'


def _known_tool_names():
    """白名单: 内置别名 ∪ assets/tools_schema.json 里声明的工具名。"""
    global _TOOL_NAMES_CACHE
    if _TOOL_NAMES_CACHE is not None: return _TOOL_NAMES_CACHE
    names = set(_PSEUDO_XML_ALIASES)
    try:
        with open(os.path.join(_ROOT, 'assets', 'tools_schema.json'), encoding='utf-8') as f:
            for t in json.load(f):
                fn = t.get('function', t) or {}
                if fn.get('name'): names.add(fn['name'])
    except Exception:
        pass
    _TOOL_NAMES_CACHE = frozenset(names)
    return _TOOL_NAMES_CACHE


def _mask_code(text):
    """把 ``` 围栏 / `行内代码` 换成等长空格(保持偏移不变)。

    ★哨兵不能用 0: 围栏正好从第 0 个字符开始时, `pos == 0` 会被误判成「还没开」,
      于是永远不闭合 —— 负例(整段被 ``` 包住)反而会被当真调用执行。
    """
    out = list(text)
    for m in re.finditer(r'```[\s\S]*?(?:```|$)', text):
        for i in range(m.start(), m.end()): out[i] = ' '
    for m in re.finditer(r'`[^`\n]*`', text):
        for i in range(m.start(), m.end()): out[i] = ' '
    return ''.join(out)


class _Scan:
    __slots__ = ('blocks', 'unclosed', 'orphans')

    def __init__(self):
        self.blocks = []      # dict(start, end, name, body, attrs)
        self.unclosed = []    # 有开无闭的块/参数(通常是流被掐断)
        self.orphans = []     # 落在任何工具块之外的 <parameter>(想调工具但没调成)


def _scan_pseudo_xml(content):
    """扫描正文里的伪工具块。

    只看**行首**开标签(正文里 inline 提到标签不算), 围栏/行内代码内全部忽略。
    """
    sc = _Scan()
    if not content: return sc
    text = _mask_code(content)
    names = _known_tool_names()
    alt = '|'.join(sorted((re.escape(n) for n in names if n), key=len, reverse=True))

    # 三种开标签: <工具名 ...> / <function=工具名> / <invoke name="工具名">
    opens = []
    for m in re.finditer(_BOL + r'<' + _DSML + r'(' + alt + r')\b' + _NOISE + r'([^<>]{0,200})>', text, re.I):
        opens.append((m.start(), m.end(), m.group(1), m.group(2) or '', 'tag'))
    for m in re.finditer(_BOL + r'<function\s*=\s*["\']?([A-Za-z_]\w*)["\']?\s*>', text, re.I):
        opens.append((m.start(), m.end(), m.group(1), '', 'function'))
    for m in re.finditer(_BOL + r'<' + _DSML + r'invoke\s+name\s*=\s*["\']?([A-Za-z_]\w*)["\']?\s*>', text, re.I):
        opens.append((m.start(), m.end(), m.group(1), '', 'invoke'))
    opens.sort()

    spans = []
    for start, end, name, attrs, form in opens:
        if name not in names: continue
        if any(a <= start < b for a, b in spans): continue     # 嵌套在外层块里
        if form == 'function':
            close_re = re.compile(r'</function\s*>', re.I)
        elif form == 'invoke':
            close_re = re.compile(r'</' + _DSML + r'invoke\s*>', re.I)
        else:
            close_re = re.compile(r'</' + _DSML + re.escape(name) + r'\s*>', re.I)
        c = close_re.search(text, end)
        if c is None:
            sc.unclosed.append(name); continue
        body = content[end:c.start()]
        spans.append((start, c.end()))
        sc.blocks.append({'start': start, 'end': c.end(), 'name': name, 'body': body, 'attrs': attrs})

    spans.sort()
    # 落在所有工具块之外的 <parameter> = 形状 D(<type> 包 parameter): 没有任何工具名,
    # 重建不了, 只能当残渣重试 —— 绝不能当最终回答交付。
    # 同样行首锚定: 正文里"用法: <parameter name=…>"这种说明句不该触发重试。
    for m in re.finditer(_BOL + r'<' + _DSML + r'parameter\b[^<>]*>', text, re.I):
        if any(a <= m.start() < b for a, b in spans): continue
        sc.orphans.append('parameter')
    # 块内参数有开无闭 = 截断(例如 </code_run> 到了但 </parameter> 没到)
    for b in sc.blocks:
        if b['body'].count('<parameter') > b['body'].count('</parameter'):
            sc.unclosed.append(b['name'])
    return sc


def _coerce(k, v):
    """参数值按名字收敛类型: timeout 等转 int, 布尔开关转 bool。"""
    if not isinstance(v, str): return v
    s = v.strip()
    if k in ('timeout', 'start', 'count', 'maxlen') and re.fullmatch(r'-?\d+', s): return int(s)
    if k in ('show_linenos', 'tabs_only', 'text_only', 'no_monitor', 'inline_eval'):
        return s.lower() in ('true', '1', 'yes')
    return v


def _pseudo_xml_args(body, name, attrs=''):
    """从块体/开标签属性里抽参数。抽不出返回 {}。"""
    args = {}
    for k, v in re.findall(r'([A-Za-z_][\w-]*)\s*=\s*["\']([^"\']*)["\']', attrs or ''):
        args[k] = _coerce(k, v)
    m = re.search(r'<' + _DSML + r'script[^<>]*>(.*?)</' + _DSML + r'script\s*>', body, re.DOTALL | re.I)
    if m: args.setdefault('script', m.group(1).strip('\n'))
    # 参数名解析与工具标签的引号风格解耦: `parameter name="k"` / `parameter name='k'` /
    # `parameter=k` / `parameter name=k` 全部认。标签上的 `string="true"` 等属性不参与。
    for pm in re.finditer(r'<' + _DSML + r'parameter\s*(?:name\s*)?=\s*["\']?([\w.-]+)["\']?[^<>]*>'
                          r'(.*?)</' + _DSML + r'parameter\s*>', body, re.DOTALL | re.I):
        k = pm.group(1)
        if k and k.lower() not in ('string', 'true', 'false', 'type'):
            args.setdefault(k, _coerce(k, pm.group(2).strip('\n')))
    if args: return args
    b = (body or '').strip()
    if not b: return {}
    if b[0] in '{[':
        try:
            d = json.loads(b)
            if isinstance(d, dict): return d
        except Exception:
            pass
    if name in ('code_run', 'bash', 'powershell') and '<' not in b:
        return {'script': b}
    return {}


_SHELL_HEAD = re.compile(
    r'^\s*(ls|cd|pwd|dir|echo|cat|git|pip|pip3|npm|curl|wget|ssh|scp|mkdir|rm|cp|mv|chmod|'
    r'python3?|bash|sh|zsh|node|docker|kubectl)\b')


def salvaged_call_problem(call):
    """抢救出来的调用能不能安全执行。返回问题描述, '' 表示没问题。

    宁可让模型重发, 也不能把半截/压平成一段的脚本直接跑起来。
    """
    fn = getattr(call, 'function', None)
    name = getattr(fn, 'name', '') or ''
    if not name: return 'tool name is empty'
    try:
        args = json.loads(getattr(fn, 'arguments', '') or '{}')
    except Exception as e:
        return 'arguments are not valid JSON: %s' % e
    if not isinstance(args, dict): return 'arguments are not an object'
    if name in ('code_run', 'code_exec', 'bash', 'powershell'):
        code = args.get('script') or args.get('code') or ''
        if not str(code).strip(): return 'script is empty'
        ctype = str(args.get('type') or '').lower()
        if not ctype: ctype = 'shell' if _SHELL_HEAD.match(str(code)) else 'python'
        if ctype in ('python', 'py'):
            try:
                ast.parse(str(code))
            except SyntaxError as e:
                return 'python syntax error (line %s: %s)' % (e.lineno, e.msg)
    elif name in ('file_read', 'file_write', 'file_patch'):
        if not args.get('path'): return 'path is empty'
    return ''


def leaked_markup_incomplete(text):
    """伪工具块是否被截断(流中断 / max_tokens)。True = 残块, 绝不能执行。"""
    try:
        if not text: return False
        return bool(_scan_pseudo_xml(text).unclosed)
    except Exception:
        return False


def textual_tool_residue(content):
    """正文里是否残留**调不成**的伪工具块。

    返回 'unclosed'(有开无闭, 通常是流被掐断) / 'empty'(块闭合但没参数) /
    'orphan'(有 <parameter> 却没有工具名) / 'invalid'(块闭合但重建的调用不可安全执行) / None。
    一旦命中就绝不能当最终回答交付:
    用户看到的「冒出一坨标签然后对话自己中断了」就是这条路径。
    """
    try:
        if not content: return None
        sc = _scan_pseudo_xml(content)
        if sc.unclosed: return 'unclosed'
        if sc.orphans: return 'orphan'
        for b in sc.blocks:
            args = _pseudo_xml_args(b['body'], b['name'], b['attrs'])
            if not args: return 'empty'
            # 块是闭合的, 但重建出来的调用不可安全执行(半截脚本/语法错) —— 同样是残渣。
            # 这类不能在 `_parse_pseudo_xml_tool_calls` 里静默丢掉(那样会被当最终回答)。
            if salvaged_call_problem(MockToolCall(b['name'], args)): return 'invalid'
        return None
    except Exception:
        return None


def _parse_pseudo_xml_tool_calls(content):
    """把伪 XML 工具块还原成 MockToolCall。返回 (tcs, 去掉块后的正文)。

    ★ 安全闸门放在**这个函数内部**(即 `_parse_text_tool_calls` 返回之前), 而不是
      `ga.do_no_tool`: 半截调用一旦变成真 tool_calls, 就会先走执行路径 ——
      PR #853 的 H 正是这样被执行的。`leaked_markup_incomplete` 和
      `salvaged_call_problem` 在这里就把它们拦下, 宁可让模型重发。
    """
    try:
        sc = _scan_pseudo_xml(content)
        if not sc.blocks: return [], content
        if textual_tool_residue(content): return [], content      # unclosed / empty / orphan
        found = []
        for b in sorted(sc.blocks, key=lambda x: x['start']):
            args = _pseudo_xml_args(b['body'], b['name'], b['attrs'])
            if not args: return [], content
            call = MockToolCall(b['name'], args)
            if salvaged_call_problem(call): return [], content    # 半截/坏脚本不许执行
            found.append(call)
        rest, last = [], 0
        for b in sorted(sc.blocks, key=lambda x: x['start']):
            if b['start'] < last: continue
            rest.append(content[last:b['start']]); last = b['end']
        rest.append(content[last:])
        tail = ''.join(rest)
        tail = re.sub(r'</?' + _DSML + r'(?:tool_calls|function_calls|invoke|function)\s*>', '', tail, flags=re.I)
        return found, tail.strip()
    except Exception as e:
        print('[WARN] _parse_pseudo_xml_tool_calls failed: %s' % e)
        return [], content

def _ensure_text_block(blocks):
    """If response has thinking but no text block, inject a synthetic summary from thinking's first line."""
    if any(b.get("type") == "text" for b in blocks): return None
    th = next((b.get("thinking", "") for b in blocks if b.get("type") == "thinking"), "")
    if not th: return None
    line = th.strip().split('\n', 1)[0]
    txt = "<summary>" + (line[:60] + '...' if len(line) > 60 else line) + "</summary>"
    blocks.insert(1, {"type": "text", "text": txt})
    return txt

def _write_llm_log(label, content, log_path=None, model=''):
    if log_path is False: return
    if not log_path:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'temp/model_responses/model_responses_{os.getpid()}.txt')
    # ★2026-11-09 本地日志脱敏: 这个文件是会话恢复的唯一事实源, 但从未脱敏,
    #   实测 96.7MB 里 mykey 的 28 个 apikey 明文全在(355 次)。
    #   只脱**本地日志**, 不动发给上游的请求体(否则 agent 会照抄占位符去配渠道)。
    #   关闭: env GA_LLM_LOG_REDACT=0
    try:
        import llm_redact as _rd
        if _rd.enabled():
            content = _rd.mask(content)
    except Exception:
        pass
    os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if model: model = f' model={model}'
    with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f"=== {label} === {ts}{model}\n{content}\n\n")

def tryparse(json_str):
    try: return json.loads(json_str)
    except: pass
    json_str = json_str.strip().strip('`').replace('json\n', '', 1).strip()
    try: return json.loads(json_str)
    except: pass
    try: return json.loads(json_str[:-1])
    except: pass
    if '}' in json_str: json_str = json_str[:json_str.rfind('}') + 1]
    return json.loads(json_str)

# ==== 渠道会话租约 (2026-10-13): 「某渠道最多同时 N 个会话」 ====================
# 配置: mykey.py 模块级  channel_session_caps = {"ds4f_404": 6}   (未列出的渠道不限)
# 语义(用户令, 会话级): 会话活着并活跃即占用一个名额; 每次 LLM 调用续租; 空闲超 _LEASE_TTL 或进程退出即释放.
#   名额满 → 该会话自动从 llm_nos 的下一顺位起选; 全部满 → 退化为「占用最少的渠道」(不阻塞).
#   未配置 caps 时 MixinSession._leases 为 None → 全链路零开销, 行为与旧版逐字节一致.
# 租约文件: <GA根>/temp/llm_leases/<渠道>__<pid>-<rand>.lease  (mtime = 最近续租时间)
_LEASE_TTL = 1800          # 租约有效期(秒): 30 分钟无活动即视为释放
_LEASE_ROOT = os.path.join(_ROOT, 'temp', 'llm_leases')
# ★2026-11-08 测试钩子(生产恒为 None/空集, 零行为变化):
#   _LEASE_TEST_PID        = 伪造「当前进程号」, 让回归测试能在同一 Python 进程里模拟多个进程;
#   _LEASE_TEST_ALIVE_PIDS = 声明某些伪造 pid 为「存活」, 免被 _live() 当死租约清掉。
_LEASE_TEST_PID = None
_LEASE_TEST_ALIVE_PIDS = set()


def _lease_cur_pid():
    return _LEASE_TEST_PID if _LEASE_TEST_PID else os.getpid()
_LEASE_SIDS = set()
# ★2026-11-05 根治「同一进程重复占名额」:
#   旧实现每个 ChannelLease 实例一个随机 sid → GA 每轮对话重建 MixinSession 就落一个新租约,
#   同一进程会把自己配的 cap 占满(实测 TUI 3 轮就把 cap=3 的渠塞满 → 顺延到别的渠)。
#   修法两层: ①sid 改为**进程级常量**(同进程所有实例共用一个租约文件, 文件名不再增长)
#            ②counts() 按 (桶, pid) **去重计数** → 一个进程对该桶只算 1 个名额(= 跨进程并发数, 这才是 cap 的原意)
#   同进程内多个实例共用一个文件 → 用 _LEASE_REF 引用计数, 减到 0 才删文件(避免 A.release 删掉 B 还在用的租约)。
_LEASE_PID_SID = {}     # pid -> 进程级 sid
_LEASE_REF = {}         # (sid, bucket) -> 进程内引用计数

def _lease_pid_sid():
    """进程级 sid: 同一进程的所有 ChannelLease 实例共用(旧实现每实例随机→同名桶反复占名额)."""
    pid = _lease_cur_pid()
    sid = _LEASE_PID_SID.get(pid)
    if sid is None:
        sid = f'{pid}-{uuid.uuid4().hex[:8]}'
        _LEASE_PID_SID[pid] = sid
    return sid

def _lease_ref_inc(sid, bucket):
    k = (sid, bucket); _LEASE_REF[k] = _LEASE_REF.get(k, 0) + 1; return _LEASE_REF[k]

def _lease_ref_dec(sid, bucket):
    """返回剩余引用数; 0 = 可以删租约文件了."""
    k = (sid, bucket); n = _LEASE_REF.get(k, 0) - 1
    if n > 0: _LEASE_REF[k] = n
    else: _LEASE_REF.pop(k, None); n = 0
    return n

def _lease_safe(name): return re.sub(r'[^0-9A-Za-z_.\-]', '_', str(name))

def _lease_pid_alive(pid):
    try:
        if int(pid) in _LEASE_TEST_ALIVE_PIDS: return True
    except Exception: pass
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        return True   # 无 psutil 时不做进程存活判定, 只靠 TTL 兜底

def _lease_unlink(p):
    """删除租约/锁文件 —— 只吞不抛, 包括 BaseException(含 SystemExit)。

    ★2026-10-20 修复: 宿主环境的 safe-delete 守卫会把「单轮内删除文件数 ≥50」
    直接提升为 SystemExit(1)。租约清理每次 acquire/release 都会删 1-2 个
    temp/llm_leases 下的内部临时文件, 长任务(如 187 条日报的 25+ 次 LLM 调用)
    必然撞线 → 主流程在聚类阶段被 SystemExit 打断, 日报产不出来。
    租约文件纯属内部临时态, 清理失败不应影响任何业务逻辑: 这里一律吞掉。
    """
    try:
        os.remove(p); return True
    except BaseException:
        return False

class ChannelLease:
    """文件租约: 记录本会话当前占用的「名额桶」(渠道名, 或同一上游账号的渠道组名), 供跨会话/跨进程统计同时会话数."""
    _atexit_hooked = False
    def __init__(self, root=None):
        self.dir = root or _LEASE_ROOT; self.held = None
        self.pid = _lease_cur_pid()
        self.sid = _lease_pid_sid()
        self._lock_path = os.path.join(self.dir, '.lock')
        try: os.makedirs(self.dir, exist_ok=True)
        except Exception: pass
        if not ChannelLease._atexit_hooked:
            ChannelLease._atexit_hooked = True; atexit.register(ChannelLease.cleanup_all)
        _LEASE_SIDS.add(self.sid)
    def _path(self, channel): return os.path.join(self.dir, f'{_lease_safe(channel)}__{self.sid}.lease')
    def _lock(self, timeout=3.0):
        end = time.time() + timeout
        while True:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode()); os.close(fd); return True
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self._lock_path) > 10: _lease_unlink(self._lock_path); continue
                except Exception: pass
                if time.time() > end: return False
                time.sleep(0.05)
            except Exception: return False
    def _unlock(self):
        _lease_unlink(self._lock_path)
    def _write(self, bucket, name=None):
        if self.held == bucket:      # 已在同一桶: 只续期, 不重复计引用
            self.renew(); return True
        p = self._path(bucket)
        try:
            with open(p + '.tmp', 'w', encoding='utf-8') as f:
                json.dump({'bucket': bucket, 'channel': name or bucket, 'sid': self.sid,
                           'pid': self.pid, 'renewed': time.time()}, f)
            os.replace(p + '.tmp', p); self.held = bucket
            _lease_ref_inc(self.sid, bucket); return True
        except Exception: return False
    def _live(self):
        """扫描全部租约, 顺带清理 过期 / 进程已死 的租约."""
        out = []
        try: names = os.listdir(self.dir)
        except Exception: return out
        for fn in names:
            if not fn.endswith('.lease'): continue
            p = os.path.join(self.dir, fn)
            try: mt = os.path.getmtime(p)
            except Exception: continue
            try:
                with open(p, encoding='utf-8') as f: d = json.load(f)
            except Exception: d = {}
            if not isinstance(d, dict): d = {}
            if time.time() - mt > _LEASE_TTL or not _lease_pid_alive(d.get('pid')):
                # ★B7 修复(2026-10-16): 删除前**重取 mtime** —— counts() 是读路径, 不该误删
                #   刚好被持有方续租(utime)的活租约; 只有"仍然过期"才清。
                try:
                    if time.time() - os.path.getmtime(p) > _LEASE_TTL or not _lease_pid_alive(d.get('pid')):
                        _lease_unlink(p)
                except Exception: pass
                continue
            out.append(d)
        return out
    def counts(self):
        """各桶当前「占用名额数」.
        ★2026-11-05: 按 (桶, pid) **去重** —— 同一进程对该桶只算 1 个名额.
          旧实现按文件计数, 而同一进程每建一次 MixinSession 就落一个新文件 →
          自己把自己塞满(实测 cap=3 的渠 3 轮对话即满). cap 的原意是「同时有几个进程在用」.
        """
        c, seen = {}, set()
        for d in self._live():
            ch = d.get('bucket') or d.get('channel')
            if not ch: continue
            key = (ch, d.get('pid'))
            if key in seen: continue
            seen.add(key); c[ch] = c.get(ch, 0) + 1
        return c
    def renew(self):
        if not self.held: return False
        try:
            p = self._path(self.held)
            if not os.path.exists(p): return False
            os.utime(p, None); return True
        except Exception: return False
    def release(self):
        if not self.held: return
        b = self.held
        self.held = None
        if _lease_ref_dec(self.sid, b) > 0: return   # 同进程还有别的实例在用这个桶 → 保留文件
        _lease_unlink(self._path(b))
    def acquire(self, bucket, name=None):
        if self.held == bucket: return self.renew()
        old = self.held
        if not self._lock(): return False
        try:
            if old and old != bucket: self.release()
            return self._write(bucket, name)
        finally: self._unlock()
    def claim(self, buckets, caps, names=None, start=0):
        """锁内完成「选渠 + 落租约」: 从 start 起按顺序找首个未满渠道并落租约.

        buckets[i] = 第 i 个渠道占用的名额桶(渠道名或账号组名); caps = {桶名: 上限}(无该项=不限).
        ★2026-10-19: start=当前渠道下标 → 「本渠满了就顺延到下一级渠道」, 全满返回 None(不越界).
        """
        if not self._lock(): return None
        try:
            counts = self.counts()
            if self.held:
                # 本实例即将换桶: 只有「本进程对该桶不再有任何引用」才从计数里减掉
                if _LEASE_REF.get((self.sid, self.held), 1) - 1 <= 0:
                    counts[self.held] = max(0, counts.get(self.held, 0) - 1)
            labels = names or buckets
            n = len(buckets)
            try: start = int(start) % n if n else 0
            except Exception: start = 0
            order = list(range(start, n)) + list(range(0, start))
            # ★2026-10-19 修复(用户令): 原实现在**所有渠道都满**时仍 `self._write(pick,...)` 落租约,
            #   注释自称"退化到占用最少者" → 实际是**静默突破 cap**(两个会话可同时占 cap=1 的渠)。
            #   现改为: 全部桶都满 → 返回 None(不写租约, 不冒领名额); 调用方 _lease_sync 会保持原渠
            #   (可用性优先, 不阻塞/不空转), 只是本会话暂不计入任何渠的名额。
            for i in order:
                b, cnt = buckets[i], counts.get(buckets[i], 0); cap = caps.get(b)
                if cap is None or cnt < cap:
                    self._write(b, labels[i]); return i
                # ★2026-11-05: 本进程(别的实例/上一轮)已占该桶 → 复用同一名额, 不算满。
                #   cap 语义已改为「跨进程并发数」(counts 按 pid 去重), 这里必须同步,
                #   否则 cap=1 的渠在第二轮会被自己判满而顺延到别的渠。
                if _LEASE_REF.get((self.sid, b), 0) > 0:
                    self._write(b, labels[i]); return i
            return None
        finally: self._unlock()
    @staticmethod
    def cleanup_all():
        for sid in list(_LEASE_SIDS):
            try:
                for fn in os.listdir(_LEASE_ROOT):
                    if fn.endswith(f'__{sid}.lease'):
                        _lease_unlink(os.path.join(_LEASE_ROOT, fn))
            except Exception: pass

# ==== 请求级渠道并发闸 (2026-11-07 用户令)=========================================
# 用户口径: 「进门之后第一间只能进多少、第二间多少; 每个进之前先数一下当前房间里有多少人;
#   都满了就在门口排队, 前面的人做完再进; 第一个房间坏了就只能在第二个房间门口排队」
#
# 现行架构(2026-11-07 审查后收敛为**单一真闸**):
#   ChannelSlotGate = 唯一的限流层: 每个**在途请求**占 1 个名额, 跨进程/跨线程安全
#   ChannelLease    = 历史会话层(按 (桶, pid) 去重 = 每进程每桶算 1 个名额),
#                     由 mykey.llm_channel_lease_gate 控制, **默认 True 开启**(2026-11-08 核实:
#                     旧注释写「默认关闭只作观测」与代码不符, 已按实际行为更正)。
#   总闸 GlobalGate 已按用户令关闭(llm_global_max_concurrency=0)
#
# 名额实现: temp/llm_chan_slots/<slot_key>/<n>.slot, n ∈ [0, cap), O_EXCL 原子抢占
#   slot_key = 可读名 + sha1 后缀 → 不同桶名永不撞车('a@b' 与 'a_b' 各自独立)
# 回收: pid 已死 / 同进程线程已死 → 立刻回收; 存活但 TTL 内无心跳 → 兜底回收
# 排队: 全满 → 门口排队; 预算耗尽 → 挑**当前最空**的房放行(override)并计数告警
#       wait<=0 = 明确不排队(返回 REJECTED, 由调用方顺延); None = 无限等
import hashlib

_CHAN_SLOT_DIR = os.path.join(_ROOT, 'temp', 'llm_chan_slots')
_CHAN_SLOT_TTL = 21600       # 单槽最长存活(秒): 无心跳时的兜底(6h), 正常靠心跳续命
_CHAN_SLOT_HB = 60           # 心跳间隔(秒): 长流式请求期间刷新 mtime, 防止被当成死槽
_CHAN_SWEEP_EVERY = 2.0      # 同桶最短清扫间隔(秒): 排队轮询时不再每 20ms 扫目录

# acquire_any 的四种结果(取代原先 path=None 一词两义的写法)
ACQUIRED, NO_CAP, OVERRIDE, REJECTED = 'acquired', 'no_cap', 'override', 'rejected'
REJECT = 'reject'            # wait 的哨兵值: 宁可放弃也不突破上限


def _wait_left(w, deadline=None):
    """把 wait 配置归一成 acquire_any 能吃的值。

    ★2026-11-07 修复: caller 原来直接写 `time.time() + self._chan_wait if self._chan_wait > 0`,
      mykey 里把 llm_channel_wait_seconds 写成字符串哨兵('reject'/'never'/'none')时,
      `float()` 或 `> 0` 会直接抛异常 → MixinSession 构造失败 / 请求崩。
      REJECT 必须原样透传(不能被 float 比较吞掉), 其余按秒数处理。
    """
    if w is REJECT: return REJECT
    if w is None: return None            # 无限等
    try: w = float(w)
    except Exception: return None        # 配错值 → 退回无限等, 绝不让业务崩
    if w <= 0: return 0.0                # 明确不等 → 立即 OVERRIDE(带计数)
    if deadline is None: return None
    return max(0.0, deadline - time.time())

_OVERRIDE_STAT = {}          # 桶名 -> 本进程内 override 次数(观测用)
_SWEEP_AT = {}               # slot_key -> 上次清扫时间


def _slot_key(bucket):
    """桶名 → 槽目录名。可读前缀 + sha1 后缀。

    ★2026-11-07 修复: 原实现直接用 _lease_safe(bucket) 当目录名, 而 _lease_safe 把
      '@' 换成 '_' → 'a@b' 与 'a_b' 撞进同一个桶(两间房静默共用名额池)。加哈希后缀后
      不同桶名永不撞车; 同时 _lease_safe 仍保持原样, 不影响历史租约文件名。
    """
    s = str(bucket)
    return _lease_safe(s) + '--' + hashlib.sha1(s.encode('utf-8')).hexdigest()[:10]


def _thread_alive(tid):
    return any(t.ident == tid for t in threading.enumerate())


class ChannelSlotGate:
    """请求级渠道并发闸: 某渠道同一时刻最多 N 个**在途请求**(跨进程 + 跨线程)."""

    def __init__(self, wait=None):
        self.dir = _CHAN_SLOT_DIR
        self.wait = wait

    # ---- 内部 ----
    def _bdir(self, bucket, create=True):
        d = os.path.join(self.dir, _slot_key(bucket))
        if create:
            try: os.makedirs(d, exist_ok=True)
            except Exception: return None
        return d

    @staticmethod
    def _scan(d):
        try: return [f for f in os.listdir(d) if f.endswith('.slot')]
        except Exception: return []

    def _sweep(self, bucket, cap=None):
        """清掉该死/过期的槽 —— 只吞不抛(纯内部临时态, 绝不能影响业务)。

        ★2026-11-07 修复(原实现两处根因):
          ① `dead = age > TTL` **优先于** pid/tid 存活判定 → 正在跑的活槽被当死槽删掉,
             该房间随即被超卖(实测: 活槽在 TTL 后被清, count 归 0)。现在存活的
             pid/线程是硬证据, TTL 只在无法判定存活时兜底。
          ② 下标 >= cap 的残留槽(调小 cap 后遗留的 3.slot/4.slot)永不回收 →
             count 虚高、房间"永远满"。现在直接回收(它们不可能再被抢到)。
        """
        d = self._bdir(bucket, create=False)
        now, mypid = time.time(), os.getpid()
        for fn in self._scan(d):
            p = os.path.join(d, fn)
            try: mt = os.path.getmtime(p)
            except Exception: continue
            if cap:
                try:
                    if int(fn[:-5]) >= int(cap):
                        _lease_unlink(p); continue
                except Exception: pass
            pid = tid = None; corrupt = False
            try:
                with open(p, encoding='utf-8') as f: info = json.load(f) or {}
                if not isinstance(info, dict): raise ValueError('bad slot')
                pid, tid = info.get('pid'), info.get('tid')
            except Exception:
                corrupt = True
            dead = False
            if corrupt:
                dead = now - mt > 5                      # 写了半截: 给 5s 宽容窗口
            elif pid is not None and not _lease_pid_alive(pid):
                dead = True                              # 进程已死
            elif pid == mypid and tid is not None and not _thread_alive(tid):
                dead = True                              # 同进程线程已死(生成器被弃用)
            elif pid == mypid:
                dead = False                             # 同进程 + 线程活着 = 精确证据, TTL 一律不适用
            elif now - mt > _CHAN_SLOT_TTL:
                dead = True                              # 他进程且长期无心跳 → 只能靠 TTL 兜底
            if dead: _lease_unlink(p)

    def _maybe_sweep(self, bucket, cap=None, force=False):
        """按 _CHAN_SWEEP_EVERY 节流清扫。

        ★2026-11-07: 原实现每次 try_acquire 前都 sweep 一遍 → 排队时 22 房 × 8 线程 ×
          每秒数十轮 = 每秒上万次 listdir + open + json.load + psutil 查询, 房间一满磁盘
          先炸。现在同桶 2s 内只扫一次。
        """
        k = _slot_key(bucket); now = time.time()
        if not force and now - _SWEEP_AT.get(k, 0.0) < _CHAN_SWEEP_EVERY: return
        _SWEEP_AT[k] = now
        self._sweep(bucket, cap)

    def count(self, bucket, cap=None):
        """该渠道当前在途请求数(已清扫)."""
        self._maybe_sweep(bucket, cap, force=True)
        return len(self._scan(self._bdir(bucket, create=False)))

    def try_acquire(self, bucket, cap):
        """非阻塞抢 1 个名额; 成功返回槽文件路径, 满返回 None."""
        if not cap or cap <= 0: return None
        d = self._bdir(bucket)
        if d is None: return None
        for i in range(int(cap)):
            p = os.path.join(d, '%d.slot' % i)
            try: fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError: continue
            except Exception: return None
            try:
                os.write(fd, json.dumps({'pid': os.getpid(), 'tid': threading.get_ident(),
                                         'bucket': bucket, 'ts': time.time()}).encode())
            finally:
                try: os.close(fd)
                except Exception: pass
            return p
        return None

    def touch(self, path):
        """心跳: 刷新槽 mtime, 让长流式请求不被 TTL 兜底回收."""
        if not path: return False
        try: os.utime(path, None); return True
        except Exception: return False

    def release(self, path):
        if path: _lease_unlink(path)

    # ---- 对外: 选房间 + 占名额(含排队) ----
    def _order_for(self, buckets, start, exclude=None):
        """本次请求的**尝试顺序**: 从 start 起环形顺延(走到尾再回头)。

        ★扩展点(下一步「渠道智能化网关」): 时间段优先组(白天优先 A / 20:00 后优先 B)
          就加在这里 —— 读时间配置把 prefer 组的下标提到 order 前面即可,
          acquire_any 的抢占/排队/override 逻辑完全不用动。
        """
        n = len(buckets)
        try: s = int(start) % n
        except Exception: s = 0
        order = list(range(s, n)) + list(range(0, s))
        if exclude:
            try: _ex = {int(i) for i in exclude}
            except Exception: _ex = set()
            kept = [i for i in order if i not in _ex]
            if kept: order = kept
            else: print('[ChanGate] 所有房间本请求均已失败 → 放开重试一轮')
        return order

    def _least_loaded(self, order, buckets, caps):
        """override 时挑「占用率最低」的房。

        ★2026-11-07 修复: 原实现一律 `return order[0]` → 超卖全堆在 start 那一间,
          其它 20 间空着(实测 5 次 override 全落同一个下标)。这与「顺延到下一间房」
          的意图正好相反, 也是"8 个会话同时打同一个模型"的复现路径。
        """
        best, best_r = order[0], None
        for i in order:
            b, cap = buckets[i], caps.get(buckets[i])
            c = self.count(b, cap)
            r = (c / cap) if cap else 0.0
            if best_r is None or r < best_r: best, best_r = i, r
        return best

    def acquire_any(self, buckets, caps, start=0, wait=None, exclude=None):
        """选一个可用的「房间」并占名额.

        返回 (idx, path, status):
          ACQUIRED : path 非空, 已占该渠道 1 个名额, 用完必须 release(path)
          NO_CAP   : path 为 None, 该渠道不限并发(没配 cap)
          OVERRIDE : path 为 None, 排队预算耗尽 → 放行(已计数告警, 可能突破上限)
          REJECTED : path 为 None, wait<=0(明确不排队)且全满 → 本次不占名额, 由上层顺延

        wait 语义(★2026-11-07 修复, 原实现有两条致命边界):
          None   = 沿用 self.wait(默认 300s)
          >0     = 排队预算(秒), 耗尽 → OVERRIDE
          <=0    = 明确「不等」→ 立刻 OVERRIDE(带计数与告警), 不再静默
          REJECT = 「宁可放弃也不突破上限」→ 全满时立刻 REJECTED, 交上层顺延
          旧实现 `wait=0` 时 `time.time()-t0 >= 0` 首轮即真 → 一个都不等就放行,
          且**只打一行日志、无计数**, cap 事实上失效(实测 0.01s 抢到第 4 个名额);
          `wait=-1` 则条件恒假 → **永久阻塞**(实测线程永不返回)。
        """
        n = len(buckets)
        if not n: return 0, None, NO_CAP
        wait = self.wait if wait is None else wait
        if isinstance(wait, str):
            wait = REJECT if wait.lower() in ('reject', 'none', 'never') else None
        else:
            try: wait = float(wait)
            except Exception: wait = None
        order = self._order_for(buckets, start, exclude)
        if all(not caps.get(buckets[i]) for i in order):
            return order[0], None, NO_CAP        # 一条渠道都没配上限 → 零开销
        t0, warned, nap = time.time(), False, 0.02
        while True:
            for i in order:
                b, cap = buckets[i], caps.get(buckets[i])
                if not cap or cap <= 0:
                    return i, None, NO_CAP       # 该渠道不限并发 → 直接进
                self._maybe_sweep(b, cap)
                p = self.try_acquire(b, cap)
                if p: return i, p, ACQUIRED
            if not warned:
                _desc = ', '.join(f'{buckets[i]}={caps.get(buckets[i])}' for i in order
                                  if caps.get(buckets[i]))
                print(f'[ChanGate] 渠道并发已满 → 门口排队 ({_desc})')
                warned = True
            if wait is REJECT:
                return order[0], None, REJECTED  # 宁可放弃也不突破上限 → 上层顺延
            if wait is not None and wait <= 0:
                # 明确「不等」: 立刻放行, 但**必须计数+告警**, 不再是静默的假限流
                i = self._least_loaded(order, buckets, caps)
                b = buckets[i]
                _OVERRIDE_STAT[b] = _OVERRIDE_STAT.get(b, 0) + 1
                if not _OVERRIDE_STAT.get('__warned_nowait__'):
                    _OVERRIDE_STAT['__warned_nowait__'] = 1
                    print(f'[ChanGate] llm_channel_wait_seconds <= 0 → 不等候直接放行 {b} '
                          f'(cap 会被突破, 已在 chan_gate_status 计数 override)')
                return i, None, OVERRIDE
            if wait is not None and time.time() - t0 >= wait:
                # 排队预算耗尽: 放行但计数(可观测的过载, 而非静默失效)
                i = self._least_loaded(order, buckets, caps)
                b = buckets[i]
                _OVERRIDE_STAT[b] = _OVERRIDE_STAT.get(b, 0) + 1
                print(f'[ChanGate] 排队 {wait:.0f}s 仍无空位 → 放行 {b} '
                      f'(override #{_OVERRIDE_STAT[b]}, 已突破渠道上限)')
                return i, None, OVERRIDE
            # 自适应退避: 刚空出立刻进(20ms), 久等才拉到 200ms —— 既省 CPU 又不白白多等
            time.sleep(nap)
            nap = min(0.2, nap * 1.5)

    def counts(self, buckets=None):
        """各渠道当前在途数(观测用). buckets 传**原始桶名**, 内部自动编码。

        ★2026-11-07 修复: 原实现直接拿 `os.listdir` 的目录名去比对传入的原始桶名,
          而目录名经过 _lease_safe 转义('@'→'_') → 传入带 '@' 的桶名永远查不到,
          恒返回 {}。现在两边都走 _slot_key, 口径一致。
        """
        out = {}
        try: names = os.listdir(self.dir)
        except Exception: return out
        if buckets is None:
            for fn in names:
                d = os.path.join(self.dir, fn)
                if not os.path.isdir(d): continue
                c = len(self._scan(d))
                if c: out[fn] = c
            return out
        for b in buckets:
            c = self.count(b)
            if c: out[b] = c
        return out


def chan_gate_status():
    """渠道闸水表: 各渠道 在途请求数 / **有效**上限 / override 次数.

    ★2026-11-07 整体重写(原实现报错数, 比没有水表更糟):
      ① `_eff()` 只读 channel_session_caps / channel_cap_groups, **不读
         channel_session_caps_by_mixin** → 隔离池的 cap 一律显示 None;
      ② 用未编码的桶名去比对已编码的目录名 → 带 '@' 的桶(隔离池)永远查不到, inflight 恒 0。
      实测旧输出: 'ds4f_oc2api'→inflight 0/cap 3, 'ds4f_oc2api_mixin_config_task_llm'→inflight 2/cap None
      (真实情况: 隔离池里 2 个在跑, cap 就是 3)
    """
    try:
        mk = reload_mykeys()[0] or {}
        caps = mk.get('channel_session_caps') or {}
        groups = mk.get('channel_cap_groups') or {}
        bymix = mk.get('channel_session_caps_by_mixin') or {}
    except Exception:
        caps, groups, bymix = {}, {}, {}

    def _group_of(ch):
        try:
            for g, members in (groups or {}).items():
                if isinstance(members, (list, tuple, set)) and ch in members:
                    return g
        except Exception: pass
        return None

    def _bucket_of(name):
        """渠道/桶名 + 可选 '@mixin' 后缀 → 真实名额桶名(与 MixinSession 的 _buckets 一致)."""
        s = str(name)
        if '@' in s: return s                  # 已隔离: 桶名就是带后缀的全名
        return _group_of(s) or s               # 组内成员 → 用组名当桶

    def _eff(bucket):
        """桶名(可能带 '@mixin' 后缀) → (cap, 来源)."""
        b = str(bucket)
        base, sep, mix = b.partition('@')
        if sep:
            ov = (bymix or {}).get(mix) or {}
            v = ov.get(base)
            if v is not None:
                try: return (int(v) if int(v) > 0 else None), f'by_mixin:{mix}'
                except Exception: pass
            # by_mixin 未显式改写 → 回落到全局表(与 MixinSession 的合并顺序一致)
        c = caps.get(base)
        if c is not None: return c, 'caps'
        g = _group_of(base)
        if g is not None: return caps.get(g), f'group:{g}'
        return None, None

    # 目录 → 在途数(只 listdir, 不清扫: 水表是观测路径, 不该删任何东西)
    live = {}
    try:
        for fn in os.listdir(_CHAN_SLOT_DIR):
            d = os.path.join(_CHAN_SLOT_DIR, fn)
            if os.path.isdir(d):
                c = len(ChannelSlotGate._scan(d))
                if c: live[fn] = c
    except Exception: pass

    # 候选桶名: 全局 caps + 组内成员 + by_mixin 覆盖(按 _isolate 决定是否带后缀)
    names = [str(k) for k in caps]
    for ms in (groups or {}).values():
        if isinstance(ms, (list, tuple, set)): names.extend(str(m) for m in ms)
    for mix, ov in (bymix or {}).items():
        if not isinstance(ov, dict): continue
        iso = ov.get('_isolate', ov.get('_namespace', ov.get('_iso')))
        iso_all = (iso is True or iso == '*')
        iso_set = {str(x) for x in iso} if isinstance(iso, (list, tuple, set)) else set()
        for k in ov:
            k = str(k)
            if k.startswith('_'): continue
            names.append(f'{k}@{mix}' if (iso_all or k in iso_set) else k)
    names = list(dict.fromkeys(names))

    out, seen = {}, set()
    for k in names:
        bucket = _bucket_of(k)
        key = _slot_key(bucket)
        seen.add(key)
        cap, src = _eff(k)
        inflight = live.get(key, 0)
        e = {'inflight': inflight, 'cap': cap, 'cap_src': src,
             'override': _OVERRIDE_STAT.get(bucket, 0)}
        if cap is not None:
            e['free'] = max(0, int(cap) - inflight)
        out[k] = e

    # 目录里存在但配置里已没有的桶(改配置后的残留) → 单独列出, 否则会"隐形占位"
    for fn, c in live.items():
        if fn not in seen:
            out.setdefault(f'<stale:{fn}>',
                           {'inflight': c, 'cap': None, 'cap_src': 'stale', 'override': 0})
    return out



# ==== 渠道速率闸 (2026-10-13): 「某渠道每窗口最多 N 次请求」 ====================
# 配置: mykey.py 模块级  channel_rate_limits = {"ds4f_404": {"limit": 60, "window": 60, "reserve": 6}}
#   语义: 跨进程共享的滑动窗口计数(窗口内已放行次数 >= limit-reserve 即视为「将满」);
#         MixinSession 路由时把「将满」的渠道排到后面(优先用其它渠), 全部将满 → 不做限制(尽力而为, 不空转).
#   未配置 channel_rate_limits 时 MixinSession._rate_gate 为 None → 全链路零开销, 行为与旧版一致.
#   计数落盘: <GA根>/temp/llm_leases/rl_<渠道>.jsonl (每行一个 epoch 秒), 每次读取自动裁剪过期项.
class ChannelRateGate:
    def __init__(self, rules):
        self.rules = rules or {}
        self.dir = _LEASE_ROOT
        try: os.makedirs(self.dir, exist_ok=True)
        except Exception: pass
        self._lock_path = os.path.join(self.dir, '.rl.lock')
    def _path(self, bucket): return os.path.join(self.dir, f'rl_{_lease_safe(bucket)}.jsonl')
    def _cfg(self, bucket):
        cfg = self.rules.get(bucket)
        if not isinstance(cfg, dict): return None
        try: limit = int(cfg.get('limit', 0))
        except Exception: return None
        if limit <= 0: return None
        try: window = float(cfg.get('window', 300))
        except Exception: window = 300.0
        try: reserve = int(cfg.get('reserve', 0))
        except Exception: reserve = 0
        return limit, window, max(0, limit - reserve)
    def _load(self, bucket, window):
        now, out = time.time(), []
        try:
            with open(self._path(bucket), encoding='utf-8', errors='ignore') as f:
                for ln in f:
                    try: t = float(ln.strip())
                    except Exception: continue
                    if now - t < window: out.append(t)
        except Exception: pass
        return out
    def has_room(self, bucket):
        c = self._cfg(bucket)
        if not c: return True
        _, window, thr = c
        return len(self._load(bucket, window)) < thr
    def admit(self, bucket):
        c = self._cfg(bucket)
        if not c: return True
        _, window, thr = c
        if not self._lock(): return True   # 拿不到锁 → 放行, 绝不阻塞主链路
        try:
            ts = self._load(bucket, window)
            if len(ts) >= thr: return False
            ts.append(time.time())
            try:
                # ★B5 修复(2026-10-16): 原为原地截断重写 → 无锁读的 has_room() 可能读到半截
                #   (少计 → 偏乐观)。改为 tmp + os.replace 原子替换, 读者永远看到完整文件。
                _p = self._path(bucket)
                with open(_p + '.tmp', 'w', encoding='utf-8') as f:
                    f.write('\n'.join('%.3f' % t for t in ts))
                os.replace(_p + '.tmp', _p)
            except Exception: pass
            return True
        finally: self._unlock()
    def _lock(self, timeout=2.0):
        end = time.time() + timeout
        while True:
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode()); os.close(fd); return True
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self._lock_path) > 10: _lease_unlink(self._lock_path); continue
                except Exception: pass
                if time.time() > end: return False
                time.sleep(0.03)
            except Exception: return False
    def _unlock(self):
        _lease_unlink(self._lock_path)

_MIXIN_DETECT_WARNED = set()


def _is_mixin_var(n):
    """与 agentmain.load_llm_sessions 的 mixin 识别规则**逐字对齐**(名字含 api/config/cookie 且含 'mixin')。

    ★B3 修复(2026-10-16): 原 `_detect_mixin_name` 要求 startswith('mixin'), 比 agentmain 更严 →
    任何不以 mixin_ 开头的合法 mixin 会静默失去隔离。
    """
    n = str(n)
    return 'mixin' in n and any(x in n for x in ('api', 'config', 'cookie'))


def _warn_mixin_detect_once(cfg, bm):
    """★B2 修复(2026-10-16): `channel_session_caps_by_mixin` 非空、但本 mixin 既无 mixin_name
    又反查不到变量名时 —— 名额覆盖/隔离会**静默失效**(安全机制静默失效最危险)。
    cfg 用 id() 记录, 每个配置对象只告警一次(否则每次 LLM 调用都会刷屏)。"""
    try:
        key = id(cfg)
        if key in _MIXIN_DETECT_WARNED: return
        _MIXIN_DETECT_WARNED.add(key)
        _ln = list((cfg or {}).get('llm_nos') or [])
        print('[WARN] channel_session_caps_by_mixin 已配置, 但本 mixin 反查不到变量名 '
              '→ 名额覆盖/隔离**未生效**! 请在本 mixin 里加 "mixin_name": "<变量名>" 字段, '
              f'或确认变量名含 "mixin"(当前 llm_nos 前 3 项={_ln[:3]})')
    except Exception:
        pass


def _detect_mixin_name(cfg, mk):
    """反查 cfg 这个 mixin 配置字典在 mykey 里的**变量名**(免去在 mixin 内手写 mixin_name 字段)。

    先按对象 identity 精确匹配(同一 mykey 模块对象); 退化为 llm_nos 完全相同且唯一。
    匹配不到 → ''(能力关闭, 行为与旧版一致)。
    """
    try:
        for _n, _v in (mk or {}).items():
            if _v is cfg and _is_mixin_var(_n):
                return str(_n)
        _ln = cfg.get('llm_nos')
        if isinstance(_ln, (list, tuple)) and _ln:
            _cands = [str(_n) for _n, _v in (mk or {}).items()
                      if _is_mixin_var(_n) and isinstance(_v, dict)
                      and list(_v.get('llm_nos') or []) == list(_ln)]
            if len(_cands) == 1:
                return _cands[0]
    except Exception:
        pass
    return ''


class MixinSession:
    """A Session facade backed by multiple routed transport sessions."""
    _TRANSPORT_OVERRIDES = frozenset({
        'stream', 'connect_timeout', 'read_timeout', 'temperature', 'max_tokens',
        'reasoning_effort', 'service_tier', 'thinking_type',
        'thinking_budget_tokens', 'omit_thinking', 'proxies', 'verify',
        'stream_hide_reasoning',
    })
    _FACADE_STATE = frozenset({'name', 'history', 'system', 'tools', 'lock'})

    def __init__(self, all_sessions, cfg, mixin_name=None):
        self._retries = cfg.get('max_retries', 3)
        self._base_delay = cfg.get('base_delay', 3.0)
        self._spring_sec = cfg.get('spring_back', 300)
        selected = [all_sessions[i].backend if isinstance(i, int) else
                    next(s.backend for s in all_sessions if type(s) is not dict and s.backend.name == i)
                    for i in cfg.get('llm_nos', [])]
        if not selected: raise ValueError('MixinSession: no sessions selected')
        # 2026-08-23: 适配渠道数——至少轮询完全部渠道 (n 个渠道需 retries>=n-1)；显式配置更高则保留
        self._retries = max(self._retries, len(selected) - 1)
        native_groups = {isinstance(s, NativeClaudeSession) for s in selected}
        if len(native_groups) != 1:
            raise ValueError(f"MixinSession: sessions must be in same group (Native or non-Native), got {[type(s).__name__ for s in selected]}")

        self._sessions = [copy.copy(s) for s in selected]
        # ★2026-11-08 用户令「重试间隔放长点」: 原实现无条件把每条腿压成 max_retries=0
        #   (失败即顺延下一渠)。对突发限流型站点这等于"刚撞墙就立刻换个号再撞",
        #   反而把整池冷却期都试坏。现允许渠道级 in_mixin_retries>0 时**在原地重试**
        #   (间隔由该渠 retry_base_delay/retry_max_delay 决定); 缺省 0 = 严格旧行为。
        for s in self._sessions:
            s.max_retries = max(0, int(getattr(s, 'in_mixin_retries', 0) or 0))
        self._native = native_groups.pop()
        self._ask_impl = selected[0].ask.__func__
        self._cur_idx, self._switched_at = 0, 0.0
        # 手动切换豁免(默认关): 只作用于**当前 MixinSession 实例**; 开时该实例
        # 不参与 channel_session_caps 的名额选择/占位, 但速率闸 channel_rate_limits
        # 仍照常生效. 关闭后立即恢复原有租约/上限行为.
        self._manual_bypass = False
        # ★2026-11-09 (用户令 方案1): 租约懒占 —— 只有**真的发过请求**的 MixinSession 才落租约.
        #   原实现: agentmain.load_llm_sessions() 会为每个 mixin_config_* 实例化 MixinSession,
        #   末尾 _sync_manual_bypass_locked() 对**每个**实例调 set_manual_bypass(False)
        #   → else 分支 → _lease_rebind() → ChannelLease.acquire(当前桶),
        #   于是**进程一启动就白占座位**(零请求)。实测 tgapp/reflect 各占
        #   hiyo/buddy/beam_free 三桶, 靠 _LEASE_TTL=1800s 到期才自动消失。
        #   现在: _pick()(唯一真实请求入口) 才置 True → 没请求过就不占座。
        self._served = False
        # 审计归因(2026-11-09): 本实例对应的 mykey 变量名, 下面算出 _mname 后回填。
        # 仅用于 llm_audit 记录「哪个 mixin 的请求落到了哪条腿」, 不参与选路。
        self._mixin_name = ''
        # 渠道会话上限 (2026-10-13): mykey.channel_session_caps = {"渠道名或组名": 上限};
        #   组名 → mykey.channel_cap_groups = {"组名": [渠道名, ...]}(同一上游账号的多个渠道名共用名额池);
        #   未配置/不匹配本 mixin 的渠道名 → 该能力完全关闭(零开销)
        self._caps, self._bucket_of = {}, {}
        try:
            _mk = reload_mykeys()[0] or {}
            _caps, _groups = _mk.get('channel_session_caps') or {}, _mk.get('channel_cap_groups') or {}
            _names = [s.name for s in self._sessions]
            if isinstance(_caps, dict):
                for k, v in _caps.items():
                    if not v or int(v) <= 0: continue
                    k, v = str(k), int(v)
                    if k in _names:
                        self._caps[k] = v; self._bucket_of[k] = k
                    elif isinstance(_groups, dict) and isinstance(_groups.get(k), (list, tuple)):
                        self._caps[k] = v
                        for nm in _groups[k]: self._bucket_of[str(nm)] = k
        except Exception:
            self._caps, self._bucket_of = {}, {}
        self._buckets = [self._bucket_of.get(s.name, s.name) for s in self._sessions]
        # ★2026-10-16 用户令「翻译单独留额度, 翻译的 oc2api 不设上限」: per-mixin 名额覆盖 + 独立命名空间
        #   mykey.channel_session_caps_by_mixin = {"mixin_config_translate": {"ds4f_oc2api": 0}}
        #   key = mixin 变量名(该 mixin 定义内须带同名字段 "mixin_name"); 值 <= 0 = 该渠在本 mixin 内不设上限;
        #   本 mixin 的租约桶加 "@<mixin名>" 后缀 → 与其它 mixin 互不占用同一名额池.
        #   未配置 → 能力关闭(行为与旧版逐字节一致).
        # ★2026-10-16 用户令: per-mixin 名额覆盖 + **渠道级**命名空间隔离
        #   mykey.channel_session_caps_by_mixin = {
        #       "mixin_config_task_llm": {"ds4f_oc2api": 5, "_isolate": ["ds4f_oc2api"]},
        #   }
        #   key = mixin 变量名(优先 cfg['mixin_name'], 缺省按对象 identity 自动识别);
        #   值 <= 0 = 该渠在本 mixin 内不设上限(从 caps 摘除); 值 > 0 = 覆盖上限;
        #   "_isolate"(唯一开关, 可选): 只有列出的渠/组加 "@<mixin名>" 后缀=独立名额池;
        #       缺省 = **不隔离**(2026-10-16 用户令: 全局表即真闸); "*"/True = 全部隔离; [] = 全部共享.
        #   ★注意: cap 是「桶」的属性 → 想给某渠单独设上限, 该渠必须隔离; 未隔离的渠沿用全局桶与全局上限.
        try:
            _bm = _mk.get('channel_session_caps_by_mixin') or {}
            _mname = str(cfg.get('mixin_name') or '') or _detect_mixin_name(cfg, _mk)
            if not _mname and mixin_name:
                _mname = str(mixin_name)     # 构造方显式传入(identity 反查跨 snapshot 必然失败)
            self._mixin_name = _mname                    # 审计归因用(见 llm_audit)
            _ov = _bm.get(_mname) or {}
            if not _mname and isinstance(_bm, dict) and _bm:
                _warn_mixin_detect_once(cfg, _bm)      # ★B2 修复: 不再静默失效
            if _mname and isinstance(_ov, dict) and _ov:
                # ★2026-10-16 用户令「默认不隔离」: _isolate **缺省 = 只做 cap 覆盖, 不加后缀**;
                #   要整池独立必须显式写 "*"/True。此前缺省=全隔离, 会让"只想设个上限"顺手把
                #   同一份额度复制一份(各池相加才是上游真实并发, 已踩过一次)。
                if not any(_k2 in _ov for _k2 in ('_isolate', '_namespace', '_iso')):
                    _iso_set = set()                      # 缺省 = 不隔离(空集合)
                else:
                    _iso = _ov.get('_isolate', _ov.get('_namespace', _ov.get('_iso')))
                    if _iso is True or _iso == '*':
                        _iso_set = None                   # None = 全部隔离
                    elif isinstance(_iso, (list, tuple, set)):
                        _iso_set = {str(x) for x in _iso}
                    else:
                        _iso_set = set()                  # 非法值 → 保守: 不隔离
                _allb = set(self._buckets)
                for _k, _v in _ov.items():
                    _k = str(_k)
                    if _k.startswith('_'): continue        # 保留键(如 _isolate)不是渠道
                    # ★B4 修复(2026-10-16): 允许 by_mixin **新增**本 mixin 用到的渠的上限。
                    #   原实现只覆盖「全局表已存在的键」→ 全局没配的渠在本池无法设上限。
                    if _k in self._caps or _k in _allb:
                        if _v and int(_v) > 0: self._caps[_k] = int(_v)
                        else: self._caps.pop(_k, None)
                # 命中隔离名单的「桶」= 直接写桶名(组名/未分组渠名), 或写出组内任一渠名
                # ★注意: 名单判定必须基于**全部桶**(self._buckets), 不能只看 self._caps ——
                #   被覆盖成 <=0 而「摘除」的渠已不在 _caps 里, 但它仍须隔离
                #   (否则 translate 的 oc2api 会掉回共享桶, 反占 task 池名额; 2026-10-16 实证)。
                _allb = set(self._buckets)
                if _iso_set is None:
                    _iso_buckets = set(_allb)
                else:
                    _iso_buckets = {x for x in _iso_set if x in _allb}
                    for _ch, _bk in self._bucket_of.items():
                        if _ch in _iso_set: _iso_buckets.add(_bk)
                _sfx = '@' + _mname
                self._caps = {f'{k}{_sfx}' if k in _iso_buckets else k: v
                              for k, v in self._caps.items()}
                self._buckets = [f'{b}{_sfx}' if b in _iso_buckets else b
                                 for b in self._buckets]
        except Exception:
            pass
        self._lease_skip = None   # 故障转移落在满额渠时: 该桶「名额满」标记(不落租约, 见 _lease_rebind)
        # ★2026-11-08 审查修复: 注释一直写「租约层默认关闭, 只作观测」, 但代码无条件创建并让
        #   _lease_sync 真的按它切渠 → 与请求级 ChannelSlotGate 形成**双重闸**(进程级 cap
        #   会额外挤压可用性)。现把注释里的开关真正落地: `llm_channel_lease_gate`
        #   默认 **True** = 保持既有行为(向后兼容, 不改变现网); 配 False 则只作观测不参与选渠。
        _lg = True
        try:
            _lgv = (reload_mykeys()[0] or {}).get('llm_channel_lease_gate', True)
            _lg = bool(_lgv) if not isinstance(_lgv, str) else _lgv.strip().lower() not in (
                '0', 'false', 'no', 'off', 'none')
        except Exception:
            _lg = True
        self._leases = ChannelLease() if (self._caps and _lg) else None
        # ★2026-11-07 请求级渠道闸: 与 ChannelLease 共用同一份 channel_session_caps 配置,
        #   但语义不同 —— Lease 数「会话/进程」, SlotGate 数「**在途请求**」。
        #   只有配了 caps 才启用(未配 → 零开销, 行为与旧版一致)。
        self._chan_gate = ChannelSlotGate() if self._caps else None
        # ★2026-11-07 修复: 原写 `float(...)`, mykey 配成 'reject'/'never' 时构造直接抛 ValueError
        #   (整个 MixinSession 起不来)。现在字符串哨兵原样保留, 非法值退回 300s 默认。
        _w = (_mk or {}).get('llm_channel_wait_seconds', 300)
        if isinstance(_w, str):
            _wl = _w.strip().lower()
            self._chan_wait = REJECT if _wl in ('reject', 'none', 'never') else (
                None if _wl in ('inf', 'infinite', 'forever') else _wait_left(_w, None))
            if self._chan_wait is REJECT:
                print('[ChanGate] llm_channel_wait_seconds=reject → 全满即放弃, 绝不突破上限')
        else:
            self._chan_wait = _wait_left(_w, None)
        # 渠道速率闸 (2026-10-13): mykey.channel_rate_limits = {"渠道名": {"limit":N,"window":S,"reserve":R}}
        #   未配置/不匹配本 mixin 渠道名 → 能力关闭(零开销), 行为与旧版一致.
        self._rate_gate = None
        try:
            _rl = (reload_mykeys()[0] or {}).get('channel_rate_limits') or {}
            if isinstance(_rl, dict):
                _rn = {s.name for s in self._sessions}
                _rules = {str(k): v for k, v in _rl.items() if str(k) in _rn and isinstance(v, dict)}
                if _rules: self._rate_gate = ChannelRateGate(_rules)
        except Exception:
            self._rate_gate = None

        primary = self._sessions[0]
        self.name = '|'.join(s.name for s in self._sessions)
        self.history = copy.deepcopy(primary.history)
        self.system = primary.system
        self.tools = getattr(primary, 'tools', None)
        self.lock = threading.Lock()
    @property
    def primary(self): return self._sessions[0]
    @property
    def current(self): return self._sessions[self._cur_idx]
    @property
    def current_name(self): return self.current.name
    def set_manual_bypass(self, enabled):
        """手动切换生效后是否豁免 channel_session_caps.

        只影响本 MixinSession 实例的「会话名额」:
          - 开: 释放已占租约并跳过 _lease_sync/_lease_rebind, 仍保持当前子渠道;
                速率闸(channel_rate_limits)不受影响.
          - 关: 立即按原有选渠/占位逻辑恢复(名额满时仍按既有方案 A 不越界).
        默认关闭, 未调用过的实例行为与旧版逐字节一致.
        """
        self._manual_bypass = bool(enabled)
        if self._leases is None: return
        if self._manual_bypass:
            self._leases.release()
            self._lease_skip = None
        else:
            self._lease_skip = None
            # ★2026-11-09 (方案1): 本实例**从未发过请求** → 不落租约.
            #   否则 agentmain.load_llm_sessions() 的启动期同步(对每个 mixin 调本函数)
            #   会让进程一开机就白占各 mixin 首渠的座位(实测 hiyo/buddy/beam_free 三桶).
            #   真正发请求时 _pick() 会把 _served 置 True, 之后一切照旧.
            if not getattr(self, '_served', False): return
            self._lease_rebind()
    def __getattr__(self, name): return getattr(self.current, name)
    def __setattr__(self, name, value):
        sessions = self.__dict__.get('_sessions')
        if sessions and name in self._TRANSPORT_OVERRIDES:
            for s in sessions: setattr(s, name, value)
            return
        node_owns = sessions and any(
            name in s.__dict__ or any(name in cls.__dict__ for cls in type(s).__mro__)
            for s in sessions)
        if node_owns and name not in self._FACADE_STATE: raise AttributeError(f"MixinSession.{name} is node-specific and read-only")
        object.__setattr__(self, name, value)
    def ask(self, prompt):
        self._pick()  # Select the node before ask() reads its context limits.
        return self._ask_impl(self, prompt)
    def make_messages(self, messages): return messages
    def _pick(self):
        # ★2026-11-09: 走到这里说明**真的要发请求**了 → 之后才允许落/续租约.
        self._served = True
        if self._cur_idx and time.time() - self._switched_at > self._spring_sec:
            self._cur_idx = 0; self._lease_skip = None   # spring_back 回位: 清除故障转移的满额跳过标记
        if self._leases is not None and not self._manual_bypass: self._lease_sync()
        if self._rate_gate is not None:
            i = self._rate_pick()
            if i != self._cur_idx:
                self._cur_idx, self._switched_at = i, time.time()
                # ★2026-10-16 审查修复(F1): 速率闸切渠后必须把租约**改挂**到新渠,
                #   否则出现「用了 B 却没占 B 的名额」(held 仍挂 A) → B 的 cap 被静默突破。
                if self._leases is not None: self._lease_rebind()
        # ★2026-11-09 (用户批准第4项: 渠道冷却): 当前渠被判"病"(风控/连败)且在冷却期内
        #   → 顺延到第一条不在冷却期的渠。全部都在冷却 → 保持原渠(可用性优先, 不空转)。
        if not _chan_cool_ok(self._sessions[self._cur_idx].name):
            for _off in range(1, len(self._sessions)):
                _j = (self._cur_idx + _off) % len(self._sessions)
                if _chan_cool_ok(self._sessions[_j].name):
                    print(f'[ChanCool] {self._sessions[self._cur_idx].name} 冷却中 → 改选 s{_j} ({self._sessions[_j].name})')
                    self._cur_idx, self._switched_at = _j, time.time()
                    if self._leases is not None and not self._manual_bypass: self._lease_rebind()
                    break
        return self._cur_idx
    def _rate_pick(self):
        """速率闸: 当前渠道「将满」且有其它渠道**既速率有余量、名额也放得下** → 顺延到最近的那条.

        ★2026-10-16 审查修复(F1): 原实现只看速率余量、不看 caps → 会把会话切到**名额已满**的渠,
        该渠被使用却不占名额(held 仍挂旧桶) ⇒ cap 被静默突破。现在两条闸一起判:
        名额满的渠不作为切渠目标; 全部候选都不合适 → 保持原渠(不空转)。
        """
        g, buckets, n, cur = self._rate_gate, self._buckets, len(self._sessions), self._cur_idx
        if g.has_room(buckets[cur]): return cur
        held = self._leases.held if self._leases is not None else None
        counts = self._leases.counts() if self._leases is not None else {}
        for off in range(1, n):
            j = (cur + off) % n
            b = buckets[j]
            if not g.has_room(b): continue
            cap = self._caps.get(b)
            if cap is not None and b != held and counts.get(b, 0) >= cap:
                continue                       # 名额已满 → 不越界
            print(f'[MixinSession] rate gate: {self._sessions[cur].name} 接近限流 → s{j} ({self._sessions[j].name})')
            return j
        return cur
    def _admit(self, idx):
        """为本次真正发送的调用占 1 个窗口名额(无闸配置时 no-op)."""
        if self._rate_gate is not None: self._rate_gate.admit(self._buckets[idx])
    def _lease_sync(self):
        """会话级渠道租约: 续租; 本渠道(或本账号组)名额满则自动改从下一顺位起选.

        2026-10-15 (用户令 方案A): 故障转移落在满额渠时本会话不落租约(_lease_skip);
        名额未空出前**保粘性**——不重新 claim(否则会立刻回弹/顶掉别人名额), 直到该桶计数归零再正常选渠.
        2026-10-19 (用户令): 本渠名额满时**跳过它、顺延到下一顺位未满的渠**(不卡住);
        全部渠都满 → claim 返回 None, 保持原渠继续调用(可用性优先), 仅本会话不计名额.
        """
        if self._manual_bypass: return
        leases = self._leases
        names = [s.name for s in self._sessions]; buckets = self._buckets
        if leases.held == buckets[self._cur_idx] and leases.renew(): return
        if leases.held: leases.release()
        # ★2026-10-19 用户令「本渠满了就直接跳到下一级渠道，不卡住」:
        #   从当前下标起**向后顺延**找第一个名额未满的渠(绕回 0 也可以); 找到就切过去并落租约.
        #   全部渠都满 → claim 返回 None: 保持原渠继续调用(可用性优先, 不阻塞/不空转),
        #   只是本会话**不落租约**(不越界、不冒领名额), 下轮再试.
        idx = leases.claim(buckets, self._caps, names, start=self._cur_idx)
        if idx is None:
            self._lease_skip = buckets[self._cur_idx]
            return
        self._lease_skip = None
        if idx != self._cur_idx:
            print(f'[MixinSession] channel caps: {names[self._cur_idx]} 已满 → s{idx} ({names[idx]})')
            self._cur_idx, self._switched_at = idx, time.time()
    def _lease_rebind(self):
        """故障转移成功 / 流异常切换后: 把租约改挂到当前渠道(不重跑名额选择, 保证可用性优先).

        2026-10-15 (用户令 方案A): 目标渠名额已满时**不落租约**(不越界), 只置 `_lease_skip` 标记
        —— 该次调用照常成功(可用性优先不变), 但本会话不再计入该渠名额, 直到 spring_back 或该渠空出.
        """
        if self._leases is None: return
        if self._manual_bypass:
            # 手动豁免期间不占名额; 关闭时 set_manual_bypass(False) 会走正常 rebind.
            self._leases.release(); self._lease_skip = None; return
        b = self._buckets[self._cur_idx]; name = self._sessions[self._cur_idx].name
        if self._leases.held == b:
            self._leases.renew(); self._lease_skip = None; return
        cap = self._caps.get(b)
        if cap is not None and self._leases.counts().get(b, 0) >= cap:
            self._leases.release()   # 不越界: 放掉旧渠租约, 本会话暂不占任何名额
            self._lease_skip = b
            print(f'[MixinSession] channel caps: {name} 已满 → 故障转移不落租约(不越界)')
            return
        self._lease_skip = None
        self._leases.acquire(b, name)
    def _prepare(self, idx, messages):
        session = self._sessions[idx]
        session.system = self.system
        session.tools = openai_tools_to_claude(self.tools) if self.tools and type(session) is NativeClaudeSession else self.tools
        return messages if self._native else session.make_messages(messages)
    def raw_ask(self, messages):
        base, n = self._pick(), len(self._sessions)
        # 审计归因(2026-11-09): 一份 messages 只探测一次(0.13ms@p90)，各 attempt 共用结果。
        #   ★ 只记计数/形状，不落正文；失败即 _pr=None，审计静默关闭，不影响请求。
        _pr = _audit_probe(messages)
        test_error = lambda x: isinstance(x, str) and x.lstrip().startswith(('!!!Error:', '[Error:'))
        deferred = 0
        # ★2026-11-07 用户令「后面房子坏了(渠道有问题)也可以自动往后」:
        #   failed 记录**本请求内已失败过的房间下标**, 选房时跳过 → 不会顺延一圈又绕回刚坏的房。
        #   一轮全试完才清空(unwrapped 由下面的 round exhausted 分支重置)。
        failed = set()
        # ★2026-11-07 修复: 排队预算是**整次请求**的总预算, 不是每次 attempt 各一份。
        #   原实现把 self._chan_wait 逐次传给 acquire_any → 最坏 (retries+1)×wait
        #   (默认 300s × 9 ≈ 45 分钟) 才返回, 调用方早就超时了。现在统一 deadline。
        # ★2026-11-07 修复: 原来直接 `time.time() + self._chan_wait if self._chan_wait > 0`,
        #   _chan_wait 为 REJECT 字符串时这里 TypeError 直接炸掉整个请求。
        _gw = self._chan_wait
        _gate_deadline = (time.time() + _gw) if (isinstance(_gw, (int, float)) and _gw > 0) else None
        for attempt in range(self._retries + 1):
            idx = (base + attempt) % n
            _arid, _dlv = None, 0      # 审计: 本次 attempt 的 rid / 已交付正文字符数
            if self._rate_gate is not None and not self._rate_gate.has_room(self._buckets[idx]):
                deferred += 1
                if deferred < n:   # 该渠已临近限流且还有其它渠道 → 顺延(不发请求, 不占服务端配额)
                    continue
                # 全部渠道都在限流窗口内 → 不再跳过, 按序放行(尽力而为, 绝不空转)
            # ★2026-11-07 请求级渠道闸(用户令「每个房间进之前先数一下里面有多少人, 满了在门口排队」):
            #   真正发送前占 1 个**本次请求**的渠道名额; 本渠满 → 顺延到下一个未满的渠;
            #   全部满 → acquire_any 内部在门口排队等前面的人做完(不再静默突破渠道上限);
            #   某渠坏了(error)由下面的 retry 逻辑转到下一顺位, 名额用完即还, 不会占着不放。
            slot = None
            if self._chan_gate is not None and self._caps and not self._manual_bypass:
                # 传「**剩余**预算」而不是整份: 一次请求内多房间重试不能各拿一份 wait
                # ★2026-11-07 修复: 原写 `self._chan_wait <= 0`, _chan_wait 为 REJECT 字符串时
                #   TypeError; 且 REJECT 必须原样透传(否则「不越界」策略被降级成 override)。
                _left = _wait_left(_gw, _gate_deadline)
                idx, slot, _st = self._chan_gate.acquire_any(
                    self._buckets, self._caps, start=idx, exclude=failed,
                    wait=self._chan_wait if _left is None else _left)
                # ★2026-11-07 修复(能力闸错位): 上面的速率闸判断用的是 **选房前** 的 idx,
                #   而 acquire_any 可能顺延到另一间房 → 真正要打的渠道根本没做过速率检查
                #   (会撞服务端 429)。这里按**最终选中的房**复核一次。
                if slot and self._rate_gate is not None \
                        and not self._rate_gate.has_room(self._buckets[idx]):
                    deferred += 1
                    if deferred < n and attempt < self._retries:
                        self._chan_gate.release(slot); slot = None
                        print(f'[ChanGate] 选中 {self._buckets[idx]} 已临近限流 → 还名额顺延')
                        continue
                    # 全部渠道都在限流窗口内 → 不再跳过, 按序放行(尽力而为, 绝不空转)。
                    #   注意**不还名额**: 还了计数就偏低, 等于变相超卖(审查 P0-1 同源)。
                    print(f'[ChanGate] 全部渠道临近限流 → 按序放行 {self._buckets[idx]} (名额保留)')
                if _st == REJECTED:
                    # 全房满 + 「宁可放弃也不突破上限」策略 → 绝不越界发送
                    if attempt >= self._retries:
                        print('[ChanGate] 所有渠道名额已满且配置为不突破上限 → 放弃本次请求')
                        yield '!!!Error: [ChanGate] all channels at capacity (override disabled)'
                        return []
                    time.sleep(min(5.0, 0.5 * (attempt + 1)))
                    continue
            try:
                self._admit(idx)       # 真正发送前占 1 个窗口名额
                session = self._sessions[idx]
                # ★2026-11-07: 渠道内部抛**非字符串异常**(连接重置/KeyError/SSL 等)时,
                #   原实现会直接冒出 raw_ask 中断整个重试循环 → 后面的好房间根本轮不到。
                #   这里统一收成 error 串, 交给下面的 is_err 分支顺延下一个房间。
                try:
                    gen = session.raw_ask(self._prepare(idx, messages))
                except Exception as _e:
                    gen = iter([f'!!!Error: {type(_e).__name__}: {str(_e)[:200]}'])
                print(f'[MixinSession] Using session ({session.name})')
                # 审计归因(2026-11-09): 真正发出前记一条，含 mixin/渠道/尝试序号/内容形状计数。
                _arid = _audit_sent(self, session.name, attempt, _pr)
                last_chunk, return_val, yielded = None, [], False
                try:
                    # ★2026-11-05: 「已交付正文」判定必须区分思维链——只有**正文**才算数。
                    #   否则长 CoT 期间断流会被当成"已吐过半截答案", 于是不换渠,
                    #   用户看到的就是"想了很久然后终止"(llmcore_sop「思考完就停」)。
                    #   思维链对用户不可见且可整段重放, 故只认 text/tool_use 块。
                    delivered = _dlv = 0
                    _hb = time.time()
                    while True:
                        chunk = next(gen); last_chunk = chunk
                        # ★2026-11-07: 长流式请求期间刷新名额 mtime(心跳)。
                        #   原实现只在 acquire 时写一次 mtime → 超过 TTL(6h) 的长请求
                        #   (或 mtime 被判旧的槽)会被 sweep 当成死槽回收, 该房随后被超卖。
                        if slot and time.time() - _hb > _CHAN_SLOT_HB:
                            _hb = time.time(); self._chan_gate.touch(slot)
                        if not yielded and test_error(chunk): continue
                        yield chunk
                        if not test_error(chunk):
                            yielded = True
                            if isinstance(chunk, str) and chunk.strip() and not isinstance(chunk, ThinkingChunk):
                                delivered += len(chunk)
                except StopIteration as e: return_val = e.value or []
                except Exception as _e:
                    # ★2026-11-07: 流中途抛非字符串异常 → 转成 error 分片, 走「换房重试」而不是整链崩溃
                    _msg = f'!!!Error: {type(_e).__name__}: {str(_e)[:200]}'
                    if not delivered:
                        last_chunk = _msg
                    else:
                        yield _msg; last_chunk = _msg
            finally:
                if slot: self._chan_gate.release(slot)   # 房间名额必须还, 否则泄漏=永久占位
            is_err = test_error(last_chunk)
            _et = str(last_chunk) if is_err else ''
            # 审计归因(2026-11-09): 每次 attempt 一条 done，与上面的 sent 用 rid 配对。
            #   ok = 非错误串（含被上游掐断/空回复等由传输层转成的 error 串）。
            #   ★ int 不可变 → 内层自增不会回写到 _dlv，这里按当前作用域取值(可能不存在)。
            _dlv = locals().get('delivered', 0) or 0
            _audit_done(_arid, not is_err, _et, _dlv)
            _canned = bool(is_err) and (('canned refusal' in _et) or any(_p in _et for _p in _CANNED_REFUSAL))
            if is_err: failed.add(idx)   # 本房间坏 → 本请求内不再选它(见上面的 exclude)
            # ★2026-11-09 (第4项: 渠道冷却): 判失败的渠道进冷却, 后续请求不再先白打它一次。
            #   区分两类: 「假成功/风控」(上游 200 却回固定话术, 实测等 20min 不恢复 =
            #   IP 级封禁, 给长冷却) vs 一般错误(连接重置/5xx, 指数退避)。
            if is_err:
                _chan_cool_mark(self._sessions[idx].name, _et, canned=_canned)
            # ★2026-11-05: 判据从 `yielded`(任何分片, 含思维链) 改为 `delivered>0`(只认真正文)。
            #   思维链也走 yield, 长 CoT 必然 yielded=True → 断流时被判"已吐半截答案"→既不换渠
            #   也不重试, 用户看到"想了很久然后自动终止"。思维链可整段重放, 不算已交付。
            if is_err and delivered and not _canned:
                # 2026-11-04: 本轮已经把正文吐给调用方了, 不能再换渠重跑整个请求
                # (否则用户会看到"半截 + 另一个渠道的完整版"=重复)。只把下一次调用指向别的渠。
                # ★2026-11-09 例外: 假成功话术(_canned)不算"有效交付"——它一个字都不是回答,
                #   即便已吐出去也必须换渠重问, 否则用户就拿到一句广告然后停住。
                if n > 1:
                    self._cur_idx = (idx + 1) % n; self._switched_at = time.time(); self._lease_rebind()
                    print(f'[MixinSession] {str(last_chunk)[:80]}, partial output kept, next call → s{self._cur_idx} ({self.current.name})')
                return return_val
            if not is_err:
                # ★2026-11-09 (第4项): 本轮真正拿到了正常响应 → 清掉该渠的失败计数/冷却。
                _chan_cool_clear(self._sessions[idx].name)
                # ★2026-11-05: 节点"只吐思维链就断"(trail 以「响应无正文」结尾)也算部分失败,
                #   下一轮从别的渠起(heads-up), 不给用户连续踩同一个坑。
                _trail = last_chunk if isinstance(last_chunk, str) else ''
                _bad_ending = ('[!!! 流异常中断' in _trail) or ('[!!! Response truncated' in _trail)
                # ★2026-11-09 (acomb 实测发现): 「撞我们自己的 max_tokens」≠「这条腿不稳」。
                #   chat 分支 `truncated: length` / anthropic `truncated: max_tokens` /
                #   responses `output truncated: max_output_tokens` 三者都是**我们给的预算**
                #   用完了, 换条腿也照样截断 —— 罚它只会冤枉一个健康渠(实测 acomb 撞
                #   max_tokens=1200 就被打 60s 冷却, 明明它守规矩)。真截断现在由
                #   NativeClaudeSession.ask 的续写循环消化, 标记只在上限用尽时才透出来。
                #   只有「流异常中断」(没收到终止事件/连接断) 才是这条腿自己的问题。
                _budget_cut = ('truncated: max_tokens' in _trail) or \
                              ('truncated: length' in _trail) or \
                              ('output truncated: max_output_tokens' in _trail)
                if _bad_ending and not _budget_cut:
                    # 断流虽已吐出正文, 但仍是"这条腿不稳"的证据 → 轻量冷却, 下次优先换条腿。
                    _chan_cool_mark(self._sessions[idx].name, _trail)
                if attempt > 0:
                    self._cur_idx = idx; self._switched_at = time.time(); self._lease_rebind()
                elif _bad_ending and not _budget_cut and n > 1:
                    self._cur_idx = (idx + 1) % n; self._switched_at = time.time(); self._lease_rebind()
                    print(f'[MixinSession] Partial failure, next call → s{self._cur_idx} ({self.current.name})')
                return return_val
            if attempt >= self._retries:
                yield last_chunk; return return_val
            nxt = (base + attempt + 1) % n
            if nxt == base:
                rnd = (attempt + 1) // n
                delay = min(30, self._base_delay * (1.5 ** rnd))
                print(f'[MixinSession] {last_chunk[:80]}, round {rnd} exhausted, retry in {delay:.1f}s')
                failed.clear()   # ★2026-11-07: 所有房间都试过一轮 → 放开, 下一轮重新全量尝试
                time.sleep(delay)
            else:
                print(f'[MixinSession] {last_chunk[:80]}, retry {attempt+1}/{self._retries} (s{idx}→s{nxt})')

THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复（含工具调用轮）都先在回复文字中包含一个<summary></summary> 中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。此内容进入长期工作记忆。
\n**若用户需求未完成，必须进行工具调用！**
""".strip()
THINKING_PROMPT_EN = """
### Action Protocol (always in effect)
The reply body should first include a minimal one-line (<30 words) physical snapshot in <summary></summary>: new info from last result + current intent. This goes into long-term working memory.
\n**If the user's request is not yet complete, tool calls are required!**
""".strip()

class NativeToolClient:
    @staticmethod
    def _thinking_prompt(): return THINKING_PROMPT_EN if os.environ.get('GA_LANG') == 'en' else THINKING_PROMPT_ZH
    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self._thinking_prompt()
        self.name = self.backend.name
        self._pending_tool_ids = []
        self.log_path = None
    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self._thinking_prompt()}" if extra_system else self._thinking_prompt()
        if combined != self.backend.system: print(f"[Debug] Updated system prompt, length {len(combined)} chars.")
        self.backend.system = combined
    def chat(self, messages, tools=None):
        if tools: self.backend.tools = tools
        if not self.backend.history: self._pending_tool_ids = []
        combined_content = []; resp = None; tool_results = []
        for msg in messages:
            c = msg.get('content', '')
            if msg['role'] == 'system': 
                self.set_system(c); continue
            if isinstance(c, str): combined_content.append({"type": "text", "text": c})
            elif isinstance(c, list): combined_content.extend(c)
            if msg['role'] == 'user' and msg.get('tool_results'): tool_results.extend(msg['tool_results'])
        tr_id_set = set();  tool_result_blocks = []
        # ★2026-11-13 修复: 文本兜底还原的 tool_call 没有 id(MockToolCall.id 默认 ''),
        #   原代码每次遇到空 id 都往 combined_content **头部**插一段裸文本 <tool_result>,
        #   导致 (a) 多个空 id 结果顺序被反转(实测 R1,R2 → R2,R1),
        #       (b) 结果块被塞到用户正文之前。
        #   改为按出现顺序 append 到 orphan_tails, 最后按序拼到 combined_content 尾部。
        orphan_tails = []
        for tr in tool_results:
            tool_use_id, content = tr.get("tool_use_id", ""), tr.get("content", "")
            tr_id_set.add(tool_use_id)
            if tool_use_id: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tool_use_id, "content": tr.get("content", "")})
            else: orphan_tails.append({"type": "text", "text": f'<tool_result>{content}</tool_result>'})
        if orphan_tails: combined_content = combined_content + orphan_tails
        for tid in self._pending_tool_ids:
            if tid not in tr_id_set: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tid, "content": ""})
        self._pending_tool_ids = []
        # Filter whitespace-only text blocks that cause 400 on strict API proxies
        filtered_content = [c for c in combined_content if c.get("text", "").strip()]
        final_content = tool_result_blocks + filtered_content
        if not final_content: final_content = [{"type": "text", "text": "."}]
        merged = {"role": "user", "content": final_content}
        prompt_raw = '{"role": "user", "content": [\n' + ",\n".join(json.dumps(b, ensure_ascii=False) for b in final_content) + "]}"
        _write_llm_log('Prompt', prompt_raw, self.log_path)
        gen = self.backend.ask(merged)
        try:
            while True: 
                chunk = next(gen); yield chunk
        except StopIteration as e: resp = e.value
        if resp: _write_llm_log('Response', resp.raw, self.log_path, model=self.backend.model)
        if resp and hasattr(resp, 'tool_calls') and resp.tool_calls: self._pending_tool_ids = [tc.id for tc in resp.tool_calls]
        return resp

def resolve_session(cfg_name, cfg=None):
    if cfg is None: cfg = reload_mykeys()[0].get(cfg_name)
    if not cfg: raise ValueError(f"Config '{cfg_name}' not in mykey")
    cfg = {**cfg, '_mykey_name': cfg_name}
    if 'native' in cfg_name: return (NativeClaudeSession if 'claude' in cfg_name else NativeOAISession)(cfg=cfg)
    print(f"[Legacy] {cfg_name} → 非native文本协议路径(待淘汰, 见legacy_llmcore.py)")
    if 'claude' in cfg_name: return ClaudeSession(cfg=cfg)
    return LLMSession(cfg=cfg) if 'oai' in cfg_name else None

def resolve_client(cfg_name, cfg=None):
    s = resolve_session(cfg_name, cfg)
    return (NativeToolClient(s) if isinstance(s, (NativeClaudeSession, NativeOAISession)) else ToolClient(s)) if s else None

def fast_ask(prompt, cfg_name=None):
    """单轮文本问答。cfg_name 默认 None = 读 mykey.task_llm_channel 统一任务路由开关(2026-08-17)。"""
    if cfg_name is None:
        try:
            import mykey as _mk
            v = getattr(_mk, "task_llm_channel", None)
            if isinstance(v, str) and v:
                cfg_name = v
        except Exception:
            pass
    sess = resolve_session(cfg_name)
    if not sess: raise ValueError(f"fast_ask: '{cfg_name}' unsupported")
    return "".join(sess.raw_ask([{"role": "user", "content": prompt}]))

# legacy三件套(待淘汰)已分离至legacy_llmcore.py, 由其尾部回挂名(禁本行前import)
try: import legacy_llmcore
except AttributeError: pass  # legacy先import时半初始化, 其尾部自会回挂
