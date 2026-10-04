import importlib.util
import json
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / 'assets' / 'configure_mykey.py'
SPEC = importlib.util.spec_from_file_location('configure_mykey', MODULE_PATH)
CONFIGURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIGURE)


class ProviderConfigurationTest(unittest.TestCase):
    def test_atlascloud_preset_uses_native_oai(self):
        provider = next(p for p in CONFIGURE.LLM_PROVIDERS if p['id'] == 'atlascloud')

        self.assertEqual(provider['type'], 'native_oai')
        self.assertEqual(provider['template']['apibase'], 'https://api.atlascloud.ai/v1')
        self.assertEqual(provider['template']['model'], 'deepseek-ai/deepseek-v4-pro')
        self.assertEqual(provider['template']['api_mode'], 'chat_completions')

    @mock.patch.object(CONFIGURE, '_get_proxy_handler', return_value=None)
    @mock.patch.object(CONFIGURE.urllib.request, 'build_opener')
    def test_atlascloud_model_probe_uses_bearer_auth(self, build_opener, _proxy):
        opener = build_opener.return_value
        response = opener.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps(
            {'data': [{'id': 'z-model'}, {'id': 'a-model'}]}
        ).encode()
        provider = next(p for p in CONFIGURE.LLM_PROVIDERS if p['id'] == 'atlascloud')

        models = CONFIGURE.probe_models(provider, 'test-key')

        self.assertEqual(models, ['a-model', 'z-model'])
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.atlascloud.ai/v1/models')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')


if __name__ == '__main__':
    unittest.main()
