import json
import os
import tempfile
import unittest


class TestModelRouter(unittest.TestCase):
    def _build_router(self, **overrides):
        from model_router import ModelRouter

        config = {
            'enabled': True,
            'default_model': 'copilot-gpt4',
            'route_targets': {
                'multimodal': 'copilot-gemini',
                'long_context': 'copilot-claude',
                'coding': 'copilot-gpt4',
                'fast': 'opencode-minimax',
            },
            'thresholds': {
                'long_query_chars': 800,
                'long_history_entries': 12,
            },
        }
        config.update(overrides)
        return ModelRouter(config=config)

    def test_routes_image_requests_to_multimodal_target(self):
        router = self._build_router()

        decision = router.route(
            query='帮我分析这张截图里的报错',
            images=['fake-image'],
            history=[],
        )

        self.assertEqual(decision.target_name, 'copilot-gemini')
        self.assertEqual(decision.reason, 'multimodal')

    def test_routes_long_context_to_long_context_target(self):
        router = self._build_router()

        decision = router.route(
            query='A' * 1200,
            images=[],
            history=['h1'],
        )

        self.assertEqual(decision.target_name, 'copilot-claude')
        self.assertEqual(decision.reason, 'long_context')

    def test_routes_coding_debug_requests_to_coding_target(self):
        router = self._build_router()

        decision = router.route(
            query='请帮我修复这个 Python 回溯错误，并给出补丁',
            images=[],
            history=[],
        )

        self.assertEqual(decision.target_name, 'copilot-gpt4')
        self.assertEqual(decision.reason, 'coding')

    def test_routes_simple_chat_to_fast_target(self):
        router = self._build_router()

        decision = router.route(
            query='帮我润色一句周报',
            images=[],
            history=[],
        )

        self.assertEqual(decision.target_name, 'opencode-minimax')
        self.assertEqual(decision.reason, 'fast')

    def test_routes_image_path_to_multimodal_target(self):
        router = self._build_router()

        decision = router.route(
            query=r'请分析这个图片路径 C:\\work\\screenshots\\error.png 并告诉我异常原因',
            images=[],
            history=[],
        )

        self.assertEqual(decision.target_name, 'copilot-gemini')
        self.assertEqual(decision.reason, 'multimodal_path')
        self.assertEqual(decision.details.get('trigger_source'), 'path_vision')

    def test_routes_document_path_to_long_context_target(self):
        router = self._build_router()

        decision = router.route(
            query=r'请根据文档 .\\spec\\prd_v2.pdf 提炼需求并给计划',
            images=[],
            history=[],
        )

        self.assertEqual(decision.target_name, 'copilot-claude')
        self.assertEqual(decision.reason, 'document_path')
        self.assertEqual(decision.details.get('trigger_source'), 'path_document')

    def test_ignores_path_like_text_inside_code_block(self):
        router = self._build_router()

        decision = router.route(
            query='''请解释这段文本：\n```python\npath = "C:/tmp/image.png"\nprint(path)\n```''',
            images=[],
            history=[],
        )

        self.assertEqual(decision.target_name, 'opencode-minimax')
        self.assertEqual(decision.reason, 'fast')

    def test_reload_invalid_json_keeps_last_good_config(self):
        from model_router import ModelRouter

        cfg = {
            'enabled': True,
            'default_model': 'copilot-gpt4',
            'route_targets': {
                'multimodal': 'copilot-gemini',
                'long_context': 'copilot-claude',
                'coding': 'copilot-gpt4',
                'fast': 'opencode-minimax',
            },
        }
        with tempfile.NamedTemporaryFile('w+', encoding='utf-8', delete=False) as f:
            json.dump(cfg, f, ensure_ascii=False)
            path = f.name

        try:
            router = ModelRouter(config_path=path)
            first = router.route(query='普通聊天', images=[], history=[])
            self.assertEqual(first.target_name, 'opencode-minimax')

            with open(path, 'w', encoding='utf-8') as bad:
                bad.write('{ invalid json ')

            router._mtime = -1  # 强制触发 reload_if_needed
            second = router.route(query='继续普通聊天', images=[], history=[])
            self.assertEqual(second.target_name, 'opencode-minimax')
            self.assertTrue(router.last_reload_error)
        finally:
            os.remove(path)


if __name__ == '__main__':
    unittest.main()