import sys, os, re, json, time, threading
from datetime import datetime
from pathlib import Path
import tempfile, traceback, subprocess, itertools, collections
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent_loop import BaseHandler, StepOutcome, try_call_generator

def code_run(code, code_type="python", timeout=60, cwd=None, code_cwd=None, stop_signal=[]):
    """代码执行器
    python: 运行复杂的 .py 脚本（文件模式）
    powershell/bash: 运行单行指令（命令模式）
    优先使用python，仅在必要系统操作时使用powershell。
    """
    preview = (code[:60].replace('\n', ' ') + '...') if len(code) > 60 else code.strip()
    yield f"[Action] Running {code_type} in {os.path.basename(cwd)}: {preview}\n"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    cwd = cwd or os.path.join(script_dir, 'temp'); tmp_path = None
    if code_type == "python":
        tmp_file = tempfile.NamedTemporaryFile(suffix=".ai.py", delete=False, mode='w', encoding='utf-8', dir=code_cwd)
        cr_header = os.path.join(script_dir, 'assets', 'code_run_header.py')
        if os.path.exists(cr_header): tmp_file.write(open(cr_header, encoding='utf-8').read())
        tmp_file.write(code)
        tmp_path = tmp_file.name
        tmp_file.close()
        cmd = [sys.executable, "-X", "utf8", "-u", tmp_path]   
    elif code_type in ["powershell", "bash"]:
        if os.name == 'nt': cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", code]
        else: cmd = ["bash", "-c", code]
    else:
        return {"status": "error", "msg": f"不支持的类型: {code_type}"}
    print("code run output:") 
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE
    full_stdout = []

    def stream_reader(proc, logs):
        for line_bytes in iter(proc.stdout.readline, b''):
            try: line = line_bytes.decode('utf-8')
            except UnicodeDecodeError: line = line_bytes.decode('gbk', errors='ignore')
            logs.append(line)
            try: print(line, end="") 
            except: pass

    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, cwd=cwd, startupinfo=startupinfo
        )
        start_t = time.time()
        t = threading.Thread(target=stream_reader, args=(process, full_stdout), daemon=True)
        t.start()

        while t.is_alive():
            istimeout = time.time() - start_t > timeout
            if istimeout or len(stop_signal) > 0:
                process.kill()
                print("[Debug] Process killed due to timeout or stop signal.")
                if istimeout: full_stdout.append("\n[Timeout Error] 超时强制终止")
                else: full_stdout.append("\n[Stopped] 用户强制终止")
                break
            time.sleep(1)

        t.join(timeout=1)
        exit_code = process.poll()

        stdout_str = "".join(full_stdout)
        status = "success" if exit_code == 0 else "error"
        status_icon = "✅" if exit_code == 0 else "❌"
        if exit_code is None: status_icon = "⏳" 
        output_snippet = smart_format(stdout_str, max_str_len=600, omit_str='\n[omitted long output]\n')
        yield f"[Status] {status_icon} Exit Code: {exit_code}\n[Stdout]\n{output_snippet}\n"
        if process.stdout: threading.Thread(target=process.stdout.close, daemon=True).start()
        return {
            "status": status,
            "stdout": smart_format(stdout_str, max_str_len=8000, omit_str='\n[omitted long output]\n'),
            "exit_code": exit_code
        }
    except Exception as e:
        if 'process' in locals(): process.kill()
        return {"status": "error", "msg": str(e)}
    finally:
        if code_type == "python" and tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)


def ask_user(question: str, candidates: list = None):
    """question: 向用户提出的问题。candidates: 可选的候选项列表。需要保证should_exit为True
    """
    return {"status": "INTERRUPT", "intent": "HUMAN_INTERVENTION",
        "data": {"question": question, "candidates": candidates or []}}

from simphtml import execute_js_rich, get_html

driver = None

def first_init_driver():
    global driver
    from TMWebDriver import TMWebDriver
    driver = TMWebDriver()
    for i in range(20):
        time.sleep(1)
        sess = driver.get_all_sessions()
        if len(sess) > 0: break
    if len(sess) == 0: return 
    if len(sess) == 1: 
        #driver.newtab()
        time.sleep(3)

def web_scan(tabs_only=False, switch_tab_id=None, text_only=False):
    """
    获取当前页面的简化HTML内容和标签页列表。注意：简化过程会过滤边栏、浮动元素等非主体内容。
    tabs_only: 仅返回标签页列表，不获取HTML内容（节省token）。
    switch_tab_id: 可选参数，如果提供，则在扫描前切换到该标签页。
    应当多用execute_js，少全量观察html。
    """
    global driver
    try:
        if driver is None: first_init_driver()
        if len(driver.get_all_sessions()) == 0:
            return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        tabs = []
        for sess in driver.get_all_sessions(): 
            sess.pop('connected_at', None)
            sess.pop('type', None)
            sess['url'] = sess.get('url', '')[:50] + ("..." if len(sess.get('url', '')) > 50 else "")
            tabs.append(sess)
        if switch_tab_id: driver.default_session_id = switch_tab_id
        result = {
            "status": "success",
            "metadata": {
                "tabs_count": len(tabs), "tabs": tabs,
                "active_tab": driver.default_session_id
            }
        }
        if not tabs_only: result["content"] = get_html(driver, cutlist=True, maxchars=28000, text_only=text_only)
        return result
    except Exception as e:
        return {"status": "error", "msg": format_error(e)}
    
def format_error(e):
    exc_type, exc_value, exc_traceback = sys.exc_info()
    tb = traceback.extract_tb(exc_traceback)
    if tb:
        f = tb[-1]
        fname = os.path.basename(f.filename)
        return f"{exc_type.__name__}: {str(e)} @ {fname}:{f.lineno}, {f.name} -> `{f.line}`"
    return f"{exc_type.__name__}: {str(e)}"

def log_memory_access(path):
    if 'memory' not in path: return
    script_dir = os.path.dirname(os.path.abspath(__file__))
    stats_file = os.path.join(script_dir, 'memory/file_access_stats.json')
    try:
        with open(stats_file, 'r', encoding='utf-8') as f: stats = json.load(f)
    except: stats = {}
    fname = os.path.basename(path)
    stats[fname] = {'count': stats.get(fname, {}).get('count', 0) + 1, 'last': datetime.now().strftime('%Y-%m-%d')}
    with open(stats_file, 'w', encoding='utf-8') as f: json.dump(stats, f, indent=2, ensure_ascii=False)

def web_execute_js(script, switch_tab_id=None, no_monitor=False):
    """
    执行 JS 脚本来控制浏览器，并捕获结果和页面变化。
    script: 要执行的 JavaScript 代码字符串。
    return {
        "status": "failed" if error_msg else "success",
        "js_return": result,
        "error": error_msg,
        "transients": transients, 
        "environment": {
            "newTabs": [],
            "reloaded": reloaded
        },
        "diff": diff_summary,
    }
    """
    global driver
    try:
        if driver is None: first_init_driver()
        if len(driver.get_all_sessions()) == 0: return {"status": "error", "msg": "没有可用的浏览器标签页，查L3记忆分析原因。"}
        if switch_tab_id: driver.default_session_id = switch_tab_id
        result = execute_js_rich(script, driver, no_monitor=no_monitor)
        return result
    except Exception as e:
        return {"status": "error", "msg": format_error(e)}

def expand_file_refs(text, base_dir=None):
    """展开文本中的 {{file:路径:起始行:结束行}} 引用为实际文件内容。
    可与普通文本混排。展开失败抛 ValueError。
    base_dir: 相对路径的基准目录，默认为进程 cwd。"""
    pattern = r'\{\{file:(.+?):(\d+):(\d+)\}\}'
    def replacer(match):
        path, start, end = match.group(1), int(match.group(2)), int(match.group(3))
        path = os.path.abspath(os.path.join(base_dir or '.', path))
        if not os.path.isfile(path): raise ValueError(f"引用文件不存在: {path}")
        with open(path, 'r', encoding='utf-8') as f: lines = f.readlines()
        if start < 1 or end > len(lines) or start > end: raise ValueError(f"行号越界: {path} 共{len(lines)}行, 请求{start}-{end}")
        return ''.join(lines[start-1:end])
    return re.sub(pattern, replacer, text)
    
def file_patch(path: str, old_content: str, new_content: str):
    """在文件中寻找唯一的 old_content 块并替换为 new_content。
    """
    path = str(Path(path).resolve())
    try:
        if not os.path.exists(path): return {"status": "error", "msg": "文件不存在"}
        with open(path, 'r', encoding='utf-8') as f: full_text = f.read()
        if not old_content: return {"status": "error", "msg": "old_content 为空，请确认 arguments"}
        count = full_text.count(old_content)
        if count == 0: return {"status": "error", "msg": "未找到匹配的旧文本块，建议：先用 file_read 确认当前内容，再分小段进行 patch。若多次失败则询问用户，严禁自行使用 overwrite 或代码替换。"}
        if count > 1: return {"status": "error", "msg": f"找到 {count} 处匹配，无法确定唯一位置。请提供更长、更具体的旧文本块以确保唯一性。建议：包含上下文行来增强特征，或分小段逐个修改。"}
        updated_text = full_text.replace(old_content, new_content)
        with open(path, 'w', encoding='utf-8') as f: f.write(updated_text)
        return {"status": "success", "msg": "文件局部修改成功"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}

def file_read(path, start=1, keyword=None, count=200, show_linenos=True):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            stream = ((i, l.rstrip('\r\n')) for i, l in enumerate(f, 1))
            stream = itertools.dropwhile(lambda x: x[0] < start, stream)
            if keyword:
                before = collections.deque(maxlen=count//3)
                for i, l in stream:
                    if keyword.lower() in l.lower():
                        res = list(before) + [(i, l)] + list(itertools.islice(stream, count - len(before) - 1))
                        break
                    before.append((i, l))
                else: return f"Keyword '{keyword}' not found after line {start}. Falling back to content from line {start}:\n\n" \
                               + file_read(path, start, None, count, show_linenos)
            else: res = list(itertools.islice(stream, count))
            realcnt = len(res); L_MAX = max(100, 512000//realcnt); TAG = " ... [TRUNCATED]"
            remaining = sum(1 for _ in itertools.islice(stream, 5000))
            total_lines = (start - 1) + realcnt + remaining
            total_tag = "[FILE] Total " + (f"{total_lines}+" if remaining >= 5000 else str(total_lines)) + ' lines\n'
            res = [(i, l if len(l) <= L_MAX else l[:L_MAX] + TAG) for i, l in res]
            result = "\n".join(f"{i}|{l}" if show_linenos else l for i, l in res)
            if show_linenos: result = total_tag + result
            return result
    except Exception as e:
        return f"Error: {str(e)}"

def smart_format(data, max_depth=2, max_str_len=100, omit_str=' ... '):
    def truncate(obj, depth):
        if isinstance(obj, str):
            if len(obj) < max_str_len+len(omit_str)*2: return obj
            return f"{obj[:max_str_len//2]}{omit_str}{obj[-max_str_len//2:]}"
        if depth >= max_depth: return truncate(str(obj), depth + 1)
        if isinstance(obj, dict): return {k: truncate(v, depth + 1) for k, v in obj.items()}
        if isinstance(obj, list): return [truncate(i, depth + 1) for i in obj]
        return obj
    if isinstance(data, (str, bytes)): return truncate(data, 0)
    return json.dumps(truncate(data, 0), indent=2, ensure_ascii=False, default=str)

class GenericAgentHandler(BaseHandler):
    '''Generic Agent 工具库，包含多种工具的实现。工具函数自动加上了 do_ 前缀。实际工具名没有前缀。'''
    def __init__(self, parent, last_history=None, cwd='./'):
        self.parent = parent
        self.working = {}
        self.cwd = cwd;  self.current_turn = 0
        self.history_info = last_history if last_history else []
        self.code_stop_signal = []

    def _get_abs_path(self, path):
        if not path: return ""
        return os.path.abspath(os.path.join(self.cwd, path))
    
    def tool_after_callback(self, tool_name, args, response, ret):
        if args.get('_index', 0) > 0: return 
        rsumm = re.search(r"<summary>(.*?)</summary>", response.content, re.DOTALL)
        if rsumm: summary = rsumm.group(1).strip()[:200]
        else:
            summary = f"调用工具{tool_name}, args: {args}"
            if tool_name == 'no_tool': summary = "直接回答了用户问题"
            if type(ret.next_prompt) is str:
                ret.next_prompt += "\nPROTOCOL_VIOLATION: 上一轮遗漏了<summary>。 我已根据物理动作自动补全。请务必在下次回复中记得<summary>协议。" 
        self.history_info.append('[Agent] ' + smart_format(summary, max_str_len=100))

    def do_code_run(self, args, response):
        '''执行代码片段，有长度限制，不允许代码中放大量数据，如有需要应当通过文件读取进行。
        '''
        if args.get('_index', 0) > 0: return StepOutcome("[BLANK]", next_prompt="no multi code_run in one round!") 
        code_type = args.get("type", "python")
        # 从 response.content 中提取代码块, 匹配 ```python ... ``` 或 ```powershell ... ```
        pattern = rf"```{code_type}\n(.*?)\n```"
        matches = re.findall(pattern, response.content, re.DOTALL)
        warning = ""
        if not matches:
            code = args.get("code") or args.get("script")
            if not code: return StepOutcome(None, next_prompt=f"【系统错误】：你调用了 code_run，但未在先在回复正文中提供 ```{code_type} 代码块。请重新输出代码并附带工具调用。")
            warning = "\n下次要记得先在回复正文中提供代码块，而不是放在参数中"
        else: code = matches[-1].strip()   # 提取最后一个代码块（通常是模型修正后的最终逻辑）
        timeout = args.get("timeout", 60)
        raw_path = os.path.join(self.cwd, args.get("cwd", './'))
        cwd = os.path.normpath(os.path.abspath(raw_path))
        code_cwd = os.path.normpath(self.cwd)
        result = yield from code_run(code, code_type, timeout, cwd, code_cwd=code_cwd, stop_signal=self.code_stop_signal)
        next_prompt = self._get_anchor_prompt() + warning
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_ask_user(self, args, response):
        question = args.get("question", "请提供输入：")
        candidates = args.get("candidates", [])
        result = ask_user(question, candidates)
        yield f"Waiting for your answer ...\n"
        return StepOutcome(result, next_prompt="", should_exit=True)
    
    def do_web_scan(self, args, response):
        '''获取当前页面内容和标签页列表。也可用于切换标签页。
        注意：HTML经过简化，边栏/浮动元素等可能被过滤。如需查看被过滤的内容请用execute_js。
        tabs_only=true时仅返回标签页列表，不获取HTML（省token）。
        '''
        tabs_only = args.get("tabs_only", False)
        switch_tab_id = args.get("switch_tab_id", None)
        text_only = args.get("text_only", False)
        result = web_scan(tabs_only=tabs_only, switch_tab_id=switch_tab_id, text_only=text_only)
        content = result.pop("content", None)
        yield f'[Info] {str(result)}\n'
        if content: next_prompt = f"<tool_result>\n```html\n{content}\n```\n</tool_result>"
        else: next_prompt = "标签页列表如上\n"  # 手动tool_result为了触发历史上下文自动压缩
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_web_execute_js(self, args, response):
        '''web情况下的优先使用工具，执行任何js达成对浏览器的*完全*控制。
        支持将结果保存到文件供后续读取分析，但保存功能仅限即时读取，与await等异步操作不兼容。
        '''
        script = args.get("script", "")
        if not script: return StepOutcome(None, next_prompt="[Error] Empty script param. Check your tool call arguments.")
        abs_path = self._get_abs_path(script.strip())
        if os.path.isfile(abs_path):
            with open(abs_path, 'r', encoding='utf-8') as f: script = f.read()
        save_to_file = args.get("save_to_file", "")
        switch_tab_id = args.get("switch_tab_id") or args.get("tab_id")
        no_monitor = args.get("no_monitor", False)
        result = web_execute_js(script, switch_tab_id=switch_tab_id, no_monitor=no_monitor)
        if save_to_file and "js_return" in result:
            content = str(result["js_return"] or '')
            abs_path = self._get_abs_path(save_to_file)
            result["js_return"] = smart_format(content, max_str_len=170)
            try:
                with open(abs_path, 'w', encoding='utf-8') as f: f.write(str(content))
                result["js_return"] += f"\n\n[已保存完整内容到 {abs_path}]"
            except:
                result['js_return'] += f"\n\n[保存失败，无法写入文件 {abs_path}]"
        try: print("Web Execute JS Result:", smart_format(result))
        except: pass
        yield f"JS 执行结果:\n{smart_format(result)}\n"
        next_prompt = self._get_anchor_prompt()
        return StepOutcome(smart_format(result, max_str_len=5000), next_prompt=next_prompt)
    
    def do_file_patch(self, args, response):
        path = self._get_abs_path(args.get("path", ""))
        yield f"[Action] Patching file: {path}\n"
        old_content = args.get("old_content", "")
        new_content = args.get("new_content", "")
        try: new_content = expand_file_refs(new_content, base_dir=self.cwd)
        except ValueError as e:
            yield f"[Status] ❌ 引用展开失败: {e}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        result = file_patch(path, old_content, new_content)
        yield f"\n{smart_format(result)}\n"
        next_prompt = self._get_anchor_prompt()
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_file_write(self, args, response):
        '''用于对整个文件的大量处理，精细修改要用file_patch。
        需要将要写入的内容放在<file_content>标签内，或者放在代码块中。
        '''
        path = self._get_abs_path(args.get("path", ""))
        mode = args.get("mode", "overwrite")  # overwrite/append/prepend
        action_str = {"prepend": "Prepending to", "append": "Appending to"}.get(mode, "Overwriting")
        yield f"[Action] {action_str} file: {os.path.basename(path)}\n"

        def extract_robust_content(text):
            tag = re.search(r"<file_content>(.*)</file_content>", text, re.DOTALL)
            if tag: return tag.group(1).strip()
            s, e = text.find("```"), text.rfind("```")
            if -1 < s < e: return text[text.find("\n", s)+1 : e].strip()
            return None
        
        blocks = extract_robust_content(response.content)
        if not blocks:
            yield f"[Status] ❌ 失败: 未在回复中找到代码块内容\n"
            return StepOutcome({"status": "error", "msg": "No content found, if you want a blank, you should use code_run"}, next_prompt="\n")
        try:
            new_content = expand_file_refs(blocks, base_dir=self.cwd)
            if mode == "prepend":
                old = open(path, 'r', encoding="utf-8").read() if os.path.exists(path) else ""
                open(path, 'w', encoding="utf-8").write(new_content + old)
            else:
                with open(path, 'a' if mode == "append" else 'w', encoding="utf-8") as f: f.write(new_content)
            yield f"[Status] ✅ {mode.capitalize()} 成功 ({len(new_content)} bytes)\n"
            next_prompt = self._get_anchor_prompt()
            return StepOutcome({"status": "success", 'writed_bytes': len(new_content)}, 
                               next_prompt=next_prompt)
        except Exception as e:
            yield f"[Status] ❌ 写入异常: {str(e)}\n"
            return StepOutcome({"status": "error", "msg": str(e)}, next_prompt="\n")
        
    def do_file_read(self, args, response):
        '''读取文件内容。从第start行开始读取。如有keyword则返回第一个keyword(忽略大小写)周边内容'''
        path = self._get_abs_path(args.get("path", ""))
        yield f"\n[Action] Reading file: {path}\n"
        start = args.get("start", 1)
        count = args.get("count", 200)
        keyword = args.get("keyword")
        show_linenos = args.get("show_linenos", True)
        result = file_read(path, start=start, keyword=keyword,
                           count=count, show_linenos=show_linenos)
        if show_linenos:
            tips = '由于设置了show_linenos，以下返回信息为：(行号|)内容 。\n'
            result = tips + result 
        if ' ... [TRUNCATED]' in result:
            result += '\n\n（某些行被截断，如需完整内容可改用 code_run 读取）'
        next_prompt = self._get_anchor_prompt()
        log_memory_access(path)
        if 'memory' in path or 'sop' in path: 
            next_prompt += "\n[SYSTEM TIPS] 正在读取记忆或SOP文件，若决定按sop执行请提取sop中的关键点（特别是靠后的）update working memory."
        return StepOutcome(result, next_prompt=next_prompt)
    
    def do_update_working_checkpoint(self, args, response):
        '''为整个任务设定后续需要临时记忆的重点。
        '''
        key_info = args.get("key_info", "")
        related_sop = args.get("related_sop", "")
        if "key_info" in args: self.working['key_info'] = key_info
        if "related_sop" in args: self.working['related_sop'] = related_sop
        self.working['passed_sessions'] = 0
        yield f"[Info] Updated key_info and related_sop.\n"
        next_prompt = self._get_anchor_prompt()
        #next_prompt += '\n[SYSTEM TIPS] 此函数一般在任务开始或中间时调用，如果任务已成功完成应该是start_long_term_update用于结算长期记忆。\n'
        return StepOutcome({"status": "success"}, next_prompt=next_prompt)

    def do_no_tool(self, args, response):
        '''这是一个特殊工具，由引擎自主调用，不要包含在TOOLS_SCHEMA里。
        当模型在一轮中未显式调用任何工具时，由引擎自动触发。
        二次确认仅在回复几乎只包含<thinking>/<summary>和一段大代码块时触发。
        '''
        content = getattr(response, 'content', '') or ""
        # 1. 空回复保护：要求模型重新生成内容或调用工具
        if not response or not content.strip():
            yield "[Warn] LLM returned an empty response. Retrying...\n"
            next_prompt = "[System] 回复为空，请重新生成内容或调用工具。"
            return StepOutcome({}, next_prompt=next_prompt, should_exit=False)
        # 2. 检测“包含较大代码块但未调用工具”的情况
        # 这里通过三引号代码块 + 最少字符数的方式粗略判断“大段代码”
        code_block_pattern = r"```[a-zA-Z0-9_]*\n[\s\S]{100,}?```"
        m = re.search(code_block_pattern, content)
        if m:
            # 仅当 content 由 <thinking> / <summary> 和该代码块构成时才触发二次确认
            residual = content
            # 去掉代码块本身
            residual = residual.replace(m.group(0), "")
            # 去掉<thinking>和<summary>块（大小写不敏感）
            residual = re.sub(r"<thinking>[\s\S]*?</thinking>", "", residual, flags=re.IGNORECASE)
            residual = re.sub(r"<summary>[\s\S]*?</summary>", "", residual, flags=re.IGNORECASE)
            # 如果去除上述结构后的非空白字符很少，说明没有额外自然语言说明
            clean_residual = re.sub(r"\s+", "", residual)
            if len(clean_residual) <= 50:
                yield "[Info] Detected large code block without tool call and no extra natural language. Requesting clarification.\n"
                next_prompt = (
                    "[System] 检测到你在上一轮回复中主要内容是较大代码块（仅配有<thinking>/<summary>），且本轮未调用任何工具。\n"
                    "如果这些代码需要执行、写入文件或进一步分析，请重新组织回复并显式调用相应工具"
                    "（例如：code_run、file_write、file_patch 等）；\n"
                    "如果只是向用户展示或讲解代码片段，请在回复中补充自然语言说明，"
                    "并明确是否还需要额外的实际操作。"
                )
                return StepOutcome({}, next_prompt=next_prompt, should_exit=False)
        # 3. 正常情况：直接将回复返回给用户并结束循环
        yield "[Info] Final response to user.\n"
        return StepOutcome(response, next_prompt=None, should_exit=True)
    
    def do_start_long_term_update(self, args, response):
        '''Agent觉得当前任务完成后有重要信息需要记忆时调用此工具。
        '''
        prompt = '''### [总结提炼经验] 既然你觉得当前任务有重要信息需要记忆，请提取最近一次任务中【事实验证成功且长期有效】的环境事实、用户偏好、重要步骤，更新记忆。
本工具是标记开启结算过程，若已在更新记忆过程或没有值得记忆的点，忽略本次调用。
**提取行动验证成功的信息**：
- **环境事实**（路径/凭证/配置）→ `file_patch` 更新 L2，同步 L1
- **复杂任务经验**（关键坑点/前置条件/重要步骤）→ L3 精简 SOP（只记你被坑得多次重试的核心要点）
**禁止**：临时变量、具体推理过程、未验证信息、通用常识、你可以轻松复现的细节。
**操作**：严格遵循提供的L0的记忆更新SOP。先 `file_read` 看现有 → 判断类型 → 最小化更新 → 无新内容跳过，保证对记忆库最小局部修改。\n
''' + get_global_memory()
        yield "[Info] Start distilling good memory for long-term storage.\n"
        path = './memory/memory_management_sop.md'
        if os.path.exists(path): result = file_read(path, show_linenos=False)
        else: result = "Memory Management SOP not found. Do not update memory."
        return StepOutcome(result, next_prompt=prompt)

    def _get_anchor_prompt(self):
        h_str = "\n".join(self.history_info[-20:])
        prompt = f"\n### [WORKING MEMORY]\n<history>\n{h_str}\n</history>"
        prompt += f"\nCurrent turn: {self.current_turn}\n"
        if self.working.get('key_info'): prompt += f"\n<key_info>{self.working.get('key_info')}</key_info>"
        if self.working.get('related_sop'): prompt += f"\n有不清晰的地方请再次读取{self.working.get('related_sop')}"
        try: print(prompt)
        except: pass
        return prompt

    def next_prompt_patcher(self, next_prompt, outcome, turn):
        if turn % 35 == 0 and 'plan' not in str(self.working.get('related_sop')):
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。你必须总结情况进行ask_user，不允许继续重试。"
        elif turn % 7 == 0:
            next_prompt += f"\n\n[DANGER] 已连续执行第 {turn} 轮。禁止无效重试。若无有效进展，必须切换策略：1. 探测物理边界 2. 请求用户协助。如有需要，可调用 update_working_checkpoint 保存关键上下文。"
        elif turn % 10 == 0: next_prompt += get_global_memory()
        return next_prompt

def get_global_memory():
    prompt = "\n"
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(script_dir, 'memory/global_mem_insight.txt'), 'r', encoding='utf-8') as f: insight = f.read()
        with open(os.path.join(script_dir, 'assets/insight_fixed_structure.txt'), 'r', encoding='utf-8') as f: structure = f.read()
        prompt += f"\n[Memory]\n"
        prompt += f'cwd = {os.path.abspath("./temp")} （用./引用）\n'
        prompt += structure + '\n../memory/global_mem_insight.txt:\n'
        prompt += insight + "\n"
    except FileNotFoundError: pass
    return prompt
