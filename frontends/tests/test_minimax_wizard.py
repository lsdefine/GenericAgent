"""Exercise MiniMax setup through generated configuration and serialized HTTP requests."""
import importlib.util
import io
import json
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wizard = load_module('minimax_wizard', ROOT / 'assets/configure_mykey.py')
llmcore = load_module('minimax_llmcore', ROOT / 'llmcore.py')
PROVIDER = next(p for p in wizard.LLM_PROVIDERS if p['id'] == 'minimax')
MODELS = ['MiniMax-M3.1-Flash', 'MiniMax-M3']


@pytest.mark.parametrize('protocol', ['native_claude', 'native_oai'])
@pytest.mark.parametrize('discovered', [MODELS + ['MiniMax-M2.7'], ['MiniMax-M2.5'], []])
def test_wizard_generated_protocol_and_catalog(monkeypatch, protocol, discovered):
    seen = []

    class Opener:
        def open(self, request, timeout):
            expected = '/anthropic/v1/models' if protocol == 'native_claude' else '/v1/models'
            assert request.full_url.endswith(expected)
            return io.BytesIO(json.dumps({'data': [{'id': m} for m in discovered]}).encode())

    monkeypatch.setattr(wizard.urllib.request, 'build_opener', lambda *a: Opener())
    monkeypatch.setattr(wizard, '_get_proxy_handler', lambda: None)
    monkeypatch.setattr(wizard, 'ask_input', lambda prompt, default=None, **kw: default or 'fixture')
    monkeypatch.setattr(wizard, 'ask_yesno', lambda *a, **kw: False)

    def choose(prompt, choices, **kw):
        ids = [c['id'] for c in choices]
        if 'native_claude' in ids: return protocol
        seen.append([m for m in ids if not m.startswith('__')])
        return 'MiniMax-M3.1-Flash'

    monkeypatch.setattr(wizard, 'ask_choice', choose)
    cfg = wizard.configure_llm(PROVIDER)
    generated = {}
    exec(wizard.generate_mykey([cfg], []), generated)
    session = llmcore.resolve_session(protocol + '_config', generated[protocol + '_config'])
    assert seen == [MODELS]
    assert session.model == MODELS[0]
    assert type(session).__name__ == ('NativeClaudeSession' if protocol == 'native_claude' else 'NativeOAISession')


def test_manual_legacy_choice(monkeypatch):
    monkeypatch.setattr(wizard, 'ask_choice', lambda *a, **kw: '__manual__')
    monkeypatch.setattr(wizard, 'ask_input', lambda *a, **kw: 'MiniMax-M2.7')
    assert wizard._fallback_model(PROVIDER) == 'MiniMax-M2.7'
    assert PROVIDER['template']['model'] == MODELS[0]


def test_other_provider_discovery_is_unchanged(monkeypatch):
    class Opener:
        def open(self, *a, **kw):
            return io.BytesIO(b'{"data":[{"id":"custom-b"},{"id":"custom-a"}]}')

    monkeypatch.setattr(wizard.urllib.request, 'build_opener', lambda *a: Opener())
    monkeypatch.setattr(wizard, '_get_proxy_handler', lambda: None)
    assert wizard.probe_models({'id': 'custom', 'template': {'apibase': 'https://example.test'}}, 'fixture') == ['custom-a', 'custom-b']


@pytest.mark.parametrize('protocol', ['native_claude', 'native_oai'])
@pytest.mark.parametrize('region', ['api.minimaxi.com', 'api.minimax.cn', 'api.minimax.io'])
@pytest.mark.parametrize('model', MODELS + ['MiniMax-M2.7', 'custom-model'])
@pytest.mark.parametrize('effort', [None, 'low', 'medium', 'high', 'xhigh', 'max'])
@pytest.mark.parametrize('stream', [False, True])
def test_serialized_requests_preserve_configuration(monkeypatch, protocol, region, model, effort, stream):
    sent = []

    def send(self, request, **kwargs):
        sent.append((request.url, json.loads(request.body)))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({'content': [{'type': 'text', 'text': 'ok'}],
                                       'choices': [{'message': {'content': 'ok'}}]}).encode()
        if stream:
            events = ([{'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}},
                       {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'ok'}},
                       {'type': 'content_block_stop', 'index': 0}, {'type': 'message_stop'}]
                      if protocol == 'native_claude' else [{'choices': [{'delta': {'content': 'ok'}}]}])
            response._content = ''.join('data: ' + json.dumps(e) + '\n\n' for e in events).encode()
            response._content_consumed = True
        return response

    monkeypatch.setattr(requests.sessions.Session, 'send', send)
    base = '/anthropic' if protocol == 'native_claude' else '/v1'
    cfg = dict(PROVIDER['template'], apikey='fixture', model=model, stream=stream,
               apibase='https://' + region + base, reasoning_effort=effort)
    if effort: cfg['thinking_type'] = 'adaptive'
    generated = {}
    exec(wizard.generate_mykey([dict(cfg, type=protocol)], []), generated)
    session = llmcore.resolve_session(protocol + '_config', generated[protocol + '_config'])
    image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'eA=='}}
    messages = [
        {'role': 'user', 'content': [image, {'type': 'text', 'text': 'inspect'}]},
        {'role': 'assistant', 'content': [{'type': 'thinking', 'thinking': 'reasoning'},
                                        {'type': 'tool_use', 'id': 'call1', 'name': 'inspect', 'input': {}}]},
        {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call1', 'content': 'result'}]},
    ]
    session.tools = [{'type': 'function', 'function': {'name': 'inspect', 'parameters': {'type': 'object'}}}]
    assert ''.join(session.raw_ask(messages)) == 'ok'
    url, payload = sent.pop()
    assert payload['model'] == model
    assert 'service_tier' not in payload and 'reasoning_split' not in payload
    assert payload['tools']
    if protocol == 'native_claude':
        assert url == cfg['apibase'] + '/v1/messages?beta=true'
        for message in payload['messages']:
            for block in message['content']: block.pop('cache_control', None)
        assert payload['messages'] == messages
        assert payload.get('thinking') == ({'type': 'adaptive'} if effort else None)
        expected = 'max' if effort == 'xhigh' and model != MODELS[0] else effort
        assert payload.get('output_config') == ({'effort': expected} if effort else None)
    else:
        assert url == cfg['apibase'] + '/chat/completions'
        assert payload.get('reasoning_effort') == effort
        assert payload['messages'][0]['content'][0]['image_url']['url'] == 'data:image/png;base64,eA=='
        assert payload['messages'][1]['reasoning_content'] == 'reasoning'
        assert payload['messages'][1]['tool_calls'][0]['id'] == 'call1'
        assert payload['messages'][2] == {'role': 'tool', 'tool_call_id': 'call1', 'content': 'result'}
