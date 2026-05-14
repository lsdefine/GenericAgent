#!/usr/bin/env python3
"""Python Async 实操测试 — 运行真实异步代码验证"""
import json, sys, asyncio


async def run_async_tests():
    """执行多项异步操作并验证结果"""
    results = []
    
    # 测试1: async/await 基本调用
    async def echo(msg):
        return msg
    r1 = await echo("hello")
    assert r1 == "hello", f"async/await 失败: {r1}"
    results.append("async/await OK")
    
    # 测试2: asyncio.gather 并发
    async def double(n):
        await asyncio.sleep(0.01)
        return n * 2
    r2 = await asyncio.gather(double(1), double(2), double(3))
    assert r2 == [2, 4, 6], f"gather 失败: {r2}"
    results.append("gather OK")
    
    # 测试3: asyncio.timeout
    async def slow():
        await asyncio.sleep(10)
        return "slow"
    try:
        async with asyncio.timeout(0.01):
            await slow()
        results.append("timeout FAIL")
    except TimeoutError:
        results.append("timeout OK")
    
    # 测试4: asyncio.Queue 生产者消费者
    queue = asyncio.Queue()
    async def producer():
        for i in range(3):
            await queue.put(i)
        await queue.put(None)
    async def consumer():
        items = []
        while True:
            item = await queue.get()
            if item is None:
                break
            items.append(item)
        return items
    r4 = await asyncio.gather(producer(), consumer())
    assert r4[1] == [0, 1, 2], f"queue 失败: {r4[1]}"
    results.append("queue OK")
    
    return results


def main():
    result = {"score": 0, "passed": False, "note": ""}
    try:
        r = asyncio.run(run_async_tests())
        result["score"] = 100
        result["passed"] = True
        result["note"] = f"Async 实操测试通过！{' / '.join(r)}"
    except Exception as e:
        result["score"] = 50
        result["note"] = f"Async 测试失败: {e}"
    
    print(json.dumps(result))
    sys.exit(0 if result["passed"] else 1)




# ── 统一接口 ──
def run(env: dict = None) -> dict:
    """统一入口: run(env) 接收 env_detector 的输出，返回测试结果"""
    if env is None:
        try:
            from env_detector import detect_all
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                env = detect_all()
        except ImportError:
            import sys
            sys.path.insert(0, r"""D:\open_claw_agent\GenericAgent\tools\skill_learn_from_cases""")
            from env_detector import detect_all
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                env = detect_all()
    return main()


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False))
