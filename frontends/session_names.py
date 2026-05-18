"""Persistent display names for `/continue`-able sessions.

JSON sidecar at `temp/model_responses/session_names.json` maps log-file
basename → user name. Touched only by `/rename` and `/continue <name>`.
"""
import glob, json, os, re, threading

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'temp', 'model_responses')
_REG_PATH = os.path.join(_LOG_DIR, 'session_names.json')
_LOG_RE = re.compile(r'^model_responses_(\d+)\.txt$')
_lock = threading.Lock()


def _load() -> dict:
    try:
        with open(_REG_PATH, encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d: dict) -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)
    tmp = _REG_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _REG_PATH)


def _resolve_basename(basename: str):
    # Registered file may be cleared by `continue_cmd._snapshot_current_log`
    # on /new or /continue; fall back to the newest non-empty snapshot of the
    # same PID so a mid-session rename survives the rotation.
    p = os.path.join(_LOG_DIR, basename)
    if os.path.isfile(p) and os.path.getsize(p) > 0:
        return p
    m = _LOG_RE.match(basename)
    if m:
        snaps = glob.glob(os.path.join(_LOG_DIR, f'model_responses_snapshot_{m.group(1)}_*.txt'))
        snaps.sort(key=os.path.getmtime, reverse=True)
        for s in snaps:
            if os.path.getsize(s) > 0:
                return s
    return None


def set_name(log_path: str, name: str) -> None:
    """Persist `name` for `log_path`. Empty name removes the entry."""
    key = os.path.basename(log_path)
    with _lock:
        d = _load()
        if name: d[key] = name
        else: d.pop(key, None)
        _save(d)


def migrate(old_path: str, new_path: str) -> None:
    """Move the entry from old basename to new basename after /continue."""
    if old_path == new_path: return
    old_key, new_key = os.path.basename(old_path), os.path.basename(new_path)
    with _lock:
        d = _load()
        if old_key in d:
            d[new_key] = d.pop(old_key)
            _save(d)


def name_for(log_path: str) -> str:
    return _load().get(os.path.basename(log_path), '')


def has_name(name: str, exclude_basename: str = None) -> bool:
    """True when any other entry already owns `name` (case-insensitive)."""
    target = (name or '').strip().lower()
    if not target: return False
    return any(v.lower() == target for k, v in _load().items() if k != exclude_basename)


def gc() -> int:
    """Drop entries whose log file is gone or empty. Returns count removed."""
    with _lock:
        d = _load()
        bad = [k for k in d if _resolve_basename(k) is None]
        for k in bad: d.pop(k)
        if bad: _save(d)
        return len(bad)


def path_for(name: str, exclude_basename: str = None):
    """Resolve `name` → newest resolvable log path. Exact-match then unique-prefix."""
    target = (name or '').strip().lower()
    if not target: return None
    d = _load()
    matches = [(k, v) for k, v in d.items() if v.lower() == target]
    if not matches:
        matches = [(k, v) for k, v in d.items() if v.lower().startswith(target)]
        if len(matches) > 1: matches = []
    if exclude_basename is not None:
        matches = [m for m in matches if m[0] != exclude_basename]
    resolved = [(p, k) for p, k in ((_resolve_basename(k), k) for k, _ in matches) if p]
    if not resolved: return None
    resolved.sort(key=lambda pk: os.path.getmtime(pk[0]), reverse=True)
    return resolved[0][0]
