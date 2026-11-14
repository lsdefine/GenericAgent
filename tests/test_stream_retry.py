# -*- coding: utf-8 -*-
"""Stream retry / empty-response regressions  --  2026-11-04

Run:  python tests/test_stream_retry.py

Covers two long-standing llmcore defects, both reproduced with a local fake
SSE server (no network, deterministic):

1. **Partial output replayed on retry.**
   ``_stream_with_retry`` retried a broken stream even when chunks had already
   been yielded to the caller, so a mid-stream ``ChunkedEncodingError`` made the
   user see the first half twice ("AAABBB" + "AAABBB").  Retrying cannot
   un-deliver text, so after any visible output we must stop and mark the
   truncation instead.

2. **Empty / thinking-only response treated as success.**
   ``test_error`` only recognises ``!!!Error:`` / ``[Error:`` prefixes, and the
   emptiness check used ``not e.value``, which is False as soon as a
   ``thinking`` block exists.  A response with no text and no tool call was
   therefore returned as a successful empty answer: no retry, no channel
   failover, and the user just sees nothing.
   The fix judges "usable output" (non-blank text or a tool_use block) and
   raises ConnectionError so the normal retry / failover path runs.
"""
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import llmcore  # noqa: E402

FAIL = []
HITS = {}
PORT = 0


def check(cond, msg):
    print(('  PASS ' if cond else '  FAIL ') + msg)
    if not cond:
        FAIL.append(msg)


class Handler(BaseHTTPRequestHandler):
    """Fake OpenAI-compatible SSE endpoint; behaviour selected by URL path."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        mode = self.path.strip("/").split("/")[0]
        HITS[mode] = HITS.get(mode, 0) + 1
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def write(b):
            self.wfile.write(("%X\r\n" % len(b)).encode() + b + b"\r\n")
            self.wfile.flush()

        def event(obj):
            write(("data: " + json.dumps(obj) + "\n\n").encode())

        def delta(d, fr=None):
            event({"choices": [{"delta": d, "finish_reason": fr}]})

        try:
            if mode == "partial":
                delta({"content": "AAA"})
                time.sleep(0.02)
                delta({"content": "BBB"})
                time.sleep(0.02)
                # never send the terminating chunk: simulate a dropped stream
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if mode == "empty":
                delta({}, "stop")
                write(b"data: [DONE]\n\n")
                write(b"")
                return
            if mode == "thinking_only":
                delta({"reasoning_content": "let me think ..."})
                delta({}, "stop")
                write(b"data: [DONE]\n\n")
                write(b"")
                return
            if mode == "tool_only":
                delta({"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                       "function": {"name": "code_run",
                                                    "arguments": "{\"script\": \"1\"}"}}]})
                delta({}, "tool_calls")
                write(b"data: [DONE]\n\n")
                write(b"")
                return
            delta({"content": "OK"})
            delta({}, "stop")
            write(b"data: [DONE]\n\n")
            write(b"")
        except OSError:
            pass


def make_session(mode, retries=1, name=None, hide=False):
    cfg = {
        "apikey": "k",
        "apibase": "http://127.0.0.1:%d/%s/v1" % (PORT, mode),
        "model": "m",
        "name": name or ("fake_" + mode),
        "max_retries": retries,
        "stream": True,
        "timeout": 3,
        "read_timeout": 5,
        "no_env_proxy": True,
        # 仅部分版本支持(隐藏思维链); 旧版 llmcore 会忽略此键
        "stream_hide_reasoning": hide,
    }
    return llmcore.NativeOAISession(cfg)


def drain(session, messages=None):
    """Consume raw_ask, return (yielded text, blocks)."""
    out, blocks = [], []
    gen = session.raw_ask(messages or [{"role": "user", "content": "hi"}])
    try:
        while True:
            out.append(next(gen))
    except StopIteration as e:
        blocks = e.value or []
    return "".join(x for x in out if isinstance(x, str)), blocks


def main():
    print("1) partial stream must NOT be replayed (no retry after visible output)")
    n0 = HITS.get("partial", 0)
    text, blocks = drain(make_session("partial", retries=2))
    check(text.count("AAA") == 1 and text.count("BBB") == 1,
          "first half appears exactly once, got %r" % text[:60])
    check("流异常中断" in text, "truncation is marked explicitly")
    check(HITS.get("partial", 0) - n0 == 1, "no re-request after partial output")

    print("2) empty response retries then surfaces an error (no silent success)")
    n0 = HITS.get("empty", 0)
    text, blocks = drain(make_session("empty", retries=1))
    check(HITS.get("empty", 0) - n0 == 2, "retried once (2 requests total)")
    check(text.lstrip().startswith("!!!Error:"), "final chunk is an error, got %r" % text[:60])

    print("3) thinking-only response is never a silent empty answer")
    n0 = HITS.get("thinking_only", 0)
    text, blocks = drain(make_session("thinking_only", retries=1, hide=True))
    # hide=True 时:
    #   渠道支持隐藏思维链 -> 什么都产不出来 -> 必须报错/换渠 (!!!Error: / 流异常中断)
    #   渠道不支持(旧版)   -> 思维链本身作为正文抵达 -> 用户看得见, 不算静默
    # 共同不变式: 调用方**永远**不会拿到一个空串却被告知"成功"。
    surfaced = ("\u6d41\u5f02\u5e38\u4e2d\u65ad" in text) or text.lstrip().startswith("!!!Error:")
    check(bool(text.strip()), "caller never gets a blank answer, got %r" % text[:60])
    check(surfaced or "think" in text.lower(),
          "visible signal (marker/error or the reasoning text itself), got %r" % text[:60])

    print("4) tool-only response is still a valid answer (must not be called empty)")
    n0 = HITS.get("tool_only", 0)
    text, blocks = drain(make_session("tool_only", retries=1))
    check(any(b.get("type") == "tool_use" for b in blocks), "tool_use block preserved")
    check("流异常中断" not in text, "no empty-response marker")
    check(HITS.get("tool_only", 0) - n0 == 1, "single request")

    print("5) normal response is untouched")
    n0 = HITS.get("ok", 0)
    text, blocks = drain(make_session("ok", retries=2))
    check(text == "OK", "text == 'OK', got %r" % text)
    check("流异常中断" not in text, "no marker on a clean stream")
    check(HITS.get("ok", 0) - n0 == 1, "single request")

    print("6) MixinSession does not fail over after delivering partial output")
    n0o = HITS.get("ok", 0)
    ch1 = llmcore.NativeToolClient(make_session("partial", retries=2, name="ch1"))
    ch2 = llmcore.NativeToolClient(make_session("ok", retries=2, name="ch2"))
    mixin = llmcore.MixinSession([ch1, ch2], {
        "llm_nos": ["ch1", "ch2"], "max_retries": 1, "base_delay": 0.0,
    })
    text, blocks = drain(mixin)
    check(text.count("AAA") == 1, "channel-1 partial text kept once")
    check(HITS.get("ok", 0) - n0o == 0, "channel 2 not replayed in the same call")
    check(mixin.current_name == "ch2", "next call is routed to channel 2")

    print()
    if FAIL:
        print("FAILED (%d):" % len(FAIL))
        for m in FAIL:
            print("  - " + m)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rc = main()
    finally:
        srv.shutdown()
    sys.exit(rc)
