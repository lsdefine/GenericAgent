import unittest
from model_router import ModelRouter

class TestModelRouter(unittest.TestCase):

    def setUp(self):
        self.router = ModelRouter(config={
            'enabled': True,
            'default_model': 'default-model',
            'route_targets': {
                'multimodal': 'multimodal-model',
                'long_context': 'long-context-model',
                'coding': 'coding-model',
                'fast': 'fast-model'
            },
            'thresholds': {
                'long_query_chars': 800,
                'long_history_entries': 12
            },
            'path_detection': {
                'enabled': True,
                'image_exts': ['.png', '.jpg'],
                'video_exts': ['.mp4'],
                'doc_exts': ['.pdf', '.docx']
            }
        })

    def test_routing_statistics(self):
        query = "This is a test document path: example.docx"
        decision = self.router.route(query)
        self.assertEqual(decision.target_name, 'long-context-model')
        self.assertEqual(decision.reason, 'document_path')
        # Placeholder: Add assertions for routing statistics once implemented

if __name__ == '__main__':
    unittest.main()