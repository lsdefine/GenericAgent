import os, sys, threading, queue, time, json, re, random, locale
os.environ.setdefault('GA_LANG', 'zh' if any(k in (locale.getlocale()[0] or '').lower() for k in ('zh', 'chinese')) else 'en')
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(errors='replace')
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(errors='replace')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from llmcore import LLMSession, ToolClient, ClaudeSession, MixinSession, NativeToolClient, NativeClaudeSession, NativeOAISession
from agent_loop import agent_runner_loop
from ga import GenericAgentHandler, smart_format, get_global_memory, format_error, consume_file
from ga_switch import get_service

script_dir = os.path.dirname(os.path.abspath(__file__))
def load_tool_schema(suffix=''):
    global TOOLS_SCHEMA
    with open(os.path.join(script_dir, f'assets/tools_schema{suffix}.json'), 'r', encoding='utf-8') as f: TS = f.read()
    TOOLS_SCHEMA = json.loads(TS if os.name == 'nt' else TS.replace('powershell', 'bash'))
load_tool_schema()

lang_suffix = '_en' if os.environ.get('GA_LANG', '') == 'en' else ''
mem_dir = os.path.join(script_dir, 'memory')
if not os.path.exists(mem_dir): os.makedirs(mem_dir)
mem_txt = os.path.join(mem_dir, 'global_mem.txt')
if not os.path.exists(mem_txt): open(mem_txt, 'w', encoding='utf-8').write('# [Global Memory - L2]\n')
mem_insight = os.path.join(mem_dir, 'global_mem_insight.txt')
if not os.path.exists(mem_insight):
    t = os.path.join(script_dir, f'assets/global_mem_insight_template{lang_suffix}.txt')
    open(mem_insight, 'w', encoding='utf-8').write(open(t, encoding='utf-8').read() if os.path.exists(t) else '')
cdp_cfg = os.path.join(script_dir, 'assets/tmwd_cdp_bridge/config.js')
if not os.path.exists(cdp_cfg):
    try:
        os.makedirs(os.path.dirname(cdp_cfg), exist_ok=True)
        open(cdp_cfg, 'w', encoding='utf-8').write(f"const TID = '__ljq_{hex(random.randint(0, 99999999))[2:8]}';")
    except Exception as e: print(f'[WARN] CDP config init failed: {e} — advanced web features (tmwebdriver) will be unavailable.')

def get_system_prompt():
    with open(os.path.join(script_dir, f'assets/sys_prompt{lang_suffix}.txt'), 'r', encoding='utf-8') as f: prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    return prompt

class GeneraticAgent:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(script_dir, 'temp'), exist_ok=True)
        self.lock = threading.Lock()
        self.task_dir = None
        self.history = []
        self.task_queue = queue.Queue() 
        self.is_running = False; self.stop_sig = False
        self.llm_no = 0; self.llmclient = None; self.llmclients = []
        self.config_source = 'legacy'; self.config_meta = {}
        self.ga_switch = get_service()
        self.inc_out = False
        self.handler = None; self.verbose = True
        self._reload_clients(initial=True)

    def _sync_tool_schema(self):
        name = self.get_llm_name().lower()
        if 'glm' in name or 'minimax' in name or 'kimi' in name: load_tool_schema('_cn')
        else: load_tool_schema()

    def _tag_client(self, client, *, route_name=None, route_kind='single', backend_kind=None, members=None):
        client.ga_switch_route_id = getattr(client, 'ga_switch_route_id', None)
        client.ga_switch_route_name = route_name or getattr(client, 'ga_switch_route_name', getattr(client.backend, 'name', ''))
        client.ga_switch_route_kind = route_kind
        client.ga_switch_backend_kind = backend_kind or getattr(client, 'ga_switch_backend_kind', None)
        client.ga_switch_members = list(members or getattr(client, 'ga_switch_members', []))
        return client

    def build_llmclients_from_store(self):
        return self.ga_switch.build_clients_from_store()

    def build_llmclients_from_legacy_mykey(self):
        from llmcore import mykeys
        llm_sessions = []
        for k, cfg in mykeys.items():
            if not any(x in k for x in ['api', 'config', 'cookie']):
                continue
            try:
                if 'native' in k and 'claude' in k:
                    llm_sessions.append(self._tag_client(NativeToolClient(NativeClaudeSession(cfg=cfg)), route_name=cfg.get('name') or k, backend_kind='native_claude'))
                elif 'native' in k and 'oai' in k:
                    llm_sessions.append(self._tag_client(NativeToolClient(NativeOAISession(cfg=cfg)), route_name=cfg.get('name') or k, backend_kind='native_oai'))
                elif 'claude' in k:
                    llm_sessions.append(self._tag_client(ToolClient(ClaudeSession(cfg=cfg)), route_name=cfg.get('name') or k, backend_kind='claude_text'))
                elif 'oai' in k:
                    llm_sessions.append(self._tag_client(ToolClient(LLMSession(cfg=cfg)), route_name=cfg.get('name') or k, backend_kind='oai_text'))
                elif 'mixin' in k:
                    llm_sessions.append({'mixin_cfg': cfg, 'route_name': cfg.get('name') or k})
            except Exception as e:
                print(f'[WARN] Failed to init legacy session {k}: {e}')
        for i, s in enumerate(llm_sessions):
            if isinstance(s, dict) and 'mixin_cfg' in s:
                try:
                    mixin = MixinSession(llm_sessions, s['mixin_cfg'])
                    client = NativeToolClient(mixin) if isinstance(mixin._sessions[0], (NativeClaudeSession, NativeOAISession)) else ToolClient(mixin)
                    llm_sessions[i] = self._tag_client(client, route_name=s['route_name'], route_kind='failover', backend_kind='mixin')
                except Exception as e:
                    print(f'[WARN] Failed to init MixinSession with cfg {s["mixin_cfg"]}: {e}')
        llm_sessions = [s for s in llm_sessions if not isinstance(s, dict)]
        return llm_sessions, {'source': 'legacy', 'active_index': min(self.llm_no, max(len(llm_sessions) - 1, 0)), 'routes': []}

    def _build_client_set(self):
        if self.ga_switch.use_structured_config() and self.ga_switch.has_usable_routes():
            try:
                clients, meta = self.build_llmclients_from_store()
                if clients:
                    meta = dict(meta or {}, source='store')
                    return clients, meta
            except Exception as e:
                print(f'[WARN] Structured config load failed, fallback to legacy: {e}')
        return self.build_llmclients_from_legacy_mykey()

    def _reload_clients(self, *, initial=False, preserve_history=True):
        old_client = self.llmclient
        old_history = getattr(old_client.backend, 'history', None) if old_client and preserve_history else None
        old_route_id = getattr(old_client, 'ga_switch_route_id', None) if old_client else None
        old_idx = self.llm_no
        clients, meta = self._build_client_set()
        self.llmclients = clients
        self.config_source = meta.get('source', 'legacy')
        self.config_meta = meta
        if not self.llmclients:
            self.llm_no = 0
            self.llmclient = None
            return []
        target_idx = meta.get('active_index', 0)
        if not initial and preserve_history:
            if self.config_source == 'store' and old_route_id is not None:
                matched_idx = next((i for i, client in enumerate(self.llmclients) if getattr(client, 'ga_switch_route_id', None) == old_route_id), None)
                if matched_idx is not None:
                    target_idx = matched_idx
            elif old_idx < len(self.llmclients):
                target_idx = old_idx
        self.llm_no = target_idx % len(self.llmclients)
        self.llmclient = self.llmclients[self.llm_no]
        if preserve_history and old_history is not None:
            self.llmclient.backend.history = old_history
        if self.config_source == 'store' and getattr(self.llmclient, 'ga_switch_route_id', None) is not None:
            self.ga_switch.set_active_route(self.llmclient.ga_switch_route_id)
        self._sync_tool_schema()
        return self.llmclients

    def next_llm(self, n=-1):
        if not self.llmclients:
            self.llmclient = None
            return None
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclients)
        lastc = self.llmclient
        self.llmclient = self.llmclients[self.llm_no]
        if lastc is not None:
            self.llmclient.backend.history = lastc.backend.history
        if hasattr(self.llmclient, 'last_tools'):
            self.llmclient.last_tools = ''
        if self.config_source == 'store' and getattr(self.llmclient, 'ga_switch_route_id', None) is not None:
            self.ga_switch.set_active_route(self.llmclient.ga_switch_route_id)
        self._sync_tool_schema()
        return self.llmclient

    def set_active_route(self, route_id_or_idx):
        if self.config_source == 'store':
            target_idx = next((i for i, client in enumerate(self.llmclients) if getattr(client, 'ga_switch_route_id', None) == route_id_or_idx), None)
            if target_idx is None and isinstance(route_id_or_idx, int) and 0 <= route_id_or_idx < len(self.llmclients):
                target_idx = route_id_or_idx
            if target_idx is None:
                raise ValueError(f'Unknown route id: {route_id_or_idx}')
            self.next_llm(target_idx)
            return self.describe_llms()[self.llm_no]
        if not isinstance(route_id_or_idx, int):
            raise ValueError(f'Legacy mode only supports index switching, got {route_id_or_idx!r}')
        self.next_llm(route_id_or_idx)
        return self.describe_llms()[self.llm_no]

    def reload_llm_config(self, preserve_history=True):
        if self.is_running:
            raise RuntimeError('Cannot reload LLM config while agent is running.')
        self._reload_clients(initial=False, preserve_history=preserve_history)
        return self.describe_llms()

    def describe_llms(self):
        result = []
        for idx, client in enumerate(self.llmclients):
            backend = client.backend
            diag = backend.describe_diagnostics() if hasattr(backend, 'describe_diagnostics') else {}
            members = getattr(client, 'ga_switch_members', [])
            route_name = getattr(client, 'ga_switch_route_name', getattr(backend, 'name', ''))
            backend_class = type(backend).__name__
            item = {
                'idx': idx,
                'active': idx == self.llm_no,
                'source': self.config_source,
                'route_id': getattr(client, 'ga_switch_route_id', None),
                'name': route_name,
                'display_name': f"{route_name} [{backend_class}/{backend.name}]",
                'route_kind': getattr(client, 'ga_switch_route_kind', 'single'),
                'backend_class': backend_class,
                'backend_kind': getattr(client, 'ga_switch_backend_kind', getattr(backend, 'backend_kind', None)),
                'provider_id': getattr(backend, 'provider_id', None),
                'provider_name': getattr(backend, 'provider_name', getattr(backend, 'name', None)),
                'model': getattr(backend, 'model', None),
                'api_mode': getattr(backend, 'api_mode', None),
                'native_tools': isinstance(client, NativeToolClient) or 'Native' in backend_class,
                'member_names': [m.get('name', '') if isinstance(m, dict) else str(m) for m in members],
                'active_member_name': getattr(backend, 'active_member_name', getattr(backend, 'name', None)),
                'last_switch_reason': getattr(backend, 'last_switch_reason', ''),
                'spring_back_seconds': getattr(backend, '_spring_sec', None),
            }
            item.update(diag)
            result.append(item)
        return result

    def list_llms(self):
        return [(item['idx'], item['display_name'], item['active']) for item in self.describe_llms()]

    def get_llm_name(self):
        if self.llmclient is None:
            return 'No LLM'
        item = self.describe_llms()[self.llm_no]
        return item['display_name']

    def abort(self):
        if not self.is_running: return
        print('Abort current task...')
        self.stop_sig = True
        if self.handler is not None: self.handler.code_stop_signal.append(1)
            
    def put_task(self, query, source="user", images=None):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "images": images or [], "output": display_queue})
        return display_queue

    # i know it is dangerous, but raw_query is dangerous enough it doesn't enlarge
    def _handle_slash_cmd(self, raw_query, display_queue):
        if not raw_query.startswith('/'): return raw_query
        if _sm := re.match(r'/session\.(\w+)=(.*)', raw_query.strip()):
            k, v = _sm.group(1), _sm.group(2)
            vfile = os.path.join(script_dir, 'temp', v)
            if os.path.isfile(vfile): v = open(vfile, encoding='utf-8').read().strip()
            try: v = json.loads(v)  # cover number parsing
            except (json.JSONDecodeError, ValueError): pass
            setattr(self.llmclient.backend, k, v)
            display_queue.put({'done': smart_format(f"✅ session.{k} = {repr(v)}", max_str_len=500), 'source': 'system'})
            return None
        if raw_query.strip() == '/resume':
            return '简单看看model_responses中的最近几次对话结尾部分(除了本次)，分别简单总结一下让我选择，然后你简单阅读了解情况后作为我们接下来聊天的基础'
        return raw_query

    def run(self):
        while True:
            task = self.task_queue.get()
            raw_query, source, images, display_queue = task["query"], task["source"], task.get("images") or [], task["output"]
            raw_query = self._handle_slash_cmd(raw_query, display_queue)
            if raw_query is None:
                self.task_queue.task_done(); continue
            self.is_running = True
            rquery = smart_format(raw_query.replace('\n', ' '), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")
            
            sys_prompt = get_system_prompt() + getattr(self.llmclient.backend, 'extra_sys_prompt', '')
            script_dir = os.path.dirname(os.path.abspath(__file__))
            handler = GenericAgentHandler(self, self.history, os.path.join(script_dir, 'temp'))
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
            # although new handler, the **full** history is in llmclient, so it is full history!
            gen = agent_runner_loop(self.llmclient, sys_prompt, user_input, 
                                handler, TOOLS_SCHEMA, max_turns=40, verbose=self.verbose,
                                initial_user_content=initial_user_content)
            try:
                full_resp = ""; last_pos = 0
                for chunk in gen:
                    if consume_file(self.task_dir, '_stop'): self.abort() 
                    if self.stop_sig: break
                    full_resp += chunk
                    if len(full_resp) - last_pos > 50 or 'LLM Running' in chunk:
                        display_queue.put({'next': full_resp[last_pos:] if self.inc_out else full_resp, 'source': source})
                        last_pos = len(full_resp)
                if self.inc_out and last_pos < len(full_resp): display_queue.put({'next': full_resp[last_pos:], 'source': source})
                if '</summary>' in full_resp: full_resp = full_resp.replace('</summary>', '</summary>\n\n')
                if '</file_content>' in full_resp: full_resp = re.sub(r'<file_content>\s*(.*?)\s*</file_content>', r'\n````\n<file_content>\n\1\n</file_content>\n````', full_resp, flags=re.DOTALL)                
                display_queue.put({'done': full_resp, 'source': source})
                self.history = handler.history_info
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                display_queue.put({'done': full_resp + f'\n```\n{format_error(e)}\n```', 'source': source})
            finally:
                if self.stop_sig:
                    print('User aborted the task.')
                    #with self.task_queue.mutex: self.task_queue.queue.clear()
                self.is_running = self.stop_sig = False
                self.task_queue.task_done()
                if self.handler is not None: self.handler.code_stop_signal.append(1)

    
if __name__ == '__main__':
    import argparse
    from datetime import datetime
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', metavar='IODIR', help='一次性任务模式(文件IO)')
    parser.add_argument('--reflect', metavar='SCRIPT', help='反射模式：加载监控脚本，check()触发时发任务')
    parser.add_argument('--input', help='prompt')
    parser.add_argument('--llm_no', type=int, default=0)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--bg', action='store_true', help='popen, print PID, exit')
    args = parser.parse_args()

    if args.bg:
        import subprocess, platform
        cmd = [sys.executable, os.path.abspath(__file__)] + [a for a in sys.argv[1:] if a != '--bg']
        d = os.path.join(script_dir, f'temp/{args.task}'); os.makedirs(d, exist_ok=True)
        p = subprocess.Popen(cmd, cwd=script_dir,
            creationflags=0x08000000 if platform.system() == 'Windows' else 0,
            stdout=open(os.path.join(d, 'stdout.log'), 'w', encoding='utf-8'),
            stderr=open(os.path.join(d, 'stderr.log'), 'w', encoding='utf-8'))
        print(p.pid); sys.exit(0)

    agent = GeneraticAgent()
    agent.next_llm(args.llm_no)
    agent.verbose = args.verbose
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        agent.task_dir = d = os.path.join(script_dir, f'temp/{args.task}'); nround = ''
        infile = os.path.join(d, 'input.txt')
        if args.input:
            os.makedirs(d, exist_ok=True)
            import glob; [os.remove(f) for f in glob.glob(os.path.join(d, 'output*.txt'))]
            with open(infile, 'w', encoding='utf-8') as f: f.write(args.input)
        with open(infile, encoding='utf-8') as f: raw = f.read()
        while True:
            dq = agent.put_task(raw, source='task')
            while 'done' not in (item := dq.get(timeout=120)): 
                if 'next' in item and random.random() < 0.95:  # 概率写一次中间结果
                    with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item.get('next', ''))
            with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item['done'] + '\n\n[ROUND END]\n')
            consume_file(d, '_stop')  # 已经成功停下来了，避免打断下次reply
            for _ in range(300):  # 等reply.txt，10分钟超时
                time.sleep(2)
                if (raw := consume_file(d, 'reply.txt')): break
            else: break
            nround = nround + 1 if isinstance(nround, int) else 1
    elif args.reflect:
        import importlib.util
        spec = importlib.util.spec_from_file_location('reflect_script', args.reflect)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        _mt = os.path.getmtime(args.reflect)
        print(f'[Reflect] loaded {args.reflect}')
        while True:
            if os.path.getmtime(args.reflect) != _mt:
                try: spec.loader.exec_module(mod); _mt = os.path.getmtime(args.reflect); print('[Reflect] reloaded')
                except Exception as e: print(f'[Reflect] reload error: {e}')
            time.sleep(getattr(mod, 'INTERVAL', 5))
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
                if getattr(mod, 'ONCE', False): raise
                print(f'[Reflect] drain error: {e}'); result = f'[ERROR] {e}'
            log_dir = os.path.join(script_dir, 'temp/reflect_logs'); os.makedirs(log_dir, exist_ok=True)
            script_name = os.path.splitext(os.path.basename(args.reflect))[0]
            open(os.path.join(log_dir, f'{script_name}_{datetime.now():%Y-%m-%d}.log'), 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}]\n{result}\n\n')
            if (on_done := getattr(mod, 'on_done', None)):
                try: on_done(result)
                except Exception as e: print(f'[Reflect] on_done error: {e}')
            if getattr(mod, 'ONCE', False): print('[Reflect] ONCE=True, exiting.'); break
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
