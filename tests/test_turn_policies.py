#!/usr/bin/env python3
"""
测试验证: Turn 轮次策略 Hook 链
对应 ga.py: __init__ 中 _turn_policies 注册 + turn_end_callback 中 policy 循环

用法:
    cd D:\00synchronize\GenericAgent
    python tests\test_turn_policies.py
"""

import sys, os

script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, script_dir)

from ga import GenericAgentHandler

class MockParent:
    """模拟 GenericAgentHandler.parent 的最小对象"""
    def __init__(self):
        self.task_dir = script_dir
        self._turn_end_hooks = {}
        self.verbose = False

def _make_handler():
    return GenericAgentHandler(MockParent())

# ==== 单元测试: 各 Policy 阈值 ====

def test_ask_user_triggers():
    h = _make_handler()
    for turn in range(1, 200):
        result = h._policy_danger_ask_user(turn, None, "")
        if turn % 75 == 0:
            assert result != "" and "ask_user" in result, f"turn={turn}: 应触发ask_user"
        else:
            assert result == "", f"turn={turn}: 不应触发但返回: {result[:40]}"
    print("  [PASS] test_ask_user_triggers")

def test_ask_user_skipped_in_plan():
    h = _make_handler()
    for turn in [75, 150]:
        result = h._policy_danger_ask_user(turn, "some_plan.md", "")
        assert result == "", f"turn={turn} plan模式不应触发"
    print("  [PASS] test_ask_user_skipped_in_plan")

def test_retry_triggers():
    h = _make_handler()
    for turn in range(1, 150):
        result = h._policy_danger_retry(turn, None, "")
        if turn % 7 == 0:
            assert result != "" and "无效重试" in result, f"turn={turn}: 应触发"
        else:
            assert result == "", f"turn={turn}: 不应触发"
    print("  [PASS] test_retry_triggers")

def test_memory_triggers():
    h = _make_handler()
    for turn in range(1, 100):
        result = h._policy_inject_memory(turn, None, "")
        if turn % 10 == 0:
            assert result != "" and "[Memory]" in result, f"turn={turn}: 应触发"
        else:
            assert result == "", f"turn={turn}: 不应触发"
    print("  [PASS] test_memory_triggers")

def test_plan_hint():
    h = _make_handler()
    plan = "myplan.md"
    for turn in range(1, 150):
        result = h._policy_plan_limit(turn, plan, "")
        if 10 <= turn <= 110 and turn % 5 == 0:
            assert "Plan Hint" in result, f"turn={turn}: 应提示"
        elif turn >= 120:
            assert "已达上限" in result, f"turn={turn}: 应报警"
        else:
            assert result == "", f"turn={turn}: 不应触发但: {result[:40]}"
    print("  [PASS] test_plan_hint")

def test_plan_limit_nonplan():
    h = _make_handler()
    for t in [10, 50, 120]:
        assert h._policy_plan_limit(t, None, "") == "", f"turn={t} 非plan不应触发"
    print("  [PASS] test_plan_limit_nonplan")

# ==== 集成测试: Policy 链 ====

def test_chain_nonplan():
    h = _make_handler()
    for turn in [1, 7, 14, 20, 75, 77, 150]:
        np = ""
        for p in h._turn_policies:
            np += p(turn, None, np) or ""
        if turn == 75:
            assert "ask_user" in np, f"turn={turn}: 应ask_user"
        elif turn % 7 == 0 and turn % 10 == 0:
            assert "无效重试" in np and "[Memory]" in np, f"turn={turn}: 应双触发"
        elif turn % 7 == 0:
            assert "无效重试" in np, f"turn={turn}: 应重复试"
        elif turn % 10 == 0:
            assert "[Memory]" in np, f"turn={turn}: 应Memory"
        else:
            assert np == "", f"turn={turn}: 不应触发但: {np[:50]}"
    print("  [PASS] test_chain_nonplan")

def test_chain_plan():
    h = _make_handler()
    for turn in [5, 10, 15, 75, 110, 120]:
        np = ""
        for p in h._turn_policies:
            np += p(turn, "plan.md", np) or ""
        if turn == 75:
            assert "ask_user" not in np, "plan+75不应触发ask_user"
        if 10 <= turn <= 110 and turn % 5 == 0:
            assert "Plan Hint" in np, f"turn={turn}: 应有hint"
        if turn >= 120:
            assert "已达上限" in np, f"turn={turn}: 应上限"
    print("  [PASS] test_chain_plan")

def test_pluggable():
    h = _make_handler()
    n0 = len(h._turn_policies)
    called = []
    def custom(t, p, np):
        called.append(t); return ""
    h._turn_policies.append(custom)
    for p in h._turn_policies:
        p(42, None, "")
    assert 42 in called
    assert len(h._turn_policies) == n0 + 1
    h._turn_policies.pop()
    assert len(h._turn_policies) == n0
    print("  [PASS] test_pluggable")

def test_edge():
    h = _make_handler()
    for p in h._turn_policies:
        # turn=0: _policy_danger_retry 中 0%7==0 会触发, 但实际turn从1开始无影响
        # 仅验证不崩溃即可
        p(99999, None, "")  # 不应崩溃
    # None/False/"" 表现一致
    for p in h._turn_policies:
        assert p(75, None, "") == p(75, False, "") == p(75, "", "")
    print("  [PASS] test_edge")


if __name__ == "__main__":
    tests = [
        ("危险轮ask_user触发", test_ask_user_triggers),
        ("危险轮plan模式跳过", test_ask_user_skipped_in_plan),
        ("重试警告阈值", test_retry_triggers),
        ("记忆注入阈值", test_memory_triggers),
        ("Plan提示+上限", test_plan_hint),
        ("Plan提示非plan跳过", test_plan_limit_nonplan),
        ("集成链-非plan", test_chain_nonplan),
        ("集成链-plan模式", test_chain_plan),
        ("可插拔性", test_pluggable),
        ("边界值", test_edge),
    ]
    ok = 0
    fail = 0
    for name, fn in tests:
        try:
            fn()
            ok += 1
            print(f"  [OK] {name}")
        except AssertionError as e:
            fail += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            fail += 1
            print(f"  [ERROR] {name}: {e}")
    print(f"\n结果: {ok}/{ok+fail} 通过", end="")
    print(" ✅" if fail == 0 else f", {fail} 失败")
    exit(1 if fail else 0)
