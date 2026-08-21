"""Per-thread LLM token usage via llmcore monkey-patches.

`install()` wraps `llmcore._record_usage` + `llmcore.print` (the SSE
`messages` path only emits final `output_tokens` through `[Output] tokens=N`).
Trackers are keyed by `threading.current_thread().name`; each TUI session
runs its agent on `ga-tui-agent-<id>`, so `/cost` is a thread lookup.

Subagent processes are out-of-process, so `scan_subagent_logs` parses the
same `[Cache]` / `[Output]` print lines from `temp/*/stdout.log`.
"""
from __future__ import annotations
import glob, json, os, re, threading, time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TokenStats:
    requests: int = 0
    input: int = 0
    output: int = 0
    cache_create: int = 0
    cache_read: int = 0
    # Latest single-LLM-call sizes — drive the spinner's `↑ N · ↓ M`.
    last_input: int = 0
    last_output: int = 0
    started_at: float = field(default_factory=time.time)

    def total_input_side(self) -> int:
        return self.input + self.cache_create + self.cache_read

    def total_tokens(self) -> int:
        return self.input + self.output + self.cache_create + self.cache_read

    def cache_hit_rate(self) -> float:
        side = self.total_input_side()
        return (self.cache_read / side * 100.0) if side else 0.0

    def elapsed_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)


# GA's real context budget lives on `BaseSession.context_win` (chars). The
# trim trigger is `context_win * 3` (see llmcore.trim_messages_history), so
# `/cost` compares actual-history chars against that cap for consistent units.
def context_window_chars(backend) -> int:
    """`context_win * 3` — the char cap before `trim_messages_history` kicks
    in. Reads dynamically so a `mykey.py` override propagates. Returns 0 on
    bad/missing backend so the caller can hide the row."""
    try:
        return int(getattr(backend, 'context_win', 0)) * 3
    except (TypeError, ValueError):
        return 0


def current_input_chars(backend) -> int:
    """Char-size of the message history (same unit as `trim_messages_history`)."""
    try:
        import json as _json
        history = getattr(backend, 'history', None) or []
        return sum(len(_json.dumps(m, ensure_ascii=False)) for m in history)
    except Exception:
        return 0


_trackers: dict[str, TokenStats] = {}
_lock = threading.Lock()
_OUT_RE = re.compile(r'\[Output\]\s+tokens=(\d+)')
_CACHE_RE_NEW = re.compile(r'\[Cache\]\s+input=(\d+)\s+creation=(\d+)\s+read=(\d+)')
_CACHE_RE_OLD = re.compile(r'\[Cache\]\s+input=(\d+)\s+cached=(\d+)')
_INSTALLED = False
_SUBAGENT_GLOB = os.path.join("temp", "*", "stdout.log")

# ── Per-call ledger ──────────────────────────────────────────────────────────

_ledger_path: Path | None = None
_ledger_fd = None
_ledger_lock = threading.RLock()
_ledger_uncompacted_bytes = 0
_LEDGER_FILENAME = "token_ledger.jsonl"
_LEGACY_HISTORY_FILENAME = "desktop_token_history.json"
_COMPACT_THRESHOLD = 10 * 1024 * 1024  # 10MB


def _migrate_legacy_history_unlocked() -> None:
    """Seed an empty ledger from the previous aggregate JSON format once."""
    global _ledger_uncompacted_bytes
    if _ledger_path is None or _ledger_fd is None:
        return
    legacy_path = _ledger_path.with_name(_LEGACY_HISTORY_FILENAME)
    try:
        if _ledger_path.stat().st_size or not legacy_path.is_file():
            return
        doc = json.loads(legacy_path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("snap"), dict):
            return
        metadata: dict[str, dict] = {}
        for entry in doc.get("history", []):
            if not isinstance(entry, dict):
                continue
            sid = entry.get("sessionId") or entry.get("id")
            if not isinstance(sid, str) or not sid:
                continue
            key = sid if sid.startswith("GA-") else f"GA-{sid}"
            try:
                ts = float(entry.get("ts", 0) or 0)
            except (TypeError, ValueError):
                ts = 0
            if key not in metadata or ts >= metadata[key]["ts"]:
                metadata[key] = {
                    "ts": ts,
                    "model": entry.get("model") if isinstance(entry.get("model"), str) else "",
                    "title": entry.get("title") if isinstance(entry.get("title"), str) else "",
                }
        fallback_ts = legacy_path.stat().st_mtime
        for key, totals in doc["snap"].items():
            if not isinstance(key, str) or not key or not isinstance(totals, dict):
                continue
            try:
                values = {
                    "i": int(totals.get("input", 0) or 0),
                    "o": int(totals.get("output", 0) or 0),
                    "cc": int(totals.get("cacheCreate", totals.get("cacheWrite", 0)) or 0),
                    "cr": int(totals.get("cacheRead", 0) or 0),
                }
            except (TypeError, ValueError):
                continue
            meta = metadata.get(key, {})
            line = json.dumps(
                {"t": meta.get("ts") or fallback_ts, "k": key, **values,
                 "m": meta.get("model", ""), "n": meta.get("title", ""), "_migrated": True},
                separators=(",", ":"),
            ) + "\n"
            _ledger_fd.write(line)
            _ledger_uncompacted_bytes += len(line.encode("utf-8"))
        _ledger_fd.flush()
    except Exception:
        return


def init_ledger(root: str) -> None:
    """Call once at bridge startup to set the ledger file path."""
    global _ledger_path, _ledger_fd, _ledger_uncompacted_bytes
    with _ledger_lock:
        if _ledger_fd is not None:
            try:
                _ledger_fd.close()
            except Exception:
                pass
        _ledger_path = Path(root) / "temp" / _LEDGER_FILENAME
        _ledger_path.parent.mkdir(parents=True, exist_ok=True)
        _ledger_fd = open(_ledger_path, "a", encoding="utf-8")
        try:
            _ledger_uncompacted_bytes = _ledger_path.stat().st_size
            if _ledger_uncompacted_bytes == 0:
                _migrate_legacy_history_unlocked()
            if _ledger_uncompacted_bytes >= _COMPACT_THRESHOLD:
                _compact_ledger()
        except OSError:
            _ledger_uncompacted_bytes = 0


def _append_ledger(thread_key: str, inp: int, out: int, cc: int, cr: int) -> None:
    global _ledger_uncompacted_bytes
    line = json.dumps(
        {"t": time.time(), "k": thread_key, "i": inp, "o": out, "cc": cc, "cr": cr},
        separators=(",", ":"),
    ) + "\n"
    with _ledger_lock:
        if _ledger_fd is None:
            return
        try:
            _ledger_fd.write(line)
            _ledger_fd.flush()
            _ledger_uncompacted_bytes += len(line.encode("utf-8"))
            if _ledger_uncompacted_bytes >= _COMPACT_THRESHOLD:
                _compact_ledger()
        except Exception:
            pass


def _iter_ledger_unlocked():
    if _ledger_path is None or not _ledger_path.is_file():
        return
    try:
        with open(_ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if isinstance(entry, dict):
                        yield entry
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return


def read_ledger() -> list[dict]:
    """Read all valid lines from the ledger. Skips corrupted lines."""
    with _ledger_lock:
        return list(_iter_ledger_unlocked())


def _aggregate_sessions(entries) -> dict[str, dict]:
    sessions: dict[str, dict] = {}
    for e in entries:
        k = e.get("k", "")
        if not isinstance(k, str) or not k:
            continue
        try:
            ts = float(e.get("t", 0) or 0)
            inp = int(e.get("i", 0) or 0)
            out = int(e.get("o", 0) or 0)
            cc = int(e.get("cc", 0) or 0)
            cr = int(e.get("cr", 0) or 0)
        except (TypeError, ValueError):
            continue
        if k not in sessions:
            sessions[k] = {"input": 0, "output": 0, "cacheCreate": 0, "cacheRead": 0,
                           "model": "", "title": "", "first_ts": ts, "last_ts": ts}
        s = sessions[k]
        s["input"] += inp
        s["output"] += out
        s["cacheCreate"] += cc
        s["cacheRead"] += cr
        s["first_ts"] = min(s["first_ts"], ts)
        s["last_ts"] = max(s["last_ts"], ts)
        if isinstance(e.get("m"), str) and e["m"]:
            s["model"] = e["m"]
        if isinstance(e.get("n"), str) and e["n"]:
            s["title"] = e["n"]
    return sessions


def _format_aggregate(sessions: dict[str, dict]) -> dict:
    history = []
    snap = {}
    for k, s in sessions.items():
        sid = k.removeprefix("GA-")
        history.append({
            "sessionId": sid,
            "title": s["title"] or sid,
            "input": s["input"],
            "output": s["output"],
            "cacheCreate": s["cacheCreate"],
            "cacheRead": s["cacheRead"],
            "model": s["model"],
            "ts": s["last_ts"],
        })
        snap[k] = {
            "input": s["input"],
            "output": s["output"],
            "cacheCreate": s["cacheCreate"],
            "cacheRead": s["cacheRead"],
        }
    return {"history": history, "snap": snap}


def aggregate_ledger() -> dict:
    """Aggregate ledger into {history: [...], snap: {...}} for /token-history."""
    with _ledger_lock:
        return _format_aggregate(_aggregate_sessions(_iter_ledger_unlocked()))


def _compact_ledger() -> None:
    """Compact ledger by aggregating into per-session totals and rewriting."""
    if _ledger_path is None:
        return
    global _ledger_fd, _ledger_uncompacted_bytes
    with _ledger_lock:
        temp_path = _ledger_path.with_suffix(".jsonl.tmp")
        try:
            if _ledger_fd is not None:
                _ledger_fd.flush()
            sessions = _aggregate_sessions(_iter_ledger_unlocked())
            with open(temp_path, "w", encoding="utf-8") as f:
                for k, s in sessions.items():
                    line = json.dumps(
                        {"t": s["last_ts"], "k": k, "i": s["input"], "o": s["output"],
                         "cc": s["cacheCreate"], "cr": s["cacheRead"], "m": s["model"],
                         "n": s["title"],
                         "_compacted": True},
                        separators=(",", ":"),
                    )
                    f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            if _ledger_fd is not None:
                _ledger_fd.close()
                _ledger_fd = None
            os.replace(temp_path, _ledger_path)
            _ledger_fd = open(_ledger_path, "a", encoding="utf-8")
            _ledger_uncompacted_bytes = 0
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            if _ledger_fd is None:
                try:
                    _ledger_fd = open(_ledger_path, "a", encoding="utf-8")
                except Exception:
                    pass


# ── Core API ─────────────────────────────────────────────────────────────────

def scan_subagent_logs(since: float = 0.0, root: str | None = None) -> TokenStats:
    """Aggregate subagent tokens from `temp/<task>/stdout.log` files; pass
    `since=tui_start_time` to scope to this run. Best-effort: bad logs skipped."""
    out = TokenStats()
    if since > 0: out.started_at = since
    pattern = os.path.join(root, _SUBAGENT_GLOB) if root else _SUBAGENT_GLOB
    for p in glob.glob(pattern):
        try:
            if since and os.path.getmtime(p) < since: continue
            with open(p, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("[Output]"):
                        m = _OUT_RE.match(line)
                        if m:
                            out.output += int(m.group(1)); out.requests += 1
                    elif line.startswith("[Cache]"):
                        # messages → `input=N creation=C read=R` (input excl. cache);
                        # chat_completions / responses → `input=N cached=R` (input incl. cached).
                        m = _CACHE_RE_NEW.match(line)
                        if m:
                            i, c, r = int(m.group(1)), int(m.group(2)), int(m.group(3))
                            out.input += i
                            out.cache_create += c; out.cache_read += r
                            continue
                        m = _CACHE_RE_OLD.match(line)
                        if m:
                            i, r = int(m.group(1)), int(m.group(2))
                            out.input += max(0, i - r); out.cache_read += r
        except OSError:
            continue
    return out


def get(thread_name: str) -> TokenStats:
    with _lock:
        if thread_name not in _trackers:
            _trackers[thread_name] = TokenStats()
        return _trackers[thread_name]


def reset(thread_name: str) -> None:
    with _lock:
        _trackers.pop(thread_name, None)


def all_trackers() -> dict[str, TokenStats]:
    with _lock:
        return dict(_trackers)


def install() -> None:
    """Idempotently wrap llmcore._record_usage and llmcore.print."""
    global _INSTALLED
    if _INSTALLED: return
    import llmcore
    orig_record, orig_print = llmcore._record_usage, print

    def record_patched(usage, api_mode):
        # Handles INPUT / CACHE only; OUTPUT comes via `[Output]` print_patched
        # below (the SSE path emits it that way; double-counting was the prior bug).
        try:
            if usage:
                t = get(threading.current_thread().name)
                t.requests += 1
                inp = cc = cr = 0
                if api_mode == 'messages':
                    inp = int(usage.get('input_tokens', 0) or 0)
                    cc = int(usage.get('cache_creation_input_tokens', 0) or 0)
                    cr = int(usage.get('cache_read_input_tokens', 0) or 0)
                    t.input += inp; t.cache_create += cc; t.cache_read += cr
                    # Non-stream `messages` skips the [Output] print, so count
                    # output_tokens here; SSE message_start carries a 1-token
                    # placeholder to skip.
                    out = int(usage.get('output_tokens', 0) or 0)
                    if out > 1:
                        t.output += out; t.last_output = out
                        _append_ledger(threading.current_thread().name, inp, out, cc, cr)
                    else:
                        _append_ledger(threading.current_thread().name, inp, 0, cc, cr)
                    t.last_input = inp + cc + cr
                elif api_mode == 'chat_completions':
                    cached = int((usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0)
                    inp = int(usage.get('prompt_tokens', 0) or 0) - cached
                    t.input += inp; t.cache_read += cached
                    t.last_input = inp + cached
                    _append_ledger(threading.current_thread().name, inp, 0, 0, cached)
                elif api_mode == 'responses':
                    cached = int((usage.get('input_tokens_details') or {}).get('cached_tokens', 0) or 0)
                    inp = int(usage.get('input_tokens', 0) or 0) - cached
                    t.input += inp; t.cache_read += cached
                    t.last_input = inp + cached
                    _append_ledger(threading.current_thread().name, inp, 0, 0, cached)
        except Exception: pass
        return orig_record(usage, api_mode)
    llmcore._record_usage = record_patched

    def print_patched(*args, **kwargs):
        try:
            if args and isinstance(args[0], str):
                m = _OUT_RE.match(args[0])
                if m:
                    t = get(threading.current_thread().name)
                    n = int(m.group(1))
                    t.output += n; t.last_output = n
                    _append_ledger(threading.current_thread().name, 0, n, 0, 0)
        except Exception: pass
        return orig_print(*args, **kwargs)
    llmcore.print = print_patched

    _INSTALLED = True
