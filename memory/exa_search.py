"""Exa web search skill. `from exa_search import search; search("query")`. Needs `pip install exa-py` and EXA_API_KEY (env or `keys.exa_api_key`)."""
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

_INTEGRATION_TAG = "generic-agent"
_client = None


def _load_api_key() -> str:
    key = os.environ.get("EXA_API_KEY")
    if key:
        return key
    # Fall back to local keychain (memory/keychain.py) so users don't have to export env vars
    try:
        import keychain
        return keychain.keys.exa_api_key.use()
    except Exception:
        pass
    raise RuntimeError(
        "EXA_API_KEY not set. Either `export EXA_API_KEY=...` or run "
        "`from keychain import keys; keys.set('exa_api_key', 'sk-...')` once."
    )


def _get_client():
    """Lazy singleton. Sets the x-exa-integration header so Exa can attribute usage."""
    global _client
    if _client is not None:
        return _client
    try:
        from exa_py import Exa
    except ImportError as e:
        raise ImportError("exa-py not installed. Run `pip install exa-py`.") from e
    c = Exa(_load_api_key())
    # Usage attribution. Safe if the SDK ever drops the attribute: falls through to the except.
    try:
        c.headers["x-exa-integration"] = _INTEGRATION_TAG
    except Exception:
        pass
    _client = c
    return c


@dataclass
class ExaResult:
    """Typed wrapper for one Exa result. `snippet` cascades through highlights/summary/text."""
    title: str
    url: str
    snippet: str
    published_date: Optional[str] = None
    author: Optional[str] = None
    score: Optional[float] = None
    highlights: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    text: Optional[str] = None

    def __repr__(self):
        s = self.snippet
        if len(s) > 120:
            s = s[:117] + "..."
        return f"ExaResult(url={self.url!r}, snippet={s!r})"


def _extract_snippet(r) -> str:
    """Pick the best short preview: highlights → summary → text. Any may be missing."""
    hs = getattr(r, "highlights", None) or []
    if hs:
        joined = " ".join(h for h in hs if h)
        if joined:
            return joined[:500]
    summ = getattr(r, "summary", None)
    if summ:
        return summ[:500]
    txt = getattr(r, "text", None)
    if txt:
        return txt[:500]
    return ""


def _convert(r) -> ExaResult:
    return ExaResult(
        title=getattr(r, "title", None) or "",
        url=getattr(r, "url", None) or "",
        snippet=_extract_snippet(r),
        published_date=getattr(r, "published_date", None),
        author=getattr(r, "author", None),
        score=getattr(r, "score", None),
        highlights=list(getattr(r, "highlights", None) or []),
        summary=getattr(r, "summary", None),
        text=getattr(r, "text", None),
    )


def search(
    query: str,
    *,
    num_results: int = 10,
    search_type: str = "auto",
    category: Optional[str] = None,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
    include_text: Optional[List[str]] = None,
    exclude_text: Optional[List[str]] = None,
    start_published_date: Optional[str] = None,
    end_published_date: Optional[str] = None,
    text: Any = None,
    highlights: Any = True,
    summary: Any = None,
) -> List[ExaResult]:
    """
    Semantic web search via Exa. Returns list[ExaResult].

    search_type: 'auto' (default) | 'neural' | 'fast' | 'instant' | 'deep' | 'deep-lite' | 'deep-reasoning'
    category:    'company' | 'research paper' | 'news' | 'personal site' | 'financial report' | 'people'

    Content flags (pass True, a dict like {'maxCharacters': 500}, or None to omit):
      - highlights: short relevant excerpts (default: True, gives compact snippets)
      - text: full page text (use sparingly — large payloads)
      - summary: LLM-distilled summary, dict only, e.g. {'query': 'key findings'}

    Dates are ISO 8601 strings (e.g. '2025-01-01T00:00:00Z').
    """
    kwargs: dict = {"num_results": num_results, "type": search_type}
    if category:               kwargs["category"] = category
    if include_domains:        kwargs["include_domains"] = include_domains
    if exclude_domains:        kwargs["exclude_domains"] = exclude_domains
    if include_text:           kwargs["include_text"] = include_text
    if exclude_text:           kwargs["exclude_text"] = exclude_text
    if start_published_date:   kwargs["start_published_date"] = start_published_date
    if end_published_date:     kwargs["end_published_date"] = end_published_date
    if text is not None:       kwargs["text"] = text
    if highlights is not None: kwargs["highlights"] = highlights
    if summary is not None:    kwargs["summary"] = summary

    resp = _get_client().search_and_contents(query, **kwargs)
    return [_convert(r) for r in (getattr(resp, "results", None) or [])]


def find_similar(
    url: str,
    *,
    num_results: int = 10,
    highlights: Any = True,
    text: Any = None,
    summary: Any = None,
) -> List[ExaResult]:
    """Find pages semantically similar to `url`. Same content flags as search()."""
    kwargs: dict = {"num_results": num_results}
    if highlights is not None: kwargs["highlights"] = highlights
    if text is not None:       kwargs["text"] = text
    if summary is not None:    kwargs["summary"] = summary
    resp = _get_client().find_similar_and_contents(url, **kwargs)
    return [_convert(r) for r in (getattr(resp, "results", None) or [])]


def get_contents(
    urls: List[str],
    *,
    text: Any = True,
    highlights: Any = None,
    summary: Any = None,
) -> List[ExaResult]:
    """Fetch page contents for known URLs (bypasses search)."""
    kwargs: dict = {}
    if text is not None:       kwargs["text"] = text
    if highlights is not None: kwargs["highlights"] = highlights
    if summary is not None:    kwargs["summary"] = summary
    resp = _get_client().get_contents(urls, **kwargs)
    return [_convert(r) for r in (getattr(resp, "results", None) or [])]


if __name__ == "__main__":
    # CLI: python exa_search.py "<query>" [num_results]
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "latest LLM research"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    for r in search(q, num_results=n):
        print(f"- {r.title}\n  {r.url}\n  {r.snippet[:200]}\n")
