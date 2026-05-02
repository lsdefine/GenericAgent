# -*- coding: utf-8 -*-
"""
自动路由策略测试用例
"""
from router_strategy import select_model, DummyContext

def run_tests():
    available = [
        'copilot-free', 'copilot-free-gpt41', 'copilot-free-gpt4o',
        'copilot-haiku', 'copilot-flash',
        'copilot-gpt4', 'copilot-claude', 'copilot-gemini', 'copilot-gpt52', 'copilot-gemini25',
        'opencode-minimax', 'opencode-big-pickle'
    ]
    cases = [
        # 默认对话
        (DummyContext(), None, None, 'copilot-free'),
        # quota 用尽
        (DummyContext(), None, 'exhausted', 'copilot-free'),
        # 多模态
        (DummyContext(multimodal=True), None, None, 'copilot-free-gpt4o'),
        # 长上下文（低门槛）
        (DummyContext(long_context=True, length=1200), None, None, 'copilot-free'),
        # 长上下文（高门槛）
        (DummyContext(long_context=True, length=3000), None, None, 'copilot-claude'),
        # 复杂代码（高门槛）
        (DummyContext(coding=True, complexity=2), None, None, 'copilot-gpt4'),
        # 代码（低门槛）
        (DummyContext(coding=True, complexity=1), None, None, 'copilot-free'),
        # 快问快答/兜底
        (DummyContext(), None, None, 'copilot-free'),
        # opencode-minimax 兜底
        (DummyContext(), None, None, 'copilot-free'),
        # opencode-big-pickle 兜底
        (DummyContext(), None, None, 'copilot-free'),
        # 手动 override
        (DummyContext(), 'copilot-gemini', None, 'copilot-gemini'),
    ]
    passed = 0
    for i, (ctx, override, quota, expect) in enumerate(cases):
        result = select_model(ctx, user_override=override, quota_state=quota, available_models=available)
        ok = (result == expect)
        print(f"Test {i+1}: expect={expect} got={result} {'✅' if ok else '❌'}")
        if ok: passed += 1
    print(f"Passed {passed}/{len(cases)}")

if __name__ == '__main__':
    run_tests()
