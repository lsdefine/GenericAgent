"""Set MODEL to an existing config name to enable shadow inference; no tools execute."""
from copy import deepcopy
from pathlib import Path
from threading import Thread
from uuid import uuid4
from plugins.hooks import register

MODEL = ''


@register('llm_before')
def shadow(ctx):
    if not MODEL:
        return
    from agent_loop import exhaust
    from llmcore import resolve_client, _write_llm_log

    client = resolve_client(MODEL)
    client.backend.history = deepcopy(ctx['client'].backend.history)
    messages = [{'role': 'system', 'content': ctx['system_prompt']}] + deepcopy(ctx['messages'])
    client.log_path = str(Path(__file__).resolve().parents[1] / 'temp' / 'shadow_model' / f'{uuid4().hex}.log')
    _write_llm_log('Shadow', f"turn={ctx['turn']} model={MODEL} log={client.log_path}", ctx['client'].log_path)
    gen = client.chat(messages, tools=deepcopy(ctx['tools_schema']))
    Thread(target=exhaust, args=(gen,), daemon=True, name='shadow-model').start()
