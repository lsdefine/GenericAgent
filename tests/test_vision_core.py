import os
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vision_core


class FakeRawSession:
    def __init__(self):
        self.seen = None
        self.connect_timeout = 1
        self.read_timeout = 1
        self.max_retries = 9
    def raw_ask(self, messages):
        self.seen = messages
        yield 'chunk-'
        yield 'tail'
        return [{'type': 'text', 'text': 'done'}]


class FakeMakeMessagesSession(FakeRawSession):
    def make_messages(self, raw_list):
        self.made_from = raw_list
        return raw_list


class FakeAskSession:
    def __init__(self):
        self.seen = None
    def ask(self, msg):
        self.seen = msg
        yield 'ignored'
        class Resp:
            content = 'ask-path-ok'
        return Resp()


class Wrapper:
    def __init__(self, backend):
        self.backend = backend


class FakeConstructedSession(FakeRawSession):
    last_cfg = None
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        FakeConstructedSession.last_cfg = dict(cfg)


class TestVisionCore(unittest.TestCase):
    def test_build_user_message_uses_default_prompt_and_image_block(self):
        img = Image.new('RGB', (32, 16), 'red')
        msg = vision_core._build_user_message(img)
        self.assertEqual(msg['role'], 'user')
        self.assertEqual(msg['content'][0]['type'], 'image')
        self.assertEqual(msg['content'][0]['source']['type'], 'base64')
        self.assertEqual(msg['content'][1]['text'], vision_core.DEFAULT_PROMPT)

    def test_image_to_data_url_and_resize(self):
        img = Image.new('RGB', (4000, 2000), 'blue')
        url = vision_core.image_to_data_url(img, max_pixels=1_000_000)
        self.assertTrue(url.startswith('data:image/png;base64,'))
        data, media_type, size = vision_core._encode_png_bytes(img, max_pixels=1_000_000)
        self.assertEqual(media_type, 'image/png')
        self.assertTrue(len(data) > 0)
        self.assertLessEqual(size[0] * size[1], 1_000_000)

    def test_ask_vision_with_raw_session_and_restore_overrides(self):
        session = FakeRawSession()
        img = Image.new('RGB', (100, 50), 'green')
        res = vision_core.ask_vision(img, prompt='describe it', session=session, timeout=12, max_retries=2)
        self.assertEqual(res, 'done')
        self.assertEqual(session.seen[0]['role'], 'user')
        self.assertEqual(session.seen[0]['content'][0]['type'], 'image')
        self.assertEqual(session.seen[0]['content'][1]['text'], 'describe it')
        self.assertEqual(session.connect_timeout, 1)
        self.assertEqual(session.read_timeout, 1)
        self.assertEqual(session.max_retries, 9)

    def test_ask_vision_unwraps_wrapper_backend(self):
        session = Wrapper(FakeRawSession())
        img = Image.new('RGB', (10, 10), 'white')
        res = vision_core.ask_vision(img, session=session)
        self.assertEqual(res, 'done')
        self.assertEqual(session.backend.seen[0]['content'][0]['type'], 'image')

    def test_ask_vision_prefers_make_messages(self):
        session = FakeMakeMessagesSession()
        img = Image.new('RGB', (8, 8), 'yellow')
        res = vision_core.ask_vision(img, session=session)
        self.assertEqual(res, 'done')
        self.assertEqual(session.made_from[0]['role'], 'user')
        self.assertEqual(session.seen[0]['role'], 'user')

    def test_ask_path_without_raw_ask_supported(self):
        session = FakeAskSession()
        img = Image.new('RGB', (8, 8), 'black')
        res = vision_core.ask_vision(img, session=session)
        self.assertEqual(res, 'ask-path-ok')
        self.assertEqual(session.seen['content'][0]['type'], 'image')

    def test_error_is_normalized_to_string(self):
        class BadSession:
            def raw_ask(self, messages):
                raise RuntimeError('boom')
                yield
        img = Image.new('RGB', (8, 8), 'black')
        res = vision_core.ask_vision(img, session=BadSession())
        self.assertTrue(res.startswith('Error:'))
        self.assertIn('boom', res)

    def test_cfg_name_route_uses_llmcore_mykeys_without_reading_real_secret_content(self):
        img = Image.new('RGB', (12, 12), 'purple')
        fake_keys = {
            'claude_config141': {
                'apikey': 'test',
                'apibase': 'https://example.com',
                'model': 'claude-test',
            }
        }
        with patch.object(vision_core.llmcore, 'mykeys', fake_keys, create=True):
            with patch.object(vision_core, '_guess_session_cls', return_value=FakeConstructedSession):
                res = vision_core.ask_vision(img, cfg_name='claude_config141', timeout=22, max_retries=3)
        self.assertEqual(res, 'done')
        self.assertEqual(FakeConstructedSession.last_cfg['apikey'], 'test')
        self.assertEqual(FakeConstructedSession.last_cfg['timeout'], 10)
        self.assertEqual(FakeConstructedSession.last_cfg['read_timeout'], 22)
        self.assertEqual(FakeConstructedSession.last_cfg['max_retries'], 3)


if __name__ == '__main__':
    unittest.main()
