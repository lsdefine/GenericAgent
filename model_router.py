import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field


DEFAULT_ROUTER_CONFIG = {
    'enabled': True,
    'default_model': None,
    'route_targets': {
        'multimodal': None,
        'long_context': None,
        'coding': None,
        'fast': None,
    },
    'thresholds': {
        'long_query_chars': 800,
        'long_history_entries': 12,
    },
    'path_detection': {
        'enabled': True,
        'image_exts': ['.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.heic'],
        'video_exts': ['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v'],
        'doc_exts': ['.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt', '.md'],
    },
}

CODING_KEYWORDS = (
    'bug', 'debug', 'fix', 'patch', 'traceback', 'exception', 'error',
    '代码', '编程', '脚本', '函数', '修复', '调试', '报错', '异常', '补丁',
)

# Match common local path-like tokens, then classify by extension.
PATH_TOKEN_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+|\\\\[^\s\"'<>|]+|(?:\.{1,2}[\\/])?[^\s\"'<>|]+\.[A-Za-z0-9]{2,8})"
)


@dataclass
class RouteDecision:
    target_name: str | None
    reason: str
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class ModelRouter:
    def __init__(self, config=None, config_path=None):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._mtime = None
        self.last_reload_error = None
        self._stats = {
            'total': 0,
            'by_reason': {},
            'by_trigger': {},
        }

        loaded = {}
        if config is None:
            loaded = self._load_config_safely(config_path) or {}
        self.config = self._normalize_config(config or loaded)

    def _normalize_config(self, config):
        normalized = json.loads(json.dumps(DEFAULT_ROUTER_CONFIG))
        for key, value in (config or {}).items():
            if isinstance(value, dict) and isinstance(normalized.get(key), dict):
                normalized[key].update(value)
            else:
                normalized[key] = value
        return normalized

    def _load_from_path(self, config_path):
        if not config_path or not os.path.exists(config_path):
            return None
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_config_safely(self, config_path):
        if not config_path or not os.path.exists(config_path):
            return None
        try:
            cfg = self._load_from_path(config_path)
            self.last_reload_error = None
            try:
                self._mtime = os.path.getmtime(config_path)
            except OSError:
                self._mtime = None
            return cfg
        except Exception as e:
            self.last_reload_error = f'{type(e).__name__}: {e}'
            return None

    @staticmethod
    def _strip_code_regions(text):
        if not text:
            return ''
        text = re.sub(r'```[\s\S]*?```', ' ', text)
        text = re.sub(r'`[^`]*`', ' ', text)
        return text

    def _detect_path_signals(self, query):
        cfg = self.config.get('path_detection', {})
        if not cfg.get('enabled', True):
            return {
                'has_any_path': False,
                'has_vision_path': False,
                'has_doc_path': False,
                'image_paths': [],
                'video_paths': [],
                'doc_paths': [],
            }

        image_exts = {e.lower() for e in cfg.get('image_exts', [])}
        video_exts = {e.lower() for e in cfg.get('video_exts', [])}
        doc_exts = {e.lower() for e in cfg.get('doc_exts', [])}

        image_paths = []
        video_paths = []
        doc_paths = []

        text = self._strip_code_regions(query or '')
        for raw in PATH_TOKEN_PATTERN.findall(text):
            token = raw.strip('.,;:!?()[]{}<>\"\'')
            if not token or '://' in token:
                continue
            ext = os.path.splitext(token.lower())[1]
            if ext in image_exts:
                image_paths.append(token)
            elif ext in video_exts:
                video_paths.append(token)
            elif ext in doc_exts:
                doc_paths.append(token)

        return {
            'has_any_path': bool(image_paths or video_paths or doc_paths),
            'has_vision_path': bool(image_paths or video_paths),
            'has_doc_path': bool(doc_paths),
            'image_paths': image_paths,
            'video_paths': video_paths,
            'doc_paths': doc_paths,
        }

    def reload_if_needed(self):
        if not self.config_path or not os.path.exists(self.config_path):
            return False
        mtime = os.path.getmtime(self.config_path)
        if self._mtime == mtime:
            return False
        with self._lock:
            mtime = os.path.getmtime(self.config_path)
            if self._mtime == mtime:
                return False
            loaded = self._load_config_safely(self.config_path)
            if loaded is None:
                # Keep last known good config when reload fails.
                return False
            self.config = self._normalize_config(loaded)
            self._mtime = mtime
        return True

    def route(self, query, images=None, history=None):
        self.reload_if_needed()
        config = self.config
        images = images or []
        history = history or []
        query = query or ''
        thresholds = config.get('thresholds', {})
        route_targets = config.get('route_targets', {})
        query_lower = query.lower()
        path_signals = self._detect_path_signals(query)
        details = {
            'query_length': len(query),
            'history_entries': len(history),
            'has_images': bool(images),
            'path_signal': {
                'has_any_path': path_signals['has_any_path'],
                'has_vision_path': path_signals['has_vision_path'],
                'has_doc_path': path_signals['has_doc_path'],
                'image_count': len(path_signals['image_paths']),
                'video_count': len(path_signals['video_paths']),
                'doc_count': len(path_signals['doc_paths']),
            },
            'reload_error': self.last_reload_error,
        }

        if not config.get('enabled', True):
            details['trigger_source'] = 'disabled'
            self._update_routing_statistics('disabled', details['trigger_source'])
            return RouteDecision(config.get('default_model'), 'disabled', details)

        if images:
            details['trigger_source'] = 'images'
            self._update_routing_statistics('multimodal', details['trigger_source'])
            return RouteDecision(route_targets.get('multimodal') or config.get('default_model'), 'multimodal', details)

        if path_signals['has_vision_path']:
            details['trigger_source'] = 'path_vision'
            self._update_routing_statistics('multimodal_path', details['trigger_source'])
            return RouteDecision(route_targets.get('multimodal') or config.get('default_model'), 'multimodal_path', details)

        if path_signals['has_doc_path']:
            details['trigger_source'] = 'path_document'
            self._update_routing_statistics('document_path', details['trigger_source'])
            return RouteDecision(route_targets.get('long_context') or config.get('default_model'), 'document_path', details)

        if any(k in query_lower for k in CODING_KEYWORDS):
            details['trigger_source'] = 'coding_keyword'
            self._update_routing_statistics('coding', details['trigger_source'])
            return RouteDecision(route_targets.get('coding') or config.get('default_model'), 'coding', details)

        long_query_chars = int(thresholds.get('long_query_chars', DEFAULT_ROUTER_CONFIG['thresholds']['long_query_chars']))
        long_history_entries = int(thresholds.get('long_history_entries', DEFAULT_ROUTER_CONFIG['thresholds']['long_history_entries']))
        if len(query) >= long_query_chars or len(history) >= long_history_entries:
            details['trigger_source'] = 'long_context_threshold'
            self._update_routing_statistics('long_context', details['trigger_source'])
            return RouteDecision(route_targets.get('long_context') or config.get('default_model'), 'long_context', details)

        # Add routing statistics tracking
        details['trigger_source'] = 'default'
        # 默认优先 fast，再 default_model，再第一个可用
        fast_target = route_targets.get('fast')
        fallback_target = fast_target or config.get('default_model')
        reason = 'fast' if fast_target else 'default'
        if fallback_target is None:
            for v in route_targets.values():
                if v:
                    fallback_target = v
                    break
        self._update_routing_statistics(reason, details['trigger_source'])
        return RouteDecision(fallback_target, reason, details)

    def _update_routing_statistics(self, reason, trigger_source):
        self._stats['total'] += 1
        self._stats['by_reason'][reason] = self._stats['by_reason'].get(reason, 0) + 1
        self._stats['by_trigger'][trigger_source] = self._stats['by_trigger'].get(trigger_source, 0) + 1

    def get_statistics(self):
        total = max(1, self._stats['total'])
        by_reason = dict(self._stats['by_reason'])
        return {
            'total': self._stats['total'],
            'by_reason': by_reason,
            'by_trigger': dict(self._stats['by_trigger']),
            'fallback_rate': (by_reason.get('default', 0) / total),
        }