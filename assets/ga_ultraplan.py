from contextlib import contextmanager, redirect_stdout, redirect_stderr
from concurrent.futures import ThreadPoolExecutor
from time import time, sleep
import html, io, json, os, re, secrets, subprocess, sys, tempfile, threading, traceback, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = ["plan", "phase", "parallel", "mapchain"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PORT = int(os.environ.get("GA_ULTRAPLAN_PORT", "47831"))
_T0 = time(); _phases = []; _phase_stack = []; _tasks = []; _current = "idle"; _events = []; _srv = None; _last = time(); _lock = threading.Lock(); _exec_lock = threading.Lock()
_TASK_SLUG = "task"; _FUNC_SEQ = 0; _PLANNED = False; _SESSION = None; _sessions = {}
_RUN_DIR = os.path.abspath(os.environ.get("GA_ULTRAPLAN_RUNDIR", os.path.join(_ROOT, "temp", "ultraplan_default")))
os.makedirs(_RUN_DIR, exist_ok=True)
_TOKEN = os.environ.get("GA_ULTRAPLAN_TOKEN") or ""
_TOKEN_FILE = os.path.join(_RUN_DIR, ".ultraplan_token")

def _bind(rundir):
    global _SESSION, _RUN_DIR, _phases, _phase_stack, _tasks, _current, _events, _FUNC_SEQ, _TASK_SLUG
    key = os.path.abspath(rundir); os.makedirs(key, exist_ok=True)
    s = _sessions.setdefault(key, {"rundir": key, "phases": [], "phase_stack": [], "tasks": [], "current": "idle", "events": [], "func_seq": 0, "task_slug": "task"})
    _SESSION = key; _RUN_DIR = key; _phases = s["phases"]; _phase_stack = s["phase_stack"]; _tasks = s["tasks"]; _current = s["current"]; _events = s["events"]; _FUNC_SEQ = s["func_seq"]; _TASK_SLUG = s["task_slug"]
    return s

def _save_session():
    if _SESSION in _sessions:
        _sessions[_SESSION].update(current=_current, func_seq=_FUNC_SEQ, task_slug=_TASK_SLUG)

def _need_plan():
    if not _PLANNED: raise RuntimeError("call plan(rundir) as the first UltraPlan statement")

def _slug(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s)).strip("_").lower()
    return s[:80] or "task"

def _task_slug(path):
    stem = os.path.splitext(os.path.basename(path or "task"))[0]
    parts = [_slug(x) for x in re.split(r"[_\-]+", stem)]
    stop = {"ultra", "ultraplan", "script", "boot", "build", "test", "debug", "verify", "explore", "reduce", "phase"}
    parts = [p for p in parts if p and not p.isdigit() and p not in stop]
    return "_".join(parts) or _slug(stem)

def _note(s):
    global _last
    with _lock:
        _last = time(); _events.append(f"{_last-_T0:7.1f}s  {s}"); del _events[:-60]

def _phase_lines(nodes, depth=0):
    out = []
    for p in nodes:
        pre = "  " * depth; mark = ">>" if p["on"] else "  "
        out.append(f"{pre}{mark} {p['status']:<7} {p['name']}" + (f" - {p['desc']}" if p['desc'] else ""))
        out += [f"{pre}   | {op}" for op in p.get("ops", [])[-8:]]
        out += [f"{pre}   - {t['status']:<5} {t['desc']}" for t in p.get("tasks", [])[-20:]]
        out += _phase_lines(p.get("children", []), depth + 1)
    return out

def _page():
    with _lock:
        lines = ["GA UltraPlan"]
        for key, s in _sessions.items():
            lines += ["", f"== {os.path.basename(key) or key} ==", f"rundir: {key}", f"current: {s['current']}", "", "phases:"]
            lines += _phase_lines(s["phases"]) or ["(none)"]
            lines += ["", "recent tasks:"]
            lines += [f"{t['status']:<7} {t['desc']}" for t in s["tasks"][-12:]] or ["(none)"]
            lines += ["", "events:", *s["events"][-30:]]
        if not _sessions: lines += ["", "(no sessions)"]
    return "<meta http-equiv=refresh content=1><pre>" + html.escape("\n".join(lines)) + "</pre>"

class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        b = _page().encode("utf-8"); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        global _TASK_SLUG, _PLANNED
        if self.path != "/exec": self.send_response(404); self.end_headers(); return
        if _TOKEN:
            got = ""
            for k, v in self.headers.items():
                if k.lower() == "authorization": got = v; break
            if not got.startswith("Bearer ") or not secrets.compare_digest(got[7:], _TOKEN):
                self.send_response(401); self.end_headers(); return
        n = int(self.headers.get("Content-Length", "0")); req = json.loads(self.rfile.read(n).decode("utf-8"))
        out = io.StringIO(); err = io.StringIO(); rc = 0
        with _exec_lock, redirect_stdout(out), redirect_stderr(err):
            _bind(req["rundir"]); _note("exec: " + req.get("path", "<script>"))
            cwd = os.getcwd(); old_env = os.environ.copy(); os.environ["GA_ULTRAPLAN_DAEMON"] = "1"; _PLANNED = False; _TASK_SLUG = req.get("task") or _task_slug(req.get("path")); _save_session()
            try:
                if req.get("cwd"): os.chdir(req["cwd"])
                g = {"__name__": "__main__", "__file__": req.get("path", "<ultraplan>")}
                exec(compile(req.get("code", ""), g["__file__"], "exec"), g, g)
            except SystemExit as e:
                rc = int(e.code or 0) if isinstance(e.code, int) else 1
            except Exception:
                rc = 1; traceback.print_exc()
            finally:
                _save_session(); os.chdir(cwd); os.environ.clear(); os.environ.update(old_env)
        body = json.dumps({"returncode": rc, "stdout": out.getvalue(), "stderr": err.getvalue()}).encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

def _serve_daemon():
    global _srv, _TOKEN
    sys.modules.setdefault("assets.ga_ultraplan", sys.modules[__name__])
    if not _TOKEN:
        _TOKEN = secrets.token_urlsafe(32)
        os.makedirs(_RUN_DIR, exist_ok=True)
        with open(_TOKEN_FILE, "w") as f: f.write(_TOKEN)
        try: os.chmod(_TOKEN_FILE, 0o600)
        except OSError: pass
    _srv = ThreadingHTTPServer(("127.0.0.1", _PORT), _H); _srv.timeout = 60; url = f"http://127.0.0.1:{_PORT}/"
    print(f"[ultraplan] {url}", flush=True)
    if os.environ.get("GA_ULTRAPLAN_BROWSER") != "0": webbrowser.open(url)
    while time() - _last < 3600: _srv.handle_request()

def _ping():
    try: urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/", timeout=0.5).read(1); return True
    except Exception: return False

def _show():
    if os.environ.get("GA_ULTRAPLAN_DAEMON") == "1" or os.environ.get("GA_ULTRAPLAN_HTML") == "0": return
    if not _ping():
        tok = secrets.token_urlsafe(32) if not _TOKEN else _TOKEN
        if not _TOKEN:
            os.makedirs(_RUN_DIR, exist_ok=True)
            with open(_TOKEN_FILE, "w") as f: f.write(tok)
            try: os.chmod(_TOKEN_FILE, 0o600)
            except OSError: pass
        subprocess.Popen([sys.executable, __file__, "--daemon"], cwd=_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "GA_ULTRAPLAN_DAEMON":"1", "GA_ULTRAPLAN_TOKEN": tok})
        for _ in range(20):
            if _ping(): break
            sleep(0.25)

def plan(rundir):
    global _PLANNED
    if _PLANNED: return
    _PLANNED = True; _bind(rundir); _save_session()
    if os.environ.get("GA_ULTRAPLAN_DAEMON") == "1": return
    _show(); path = os.path.abspath(sys.argv[0]); code = open(path, encoding="utf-8").read()
    data = json.dumps({"path": path, "cwd": os.getcwd(), "rundir": _RUN_DIR, "task": _task_slug(path), "code": code}).encode("utf-8")
    tok = os.environ.get("GA_ULTRAPLAN_TOKEN") or (open(_TOKEN_FILE).read().strip() if os.path.exists(_TOKEN_FILE) else "")
    headers = {"Content-Type": "application/json"}
    if tok: headers["Authorization"] = "Bearer " + tok
    r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{_PORT}/exec", data=data, headers=headers), timeout=None)
    resp = json.loads(r.read().decode("utf-8")); sys.stdout.write(resp.get("stdout", "")); sys.stderr.write(resp.get("stderr", "")); sys.exit(resp.get("returncode", 1))

@contextmanager
def phase(name, desc=""):
    global _current
    _need_plan(); t = time(); p = {"name": name, "desc": desc, "status": "run", "on": True, "children": [], "tasks": [], "ops": []}
    with _lock:
        (_phase_stack[-1]["children"] if _phase_stack else _phases).append(p)
        _phase_stack.append(p); _current = f"phase: {name}"; _save_session()
    print(f"[phase] {name}" + (f" - {desc}" if desc else ""), flush=True); _note(f"phase start: {name}")
    failed = False
    try:
        yield
    except Exception:
        failed = True; raise
    finally:
        dt = time() - t; status = "fail" if failed else "done"
        with _lock:
            p["status"] = status; p["on"] = False
            if _phase_stack and _phase_stack[-1] is p: _phase_stack.pop()
            elif p in _phase_stack: _phase_stack.remove(p)
            if _phase_stack: _current = f"phase: {_phase_stack[-1]['name']}"
            else: _current = ("failed" if failed else "all phases done") + f"; last: {name} ({dt:.1f}s)"
            _save_session()
        print(f"[{status}] {name} ({dt:.1f}s)", flush=True)
        print("[next] Main agent must continue orchestration or stop; do not take over task work.", flush=True)
        _note(f"phase {status}:  {name} ({dt:.1f}s)")

def _task(desc, status="run"):
    with _lock:
        t = {"desc": str(desc), "status": status}; _tasks.append(t); del _tasks[:-80]
        if _phase_stack: _phase_stack[-1]["tasks"].append(t)
    return t

def _task_done(t, status="done"):
    with _lock: t["status"] = status

def _op(s):
    with _lock:
        if _phase_stack: _phase_stack[-1]["ops"].append(s)

def _fmt(x, data):
    return x.format(**data) if isinstance(x, str) else x

def _subagent(desc, prompt=None, *, llm_no=0, timeout=3600):
    global _FUNC_SEQ
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _FUNC_SEQ += 1; path = os.path.join(_RUN_DIR, f"{_FUNC_SEQ:03d}_{_TASK_SLUG}_{_slug(desc)}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(desc if prompt is None else prompt)
    print(f"[subagent] {desc} -> {path}", flush=True); _note(f"agent: {desc}")
    cmd = [
        sys.executable, os.path.join(root, "agentmain.py"), "--func", path,
        "--llm_no", str(llm_no), "--nobg", "--nolog", "--no-user-tools",
    ]
    r = subprocess.run(cmd, cwd=root, text=True, capture_output=True, timeout=timeout)
    if r.returncode: raise RuntimeError(f"subagent failed: {desc}\n{r.stdout}\n{r.stderr}")
    return os.path.splitext(path)[0] + ".out.txt"

def _run(task, data):
    task = task() if callable(task) else task
    if isinstance(task, (tuple, list)):
        desc = _fmt(task[0], data); t = _task(desc)
        try: return _subagent(desc, _fmt(task[1] if len(task) > 1 else task[0], data), llm_no=data.get("llm_no", 0), timeout=data.get("timeout", 3600))
        except Exception: _task_done(t, "fail"); raise
        finally:
            if t["status"] == "run": _task_done(t)
    if isinstance(task, dict):
        d = {**data, **task.get("data", {})}; desc = _fmt(task.get("desc", "task"), d); t = _task(desc)
        try: return _subagent(desc, _fmt(task.get("prompt", task.get("desc", "task")), d), llm_no=task.get("llm_no", d.get("llm_no", 0)), timeout=task.get("timeout", d.get("timeout", 3600)))
        except Exception: _task_done(t, "fail"); raise
        finally:
            if t["status"] == "run": _task_done(t)
    return task

def parallel(tasks, max_workers=None, _label=None, **data):
    global _current
    _need_plan(); tasks = list(tasks); label = _label or f"parallel: {len(tasks)} tasks"
    with _lock: _current = label; _save_session()
    _op(label); _note(label)
    with ThreadPoolExecutor(max_workers=max_workers or min(3, len(tasks) or 1)) as ex:
        return list(ex.map(lambda t: _run(t, data), tasks))

def mapchain(items, *steps, max_workers=None, **data):
    global _current
    _need_plan(); items = list(items); label = f"mapchain: {len(items)} items x {len(steps)} steps"
    with _lock: _current = label; _save_session()
    def run(x):
        for step in steps:
            d = {**data, "item": x, "previous": x}; x = _run(step(x) if callable(step) else step, d)
        return x
    return parallel([lambda x=x: run(x) for x in items], max_workers=max_workers, _label=label)

if __name__ == "__main__" and "--daemon" in sys.argv:
    _serve_daemon()
