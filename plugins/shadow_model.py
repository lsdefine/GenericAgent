"""Opt-in shadow inference. Set MODEL to an existing llmcore config name; '' disables it.

Only the main agent executes tools. Each step is saved under OUTPUT_DIR; a daemon
worker calls llmcore in a separate process to isolate stats, logging and history.
Queued work may remain unfinished when GA exits; input.json is retained for replay.
"""
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from plugins.hooks import register

MODEL = ''
OUTPUT_DIR = Path(__file__).resolve().parents[1] / 'temp' / 'shadow_model'
TIMEOUT = 600  # wall-clock seconds per shadow request, including retries
QUEUE_LIMIT = 32

_local = threading.local()
_jobs = None
_start_lock = threading.Lock()


def _save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _response(response, client):
    if response is None:
        raise RuntimeError('Model returned no response')
    return {
        'model': client.backend.model,
        'thinking': response.thinking,
        'content': response.content,
        'tool_calls': [
            {'id': tc.id, 'name': tc.function.name, 'arguments': tc.function.arguments}
            for tc in (response.tool_calls or [])
        ],
        'raw': response.raw,
        'stop_reason': getattr(response, 'stop_reason', None),
    }


def _run_job(directory):
    """Child process only; use the normal client rather than assembling API payloads."""
    from llmcore import resolve_client

    data = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
    client = resolve_client(data['shadow_config'])
    if client is None:
        raise ValueError('Unsupported shadow model configuration')
    client.backend.history = data['history']  # JSON decoding already isolates mutations.
    messages = data['messages']
    if not any(m['role'] == 'system' for m in messages):
        messages = [{'role': 'system', 'content': data['system_prompt']}] + messages
    client.log_path = str(directory / 'llm.log')
    gen = client.chat(messages, tools=data['tools'])
    try:
        while True:
            next(gen)
    except StopIteration as end:
        response = _response(end.value, client)
    failed = str(response['content']).startswith('!!!Error:')
    _save(directory / 'shadow.json', {
        'status': 'error' if failed else 'ok', 'finished_at': time.time(),
        'response': response,
    })


def _worker(jobs):
    while True:
        directory, timeout = jobs.get()
        try:
            with (directory / 'worker.log').open('w', encoding='utf-8') as log:
                subprocess.run(
                    [sys.executable, '-m', 'plugins.shadow_model', '--worker', str(directory)],
                    cwd=Path(__file__).resolve().parents[1],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    timeout=timeout, check=True,
                )
        except Exception as exc:
            try:
                _save(directory / 'shadow.json', {
                    'status': 'error', 'error': f'{type(exc).__name__}: {exc}',
                    'finished_at': time.time(),
                })
            except OSError as write_error:
                print(f'[shadow_model] Cannot save failure: {write_error}', file=sys.stderr)
        finally:
            jobs.task_done()


def _submit(directory):
    global _jobs
    with _start_lock:
        if _jobs is None:
            _jobs = queue.Queue(maxsize=QUEUE_LIMIT)
            threading.Thread(target=_worker, args=(_jobs,), daemon=True,
                             name='shadow-model').start()
    try:
        _jobs.put_nowait((directory, TIMEOUT))
    except queue.Full:
        _save(directory / 'shadow.json', {'status': 'skipped', 'reason': 'queue_full'})


@register('agent_before')
def _begin(ctx):
    _local.run = None
    _local.step = None


@register('llm_before')
def _before(ctx):
    _local.step = None
    model = MODEL
    if not model:
        return
    if getattr(_local, 'run', None) is None:
        _local.run = Path(OUTPUT_DIR).resolve() / uuid.uuid4().hex
    directory = _local.run / f"{ctx['turn']:04d}"
    directory.mkdir(parents=True, exist_ok=False)
    client = ctx['client']
    _save(directory / 'input.json', {
        'created_at': time.time(), 'turn': ctx['turn'],
        'shadow_config': model, 'main_config': client.name,
        'system_prompt': ctx['system_prompt'],
        'history': client.backend.history, 'messages': ctx['messages'],
        'tools': ctx['tools_schema'],
    })
    _local.step = directory
    _submit(directory)


@register('llm_after')
def _after(ctx):
    directory = getattr(_local, 'step', None)
    _local.step = None
    if directory is not None:
        _save(directory / 'main.json', {
            'finished_at': time.time(),
            'response': _response(ctx['response'], ctx['client']),
        })


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--worker':
        raise SystemExit('Usage: python -m plugins.shadow_model --worker STEP_DIRECTORY')
    _run_job(Path(sys.argv[2]).resolve())
