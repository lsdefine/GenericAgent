"""Offline: real llmcore message assembly, mocked transport, no secrets/API calls."""
import copy
import json
import queue
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from plugins import shadow_model as shadow
from plugins.hooks import trigger
import llmcore


class ShadowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, value in [('MODEL', 'test_native'), ('OUTPUT_DIR', self.root), ('_jobs', None)]:
            p = patch.object(shadow, name, value)
            p.start()
            self.addCleanup(p.stop)
        shadow._begin({})
        self.cfg = {'apikey': 'offline', 'apibase': 'http://unused.invalid', 'model': 'mock'}
        self.client = llmcore.resolve_client('test_native', self.cfg)
        self.client.backend.history = [{'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'main-id', 'name': 'probe', 'input': {}}]}]
        self.ctx = {'client': self.client, 'turn': 1, 'system_prompt': 'Test system',
                    'messages': [{'role': 'user', 'content': 'Next', 'tool_results': [
                        {'tool_use_id': 'main-id', 'content': 'Observed state'}]}], 'tools_schema': []}

    def capture(self):
        with patch.object(shadow, '_submit') as submit:
            shadow._before(self.ctx)
        return submit.call_args.args[0]

    def test_disabled(self):
        shadow.MODEL = ''
        with patch.object(shadow, '_save') as save, patch.object(shadow, '_submit') as submit:
            shadow._before({})
            shadow._after({})
        save.assert_not_called()
        submit.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_real_chat_snapshot_pairing(self):
        before = copy.deepcopy(self.client.backend.history)
        directory = self.capture()
        seen = []
        def raw(backend, messages):
            seen.append(copy.deepcopy(messages))
            self.assertIn('Test system', backend.system)
            messages[0]['content'][0]['input']['shadow_only'] = True
            yield 'stream'
            return [{'type': 'thinking', 'thinking': 'student reasoning'},
                    {'type': 'tool_use', 'id': 'shadow-id', 'name': 'never_execute', 'input': {}}]
        resolve = llmcore.resolve_client
        with patch.object(llmcore, 'resolve_client', side_effect=lambda n: resolve(n, self.cfg)), \
             patch.object(llmcore.NativeOAISession, 'raw_ask', raw), \
             patch.object(llmcore.mykeys_store, '_load', side_effect=AssertionError('No keys')):
            shadow._run_job(directory)
        result = json.loads((directory / 'shadow.json').read_text())
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['response']['thinking'], 'student reasoning')
        self.assertEqual(result['response']['tool_calls'][0]['name'], 'never_execute')
        self.assertEqual(seen[0][-1]['content'][0]['tool_use_id'], 'main-id')
        self.assertEqual(self.client.backend.history, before)
        self.client.backend.history.append({'role': 'assistant', 'content': 'later'})
        self.assertEqual(json.loads((directory / 'input.json').read_text())['history'], before)
        self.ctx['response'] = llmcore.MockResponse('', 'main answer', [], 'raw')
        shadow.MODEL = ''
        shadow._after(self.ctx)
        self.assertEqual(json.loads((directory / 'main.json').read_text())['response']['content'], 'main answer')

    def test_run_ids(self):
        first = self.capture()
        shadow._begin({})
        self.assertNotEqual(self.capture(), first)

    def test_queue_full(self):
        shadow._jobs = queue.Queue(maxsize=1)
        shadow._jobs.put('occupied')
        directory = self.capture()
        shadow._submit(directory)
        self.assertEqual(json.loads((directory / 'shadow.json').read_text())['status'], 'skipped')

    def test_worker_errors(self):
        for error in [subprocess.CalledProcessError(1, 'test'), subprocess.TimeoutExpired('test', 1)]:
            jobs = SimpleNamespace(get=Mock(side_effect=[(self.root, 1), SystemExit]), task_done=Mock())
            with patch.object(subprocess, 'run', side_effect=error), self.assertRaises(SystemExit):
                shadow._worker(jobs)
            result = json.loads((self.root / 'shadow.json').read_text())
            self.assertEqual(result['status'], 'error')
            self.assertIn(type(error).__name__, result['error'])
            jobs.task_done.assert_called_once()

    def test_hook_failure_contained(self):
        with patch.object(shadow, '_save', side_effect=OSError('disk full')):
            trigger('llm_before', self.ctx)
        self.assertIsNone(shadow._local.step)


if __name__ == '__main__':
    unittest.main()
