"""Regression tests for issue #753 — OpenAI Responses SSE overload / transient
errors must trigger _stream_with_retry instead of being returned to the caller
as if the request succeeded.

Covers:
  * `_is_retryable_stream_err`: coded / numeric / prose detection on
    dict-shaped and string-shaped payloads.
  * `_raise_if_retryable_overload`: raises ConnectionError for retryable
    payloads, never raises for permanent failures.
  * `_parse_openai_sse(api_mode="responses")` `error` event with
    `{code: "server_error"}` (no "overloaded" word anywhere) routes to retry.
  * `_parse_openai_sse(api_mode="responses")` `response.failed` event with
    `{code: "rate_limit_error"}` routes to retry.
  * Permanent failures (`invalid_request_error`, `context_length_exceeded`)
    do not retry — they remain visible as `!!!Error:` text in the stream.
"""

import os
import sys
import types
import importlib

import pytest


def _import_llmcore():
    """Import llmcore with `requests` and any missing deps stubbed in."""
    sys.modules.pop("llmcore", None)
    # llmcore.py imports requests at module scope — must already be present.
    import llmcore  # noqa: F401
    return sys.modules["llmcore"]


def test_is_retryable_stream_err_codes():
    lc = _import_llmcore()
    is_retry = lc._is_retryable_stream_err
    # OpenAI Responses / Anthropic / upstream-proxy transient codes.
    assert is_retry(err={"code": "rate_limit_error"}) is True
    assert is_retry(err={"type": "rate_limit_error"}) is True
    assert is_retry(err={"code": "server_error"}) is True
    assert is_retry(err={"code": "service_unavailable"}) is True
    assert is_retry(err={"code": "overloaded"}) is True
    assert is_retry(err={"code": "engine_overloaded"}) is True
    assert is_retry(err={"code": "api_error"}) is True
    assert is_retry(err={"code": "upstream_error"}) is True
    assert is_retry(err={"code": "too_many_requests"}) is True
    # Numeric codes slipped into SSE error payload.
    assert is_retry(err={"code": "429"}) is True
    assert is_retry(err={"code": "503"}) is True
    assert is_retry(err={"code": "502"}) is True
    # OpenAI Responses nested-shape error payload.
    assert is_retry(err={"error": {"code": "rate_limit_error"}}) is True
    assert is_retry(err={"error": {"type": "server_error", "message": "down"}}) is True
    # Prose fallback — original behavior preserved for plain message strings.
    assert is_retry(emsg="Our servers are currently overloaded. Please try again later.") is True
    assert is_retry(emsg="concurrency limit hit") is True
    assert is_retry(emsg="rate limit exceeded, please retry") is True
    # New prose patterns the old regex missed.
    assert is_retry(emsg="server is busy, retry") is True
    assert is_retry(emsg="Service temporarily unavailable") is True
    assert is_retry(emsg="engine overloaded, backoff") is True
    assert is_retry(emsg="try again later") is True
    assert is_retry(emsg="reached capacity, try later") is True


def test_is_retryable_stream_err_permanent():
    lc = _import_llmcore()
    is_retry = lc._is_retryable_stream_err
    # Permanent failures — must NOT retry, surface as `!!!Error:` text instead.
    assert is_retry(err={"code": "invalid_request_error"}) is False
    assert is_retry(err={"code": "context_length_exceeded"}) is False
    assert is_retry(err={"code": "authentication_error"}) is False
    assert is_retry(err={"code": "permission_denied"}) is False
    assert is_retry(err={"code": "not_found"}) is False
    assert is_retry(err={"code": "400"}) is False  # 400 is a permanent bad-request
    assert is_retry(err={"code": "404"}) is False
    # Plain text with no signal words.
    assert is_retry(emsg="") is False
    assert is_retry(emsg=None) is False
    assert is_retry(emsg="something went wrong, please check your input") is False


def test_raise_if_retryable_overload_dict():
    lc = _import_llmcore()
    rai = lc._raise_if_retryable_overload
    # Coded transient → raise.
    with pytest.raises(Exception) as ei:
        rai({"code": "server_error", "message": "down"})
    assert "down" in str(ei.value)
    # String transient → raise.
    with pytest.raises(Exception):
        rai("server overloaded")


def test_raise_if_retryable_overload_no_raise_for_permanent():
    lc = _import_llmcore()
    rai = lc._raise_if_retryable_overload
    # Permanent: must return normally (no raise).
    rai({"code": "invalid_request_error", "message": "bad"})
    rai("unrelated message about syntax error")
    rai("")
    rai(None)


def _sse(events):
    """Build an iterable of byte/str lines that mimics `iter_lines()`."""
    out = []
    for e in events:
        if isinstance(e, str):
            out.append(e.encode("utf-8"))
        else:
            out.append(e)
    return out


def test_parse_openai_sse_responses_error_routes_to_retry():
    """`_parse_openai_sse` with `error` event whose `code` is `server_error`
    must raise ConnectionError so `_stream_with_retry` retries.
    """
    lc = _import_llmcore()
    parse = lc._parse_openai_sse
    lines = _sse([
        'data: {"type": "response.output_text.delta", "delta": "hello"}',
        # Coded transient — should NOT appear as assistant text, should raise.
        'data: {"type": "error", "error": {"code": "server_error", "message": "Server is down"}}',
    ])
    gen = parse(iter(lines), api_mode="responses")
    # First chunk streams fine.
    first = next(gen)
    assert first == "hello"
    # The next call hits the error event — must raise ConnectionError.
    with pytest.raises(Exception) as ei:
        next(gen)
    assert "Server is down" in str(ei.value)


def test_parse_openai_sse_responses_response_failed_routes_to_retry():
    lc = _import_llmcore()
    parse = lc._parse_openai_sse
    lines = _sse([
        'data: {"type": "response.output_text.delta", "delta": "ok"}',
        # response.failed path with rate_limit_error — must retry.
        'data: {"type": "response.failed", "response": {"error": {"code": "rate_limit_error", "message": "Try again"}, "usage": {}}}',
    ])
    gen = parse(iter(lines), api_mode="responses")
    assert next(gen) == "ok"
    with pytest.raises(Exception) as ei:
        next(gen)
    assert "Try again" in str(ei.value)


def test_parse_openai_sse_responses_permanent_failure_surfaces_as_text():
    lc = _import_llmcore()
    parse = lc._parse_openai_sse
    lines = _sse([
        'data: {"type": "response.output_text.delta", "delta": ""}',  # empty delta to get seen_delta path
        'data: {"type": "response.failed", "response": {"error": {"code": "invalid_request_error", "message": "Bad model ID"}, "usage": {}}}',
    ])
    gen = parse(iter(lines), api_mode="responses")
    # Must yield `!!!Error:` text, not raise.
    chunks = []
    for c in gen:
        chunks.append(c)
    assert any("Bad model ID" in c for c in chunks)


def test_parse_claude_sse_error_routes_to_retry():
    """Claude path's `error` event already used the helper, but verify it now
    also honors the new prose patterns (the original regex didn't catch
    'Server is busy, retry')."""
    lc = _import_llmcore()
    parse = lc._parse_claude_sse
    lines = _sse([
        'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}',
        'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}}',
        'data: {"type": "content_block_stop", "index": 0}',
        'data: {"type": "error", "error": {"message": "Server is busy, retry"}}',
    ])
    gen = parse(iter(lines))
    chunks = []
    try:
        for c in gen:
            chunks.append(c)
    except Exception as e:  # noqa: BLE001
        # A ConnectionError is acceptable — the stream's terminal warn fires
        # only AFTER the helper decides not to retry. For retryable errors it
        # should raise and stop the generator before warn assignment.
        assert "Server is busy" in str(e), f"unexpected: {type(e).__name__}: {e}"
        return
    pytest.fail("Expected retry raise; got chunks: %r" % (chunks,))


def test_no_regression_on_legacy_message_only():
    """Pre-#753 prose path: an error event with no `code`/`type` but text that
    contains 'overloaded' must still retry (regression guard)."""
    lc = _import_llmcore()
    parse = lc._parse_openai_sse
    lines = _sse([
        'data: {"type": "response.output_text.delta", "delta": "x"}',
        'data: {"type": "error", "error": {"message": "Our servers are currently overloaded."}}',
    ])
    gen = parse(iter(lines), api_mode="responses")
    assert next(gen) == "x"
    with pytest.raises(Exception) as ei:
        next(gen)
    assert "overloaded" in str(ei.value).lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-vv"]))
