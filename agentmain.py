import os, sys, threading, queue, time, json, re, random
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(errors='replace')
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(errors='replace')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from llmcore import (
    SiderLLMSession,
    LLMSession,
    ToolClient,
    ClaudeSession,
    XaiSession,
    GeminiSession,
    NativeToolClient,
    NativeClaudeSession,
    NativeOAISession,
    build_multimodal_content,
    refresh_mykeys,
)
from agent_loop import agent_runner_loop
from ga import GenericAgentHandler, smart_format, get_global_memory, format_error

script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir, 'assets/tools_schema.json'), 'r', encoding='utf-8') as f:
    TS = f.read()
    TOOLS_SCHEMA = json.loads(TS if os.name == 'nt' else TS.replace('powershell', 'bash'))

mem_dir = os.path.join(script_dir, 'memory')
if not os.path.exists(mem_dir): os.makedirs(mem_dir)
mem_txt = os.path.join(mem_dir, 'global_mem.txt')
if not os.path.exists(mem_txt): open(mem_txt, 'w', encoding='utf-8').write('')
mem_insight = os.path.join(mem_dir, 'global_mem_insight.txt')
if not os.path.exists(mem_insight):
    t = os.path.join(script_dir, 'assets/global_mem_insight_template.txt')
    open(mem_insight, 'w', encoding='utf-8').write(open(t, encoding='utf-8').read() if os.path.exists(t) else '')
cdp_cfg = os.path.join(script_dir, 'assets/tmwd_cdp_bridge/config.js')
if not os.path.exists(cdp_cfg):
    try:
        os.makedirs(os.path.dirname(cdp_cfg), exist_ok=True)
        open(cdp_cfg, 'w', encoding='utf-8').write(f"const TID = '__ljq_{hex(random.randint(0, 99999999))[2:8]}';")
    except Exception as e: print(f'[WARN] CDP config init failed: {e} — advanced web features (tmwebdriver) will be unavailable.')

def get_system_prompt():
    with open(os.path.join(script_dir, 'assets/sys_prompt.txt'), 'r', encoding='utf-8') as f: prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    return prompt

class GeneraticAgent:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(script_dir, 'temp'), exist_ok=True)
        self.lock = threading.Lock()
        self.history = []               
        self.task_queue = queue.Queue() 
        self.is_running = False; self.stop_sig = False
        self.llm_no = 0;  self.inc_out = False
        self.handler = None; self.verbose = True
        self.reload_backends()

    def _iter_llm_configs(self, mykeys):
        ordered_items = list(mykeys.items())
        default_key = mykeys.get("default_model_key")
        if default_key:
            ordered_items.sort(key=lambda item: item[0] != default_key)
        for key, cfg in ordered_items:
            if any(x in key for x in ['api', 'config', 'cookie']):
                yield key, cfg

    def _make_llm_clients(self, key, cfg):
        if 'native' in key and 'claude' in key:
            return [NativeToolClient(NativeClaudeSession(cfg=cfg))]
        if 'native' in key and 'oai' in key:
            return [NativeToolClient(NativeOAISession(cfg=cfg))]
        if 'claude' in key:
            return [ToolClient(ClaudeSession(cfg=cfg))]
        if 'oai' in key:
            return [ToolClient(LLMSession(cfg=cfg))]
        if 'xai' in key:
            return [ToolClient(XaiSession(cfg=cfg))]
        if 'google' in key or 'gemini' in key:
            gcfg = cfg if isinstance(cfg, dict) else {'google_api_key': cfg}
            return [ToolClient(GeminiSession(cfg=gcfg))]
        if 'sider' in key:
            return [ToolClient(SiderLLMSession(cfg={'apikey': cfg, 'model': model})) for model in ["gemini-3.0-flash", "gpt-5.4"]]
        return []

    def _build_llm_clients(self, mykeys):
        llm_clients = []
        for key, cfg in self._iter_llm_configs(mykeys):
            try:
                llm_clients.extend(self._make_llm_clients(key, cfg))
            except Exception:
                pass
        return llm_clients

    def _describe_client(self, client):
        return f"{type(client.backend).__name__}/{client.backend.default_model}"

    def reload_backends(self):
        mykeys = refresh_mykeys()
        self.llmclients = self._build_llm_clients(mykeys)
        if self.llmclients and self.llm_no >= len(self.llmclients):
            self.llm_no = 0
        self.llmclient = self.llmclients[self.llm_no] if self.llmclients else None
        return bool(self.llmclient)

    def next_llm(self, n=-1):
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclients)
        self.llmclient = self.llmclients[self.llm_no]
        self.llmclient.last_tools = ''
    def list_llms(self): return [(i, self._describe_client(client), i == self.llm_no) for i, client in enumerate(self.llmclients)]
    def get_llm_name(self):
        return self._describe_client(self.llmclient)

    def abort(self):
        print('Abort current task...')
        if not self.is_running: return
        self.stop_sig = True
        if self.handler is not None: self.handler.code_stop_signal.append(1)
            
    def put_task(self, query, source="user", images=None):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "images": images or [], "output": display_queue})
        return display_queue

    def run(self):
        while True:
            task = self.task_queue.get()
            self.is_running = True
            raw_query, source, images, display_queue = task["query"], task["source"], task.get("images") or [], task["output"]
            rquery = smart_format(raw_query.replace('\n', ' '), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")
            
            sys_prompt = get_system_prompt()
            script_dir = os.path.dirname(os.path.abspath(__file__))
            handler = GenericAgentHandler(None, self.history, os.path.join(script_dir, 'temp'))
            if self.handler and 'key_info' in self.handler.working: 
                ki = re.sub(r'\n\[SYSTEM\] 此为.*?工作记忆[。\n]*', '', self.handler.working['key_info'])  # 去旧
                handler.working['key_info'] = ki
                handler.working['passed_sessions'] = ps = self.handler.working.get('passed_sessions', 0) + 1
                if ps > 0: handler.working['key_info'] += f'\n[SYSTEM] 此为 {ps} 个对话前设置的key_info，若已在新任务，先更新或清除工作记忆。\n'
            self.handler = handler
            user_input = raw_query
            if source == 'feishu' and len(self.history) > 1:   # 如果有历史记录且来自飞书，注入到首轮 user_input 中（支持/restore恢复上下文）
                user_input = handler._get_anchor_prompt() + f"\n\n### 用户当前消息\n{raw_query}"
            initial_user_content = None
            if images and isinstance(self.llmclient.backend, LLMSession):
                initial_user_content = build_multimodal_content(user_input, images)
            elif images:
                print(f"[INFO] backend {type(self.llmclient.backend).__name__} does not support direct multimodal input, fallback to text attachment hints.")
            gen = agent_runner_loop(self.llmclient, sys_prompt, user_input,
                                handler, TOOLS_SCHEMA, max_turns=40, verbose=self.verbose,
                                initial_user_content=initial_user_content)
            try:
                full_resp = ""; last_pos = 0; loop_result = None
                while True:
                    try:
                        chunk = next(gen)
                    except StopIteration as e:
                        loop_result = e.value; break
                    if self.stop_sig: break
                    full_resp += chunk
                    if len(full_resp) - last_pos > 50:
                        display_queue.put({'next': full_resp[last_pos:] if self.inc_out else full_resp, 'source': source})
                        last_pos = len(full_resp)
                if self.inc_out and last_pos < len(full_resp): display_queue.put({'next': full_resp[last_pos:], 'source': source})
                if '</summary>' in full_resp: full_resp = full_resp.replace('</summary>', '</summary>\n\n')
                if '</file_content>' in full_resp: full_resp = re.sub(r'<file_content>\s*(.*?)\s*</file_content>', r'\n````\n<file_content>\n\1\n</file_content>\n````', full_resp, flags=re.DOTALL)
                done_item = {'done': full_resp, 'source': source}
                if loop_result: done_item['result'] = loop_result
                display_queue.put(done_item)
                self.history = handler.history_info
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                display_queue.put({'done': full_resp + f'\n```\n{format_error(e)}\n```', 'source': source})
            finally:
                self.is_running = self.stop_sig = False
                self.task_queue.task_done()
                if self.handler is not None: self.handler.code_stop_signal.append(1)

    
if __name__ == '__main__':
    import argparse
    from datetime import datetime
    parser = argparse.ArgumentParser()
    parser.add_argument('--scheduled', action='store_true', help='计划任务轮询模式')
    parser.add_argument('--task', metavar='IODIR', help='一次性任务模式(文件IO)')
    parser.add_argument('--reflect', metavar='SCRIPT', help='反射模式：加载监控脚本，check()触发时发任务')
    parser.add_argument('--llm_no', type=int, default=0, help='LLM编号')
    args = parser.parse_args()

    agent = GeneraticAgent()
    agent.next_llm(args.llm_no)
    agent.verbose = False
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        d = os.path.join(script_dir, f'temp/{args.task}'); rp = os.path.join(d, 'reply.txt'); nround = ''
        with open(os.path.join(d, 'input.txt'), encoding='utf-8') as f: raw = f.read()
        while True:
            dq = agent.put_task(raw, source='task')
            while 'done' not in (item := dq.get(timeout=120)): 
                if 'next' in item and random.random() < 0.95:  # 概率写一次中间结果
                    with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item.get('next', ''))
            with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item['done'] + '\n\n[ROUND END]\n')
            for _ in range(150):  # 等reply.txt，5分钟超时
                time.sleep(2)
                if os.path.exists(rp):
                    with open(rp, encoding='utf-8') as f: raw = f.read()
                    os.remove(rp); break
            else: break
            nround = int(nround) + 1 if nround.isdigit() else 1
    elif args.reflect:
        import importlib.util
        spec = importlib.util.spec_from_file_location('reflect_script', args.reflect)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        interval = getattr(mod, 'INTERVAL', 5)
        once = getattr(mod, 'ONCE', False)
        on_done = getattr(mod, 'on_done', None)
        print(f'[Reflect] loaded {args.reflect}, interval={interval}s, once={once}')
        while True:
            time.sleep(interval)
            try: task = mod.check()
            except Exception as e: 
                print(f'[Reflect] check() error: {e}'); continue
            if task is None: continue
            print(f'[Reflect] triggered: {task[:80]}')
            dq = agent.put_task(task, source='reflect')
            try:
                while 'done' not in (item := dq.get(timeout=120)): pass
                result = item['done']
                print(result)
            except Exception as e:
                if once: raise
                print(f'[Reflect] drain error: {e}'); result = f'[ERROR] {e}'
            log_dir = os.path.join(script_dir, 'temp/reflect_logs'); os.makedirs(log_dir, exist_ok=True)
            script_name = os.path.splitext(os.path.basename(args.reflect))[0]
            open(os.path.join(log_dir, f'{script_name}_{datetime.now():%Y-%m-%d}.log'), 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}]\n{result}\n\n')
            if on_done:
                try: on_done(result)
                except Exception as e: print(f'[Reflect] on_done error: {e}')
            if once: print('[Reflect] ONCE=True, exiting.'); break
    elif args.scheduled: 
        print('moved to reflect mode')
    else:
        agent.inc_out = True
        while True:
            q = input('> ').strip()
            if not q: continue
            try:
                dq = agent.put_task(q, source='user')
                while True:
                    item = dq.get()
                    if 'next' in item: print(item['next'], end='', flush=True)
                    if 'done' in item: print(); break
            except KeyboardInterrupt:
                agent.abort()
                print('\n[Interrupted]')
