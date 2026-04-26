import base64
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentmain import build_multimodal_user_content


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK3sAAAAASUVORK5CYII="
)


class TestMultimodalUserContent(unittest.TestCase):
    def test_build_multimodal_user_content_includes_image_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, 'tiny.png')
            with open(image_path, 'wb') as f:
                f.write(PNG_1X1)

            content = build_multimodal_user_content('看图回答', [image_path])

        self.assertEqual(content[0], {'type': 'text', 'text': '看图回答'})
        self.assertEqual(content[1]['type'], 'image')
        self.assertEqual(content[1]['source']['type'], 'base64')
        self.assertEqual(content[1]['source']['media_type'], 'image/png')
        self.assertTrue(content[1]['source']['data'])

    def test_build_multimodal_user_content_skips_missing_or_non_image_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            text_path = os.path.join(temp_dir, 'note.txt')
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write('hello')

            content = build_multimodal_user_content('只保留文本', [text_path, os.path.join(temp_dir, 'missing.png')])

        self.assertEqual(content, [{'type': 'text', 'text': '只保留文本'}])