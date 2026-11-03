"""Optional P2P phone pairing plug-in for hub.py."""
import asyncio
import os
import socket
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from p2p_ws_client import (
    Group, HTTPExporter, HubUnion, connect_saved, create_code, load_room,
    retry_forever, save_room,
)


def install(app, *, web_port, token, here):
    signal = os.environ.get("GA_P2P_SIGNAL", "ws://47.101.182.29:49157/ws")
    name = os.environ.get("GA_P2P_NAME", "ga-hub-phone")
    rooms = Path(os.environ.get("GA_P2P_ROOMS", "~/.p2p_ws/rooms.json")).expanduser()
    # 组内每个 hub 一个成员名(hub: 前缀供 customer 自动连接)；被叫导出本机 API。
    member = "hub:" + os.environ.get("GA_P2P_MEMBER", f"{socket.gethostname()}-{web_port}")
    state = {"task": None, "invite": None, "status": "idle", "error": None,
             "started": False, "group": None, "legacy": None}
    union = HubUnion()  # 本机兼作 customer：/p2p/api/ 即组内其他 hub 的并集
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

    # ---- 旧 1 对 1 兼容(旧版手机直连 UUID 房)：只由在线 hub 中名字最小者进房。手机全升级后删本段 ----
    async def legacy(group):
        while True:
            hubs = [m for m in group.members if m.startswith("hub:")]
            lead = group._ws is not None and member < min(hubs, default="hub:\U0010ffff")
            task, pairing = state["legacy"], state["task"] and not state["task"].done()
            if lead and not pairing and (task is None or task.done()):
                state["legacy"] = asyncio.create_task(reconnect())
            elif not lead and group._ws is not None and task and not task.done():
                task.cancel()
                state["status"] = "standby"
            await asyncio.sleep(0.5)
    # ---- 旧 1 对 1 兼容 end ----

    def start_group():
        if state["group"]:
            return
        room = load_room(name, path=rooms)
        group = state["group"] = Group(
            room["signal_url"], room["room"], member, serve_customer, union.use,
        )
        state["group_tasks"] = [asyncio.create_task(group.run()), asyncio.create_task(legacy(group))]

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
                await ws.close()  # 之后由 legacy() 接管重连
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
                start_group()
        return Response(content='''<!doctype html><meta charset="utf-8"><title>PC pairing</title>
<h2>Phone pairing</h2><p>Enter this code on the phone:</p><pre id="code">waiting...</pre>
<p id="state">starting...</p><script>
async function poll(){try{let r=await fetch('/pair/status'),s=await r.json();
document.querySelector('#code').textContent=s.code||'-';
document.querySelector('#state').textContent=s.status+(s.error?' : '+s.error:'');
if(s.status!=='connected')setTimeout(poll,1000)}catch(e){document.querySelector('#state').textContent=e}}
poll();</script>''', media_type="text/html")

    @app.api_route("/p2p/api/{path:path}", methods=["GET", "POST"])
    async def p2p_api(request: Request, path: str):
        """组内其他 hub 的并集 API(会话名 name@hub)，用法同 /api/。首次调用才连接。"""
        group = state["group"]
        if not group:
            return JSONResponse({"error": "not paired"}, status_code=404)
        if not group.auto:
            group.auto = ("hub:",)
            group._sync(group.members)
            for _ in range(100):
                if union.hubs or not group.members:
                    break
                await asyncio.sleep(0.1)
        query = request.url.query
        status, body = await union.request(
            request.method, f"/api/{path}" + (f"?{query}" if query else ""), await request.body())
        return Response(body, status_code=status, media_type="application/json")

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
        start_group()

    app.add_event_handler("startup", startup)
    return state
