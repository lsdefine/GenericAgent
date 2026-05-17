
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontends")))

import frontends.fsapp as fsapp


class FeishuCardSectionTests(unittest.TestCase):
    def test_final_output_uses_collapsible_sections(self):
        card = fsapp._TaskCard("chat-1", "chat_id", reply_to_message_id="root-1")
        card.final = "# ???\n?????????\n\n# ???\n?????????"

        payload = json.loads(card._build())
        elements = payload["body"]["elements"]
        panels = [element for element in elements if element.get("tag") == "collapsible_panel"]

        self.assertEqual(len(panels), 2)
        self.assertEqual([panel["expanded"] for panel in panels], [False, False])
        self.assertEqual(panels[0]["header"]["title"]["content"], "???")
        self.assertEqual(panels[1]["header"]["title"]["content"], "???")
        self.assertNotIn("?????????", [element.get("content", "") for element in elements if element.get("tag") == "markdown"])

    def test_long_plain_final_output_is_chunked(self):
        sections = fsapp._split_card_sections("???\n\n" + ("x" * 30) + "\n\n???", limit=20)

        self.assertGreaterEqual(len(sections), 2)
        self.assertTrue(all(len(body) <= 20 for _, body in sections))


if __name__ == "__main__":
    unittest.main()
