#!/usr/bin/env python3
"""
ga_search.py — GenericAgent AnySearch实时搜索引擎集成

功能:
  实时web搜索→摘要闭环
  多backend: AnySearch(优先级1) → Tavily(优先级2)
  支持搜索结果摘要提取、Firecrawl深度抓取

用法:
  python ga_search.py "search query"          # CLI搜索
  python ga_search.py "query" --backend tavily  # 指定backend
  python ga_search.py "query" --summarize      # 搜索+AI摘要

API:
  from ga_search import search, search_and_summarize
  results = search("your query")
  summary = search_and_summarize("your query")
"""

import os
import sys
import json
import time
import logging
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger("ga_search")

# ─── 配置 ─────────────────────────────────────────────────────

# AnySearch API (优先级1)
ANYSEARCH_API_KEY = None
ANYSEARCH_API_BASE = os.environ.get(
    "ANYSEARCH_API_BASE",
    "https://anysearch.ai"          # 默认endpoint，可通过env覆盖
)

# Tavily API (优先级2)
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# Firecrawl API (深度抓取)
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")

# 从 mykey.py 加载 AnySearch API Key（若存在）
def _load_anysearch_key():
    """尝试从 mykey.py 加载 ANYSEARCH_API_KEY"""
    global ANYSEARCH_API_KEY
    try:
        mykey_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mykey.py")
        if os.path.exists(mykey_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location("mykey", mykey_path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if hasattr(mod, "agent_api_keys") and isinstance(mod.agent_api_keys, dict):
                    ANYSEARCH_API_KEY = mod.agent_api_keys.get("ANYSEARCH_API_KEY", ANYSEARCH_API_KEY)
    except Exception as e:
        log.debug(f"Load AnySearch key from mykey.py: {e}")

_load_anysearch_key()

# ─── Backend: AnySearch ───────────────────────────────────────

def _search_anysearch(query: str, max_results: int = 5) -> list:
    """
    通过 AnySearch API 搜索。
    AnySearch 是统一的搜索API，替代 Tavily+DashScope。
    返回 [{"title": ..., "url": ..., "content": ..., "score": ...}, ...]
    """
    if not ANYSEARCH_API_KEY:
        log.debug("ANYSEARCH_API_KEY not available, skip AnySearch backend")
        return []

    endpoints = [
        f"{ANYSEARCH_API_BASE}/v1/search",
        f"{ANYSEARCH_API_BASE}/search",
        f"{ANYSEARCH_API_BASE}/api/search",
    ]

    headers = {
        "Authorization": f"Bearer {ANYSEARCH_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }

    for ep in endpoints:
        try:
            import requests
            resp = requests.post(ep, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data.get("data", []))
                if not results and "answer" in data:
                    # Tavily-like response
                    results = data.get("results", [])
                log.info(f"AnySearch[{ep.split('/')[-1]}]: {len(results)} results")
                return results
            else:
                log.debug(f"AnySearch {ep}: HTTP {resp.status_code}")
        except Exception as e:
            log.debug(f"AnySearch {ep}: {e}")
            continue

    log.warning("All AnySearch endpoints failed")
    return []


# ─── Backend: Tavily ──────────────────────────────────────────

def _search_tavily(query: str, max_results: int = 5) -> list:
    """
    通过 Tavily API 搜索（fallback）。
    """
    if not TAVILY_API_KEY:
        log.debug("TAVILY_API_KEY not available, skip Tavily backend")
        return []

    try:
        import requests
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            log.info(f"Tavily: {len(results)} results")
            # 统一返回格式
            unified = []
            for r in results:
                unified.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0),
                })
            return unified
        else:
            log.warning(f"Tavily: HTTP {resp.status_code} - {resp.text[:200]}")
            return []
    except Exception as e:
        log.warning(f"Tavily error: {e}")
        return []


# ─── Backend: Firecrawl (深度抓取) ────────────────────────────

def _scrape_firecrawl(url: str) -> Optional[str]:
    """
    使用 Firecrawl 抓取指定URL的内容。
    """
    if not FIRECRAWL_API_KEY:
        log.debug("FIRECRAWL_API_KEY not available, skip Firecrawl")
        return None

    try:
        import requests
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            json={"url": url, "formats": ["markdown"]},
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("data", {}).get("markdown", "")
            log.info(f"Firecrawl scraped {url}: {len(content)} chars")
            return content[:5000]  # 限制长度
        else:
            log.debug(f"Firecrawl: HTTP {resp.status_code}")
            return None
    except Exception as e:
        log.debug(f"Firecrawl error: {e}")
        return None


# ─── 统一搜索接口 ─────────────────────────────────────────────

def search(query: str, max_results: int = 5, backend: str = "auto") -> list:
    """
    统一搜索接口。

    参数:
      query:      搜索查询
      max_results: 最大结果数 (默认5)
      backend:    "auto" | "anysearch" | "tavily"

    返回:
      [{"title": ..., "url": ..., "content": ..., "score": ...}, ...]
    """
    results = []

    if backend in ("auto", "anysearch"):
        results = _search_anysearch(query, max_results)
        if results:
            return results

    if backend in ("auto", "tavily"):
        results = _search_tavily(query, max_results)
        if results:
            return results

    return results


def search_and_summarize(query: str, max_results: int = 5, backend: str = "auto") -> dict:
    """
    搜索 + 摘要（闭环）。

    返回:
      {
        "query": ...,
        "results": [...],
        "summary": "...",     # 如果有LLM可用则生成摘要
        "sources": [...]
      }
    """
    results = search(query, max_results, backend)

    output = {
        "query": query,
        "results": results,
        "summary": "",
        "sources": [r["url"] for r in results if r.get("url")],
    }

    # 如果有结果且LLM可用，生成摘要
    if results:
        try:
            # 尝试使用 vision_api 的 ask_vision 做摘要（复用现有LLM能力）
            sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
            from vision_api import ask_vision

            context = "\n\n".join([
                f"[{i+1}] {r['title']}: {r.get('content', '')[:500]}"
                for i, r in enumerate(results[:3])
            ])

            summary_prompt = (
                f"基于以下搜索结果为「{query}」写一段中文摘要（200字以内），"
                f"涵盖关键信息：\n\n{context}"
            )

            summary = ask_vision(summary_prompt, backend="openai")
            if summary and not summary.startswith("Error"):
                output["summary"] = summary[:1000]
        except Exception as e:
            log.debug(f"Summarization skipped: {e}")

    return output


# ─── CLI ──────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="GenericAgent AnySearch实时搜索"
    )
    parser.add_argument("query", nargs="?", help="搜索查询")
    parser.add_argument("--backend", default="auto",
                        choices=["auto", "anysearch", "tavily"],
                        help="搜索后端")
    parser.add_argument("--max-results", type=int, default=5,
                        help="最大结果数")
    parser.add_argument("--summarize", action="store_true",
                        help="生成摘要")
    parser.add_argument("--json", action="store_true",
                        help="JSON格式输出")
    parser.add_argument("--scrape", type=str, metavar="URL",
                        help="抓取指定URL内容")

    args = parser.parse_args()

    # 抓取模式
    if args.scrape:
        content = _scrape_firecrawl(args.scrape)
        if content:
            print(content[:2000])
        else:
            print("抓取失败")
        return

    # 搜索模式
    if not args.query:
        parser.print_help()
        return

    if args.summarize:
        result = search_and_summarize(args.query, args.max_results, args.backend)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"🔍 搜索: {result['query']}")
            print(f"{'='*60}")
            if result["summary"]:
                print(f"\n📝 摘要:\n{result['summary']}\n")
            print(f"\n📄 结果 ({len(result['results'])}条):")
            for i, r in enumerate(result["results"]):
                print(f"\n  [{i+1}] {r.get('title', 'N/A')}")
                print(f"       {r.get('url', 'N/A')}")
                if r.get("content"):
                    print(f"       {r['content'][:200]}...")
            if result["sources"]:
                print(f"\n🔗 来源:")
                for s in result["sources"]:
                    print(f"  - {s}")
    else:
        results = search(args.query, args.max_results, args.backend)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"🔍 搜索: {args.query}")
            print(f"{'='*60}")
            print(f"后端: {args.backend} | 结果: {len(results)}条\n")
            for i, r in enumerate(results):
                print(f"  [{i+1}] {r.get('title', 'N/A')}")
                print(f"       {r.get('url', 'N/A')}")
                if r.get("content"):
                    print(f"       {r['content'][:200]}...")


if __name__ == "__main__":
    main()
