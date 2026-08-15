"""
Verification for fix/issue-726: Remove loopback exemption in RemoteAuth.

Before fix: when --key is set, the auth predicate was
    if args.key and remote not in ("127.0.0.1", "::1") and not compare_digest(...)
That exempted loopback callers from auth (the security bug #726).

After fix: the same predicate becomes
    if args.key and not compare_digest(...)
So loopback callers must also send the Authorization header.

This test imports the conductor module with a monkey-patched `args` namespace
and exercises the RemoteAuth ASGI middleware against mock scopes to confirm:
  1. Loopback caller without Authorization header → 401 (the bug, now fixed).
  2. Loopback caller with correct Authorization header → passes through.
  3. Off-loopback caller without Authorization header → 401 (unchanged).
  4. When args.key is None (default), no auth check is performed (unchanged).
  5. WebSocket loopback without auth → connection closed.
"""
import asyncio, base64, importlib, sys
from types import SimpleNamespace

sys.path.insert(0, "/root/repos/GenericAgent")
# conductor.py has side-effects at import (uvicorn.run is NOT run because
# it sits under `if __name__ == '__main__'` — verified earlier). But
# top-level parser.parse_args() will read argv; we fake argv to skip launch.
saved_argv = sys.argv[:]
sys.argv = ["conductor.py", "--no-browser", "--host", "127.0.0.1", "--port", "8901"]
try:
    if "frontends.conductor" in sys.modules:
        mod = sys.modules["frontends.conductor"]
    else:
        mod = importlib.import_module("frontends.conductor")
finally:
    sys.argv = saved_argv

RemoteAuth = mod.RemoteAuth


def make_scope(client, auth_value=None, type_="http"):
    headers = []
    if auth_value is not None:
        headers.append((b"authorization", auth_value.encode()))
    return {"type": type_, "client": (client, 50000), "headers": headers}


def make_send_collector():
    out = []
    async def send(ev):
        out.append(ev)
    return send, out


async def receive_empty():
    return {"type": "http.request", "body": b"", "more_body": False}


async def drive(mw, scope):
    send, sent = make_send_collector()
    await mw(scope, receive_empty, send)
    return sent


async def downstream_ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"OK"})


def expect_401(events):
    return any(ev.get("type") == "http.response.start"
               and ev.get("status") == 401 for ev in events)


def expect_passthrough(events):
    return any(ev.get("type") == "http.response.start"
               and ev.get("status") == 200 for ev in events)


def expect_ws_close(events):
    return any(ev.get("type") == "websocket.close" for ev in events)


async def main():
    # Build the middleware instance — __init__ stores self.app.
    mw = RemoteAuth(downstream_ok)
    auth = "Basic " + base64.b64encode(b"conductor:s3cret").decode()
    other = "Basic " + base64.b64encode(b"conductor:wrong").decode()

    def with_key(k):
        mod.args = SimpleNamespace(key=k, host="127.0.0.1", port=8900)

    print("=== Test 1: loopback caller, --key set, no Authorization header → expect 401 (was the bug) ===")
    with_key("s3cret")
    ev = await drive(mw, make_scope("127.0.0.1", auth_value=None))
    assert expect_401(ev), f"Expected 401; got events: {ev}"
    print("  PASS")

    print("=== Test 2: loopback caller, --key set, correct Authorization → expect passthrough ===")
    with_key("s3cret")
    ev = await drive(mw, make_scope("127.0.0.1", auth_value=auth))
    assert expect_passthrough(ev), f"Expected 200; got events: {ev}"
    print("  PASS")

    print("=== Test 3: loopback caller, --key set, wrong Authorization → expect 401 ===")
    with_key("s3cret")
    ev = await drive(mw, make_scope("127.0.0.1", auth_value=other))
    assert expect_401(ev), f"Expected 401; got events: {ev}"
    print("  PASS")

    print("=== Test 4: off-loopback caller, --key set, no Authorization → expect 401 (unchanged) ===")
    with_key("s3cret")
    ev = await drive(mw, make_scope("10.0.0.5", auth_value=None))
    assert expect_401(ev), f"Expected 401; got events: {ev}"
    print("  PASS")

    print("=== Test 5: --key not set (default launch), no Authorization → expect passthrough (unchanged) ===")
    with_key(None)
    ev = await drive(mw, make_scope("127.0.0.1", auth_value=None))
    assert expect_passthrough(ev), f"Expected 200 (no key = no auth); got events: {ev}"
    print("  PASS")

    print("=== Test 6: off-loopback caller, --key set, correct Authorization → expect passthrough ===")
    with_key("s3cret")
    ev = await drive(mw, make_scope("10.0.0.5", auth_value=auth))
    assert expect_passthrough(ev), f"Expected 200; got events: {ev}"
    print("  PASS")

    print("=== Test 7: websocket scope, loopback no-auth → expect close code 1008 ===")
    with_key("s3cret")
    ev = await drive(mw, make_scope("127.0.0.1", auth_value=None, type_="websocket"))
    assert expect_ws_close(ev), f"Expected WS close; got events: {ev}"
    print("  PASS")

    print()
    print("ALL TESTS PASSED — loopback auth fix is correct.")


asyncio.run(main())
