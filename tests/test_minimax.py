"""Unit tests for MiniMax provider support in llmcore.py."""
import json
import re
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMiniMaxTemperatureClamping(unittest.TestCase):
    """Test MiniMax temperature clamping in _openai_stream."""

    def _make_stream_call(self, model, temperature):
        """Capture the payload sent by _openai_stream."""
        from llmcore import _openai_stream

        captured = {}

        def fake_post(url, headers=None, json=None, stream=None, timeout=None, proxies=None):
            captured['payload'] = json
            captured['url'] = url
            resp = MagicMock()
            resp.status_code = 200
            resp.iter_lines.return_value = iter([b'data: [DONE]'])
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch('llmcore.requests.post', side_effect=fake_post):
            gen = _openai_stream(
                'https://api.minimax.io/v1', 'test-key', [{"role": "user", "content": "hi"}],
                model, temperature=temperature
            )
            # Drain the generator
            for _ in gen:
                pass

        return captured.get('payload', {})

    def test_minimax_temp_zero_clamped(self):
        """MiniMax rejects temperature=0, should be clamped to 0.01."""
        payload = self._make_stream_call('MiniMax-M2.7', 0.0)
        self.assertAlmostEqual(payload['temperature'], 0.01)

    def test_minimax_temp_negative_clamped(self):
        """Negative temperature should be clamped to 0.01."""
        payload = self._make_stream_call('MiniMax-M2.5', -0.5)
        self.assertAlmostEqual(payload['temperature'], 0.01)

    def test_minimax_temp_normal_preserved(self):
        """Normal temperature (0 < t <= 1) should be preserved."""
        payload = self._make_stream_call('MiniMax-M2.7', 0.5)
        self.assertAlmostEqual(payload['temperature'], 0.5)

    def test_minimax_temp_one_preserved(self):
        """Temperature=1.0 should be preserved."""
        payload = self._make_stream_call('MiniMax-M2.7-highspeed', 1.0)
        self.assertAlmostEqual(payload['temperature'], 1.0)

    def test_minimax_temp_above_one_clamped(self):
        """Temperature > 1.0 should be clamped to 1.0."""
        payload = self._make_stream_call('MiniMax-M2.7', 1.5)
        self.assertAlmostEqual(payload['temperature'], 1.0)

    def test_minimax_case_insensitive(self):
        """Model name matching should be case-insensitive."""
        payload = self._make_stream_call('minimax-m2.7', 0.0)
        self.assertAlmostEqual(payload['temperature'], 0.01)

    def test_non_minimax_temp_zero_unchanged(self):
        """Non-MiniMax models should not have temperature clamped."""
        payload = self._make_stream_call('gpt-4o', 0.0)
        self.assertAlmostEqual(payload['temperature'], 0.0)

    def test_kimi_temp_still_forced(self):
        """Kimi/Moonshot temp override should still work."""
        payload = self._make_stream_call('kimi-2.0', 0.5)
        self.assertAlmostEqual(payload['temperature'], 1.0)


class TestMiniMaxThinkTagHandling(unittest.TestCase):
    """Test <think>...</think> tag stripping for MiniMax M2.7 responses."""

    def test_think_tag_stripped_from_response(self):
        """<think> tags (used by MiniMax M2.7) should be stripped from content."""
        from llmcore import ToolClient, LLMSession

        mock_cfg = {
            'apikey': 'test', 'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        }
        with patch('llmcore._load_mykeys', return_value={}):
            session = LLMSession(mock_cfg)

        client = ToolClient(session)
        text = '<think>Let me reason about this task.</think>\n\nHere is the answer.'
        result = client._parse_mixed_response(text)
        self.assertEqual(result.thinking, 'Let me reason about this task.')
        self.assertEqual(result.content, 'Here is the answer.')

    def test_thinking_tag_still_works(self):
        """<thinking> tags (used by Claude) should still work."""
        from llmcore import ToolClient, LLMSession

        mock_cfg = {
            'apikey': 'test', 'apibase': 'https://api.anthropic.com',
            'model': 'claude-sonnet-4-20250514',
        }
        with patch('llmcore._load_mykeys', return_value={}):
            session = LLMSession(mock_cfg)

        client = ToolClient(session)
        text = '<thinking>Let me analyze this.</thinking>\n\nThe result is 42.'
        result = client._parse_mixed_response(text)
        self.assertEqual(result.thinking, 'Let me analyze this.')
        self.assertEqual(result.content, 'The result is 42.')

    def test_think_tag_with_tool_use(self):
        """<think> tags should be separated from tool_use blocks."""
        from llmcore import ToolClient, LLMSession

        mock_cfg = {
            'apikey': 'test', 'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        }
        with patch('llmcore._load_mykeys', return_value={}):
            session = LLMSession(mock_cfg)

        client = ToolClient(session)
        text = '<think>I need to read the file first.</think>\n\n<summary>Reading config</summary>\n\n<tool_use>\n{"name": "file_read", "arguments": {"path": "/tmp/test.txt"}}\n</tool_use>'
        result = client._parse_mixed_response(text)
        self.assertEqual(result.thinking, 'I need to read the file first.')
        self.assertTrue(len(result.tool_calls) > 0)
        self.assertEqual(result.tool_calls[0].function.name, 'file_read')


class TestMiniMaxCompressHistoryTags(unittest.TestCase):
    """Test that <think> tags are compressed in history like <thinking> tags."""

    def test_think_tag_compressed_in_old_messages(self):
        """<think> tags in old messages should be truncated."""
        from llmcore import compress_history_tags

        long_think = "A" * 2000
        messages = [
            {"role": "assistant", "prompt": f"<think>{long_think}</think>\nShort answer."},
            {"role": "user", "prompt": "Follow up"},
        ] + [{"role": "user", "prompt": f"msg{i}"} for i in range(12)]

        # Force compression (counter divisible by 5)
        compress_history_tags._cd = 4
        result = compress_history_tags(messages, keep_recent=10, max_len=800)
        # The first message's <think> content should be truncated
        first_content = result[0]["prompt"]
        self.assertIn("<think>", first_content)
        self.assertIn("...", first_content)
        self.assertLess(len(first_content), len(f"<think>{long_think}</think>\nShort answer."))


class TestMiniMaxAutoMakeUrl(unittest.TestCase):
    """Test URL construction for MiniMax API base."""

    def test_minimax_base_url(self):
        from llmcore import auto_make_url
        url = auto_make_url('https://api.minimax.io/v1', 'chat/completions')
        self.assertEqual(url, 'https://api.minimax.io/v1/chat/completions')

    def test_minimax_base_url_no_version(self):
        from llmcore import auto_make_url
        url = auto_make_url('https://api.minimax.io', 'chat/completions')
        self.assertEqual(url, 'https://api.minimax.io/v1/chat/completions')

    def test_minimax_full_url_preserved(self):
        from llmcore import auto_make_url
        url = auto_make_url('https://api.minimax.io/v1/chat/completions$', 'chat/completions')
        self.assertEqual(url, 'https://api.minimax.io/v1/chat/completions')


class TestMiniMaxNativeOAISessionThinkTag(unittest.TestCase):
    """Test <think> tag handling in NativeOAISession."""

    def test_think_tag_extracted_in_native_oai(self):
        """NativeOAISession.ask should extract <think> tags from MiniMax M2.7 responses."""
        from llmcore import NativeOAISession

        cfg = {
            'apikey': 'test-key',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        }
        session = NativeOAISession(cfg)

        # Mock the raw_ask to return content with <think> tag via generator
        def mock_raw_ask(messages, tools=None, system=None, model=None, temperature=0.5, max_tokens=6144, **kw):
            content_text = "<think>Planning the approach.</think>\n\nHere is the result."
            yield content_text
            return [{"type": "text", "text": content_text}]

        session.raw_ask = mock_raw_ask

        msg = {"role": "user", "content": [{"type": "text", "text": "test"}]}
        gen = session.ask(msg)
        # Drain generator
        try:
            while True:
                next(gen)
        except StopIteration as e:
            resp = e.value

        self.assertEqual(resp.thinking, 'Planning the approach.')
        self.assertNotIn('<think>', resp.content)
        self.assertIn('Here is the result.', resp.content)


class TestMiniMaxLLMSessionConfig(unittest.TestCase):
    """Test LLMSession configuration with MiniMax settings."""

    def test_llm_session_init_with_minimax(self):
        """LLMSession should initialize correctly with MiniMax config."""
        from llmcore import LLMSession

        cfg = {
            'apikey': 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
            'context_win': 50000,
            'max_retries': 2,
            'connect_timeout': 10,
            'read_timeout': 120,
        }
        session = LLMSession(cfg)
        self.assertEqual(session.model, 'MiniMax-M2.7')
        self.assertEqual(session.api_base, 'https://api.minimax.io/v1')
        self.assertEqual(session.context_win, 50000)
        self.assertEqual(session.max_retries, 2)

    def test_llm_session_minimax_highspeed(self):
        """LLMSession should work with MiniMax-M2.7-highspeed model."""
        from llmcore import LLMSession

        cfg = {
            'apikey': 'test-key',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7-highspeed',
        }
        session = LLMSession(cfg)
        self.assertEqual(session.model, 'MiniMax-M2.7-highspeed')


class TestMiniMaxNativeToolClientThinkTag(unittest.TestCase):
    """Test <think> tag handling in NativeToolClient.chat."""

    def test_native_tool_client_think_tag(self):
        """NativeToolClient should extract <think> tags from MiniMax responses."""
        from llmcore import NativeToolClient, NativeOAISession, MockResponse

        cfg = {
            'apikey': 'test-key',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        }
        session = NativeOAISession(cfg)
        client = NativeToolClient(session)

        # Mock the backend.ask to yield chunks and return a MockResponse with think tags
        def mock_ask(msg, tools=None, model=None):
            text = "<think>Analyzing the request.</think>\n\nResult: success"
            yield text
            return MockResponse('', text, [], text)

        session.ask = mock_ask

        messages = [{"role": "user", "content": "test query"}]
        gen = client.chat(messages)
        resp = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            resp = e.value

        self.assertIsNotNone(resp)
        self.assertEqual(resp.thinking, 'Analyzing the request.')
        self.assertEqual(resp.content, 'Result: success')


if __name__ == '__main__':
    unittest.main()
