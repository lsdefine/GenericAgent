"""Offline regression: actual chat/ask, no API or real configuration access."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import llmcore
from plugins import shadow_model as plugin


class ShadowTests(unittest.TestCase):
    def test_disabled(self):
        with patch.object(plugin, 'MODEL', ''), patch.object(plugin, 'Thread') as thread:
            plugin.shadow({})
        thread.assert_not_called()

    def test_snapshot_and_log(self):
        cfg = {'apikey': 'offline', 'apibase': 'http://unused.invalid', 'model': 'mock'}
        resolve = llmcore.resolve_client
        main = resolve('test_native', cfg)
        main.backend.history = [{'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'main-id', 'name': 'probe', 'input': {}}]}]
        before = copy.deepcopy(main.backend.history)
        messages = [{'role': 'user', 'content': 'next', 'tool_results': [
            {'tool_use_id': 'main-id', 'content': 'observed'}]}]
        seen = []
        def raw(backend, request):
            seen.append(copy.deepcopy(request))
            self.assertIn('system', backend.system)
            request[0]['content'][0]['input']['mutated'] = True
            yield 'chunk'
            return [{'type': 'thinking', 'thinking': 'reasoning'},
                    {'type': 'tool_use', 'id': 'shadow-id', 'name': 'never_execute', 'input': {}}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main.log_path = str(root / 'main.log')
            ctx = dict(client=main, messages=messages, tools_schema=[], system_prompt='system', turn=2)
            with patch.object(plugin, 'MODEL', 'test_native'), \
                 patch.object(plugin, '__file__', str(root / 'plugins' / 'shadow_model.py')), \
                 patch.object(plugin, 'Thread') as thread, \
                 patch.object(llmcore, 'resolve_client', side_effect=lambda name: resolve(name, cfg)), \
                 patch.object(llmcore.NativeOAISession, 'raw_ask', raw), \
                 patch.object(llmcore.mykeys_store, '_load', side_effect=AssertionError('No keys')):
                plugin.shadow(ctx)
                thread.return_value.start.assert_called_once()
                main.backend.history.append({'role': 'assistant', 'content': 'later'})
                response = thread.call_args.kwargs['target'](*thread.call_args.kwargs['args'])
            self.assertEqual(main.backend.history[:-1], before)
            self.assertEqual(len(seen[0]), 2)
            self.assertEqual(seen[0][-1]['content'][0]['tool_use_id'], 'main-id')
            self.assertEqual(response.thinking, 'reasoning')
            log = next((root / 'temp' / 'shadow_model').glob('*.log'))
            self.assertIn('never_execute', log.read_text())
            self.assertIn(str(log), Path(main.log_path).read_text())


if __name__ == '__main__':
    unittest.main()
