"""Integration tests for MiniMax provider support.

These tests verify end-to-end MiniMax integration by mocking the HTTP layer
while exercising the full session → stream → parse pipeline.

To run against a real MiniMax API, set MINIMAX_API_KEY in your environment.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_sse_response(chunks, finish_reason="stop"):
    """Build a mock SSE HTTP response from a list of text chunks."""
    lines = []
    for chunk in chunks:
        data = {
            "choices": [{"delta": {"content": chunk}}],
        }
        lines.append(f"data: {json.dumps(data)}".encode())
    # Final chunk with usage
    usage_data = {
        "choices": [{"delta": {}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                  "prompt_tokens_details": {"cached_tokens": 0}},
    }
    lines.append(f"data: {json.dumps(usage_data)}".encode())
    lines.append(b"data: [DONE]")
    return lines


class TestMiniMaxEndToEnd(unittest.TestCase):
    """End-to-end integration test: LLMSession + ToolClient + MiniMax streaming."""

    def test_full_pipeline_with_think_tag(self):
        """Full pipeline: LLMSession → _openai_stream → ToolClient parse with <think> tag."""
        from llmcore import LLMSession, ToolClient

        cfg = {
            'apikey': 'test-integration-key',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
            'context_win': 50000,
        }
        session = LLMSession(cfg)
        client = ToolClient(session)

        sse_lines = _make_sse_response([
            "<think>Let me analyze this task step by step.\n",
            "1. First, I need to understand the request.\n",
            "2. Then, execute the appropriate action.</think>\n\n",
            "<summary>Analyzing user request</summary>\n\n",
            "I'll help you with that task.",
        ])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(sse_lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('llmcore.requests.post', return_value=mock_resp):
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Help me read a file."},
            ]
            gen = client.chat(messages=messages, tools=None)
            chunks = []
            try:
                while True:
                    chunks.append(next(gen))
            except StopIteration as e:
                response = e.value

        self.assertIsNotNone(response)
        self.assertIn("analyze this task", response.thinking)
        self.assertIn("help you with that task", response.content)
        # <think> should be stripped from content
        self.assertNotIn("<think>", response.content)

    def test_full_pipeline_with_tool_call(self):
        """Full pipeline: MiniMax response with tool_use block."""
        from llmcore import LLMSession, ToolClient

        cfg = {
            'apikey': 'test-key',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        }
        session = LLMSession(cfg)
        client = ToolClient(session)

        sse_lines = _make_sse_response([
            "<think>I need to read the config file.</think>\n\n",
            "<summary>Reading config</summary>\n\n",
            '<tool_use>\n{"name": "file_read", "arguments": {"path": "/etc/config.json"}}\n</tool_use>',
        ])

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = iter(sse_lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch('llmcore.requests.post', return_value=mock_resp):
            messages = [{"role": "user", "content": "Read the config file."}]
            gen = client.chat(messages=messages, tools=None)
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                response = e.value

        self.assertEqual(response.thinking, "I need to read the config file.")
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].function.name, "file_read")

    def test_temperature_enforced_in_request(self):
        """Verify the actual HTTP request has clamped temperature for MiniMax."""
        from llmcore import LLMSession

        cfg = {
            'apikey': 'test-key',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        }
        session = LLMSession(cfg)
        captured = {}

        def capture_post(url, headers=None, json=None, stream=None, timeout=None, proxies=None):
            captured['json'] = json
            captured['url'] = url
            resp = MagicMock()
            resp.status_code = 200
            resp.iter_lines.return_value = iter([b'data: [DONE]'])
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with patch('llmcore.requests.post', side_effect=capture_post):
            session.raw_msgs = [{"role": "user", "prompt": "test", "image": None}]
            gen = session.raw_ask(
                [{"role": "user", "content": "test"}],
                model='MiniMax-M2.7',
                temperature=0.0,
            )
            for _ in gen:
                pass

        self.assertAlmostEqual(captured['json']['temperature'], 0.01)
        self.assertIn('api.minimax.io', captured['url'])


@unittest.skipUnless(
    os.environ.get('MINIMAX_API_KEY'),
    'Set MINIMAX_API_KEY to run live integration tests'
)
class TestMiniMaxLive(unittest.TestCase):
    """Live integration tests against MiniMax API (requires MINIMAX_API_KEY)."""

    def test_live_chat_completion(self):
        """Send a real chat completion to MiniMax API."""
        from llmcore import LLMSession

        cfg = {
            'apikey': os.environ['MINIMAX_API_KEY'],
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7-highspeed',
        }
        session = LLMSession(cfg)

        messages = [{"role": "user", "content": "Say 'hello' and nothing else."}]
        gen = session.raw_ask(messages, temperature=0.1)
        text = ''
        for chunk in gen:
            text += chunk

        self.assertFalse(text.startswith('Error:'), f"API returned error: {text}")
        self.assertIn('hello', text.lower())

    def test_live_tool_client_pipeline(self):
        """Full ToolClient pipeline with real MiniMax API."""
        from llmcore import LLMSession, ToolClient

        cfg = {
            'apikey': os.environ['MINIMAX_API_KEY'],
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7-highspeed',
            'context_win': 50000,
        }
        session = LLMSession(cfg)
        client = ToolClient(session)

        messages = [{"role": "user", "content": "What is 2+2? Reply with just the number."}]
        gen = client.chat(messages=messages, tools=None)
        try:
            while True:
                next(gen)
        except StopIteration as e:
            response = e.value

        self.assertIn('4', response.content)

    def test_live_streaming_chunks(self):
        """Verify streaming works with MiniMax API."""
        from llmcore import LLMSession

        cfg = {
            'apikey': os.environ['MINIMAX_API_KEY'],
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7-highspeed',
        }
        session = LLMSession(cfg)

        session.raw_msgs.append({"role": "user", "prompt": "Count from 1 to 5.", "image": None})
        result = session.ask("Count from 1 to 5.", stream=False)
        self.assertFalse(result.startswith('Error:'), f"API returned error: {result}")
        # Should contain at least some numbers
        for n in ['1', '2', '3']:
            self.assertIn(n, result)


if __name__ == '__main__':
    unittest.main()
