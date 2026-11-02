"""Optional P2P phone pairing plug-in for hub.py."""
import asyncio
import os
import socket
import time
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
    # 组内每个 hub 一个成员名；连接按需建立：主叫代理对方 API，被叫导出本机 API。
    member = os.environ.get("GA_P2P_MEMBER", f"{socket.gethostname()}-{web_port}")
    state = {"task": None, "invite": None, "status": "idle", "error": None,
             "started": False, "group": None, "proxies": {}}
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
        state["proxies"][peer] = proxy
        try:
            await proxy.wait_closed()
        finally:
            if state["proxies"].get(peer) is proxy:
                del state["proxies"][peer]
            await proxy.close()

    async def reap_idle(group):
        while True:  # 10 分钟没请求的代理断开，下次 /p2p/open 再按需重连
            await asyncio.sleep(60)
            for peer, proxy in list(state["proxies"].items()):
                if time.monotonic() - proxy.last_used > 600:
                    group.close(peer)

    def start_group():
        if state["group"]:
            return
        room = load_room(name, path=rooms)
        group = state["group"] = Group(
            room["signal_url"], room["room"], member, serve_customer, use_hub,
        )
        state["group_tasks"] = [asyncio.create_task(group.run()), asyncio.create_task(reap_idle(group))]

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
        """同组在线 hub {成员名: 本地代理地址，未连接为 null}。"""
        group, proxies = state["group"], state["proxies"]
        members = sorted(group.members) if group else []
        return JSONResponse({m: getattr(proxies.get(m), "url", None) for m in members})

    @app.get("/p2p/open")
    async def p2p_open(hub: str):
        """按需连接 hub，返回本地代理地址，之后按原 /api/ 访问。"""
        group = state["group"]
        if not group or hub not in group.members:
            return JSONResponse({"error": "hub offline"}, status_code=404)
        group.open(hub)
        for _ in range(200):
            if proxy := state["proxies"].get(hub):
                proxy.last_used = time.monotonic()
                return JSONResponse({"url": proxy.url})
            await asyncio.sleep(0.1)
        return JSONResponse({"error": "connect timeout"}, status_code=504)

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
