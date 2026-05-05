"""
无侵入自动路由插件（已清理重复内容，添加模块级幂等与状态暴露）

在 `mykey.py` 中包含 `my_plugins = ['my_auto_route_plugin']` 即会被 import。
插件会在模块 import 时尝试对 `GeneraticAgent` 做运行时 monkeypatch。
"""
from copy import deepcopy
import queue
import threading
import time
import re
import os

# 模块级幂等标志与简单状态，供外部 UI 或检查读取
__myauto_plugin_inited = False
plugin_status = {
    'patched': False,
    'last_init_time': None,
    'init_warnings': [],
}

try:
    # 延迟导入主模块与路由器，保证在插件被 import 时不会抛错
    from model_router import ModelRouter
    import agentmain
except Exception as e:
    # 如果无法导入，输出警告但不抛异常，保持无侵入性
    ModelRouter = None
    agentmain = None
    plugin_status['init_warnings'].append(str(e))


DEFAULT_ALLOWED = set([
    'copilot-free', 'copilot-free-gpt41', 'copilot-free-gpt4o',
    'opencode-minimax', 'opencode-big-pickle'
])


def _ensure_attrs(agent):
    """为 agent 实例注入自动路由相关状态（只做一次）。"""
    if getattr(agent, '_myauto_inited', False):
        return
    setattr(agent, '_myauto_inited', True)
    router = None
    try:
        if ModelRouter is not None:
            cfg_path = os.path.join(os.path.dirname(__file__), '..', 'auto_route_config.json')
            cfg_path = os.path.abspath(cfg_path)
            if os.path.exists(cfg_path):
                router = ModelRouter(config_path=cfg_path)
            else:
                router = ModelRouter()
    except Exception as e:
        plugin_status['init_warnings'].append(f"ModelRouter init failed: {e}")
        router = None
    agent._myauto_router = router
    agent._myauto_auto_route_enabled = bool(getattr(router, 'config', {}).get('enabled', True)) if router else True
    agent._myauto_manual_override = False
    agent._myauto_manual_turns = 0
    agent._myauto_auto_unlock_turns = 3
    agent._myauto_blocked_targets = {}
    agent._myauto_invalid_model_pattern = re.compile(r"Invalid model name passed in model=([^.'\"\s]+)", re.IGNORECASE)
    try:
        cfg_allowed = getattr(agent._myauto_router, 'config', {}).get('allowed_free_models') if agent._myauto_router else None
        if cfg_allowed and isinstance(cfg_allowed, (list, tuple)):
            agent._myauto_allowed_free_models = set(cfg_allowed)
        else:
            agent._myauto_allowed_free_models = DEFAULT_ALLOWED
    except Exception:
        agent._myauto_allowed_free_models = DEFAULT_ALLOWED


def _name_to_index(agent):
    mapping = {}
    for idx, client in enumerate(getattr(agent, 'llmclients', []) or []):
        try:
            backend = getattr(client, 'backend', None)
            name = getattr(backend, 'name', None)
            if name:
                mapping[name] = idx
        except Exception:
            continue
    return mapping


def _is_target_blocked(agent, target_name):
    if not target_name:
        return False
    info = agent._myauto_blocked_targets.get(target_name)
    if not info:
        return False
    exp = info.get('expires_at')
    if exp and time.time() > exp:
        try:
            del agent._myauto_blocked_targets[target_name]
        except Exception:
            pass
        return False
    return True


def _mark_target_blocked(agent, target_name, reason):
    if not target_name:
        return
    now = int(time.time())
    ttl = 300
    if reason == 'invalid_model_name':
        ttl = 3600
    if reason == 'quota_exhausted':
        ttl = 600
    agent._myauto_blocked_targets[target_name] = {
        'reason': reason,
        'at': now,
        'expires_at': now + ttl,
    }
    print(f"[MyAutoRoute] Blocked target {target_name} for {ttl}s due to {reason}")


def _record_execution_feedback(agent, executed_target, done_text):
    text = str(done_text or '')
    if not text:
        return
    if agent._myauto_invalid_model_pattern.search(text):
        _mark_target_blocked(agent, executed_target, 'invalid_model_name')
    if 'HTTP 429' in text or 'HTTP 503' in text:
        _mark_target_blocked(agent, executed_target, 'quota_exhausted')
    if 'HTTP 400' in text or 'Bad Request' in text:
        _mark_target_blocked(agent, executed_target, 'bad_request')


def _wrap_queue_with_feedback(agent, inner_queue, executed_target):
    if inner_queue is None:
        return inner_queue
    out = queue.Queue()

    def _pump():
        while True:
            item = inner_queue.get()
            try:
                if isinstance(item, dict) and 'done' in item:
                    _record_execution_feedback(agent, executed_target, item.get('done', ''))
                    out.put(item)
                    break
            except Exception:
                pass
            out.put(item)

    threading.Thread(target=_pump, daemon=True).start()
    return out


def _route_for_task(agent, query, images=None):
    images = images or []
    decision = None
    try:
        if agent._myauto_router:
            decision = agent._myauto_router.route(query=query, images=images, history=getattr(agent, 'history', []))
    except Exception:
        decision = None
    # 白名单断言
    if decision and getattr(decision, 'target_name', None):
        tname = decision.target_name
        if tname and tname not in agent._myauto_allowed_free_models:
            print(f"[MyAutoRoute] Blocking non-free auto-target {tname} (not in allowed_free_models)")
            decision.target_name = None
            _mark_target_blocked(agent, tname, 'not_in_whitelist')
    mapping = _name_to_index(agent)
    default_name = getattr(agent._myauto_router, 'config', {}).get('default_model') if agent._myauto_router else None
    route_targets = getattr(agent._myauto_router, 'config', {}).get('route_targets', {}) if agent._myauto_router else {}
    selected_name = decision.target_name if decision else None
    fallback_reason = None

    candidates = [selected_name, default_name, route_targets.get('fast')]
    selected_idx = None
    for candidate in candidates:
        if not candidate:
            continue
        if candidate not in mapping:
            if candidate == (decision.target_name if decision else None) and fallback_reason is None:
                fallback_reason = 'target_not_found'
            continue
        if _is_target_blocked(agent, candidate):
            fallback_reason = 'target_blocked_invalid_model'
            continue
        selected_name = candidate
        selected_idx = mapping[candidate]
        break

    if selected_idx is None:
        for candidate, idx in mapping.items():
            if _is_target_blocked(agent, candidate):
                continue
            selected_name = candidate
            selected_idx = idx
            fallback_reason = fallback_reason or 'default_not_found'
            break

    if selected_idx is None:
        selected_idx = getattr(agent, 'llm_no', 0)
        try:
            selected_name = agent.get_llm_name() if hasattr(agent, 'get_llm_name') else None
        except Exception:
            selected_name = None
        fallback_reason = fallback_reason or 'all_targets_blocked'

    last_route = {
        'target_name': decision.target_name if decision else None,
        'selected_name': selected_name,
        'selected_index': selected_idx,
        'reason': getattr(decision, 'reason', None) if decision else None,
        'details': deepcopy(getattr(decision, 'details', {})) if decision else {},
        'fallback_reason': fallback_reason,
        'manual_override': agent._myauto_manual_override,
        'auto_route_enabled': agent._myauto_auto_route_enabled,
        'blocked_targets': deepcopy(agent._myauto_blocked_targets),
    }
    agent._myauto_last_route = last_route
    return last_route


def patch_agent():
    global __myauto_plugin_inited, plugin_status
    if __myauto_plugin_inited:
        return
    __myauto_plugin_inited = True

    if agentmain is None:
        plugin_status['init_warnings'].append('agentmain not available')
        return
    GA = getattr(agentmain, 'GeneraticAgent', None)
    if GA is None:
        plugin_status['init_warnings'].append('GeneraticAgent not found in agentmain')
        return

    # 保存原方法
    if getattr(GA, '_myauto_patched', False):
        plugin_status['patched'] = True
        return
    GA._myauto_patched = True
    orig_put_task = GA.put_task

    # 注入 clear_manual_override 方法，兼容 UI 调用
    def clear_manual_override(self):
        self._myauto_manual_override = False
        self._myauto_manual_turns = 0
    GA.clear_manual_override = clear_manual_override

    def new_put_task(self, query, source='user', images=None):
        try:
            _ensure_attrs(self)
            if self._myauto_manual_override:
                self._myauto_manual_turns += 1
                if self._myauto_manual_turns >= self._myauto_auto_unlock_turns:
                    self._myauto_manual_override = False
                    self._myauto_manual_turns = 0
            executed_target = None
            if self._myauto_auto_route_enabled and not self._myauto_manual_override:
                route = _route_for_task(self, query, images=images)
                sel_idx = route.get('selected_index')
                try:
                    self.next_llm(sel_idx)
                except Exception:
                    pass
                self._myauto_last_route['previous_model'] = None
                try:
                    self._myauto_last_route['previous_model'] = self.get_llm_name() if hasattr(self, 'get_llm_name') else None
                except Exception:
                    pass
                try:
                    self._myauto_last_route['executed_model'] = self.get_llm_name() if hasattr(self, 'get_llm_name') else self._myauto_last_route.get('selected_name')
                except Exception:
                    self._myauto_last_route['executed_model'] = self._myauto_last_route.get('selected_name')
                executed_target = self._myauto_last_route.get('selected_name')
            else:
                self._myauto_last_route = {
                    'target_name': None,
                    'selected_name': getattr(self, 'get_llm_name') and self.get_llm_name(),
                    'selected_index': getattr(self, 'llm_no', 0),
                    'reason': 'manual_override' if self._myauto_manual_override else 'disabled',
                    'details': {'has_images': bool(images), 'query_length': len(query or '')},
                    'fallback_reason': None,
                    'manual_override': self._myauto_manual_override,
                    'auto_route_enabled': self._myauto_auto_route_enabled,
                    'previous_model': getattr(self, 'get_llm_name') and self.get_llm_name(),
                    'executed_model': getattr(self, 'get_llm_name') and self.get_llm_name(),
                    'blocked_targets': deepcopy(self._myauto_blocked_targets),
                }
            q = orig_put_task(self, query, source=source, images=images)
            return _wrap_queue_with_feedback(self, q, executed_target)
        except Exception:
            try:
                return orig_put_task(self, query, source=source, images=images)
            except Exception:
                raise

    GA.put_task = new_put_task
    plugin_status['patched'] = True
    plugin_status['last_init_time'] = int(time.time())


# 自动执行 patch，在模块 import 时就注入（但受模块级幂等保护）
try:
    patch_agent()
    print('[MyAutoRoute] Plugin initialized and patch applied')
except Exception as e:
    plugin_status['init_warnings'].append(str(e))
    print(f"[MyAutoRoute] Plugin patch failed: {e}")
