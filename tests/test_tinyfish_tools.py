import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ga


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class TinyFishToolTests(unittest.TestCase):
    def setUp(self):
        self._env = mock.patch.dict(os.environ, {"TINYFISH_API_KEY": "tf-test"}, clear=False)
        self._env.start()

    def tearDown(self):
        self._env.stop()

    @mock.patch("ga.requests.get")
    def test_search_sends_key_and_limits_results(self, get):
        get.return_value = FakeResponse(
            payload={
                "query": "agent tools",
                "results": [{"title": str(i), "url": f"https://example.com/{i}"} for i in range(5)],
                "total_results": 5,
            }
        )

        result = ga.tinyfish_search("agent tools", location="GB", language="en", page=2, max_results=3)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["results"]), 3)
        get.assert_called_once()
        _, kwargs = get.call_args
        self.assertEqual(kwargs["headers"]["X-API-Key"], "tf-test")
        self.assertEqual(kwargs["params"]["query"], "agent tools")
        self.assertEqual(kwargs["params"]["location"], "GB")
        self.assertEqual(kwargs["params"]["page"], 2)

    @mock.patch("ga.requests.post")
    def test_fetch_posts_payload_and_truncates_text(self, post):
        post.return_value = FakeResponse(
            payload={
                "results": [
                    {"url": "https://example.com", "title": "Example", "text": "x" * 5000, "format": "markdown"}
                ],
                "errors": [],
            }
        )

        result = ga.tinyfish_fetch(["https://example.com"], links=True, image_links=True, max_chars=1200)

        self.assertEqual(result["status"], "success")
        self.assertLess(len(result["results"][0]["text"]), 5000)
        post.assert_called_once()
        _, kwargs = post.call_args
        self.assertEqual(kwargs["headers"]["X-API-Key"], "tf-test")
        self.assertEqual(kwargs["json"]["urls"], ["https://example.com"])
        self.assertTrue(kwargs["json"]["links"])
        self.assertTrue(kwargs["json"]["image_links"])

    def test_fetch_rejects_more_than_ten_urls(self):
        result = ga.tinyfish_fetch([f"https://example.com/{i}" for i in range(11)])

        self.assertEqual(result["status"], "error")
        self.assertIn("at most 10", result["msg"])


if __name__ == "__main__":
    unittest.main()
