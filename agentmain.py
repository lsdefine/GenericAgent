import os, sys, threading, queue, time, json, re, random
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
elif hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(errors='replace')
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
elif hasattr(sys.stderr, 'reconfigure'): sys.stderr.reconfigure(errors='replace')
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sidercall import SiderLLMSession, LLMSession, ToolClient, ClaudeSession, XaiSession
from agent_loop import agent_runner_loop, StepOutcome, BaseHandler
from ga import GenericAgentHandler, smart_format, get_global_memory, format_error

with open('assets/tools_schema.json', 'r', encoding='utf-8') as f:
    TS = f.read()
    TOOLS_SCHEMA = json.loads(TS if os.name == 'nt' else TS.replace('powershell', 'bash'))

def get_system_prompt():
    if not os.path.exists('memory'): os.makedirs('memory')
    if not os.path.exists('memory/global_mem.txt'):
        with open('memory/global_mem.txt', 'w', encoding='utf-8') as f: f.write('')
    if not os.path.exists('memory/global_mem_insight.txt'):
        t = 'assets/global_mem_insight_template.txt'
        open('memory/global_mem_insight.txt', 'w', encoding='utf-8').write(open(t, encoding='utf-8').read() if os.path.exists(t) else '')
    with open('assets/sys_prompt.txt', 'r', encoding='utf-8') as f: prompt = f.read()
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    return prompt

class GeneraticAgent:
    def __init__(self):
        if not os.path.exists('temp'): os.makedirs('temp')
        from sidercall import mykeys
        llm_sessions = []
        for k, cfg in mykeys.items():
            if not any(x in k for x in ['api', 'config', 'cookie']): continue
            try:
                if 'claude' in k: llm_sessions += [ClaudeSession(api_key=cfg['apikey'], api_base=cfg['apibase'], model=cfg['model'])]
                if 'oai' in k: llm_sessions += [LLMSession(
                    api_key=cfg['apikey'], api_base=cfg['apibase'], model=cfg['model'], proxy=cfg.get('proxy'),
                    api_mode=cfg.get('api_mode', 'chat_completions'),
                    max_retries=cfg.get('max_retries', 2),
                    connect_timeout=cfg.get('connect_timeout', 10),
                    read_timeout=cfg.get('read_timeout', 120),
                )]
                if 'xai' in k: llm_sessions += [XaiSession(cfg, mykeys.get('proxy', ''))]
                if 'sider' in k: llm_sessions += [SiderLLMSession(cfg, default_model=x) for x in \
                                    ["gemini-3.0-flash", "claude-haiku-4.5"]]
            except: pass
        if len(llm_sessions) > 0: self.llmclient = ToolClient(llm_sessions, auto_save_tokens=True)
        else: self.llmclient = None
        self.lock = threading.Lock()
        self.history = []               
        self.task_queue = queue.Queue() 
        self.is_running, self.stop_sig = False, False
        self.llm_no = 0
        self.inc_out = False
        self.handler = None
        self.verbose = True

    def next_llm(self, n=-1):
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclient.backends)
        self.llmclient.last_tools = ''
    def list_llms(self): return [(i, f"{type(b).__name__}/{b.default_model}", i == self.llm_no) for i, b in enumerate(self.llmclient.backends)]
    def get_llm_name(self):
        b = self.llmclient.backends[self.llm_no]
        return f"{type(b).__name__}/{b.default_model}"

    def abort(self):
        print('Abort current task...')
        if not self.is_running: return
        self.stop_sig = True
        if self.handler is not None: 
            self.handler.code_stop_signal.append(1)
            
    def put_task(self, query, source="user"):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "output": display_queue})
        return display_queue

    def run(self):
        while True:
            task = self.task_queue.get()
            self.is_running = True
            raw_query, source, display_queue = task["query"], task["source"], task["output"]
            rquery = smart_format(raw_query.replace('\n', ' '), max_str_len=200)
            self.history.append(f"[USER]: {rquery}")
            
            sys_prompt = get_system_prompt()
            handler = GenericAgentHandler(None, self.history, './temp')
            if self.handler and self.handler.key_info: 
                handler.key_info = self.handler.key_info
                if '清除工作记忆' not in handler.key_info:
                    handler.key_info += '\n[SYSTEM] 如果是新任务，请先更新或清除工作记忆\n'
            self.handler = handler
            self.llmclient.backend = self.llmclient.backends[self.llm_no]
            # 如果有历史记录，注入到首轮 user_input 中
            user_input = raw_query
            if len(self.history) > 1:  # 至少有之前的对话记录
                h_str = "\n".join(self.history[-20:])
                user_input = f"### [WORKING MEMORY]\n<history>\n{h_str}\n</history>\n\n### 用户当前消息\n{raw_query}"
            gen = agent_runner_loop(self.llmclient, sys_prompt, user_input, 
                                handler, TOOLS_SCHEMA, max_turns=40, verbose=self.verbose)
            try:
                full_resp = ""; last_pos = 0
                for chunk in gen:
                    if self.stop_sig: break
                    full_resp += chunk
                    if len(full_resp) - last_pos > 50:
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
    agent.llm_no = args.llm_no
    agent.verbose = False
    threading.Thread(target=agent.run, daemon=True).start()

    if args.task:
        d = f'temp/{args.task}'; rp = f'{d}/reply.txt'; nround = ''
        with open(f'{d}/input.txt', encoding='utf-8') as f: raw = f.read()
        while True:
            dq = agent.put_task(raw, source='task')
            while 'done' not in (item := dq.get(timeout=120)): 
                if 'next' in item and random.random() < 0.95:  # 概率写一次中间结果
                    with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item.get('next', ''))
            with open(f'{d}/output{nround}.txt', 'w', encoding='utf-8') as f: f.write(item['done'] + '\n[ROUND END]\n')
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
            except Exception as e:
                if once: raise
                print(f'[Reflect] drain error: {e}'); result = f'[ERROR] {e}'
            open('./temp/reflect.log', 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}]\n{result}\n\n')
            if on_done:
                try: on_done(result)
                except Exception as e: print(f'[Reflect] on_done error: {e}')
            if once: print('[Reflect] ONCE=True, exiting.'); break
    elif args.scheduled: 
        def drain(dq, tag):
            while 'done' not in (item := dq.get()): pass
            open('./temp/scheduler.log', 'a', encoding='utf-8').write(f'[{datetime.now():%m-%d %H:%M}] {tag}\n{item["done"]}\n\n')
        while True:
            time.sleep(55 + random.random() * 10)
            now = datetime.now()
            if not os.path.isdir('./sche_tasks/pending'): continue
            for f in os.listdir('./sche_tasks/pending'):
                m = re.match(r'(\d{4}-\d{2}-\d{2})_(\d{4})_', f)
                if m and now >= datetime.strptime(f'{m[1]} {m[2]}', '%Y-%m-%d %H%M'):
                    raw = open(f'./sche_tasks/pending/{f}', encoding='utf-8').read()
                    dq = agent.put_task(f'按scheduled_task_sop执行任务文件 ../sche_tasks/pending/{f}（立刻移到running）\n内容：\n{raw}', source='scheduler')
                    threading.Thread(target=drain, args=(dq, f), daemon=True).start()
                    break
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
