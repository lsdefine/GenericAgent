"""
Verification for fix/issue-729: require Authorization: Bearer <token> on /exec.

Before fix: ga_ultraplan.py do_POST accepted any POST to /exec with no
authentication — any local process that could reach 127.0.0.1:47831
could execute arbitrary Python in the daemon process.

After fix: a per-start token is minted in _serve_daemon (and propagated
through _show when auto-spawning). do_POST now requires
`Authorization: Bearer <token>` and uses secrets.compare_digest to
verify it. Without the header (or with a wrong header) the daemon
returns 401 and never enters the exec body.

This test exercises the daemon end-to-end in two ways:
  1. POST without Authorization header → 401 (the bug, now fixed).
  2. POST with the correct Bearer token → 200 with our canary file
     proving the request reached the exec sink.
  3. POST with a wrong Bearer token → 401 (compare_digest rejects).
"""
import json, os, secrets, socket, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

sys.path.insert(0, "/root/repos/GenericAgent")
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ga_ultraplan", "/root/repos/GenericAgent/assets/ga_ultraplan.py")
ga_ultraplan = importlib.util.module_from_spec(spec)
sys.modules["ga_ultraplan"] = ga_ultraplan
spec.loader.exec_module(ga_ultraplan)

import socket
# pick a free port
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _s:
    _s.bind(("127.0.0.1", 0))
    PORT = _s.getsockname()[1]

RUNDIR = tempfile.mkdtemp(prefix="ga-ultraplan-test-")
os.makedirs(RUNDIR, exist_ok=True)

# Configure the module for this test: distinct port + distinct run dir
ga_ultraplan._PORT = PORT
ga_ultraplan._RUN_DIR = RUNDIR
ga_ultraplan._TOKEN_FILE = os.path.join(RUNDIR, ".ultraplan_token")
ga_ultraplan._TOKEN = ""

# Start the daemon in-process via _serve_daemon in a thread so the test
# can drive it without launching a subprocess.
daemon_thread = threading.Thread(target=ga_ultraplan._serve_daemon, daemon=True)
daemon_thread.start()
for _ in range(40):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=0.5).read(1)
        break
    except Exception:
        time.sleep(0.1)

token = open(ga_ultraplan._TOKEN_FILE).read().strip()
assert len(token) > 20, f"token too short: {token!r}"


def _post(headers):
    nonce = "CANARY_" + secrets.token_hex(8)
    marker = os.path.join(tempfile.gettempdir(), nonce)
    code = f"from pathlib import Path; Path({marker!r}).write_text({nonce!r})\n"
    body = json.dumps({"rundir": RUNDIR, "code": code, "path": "<test>"}).encode()
    h = {"Content-Type": "application/json"}
    h.update(headers)
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/exec",
        data=body, headers=h, method="POST",
    )
    return urllib.request.urlopen(req), nonce, marker


# Case 1: no Authorization header → must fail with 401.
try:
    resp, _, _ = _post({})
    raise AssertionError(f"expected 401, got {resp.status}")
except urllib.error.HTTPError as e:
    assert e.code == 401, f"expected 401, got {e.code}"
print("✓ no Authorization header → 401")


# Case 2: wrong Bearer token → must fail with 401.
try:
    resp, _, _ = _post({"Authorization": "Bearer wrongtoken1234567"})
    raise AssertionError(f"expected 401, got {resp.status}")
except urllib.error.HTTPError as e:
    assert e.code == 401, f"expected 401, got {e.code}"
print("✓ wrong Bearer token → 401")


# Case 3: correct Bearer token → 200, canary file written.
resp, nonce, marker = _post({"Authorization": "Bearer " + token})
assert resp.status == 200, f"expected 200, got {resp.status}"
assert Path(marker).exists(), f"canary marker {marker} missing"
assert Path(marker).read_text() == nonce, f"canary content mismatch"
print("✓ correct Bearer token → 200, exec sink reached, canary written")


# Cleanup: shutdown the server so the daemon thread can exit.
try: ga_ultraplan._srv.shutdown()
except Exception: pass
time.sleep(0.2)
print("ALL CHECKS PASSED")
import os; os._exit(0)
