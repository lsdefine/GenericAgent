import os, json, re, time, requests, sys, threading, urllib3
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try: import mykey
except: raise Exception('[ERROR] mykey.py not found, please copy mykey_template.py to mykey.py and fill your LLM backend.')

mykeys = vars(mykey)
proxy = mykeys.get("proxy", 'http://127.0.0.1:2082')
proxies = {"http": proxy, "https": proxy} if proxy else None

def compress_history_tags(messages, keep_recent=4, max_len=200):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages to save tokens."""
    for i, msg in enumerate(messages):
        if i < len(messages) - keep_recent and 'orig' not in msg:
            msg['orig'] = msg['prompt']
            for tag in ('thinking', 'tool_use', 'tool_result'):
                msg['prompt'] = re.sub(
                    rf'(<{tag}>)([\s\S]*?)(</{tag}>)',
                    lambda m, _ml=max_len: m.group(1) + (m.group(2)[:_ml] + '...') + m.group(3) if len(m.group(2)) > _ml else m.group(0),
                    msg['prompt']
                )
    return messages

class SiderLLMSession:
    def __init__(self, sider_cookie, default_model="gemini-3.0-flash"):
        from sider_ai_api import Session   # 不使用sider的话没必要安装这个包
        self._core = Session(cookie=sider_cookie, proxies=proxies)   
        self.default_model = default_model
    def ask(self, prompt, model=None, stream=False):
        if model is None: model = self.default_model
        if len(prompt) > 28000: 
            print(f"[Warn] Prompt too long ({len(prompt)} chars), truncating.")
            prompt = prompt[-28000:]
        full_text = self._core.chat(prompt, model, stream=False)
        if stream: return iter([full_text])   # gen有奇怪的空回复或死循环行为，sider足够快
        return full_text   

class ClaudeSession:
    def __init__(self, api_key, api_base, model="claude-opus", context_win=10000):
        self.api_key, self.api_base, self.default_model, self.context_win = api_key, api_base.rstrip('/'), model, context_win
        self.raw_msgs, self.lock = [], threading.Lock()
    def _trim_messages(self, messages):
        compress_history_tags(messages)
        total = sum(len(m['prompt']) for m in messages)
        if total <= self.context_win * 4: return messages
        target, current, result = self.context_win * 4 * 0.9, 0, []
        for msg in reversed(messages):
            if (msg_len := len(msg['prompt'])) + current <= target:
                result.append(msg); current += msg_len
            else: break
        if current > self.context_win * 3.6: print(f'[DEBUG] {len(result)} contexts, whole length {current//4} tokens.')
        return result[::-1] or messages[-2:]
    def raw_ask(self, messages, model=None, temperature=0.5, max_tokens=6144):
        model = model or self.default_model
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens, "stream": True}
        try:
            with requests.post(f"{self.api_base}/v1/messages", headers=headers, json=payload, stream=True, timeout=(5,30)) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line: continue
                    line = line.decode("utf-8") if isinstance(line, bytes) else line
                    if not line.startswith("data:"): continue
                    data = line[5:].lstrip()
                    if data == "[DONE]": break
                    try:
                        obj = json.loads(data)
                        if obj.get("type") == "content_block_delta" and obj.get("delta", {}).get("type") == "text_delta":
                            text = obj["delta"].get("text", "")
                            if text: yield text
                    except: pass
        except Exception as e: yield f"Error: {str(e)}"
    def make_messages(self, raw_list):
        trimmed = self._trim_messages(raw_list)
        return [{"role": m['role'], "content": m['prompt']} for m in trimmed]
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
    def __init__(self, api_key, api_base, model, context_win=12000, proxy=None, api_mode="chat_completions",
                 max_retries=2, connect_timeout=10, read_timeout=120):
        self.api_key = api_key; self.api_base = api_base.rstrip('/'); self.default_model = model
        self.context_win = context_win; self.raw_msgs = []; self.messages = []
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.lock = threading.Lock()
        self.max_retries = max(0, int(max_retries))
        self.connect_timeout = max(1, int(connect_timeout))
        self.read_timeout = max(5, int(read_timeout))
        mode = str(api_mode or "chat_completions").strip().lower().replace('-', '_')
        if mode in ["responses", "response"]: self.api_mode = "responses"
        else: self.api_mode = "chat_completions"

    def _endpoint(self, path):
         # 处理火山引擎API，它已经包含完整路径 
        if 'ark.cn-beijing.volces.com' in self.api_base or 'ark.cn-shanghai.volces.com' in self.api_base:
            return f"{self.api_base}/{path.lstrip('/')}"
        if self.api_base.endswith('/v1'): return f"{self.api_base}/{path.lstrip('/')}"
        if self.api_base.endswith('$'): return f"{self.api_base.rstrip('$')}/{path.lstrip('/')}"
        return f"{self.api_base}/v1/{path.lstrip('/')}"

    def _retry_delay(self, resp, attempt):
        retry_after = None
        try:
            if resp is not None:
                retry_after = (resp.headers or {}).get("retry-after")
            if retry_after is not None:
                retry_after = float(retry_after)
        except:
            retry_after = None
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
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_mode == "responses":
            url = self._endpoint("responses")
            payload = {"model": model, "input": self._to_responses_input(messages), "temperature": temperature, "stream": True}
        else:
            url = self._endpoint("chat/completions")
            payload = {"model": model, "messages": messages, "temperature": temperature, "stream": True}
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
                        if '</tool_use>' in buffer[-30:]: break
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
                l = len(str(m))//4
                if tok + l > self.context_win*0.2: break
                tok += l; keep += 1
            keep = max(2, keep)
            old, self.raw_msgs = self.raw_msgs[:-keep], self.raw_msgs[-keep:]
            if len(old) == 0: old = self.raw_msgs; self.raw_msgs = []
            p = "Summarize prev summary and prev conversations into compact memory (facts/decisions/constraints/open questions). Do NOT restate long schemas. The new summary should less than 1000 tokens. Permit dropping non-important things.\n"
            messages = self.make_messages(old, omit_images=True)
            messages += [{"role":"user", "content":p}]
            msg_lens = [1000 if isinstance(m["content"], list) else len(str(m["content"]))//4 for m in messages]
            summary = ''.join(list(self.raw_ask(messages, model, temperature=0.1)))
            print('[Debug] Summary length:', len(summary)//4, '; Orig context lengths:', str(msg_lens))
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
                msg_lens = [1000 if isinstance(m["content"], list) else len(str(m["content"]))//4 for m in messages]
                total_len = sum(msg_lens)   # estimate token count
            gen = self.raw_ask(messages, model)
            for chunk in gen:
                content += chunk; yield chunk
            if not content.startswith("Error:"):
                self.raw_msgs.append({"role": "assistant", "prompt": content, "image": None})
            if total_len > 5000: print(f"[Debug] Whole context length {total_len} {str(msg_lens)}.")
            if total_len > self.context_win: 
                yield '[NextWillSummary]'
                threading.Thread(target=self.summary_history, daemon=True).start()
        if stream: return _ask_gen()
        return ''.join(list(_ask_gen())) 
        
  
class GeminiSession:
    def __init__(self, api_key=None, default_model="gemini-2.0-flash-001", proxy=proxy):
        self.api_key = api_key or google_api_key
        if not self.api_key: raise ValueError("google_api_key 未配置或为空，请在 mykey.py 中设置")
        self.default_model = default_model
        self.proxies = {"http":proxy, "https":proxy} if proxy else None
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
    def __init__(self, api_key, proxy="http://127.0.0.1:2082", default_model="grok-4-1-fast-non-reasoning"):
        import xai_sdk
        from xai_sdk.chat import user, system
        self._user, self._system = user, system
        self.default_model = default_model
        self._last_response_id = None  # 多轮对话链
        os.environ["XAI_API_KEY"] = api_key
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

class MockFunction:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments  
         
class MockToolCall:
    def __init__(self, name, args):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else args
        self.function = MockFunction(name, arg_str)

class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw):
        self.thinking = thinking        # 存放 <thinking> 内部的思维过程
        self.content = content          # 存放去除标签后的纯文本回复
        self.tool_calls = tool_calls    # 存放 MockToolCall 列表 或 None
        self.raw = raw
    def __repr__(self):    
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"

class ToolClient:
    def __init__(self, backends, auto_save_tokens=False):
        if isinstance(backends, list): self.backends = backends
        else: self.backends = [backends]
        self.backend = self.backends[0]
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ''
        self.total_cd_tokens = 0

    def chat(self, messages, tools=None):
        full_prompt = self._build_protocol_prompt(messages, tools)      
        print("Full prompt length:", len(full_prompt), 'chars')
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, f'./temp/model_responses_{os.getpid()}.txt'), 'a', encoding='utf-8', errors="replace") as f:
            f.write(f"=== Prompt === {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{full_prompt}\n")
        gen = self.backend.ask(full_prompt, stream=True)
        raw_text = ''; summarytag = '[NextWillSummary]'
        for chunk in gen:
            raw_text += chunk; 
            if chunk != summarytag: yield chunk
        print('Complete response received.')
        if raw_text.endswith(summarytag):
            self.last_tools = ''; raw_text = raw_text[:-len(summarytag)]
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, f'./temp/model_responses_{os.getpid()}.txt'), 'a', encoding='utf-8', errors="replace") as f:
            f.write(f"=== Response === {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{raw_text}\n\n")
        return self._parse_mixed_response(raw_text)

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((m['content'] for m in messages if m['role'].lower() == 'system'), "")
        history_msgs = [m for m in messages if m['role'].lower() != 'system']
        # 构造工具描述
        tool_instruction = ""
        if tools:
            tools_json = json.dumps(tools, ensure_ascii=False, separators=(',', ':'))
            tool_instruction = f"""
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动，标签之间需要回车换行：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出*极为简短*的高度概括的单行（<30字）物理快照，包括上次工具调用结果产生的新信息+本次工具调用意图。此内容将进入长期工作记忆，记录关键信息，严禁输出无实际信息增量的描述。
3. **行动**: 如需调用工具，请在回复正文之后输出一个 **<tool_use>块**，然后结束，我会稍后给你返回<tool_result>块。
   格式: ```<tool_use>\n{{"name": "工具名", "arguments": {{参数}}}}\n</tool_use>\n```

### 可用工具库（已挂载，持续有效）
{tools_json}
"""
            if self.auto_save_tokens and self.last_tools == tools_json:
                tool_instruction = "\n### 工具库状态：持续有效（code_run/file_read等），**可正常调用**。调用协议沿用。\n"
            else:
                self.total_cd_tokens = 0
            self.last_tools = tools_json
            
        prompt = ""
        if system_content: prompt += f"=== SYSTEM ===\n{system_content}\n"
        prompt += f"{tool_instruction}\n\n"
        for m in history_msgs:
            role = "USER" if m['role'] == 'user' else "ASSISTANT"
            prompt += f"=== {role} ===\n{m['content']}\n\n"
            self.total_cd_tokens += len(m['content'])
            
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
        tool_pattern = r"<tool_use>(.{15,}?)</tool_use>"
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
        return MockResponse(thinking, content, tool_calls[-1:], text)

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

if __name__ == "__main__":
    import sys, os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        import mykey
    except ImportError:
        class MockMyKey: pass
        mykey = MockMyKey()
    
    mykeys = vars(mykey)
    sider_cookie = mykeys.get("sider_cookie")
    oai_configs = {
        k: v for k, v in vars(mykey).items() if k.startswith("oai_config") and v
    }
    google_api_key = mykeys.get("google_api_key")
    cfg = oai_configs.get("oai_config")

    llmclient = ToolClient(GeminiSession(api_key=google_api_key, proxy='127.0.0.1:2082').ask)
    #llmclient = ToolClient(LLMSession(api_key=cfg['apikey'], api_base=cfg['apibase'], model=cfg['model']).ask)
    #llmclient = ToolClient(SiderLLMSession().ask)
    def get_final(gen):
        try:
            while True: print('mid:', next(gen))
        except StopIteration as e:
            return e.value
        
    response = get_final(llmclient.chat(
        messages=[{"role": "user", "content": "我的IP是多少"}], 
        tools=[{"name": "get_ip", "parameters": {}}]
    ))
    print(f"思考: {response.thinking}") 
    if response.tool_calls:
        cmd = response.tool_calls[0]
        print(f"调用: {cmd.function.name} 参数: {cmd.function.arguments}")

    response = get_final(llmclient.chat(
        messages=[{"role": "user", "content": "<tool_result>10.176.45.12</tool_result>"}] 
    ))
    print(response.content)