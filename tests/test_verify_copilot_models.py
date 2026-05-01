import tempfile
import unittest
from pathlib import Path

from verify_copilot_models import apply_updates


class TestVerifyCopilotModels(unittest.TestCase):
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

            apply_updates(['gpt-4'], litellm_config_path=litellm_path, mykey_path=mykey_path)

            litellm_text = litellm_path.read_text(encoding='utf-8')
            mykey_text = mykey_path.read_text(encoding='utf-8')
            self.assertIn('model_name: gpt-4', litellm_text)
            self.assertIn("'model': 'gpt-4'", mykey_text)


if __name__ == '__main__':
    unittest.main()
