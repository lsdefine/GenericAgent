import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import llmcore as core
from agent_loop import exhaust


TEXT = "!!!Error: ConnectionError: empty response"


def stream(chunks, blocks):
    yield from chunks
    return blocks


class ErrorProvenanceTests(unittest.TestCase):
    def transport(self, parser, response=None):
        response = response or SimpleNamespace(status_code=200)
        response.__enter__ = lambda: response
        sess = SimpleNamespace(name="test", max_retries=0, stream=True,
                               connect_timeout=1, read_timeout=1,
                               proxies=None, verify=True)
        with patch.object(core.requests, "post") as post:
            post.return_value.__enter__.return_value = response
            chunks = []
            gen = core._stream_with_retry(sess, "https://unused", {}, {}, parser)
            try:
                while True:
                    chunks.append(next(gen))
            except StopIteration as exc:
                return chunks, exc.value

    def native(self, chunks, blocks, cls=core.NativeClaudeSession):
        sess = cls.__new__(cls)
        sess.lock = threading.Lock()
        sess.history = []
        sess.omit_thinking = False
        sess.raw_ask = lambda messages: stream(chunks, blocks)
        with patch.object(core, "trim_messages_history"):
            result = exhaust(sess.ask({"role": "user", "content": []}))
        return result, sess.history

    def test_empty_transport_is_typed(self):
        chunks, blocks = self.transport(lambda r: stream([], []))
        self.assertIsInstance(chunks[-1], core.LLMError)
        self.assertEqual(str(chunks[-1]), TEXT)
        self.assertEqual(blocks[-1]["error"], TEXT)

    def test_same_text_native_response_and_history(self):
        for cls in (core.NativeClaudeSession, core.NativeOAISession):
            for failed in (False, True):
                with self.subTest(cls=cls, failed=failed):
                    chunk = core.LLMError(TEXT) if failed else TEXT
                    chunks, blocks = self.transport(lambda r: stream([chunk], [{"type": "text", "text": TEXT}]))
                    response, history = self.native(chunks, blocks, cls)
                    self.assertEqual(response.content, TEXT)
                    self.assertEqual(bool(response.error), failed)
                    self.assertEqual(len(history), 1 if failed else 2)

    def test_same_text_protocol_client_and_history(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                sess = core.BaseSession.__new__(core.BaseSession)
                sess.lock = threading.Lock()
                sess.history = []
                sess.name = sess.model = "test"
                sess.make_messages = lambda messages: messages
                chunk = core.LLMError(TEXT) if failed else TEXT
                sess.raw_ask = lambda messages: stream([chunk], [{"type": "text", "text": TEXT}])
                client = core.ToolClient(sess)
                client._build_protocol_prompt = lambda messages, tools: "test"
                with patch.object(core, "trim_messages_history"):
                    response = exhaust(client.chat([]))
                self.assertEqual(response.content, TEXT)
                self.assertEqual(bool(response.error), failed)
                self.assertEqual(len(sess.history), 1 if failed else 2)

    def test_native_error_does_not_execute_partial_tool(self):
        chunks, blocks = self.transport(lambda r: stream([core.LLMError(TEXT)], [
            {"type": "tool_use", "id": "t", "name": "danger", "input": {}},
            {"type": "text", "text": TEXT}]))
        response, history = self.native(chunks, blocks)
        self.assertTrue(response.error)
        self.assertEqual(response.tool_calls, [])
        self.assertEqual(len(history), 1)

    def test_mixin_only_falls_back_for_typed_errors(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                first = core.LLMError(TEXT) if failed else TEXT
                calls = []
                def raw(index, chunk):
                    calls.append(index)
                    yield chunk
                    return [{"type": "text", "text": str(chunk)}]
                mix = core.MixinSession.__new__(core.MixinSession)
                mix.__dict__.update(_sessions=[
                    SimpleNamespace(name="a", raw_ask=lambda m: raw(0, first)),
                    SimpleNamespace(name="b", raw_ask=lambda m: raw(1, "OK"))],
                    _retries=1, _base_delay=0, _native=True, _cur_idx=0, _switched_at=0)
                mix._pick = lambda: 0
                mix._prepare = lambda idx, messages: messages
                with patch.object(core.time, "sleep"):
                    chunks = list(mix.raw_ask([]))
                self.assertEqual(calls, [0, 1] if failed else [0])
                self.assertEqual(chunks, ["OK"] if failed else [TEXT])

    def test_provider_error_events_are_typed(self):
        cases = [
            lambda: core._parse_claude_sse([b'data: {"type":"error","error":{"message":"bad request"}}']),
            lambda: core._parse_claude_sse([]),
            lambda: core._parse_openai_sse([b'data: {"type":"error","error":{"message":"bad request"}}'], "responses"),
            lambda: core._parse_openai_json({"status": "failed", "error": {"message": "bad request"}}, "responses"),
        ]
        for parser in cases:
            with self.subTest(parser=parser):
                chunks, blocks = self.transport(lambda r: parser())
                self.assertTrue(any(isinstance(c, core.LLMError) for c in chunks))
                self.assertTrue(any(b.get("error") for b in blocks))


if __name__ == "__main__":
    unittest.main()
