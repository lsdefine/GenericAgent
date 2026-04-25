"""Regression tests for OpenAI payload field selection."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOpenAIMaxTokenFields(unittest.TestCase):
    def _capture_payload(self, *, model, api_mode='chat_completions', max_tokens=4096):
        from llmcore import _openai_stream

        captured = {}

        def fake_post(url, headers=None, json=None, stream=None, timeout=None, proxies=None):
            captured['payload'] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.iter_lines.return_value = iter([b'data: [DONE]'])
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch('llmcore.requests.post', side_effect=fake_post):
            gen = _openai_stream(
                'https://api.openai.com/v1',
                'test-key',
                [{"role": "user", "content": "hi"}],
                model,
                api_mode=api_mode,
                max_tokens=max_tokens,
            )
            for _ in gen:
                pass

        return captured['payload']

    def test_gpt5_chat_uses_max_completion_tokens(self):
        payload = self._capture_payload(model='gpt-5.4')
        self.assertEqual(payload['max_completion_tokens'], 4096)
        self.assertNotIn('max_tokens', payload)

    def test_gpt4o_chat_keeps_max_tokens(self):
        payload = self._capture_payload(model='gpt-4o')
        self.assertEqual(payload['max_tokens'], 4096)
        self.assertNotIn('max_completion_tokens', payload)

    def test_responses_uses_max_output_tokens(self):
        payload = self._capture_payload(model='gpt-5.4', api_mode='responses')
        self.assertEqual(payload['max_output_tokens'], 4096)
        self.assertNotIn('max_tokens', payload)
        self.assertNotIn('max_completion_tokens', payload)


if __name__ == '__main__':
    unittest.main()