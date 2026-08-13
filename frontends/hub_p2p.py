"""Optional P2P phone pairing plug-in for hub.py."""
import asyncio
import os
from pathlib import Path

from fastapi import Response
from fastapi.responses import JSONResponse
from p2p_ws_client import HTTPExporter, connect_saved, create_code, load_room, save_room


def install(app, *, web_port, token, here):
    signal = os.environ.get("GA_P2P_SIGNAL", "ws://47.101.182.29:49157/ws")
    name = os.environ.get("GA_P2P_NAME", "ga-hub-phone")
    rooms = Path(os.environ.get("GA_P2P_ROOMS", "~/.p2p_ws/rooms.json")).expanduser()
    state = {"task": None, "invite": None, "status": "idle", "error": None,
             "started": False}
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
        while True:
            connected = False
            try:
                state["status"], state["error"] = "reconnecting", None
                ws = await connect_saved(name, path=rooms, direct_timeout=15)
                connected = True
                try:
                    await export(ws)
                finally:
                    await ws.close()  # 不关会泄漏信令连接: 旧连接与新连接自配对占满房间
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state["status"], state["error"] = "error", str(exc)
            await asyncio.sleep(0.2 if connected else 5)

    async def new_pair():
        try:
            invite = state["invite"] = await create_code(
                signal, name=name + "-pending", rooms_file=rooms,
            )
            state["status"], state["error"] = "waiting", None
            ws = await invite.connect(direct_timeout=15)
            save_room(signal, invite.room, name=name, path=rooms)
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

    app.add_event_handler("startup", startup)
    return state
