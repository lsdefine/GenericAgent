import importlib
import json
import os
import sys
import unittest


REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)


class TestDashscopeGlmConfig(unittest.TestCase):
    def setUp(self):
        self._old_value = os.environ.get('DASHSCOPE_API_KEY')
        os.environ['DASHSCOPE_API_KEY'] = 'test-dashscope-key'
        sys.modules.pop('mykey', None)

    def tearDown(self):
        if self._old_value is None:
            os.environ.pop('DASHSCOPE_API_KEY', None)
        else:
            os.environ['DASHSCOPE_API_KEY'] = self._old_value
        sys.modules.pop('mykey', None)

    def test_dashscope_glm_is_primary_mixin_model(self):
        mykey = importlib.import_module('mykey')

        self.assertEqual(mykey.mixin_config['llm_nos'][0], 'dashscope-glm-5')

    def test_dashscope_glm_uses_direct_openai_compatible_endpoint(self):
        mykey = importlib.import_module('mykey')
        cfg = mykey.native_oai_config_dashscope_glm_5

        self.assertEqual(cfg['name'], 'dashscope-glm-5')
        self.assertEqual(cfg['apikey'], 'test-dashscope-key')
        self.assertEqual(cfg['apibase'], 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.assertEqual(cfg['model'], 'glm-5')
        self.assertEqual(cfg['api_mode'], 'chat_completions')
        self.assertTrue(cfg['stream'])
        self.assertIsNone(cfg['proxy'])


class TestModelScopeReasoningParsing(unittest.TestCase):
    def test_parse_openai_sse_keeps_reasoning_content(self):
        from llmcore import _parse_openai_sse

        lines = [
            'data: ' + json.dumps({'choices': [{'delta': {'reasoning_content': '先分析问题'}}]}, ensure_ascii=False),
            'data: ' + json.dumps({'choices': [{'delta': {'content': '最终答案'}}]}, ensure_ascii=False),
            'data: [DONE]',
        ]

        gen = _parse_openai_sse(lines)
        streamed = []
        try:
            while True:
                streamed.append(next(gen))
        except StopIteration as e:
            blocks = e.value

        self.assertEqual(streamed, ['先分析问题', '最终答案'])
        self.assertEqual(blocks[0], {'type': 'thinking', 'thinking': '先分析问题'})
        self.assertEqual(blocks[1], {'type': 'text', 'text': '最终答案'})

    def test_parse_openai_json_keeps_reasoning_content(self):
        from llmcore import _parse_openai_json

        payload = {
            'choices': [{
                'message': {
                    'reasoning_content': '先思考',
                    'content': '再回答',
                }
            }]
        }

        gen = _parse_openai_json(payload)
        streamed = []
        try:
            while True:
                streamed.append(next(gen))
        except StopIteration as e:
            blocks = e.value

        self.assertEqual(streamed, ['先思考', '再回答'])
        self.assertEqual(blocks[0], {'type': 'thinking', 'thinking': '先思考'})
        self.assertEqual(blocks[1], {'type': 'text', 'text': '再回答'})


class TestVerifyCopilotModelsPreservesDashscopePrimary(unittest.TestCase):
    def test_render_mykey_keeps_dashscope_glm_first(self):
        from verify_copilot_models import render_mykey

        rendered = render_mykey(['gpt-4', 'claude-sonnet-4.5'])

        self.assertIn('native_oai_config_dashscope_glm_5', rendered)
        self.assertIn("'apibase': 'https://dashscope.aliyuncs.com/compatible-mode/v1'", rendered)
        self.assertIn("'model': 'glm-5'", rendered)
        self.assertIn("'proxy': None", rendered)
        self.assertLess(
            rendered.index("'dashscope-glm-5'"),
            rendered.index("'copilot-gpt4'"),
        )


if __name__ == '__main__':
    unittest.main()