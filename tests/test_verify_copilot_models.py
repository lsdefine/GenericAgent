import tempfile
import unittest
from pathlib import Path

from verify_copilot_models import apply_updates, select_preferred_models


class TestVerifyCopilotModels(unittest.TestCase):
    def test_select_preferred_models_picks_highest_supported_per_family(self):
        results = {
            'gpt-5.4': {'success': True},
            'gpt-5.2': {'success': True},
            'gpt-5-mini': {'success': True},
            'gpt-4.1': {'success': True},
            'gpt-4o': {'success': True},
            'gpt-4': {'success': True},
            'claude-sonnet-4.6': {'success': True},
            'claude-sonnet-4.5': {'success': True},
            'claude-sonnet-4': {'success': True},
            'claude-haiku-4.5': {'success': True},
            'gemini-3.1-pro-preview': {'success': True},
            'gemini-2.5-pro': {'success': True},
            'gemini-3-flash-preview': {'success': True},
        }

        selected = select_preferred_models(results)

        self.assertEqual(selected, ['gpt-5.4', 'claude-sonnet-4.6', 'gemini-3.1-pro-preview'])

    def test_apply_updates_refuses_empty_supported_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            litellm_path = Path(tmpdir) / 'litellm_config.yaml'
            mykey_path = Path(tmpdir) / 'mykey.py'
            litellm_path.write_text('model_list:\n  - model_name: gpt-4\n', encoding='utf-8')
            mykey_path.write_text("import os\n\n# keep\n", encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'Refusing to apply empty Copilot model set'):
                apply_updates([], litellm_config_path=litellm_path, mykey_path=mykey_path)

            self.assertIn('gpt-4', litellm_path.read_text(encoding='utf-8'))
            self.assertIn('# keep', mykey_path.read_text(encoding='utf-8'))

    def test_apply_updates_writes_supported_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            litellm_path = Path(tmpdir) / 'litellm_config.yaml'
            mykey_path = Path(tmpdir) / 'mykey.py'
            litellm_path.write_text('model_list:\n', encoding='utf-8')
            mykey_path.write_text("import os\n", encoding='utf-8')

            apply_updates(['gpt-5.4', 'claude-sonnet-4.6'], litellm_config_path=litellm_path, mykey_path=mykey_path)

            litellm_text = litellm_path.read_text(encoding='utf-8')
            mykey_text = mykey_path.read_text(encoding='utf-8')
            self.assertIn('model_name: gpt-5.4', litellm_text)
            self.assertIn('model_name: claude-sonnet-4.6', litellm_text)
            self.assertIn("'model': 'gpt-5.4'", mykey_text)
            self.assertIn("'model': 'claude-sonnet-4.6'", mykey_text)


if __name__ == '__main__':
    unittest.main()
