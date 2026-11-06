"""Watchdog checks run in disposable processes, never the pytest process."""
import ast
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "fsapp.py"
TREE = ast.parse(SOURCE.read_text())
WATCHDOG = next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                and node.name == "_start_ws_client")
BOOTSTRAP = """
import asyncio, os, sys, threading, time
from types import SimpleNamespace
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
""" + ast.unparse(WATCHDOG) + "\n"


def run_child(code):
    return subprocess.run([sys.executable, "-c", BOOTSTRAP + textwrap.dedent(code)],
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("phase", ["startup", "running"])
def test_stalled_loop_exits_process(phase):
    result = run_child(f"""
        def start():
            if {phase!r} == 'running':
                loop.call_later(0.1, time.sleep, 3)
                loop.run_forever()
            else:
                time.sleep(3)
        _start_ws_client(SimpleNamespace(start=start), loop, timeout=0.3, interval=0.02)
        raise AssertionError('stalled client returned without watchdog exit')
    """)
    assert result.returncode == 1, result.stderr
    assert "飞书事件循环超过 0.3s 未响应" in result.stderr
    assert "Traceback" not in result.stderr


def test_idle_and_async_retry_wait_do_not_trigger_watchdog():
    result = run_child("""
        async def idle():
            # No incoming messages; longer than the watchdog deadline.
            await asyncio.sleep(0.9)
        for _ in range(2):
            _start_ws_client(SimpleNamespace(start=lambda: loop.run_until_complete(idle())),
                             loop, timeout=0.3, interval=0.02)
        assert not any(t.name == 'feishu-watchdog' for t in threading.enumerate())
        time.sleep(0.5)  # A stopped loop must not trigger a previous watcher.
        loop.close()
    """)
    assert result.returncode == 0, result.stderr
    assert not result.stderr


@pytest.mark.parametrize("error", ["RuntimeError", "KeyboardInterrupt"])
def test_start_failure_stops_watcher_and_preserves_exception(error):
    result = run_child(f"""
        def start():
            raise {error}('expected')
        try:
            _start_ws_client(SimpleNamespace(start=start), loop, timeout=0.3, interval=0.02)
        except {error} as exc:
            assert str(exc) == 'expected'
        else:
            raise AssertionError('exception swallowed')
        assert not any(t.name == 'feishu-watchdog' for t in threading.enumerate())
        time.sleep(0.5)
        loop.close()
    """)
    assert result.returncode == 0, result.stderr
    assert not result.stderr


def test_main_wraps_sdk_start_and_keeps_existing_backoff():
    main = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "main")
    calls, delays = [], []
    client, event_loop = object(), object()
    handler = object()
    builder = SimpleNamespace(register_p2_im_message_receive_v1=lambda *_: SimpleNamespace(build=lambda: handler))

    def guarded_start(actual_client, actual_loop):
        calls.append((actual_client, actual_loop))
        raise RuntimeError("simulate SDK failure")

    def sleep(delay):
        delays.append(delay)
        if len(delays) == 7:
            raise KeyboardInterrupt()

    namespace = {
        "_feishu_config": lambda: ("app", "secret", set(), False, "test-config"),
        "create_client": lambda: object(), "handle_message": lambda *_: None,
        "_start_ws_client": guarded_start, "ws_loop": event_loop,
        "time": SimpleNamespace(sleep=sleep),
        "traceback": SimpleNamespace(print_exc=lambda: None),
        "lark": SimpleNamespace(
            ws=SimpleNamespace(Client=lambda *a, **kw: client),
            EventDispatcherHandler=SimpleNamespace(builder=lambda *_: builder),
            LogLevel=SimpleNamespace(INFO="info")),
    }
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(SOURCE), "exec"), namespace)
    with pytest.raises(KeyboardInterrupt):
        namespace["main"]()
    assert calls == [(client, event_loop)] * 7
    assert delays == [5, 10, 20, 40, 80, 120, 120]
