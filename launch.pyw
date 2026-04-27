import threading, subprocess, sys, time, os, ctypes, atexit, socket, random, webbrowser, urllib.request

WINDOW_WIDTH, WINDOW_HEIGHT, RIGHT_PADDING, TOP_PADDING = 600, 900, 0, 100

script_dir = os.path.dirname(os.path.abspath(__file__))
frontends_dir = os.path.join(script_dir, "frontends")
window = proc = None

def find_free_port(lo=18501, hi=18599):
    ports = list(range(lo, hi+1)); random.shuffle(ports)
    for p in ports:
        try: s = socket.socket(); s.bind(('127.0.0.1', p)); s.close(); return p
        except OSError: continue
    raise RuntimeError(f'No free port in {lo}-{hi}')

def get_screen_width():
    try: return ctypes.windll.user32.GetSystemMetrics(0)
    except: return 1920

def start_streamlit(port):
    global proc
    cmd = [sys.executable, "-m", "streamlit", "run", os.path.join(frontends_dir, "stapp.py"), "--server.port", str(port), "--server.address", "localhost", "--server.headless", "true"]
    proc = subprocess.Popen(cmd)
    atexit.register(proc.kill)

def wait_for_streamlit(url, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5): return True
        except Exception: time.sleep(0.5)
    return False

def keep_streamlit_alive():
    try:
        while proc and proc.poll() is None: time.sleep(1)
    except KeyboardInterrupt:
        if proc and proc.poll() is None: proc.kill()

def open_browser_mode(port, reason=None):
    url = f'http://localhost:{port}'
    if reason: print(f'[Launch] Native window unavailable: {reason}')
    wait_for_streamlit(url)
    print(f'[Launch] Opening browser: {url}')
    webbrowser.open(url)
    keep_streamlit_alive()

def inject(text):
    window.evaluate_js(f"""
        const textarea = document.querySelector('textarea[data-testid="stChatInputTextArea"]');
        if (textarea) {{
            // 1. 用原生 setter 设置值（绕过 React）
            const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
            nativeTextAreaValueSetter.call(textarea, {repr(text)});
            // 2. 触发 React 的 input 事件
            textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
            // 3. 触发 change 事件（有些组件需要）
            textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
            // 4. 延迟提交
            setTimeout(() => {{
                const btn = document.querySelector('[data-testid="stChatInputSubmitButton"]');
                if (btn) {{btn.click();console.log('Submitted:', {repr(text)});}}
            }}, 200);
        }}""")

def get_last_reply_time():
    last = window.evaluate_js("""
        const el = document.getElementById('last-reply-time');
        el ? parseInt(el.textContent) : 0;
    """) or 0
    return last or int(time.time())

PASTE_HOOK_JS = """if (!window._pasteHooked) { window._pasteHooked = true;
    document.addEventListener('paste', e => {
        const items = e.clipboardData?.items; if (!items) return;
        let t = null;
        for (const item of items) { if (item.kind === 'file') { t = item.type.startsWith('image/') ? 'image in clipboard, ' : 'file in clipboard, '; break; } }
        if (!t) return;
        e.preventDefault(); e.stopImmediatePropagation();
        const el = document.querySelector('textarea[data-testid="stChatInputTextArea"]') || document.activeElement;
        if (el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT')) {
            const s = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            s.call(el, el.value + t); el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }, true);
}"""

def idle_monitor(stop_event=None):
    last_trigger_time = 0
    while True:
        if stop_event and stop_event.is_set(): return
        time.sleep(5)
        try:
            window.evaluate_js(PASTE_HOOK_JS)
            now = time.time()
            if now - last_trigger_time < 120: continue
            last_reply = get_last_reply_time()
            if now - last_reply > 1800:
                print('[Idle Monitor] Detected idle state, injecting task...')
                inject("[AUTO]🤖 用户已经离开超过30分钟，作为自主智能体，请阅读自动化sop，执行自动任务。")
                last_trigger_time = now
        except Exception as e:
            print(f'[Idle Monitor] Error: {e}')

def start_native_window(port):
    global window
    if os.name == 'nt': os.environ.setdefault('PYTHONNET_RUNTIME', 'coreclr')
    import webview
    if os.name == 'nt':
        screen_width = get_screen_width()
        x_pos = screen_width - WINDOW_WIDTH - RIGHT_PADDING
    else: x_pos = 100
    time.sleep(2)
    window = webview.create_window(
        title='GenericAgent', url=f'http://localhost:{port}',
        width=WINDOW_WIDTH, height=WINDOW_HEIGHT, x=x_pos, y=TOP_PADDING,
        resizable=True, text_select=True)
    monitor_stop = threading.Event()
    monitor_thread = threading.Thread(target=idle_monitor, args=(monitor_stop,), daemon=True)
    monitor_thread.start()
    try: webview.start()
    except Exception:
        monitor_stop.set()
        raise

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('port', nargs='?', default='0'); 
    parser.add_argument('--browser', action='store_true', help='Open Streamlit in the default browser')
    parser.add_argument('--tg', action='store_true', help='启动 Telegram Bot'); 
    parser.add_argument('--qq', action='store_true', help='启动 QQ Bot');
    parser.add_argument('--feishu', '--fs', dest='feishu', action='store_true', help='启动 Feishu Bot');
    parser.add_argument('--wecom', action='store_true', help='启动 WeCom Bot');
    parser.add_argument('--dingtalk', '--dt', dest='dingtalk', action='store_true', help='启动 DingTalk Bot');
    parser.add_argument('--sched', action='store_true', help='启动计划任务调度器')
    parser.add_argument('--llm_no', type=int, default=0, help='LLM编号')
    args = parser.parse_args()
    port = str(find_free_port()) if args.port == '0' else args.port
    print(f'[Launch] Using port {port}')
    threading.Thread(target=start_streamlit, args=(port,), daemon=True).start()

    if args.tg:
        tgproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "tgapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(tgproc.kill)
        print('[Launch] Telegram Bot started')
    else: print('[Launch] Telegram Bot not enabled (use --tg to start)')

    if args.qq:
        qqproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "qqapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(qqproc.kill)
        print('[Launch] QQ Bot started')
    else: print('[Launch] QQ Bot not enabled (use --qq to start)')

    if args.feishu:
        fsproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "fsapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(fsproc.kill)
        print('[Launch] Feishu Bot started')
    else: print('[Launch] Feishu Bot not enabled (use --feishu to start)')

    if args.wecom:
        wcproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "wecomapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(wcproc.kill)
        print('[Launch] WeCom Bot started')
    else: print('[Launch] WeCom Bot not enabled (use --wecom to start)')

    if args.dingtalk:
        dtproc = subprocess.Popen([sys.executable, os.path.join(frontends_dir, "dingtalkapp.py")], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(dtproc.kill)
        print('[Launch] DingTalk Bot started')
    else: print('[Launch] DingTalk Bot not enabled (use --dingtalk to start)')
    
    if args.sched:
        scheduler_proc = subprocess.Popen([sys.executable, os.path.join(script_dir, "agentmain.py"), "--reflect", os.path.join(script_dir, "reflect", "scheduler.py"), "--llm_no", str(args.llm_no)], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atexit.register(scheduler_proc.kill)
        print('[Launch] Task Scheduler started (duplicate prevented by scheduler port lock)')
    else: print('[Launch] Task Scheduler not enabled (--sched)')

    if args.browser: open_browser_mode(port)
    else:
        try: start_native_window(port)
        except Exception as e: open_browser_mode(port, e)
