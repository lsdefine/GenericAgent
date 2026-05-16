#!/usr/bin/env python3
"""
GenericAgent Web2 Bridge.

Clear split:
1) AgentManager: owns GenericAgent instances, sessions and histories.
2) Transport: HTTP is the command/data channel; WebSocket only pushes small
   session-state notifications.

HTTP API:
  GET    /status
  GET    /config
  POST   /config
  GET    /model-profiles
  GET    /sessions
  POST   /session/new
  GET    /session/{sid}
  DELETE /session/{sid}
  POST   /session/{sid}/prompt
  GET    /session/{sid}/messages?after=0&limit=200
  POST   /session/{sid}/cancel

WS API:
  GET /ws -> events only, e.g.
  {"type":"session-state","sessionId":"sess-...","state":"running","seq":3,"updatedAt":...}
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from aiohttp import web, WSMsgType

APP_DIR = Path(__file__).resolve().parent


def find_default_ga_root() -> Path:
    """Find GenericAgent root near this bridge.

    Probe, in order:
      ../
      ../../
      ../GenericAgent
      ../../GenericAgent
    and return the first directory containing agentmain.py.
    """
    candidates = [
        APP_DIR / "..",
        APP_DIR / ".." / "..",
        APP_DIR / ".." / "GenericAgent",
        APP_DIR / ".." / ".." / "GenericAgent",
    ]
    for p in candidates:
        root = p.resolve()
        if (root / "agentmain.py").exists():
            return root
    return APP_DIR.parent.parent.resolve()


DEFAULT_GA_ROOT = find_default_ga_root()

for _s in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _s.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Agent management layer
# ---------------------------------------------------------------------------

@dataclass
class Session:
    id: str
    title: str = "New chat"
    cwd: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    messages: List[dict] = field(default_factory=list)
    msg_seq: int = 0
    partial: Optional[dict] = None
    status: str = "idle"  # idle|running|error|cancelled
    agent: Any = None
    thread: Optional[threading.Thread] = None
    cancel_requested: bool = False
    last_error: str = ""


class AgentManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.ga_root = str(DEFAULT_GA_ROOT)
        self.config: Dict[str, Any] = {}
        self.sessions: Dict[str, Session] = {}
        self.active_session_id: Optional[str] = None

    @property
    def mykey_path(self) -> str:
        return str(Path(self.ga_root) / "mykey.txt")

    def ensure_ga_import_path(self) -> Path:
        root = Path(self.ga_root).resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return root

    def make_agent(self, sess: Session):
        root = self.ensure_ga_import_path()
        old_cwd = os.getcwd()
        try:
            os.chdir(sess.cwd or str(root))
            agentmain = importlib.import_module("agentmain")
            GA = getattr(agentmain, "GenericAgent")
            agent = GA()
            agent.inc_out = True
            agent.verbose = True
            threading.Thread(target=agent.run, daemon=True, name=f"GA-{sess.id}").start()
            return agent
        finally:
            with contextlib.suppress(Exception):
                os.chdir(old_cwd)

    def list_model_profiles(self):
        self.ensure_ga_import_path()
        try:
            agentmain = importlib.import_module("agentmain")
            agent = agentmain.GenericAgent()
            if hasattr(agent, "list_llms"):
                return [{"id": i, "name": name, "active": active} for i, name, active in agent.list_llms()]
        except Exception as e:
            print(f"get model profiles failed: {e}", file=sys.stderr)
        return []

    def snapshot(self, sess: Session, include_messages: bool = True) -> dict:
        out = {
            "sessionId": sess.id,
            "id": sess.id,
            "title": sess.title,
            "cwd": sess.cwd,
            "status": sess.status,
            "createdAt": sess.created_at,
            "updatedAt": sess.updated_at,
            "lastError": sess.last_error,
            "msgSeq": sess.msg_seq,
        }
        if include_messages:
            out["messages"] = list(sess.messages)
            out["partial"] = dict(sess.partial) if sess.partial else None
        return out

    def add_message(self, sess: Session, role: str, content: str, **extra) -> dict:
        sess.msg_seq += 1
        msg = {"id": sess.msg_seq, "role": role, "content": content, "ts": time.time()}
        msg.update(extra)
        sess.messages.append(msg)
        sess.updated_at = time.time()
        if role == "user" and content.strip() and sess.title == "New chat":
            sess.title = content.strip().replace("\n", " ")[:40]
        return msg

    def create_session(self, cwd: Optional[str] = None) -> Session:
        sid = "sess-" + uuid.uuid4().hex[:12]
        sess = Session(id=sid, cwd=str(cwd or self.ga_root))
        with self.lock:
            self.sessions[sid] = sess
            self.active_session_id = sid
        emit_session_state(sess, "created")
        return sess

    def get_session(self, sid: str) -> Session:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            return sess

    def delete_session(self, sid: str) -> dict:
        with self.lock:
            sess = self.sessions.pop(sid, None)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            if self.active_session_id == sid:
                self.active_session_id = next(iter(self.sessions), None)
            if sess.agent and hasattr(sess.agent, "cancel"):
                with contextlib.suppress(Exception):
                    sess.agent.cancel()
        emit_session_state(sess, "closed")
        return {"ok": True, "sessionId": sid}

    def submit_prompt(self, sid: str, prompt: Any, images: Optional[list] = None) -> dict:
        prompt, image_ids = normalize_prompt(prompt, images)
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            if sess.status == "running":
                raise web.HTTPConflict(text=json.dumps({"error": "session is already running"}, ensure_ascii=False), content_type="application/json")
            extra = {}
            if image_ids:
                extra["image_ids"] = image_ids
            user_msg = self.add_message(sess, "user", prompt, **extra)
            sess.status = "running"
            sess.cancel_requested = False
            sess.last_error = ""
            sess.partial = {"id": sess.msg_seq + 1, "role": "assistant", "content": "", "ts": time.time(), "partial": True}
            t = threading.Thread(target=self.run_agent_turn, args=(sess, prompt, None), daemon=True, name=f"Turn-{sid}")
            sess.thread = t
            t.start()
            seq = sess.msg_seq
        emit_session_state(sess, "running")
        return {"ok": True, "sessionId": sid, "accepted": True, "userMessageId": user_msg["id"], "seq": seq}

    def run_agent_turn(self, sess: Session, prompt: str, images: Optional[list] = None):
        try:
            if sess.agent is None:
                sess.agent = self.make_agent(sess)
            agent = sess.agent
            full = ""
            if hasattr(agent, "put_task"):
                display_q = agent.put_task(prompt, images=images or [])
                pieces = []
                while True:
                    item = display_q.get()
                    if isinstance(item, dict):
                        if item.get("next"):
                            text = str(item["next"])
                            pieces.append(text)
                            with self.lock:
                                if sess.partial is not None:
                                    sess.partial["content"] = "".join(pieces) if getattr(agent, "inc_out", False) else text
                                    sess.partial["ts"] = time.time()
                                    sess.updated_at = time.time()
                        if "done" in item:
                            full = str(item.get("done") or "")
                            break
                    else:
                        pieces.append(str(item))
                if not full and pieces:
                    full = pieces[-1] if not getattr(agent, "inc_out", False) else "".join(pieces)
            elif hasattr(agent, "run"):
                ret = agent.run(prompt)
                if isinstance(ret, str):
                    full = ret
            else:
                full = "GenericAgent object has no put_task/run method"
            if not full:
                full = "(completed)"
            with self.lock:
                sess.partial = None
                # Strip trailing [Info] Final response to user. marker
                import re as _re
                full = _re.sub(r'\n*`{5}\n*\[Info\] Final response to user\.\n*`{5}\s*$', '', full)
                self.add_message(sess, "assistant", full)
                sess.status = "idle"
                sess.last_error = ""
            emit_session_state(sess, "idle")
        except Exception as e:
            tb = traceback.format_exc()
            with self.lock:
                sess.partial = None
                sess.status = "error"
                sess.last_error = str(e)
                self.add_message(sess, "error", str(e))
            print(tb, file=sys.stderr)
            emit_session_state(sess, "error")

    def messages(self, sid: str, after: int = 0, limit: int = 200) -> dict:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            msgs = [m for m in sess.messages if int(m.get("id", 0)) > after]
            if limit > 0:
                msgs = msgs[-limit:]
            return {
                "sessionId": sid,
                "status": sess.status,
                "messages": msgs,
                "partial": dict(sess.partial) if sess.partial else None,
                "msgSeq": sess.msg_seq,
                "updatedAt": sess.updated_at,
                "lastError": sess.last_error,
            }

    def cancel(self, sid: str) -> dict:
        with self.lock:
            sess = self.sessions.get(sid)
            if not sess:
                raise web.HTTPNotFound(text=json.dumps({"error": f"session not found: {sid}"}, ensure_ascii=False), content_type="application/json")
            sess.cancel_requested = True
            if sess.agent and hasattr(sess.agent, "cancel"):
                with contextlib.suppress(Exception):
                    sess.agent.cancel()
            sess.status = "cancelled"
            sess.partial = None
            sess.updated_at = time.time()
        emit_session_state(sess, "cancelled")
        return {"ok": True, "sessionId": sid}


import base64
import tempfile

# Shared temp dir for image uploads (persists for process lifetime)
_UPLOAD_DIR = Path(tempfile.gettempdir()) / "ga_web2_uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_image_data(data_url: str, img_id: str) -> str:
    """Save a data URL to disk, return absolute path."""
    # data:image/png;base64,xxxxx
    if "," in data_url:
        header, b64 = data_url.split(",", 1)
    else:
        b64 = data_url
        header = ""
    ext = "png"
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
    elif "webp" in header:
        ext = "webp"
    elif "gif" in header:
        ext = "gif"
    fpath = _UPLOAD_DIR / f"{img_id}.{ext}"
    fpath.write_bytes(base64.b64decode(b64))
    return str(fpath)


def normalize_prompt(prompt: Any, images: Optional[list] = None):
    """Normalize prompt and images.
    
    images: list of dicts {"id": "img-xxx", "dataUrl": "data:..."} or plain data URLs.
    Returns: (prompt_text_with_image_tags, image_ids_list)
    """
    images = list(images or [])
    if isinstance(prompt, list):
        text_parts = []
        for part in prompt:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in ("text", "input_text"):
                    text_parts.append(str(part.get("text") or part.get("content") or ""))
                elif part.get("type") in ("image", "input_image"):
                    url = part.get("image_url") or part.get("url") or part.get("data")
                    if isinstance(url, dict):
                        url = url.get("url")
                    if url:
                        images.append(url)
        prompt = "\n".join([p for p in text_parts if p])

    # Process images: save to disk, build [image:path] tags
    image_ids = []
    image_tags = []
    for img in images:
        if isinstance(img, dict):
            img_id = img.get("id") or f"img-{uuid.uuid4().hex[:8]}"
            data_url = img.get("dataUrl") or img.get("data_url") or ""
        else:
            # Plain data URL string
            img_id = f"img-{uuid.uuid4().hex[:8]}"
            data_url = str(img)
        if data_url:
            path = _save_image_data(data_url, img_id)
            image_tags.append(f"[image:{path}]")
            image_ids.append(img_id)

    # Append image tags to prompt
    final_prompt = str(prompt or "")
    if image_tags:
        final_prompt = final_prompt + "\n" + "\n".join(image_tags)

    return final_prompt, image_ids


manager = AgentManager()


# ---------------------------------------------------------------------------
# Transport layer: WS notification only
# ---------------------------------------------------------------------------

class WsHub:
    def __init__(self):
        self.websockets: Set[web.WebSocketResponse] = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def emit(self, obj: dict):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast(obj), self.loop)

    async def _broadcast(self, obj: dict):
        data = json.dumps(obj, ensure_ascii=False, default=str)
        dead = set()
        for ws in list(self.websockets):
            try:
                await ws.send_str(data)
            except Exception:
                dead.add(ws)
        self.websockets.difference_update(dead)


hub = WsHub()


def emit_session_state(sess: Session, state_name: str):
    hub.emit({
        "type": "session-state",
        "sessionId": sess.id,
        "state": state_name,
        "status": sess.status,
        "seq": sess.msg_seq,
        "updatedAt": sess.updated_at,
        "title": sess.title,
    })


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    hub.websockets.add(ws)
    await ws.send_str(json.dumps({
        "type": "bridge-ready",
        "gaRoot": manager.ga_root,
        "mykeyPath": manager.mykey_path,
        "http": True,
        "wsEventsOnly": True,
    }, ensure_ascii=False))
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            # WS is intentionally not a data/command channel anymore.
            with contextlib.suppress(Exception):
                data = json.loads(msg.data)
                if data.get("action") == "ping":
                    await ws.send_str(json.dumps({"type": "pong", "ts": time.time()}, ensure_ascii=False))
    hub.websockets.discard(ws)
    return ws


# ---------------------------------------------------------------------------
# Transport layer: HTTP command/data API
# ---------------------------------------------------------------------------

def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=cors_headers())
    resp = await handler(request)
    for k, v in cors_headers().items():
        resp.headers[k] = v
    return resp


def json_ok(data: dict, status: int = 200):
    return web.json_response(data, status=status, headers=cors_headers(), dumps=lambda x: json.dumps(x, ensure_ascii=False, default=str))


async def read_json(request) -> dict:
    if request.can_read_body:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


async def status_handler(request):
    return json_ok({
        "ok": True,
        "running": True,
        "ready": True,
        "gaRoot": manager.ga_root,
        "mykeyPath": manager.mykey_path,
        "sessionCount": len(manager.sessions),
        "activeSessionId": manager.active_session_id,
        "ws": "/ws",
        "transport": {"http": True, "wsEventsOnly": True},
    })


async def get_config_handler(request):
    return json_ok({"gaRoot": manager.ga_root, "mykeyPath": manager.mykey_path, "config": manager.config})


async def save_config_handler(request):
    data = await read_json(request)
    cfg = data.get("config", data)
    if isinstance(cfg, dict):
        manager.config.update(cfg)
    return json_ok({"ok": True, "gaRoot": manager.ga_root, "mykeyPath": manager.mykey_path, "config": manager.config})


async def model_profiles_handler(request):
    return json_ok({"profiles": manager.list_model_profiles()})


async def list_sessions_handler(request):
    with manager.lock:
        sessions = [manager.snapshot(s, include_messages=False) for s in manager.sessions.values()]
    return json_ok({"sessions": sessions, "activeSessionId": manager.active_session_id})


async def new_session_handler(request):
    data = await read_json(request)
    sess = manager.create_session(cwd=data.get("cwd") or data.get("path"))
    return json_ok({"ok": True, "sessionId": sess.id, "session": manager.snapshot(sess)}, status=201)


async def get_session_handler(request):
    sid = request.match_info["sid"]
    sess = manager.get_session(sid)
    return json_ok({"sessionId": sid, "session": manager.snapshot(sess), "messages": list(sess.messages), "partial": sess.partial})


async def delete_session_handler(request):
    sid = request.match_info["sid"]
    return json_ok(manager.delete_session(sid))


async def prompt_handler(request):
    sid = request.match_info["sid"]
    data = await read_json(request)
    prompt = data.get("prompt", data.get("content", data.get("message", "")))
    images = data.get("images") or []
    return json_ok(manager.submit_prompt(sid, prompt, images))


async def messages_handler(request):
    sid = request.match_info["sid"]
    after = int(request.query.get("after") or request.query.get("afterId") or 0)
    limit = int(request.query.get("limit") or 200)
    return json_ok(manager.messages(sid, after=after, limit=limit))


async def cancel_handler(request):
    sid = request.match_info["sid"]
    return json_ok(manager.cancel(sid))


async def path_open_handler(request):
    data = await read_json(request)
    kind = data.get("kind", "")
    if kind == "mykey":
        target = Path(manager.ga_root) / "mykey.py"
    else:
        target = Path(data.get("path") or data.get("target") or manager.ga_root)
    target = target.resolve()
    if not target.exists():
        return json_ok({"ok": False, "error": f"File not found: {target}"})
    # Actually open the file with the system default editor
    import subprocess, platform
    if platform.system() == "Windows":
        os.startfile(str(target))
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return json_ok({"ok": True, "path": str(target)})


def create_app():
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/status", status_handler)
    app.router.add_get("/config", get_config_handler)
    app.router.add_post("/config", save_config_handler)
    app.router.add_get("/model-profiles", model_profiles_handler)
    app.router.add_get("/sessions", list_sessions_handler)
    app.router.add_post("/session/new", new_session_handler)
    app.router.add_get("/session/{sid}", get_session_handler)
    app.router.add_delete("/session/{sid}", delete_session_handler)
    app.router.add_post("/session/{sid}/prompt", prompt_handler)
    app.router.add_get("/session/{sid}/messages", messages_handler)
    app.router.add_post("/session/{sid}/cancel", cancel_handler)
    app.router.add_post("/path/open", path_open_handler)

    # Serve static frontend (desktop/static/)
    static_dir = APP_DIR / "desktop" / "static"

    async def index_handler(request):
        return web.FileResponse(static_dir / "index.html")

    app.router.add_get("/", index_handler)
    app.router.add_static("/", static_dir, show_index=False)

    async def on_startup(app):
        hub.loop = asyncio.get_running_loop()

    app.on_startup.append(on_startup)
    return app


if __name__ == "__main__":
    host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ.get("BRIDGE_PORT", "14168"))
    print(f"GenericAgent Web2 bridge: http://{host}:{port}  ws://{host}:{port}/ws", file=sys.stderr)
    web.run_app(create_app(), host=host, port=port, print=None)
