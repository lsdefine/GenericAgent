#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brave Search API Wrapper"""
import requests, json, sys, os

def brave_search(api_key, query, count=5):
    """Call Brave Search API"""
    params = {"q": query, "count": count}
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    resp = requests.get("https://api.search.brave.com/res/v1/web/search", params=params, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Brave API error: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    results = []
    for r in data.get("web", {}).get("results", []):
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("description", "")
        })
    return results

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "AI agent"
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        raise Exception("BRAVE_API_KEY not found")
    results = brave_search(api_key, query)
    # 确保输出UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))