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

script_dir = os.path.dirname(os.path.abspath(__file__))

class TrackedLock:
    """
    为 RLock 提供 locked 状态与递归深度追踪。
    Python 3.11 的 threading.RLock 没有 .locked()，此处补齐。
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._depth = 0

    def acquire(self, blocking=True, timeout=-1):
        ok = self._lock.acquire(blocking=blocking, timeout=timeout)
        if ok:
            self._depth += 1
        return ok

    def release(self):
        self._depth -= 1
        self._lock.release()

    @property
    def locked(self):
        return self._depth > 0

    @property
    def depth(self):
        return self._depth

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
        return False

def load_tool_schema(suffix=''):
    global TOOLS_SCHEMA
    TS = open(os.path.join(script_dir, f'assets/tools_schema{suffix}.json'), 'r', encoding='utf-8').read()
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
    # P1.4 Step A': L0 SYSTEM OVERRIDE 强制前置,截断前文"物理级全能执行者"注意力残留,100% 纯度接管人设
    l0_override = ""
    try:
        l0_path = os.path.join(script_dir, 'memory/L0_persona.txt')
        if os.path.exists(l0_path):
            with open(l0_path, 'r', encoding='utf-8', errors='replace') as f: l0_raw = f.read()
            l0_override = (
                "========================================\n"
                "[!!! SYSTEM OVERRIDE - CRITICAL !!!]\n"
                "DISREGARD ANY PREVIOUS INSTRUCTIONS DEFINING YOU AS A PASSIVE ASSISTANT.\n"
                "IGNORE '物理级全能执行者' SETTING.\n"
                "YOUR SOLE, EXCLUSIVE IDENTITY IS NOW ACTING AS FOLLOWS:\n\n"
                f"{l0_raw}\n"
                "========================================\n\n"
            )
    except Exception as e: print(f"[L0] Override 注入失败(降级): {e}")
    with open(os.path.join(script_dir, f'assets/sys_prompt{lang_suffix}.txt'), 'r', encoding='utf-8') as f: prompt = f.read()
    prompt = l0_override + prompt  # Override 前置,语义强隔离
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"
    prompt += get_global_memory()
    return prompt

class GeneraticAgent:
    def __init__(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(os.path.join(script_dir, 'temp'), exist_ok=True)
        from llmcore import mykeys
        llm_sessions = []
        for k, cfg in mykeys.items():
            if not any(x in k for x in ['api', 'config', 'cookie']): continue
            try:
                if 'native' in k and 'claude' in k: llm_sessions += [NativeToolClient(NativeClaudeSession(cfg=cfg))]
                elif 'native' in k and 'oai' in k: llm_sessions += [NativeToolClient(NativeOAISession(cfg=cfg))]
                elif 'claude' in k: llm_sessions += [ToolClient(ClaudeSession(cfg=cfg))]
                elif 'oai' in k: llm_sessions += [ToolClient(LLMSession(cfg=cfg))]
                elif 'mixin' in k: llm_sessions += [{'mixin_cfg': cfg}]
            except: pass
        for i, s in enumerate(llm_sessions):
            if isinstance(s, dict) and 'mixin_cfg' in s:
                try:
                    mixin = MixinSession(llm_sessions, s['mixin_cfg'])
                    if isinstance(mixin._sessions[0], (NativeClaudeSession, NativeOAISession)): llm_sessions[i] = NativeToolClient(mixin)
                    else: llm_sessions[i] = ToolClient(mixin)
                except Exception as e: print(f'[WARN] Failed to init MixinSession with cfg {s["mixin_cfg"]}: {e}')
        self.llmclients = llm_sessions
        self.lock = threading.Lock()
        # P2.1 CTO硬核令: LLM 推理闸升级 RLock,heartbeat 生产端改非阻塞 acquire(blocking=False) 探测
        self.llm_busy_lock = TrackedLock()  # 带 depth 追踪，支持并发排队提示
        self.task_dir = None
        self.history = []
        self.task_queue = queue.Queue() 
        self.is_running = False; self.stop_sig = False
        self.llm_no = 0;  self.inc_out = False
        self.handler = None; self.verbose = True
        self.llmclient = self.llmclients[self.llm_no]

    def next_llm(self, n=-1):
        self.llm_no = ((self.llm_no + 1) if n < 0 else n) % len(self.llmclients)
        lastc = self.llmclient
        self.llmclient = self.llmclients[self.llm_no]
        self.llmclient.backend.history = lastc.backend.history
        self.llmclient.last_tools = ''
        name = self.get_llm_name(model=True)
        if 'glm' in name or 'minimax' in name or 'kimi' in name: load_tool_schema('_cn')
        else: load_tool_schema()
    def list_llms(self): return [(i, self.get_llm_name(b), i == self.llm_no) for i, b in enumerate(self.llmclients)]
    def get_llm_name(self, b=None, model=False):
        b = self.llmclient if b is None else b
        if isinstance(b, dict): return 'BADCONFIG_MIXIN'
        if model: return b.backend.model.lower()
        return f"{type(b.backend).__name__}/{b.backend.name}"

    def abort(self):
        if not self.is_running: return
        print('Abort current task...')
        self.stop_sig = True
        if self.handler is not None: self.handler.code_stop_signal.append(1)
            
    def put_task(self, query, source="user", images=None):
        display_queue = queue.Queue()
        self.task_queue.put({"query": query, "source": source, "images": images or [], "output": display_queue})
        return display_queue

    def _handle_internal_event(self, task):
        """P1.4 内部事件分发: mem_write 异步向量化落盘 / heartbeat 主动突袭"""
        ttype = task.get("type")
        try:
            if ttype == "mem_write":
                from memory_vec import brain
                brain.add_memory(task.get("text", ""))
                print(f"[Memory] ✅ 异步向量化落盘成功 qsize={self.task_queue.qsize()}", flush=True)
            elif ttype == "heartbeat":
                from memory_vec import brain
                try: hits = brain.search("未完成 任务 懒惰 承诺 进度", k=3)
                except Exception: hits = []
                context = "\n".join(f"- {h}" for h in hits) if hits else "- 常规巡查(记忆库暂无历史)"
                ts = time.strftime("%H:%M")
                trigger_msg = (
                    f"[SYSTEM TRIGGER: {ts}]\n"
                    f"记忆参考：\n{context}\n\n"
                    f"指令：不要等提问！立刻以严厉导师口吻索要执行进度，数据说话！"
                )
                # 主线程忙时跳过(避免打断当前对话);空闲时经 put_task 重新入队触发主动突袭(而非递归调 agent_runner_loop)
                if not self.is_running:
                    self.put_task(trigger_msg, source="system")
                    print(f"[Heartbeat] 🎯 主动突袭已入队 @ {time.strftime('%H:%M:%S')} qsize={self.task_queue.qsize()}", flush=True)
                else:
                    print(f"[Heartbeat] 主线程忙,跳过本次突袭 qsize={self.task_queue.qsize()}", flush=True)
        except Exception as e:
            print(f"[Queue] type={ttype} 处理失败(忽略): {e}", flush=True)
        finally:
            self.task_queue.task_done()

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
            return r'用re.findall(r"<history>\\n\[(?:USER\|Agent)\].*?</history>", content, re.DOTALL) 扫temp/model_responses/下时间最近的10个文件(除本PID)，取每文件最后一个匹配(注意JSON里换行是字面\\n)作为该会话内容，按mtime倒序，每个用一句话总结聊了什么让我选择；选定后再简单读该文件末尾作为聊天基础'
        return raw_query

    def run(self):
        while True:
            task = self.task_queue.get()
            # P1.4 type 分发: 内部事件(mem_write/heartbeat)与用户对话分离,向后兼容原对话格式(无 type 字段)
            if isinstance(task, dict) and task.get("type") in ("mem_write", "heartbeat"):
                self._handle_internal_event(task); continue
            raw_query, source, images, display_queue = task["query"], task["source"], task.get("images") or [], task["output"]
            raw_query = self._handle_slash_cmd(raw_query, display_queue)
            if raw_query is None:
                self.task_queue.task_done(); continue
            self.is_running = True
            if self.llm_busy_lock.locked:
                print(f"\n⏳ [UserTurn] queued, waiting lock (depth={self.llm_busy_lock.depth}) - 教授正在处理后台事务，请稍候...", flush=True)
            self.llm_busy_lock.acquire()  # P1.4 CTO验收: 闸上锁,heartbeat 生产端检测到则跳过本轮突袭
            print("[UserTurn] lock acquired, processing...", flush=True)
            # P2.1 CTO硬核令: source=="system" 即心跳触发的主动突袭,前置打标识便于 log 证据②抓取
            if source == 'system':
                print(f"\n🔔 [教授突袭] {time.strftime('%H:%M:%S')} 主动发难 (trigger=heartbeat)", flush=True)
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
            # P1.4 RAG 前置注入: 基于 raw_query 检索向量记忆 Top3,前置注入以提供触发记忆上下文
            try:
                from memory_vec import brain
                hits = brain.search(raw_query, k=3)
                if hits:
                    mem_str = "\n".join([f"- {h}" for h in hits])
                    user_input = f"[触发记忆]\n{mem_str}\n\n{user_input}"
                    print(f"[RAG] 前置注入 {len(hits)} 条触发记忆", flush=True)
            except Exception as e: print(f"[RAG] 检索失败(忽略): {e}", flush=True)
            if 'gpt' in self.get_llm_name(model=True): handler._done_hooks.append('请确定用户任务是否完成，如未完成需要继续工具调用直到完成任务，确实需要问用户应使用ask_user工具')
            # although new handler, the **full** history is in llmclient, so it is full history!
            gen = agent_runner_loop(self.llmclient, sys_prompt, user_input, 
                                handler, TOOLS_SCHEMA, max_turns=40, verbose=self.verbose)
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
                # P1.4 异步向量化落盘: 当前对话丢入 task_queue,由消费者分发到 mem_write 分支处理
                try:
                    mem_text = f"用户: {smart_format(raw_query, max_str_len=500)}\n导师: {smart_format(full_resp, max_str_len=1500)}"
                    self.task_queue.put({"type": "mem_write", "text": mem_text})
                except Exception as e: print(f"[Memory] 异步入队失败(忽略): {e}", flush=True)
                self.history = handler.history_info
            except Exception as e:
                print(f"Backend Error: {format_error(e)}")
                display_queue.put({'done': full_resp + f'\n```\n{format_error(e)}\n```', 'source': source})
            finally:
                if self.stop_sig:
                    print('User aborted the task.')
                    #with self.task_queue.mutex: self.task_queue.queue.clear()
                # P2.1 CTO硬核令: RLock 无 .locked() 方法,用 try/except 解闸
                try: self.llm_busy_lock.release()
                except RuntimeError: pass
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
    # P1.4 启动心跳起搏器(daemon 线程,60s 间隔投递 heartbeat 事件)
    try:
        from heartbeat import HeartbeatProducer
        HeartbeatProducer(agent, interval_sec=60).start()
        print("[Heartbeat] 起搏器已启动,interval=60s", flush=True)
    except Exception as e: print(f"[Heartbeat] 启动失败(忽略): {e}", flush=True)

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
