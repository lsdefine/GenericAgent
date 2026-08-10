"""GA Hub: `import hub` -> client (silent if no server); `python hub.py` -> WS server.
    hub.connect(agent, 'stapp')     # or override any hook: connect(a, n, put_task=, get_outputs=, abort=)
    default put -> 'busy' if agent.is_running, else parks plain text in agent._hub_inbox for the UI
HTTP (errors = {'error','code'} + status: offline/gone 404, busy 409, timeout 504, nosupport 501, badop 400):
    GET peers -> [{name,title,n_msgs,sig}] | {name}/messages?detail=1&sig= -> {title,tasks:[{i,input,steps:
    [{j,title,n}]}],sig} or {same:1,sig} | {name}/seg/{i}/{j}?off=N -> {content,off,n} (step bodies, tailable)
    POST {name}/put {"text":..} -> {ok:1} | {name}/abort -> {ok:1}
"""
import os, re, sys, json, time, asyncio, threading, random, hmac
PORT = int(os.environ.get('GA_HUB_PORT', 19736))
WEB_PORT = int(os.environ.get('GA_HUB_WEB_PORT', PORT + 1))   # the only face fit to be tunnelled out (frp this one)
TOKEN = os.environ.get('GA_HUB_TOKEN') or ''.join(random.choices('abcdefghijkmnpqrstuvwxyz23456789', k=6))
URL = os.environ.get('GA_HUB', f'ws://127.0.0.1:{PORT}/ws')
TITLE_MIN = 12                    # a too short last input gets the previous one prepended
NOISE = re.compile(r'\**LLM Running \(Turn \d+\) \.\.\.\**|`{3,}.*?`{3,}|<thinking>.*?</thinking>', re.DOTALL)

class HubClient:
    def __init__(self, name, put_task=None, get_outputs=None, abort=None, state=None, on_ev=None, sub=(), fixed=False):
        self.name, self.put_task, self.get_outputs, self.abort = name, put_task, get_outputs, abort
        self.state, self.on_ev, self.sub, self.fixed = state or dict, on_ev, list(sub), fixed  # fixed -> stable name
        self._tc, self._ws, self._lp = {}, None, None   # (i,j) -> (fp, title): a finished step is never re-scanned
    def emit(self, topic, data=None, to=None):          # thread-safe fire-and-forget from the host thread
        if self._ws and self._lp: asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(
            {'op': 'ev', 'topic': topic, 'to': to, 'data': data}, default=str)), self._lp)
    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._loop()), daemon=True).start(); return self
    async def _loop(self):
        try: import websockets
        except ImportError: return
        while True:
            try:
                async with websockets.connect(URL, open_timeout=3, max_size=None) as ws:
                    self._ws, self._lp = ws, asyncio.get_running_loop()
                    caps = [k for k, v in (('get', self.get_outputs), ('put', self.put_task), ('abort', self.abort)) if v]
                    await ws.send(json.dumps({'op': 'hello', 'name': self.name, 'pid': os.getpid(),
                                              'fixed': self.fixed, 'caps': caps, 'sub': self.sub}))
                    async for raw in ws: await self._on_cmd(ws, json.loads(raw))
            except Exception: pass         # silent: the hub is optional, it must not disturb the host
            self._ws = None
            await asyncio.sleep(5)
    def _stitle(self, i, j, s):
        s, e = s or '', self._tc.get((i, j))
        fp = (len(s), s[:24] + s[-24:])    # memoised on length+edges: guards index reuse after /clear
        if e and e[0] == fp: return e[1]
        body = NOISE.sub('', s)            # title = <summary> if present, else first meaningful line
        m = re.search(r'<summary>\s*(.*?)\s*</summary>', body, re.DOTALL)
        t = (m.group(1) if m else body.strip()).strip().split('\n')[0]; t = t[:50] + '...' if len(t) > 50 else t or f'step {j + 1}'
        self._tc[(i, j)] = (fp, t); return t
    def _build(self, c):
        """Skeleton only (no bodies), off-loop: regex/serialisation must not stall the WS reader."""
        tasks = list(self.get_outputs() or []); outs = [list(t.get('outputs') or []) for t in tasks]  # copy: host mutates
        sig = '.'.join(str(len(o)) for o in outs) + ':' + str(len(outs[-1][-1] or '') if outs and outs[-1] else 0)
        if c.get('sig') == sig: return {'same': 1, 'sig': sig, **self.state()}   # nothing moved -> no payload at all
        ins = [(t.get('input') or '').strip() for t in tasks]
        ins = [u for u in ins if u and not u.startswith('/')] or [u for u in ins if u]   # /clear is plumbing
        title = ins[-1].split('\n')[0] if ins else '(empty)'
        w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in title)   # display width: a CJK char is worth two
        if len(ins) > 1 and w < TITLE_MIN: title = ins[-2].split('\n')[0] + ' <- ' + title
        det, rows = int(c.get('detail', 1)), []
        since = max(0, int(c.get('since') or 0))   # delta: the client already holds rows < since (they are immutable)
        for i, (t, o) in enumerate(zip(tasks, outs)):
            if i < since: continue
            steps = [{'j': j, 'title': self._stitle(i, j, s), 'n': len(s or '')} for j, s in enumerate(o)]
            rows.append({'i': i, 'input': t.get('input', ''), **({'steps': steps} if det else {'ns': len(o)})})
        return {'title': title[:80], 'tasks': rows, 'nt': len(tasks), 'sig': sig, **self.state()}   # nt lets a delta client spot /clear
    def _seg(self, c):
        tasks, off = list(self.get_outputs() or []), max(0, int(c.get('off') or 0))
        i, j = int(c.get('i', -1)), int(c.get('j', -1))
        o = (tasks[i].get('outputs') or []) if -len(tasks) <= i < len(tasks) else None
        if o is None or not (-len(o) <= j < len(o)):
            return {'error': f'segment {i}/{j} gone (trimmed or cleared)', 'code': 'gone'}
        s = o[j] or ''; return {'content': s[off:], 'off': off, 'n': len(s)}          # off lets a UI tail a growing step
    async def _on_cmd(self, ws, c):
        op = c.get('op'); data = {'error': f'unknown op {op}', 'code': 'badop'}
        if op == 'ev': return self.on_ev and self.on_ev(c)      # bus push: no reply, must not block the reader
        if op in ('get', 'seg'): data = await asyncio.to_thread(self._build if op == 'get' else self._seg, c)
        elif op == 'put_task': data = (c.get('text') and await asyncio.to_thread(self.put_task, c['text'])) or {'ok': 1}
        elif op == 'abort': data = (await asyncio.to_thread(self.abort) or {'ok': 1}) if self.abort else {'error': 'no abort hook', 'code': 'nosupport'}
        await ws.send(json.dumps({'op': 'r', 'id': c.get('id'), 'name': self.name, 'data': data}, default=str))

def serve():
    """Bring the hub up on demand: any host may spawn it, the port is the lock (a loser just exits).
    Detached + windowless, so it outlives its spawner and no console ever flashes."""
    import socket, subprocess
    if '127.0.0.1' not in URL and 'localhost' not in URL: return    # a remote hub is not ours to start
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1', PORT)) == 0: return           # already listening
    exe = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    subprocess.Popen([exe if os.path.exists(exe) else sys.executable, os.path.abspath(__file__)],
                     cwd=os.path.dirname(os.path.abspath(__file__)), close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x08000008 if os.name == 'nt' else 0)   # DETACHED | NO_WINDOW

def connect(agent, name=None, put_task=None, get_outputs=None, abort=None, fold=None):
    """One line to wire a GA host: `hub.connect(agent, 'stapp')`; any hook can still be overridden.
    Default put refuses while the agent is busy (a remote must not cut in line), else it parks
    plain text in agent._hub_inbox; the UI feeds it through its own input entrance when idle,
    so remote tasks behave exactly like typed ones (bubble/stream/stop). Requires a live UI tab.
    Never raises: a broken hub must not break its host."""
    def _put(text):
        if getattr(agent, 'is_running', False): return {'error': f'peer {name} is busy', 'code': 'busy'}
        agent._hub_inbox.append(text)   # no put_task here: the UI's unified entrance sends it
    try:
        try: serve()                                   # best effort: bring up a local hub if none is listening
        except Exception: pass
        if not hasattr(agent, '_hub_inbox'): agent._hub_inbox = []
        agent._hub = HubClient(name or getattr(agent, 'name', 'agent'), put_task or _put,
                               get_outputs or (lambda: agent.all_outputs), abort or agent.abort,
                               state=lambda: {'run': bool(getattr(agent, 'is_running', False))})
        return agent._hub.start()
    except Exception: return None

# ------------------------------- server (python hub.py) -------------------------------
if __name__ == '__main__':
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
    from fastapi.responses import FileResponse, JSONResponse; import uvicorn
    HERE, OK_ORIGIN = os.path.dirname(os.path.abspath(__file__)), ('', f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}')
    STATUS = {'offline': 404, 'gone': 404, 'timeout': 504, 'nosupport': 501, 'badop': 400, 'busy': 409}
    app, peers, meta, waits, seq, pcache, pdead = FastAPI(), {}, {}, {}, [0], {}, {}  # ws / hello / futures / row / probe
    @app.middleware('http')
    async def guard(req: Request, call_next):
        if req.scope['server'][1] == PORT: return Response(status_code=404)   # bus port speaks WebSocket only
        public = getattr(app.state, 'p2p_pair_open', False) and req.url.path in ('/pair', '/pair/status')
        if public: return await call_next(req)
        t = req.query_params.get('t') or req.cookies.get('ga_hub_t') or ''    # web port: token or nothing
        if not hmac.compare_digest(t, TOKEN): return Response(status_code=403)
        r = await call_next(req); r.set_cookie('ga_hub_t', TOKEN, httponly=True, samesite='lax'); return r
    async def ask(name, msg, timeout=15):
        if name not in peers: return {'error': f'peer {name} offline', 'code': 'offline'}
        seq[0] += 1; rid = seq[0]
        waits[rid] = fut = asyncio.get_running_loop().create_future()
        try:
            await peers[name].send_text(json.dumps(dict(msg, id=rid)))
            return await asyncio.wait_for(fut, timeout)    # the WS reader resolves it
        except asyncio.TimeoutError: return {'error': f'peer busy (>{timeout}s)', 'code': 'timeout'}
        except Exception as e: return {'error': str(e) or type(e).__name__, 'code': 'offline'}
        finally: waits.pop(rid, None)
    async def fan(m, frm):      # the bus: unicast when 'to' is set, else every peer subscribed to the topic
        for n, w in list(peers.items()):
            if n != frm and (m.get('to') == n or (not m.get('to') and m.get('topic') in (meta.get(n, {}).get('sub') or []))):
                try: await w.send_text(json.dumps({'op': 'ev', 'topic': m.get('topic'), 'from': frm, 'data': m.get('data')}))
                except Exception: pass
    def out(d):                 # a peer-level error becomes a real HTTP status, not a 200 with a body
        c = d.get('code') if isinstance(d, dict) else None; return JSONResponse(d, STATUS.get(c, 400)) if c else d
    @app.websocket('/ws')
    async def endpoint(ws: WebSocket):
        if ws.scope['server'][1] != PORT or (ws.headers.get('origin') or '') not in OK_ORIGIN:
            return await ws.close(code=1008)      # the bus lives on PORT alone and never leaves this machine
        await ws.accept(); name = None
        try:
            while True:
                m = json.loads(await ws.receive_text())
                if m.get('op') == 'hello':      # fixed -> one stable, addressable name (pet, notifier, scheduler...)
                    name = re.sub(r'[^\w.-]', '_', m['name'] if m.get('fixed') else f"{m.get('name')}-{m.get('pid')}")
                    m['caps'] = m.get('caps', ['get', 'put', 'abort'])   # legacy clients (no caps in hello) = full agent
                    peers[name], meta[name] = ws, m; print(f'[+] {name} {m["caps"]} ({len(peers)} online)')
                elif m.get('op') == 'ev': await fan(m, name)
                f = waits.get(m.get('id')) if m.get('op') == 'r' else None
                if f and not f.done(): f.set_result(m.get('data'))
        except WebSocketDisconnect: pass
        finally:
            if name and peers.get(name) is ws:      # never evict the successor that replaced us
                peers.pop(name, None); meta.pop(name, None); print(f'[-] {name} ({len(peers)} online)')
    @app.get('/api/peers')
    async def api_peers():      # one cheap round-trip per peer: counts only, and only if its sig moved
        now = time.time()
        names = [n for n in peers if 'get' in (meta.get(n, {}).get('caps') or []) and now >= pdead.get(n, 0)]
        rs = await asyncio.gather(*[ask(n, {'op': 'get', 'detail': 0,
                                            'sig': (pcache.get(n) or {}).get('sig')}, 3) for n in names])
        for n, r in zip(names, rs): pdead[n] = now + 15 if (r or {}).get('error') else 0
        rs, rows = dict(zip(names, rs)), []
        for n in peers:
            r, caps = rs.get(n), meta.get(n, {}).get('caps') or []
            if 'get' not in caps: rows.append({'name': n, 'title': '', 'n_msgs': 0, 'sig': None, 'caps': caps}); continue
            if r is None or r.get('error') or (r.get('same') and n in pcache):   # busy/skipped/idle -> last row
                rows.append({**(pcache.get(n) or {'name': n, 'title': '?', 'n_msgs': 0, 'sig': None}),
                             'caps': caps, 'run': (r or {}).get('run')}); continue
            msgs = sum(1 for t in r.get('tasks', []) if not (t.get('input') or '').lstrip().startswith('/'))
            rows.append({'name': n, 'title': r.get('title', '?'), 'n_msgs': msgs, 'sig': r.get('sig'),
                         'caps': caps, 'run': r.get('run')})
            if r.get('sig'): pcache[n] = rows[-1]
        for n in [x for x in pcache if x not in peers]: pcache.pop(n, None)
        return rows
    @app.get('/api/{name}/messages')
    async def api_messages(name: str, detail: int = 1, sig: str = None, since: int = 0): return out(await ask(name, {'op': 'get', 'detail': detail, 'sig': sig, 'since': since}))
    @app.get('/api/{name}/seg/{i}/{j}')
    async def api_seg(name: str, i: int, j: int, off: int = 0): return out(await ask(name, {'op': 'seg', 'i': i, 'j': j, 'off': off}))
    @app.post('/api/{name}/put')
    async def api_put(name: str, body: dict): return out(await ask(name, {'op': 'put_task', 'text': body.get('text', '')}))
    @app.post('/api/{name}/abort')
    async def api_abort(name: str): return out(await ask(name, {'op': 'abort'}))
    # ---- optional P2P pairing; delete this block to remove it completely ----
    try:
        from hub_p2p import install as _install_p2p
        _install_p2p(app, web_port=WEB_PORT, token=TOKEN, here=HERE)
    except Exception:
        pass  # missing plug-in/client/dependency must not affect the hub

    @app.get('/')
    async def index(): return FileResponse(os.path.join(HERE, 'hub.html'))
    @app.get('/vendor/{f}')
    async def vendor(f: str):
        p = os.path.join(HERE, 'desktop', 'static', 'vendor', os.path.basename(f))
        return FileResponse(p) if os.path.exists(p) else Response(status_code=404)
    def serve(p):
        uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=p, log_level='warning')).run()
    print(f'[hub] bus ws://127.0.0.1:{PORT}/ws (no HTTP)  |  panel http://127.0.0.1:{WEB_PORT}/?t={TOKEN}')
    threading.Thread(target=serve, args=(WEB_PORT,), daemon=True).start()
    try: serve(PORT)
    except OSError: sys.exit(f'hub already running on {PORT}')
