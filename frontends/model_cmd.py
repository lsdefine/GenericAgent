"""/model 命令的 agent 无关逻辑: 拉模型列表 + 运行时改 model。
被 tuiapp_v2 import; 不 patch 任何类, 不依赖 llmcore。"""
from typing import Optional, List, Tuple

import requests


def _is_mixin(b) -> bool:
    return type(b).__name__ == 'MixinSession'


def _resolve(agent, sub: Optional[int] = None):
    """返回 (真正持有 model 的 session, mixin或None)。"""
    b = agent.llmclient.backend
    if _is_mixin(b):
        return b._sessions[b._cur_idx if sub is None else sub], b
    return b, None


def list_subsessions(agent) -> Optional[List[Tuple[int, str, bool]]]:
    """mixin 渠道 → [(idx, name, is_current)]; 普通渠道 → None。"""
    b = agent.llmclient.backend
    if not _is_mixin(b):
        return None
    return [(i, s.name, i == b._cur_idx) for i, s in enumerate(b._sessions)]


def current_model(agent, sub: Optional[int] = None) -> str:
    s, _ = _resolve(agent, sub)
    return s.model


def fetch_models(agent, sub: Optional[int] = None, timeout: int = 10) -> List[str]:
    """GET models 列表, 自动尝试 /models 与 /v1/models、原生头与 Bearer。"""
    s, _ = _resolve(agent, sub)
    base = s.api_base.rstrip('/')
    urls = [f'{base}/models'] + ([] if base.endswith('/v1') else [f'{base}/v1/models'])
    heads = [{'Authorization': f'Bearer {s.api_key}'}]
    if 'Claude' in type(s).__name__:
        heads.insert(0, {'x-api-key': s.api_key, 'anthropic-version': '2023-06-01'})
    err = None
    for url in urls:
        for h in heads:
            try:
                r = requests.get(url, headers=h, timeout=timeout,
                                 proxies=getattr(s, 'proxies', None),
                                 verify=getattr(s, 'verify', True))
                r.raise_for_status()
                data = r.json().get('data', [])  # 非 JSON(如 HTML 首页)会抛错进入下一候选
                ids = {m['id'] for m in data if isinstance(m, dict) and m.get('id')}
                if ids:
                    return sorted(ids)
            except Exception as e:
                err = e
    raise err or RuntimeError('no models endpoint')


def set_model(agent, model: str, sub: Optional[int] = None) -> str:
    """运行时改 model(内存态, mykey 重载/重启后还原)。返回结果描述。"""
    s, mixin = _resolve(agent, sub)
    old = s.model
    s.model = model  # mixin 的 model 是只读 property, 必须落子 session
    warn = ""
    try:  # 对齐 agentmain.next_llm 的中文 schema 切换
        from agentmain import load_tool_schema
        load_tool_schema('_cn' if any(x in model.lower() for x in ('glm', 'minimax', 'kimi')) else '')
    except Exception as ex:  # schema 选错会实际影响 agent 行为, 半径不为零, 不静默
        warn = f"  (⚠ schema 切换失败: {type(ex).__name__})"
    where = f"[{s.name}]" if mixin else s.name
    return f"{where}: {old} → {model}{warn}"


# GA 配置层允许的全部档位(llmcore BaseSession._enum)。各协议的真实支持面不同:
# Claude(output_config.effort) 只认 low/medium/high + xhigh→max, none/minimal
# 会被 _apply_claude_thinking 打 WARN 忽略; OpenAI 系(reasoning_effort /
# reasoning.effort) 原样透传, 由渠道端校验。
EFFORT_LEVELS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh']


def _protocols(agent) -> set:
    """当前渠道涉及的协议集合 {'claude', 'openai'}。mixin 看全部子渠道(广播
    会落到每一个)。NativeOAISession 名字不含 'Claude', 正确归入 openai。"""
    b = agent.llmclient.backend
    sessions = b._sessions if _is_mixin(b) else [b]
    return {('claude' if 'Claude' in type(s).__name__ else 'openai')
            for s in sessions}


def effort_note(level, protocols) -> str:
    """单点描述某档位在给定协议上的特殊行为(空串=无特殊)。set_effort 的结果
    描述与 /effort picker 的行内备注共用它, 领域知识只在此编码一次。"""
    if level and 'claude' in protocols:
        if level in ('none', 'minimal'):
            return 'Claude 渠道忽略'
        if level == 'xhigh':
            return 'Claude 对应 max'
    return ''


def current_effort(agent) -> str:
    return getattr(agent.llmclient.backend, 'reasoning_effort', None) or ''


def set_effort(agent, value) -> str:
    """运行时改 reasoning_effort(内存态)。空值/off 清除(不再发送 effort 字段)。
    直接设在 backend 上: MixinSession 把它列为 _BROADCAST_ATTRS, 会同步到所有
    子渠道(故障切换后档位不丢); 普通渠道就是 session 本身。请求时各协议现读
    该属性, 立即生效。"""
    e = (value or '').strip().lower()
    if e in ('', 'off', 'clear', 'unset'):
        e = None
    elif e not in EFFORT_LEVELS:
        return (f"无效 effort: {value!r}"
                f" (可选 {'/'.join(EFFORT_LEVELS)}, 留空或 off 清除)")
    b = agent.llmclient.backend
    old = getattr(b, 'reasoning_effort', None)
    b.reasoning_effort = e
    note = effort_note(e, _protocols(agent))
    tail = f" ({note})" if note else ""
    return f"reasoning_effort: {old or '(未设置)'} → {e or '(清除)'}{tail}"
