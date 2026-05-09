import os, sys, time, json, uuid, queue, base64, mimetypes, threading, traceback
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from bottle import Bottle, request, response, static_file, run, ServerAdapter, BaseRequest, HTTPError
except Exception as e:
    raise SystemExit("Bottle is required. Try: uv add bottle or pip install bottle") from e

# Bottle's default request-body spool limit is too small for base64 image JSON.
# Keep this aligned with the frontend MAX_JSON_BYTES and backend decoded-file limit.
MAX_REQUEST_BYTES = int(os.environ.get('GA_REACT_MAX_REQUEST_MB', '32')) * 1024 * 1024
BaseRequest.MEMFILE_MAX = MAX_REQUEST_BYTES

class ThreadedWSGIServer(ServerAdapter):
    def run(self, handler):
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server
        class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True
            allow_reuse_address = True
        self.srv = make_server(self.host, self.port, handler, server_class=_ThreadingWSGIServer, handler_class=WSGIRequestHandler)
        self.srv.serve_forever()

from agentmain import GeneraticAgent
try:
    from frontends.continue_cmd import reset_conversation
except Exception:
    def reset_conversation(agent, message=None):
        agent.history = []
        b = getattr(getattr(agent, 'llmclient', None), 'backend', None)
        if b is not None and hasattr(b, 'history'):
            b.history = []

APP_DIR = Path(__file__).resolve().parent / 'ga_react_app'
DIST_DIR = APP_DIR / 'dist'
SESSION_DIR = ROOT / 'temp' / 'react_frontend_sessions'
UPLOAD_DIR = ROOT / 'temp' / 'uploads'
SESSION_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_LOCK = threading.RLock()
_AGENTS = {}
_RUNS = {}


def _new_agent(llm_no=0, verbose=True):
    a = GeneraticAgent()
    try:
        a.next_llm(int(llm_no or 0))
    except Exception:
        pass
    a.verbose = bool(verbose)
    # React NDJSON streaming expects incremental chunks from agentmain.
    # Without this, agentmain emits cumulative prefixes and the server-side
    # `full += next` below turns them into repeated text that later gets saved.
    a.inc_out = True
    t = threading.Thread(target=a.run, daemon=True)
    t.start()
    a._react_thread = t
    return a


def _agent(session_id, llm_no=0, verbose=True):
    with _LOCK:
        a = _AGENTS.get(session_id)
        if a is None:
            a = _new_agent(llm_no, True)
            _AGENTS[session_id] = a
        else:
            # Existing sessions may have been created while the old frontend
            # allowed disabling process output. React should always stream GA
            # process chunks and only expose model switching.
            a.verbose = True
            a.inc_out = True
        return a


def _safe_id(v):
    s = str(v or '').strip()
    return s if s and all(c.isalnum() or c in '-_' for c in s) else uuid.uuid4().hex


def _session_path(sid):
    return SESSION_DIR / f'{_safe_id(sid)}.json'


def _load_messages(sid):
    p = _session_path(sid)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        return data.get('messages') or []
    except Exception:
        return []


def _save_session(sid, messages, title=None):
    sid = _safe_id(sid)
    now = int(time.time())
    title = title or next((m.get('content','').strip().split('\n',1)[0][:64] for m in messages if m.get('role') == 'user' and m.get('content','').strip()), '新会话')
    data = {'id': sid, 'title': title, 'updated_at': now, 'messages': messages}
    _session_path(sid).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def _run_snapshot(sid):
    sid = _safe_id(sid)
    with _LOCK:
        r = _RUNS.get(sid)
        if not r:
            return None
        return dict(r)


def _set_run(sid, **patch):
    sid = _safe_id(sid)
    with _LOCK:
        r = _RUNS.setdefault(sid, {'running': False, 'text': '', 'started_at': int(time.time())})
        r.update(patch)
        return dict(r)


def _clear_run(sid):
    sid = _safe_id(sid)
    with _LOCK:
        _RUNS.pop(sid, None)


def _json(obj, code=200):
    response.status = code
    response.content_type = 'application/json; charset=utf-8'
    return json.dumps(obj, ensure_ascii=False)


def _backend(agent):
    return getattr(getattr(agent, 'llmclient', None), 'backend', None)


def _coerce(v):
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in ('', 'none', 'null'): return None
        if s.lower() in ('true','false'): return s.lower() == 'true'
        try: return int(s)
        except Exception: pass
        try: return float(s)
        except Exception: return v
    return v


def _apply_settings(agent, settings):
    """Apply user-selectable settings.

    Frontend is intentionally limited to model switching only. All backend
    options (api_mode, reasoning, thinking, temperature, tokens, etc.) must
    come from mykey / backend initialization. The React frontend always shows
    GA process output, so keep verbose enabled here instead of exposing it as a
    user setting.
    """
    try:
        agent.verbose = True
        agent.inc_out = True
    except Exception:
        pass
    if not isinstance(settings, dict):
        return
    if 'llm_no' in settings:
        try: agent.next_llm(int(settings['llm_no']))
        except Exception: pass


def _file_meta(path):
    p = Path(path)
    name = p.name
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    return {'path': str(p), 'name': name, 'mime': mime, 'isImage': mime.startswith('image/'), 'url': '/api/file/' + quote(name)}


def _file_to_blocks(files):
    blocks, saved = [], []
    for item in files or []:
        name = Path(item.get('name') or 'upload.bin').name
        data_url = item.get('dataUrl') or ''
        mime = item.get('type') or mimetypes.guess_type(name)[0] or 'application/octet-stream'
        raw = b''
        if data_url.startswith('data:') and ',' in data_url:
            head, payload = data_url.split(',', 1)
            if ';base64' in head:
                raw = base64.b64decode(payload)
        elif item.get('base64'):
            raw = base64.b64decode(item['base64'])
        if not raw:
            raise ValueError(f'附件为空或读取失败：{name}')
        if len(raw) > 15 * 1024 * 1024:
            raise ValueError(f'附件过大：{name} ({len(raw)/1024/1024:.1f}MB)，请压缩到 15MB 以内')
        safe = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}_{name}"
        out = UPLOAD_DIR / safe
        out.write_bytes(raw)
        saved.append(_file_meta(out))
        if mime.startswith('image/'):
            blocks.append({'type':'image_url','image_url':{'url': f'data:{mime};base64,{base64.b64encode(raw).decode("ascii")}'}})
    return blocks, saved

app = Bottle()

@app.error(413)
def _too_large(err):
    response.content_type = 'application/json; charset=utf-8'
    response.status = 413
    return json.dumps({'error': f'请求体过大，当前后端限制约 {MAX_REQUEST_BYTES//1024//1024}MB。请减少附件数量或压缩图片。'}, ensure_ascii=False)

@app.hook('after_request')
def _cors():
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,DELETE,OPTIONS'

@app.route('/api/<_:re:.*>', method='OPTIONS')
def _options(_):
    return ''

@app.get('/api/health')
def health():
    return _json({'ok': True, 'time': int(time.time())})

@app.get('/api/sessions')
def sessions():
    items=[]
    for p in SESSION_DIR.glob('*.json'):
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
            items.append({'id': d.get('id') or p.stem, 'title': d.get('title') or '未命名', 'updated_at': d.get('updated_at') or 0, 'count': len(d.get('messages') or [])})
        except Exception: pass
    items.sort(key=lambda x:x.get('updated_at') or 0, reverse=True)
    return _json({'sessions': items[:80]})

@app.post('/api/session/new')
def new_session():
    sid = uuid.uuid4().hex
    _save_session(sid, [])
    return _json({'id': sid, 'messages': []})

@app.get('/api/session/<sid>')
def get_session(sid):
    sid=_safe_id(sid)
    run = _run_snapshot(sid)
    return _json({'id': sid, 'messages': _load_messages(sid), 'run': run})

@app.get('/api/run/<sid>')
def get_run(sid):
    sid=_safe_id(sid)
    return _json({'id': sid, 'run': _run_snapshot(sid)})

@app.delete('/api/session/<sid>')
def delete_session(sid):
    p=_session_path(sid)
    if p.exists(): p.unlink()
    with _LOCK:
        _AGENTS.pop(_safe_id(sid), None)
        _RUNS.pop(_safe_id(sid), None)
    return _json({'ok': True})

@app.post('/api/abort/<sid>')
def abort(sid):
    a=_agent(_safe_id(sid))
    try: a.abort()
    except Exception as e: return _json({'ok': False, 'error': str(e)}, 500)
    return _json({'ok': True})

@app.post('/api/settings/<sid>')
def settings(sid):
    sid=_safe_id(sid)
    data=request.json or {}
    a=_agent(sid, data.get('llm_no',0))
    _apply_settings(a, data)
    b=_backend(a)
    return _json({'ok': True, 'llm_no': getattr(a,'llm_no',None), 'backend': type(b).__name__ if b else None})

@app.get('/api/state/<sid>')
def state(sid):
    a=_agent(_safe_id(sid))
    b=_backend(a)
    try: llms=[{'id': i, 'name': name or '', 'enabled': en} for i,name,en in a.list_llms()]
    except Exception: llms=[]
    return _json({'llm_no': getattr(a,'llm_no',0), 'llms': llms, 'backend': {'class': type(b).__name__ if b else '', 'name': getattr(b,'name','') if b else '', 'api_mode': getattr(b,'api_mode','') if b else '', 'thinking_type': getattr(b,'thinking_type','') if b else '', 'reasoning_effort': getattr(b,'reasoning_effort','') if b else ''}})

@app.post('/api/_debug/body_size')
def _debug_body_size():
    data = request.json or {}
    return _json({'ok': True, 'payload_chars': len(str(data.get('blob') or '')), 'max_request_mb': MAX_REQUEST_BYTES//1024//1024})

@app.post('/api/chat/<sid>')
def chat(sid):
    sid=_safe_id(sid)
    data=request.json or {}
    prompt=str(data.get('prompt') or '')
    files=data.get('files') or []
    settings=data.get('settings') or {}
    a=_agent(sid, settings.get('llm_no',0))
    _apply_settings(a, settings)
    image_blocks, saved_files = _file_to_blocks(files)
    display_prompt = prompt
    send_prompt = prompt
    if saved_files:
        refs='\n'.join(f'[FILE:{p.get("path", p.get("name", ""))}]' for p in saved_files)
        display_prompt=(display_prompt+'\n\n' if display_prompt else '')+'[附件已保存]\n'+refs
        send_prompt=(send_prompt+'\n\n' if send_prompt else '')+'[附件已保存]\n'+refs
    messages=_load_messages(sid)
    user_id = data.get('client_user_id') or uuid.uuid4().hex
    user_msg={'id': _safe_id(user_id), 'role':'user', 'content': display_prompt, 'files': saved_files, 'created_at': int(time.time())}
    messages.append(user_msg)
    _save_session(sid, messages)
    _set_run(sid, running=True, text='', user=user_msg, assistant_id=uuid.uuid4().hex, started_at=int(time.time()), updated_at=int(time.time()), error=False)

    response.content_type='application/x-ndjson; charset=utf-8'
    outq = queue.Queue()

    def emit(ev):
        try:
            outq.put(ev)
        except Exception:
            pass

    def worker():
        full=''
        try:
            dq=a.put_task(send_prompt, source='user', images=image_blocks)
            while True:
                item=dq.get(timeout=300)
                if 'next' in item:
                    chunk = item.get('next') or ''
                    # Normal path: a.inc_out=True makes `next` an incremental chunk.
                    # Defensive path: if an older/live agent still emits cumulative
                    # text, strip the already-sent prefix instead of duplicating it.
                    if chunk.startswith(full):
                        chunk = chunk[len(full):]
                    full += chunk
                    _set_run(sid, running=True, text=full, updated_at=int(time.time()), error=False)
                    emit({'type':'delta','text': full})
                if 'done' in item:
                    full=item.get('done') or full
                    msg={'id': uuid.uuid4().hex, 'role':'assistant', 'content': full, 'created_at': int(time.time())}
                    messages.append(msg)
                    _save_session(sid, messages)
                    _clear_run(sid)
                    emit({'type':'done','message': msg})
                    break
        except Exception as e:
            err='提交失败：%s: %s\n%s' % (type(e).__name__, e, traceback.format_exc())
            msg={'id': uuid.uuid4().hex, 'role':'assistant', 'content': err, 'created_at': int(time.time()), 'error': True}
            messages.append(msg); _save_session(sid, messages)
            _set_run(sid, running=False, text=err, updated_at=int(time.time()), error=True, message=msg)
            emit({'type':'error','message': msg})

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        yield json.dumps({'type':'user','message':user_msg}, ensure_ascii=False)+'\n'
        while True:
            ev = outq.get()
            yield json.dumps(ev, ensure_ascii=False)+'\n'
            if ev.get('type') in ('done','error'):
                break
    return gen()

@app.get('/api/file/<name:path>')
def get_uploaded_file(name):
    safe = Path(unquote(name)).name
    target = (UPLOAD_DIR / safe).resolve()
    root = UPLOAD_DIR.resolve()
    try:
        target.relative_to(root)
    except Exception:
        raise HTTPError(403, 'Forbidden')
    if not target.exists() or not target.is_file():
        raise HTTPError(404, 'Not found')
    return static_file(target.name, root=str(root))

@app.get('/')
def index():
    if (DIST_DIR/'index.html').exists():
        return static_file('index.html', root=str(DIST_DIR))
    return static_file('index.html', root=str(APP_DIR))

@app.get('/<path:path>')
def static(path):
    root = DIST_DIR if DIST_DIR.exists() else APP_DIR
    target = root / path
    if target.exists() and target.is_file():
        return static_file(path, root=str(root))
    return static_file('index.html', root=str(root))

if __name__ == '__main__':
    port=int(os.environ.get('GA_REACT_PORT','7861'))
    print(f'GA React frontend: http://127.0.0.1:{port}')
    run(app, host='127.0.0.1', port=port, server=ThreadedWSGIServer, quiet=False)
