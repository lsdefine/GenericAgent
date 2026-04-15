"""Unit tests for memory/exa_search.py.

Covers:
  - snippet fallback (highlights → summary → text → empty)
  - client singleton + integration header + key loading
  - search() kwargs wiring (types, filters, content flags)
  - disabled state when EXA_API_KEY is missing and keychain has no entry
"""
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Match the sys.path pattern used in other tests + the one skills themselves use.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_DIR)
sys.path.insert(0, os.path.join(_REPO_DIR, "memory"))


def _fresh_module():
    """Re-import exa_search with a cleared _client singleton so each test starts clean."""
    if "exa_search" in sys.modules:
        del sys.modules["exa_search"]
    import exa_search  # noqa: E402
    return exa_search


class _FakeResult:
    """Mimics one entry of exa_py's SearchResponse.results."""
    def __init__(self, **kw):
        self.title = kw.get("title")
        self.url = kw.get("url")
        self.published_date = kw.get("published_date")
        self.author = kw.get("author")
        self.score = kw.get("score")
        self.highlights = kw.get("highlights")
        self.summary = kw.get("summary")
        self.text = kw.get("text")


class _FakeResponse:
    def __init__(self, results):
        self.results = results


def _install_fake_exa_py(captured: dict):
    """Install a fake exa_py module so `from exa_py import Exa` inside exa_search works."""
    fake_mod = types.ModuleType("exa_py")

    class FakeExa:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            captured["instance"] = self
            self.headers = {}

        def search_and_contents(self, query, **kwargs):
            captured["method"] = "search_and_contents"
            captured["query"] = query
            captured["kwargs"] = kwargs
            return _FakeResponse(captured.get("return_results", []))

        def find_similar_and_contents(self, url, **kwargs):
            captured["method"] = "find_similar_and_contents"
            captured["url"] = url
            captured["kwargs"] = kwargs
            return _FakeResponse(captured.get("return_results", []))

        def get_contents(self, urls, **kwargs):
            captured["method"] = "get_contents"
            captured["urls"] = urls
            captured["kwargs"] = kwargs
            return _FakeResponse(captured.get("return_results", []))

    fake_mod.Exa = FakeExa
    sys.modules["exa_py"] = fake_mod
    return fake_mod


class TestSnippetFallback(unittest.TestCase):
    """_extract_snippet must cascade: highlights → summary → text → ''."""

    def setUp(self):
        self.mod = _fresh_module()

    def test_highlights_preferred(self):
        r = _FakeResult(highlights=["alpha", "beta"], summary="summ", text="full")
        self.assertEqual(self.mod._extract_snippet(r), "alpha beta")

    def test_summary_when_no_highlights(self):
        r = _FakeResult(highlights=None, summary="summ", text="full")
        self.assertEqual(self.mod._extract_snippet(r), "summ")

    def test_summary_when_highlights_empty_list(self):
        r = _FakeResult(highlights=[], summary="summ", text="full")
        self.assertEqual(self.mod._extract_snippet(r), "summ")

    def test_text_when_no_highlights_or_summary(self):
        r = _FakeResult(text="full page text")
        self.assertEqual(self.mod._extract_snippet(r), "full page text")

    def test_empty_when_all_missing(self):
        r = _FakeResult()
        self.assertEqual(self.mod._extract_snippet(r), "")

    def test_highlights_all_empty_strings_falls_through(self):
        r = _FakeResult(highlights=["", ""], summary="summ")
        # Joined empty strings → falsy → fall through to summary
        self.assertEqual(self.mod._extract_snippet(r), "summ")

    def test_long_snippet_truncated(self):
        r = _FakeResult(text="x" * 2000)
        self.assertEqual(len(self.mod._extract_snippet(r)), 500)


class TestConvert(unittest.TestCase):
    """_convert produces typed ExaResult with all fields."""

    def setUp(self):
        self.mod = _fresh_module()

    def test_full_conversion(self):
        r = _FakeResult(
            title="T", url="https://ex.com", published_date="2025-01-01",
            author="A", score=0.9, highlights=["h1"], summary="s", text="t",
        )
        out = self.mod._convert(r)
        self.assertEqual(out.title, "T")
        self.assertEqual(out.url, "https://ex.com")
        self.assertEqual(out.snippet, "h1")
        self.assertEqual(out.published_date, "2025-01-01")
        self.assertEqual(out.author, "A")
        self.assertEqual(out.score, 0.9)
        self.assertEqual(out.highlights, ["h1"])
        self.assertEqual(out.summary, "s")
        self.assertEqual(out.text, "t")

    def test_defaults_when_missing(self):
        out = self.mod._convert(_FakeResult())
        self.assertEqual(out.title, "")
        self.assertEqual(out.url, "")
        self.assertEqual(out.snippet, "")
        self.assertIsNone(out.published_date)
        self.assertEqual(out.highlights, [])


class TestClientConstruction(unittest.TestCase):
    """Client singleton sets integration header and reads EXA_API_KEY."""

    def setUp(self):
        self.captured: dict = {}
        _install_fake_exa_py(self.captured)
        self.mod = _fresh_module()

    def tearDown(self):
        os.environ.pop("EXA_API_KEY", None)
        sys.modules.pop("exa_py", None)

    def test_uses_env_var(self):
        os.environ["EXA_API_KEY"] = "sk-env"
        self.mod._client = None
        c = self.mod._get_client()
        self.assertEqual(self.captured["api_key"], "sk-env")
        self.assertEqual(c.headers["x-exa-integration"], "generic-agent")

    def test_singleton_reused(self):
        os.environ["EXA_API_KEY"] = "sk-env"
        self.mod._client = None
        c1 = self.mod._get_client()
        c2 = self.mod._get_client()
        self.assertIs(c1, c2)

    def test_missing_key_raises(self):
        os.environ.pop("EXA_API_KEY", None)
        self.mod._client = None
        # Patch keychain lookup inside _load_api_key so we test the "no key anywhere" path
        # regardless of whether memory/keychain.py has a real saved key locally.
        with patch.object(self.mod, "_load_api_key", side_effect=RuntimeError("EXA_API_KEY not set.")):
            with self.assertRaises(RuntimeError) as ctx:
                self.mod._get_client()
            self.assertIn("EXA_API_KEY", str(ctx.exception))

    def test_missing_sdk_raises_helpful_error(self):
        # Simulate exa-py not installed.
        os.environ["EXA_API_KEY"] = "sk-env"
        self.mod._client = None
        sys.modules.pop("exa_py", None)
        # With exa_py removed from sys.modules and no install on path, import fails.
        # We guarantee that by patching builtins.__import__ for the "exa_py" name only.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "exa_py":
                raise ImportError("No module named 'exa_py'")
            return real_import(name, *a, **kw)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            with self.assertRaises(ImportError) as ctx:
                self.mod._get_client()
            self.assertIn("exa-py", str(ctx.exception))


class TestSearchKwargsWiring(unittest.TestCase):
    """search() must wire all kwargs to the SDK correctly."""

    def setUp(self):
        self.captured: dict = {}
        _install_fake_exa_py(self.captured)
        os.environ["EXA_API_KEY"] = "sk-env"
        self.mod = _fresh_module()
        self.mod._client = None

    def tearDown(self):
        os.environ.pop("EXA_API_KEY", None)
        sys.modules.pop("exa_py", None)

    def test_defaults(self):
        self.captured["return_results"] = []
        self.mod.search("hello")
        kw = self.captured["kwargs"]
        self.assertEqual(self.captured["query"], "hello")
        self.assertEqual(kw["type"], "auto")
        self.assertEqual(kw["num_results"], 10)
        self.assertEqual(kw["highlights"], True)
        # None-valued args must NOT be passed through
        self.assertNotIn("category", kw)
        self.assertNotIn("text", kw)
        self.assertNotIn("summary", kw)
        self.assertNotIn("include_domains", kw)

    def test_all_filters_forwarded(self):
        self.captured["return_results"] = []
        self.mod.search(
            "q",
            num_results=3,
            search_type="neural",
            category="research paper",
            include_domains=["arxiv.org"],
            exclude_domains=["reddit.com"],
            include_text=["transformer"],
            exclude_text=["ad"],
            start_published_date="2025-01-01T00:00:00Z",
            end_published_date="2025-12-31T00:00:00Z",
            text={"maxCharacters": 500},
            highlights={"maxCharacters": 200, "query": "results"},
            summary={"query": "findings"},
        )
        kw = self.captured["kwargs"]
        self.assertEqual(kw["type"], "neural")
        self.assertEqual(kw["num_results"], 3)
        self.assertEqual(kw["category"], "research paper")
        self.assertEqual(kw["include_domains"], ["arxiv.org"])
        self.assertEqual(kw["exclude_domains"], ["reddit.com"])
        self.assertEqual(kw["include_text"], ["transformer"])
        self.assertEqual(kw["exclude_text"], ["ad"])
        self.assertEqual(kw["start_published_date"], "2025-01-01T00:00:00Z")
        self.assertEqual(kw["end_published_date"], "2025-12-31T00:00:00Z")
        self.assertEqual(kw["text"], {"maxCharacters": 500})
        self.assertEqual(kw["highlights"]["maxCharacters"], 200)
        self.assertEqual(kw["summary"], {"query": "findings"})

    def test_highlights_can_be_disabled(self):
        self.captured["return_results"] = []
        self.mod.search("q", highlights=None)
        self.assertNotIn("highlights", self.captured["kwargs"])

    def test_content_types_combine(self):
        """Text + highlights + summary must all be sent together; they're not mutually exclusive."""
        self.captured["return_results"] = []
        self.mod.search("q", text=True, highlights=True, summary={"query": "x"})
        kw = self.captured["kwargs"]
        self.assertTrue(kw["text"])
        self.assertTrue(kw["highlights"])
        self.assertEqual(kw["summary"], {"query": "x"})

    def test_returns_typed_results(self):
        self.captured["return_results"] = [
            _FakeResult(title="T1", url="https://a", highlights=["snip1"]),
            _FakeResult(title="T2", url="https://b", summary="snip2"),
        ]
        out = self.mod.search("q")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].title, "T1")
        self.assertEqual(out[0].snippet, "snip1")
        self.assertEqual(out[1].snippet, "snip2")
        self.assertEqual(out[1].title, "T2")

    def test_empty_results(self):
        self.captured["return_results"] = []
        self.assertEqual(self.mod.search("q"), [])

    def test_missing_results_attr(self):
        """If the SDK response has no `results` attr, return []."""
        class NoResults: pass
        with patch.object(self.mod, "_get_client") as gc:
            client = MagicMock()
            client.search_and_contents.return_value = NoResults()
            gc.return_value = client
            self.assertEqual(self.mod.search("q"), [])


class TestFindSimilarAndGetContents(unittest.TestCase):
    def setUp(self):
        self.captured: dict = {}
        _install_fake_exa_py(self.captured)
        os.environ["EXA_API_KEY"] = "sk-env"
        self.mod = _fresh_module()
        self.mod._client = None

    def tearDown(self):
        os.environ.pop("EXA_API_KEY", None)
        sys.modules.pop("exa_py", None)

    def test_find_similar(self):
        self.captured["return_results"] = [_FakeResult(title="sim", url="https://s", text="body")]
        out = self.mod.find_similar("https://seed.com", num_results=5)
        self.assertEqual(self.captured["method"], "find_similar_and_contents")
        self.assertEqual(self.captured["url"], "https://seed.com")
        self.assertEqual(self.captured["kwargs"]["num_results"], 5)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "sim")

    def test_get_contents_default_text_true(self):
        self.captured["return_results"] = [_FakeResult(url="https://x", text="full text")]
        out = self.mod.get_contents(["https://x"])
        self.assertEqual(self.captured["method"], "get_contents")
        self.assertEqual(self.captured["urls"], ["https://x"])
        self.assertTrue(self.captured["kwargs"]["text"])
        self.assertEqual(out[0].text, "full text")


if __name__ == "__main__":
    unittest.main()
