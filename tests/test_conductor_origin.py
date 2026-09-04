import importlib.util
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = ROOT / "frontends"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_old_argv = sys.argv[:]
try:
    sys.argv = [sys.argv[0], "--no-browser"]
    spec = importlib.util.spec_from_file_location("conductor", FRONTENDS / "conductor.py")
    assert spec and spec.loader
    conductor = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = conductor
    spec.loader.exec_module(conductor)
finally:
    sys.argv = _old_argv


def make_app():
    app = FastAPI()
    app.add_middleware(conductor.BrowserOriginGuard)

    @app.post("/probe")
    async def probe():
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        await ws.send_text("ok")
        await ws.close()

    return app


class ConductorBrowserOriginTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(make_app(), base_url="http://127.0.0.1:8900")

    def test_cross_origin_preflight_is_rejected(self):
        r = self.client.options(
            "/probe",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(r.status_code, 403)

    def test_cross_origin_post_is_rejected(self):
        r = self.client.post("/probe", headers={"Origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_dns_rebinding_origin_is_rejected_on_loopback(self):
        r = self.client.post(
            "/probe",
            headers={"Host": "evil.example:8900", "Origin": "https://evil.example"},
        )
        self.assertEqual(r.status_code, 403)

    def test_malformed_serialized_origins_are_rejected(self):
        origins = (
            "http://127.0.0.1:14168/path",
            "http://127.0.0.1:14168?x=1",
            "http://user@127.0.0.1:14168",
            "http://127.0.0.1:notaport",
            "http://127.0.0.1:14168#fragment",
        )
        for origin in origins:
            with self.subTest(origin=origin):
                r = self.client.post(
                    "/probe",
                    headers={"Host": "127.0.0.1:8900", "Origin": origin},
                )
                self.assertEqual(r.status_code, 403)

    def test_desktop_origin_same_hostname_different_port_is_allowed(self):
        origin = "http://127.0.0.1:14168"
        r = self.client.post("/probe", headers={"Origin": origin})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), origin)

    def test_null_origin_is_rejected(self):
        r = self.client.post("/probe", headers={"Origin": "null"})
        self.assertEqual(r.status_code, 403)

    def test_non_browser_request_without_origin_is_allowed(self):
        r = self.client.post("/probe")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)

    def test_cross_origin_websocket_is_rejected(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/ws",
                headers={"Host": "127.0.0.1:8900", "Origin": "https://evil.example"},
            ):
                pass

    def test_desktop_origin_websocket_is_allowed(self):
        with self.client.websocket_connect(
            "/ws",
            headers={"Host": "127.0.0.1:8900", "Origin": "http://127.0.0.1:14168"},
        ) as ws:
            self.assertEqual(ws.receive_text(), "ok")


if __name__ == "__main__":
    unittest.main()
