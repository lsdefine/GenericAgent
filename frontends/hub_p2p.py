"""Optional P2P phone pairing plug-in for hub.py."""
import asyncio
import os
import socket
from pathlib import Path

from fastapi import Response
from fastapi.responses import JSONResponse
from p2p_ws_client import (
    Group, HTTPExporter, HTTPLocalProxy, connect_saved, create_code, load_room,
    retry_forever, save_room,
)


def install(app, *, web_port, token, here):
    signal = os.environ.get("GA_P2P_SIGNAL", "ws://47.101.182.29:49157/ws")
    name = os.environ.get("GA_P2P_NAME", "ga-hub-phone")
    rooms = Path(os.environ.get("GA_P2P_ROOMS", "~/.p2p_ws/rooms.json")).expanduser()
    # 多人组成员名带角色前缀：hub: 导出本机 API，cust: 代理对方 API。一条 P2PSocket
    # 只能有一个 HTTP 消费者，故同一进程以两个成员身份入组，每对连接角色唯一。
    member = os.environ.get("GA_P2P_MEMBER", f"{socket.gethostname()}-{web_port}")
    state = {"task": None, "invite": None, "status": "idle", "error": None,
             "started": False, "group": None, "hubs": {}}
    app.state.p2p_pair_open = True

    async def export(ws):
        exporter = await HTTPExporter(
            ws, f"http://127.0.0.1:{web_port}",
            allow=("/api/",), query={"t": token},
        ).start()
        try:
            state["status"], state["error"] = "connected", None
            await exporter.wait_closed()
        finally:
            await exporter.close()

    async def reconnect():
        async def once():
            state["status"], state["error"] = "reconnecting", None
            # 已配对候房不超时；信令断开仍立即失败并走退避。
            ws = await connect_saved(name, path=rooms, direct_timeout=15, peer_timeout=None)
            try:
                await export(ws)
            finally:
                await ws.close()  # 不关会泄漏信令连接: 旧连接与新连接自配对占满房间

        def failed(exc):
            state["status"], state["error"] = "error", str(exc)

        await retry_forever(once, failed)

    async def serve_customer(ws, peer):
        exporter = await HTTPExporter(
            ws, f"http://127.0.0.1:{web_port}", allow=("/api/",), query={"t": token},
        ).start()
        try:
            await exporter.wait_closed()
        finally:
            await exporter.close()

    async def use_hub(ws, peer):
        proxy = await HTTPLocalProxy(ws).start()
        state["hubs"][peer[4:]] = proxy.url
        try:
            await proxy.wait_closed()
        finally:
            if state["hubs"].get(peer[4:]) == proxy.url:
                del state["hubs"][peer[4:]]
            await proxy.close()

    def start_group():
        if state["group"]:
            return
        room = load_room(name, path=rooms)
        hub, cust = f"hub:{member}", f"cust:{member}"
        roles = ((hub, serve_customer, "cust:"), (cust, use_hub, "hub:"))
        state["group"] = [asyncio.create_task(Group(
            room["signal_url"], room["room"], me, serve,
            want=lambda p, other=other: p.startswith(other) and p[len(other):] != member,
        ).run()) for me, serve, other in roles]

    async def new_pair():
        try:
            invite = state["invite"] = await create_code(
                signal, name=name + "-pending", rooms_file=rooms,
            )
            state["status"], state["error"] = "waiting", None
            ws = await invite.connect(direct_timeout=15)
            save_room(signal, invite.room, name=name, path=rooms)
            start_group()
            try:
                await export(ws)
            finally:
                await ws.close()
                await reconnect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["status"], state["error"] = "error", str(exc)

    @app.get("/pair")
    async def pair():
        task = state["task"]
        if task is None or task.done():
            try:
                load_room(name, path=rooms)
            except KeyError:
                state["task"] = asyncio.create_task(new_pair())
            else:
                state["task"] = asyncio.create_task(reconnect())
        return Response(content='''<!doctype html><meta charset="utf-8"><title>PC pairing</title>
<h2>Phone pairing</h2><p>Enter this code on the phone:</p><pre id="code">waiting...</pre>
<p id="state">starting...</p><script>
async function poll(){try{let r=await fetch('/pair/status'),s=await r.json();
document.querySelector('#code').textContent=s.code||'-';
document.querySelector('#state').textContent=s.status+(s.error?' : '+s.error:'');
if(s.status!=='connected')setTimeout(poll,1000)}catch(e){document.querySelector('#state').textContent=e}}
poll();</script>''', media_type="text/html")

    @app.get("/p2p/hubs")
    async def p2p_hubs():
        """同组其他 hub 的本地代理地址 {成员名: http://127.0.0.1:端口}，按原 /api/ 访问。"""
        return JSONResponse(state["hubs"])

    @app.get("/pair/status")
    async def pair_status():
        invite = state["invite"]
        return JSONResponse({
            "status": state["status"],
            "code": getattr(invite, "code", None),
            "expires_at": getattr(invite, "expires_at", None),
            "error": state["error"],
        })

    async def startup():
        if state["started"]:
            return
        state["started"] = True
        try:
            load_room(name, path=rooms)
        except KeyError:
            return
        state["task"] = asyncio.create_task(reconnect())
        start_group()

    app.add_event_handler("startup", startup)
    return state
