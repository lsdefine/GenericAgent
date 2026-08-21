#!/usr/bin/env python3
"""
Image Pipeline Integration Test
测试图片从前端上传到 LLM 接收的完整管线。

前置条件: bridge 在 127.0.0.1:14168 运行
运行: python3 frontends/desktop/testing/test_image_pipeline.py
"""
import base64, json, os, sys, time, urllib.request, urllib.error

# This is an operator-run integration script, not a hermetic pytest module.  Keep
# its descriptive test_* function names without allowing a repository-wide
# pytest invocation to collect it as an unattended test suite.
__test__ = False

BRIDGE = "http://127.0.0.1:14168"

# 1x1 red PNG (最小有效图片)
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg=="
)


def api(method, path, body=None):
    url = f"{BRIDGE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        print(f"  HTTP {e.code}: {body_text[:200]}")
        return None


def test_bridge_alive():
    print("[T0] Bridge alive check...")
    r = api("GET", "/status")
    assert r and r.get("ok"), f"Bridge not responding: {r}"
    print(f"  OK — {r.get('sessionCount')} sessions")
    return True


def test_upload():
    print("[T1] Upload image...")
    data_url = f"data:image/png;base64,{TINY_PNG_B64}"
    r = api("POST", "/upload", {"name": "test_pixel.png", "dataUrl": data_url, "sid": "_test"})
    assert r and r.get("ok"), f"Upload failed: {r}"
    path = r["path"]
    assert os.path.isfile(path), f"File not on disk: {path}"
    size = os.path.getsize(path)
    assert size > 0, "Uploaded file is empty"
    print(f"  OK — saved to {path} ({size} bytes)")
    return path


def test_send_with_image(image_path):
    print("[T2] Create session + send prompt with image...")
    r = api("POST", "/session/new", {"cwd": "", "mcp_servers": []})
    assert r and r.get("sessionId"), f"Session creation failed: {r}"
    sid = r["sessionId"]
    print(f"  Session: {sid}")

    r = api("POST", f"/session/{sid}/prompt", {
        "sessionId": sid,
        "prompt": "Describe what you see in the attached image in one sentence.",
        "display": "Describe the image",
        "llmNo": 0,
        "files": [],
        "imageMetas": [{"name": "test_pixel.png", "path": image_path}],
    })
    assert r and r.get("ok"), f"Prompt submission failed: {r}"
    print(f"  Prompt accepted, userMessageId={r.get('userMessageId')}")
    return sid


def test_poll_response(sid, timeout=120):
    print(f"[T3] Polling for response (timeout {timeout}s)...")
    start = time.time()
    last_content = ""
    while time.time() - start < timeout:
        r = api("GET", f"/session/{sid}/messages?limit=10")
        if not r:
            time.sleep(2)
            continue
        status = r.get("status", "idle")
        partial = r.get("partial")
        if partial and partial.get("content"):
            c = partial["content"]
            if c != last_content:
                last_content = c
                print(f"  ... streaming ({len(c)} chars)")

        if status == "idle" and r.get("messages"):
            msgs = r["messages"]
            assistant_msgs = [m for m in msgs if m.get("role") == "assistant"]
            if assistant_msgs:
                reply = assistant_msgs[-1].get("content", "")
                print(f"  Response ({len(reply)} chars): {reply[:120]}...")
                return reply
        time.sleep(2)
    print("  TIMEOUT — no response received")
    return None


def test_image_in_llm_log():
    """Check the latest model_responses log for image content blocks."""
    print("[T4] Checking LLM log for image blocks...")
    log_dir = os.path.join(os.path.dirname(__file__), "../../../temp/model_responses")
    log_dir = os.path.abspath(log_dir)
    if not os.path.isdir(log_dir):
        print(f"  SKIP — log dir not found: {log_dir}")
        return None

    files = sorted(
        [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".txt")],
        key=os.path.getmtime,
        reverse=True,
    )
    if not files:
        print("  SKIP — no log files")
        return None

    latest = files[0]
    content = open(latest, encoding="utf-8", errors="replace").read()
    has_image = '"type": "image"' in content or '"type":"image"' in content
    has_image_url = '"type": "image_url"' in content or '"type":"image_url"' in content
    if has_image or has_image_url:
        print(f"  OK — image block found in {os.path.basename(latest)}")
        return True
    else:
        print(f"  WARN — no image block in latest log ({os.path.basename(latest)})")
        return False


def main():
    print("=" * 60)
    print("Image Pipeline Integration Test")
    print("=" * 60)

    results = {}

    try:
        results["bridge"] = test_bridge_alive()
    except AssertionError as e:
        print(f"  FAIL: {e}")
        sys.exit(1)

    try:
        image_path = test_upload()
        results["upload"] = True
    except AssertionError as e:
        print(f"  FAIL: {e}")
        results["upload"] = False
        sys.exit(1)

    try:
        sid = test_send_with_image(image_path)
        results["send"] = True
    except AssertionError as e:
        print(f"  FAIL: {e}")
        results["send"] = False
        sys.exit(1)

    reply = test_poll_response(sid)
    results["response"] = reply is not None

    log_check = test_image_in_llm_log()
    results["log"] = log_check

    print("\n" + "=" * 60)
    print("Results:")
    for k, v in results.items():
        status = "PASS" if v else ("SKIP" if v is None else "FAIL")
        print(f"  [{status}] {k}")

    all_pass = all(v is not False for v in results.values())
    print(f"\n{'ALL PASS' if all_pass else 'SOME FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
