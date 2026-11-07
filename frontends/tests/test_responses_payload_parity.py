# -*- coding: utf-8 -*-
"""Regression: responses-mode payload parity (upstream issue #813, A-4/A-5).

Two silent-config bugs in the OpenAI Responses branch of llmcore:

1. `temperature` — the chat_completions branch sends the user-configured value
   (`if temperature != 1`, same pattern as ClaudeSession.raw_ask), the
   responses branch never did: temperature in mykey.py silently no-op'd for
   every responses endpoint. Official Responses API supports the field
   (default 1.0), so the chat-branch guard is reused verbatim.
2. `reasoning_effort` — BaseSession._enum's whitelist lacked 'ultra'
   (GPT-5.6 tier), so the value was dropped with a single WARN line and the
   payload silently fell back to the endpoint default.

Verification: monkeypatch llmcore.requests.post to capture the real payload
and return a canned SSE stream; drive real NativeOAISession.raw_ask. No
network, no credentials.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent

# test_bridge_sessions.py setdefault()s an empty llmcore stub into sys.modules;
# under full-suite collection it can shadow the real module before us.
_stub = sys.modules.get("llmcore")
if _stub is not None and not hasattr(_stub, "NativeOAISession"):
    del sys.modules["llmcore"]
sys.path.insert(0, str(ROOT))

import llmcore  # noqa: E402


_SSE_LINES = [
    'data: {"type":"response.output_text.delta","delta":"hi"}',
    'data: {"type":"response.completed","response":{"usage":{"input_tokens":1,"output_tokens":1}}}',
    'data: [DONE]', '',
]

_CHAT_SSE_LINES = [
    'data: {"choices":[{"delta":{"content":"hi"}}]}',
    'data: {"choices":[{"delta":{},"usage":{"prompt_tokens":1,"completion_tokens":1}}]}',
    'data: [DONE]', '',
]


class FakeResponse:
    """Upstream calls requests.post as a context manager (TTFT/abort support,
    added after GiftedScout's fork point), so the fake supports the protocol
    too — a plain object would AttributeError on __enter__."""
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        for line in self._lines:
            yield line

    def json(self):
        return {}


def _cfg(**over):
    cfg = {
        'apikey': 'sk-test', 'apibase': 'https://api.example.com/v1',
        'model': 'test-model', 'api_mode': 'responses',
        'system': 'S', 'stream': True, 'max_retries': 0,
    }
    cfg.update(over)
    return cfg


@pytest.fixture
def capture(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, stream=False, timeout=None, **kw):
        seen['url'] = url
        seen['payload'] = json
        seen['kw'] = kw
        lines = _CHAT_SSE_LINES if 'chat/completions' in url else _SSE_LINES
        return FakeResponse(lines)

    monkeypatch.setattr(llmcore.requests, 'post', fake_post)
    return seen


def _ask_payload(capture, **cfgover):
    sess = llmcore.NativeOAISession(_cfg(**cfgover))
    list(sess.raw_ask([{'role': 'user', 'content': 'x'}]))
    return capture, sess


# --- temperature ------------------------------------------------------------

def test_responses_payload_includes_configured_temperature(capture):
    seen, _ = _ask_payload(capture, temperature=0.5)
    assert seen['payload']['temperature'] == 0.5


def test_responses_temperature_default_still_omitted(capture):
    seen, _ = _ask_payload(capture, temperature=1)
    assert 'temperature' not in seen['payload']


def test_responses_temperature_respects_model_override(capture):
    # kimi/moonshot force temperature to 1 before either branch builds a payload
    seen, _ = _ask_payload(capture, model='kimi-k2', temperature=0.5)
    assert 'temperature' not in seen['payload']


# --- reasoning_effort -------------------------------------------------------

def test_reasoning_effort_ultra_survives_enum_and_payload(capture):
    seen, sess = _ask_payload(capture, reasoning_effort='ultra')
    assert sess.reasoning_effort == 'ultra'
    assert seen['payload']['reasoning'] == {'effort': 'ultra'}


def test_reasoning_effort_high_unchanged(capture):
    seen, sess = _ask_payload(capture, reasoning_effort='high')
    assert sess.reasoning_effort == 'high'
    assert seen['payload']['reasoning'] == {'effort': 'high'}


def test_reasoning_effort_invalid_still_dropped(capture):
    seen, sess = _ask_payload(capture, reasoning_effort='bogus')
    assert sess.reasoning_effort is None
    assert 'reasoning' not in seen['payload']


# --- chat_completions branch regression -------------------------------------

def test_chat_branch_temperature_and_effort_shape(capture):
    seen, _ = _ask_payload(capture, api_mode='chat_completions', temperature=0.3,
                           reasoning_effort='ultra', max_tokens=2048)
    p = seen['payload']
    assert p['temperature'] == 0.3
    assert p['reasoning_effort'] == 'ultra'  # flat key, not the responses shape
    assert 'reasoning' not in p
    assert p['max_tokens'] == 2048
    assert 'chat/completions' in seen['url']
