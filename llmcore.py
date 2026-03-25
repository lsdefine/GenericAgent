import os, json, re, time, requests, sys, threading, urllib3, base64, mimetypes
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def _load_mykeys():
    try:
        import mykey; return {k: v for k, v in vars(mykey).items() if not k.startswith('_')}
    except ImportError: pass
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mykey.json')
    if not os.path.exists(p): raise Exception('[ERROR] mykey.py or mykey.json not found, please create one from mykey_template.')
    with open(p, encoding='utf-8') as f: return json.load(f)

mykeys = _load_mykeys()
proxy = mykeys.get("proxy", 'http://127.0.0.1:2082')
proxies = {"http": proxy, "https": proxy} if proxy else None

def compress_history_tags(messages, keep_recent=10, max_len=1000):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages to save tokens.
    Supports both prompt-style (ClaudeSession/LLMSession) and content-style (NativeClaudeSession) messages."""
    compress_history_tags._cd = getattr(compress_history_tags, '_cd', 0) + 1
    if compress_history_tags._cd % 5 != 0: return messages
    _pats = {tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)') for tag in ('thinking', 'tool_use', 'tool_result')}
    def _trunc(text):
        for pat in _pats.values(): text = pat.sub(lambda m: m.group(1) + m.group(2)[:max_len] + '...' + m.group(3) if len(m.group(2)) > max_len else m.group(0), text)
        return text
    for i, msg in enumerate(messages):
        if i >= len(messages) - keep_recent: break
        if 'prompt' in msg and 'orig' not in msg:
            msg['orig'] = msg['prompt']
            msg['prompt'] = _trunc(msg['prompt'])
        elif 'content' in msg and 'prompt' not in msg:
            c = msg['content']
            if isinstance(c, str): msg['content'] = _trunc(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
                        block['text'] = _trunc(block['text'])
    return messages

def auto_make_url(base, path):
    b, p = base.rstrip('/'), path.strip('/')
    if b.endswith('$'): return b[:-1].rstrip('/')
    return b if b.endswith(p) else f"{b}/{p}" if re.search(r'/v\d+$', b) else f"{b}/v1/{p}"

def build_multimodal_content(prompt_text, image_paths):
    parts = []
    text = prompt_text if isinstance(prompt_text, str) else str(prompt_text or "")
    if text.strip():
        parts.append({"type": "text", "text": text})
    else:
        parts.append({"type": "text", "text": "请查看图片并理解用户意图。"})
    for path in image_paths or []:
        if not path or not os.path.isfile(path): continue
        try:
            mime = mimetypes.guess_type(path)[0] or "image/png"
            if not mime.startswith("image/"): mime = "image/png"
            with open(path, "rb") as f:
                data_url = f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"
            parts.append({"type": "image_url", "image_url": {"url": data_url}})
        except Exception as e:
            print(f"[WARN] encode image failed {path}: {e}")
    return parts

class SiderLLMSession:
    def __init__(self, cfg):
        from sider_ai_api import Session   # 不使用sider的话没必要安装这个包
        self._core = Session(cookie=cfg['apikey'], proxies=proxies)   
        self.default_model = cfg.get('model', 'gemini-3.0-flash')
    def ask(self, prompt, model=None, stream=False):
        if model is None: model = self.default_model
        if len(prompt) > 28000: 
            print(f"[Warn] Prompt too long ({len(prompt)} chars), truncating.")
            prompt = prompt[-28000:]
        full_text = self._core.chat(prompt, model, stream=False)
        if stream: return iter([full_text])   # gen有奇怪的空回复或死循环行为，sider足够快
        return full_text   

class ClaudeSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']; self.api_base = cfg['apibase'].rstrip('/')
        self.default_model = cfg.get('model', 'claude-opus')
        self.context_win = cfg.get('context_win', 18000)
        self.raw_msgs, self.lock = [], threading.Lock()
        self.prompt_cache = cfg.get('prompt_cache', False)
    def _trim_messages(self, messages):
        compress_history_tags(messages)
        total = sum(len(m['prompt']) for m in messages)
        if total <= self.context_win * 3: return messages
        target, current, result = self.context_win * 3 * 0.6, 0, []
        for msg in reversed(messages):
            if (msg_len := len(msg['prompt'])) + current <= target:
                result.append(msg); current += msg_len
            else: break
        if current > self.context_win * 2.7: print(f'[DEBUG] {len(result)} contexts, whole length {current//3} tokens.')
        return result[::-1] or messages[-2:]
    def raw_ask(self, messages, model=None, temperature=0.5, max_tokens=6144):
        model = model or self.default_model
        if 'kimi' in model.lower() or 'moonshot' in model.lower(): temperature = 1.0  # kimi/moonshot only accepts temp 1.0
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01", "anthropic-beta": "prompt-caching-2024-07-31"}
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
        try:
            with requests.post(auto_make_url(self.api_base, "messages"), headers=headers, json=payload, stream=True, timeout=(5,30)) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line: continue
                    line = line.decode("utf-8") if isinstance(line, bytes) else line
                    if not line.startswith("data:"): continue
                    data = line[5:].lstrip()
                    if data == "[DONE]": break
                    try:
                        obj = json.loads(data)
                        if obj.get("type") == "message_start":
                            usage = obj.get("message", {}).get("usage", {})
                            ci, cr, inp = usage.get("cache_creation_input_tokens", 0), usage.get("cache_read_input_tokens", 0), usage.get("input_tokens", 0)
                            print(f"[Cache] input={inp} creation={ci} read={cr}")
                        elif obj.get("type") == "content_block_delta" and obj.get("delta", {}).get("type") == "text_delta":
                            text = obj["delta"].get("text", "")
                            if text: yield text
                    except: pass
        except Exception as e: yield f"Error: {str(e)}"
    def make_messages(self, raw_list):
        trimmed = self._trim_messages(raw_list)
        msgs = [{"role": m['role'], "content": [{"type": "text", "text": m['prompt']}] if m['role'] == "assistant" else m['prompt']} for m in trimmed]
        for i in range(len(msgs)-1, -1, -1):
            if msgs[i]["role"] == "assistant":
                msgs[i]["content"][-1]["cache_control"] = {"type": "ephemeral"}
                break
        return msgs
    def ask(self, prompt, model=None, stream=False):
        def _ask_gen():
            content = ''
            with self.lock:
                self.raw_msgs.append({"role": "user", "prompt": prompt})
                messages = self.make_messages(self.raw_msgs)
            for chunk in self.raw_ask(messages, model):
                content += chunk; yield chunk
            if not content.startswith("Error:"): self.raw_msgs.append({"role": "assistant", "prompt": content})
        return _ask_gen() if stream else ''.join(list(_ask_gen()))

class LLMSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']; self.api_base = cfg['apibase'].rstrip('/')
        self.default_model = cfg['model']
        self.context_win = cfg.get('context_win', 18000)
        self.raw_msgs, self.messages = [], []
        proxy = cfg.get('proxy')
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.prompt_cache = cfg.get('prompt_cache', False)
        self.lock = threading.Lock()
        self.max_retries = max(0, int(cfg.get('max_retries', 2)))
        self.connect_timeout = max(1, int(cfg.get('connect_timeout', 10)))
        self.read_timeout = max(5, int(cfg.get('read_timeout', 120)))
        effort = cfg.get('reasoning_effort')
        effort = None if effort is None else str(effort).strip().lower()
        self.reasoning_effort = effort if effort in ['none', 'minimal','low', 'medium', 'high', 'xhigh'] else None
        if effort and self.reasoning_effort is None: print(f"[WARN] Invalid reasoning_effort {effort!r}, ignored.")
        mode = str(cfg.get('api_mode', 'chat_completions')).strip().lower().replace('-', '_')
        if mode in ["responses", "response"]: self.api_mode = "responses"
        else: self.api_mode = "chat_completions"

    def _retry_delay(self, resp, attempt):
        retry_after = None
        try:
            if resp is not None: retry_after = (resp.headers or {}).get("retry-after")
            if retry_after is not None: retry_after = float(retry_after)
        except: retry_after = None
        if retry_after is None: retry_after = min(30.0, 1.5 * (2 ** attempt))
        return max(0.5, float(retry_after))

    def _to_responses_input(self, messages):
        result = []
        for msg in messages:
            role = str(msg.get("role", "user")).lower()
            if role not in ["user", "assistant", "system", "developer"]: role = "user"
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
            if len(parts) == 0: parts = [{"type": text_type, "text": str(content)}]
            result.append({"role": role, "content": parts})
        return result

    def raw_ask(self, messages, model=None, temperature=0.5):
        if model is None: model = self.default_model
        if 'kimi' in model.lower() or 'moonshot' in model.lower(): temperature = 1.0  # kimi/moonshot only accepts temp 1.0
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_mode == "responses":
            url = auto_make_url(self.api_base, "responses")
            payload = {"model": model, "input": self._to_responses_input(messages), "temperature": temperature, "stream": True}
            if self.reasoning_effort: payload["reasoning"] = {"effort": self.reasoning_effort}
        else:
            url = auto_make_url(self.api_base, "chat/completions")
            payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
            if self.reasoning_effort: payload["reasoning_effort"] = self.reasoning_effort
        for attempt in range(self.max_retries + 1):
            streamed_any = False
            try:
                with requests.post(url, headers=headers, json=payload, stream=True,
                                   timeout=(self.connect_timeout, self.read_timeout), proxies=self.proxies) as r:
                    if r.status_code >= 400:
                        retryable = r.status_code in [408, 409, 425, 429, 500, 502, 503, 504]
                        if retryable and attempt < self.max_retries:
                            delay = self._retry_delay(r, attempt)
                            print(f"[LLM Retry] HTTP {r.status_code}, retry in {delay:.1f}s ({attempt+1}/{self.max_retries+1})")
                            time.sleep(delay)
                            continue
                    r.raise_for_status()
                    buffer = ''; seen_delta = False
                    for line in r.iter_lines():
                        line = line.decode("utf-8") if isinstance(line, bytes) else line
                        if not line or not line.startswith("data:"): continue
                        data = line[5:].lstrip()
                        if data == "[DONE]": break
                        try: obj = json.loads(data)
                        except: continue
                        if self.api_mode == "responses":
                            etype = obj.get("type", "")
                            delta = obj.get("delta", "") if etype == "response.output_text.delta" else ""
                            if delta:
                                streamed_any = True; seen_delta = True
                                yield delta; buffer += delta
                            elif etype == "response.output_text.done" and not seen_delta:
                                text = obj.get("text", "")
                                if text:
                                    streamed_any = True
                                    yield text; buffer += text
                            elif etype == "error":
                                err = obj.get("error", {})
                                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                                if emsg:
                                    yield f"Error: {emsg}"
                                    return
                            elif etype == "response.completed":
                                break
                        else:
                            ch = (obj.get("choices") or [{}])[0]
                            finish_reason = ch.get("finish_reason")
                            delta = (ch.get("delta") or {}).get("content")
                            if delta:
                                streamed_any = True
                                yield delta; buffer += delta
                            if finish_reason: break
                        #if '</tool_use>' in buffer[-30:]: break
                    return
            except requests.HTTPError as e:
                resp = getattr(e, "response", None)
                status = getattr(resp, "status_code", "unknown")
                retryable = isinstance(status, int) and status in [408, 409, 425, 429, 500, 502, 503, 504]
                if retryable and attempt < self.max_retries and not streamed_any:
                    delay = self._retry_delay(resp, attempt)
                    print(f"[LLM Retry] HTTP {status}, retry in {delay:.1f}s ({attempt+1}/{self.max_retries+1})")
                    time.sleep(delay)
                    continue
                body = ""
                try: body = (resp.text or "").strip()
                except: body = ""
                body = body[:1200] if body else "<empty>"
                rid = ""; retry_after = ""; ct = ""
                try:
                    h = resp.headers or {}
                    rid = h.get("x-request-id") or h.get("request-id") or ""
                    retry_after = h.get("retry-after") or ""
                    ct = h.get("content-type") or ""
                except: pass
                yield f"Error: HTTP {status} {str(e)}; content_type: {ct or '<empty>'}; retry_after: {retry_after or '<empty>'}; request_id: {rid or '<empty>'}; body: {body}"
                return
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < self.max_retries and not streamed_any:
                    delay = self._retry_delay(None, attempt)
                    print(f"[LLM Retry] {type(e).__name__}, retry in {delay:.1f}s ({attempt+1}/{self.max_retries+1})")
                    time.sleep(delay)
                    continue
                yield f"Error: {type(e).__name__}: {str(e)}"
                return
            except Exception as e:
                yield f"Error: {str(e)}"
                return

    def make_messages(self, raw_list, omit_images=True):
        compress_history_tags(raw_list)
        messages = []
        for i, msg in enumerate(raw_list):
            prompt = msg['prompt']
            image = msg.get('image')
            if omit_images and image: messages.append({"role": msg['role'], "content": "[Image omitted, if you needed it, ask me]\n" + prompt})
            elif not omit_images and image:
                messages.append({"role": msg['role'], "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}},
                    {"type": "text", "text": prompt} ]})
            else:
                messages.append({"role": msg['role'], "content": prompt})
        return messages
       
    def summary_history(self, model=None):
        if model is None: model = self.default_model
        with self.lock:
            keep = 0; tok = 0
            for m in reversed(self.raw_msgs):
                l = len(str(m))//3
                if tok + l > self.context_win*0.2: break
                tok += l; keep += 1
            keep = max(2, keep)
            old, self.raw_msgs = self.raw_msgs[:-keep], self.raw_msgs[-keep:]
            if len(old) == 0: old = self.raw_msgs; self.raw_msgs = []
            p = "Summarize prev summary and prev conversations into compact memory (facts/decisions/constraints/open questions). Do NOT restate long schemas. The new summary should less than 1000 tokens. Permit dropping non-important things.\n"
            messages = self.make_messages(old, omit_images=True)
            messages += [{"role":"user", "content":p}]
            msg_lens = [1000 if isinstance(m["content"], list) else len(str(m["content"]))//3 for m in messages]
            summary = ''.join(list(self.raw_ask(messages, model, temperature=0.1)))
            print('[Debug] Summary length:', len(summary)//3, '; Orig context lengths:', str(msg_lens))
            if not summary.startswith("Error:"): 
                self.raw_msgs.insert(0, {"role":"assistant", "prompt":"Prev summary:\n"+summary, "image":None})
            else: self.raw_msgs = old + self.raw_msgs   # 不做了，下次再做

    def ask(self, prompt, model=None, image_base64=None, stream=False):
        if model is None: model = self.default_model
        def _ask_gen():
            content = ''
            with self.lock:
                self.raw_msgs.append({"role": "user", "prompt": prompt, "image": image_base64})
                messages = self.make_messages(self.raw_msgs[:-1], omit_images=True)
                messages += self.make_messages([self.raw_msgs[-1]], omit_images=False)
                msg_lens = [1000 if isinstance(m["content"], list) else len(str(m["content"]))//3 for m in messages]
                total_len = sum(msg_lens)   # estimate token count
            gen = self.raw_ask(messages, model)
            for chunk in gen:
                content += chunk; yield chunk
            if not content.startswith("Error:"):
                self.raw_msgs.append({"role": "assistant", "prompt": content, "image": None})
            if total_len > self.context_win // 2: print(f"[Debug] Whole context length {total_len} {str(msg_lens)}.")
            if total_len > self.context_win: 
                yield '[NextWillSummary]'
                threading.Thread(target=self.summary_history, daemon=True).start()
        if stream: return _ask_gen()
        return ''.join(list(_ask_gen())) 
        
  
class GeminiSession:
    def __init__(self, cfg):
        self.api_key = cfg.get('apikey')
        if not self.api_key: raise ValueError("google_api_key 未配置或为空，请在 mykey.py 中设置")
        self.default_model = cfg.get('model', 'gemini-2.0-flash-001')
        p = cfg.get('proxy', proxy)
        self.proxies = {"http":p, "https":p} if p else None
    def ask(self, prompt, model=None, stream=False):
        if model is None: model = self.default_model
        url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={self.api_key}"
        headers = {"Content-Type":"application/json"}
        data = {"contents":[{"role":"user","parts":[{"text":prompt}]}]}
        try:
            kw = {"headers":headers, "json":data, "timeout":60, 'proxies': self.proxies}
            r = requests.post(url, **kw)
        except Exception as e:
            return f"[GeminiError] request failed: {e}"
        if r.status_code != 200:
            body = r.text[:500].replace("\n"," ")
            return f"[GeminiError] HTTP {r.status_code}: {body}"
        try:
            obj = r.json(); cands = obj.get("candidates") or []
            if not cands: return "[GeminiError] empty candidates"
            parts = (cands[0].get("content") or {}).get("parts") or []
            full_text = "".join(p.get("text","") for p in parts)
        except Exception as e:
            return f"[GeminiError] invalid response format: {e}"
        return iter([full_text]) if stream else full_text

class XaiSession:
    def __init__(self, cfg):
        import xai_sdk
        from xai_sdk.chat import user, system
        self._user, self._system = user, system
        self.default_model = cfg.get('model', 'grok-4-1-fast-non-reasoning')
        self._last_response_id = None  # 多轮对话链
        os.environ["XAI_API_KEY"] = cfg['apikey']
        proxy = cfg.get('proxy', 'http://127.0.0.1:2082')
        if not proxy.startswith("http"): proxy = f"http://{proxy}"
        os.environ.setdefault("grpc_proxy", proxy)
        self._client = xai_sdk.Client()
    def ask(self, prompt, model=None, system_prompt=None, stream=False):
        """发送消息，自动串联多轮对话；stream=True返回生成器"""
        mdl = model or self.default_model
        try:
            kw = dict(model=mdl, store_messages=True)
            if self._last_response_id: kw["previous_response_id"] = self._last_response_id
            chat = self._client.chat.create(**kw)
            if system_prompt: chat.append(self._system(system_prompt))
            chat.append(self._user(prompt))
            if stream: return self._stream(chat)
            resp = chat.sample()
            self._last_response_id = resp.id
            return resp.content
        except Exception as e:
            err = f"[XaiError] {e}"
            return iter([err]) if stream else err
    def _stream(self, chat):
        try:
            last_resp = None
            for resp, chunk in chat.stream():
                last_resp = resp
                if chunk and chunk.content: yield chunk.content
            if last_resp and hasattr(last_resp, 'id'): self._last_response_id = last_resp.id
        except Exception as e:
            yield f"[XaiError] {e}"
    def reset(self): self._last_response_id = None


class NativeOAISession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']; self.api_base = cfg['apibase'].rstrip('/')
        self.default_model = cfg.get('model', 'gpt-4o')
        self.context_win = cfg.get('context_win', 28000)
        proxy = cfg.get('proxy')
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.history = []; self.system = None; self.lock = threading.Lock()
    def set_system(self, system_text): self.system = system_text

    def raw_ask(self, messages, tools=None, system=None, model=None, temperature=0.5, max_tokens=6144, **kw):
        """OpenAI streaming. yields text chunks, generator return = list[content_block]"""
        model = model or self.default_model
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
        if tools: payload["tools"] = tools
        try:
            resp = requests.post(auto_make_url(self.api_base, "chat/completions"), headers=headers, json=payload, stream=True, timeout=120, proxies=self.proxies)
            if resp.status_code != 200:
                err = f"Error: HTTP {resp.status_code} {resp.text[:500]}"; yield err; return [{"type": "text", "text": err}]
        except Exception as e:
            err = f"Error: {e}"; yield err; return [{"type": "text", "text": err}]
        content_text = ""; tc_buf = {}  # index -> {id, name, args_str}
        for line in resp.iter_lines():
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data: "): continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]": break
            try: evt = json.loads(data_str)
            except: continue
            delta = evt.get("choices", [{}])[0].get("delta", {})
            if delta.get("content"):
                text = delta["content"]; content_text += text; yield text
            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                if idx not in tc_buf: tc_buf[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
                if tc.get("function", {}).get("name"): tc_buf[idx]["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"): tc_buf[idx]["args"] += tc["function"]["arguments"]
        blocks = []
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(tc_buf):
            tc = tc_buf[idx]
            try: inp = json.loads(tc["args"]) if tc["args"] else {}
            except: inp = {"_raw": tc["args"]}
            blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": inp})
        return blocks

    def ask(self, msg, tools=None, model=None, **kw):
        """Managed ask with history. yields text chunks, return MockResponse"""
        if isinstance(msg, str): msg = {"role": "user", "content": msg}
        elif isinstance(msg, list): msg = {"role": "user", "content": msg}
        with self.lock:
            self.history.append(msg)
            compress_history_tags(self.history)
            cost = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.history) 
            if cost > self.context_win * 3: 
                target = self.context_win * 3 * 0.6
                while len(self.history) > 2 and cost > target:
                    self.history.pop(0); self.history.pop(0)
                    cost = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.history)
            messages = list(self.history)
        content_blocks = None
        gen = self.raw_ask(messages, tools, self.system, model)
        try:
            while True: yield next(gen)
        except StopIteration as e: content_blocks = e.value or []
        if content_blocks and not (len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("Error:")):
            self.history.append({"role": "assistant", "content": content_blocks})
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in content_blocks if b.get("type") == "tool_use"]
        return MockResponse("", content, tool_calls, str(content_blocks))


class NativeClaudeSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']; self.api_base = cfg['apibase'].rstrip('/')
        self.default_model = cfg.get('model', 'claude-opus')
        self.context_win = cfg.get('context_win', 32000)
        self.history = []  
        self.system = None
        self.lock = threading.Lock()
    def set_system(self, system_text): self.system = system_text

    def raw_ask(self, messages, tools=None, system=None, model=None, temperature=0.5, max_tokens=6144):
        """底层API调用。yields text chunks，generator return = list[content_block]"""
        model = model or self.default_model
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01", "anthropic-beta": "prompt-caching-2024-07-31"}
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
        if tools:
            tools = [dict(t) for t in tools]; tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tools
        if system: payload["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        # 历史消息缓存：最后一个assistant消息加cache_control
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "assistant":
                c = messages[i].get("content", [])
                if isinstance(c, list) and c: messages[i] = {**messages[i], "content": [*c[:-1], {**c[-1], "cache_control": {"type": "ephemeral"}}]}
                break
        try:
            resp = requests.post(auto_make_url(self.api_base, "messages"), headers=headers, json=payload, stream=True, timeout=120)
            if resp.status_code != 200:
                error_msg = f"Error: HTTP {resp.status_code} {resp.text[:500]}"
                yield error_msg
                return [{"type": "text", "text": error_msg}]
        except Exception as e:
            error_msg = f"Error: {e}"
            yield error_msg
            return [{"type": "text", "text": error_msg}]

        content_blocks = []; current_block = None; tool_json_buf = ""
        for line in resp.iter_lines():
            if not line: continue
            line = line.decode('utf-8') if isinstance(line, bytes) else line
            data_str = line[6:]
            if data_str.strip() == "[DONE]": break
            try: evt = json.loads(data_str)
            except: continue
            evt_type = evt.get("type", "")
            if evt_type == "content_block_start":
                block = evt.get("content_block", {})
                if block.get("type") == "text": current_block = {"type": "text", "text": ""}
                elif block.get("type") == "tool_use":
                    current_block = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
                    tool_json_buf = ""
            elif evt_type == "content_block_delta":
                delta = evt.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if current_block: current_block["text"] += text
                    yield text
                elif delta.get("type") == "input_json_delta": tool_json_buf += delta.get("partial_json", "")
            elif evt_type == "content_block_stop":
                if current_block:
                    if current_block["type"] == "tool_use":
                        try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
                        except: current_block["input"] = {"_raw": tool_json_buf}
                    content_blocks.append(current_block)
                    current_block = None
        return content_blocks

    def ask(self, msg, tools=None, model=None):
        """增量ask。msg: str|list[content_block]|dict。yields text chunks, return MockResponse"""
        if isinstance(msg, str): msg = {"role": "user", "content": msg}
        elif isinstance(msg, list): msg = {"role": "user", "content": msg}  
        with self.lock:
            self.history.append(msg)
            compress_history_tags(self.history)
            cost = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.history) 
            if cost > self.context_win * 3: 
                target = self.context_win * 3 * 0.6
                while len(self.history) > 2 and cost > target:
                    self.history.pop(0); self.history.pop(0)
                    cost = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.history)
            messages = list(self.history)

        content_blocks = None
        gen = self.raw_ask(messages, tools, self.system, model)
        try:
            while True: yield next(gen)
        except StopIteration as e: content_blocks = e.value or []
        if content_blocks and not (len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("Error:")):
            self.history.append({"role": "assistant", "content": content_blocks})
        thinking = ''
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = []
        for b in content_blocks:
            if b.get("type") == "tool_use":
                tool_calls.append(MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")))
        return MockResponse(thinking, content, tool_calls, str(content_blocks))

def openai_tools_to_claude(tools):
    """[{type:'function', function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    result = []
    for t in tools:
        if 'input_schema' in t: result.append(t); continue  # 已是claude格式
        fn = t.get('function', t)
        result.append({
            'name': fn['name'], 'description': fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}})
        })
    return result


class MockFunction:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments  
         
class MockToolCall:
    def __init__(self, name, args, id=''):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else args
        self.function = MockFunction(name, arg_str); self.id = id

class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw, stop_reason='end_turn'):
        self.thinking = thinking; self.content = content          
        self.tool_calls = tool_calls; self.raw = raw
        self.stop_reason = 'tool_use' if tool_calls else stop_reason
    def __repr__(self):    
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"

class ToolClient:
    def __init__(self, backends, auto_save_tokens=True):
        if isinstance(backends, list): self.backends = backends
        else: self.backends = [backends]
        self.backend = self.backends[0]
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ''
        self.total_cd_tokens = 0

    def chat(self, messages, tools=None):
        if self._should_use_structured_messages(messages):
            backend_messages = self._build_backend_messages(messages, tools)
            print("Structured prompt length:", sum(self._estimate_content_len(m.get("content")) for m in backend_messages), 'chars')
            prompt_log = self._serialize_messages_for_log(backend_messages)
            gen = self.backend.raw_ask(backend_messages)
        else:
            full_prompt = self._build_protocol_prompt(messages, tools)
            print("Full prompt length:", len(full_prompt), 'chars')
            prompt_log = full_prompt
            gen = self.backend.ask(full_prompt, stream=True)
        _write_llm_log('Prompt', prompt_log)
        raw_text = ''; summarytag = '[NextWillSummary]'
        for chunk in gen:
            raw_text += chunk
            if chunk != summarytag: yield chunk
        print('Complete response received.')
        if raw_text.endswith(summarytag):
            self.last_tools = ''; raw_text = raw_text[:-len(summarytag)]
        _write_llm_log('Response', raw_text)
        return self._parse_mixed_response(raw_text)

    def _should_use_structured_messages(self, messages):
        return isinstance(self.backend, LLMSession) and any(isinstance(m.get("content"), list) for m in messages)

    def _estimate_content_len(self, content):
        if isinstance(content, str): return len(content)
        if isinstance(content, list):
            total = 0
            for part in content:
                if not isinstance(part, dict): continue
                if part.get("type") == "text":
                    total += len(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += 1000
            return total
        return len(str(content))

    def _prepare_tool_instruction(self, tools):
        tool_instruction = ""
        if not tools: return tool_instruction
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(',', ':'))
        tool_instruction = f"""
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动，标签之间需要回车换行：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出*极为简短*的高度概括的单行（<30字）物理快照，包括上次工具调用结果产生的新信息+本次工具调用意图。此内容将进入长期工作记忆，记录关键信息，严禁输出无实际信息增量的描述。
3. **行动**: 如需调用工具，请在回复正文之后输出一个（或多个）**<tool_use>块**，然后结束，我会稍后给你返回<tool_result>块。
   格式: ```<tool_use>\n{{"name": "工具名", "arguments": {{参数}}}}\n</tool_use>\n```

### 可用工具库（已挂载，持续有效）
{tools_json}
"""
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = "\n### 工具库状态：持续有效（code_run/file_read等），**可正常调用**。调用协议沿用。\n"
        else:
            self.total_cd_tokens = 0
        self.last_tools = tools_json
        return tool_instruction

    def _build_backend_messages(self, messages, tools):
        system_content = next((m['content'] for m in messages if m['role'].lower() == 'system'), "")
        history_msgs = [m for m in messages if m['role'].lower() != 'system']
        tool_instruction = self._prepare_tool_instruction(tools)
        backend_messages = []
        merged_system = f"{system_content}\n{tool_instruction}".strip() if tool_instruction else system_content
        if merged_system:
            backend_messages.append({"role": "system", "content": merged_system})
        for m in history_msgs:
            backend_messages.append({"role": m['role'], "content": m['content']})
            self.total_cd_tokens += self._estimate_content_len(m['content'])
        if self.total_cd_tokens > 6000: self.last_tools = ''
        return backend_messages

    def _serialize_messages_for_log(self, messages):
        logged = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict): continue
                    if part.get("type") == "text":
                        parts.append({"type": "text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url = (part.get("image_url") or {}).get("url", "")
                        prefix = url.split(",", 1)[0] if url else "data:image/unknown;base64"
                        parts.append({"type": "image_url", "image_url": {"url": prefix + ",<omitted>"}})
                    else:
                        parts.append(part)
                logged.append({"role": msg.get("role"), "content": parts})
            else:
                logged.append(msg)
        return json.dumps(logged, ensure_ascii=False, indent=2)

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((m['content'] for m in messages if m['role'].lower() == 'system'), "")
        history_msgs = [m for m in messages if m['role'].lower() != 'system']
        tool_instruction = self._prepare_tool_instruction(tools)
            
        prompt = ""
        if system_content: prompt += f"=== SYSTEM ===\n{system_content}\n"
        prompt += f"{tool_instruction}\n\n"
        for m in history_msgs:
            role = "USER" if m['role'] == 'user' else "ASSISTANT"
            prompt += f"=== {role} ===\n{m['content']}\n\n"
            self.total_cd_tokens += self._estimate_content_len(m['content'])
            
        if self.total_cd_tokens > 6000: self.last_tools = ''

        prompt += "=== ASSISTANT ===\n" 
        return prompt

    def _parse_mixed_response(self, text):
        remaining_text = text; thinking = ''
        think_pattern = r"<thinking>(.*?)</thinking>"
        think_match = re.search(think_pattern, text, re.DOTALL)
        
        if think_match:
            thinking = think_match.group(1).strip()
            remaining_text = re.sub(think_pattern, "", remaining_text, flags=re.DOTALL)
        
        tool_calls = []; json_strs = []; errors = []
        tool_pattern = r"<tool_use>((?:(?!<tool_use>).){15,}?)</tool_use>"
        tool_all = re.findall(tool_pattern, remaining_text, re.DOTALL)
        
        if tool_all:
            tool_all = [s.strip() for s in tool_all]
            json_strs.extend([s for s in tool_all if s.startswith('{') and s.endswith('}')])
            remaining_text = re.sub(tool_pattern, "", remaining_text, flags=re.DOTALL)
        elif '<tool_use>' in remaining_text:
            weaktoolstr = remaining_text.split('<tool_use>')[-1].strip()
            json_str = weaktoolstr if weaktoolstr.endswith('}') else ''
            if json_str == '' and '```' in weaktoolstr and weaktoolstr.split('```')[0].strip().endswith('}'):
                json_str = weaktoolstr.split('```')[0].strip()
            if json_str:
                json_strs.append(json_str)
            remaining_text = remaining_text.replace('<tool_use>'+weaktoolstr, "")
        elif '"name":' in remaining_text and '"arguments":' in remaining_text:
            json_match = re.search(r"(\{.*\"name\":.*?\})", remaining_text, re.DOTALL | re.MULTILINE)
            if json_match:
                json_str = json_match.group(1).strip()
                json_strs.append(json_str)
                remaining_text = remaining_text.replace(json_str, "").strip()

        for json_str in json_strs:
            try:
                data = tryparse(json_str)
                func_name = data.get('name') or data.get('function') or data.get('tool')
                args = data.get('arguments') or data.get('args') or data.get('params') or data.get('parameters')
                if args is None: args = data
                if func_name: tool_calls.append(MockToolCall(func_name, args))
            except json.JSONDecodeError as e:
                errors.append({'err': f"[Warn] Failed to parse tool_use JSON: {json_str}", 'bad_json': f'Failed to parse tool_use JSON: {json_str[:200]}'})
                self.last_tools = ''   # llm肯定忘了tool schema了，再提供下
            except Exception as e:
                errors.append({'err': f'[Warn] Exception during tool_use parsing: {str(e)} {str(data)}'})
        if len(tool_calls) == 0:
            for e in errors:
                print(e['err'])
                if 'bad_json' in e: tool_calls.append(MockToolCall('bad_json', {'msg': e['bad_json']}))
        content = remaining_text.strip()
        return MockResponse(thinking, content, tool_calls, text)

def _write_llm_log(label, content):
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'temp/model_responses_{os.getpid()}.txt')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(log_path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(f"=== {label} === {ts}\n{content}\n\n")

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


class NativeToolClient:
    THINKING_PROMPT = """
### 行动规范（持续有效）
每次回复请遵循：
1. 在 <thinking></thinking> 标签中先分析现状和策略
2. 在 <summary></summary> 中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。此内容进入长期工作记忆。
3. 如需调用工具，直接使用工具调用能力，然后结束回复。
""".strip()
    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self.THINKING_PROMPT
        self.tools = {}
        self._pending_tool_ids = []
    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self.THINKING_PROMPT}" if extra_system else self.THINKING_PROMPT
        self.backend.system = combined
    def chat(self, messages, tools=None):
        if tools: self.tools = openai_tools_to_claude(tools) if isinstance(self.backend, NativeClaudeSession) else tools
        combined_content = []; resp = None
        for msg in messages:
            c = msg.get('content', '')
            if isinstance(c, str): combined_content.append({"type": "text", "text": c})
            elif isinstance(c, list) or isinstance(c, dict): combined_content.extend(c)
        if self._pending_tool_ids and isinstance(self.backend, NativeClaudeSession):
            tool_result_blocks = [{"type": "tool_result", "tool_use_id": tid, "content": ""} for tid in self._pending_tool_ids]
            combined_content = tool_result_blocks + combined_content
            self._pending_tool_ids = []
        merged = {"role": "user", "content": combined_content}
        _write_llm_log('Prompt', json.dumps(merged, ensure_ascii=False, indent=2))
        gen = self.backend.ask(merged, self.tools); 
        try:
            while True: 
                chunk = next(gen); yield chunk
        except StopIteration as e: resp = e.value
        print('Complete response received.')
        if resp:
            _write_llm_log('Response', resp.raw)
            text = resp.content
            think_match = re.search(r'<thinking>(.*?)</thinking>', text, re.DOTALL)
            if think_match:
                resp.thinking = think_match.group(1).strip()
                text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
            resp.content = text.strip()
        if resp and hasattr(resp, 'tool_calls') and resp.tool_calls and isinstance(self.backend, NativeClaudeSession):
            self._pending_tool_ids = [tc.id for tc in resp.tool_calls]
        return resp