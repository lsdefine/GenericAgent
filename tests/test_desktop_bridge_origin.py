import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


ROOT = Path(__file__).resolve().parents[1]
FRONTENDS = ROOT / "frontends"
if str(FRONTENDS) not in sys.path:
    sys.path.insert(0, str(FRONTENDS))

# desktop_bridge has import-time persistence/upload setup. Point it at an isolated
# valid GA root so test discovery cannot touch a developer's configured GA_ROOT.
_TEST_GA_ROOT = tempfile.TemporaryDirectory()
_TEST_GA_PATH = Path(_TEST_GA_ROOT.name)
(_TEST_GA_PATH / "agentmain.py").touch()
_old_ga_root = os.environ.get("GA_ROOT")
_old_argv = sys.argv[:]
os.environ["GA_ROOT"] = str(_TEST_GA_PATH)
sys.argv = [sys.argv[0]]
try:
    spec = importlib.util.spec_from_file_location("desktop_bridge", FRONTENDS / "desktop_bridge.py")
    assert spec and spec.loader
    bridge = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bridge
    spec.loader.exec_module(bridge)
finally:
    sys.argv = _old_argv
    if _old_ga_root is None:
        os.environ.pop("GA_ROOT", None)
    else:
        os.environ["GA_ROOT"] = _old_ga_root


class DesktopBridgeOriginTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application(middlewares=[bridge.cors_middleware])

        async def probe(request):
            return bridge.json_ok({"ok": True})

        app.router.add_post("/probe", probe)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_import_uses_isolated_ga_root(self):
        self.assertEqual(Path(bridge.DEFAULT_GA_ROOT), _TEST_GA_PATH)
        self.assertEqual(bridge._WEB_UPLOAD_DIR, _TEST_GA_PATH / "temp" / "desktop_uploads")

    async def test_cross_origin_preflight_is_rejected(self):
        response = await self.client.options(
            "/probe",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status, 403)

    async def test_cross_origin_post_is_rejected(self):
        response = await self.client.post(
            "/probe", headers={"Origin": "https://evil.example"}, json={}
        )
        self.assertEqual(response.status, 403)

    async def test_dns_rebinding_origin_is_rejected_on_loopback(self):
        response = await self.client.post(
            "/probe",
            headers={"Host": "evil.example:14168", "Origin": "https://evil.example:14168"},
            json={},
        )
        self.assertEqual(response.status, 403)

    async def test_malformed_serialized_origins_are_rejected(self):
        origin = str(self.client.make_url("/")).rstrip("/")
        origins = (
            f"{origin}/path",
            f"{origin}?x=1",
            origin.replace("http://", "http://user@", 1),
            "http://127.0.0.1:notaport",
            f"{origin}#fragment",
        )
        for candidate in origins:
            with self.subTest(origin=candidate):
                response = await self.client.post(
                    "/probe", headers={"Origin": candidate}, json={}
                )
                self.assertEqual(response.status, 403)

    async def test_null_origin_is_rejected(self):
        response = await self.client.post("/probe", headers={"Origin": "null"}, json={})
        self.assertEqual(response.status, 403)

    async def test_same_origin_request_is_allowed(self):
        origin = str(self.client.make_url("/")).rstrip("/")
        response = await self.client.post("/probe", headers={"Origin": origin}, json={})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)

    async def test_non_browser_request_without_origin_is_allowed(self):
        response = await self.client.post("/probe", json={})
        self.assertEqual(response.status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
