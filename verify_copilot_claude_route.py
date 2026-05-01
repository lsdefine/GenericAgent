import json
import queue
import threading
from urllib.error import URLError
from urllib.request import urlopen

from agentmain_auto import build_agent


EXPECTED_ALIAS = 'copilot-claude'
EXPECTED_MODEL = 'claude-sonnet-4.6'
EXPECTED_REPLY = 'SELFTEST_OK'
MODEL_URL = 'http://127.0.0.1:8000/v1/models'


def fetch_models():
    try:
        with urlopen(MODEL_URL, timeout=10) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except URLError as exc:
        raise RuntimeError(f'LiteLLM is not reachable at {MODEL_URL}: {exc}') from exc
    data = payload.get('data') or []
    return [item.get('id') for item in data if item.get('id')]


def run_long_context_selftest():
    available_models = fetch_models()
    if EXPECTED_MODEL not in available_models:
        raise RuntimeError(
            f'Expected model {EXPECTED_MODEL} is missing from LiteLLM /v1/models: {available_models}'
        )

    agent = build_agent()
    agent.verbose = False
    worker = threading.Thread(target=agent.base_agent.run, daemon=True)
    worker.start()

    query = '请阅读下面这段长文本并仅回复 SELFTEST_OK。' + (' 长上下文验证片段' * 120)
    display_queue = agent.put_task(query, source='selftest')

    done_text = ''
    while True:
        item = display_queue.get(timeout=180)
        if 'done' in item:
            done_text = (item.get('done') or '').strip()
            break

    status = agent.route_status()
    last_route = status.get('last_route') or {}
    reply_ok = EXPECTED_REPLY in done_text
    alias_ok = last_route.get('selected_name') == EXPECTED_ALIAS
    reason_ok = last_route.get('reason') == 'long_context'
    backend_model = getattr(agent.base_agent.llmclient.backend, 'model', None)
    model_ok = backend_model == EXPECTED_MODEL

    result = {
        'reply': done_text,
        'reply_ok': reply_ok,
        'route_selected_name': last_route.get('selected_name'),
        'route_reason': last_route.get('reason'),
        'executed_model': last_route.get('executed_model'),
        'current_model': status.get('current_model'),
        'executed_backend_model': backend_model,
        'available_models': available_models,
        'checks': {
            'reply_ok': reply_ok,
            'alias_ok': alias_ok,
            'reason_ok': reason_ok,
            'model_ok': model_ok,
        },
    }

    if not all(result['checks'].values()):
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))

    return result


def main():
    result = run_long_context_selftest()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()