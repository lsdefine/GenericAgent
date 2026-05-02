# -*- coding: utf-8 -*-
"""
AI模型自动路由主策略（含详细日志，适配 opencode/copilot/高门槛）
"""
import logging

def select_model(context, user_override=None, quota_state=None, available_models=None):
    """
    context: 需实现 is_multimodal(), is_long_context(), is_coding(), complexity, length 等接口
    user_override: 用户强制指定模型名
    quota_state: None/"exhausted"
    available_models: 可用模型名列表
    """
    log = logging.getLogger("router")
    def _log(*args):
        log.info("[ROUTE] " + " ".join(str(x) for x in args))

    # 1. 手动 override
    if user_override:
        _log("manual_override", user_override)
        return user_override

    # 仅0x层级参与自动路由
    free_models = [
        "copilot-free-gpt4o", "copilot-free-gpt41", "copilot-free",
        "opencode-minimax", "opencode-big-pickle"
        # 可在此扩充更多0x模型
    ]

    # 0x层级用尽直接None，其余层级不参与自动路由
    if quota_state in ("free_exhausted", "lowcost_exhausted", "all_exhausted"):
        _log("quota_0x_exhausted_none")
        return None

    # 仅0x层级自动分流
    if context.is_multimodal():
        for m in free_models:
            if m in available_models:
                _log("route", "multimodal", m)
                return m

    if context.is_long_context():
        for m in free_models:
            if m in available_models:
                _log("route", "long_context", m)
                return m

    if context.is_coding():
        for m in free_models:
            if m in available_models:
                _log("route", "coding", m)
                return m

    # 默认优先级：仅0x层级
    for m in free_models:
        if m in available_models:
            _log("route", "default", m)
            return m

    # 8. 极端兜底
    _log("route", "all_none")
    return None

# 示例 context stub（实际项目需替换为真实上下文对象）
class DummyContext:
    def __init__(self, multimodal=False, long_context=False, coding=False, length=0, complexity=1):
        self._multimodal = multimodal
        self._long_context = long_context
        self._coding = coding
        self.length = length
        self.complexity = complexity
    def is_multimodal(self): return self._multimodal
    def is_long_context(self): return self._long_context
    def is_coding(self): return self._coding
