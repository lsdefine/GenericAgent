import queue
import re
import threading
import time
from copy import deepcopy

from model_router import ModelRouter


class AutoRoutingAgent:
    def __init__(self, base_agent, router=None, router_config=None, config_path=None):
        self.base_agent = base_agent
        self.router = router or ModelRouter(config=router_config, config_path=config_path)
        self.auto_route_enabled = bool(self.router.config.get('enabled', True))
        self.manual_override = False
        self.last_route = {}
        self._manual_override_turns = 0
        self._auto_unlock_turns = 3  # 可配置，默认3轮自动解锁
        self._blocked_targets = {}
        self._invalid_model_pattern = re.compile(r'Invalid model name passed in model=([^\.\'\"\s]+)', re.IGNORECASE)

    def __getattr__(self, name):
        return getattr(self.base_agent, name)

    def _name_to_index(self):
        mapping = {}
        for idx, client in enumerate(getattr(self.base_agent, 'llmclients', []) or []):
            backend = getattr(client, 'backend', None)
            name = getattr(backend, 'name', None)
            if name:
                mapping[name] = idx
        return mapping

    def enable_auto_route(self, enabled, clear_manual_override=False):
        self.auto_route_enabled = bool(enabled)
        self.router.config['enabled'] = self.auto_route_enabled
        if clear_manual_override:
            self.manual_override = False
            self._manual_override_turns = 0

    def _is_target_blocked(self, target_name):
        return bool(target_name) and target_name in self._blocked_targets

    def _mark_target_blocked(self, target_name, reason):
        if not target_name:
            return
        self._blocked_targets[target_name] = {
            'reason': reason,
            'at': int(time.time()),
        }

    def _record_execution_feedback(self, executed_target, done_text):
        text = str(done_text or '')
        if not text:
            return
        if self._invalid_model_pattern.search(text):
            self._mark_target_blocked(executed_target, 'invalid_model_name')

    def _wrap_queue_with_feedback(self, inner_queue, executed_target):
        if inner_queue is None:
            return inner_queue
        out = queue.Queue()

        def _pump():
            while True:
                item = inner_queue.get()
                if isinstance(item, dict) and 'done' in item:
                    self._record_execution_feedback(executed_target, item.get('done', ''))
                    out.put(item)
                    break
                out.put(item)

        threading.Thread(target=_pump, daemon=True).start()
        return out

    def next_llm(self, n=-1):
        self.manual_override = True
        self._manual_override_turns = 0
        return self.base_agent.next_llm(n)

    def clear_manual_override(self):
        self.manual_override = False
        self._manual_override_turns = 0

    def route_for_task(self, query, images=None):
        decision = self.router.route(query=query, images=images, history=getattr(self.base_agent, 'history', []))
        mapping = self._name_to_index()
        default_name = self.router.config.get('default_model')
        route_targets = self.router.config.get('route_targets', {})
        selected_name = decision.target_name
        fallback_reason = None

        candidates = [
            selected_name,
            default_name,
            route_targets.get('fast'),
        ]
        selected_idx = None
        for candidate in candidates:
            if not candidate:
                continue
            if candidate not in mapping:
                if candidate == decision.target_name and fallback_reason is None:
                    fallback_reason = 'target_not_found'
                continue
            if self._is_target_blocked(candidate):
                fallback_reason = 'target_blocked_invalid_model'
                continue
            selected_name = candidate
            selected_idx = mapping[candidate]
            break

        if selected_idx is None:
            for candidate, idx in mapping.items():
                if self._is_target_blocked(candidate):
                    continue
                selected_name = candidate
                selected_idx = idx
                fallback_reason = fallback_reason or 'default_not_found'
                break

        if selected_idx is None:
            # Last resort: all targets blocked, keep current model index.
            selected_idx = getattr(self.base_agent, 'llm_no', 0)
            selected_name = self.base_agent.get_llm_name() if hasattr(self.base_agent, 'get_llm_name') else None
            fallback_reason = fallback_reason or 'all_targets_blocked'

        self.last_route = {
            'target_name': decision.target_name,
            'selected_name': selected_name,
            'selected_index': selected_idx,
            'reason': decision.reason,
            'details': deepcopy(decision.details),
            'fallback_reason': fallback_reason,
            'manual_override': self.manual_override,
            'auto_route_enabled': self.auto_route_enabled,
            'blocked_targets': deepcopy(self._blocked_targets),
        }
        return self.last_route

    def put_task(self, query, source='user', images=None):
        images = images or []
        previous_model = self.base_agent.get_llm_name() if hasattr(self.base_agent, 'get_llm_name') else None
        # 自动解锁逻辑
        if self.manual_override:
            self._manual_override_turns += 1
            if self._manual_override_turns >= self._auto_unlock_turns:
                self.manual_override = False
                self._manual_override_turns = 0
        executed_target = None
        if self.auto_route_enabled and not self.manual_override:
            route = self.route_for_task(query, images=images)
            self.base_agent.next_llm(route['selected_index'])
            self.last_route['previous_model'] = previous_model
            self.last_route['executed_model'] = self.base_agent.get_llm_name() if hasattr(self.base_agent, 'get_llm_name') else route.get('selected_name')
            executed_target = route.get('selected_name')
        else:
            self.last_route = {
                'target_name': None,
                'selected_name': self.base_agent.get_llm_name(),
                'selected_index': getattr(self.base_agent, 'llm_no', 0),
                'reason': 'manual_override' if self.manual_override else 'disabled',
                'details': {'has_images': bool(images), 'query_length': len(query or '')},
                'fallback_reason': None,
                'manual_override': self.manual_override,
                'auto_route_enabled': self.auto_route_enabled,
                'previous_model': previous_model,
                'executed_model': self.base_agent.get_llm_name(),
                'blocked_targets': deepcopy(self._blocked_targets),
            }
        q = self.base_agent.put_task(query, source=source, images=images)
        return self._wrap_queue_with_feedback(q, executed_target)

    def route_status(self):
        if self.manual_override:
            effective_mode = 'manual_override'
        elif not self.auto_route_enabled:
            effective_mode = 'auto_route_disabled'
        else:
            effective_mode = 'auto_route'
        return {
            'auto_route_enabled': self.auto_route_enabled,
            'manual_override': self.manual_override,
            'effective_mode': effective_mode,
            'current_model': self.base_agent.get_llm_name() if getattr(self.base_agent, 'llmclient', None) else None,
            'blocked_targets': deepcopy(self._blocked_targets),
            'last_route': deepcopy(self.last_route),
        }

    def shutdown(self):
        abort = getattr(self.base_agent, 'abort', None)
        if callable(abort):
            abort()