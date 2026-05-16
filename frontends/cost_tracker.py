"""Per-thread LLM token usage, captured via llmcore monkey-patches.

`install()` wraps `llmcore._record_usage` (covers all three API modes) and
`llmcore.print` (the `messages` SSE path emits the final `output_tokens`
only via `[Output] tokens=N`, never through `_record_usage`). Tracking is
keyed by `threading.current_thread().name`; each TUI session runs the
agent on a uniquely named thread (`ga-tui-agent-<id>`), so `/cost` is a
thread lookup.
"""
import re, threading, time
from dataclasses import dataclass, field


@dataclass
class TokenStats:
    requests: int = 0
    input: int = 0
    output: int = 0
    cache_create: int = 0
    cache_read: int = 0
    # Latest request's effective prompt size — used for the % context-left line.
    last_input: int = 0
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


# Best-effort model → context window. `startswith` match; None hides the line.
_CTX_LIMITS: list[tuple[str, int]] = [
    ("claude-sonnet-4-5", 1_000_000),
    ("claude-opus-4",       200_000),
    ("claude-haiku-4",      200_000),
    ("claude-sonnet-4",     200_000),
    ("claude-3-5-sonnet",   200_000),
    ("claude-3-5-haiku",    200_000),
    ("claude-3-7-sonnet",   200_000),
    ("claude-3-opus",       200_000),
    ("claude-3-haiku",      200_000),
    ("claude-3-sonnet",     200_000),
    ("gpt-5-pro",           400_000),
    ("gpt-5",               256_000),
    ("gpt-4o",              128_000),
    ("gpt-4-turbo",         128_000),
    ("gpt-4",                 8_192),
    ("o1",                  200_000),
    ("o3",                  200_000),
    ("o4",                  200_000),
    ("gemini-2.5",        2_000_000),
    ("gemini-2",          1_000_000),
    ("gemini-1.5",        1_000_000),
    ("glm-5",               256_000),
    ("glm-4",               128_000),
    ("qwen",                128_000),
    ("deepseek",             64_000),
    ("kimi",                200_000),
    ("moonshot",            200_000),
]


def context_limit_for(model: str | None) -> int | None:
    if not model: return None
    m = model.lower()
    for prefix, limit in _CTX_LIMITS:
        if m.startswith(prefix): return limit
    return None


_trackers: dict[str, TokenStats] = {}
_lock = threading.Lock()
_OUT_RE = re.compile(r'\[Output\]\s+tokens=(\d+)')
_INSTALLED = False


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
        try:
            if usage:
                t = get(threading.current_thread().name)
                t.requests += 1
                if api_mode == 'messages':
                    # SSE delivers final output via [Output] print; non-stream
                    # delivers it here. `output_tokens` in stream message_start
                    # is a 0–1 placeholder, acceptable noise.
                    inp = int(usage.get('input_tokens', 0) or 0)
                    cc = int(usage.get('cache_creation_input_tokens', 0) or 0)
                    cr = int(usage.get('cache_read_input_tokens', 0) or 0)
                    t.input += inp; t.cache_create += cc; t.cache_read += cr
                    t.output += int(usage.get('output_tokens', 0) or 0)
                    t.last_input = inp + cc + cr
                elif api_mode == 'chat_completions':
                    cached = int((usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0) or 0)
                    inp = int(usage.get('prompt_tokens', 0) or 0) - cached
                    t.input += inp; t.cache_read += cached
                    t.output += int(usage.get('completion_tokens', 0) or 0)
                    t.last_input = inp + cached
                elif api_mode == 'responses':
                    cached = int((usage.get('input_tokens_details') or {}).get('cached_tokens', 0) or 0)
                    inp = int(usage.get('input_tokens', 0) or 0) - cached
                    t.input += inp; t.cache_read += cached
                    t.output += int(usage.get('output_tokens', 0) or 0)
                    t.last_input = inp + cached
        except Exception: pass
        return orig_record(usage, api_mode)
    llmcore._record_usage = record_patched

    def print_patched(*args, **kwargs):
        try:
            if args and isinstance(args[0], str):
                m = _OUT_RE.match(args[0])
                if m: get(threading.current_thread().name).output += int(m.group(1))
        except Exception: pass
        return orig_print(*args, **kwargs)
    llmcore.print = print_patched

    _INSTALLED = True
