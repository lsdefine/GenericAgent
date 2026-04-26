#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jina Reader/Search API Wrapper - Supports Free Endpoint with Auto-Fallback

Features:
- Free endpoint: https://r.jina.ai/http://<URL> (no API key, rate limited)
- API endpoint: Bearer token (requires balance, 10M tokens quota)
- Auto-fallback: 402 error -> automatically use free endpoint
"""
import requests, json, sys, os

def jina_read_url(url, api_key=None, auto_fallback=True):
    """Call Jina Reader API (URL to Markdown)
    
    Args:
        url: Target URL to read
        api_key: Optional Jina API Key for higher rate limits
        auto_fallback: If True, automatically fallback to free endpoint on 402 error
    
    Returns:
        Markdown content string
    """
    # Ensure URL has protocol
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    
    # Try with API key first if provided
    if api_key:
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 402 and auto_fallback:
                # Auto-fallback to free endpoint
                print(f"⚠️ Jina API 402 (insufficient balance), falling back to free endpoint...", file=sys.stderr)
                return jina_read_url(url, api_key=None, auto_fallback=False)
            else:
                raise Exception(f"Jina API error {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as e:
            if auto_fallback:
                print(f"⚠️ Jina API request failed ({e}), falling back to free endpoint...", file=sys.stderr)
                return jina_read_url(url, api_key=None, auto_fallback=False)
            raise
    else:
        # Free endpoint mode - no auth header
        resp = requests.get(f"https://r.jina.ai/{url}", timeout=10)
        if resp.status_code != 200:
            raise Exception(f"Jina Reader error: {resp.status_code} {resp.text[:200]}")
        return resp.text

def jina_search(query, count=5, api_key=None):
    """Call Jina Search API - requires API key with balance
    
    Args:
        query: Search query string
        count: Number of results (default 5)
        api_key: Optional, will try environment variable if not provided
    
    Returns:
        List of search results with title, url, description
    """
    if not api_key:
        api_key = os.environ.get("JINA_API_KEY")
    
    if not api_key:
        raise Exception("JINA_API_KEY required for search. Use read mode with free endpoint instead.")
    
    params = {"query": query, "limit": count}
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.post("https://r.jina.ai/search", json=params, headers=headers, timeout=10)
    
    if resp.status_code == 402:
        raise Exception(f"Jina Search 402 InsufficientBalanceError: Account needs recharge. Use read mode with free endpoint instead.")
    elif resp.status_code != 200:
        raise Exception(f"Jina API error: {resp.status_code} {resp.text[:200]}")
    
    data = resp.json()
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
            for r in data.get("data", [])]

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    
    if len(sys.argv) < 2:
        print("Usage: python jina_reader.py read <url> [--api] [--no-fallback]")
        print("       python jina_reader.py search 'query' [count]")
        print("")
        print("Modes:")
        print("  read <url>           - Auto mode: try API key first, fallback to free endpoint on 402")
        print("  read <url> --api     - Force API key mode (no fallback)")
        print("  read <url> --no-fallback - Disable auto fallback")
        print("  search 'query'       - Search API (requires JINA_API_KEY with balance)")
        print("")
        print("Environment: JINA_API_KEY (from registry or set manually)")
        sys.exit(1)
    
    mode = sys.argv[1]
    api_key = os.environ.get("JINA_API_KEY")
    use_api_force = "--api" in sys.argv
    no_fallback = "--no-fallback" in sys.argv or use_api_force
    
    if mode == "read":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://example.com"
        if use_api_force and not api_key:
            print("❌ --api requires JINA_API_KEY in environment", file=sys.stderr)
            sys.exit(1)
        
        # Auto mode: use api_key if available, with fallback
        effective_key = api_key if (api_key and not no_fallback) else None
        
        try:
            content = jina_read_url(url, api_key=effective_key, auto_fallback=not no_fallback)
            print(content[:3000])
        except Exception as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif mode == "search":
        if not api_key:
            print("❌ JINA_API_KEY not found in environment", file=sys.stderr)
            print("   For free usage, use: python jina_reader.py read <url>", file=sys.stderr)
            sys.exit(1)
        
        query = sys.argv[2] if len(sys.argv) > 2 else "AI agent"
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        
        try:
            results = jina_search(query, count, api_key)
            print(json.dumps(results, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"❌ Search error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)