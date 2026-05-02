# -*- coding: utf-8 -*-
"""
自动路由策略严苛测试用例（全分支+极端场景+日志核查）
"""
from router_strategy import select_model, DummyContext
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("router_test")

def run_strict_tests():
    available = [
        'copilot-free', 'copilot-free-gpt41', 'copilot-free-gpt4o',
        'copilot-haiku', 'copilot-flash',
        'copilot-gpt4', 'copilot-claude', 'copilot-gemini', 'copilot-gpt52', 'copilot-gemini25',
        'opencode-minimax', 'opencode-big-pickle'
    ]
    cases = [
        # 1. 默认对话，优先低层级高性能
        (DummyContext(), None, None, 'copilot-free-gpt4o', '默认优先低层级高性能'),
        # 2. 免费模型 quota 用尽（仅 0x 自动路由）→ 无自动回退
        (DummyContext(), None, 'free_exhausted', None, '免费用尽→无自动回退'),
        # 3. 免费+低成本 quota 用尽（仅 0x 自动路由）→ 无自动回退
        (DummyContext(), None, 'lowcost_exhausted', None, '低成本用尽→无自动回退'),
        # 4. 所有 quota 用尽，None
        (DummyContext(), None, 'all_exhausted', None, '全部用尽→None'),
        # 5. 多模态优先低层级高性能
        (DummyContext(multimodal=True), None, None, 'copilot-free-gpt4o', '多模态优先低层级高性能'),
        # 6. 长上下文（低门槛）优先低层级高性能
        (DummyContext(long_context=True, length=1200), None, None, 'copilot-free-gpt4o', '长上下文-低门槛优先低层级高性能'),
        # 7. 长上下文（高门槛）——仅 0x 自动路由时降级到免费优先模型
        (DummyContext(long_context=True, length=3000), None, None, 'copilot-free-gpt4o', '长上下文-高门槛→免费优先降级'),
        # 8. 复杂代码（高门槛）——仅 0x 自动路由时降级到免费优先模型
        (DummyContext(coding=True, complexity=2), None, None, 'copilot-free-gpt4o', '复杂代码-高门槛→免费优先降级'),
        # 9. 代码（低门槛）优先低层级高性能
        (DummyContext(coding=True, complexity=1), None, None, 'copilot-free-gpt4o', '代码-低门槛优先低层级高性能'),
        # 10. 快问快答/兜底优先低层级高性能
        (DummyContext(), None, None, 'copilot-free-gpt4o', '快问快答优先低层级高性能'),
        # 11. 手动 override
        (DummyContext(), 'copilot-gemini', None, 'copilot-gemini', '手动 override'),
        # 12. 极端：所有模型都不可用
        (DummyContext(), None, 'all_exhausted', None, '全部不可用', []),
    ]
    passed = 0
    for i, case in enumerate(cases):
        ctx, override, quota, expect, desc = case[:5]
        custom_avail = case[5] if len(case) > 5 else available
        result = select_model(ctx, user_override=override, quota_state=quota, available_models=custom_avail)
        ok = (result == expect)
        logger.info(f"Test {i+1:02d} [{desc}]: expect={expect} got={result} {'✅' if ok else '❌'}")
        if ok: passed += 1
    logger.info(f"\nPassed {passed}/{len(cases)} (覆盖率{passed/len(cases)*100:.1f}%)\n")

if __name__ == '__main__':
    run_strict_tests()
