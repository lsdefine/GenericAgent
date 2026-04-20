from datetime import datetime, timezone


ERROR_KINDS = (
    "auth",
    "quota",
    "rate_limit",
    "timeout",
    "network",
    "server",
    "bad_request",
    "model_not_found",
    "unsupported_param",
    "unknown",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_message(message, limit=2000) -> str:
    text = "" if message is None else str(message).strip()
    return text[:limit]


def classify_error(*, status_code=None, message="", body="", exc_type="") -> str:
    status = None if status_code is None else int(status_code)
    hay = " ".join(x for x in (str(message or ""), str(body or ""), str(exc_type or "")) if x).lower()

    if status in (401, 403):
        return "auth"
    if status == 404 or "model_not_found" in hay or "model not found" in hay or "no such model" in hay:
        return "model_not_found"
    if "unsupported_param" in hay or ("unsupported" in hay and any(k in hay for k in ("param", "reasoning_effort", "reasoning.effort", "api_mode"))):
        return "unsupported_param"
    if status == 400:
        return "unsupported_param" if "unsupported" in hay else "bad_request"
    if status == 429:
        quota_tokens = ("insufficient_quota", "quota", "credit", "billing", "余额", "配额")
        return "quota" if any(token in hay for token in quota_tokens) else "rate_limit"
    if status is not None and status >= 500:
        return "server"
    if any(token in hay for token in ("timeout", "timed out", "readtimeout", "connecttimeout")):
        return "timeout"
    if any(token in hay for token in ("connectionerror", "proxyerror", "sslerror", "name or service not known", "connection reset", "dns", "proxy", "connection refused")):
        return "network"
    return "unknown"
