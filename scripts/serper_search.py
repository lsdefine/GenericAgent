#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serper (Google) Search API Wrapper"""
import requests, json, sys, os

def serper_search(api_key, query, count=5):
    """Call Serper Search API (Google) - use x-api-key header"""
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": count}
    resp = requests.post("https://google.serper.dev/search", headers=headers, json=payload, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Serper API error: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    return [{"title": r.get("title", ""), "url": r.get("link", ""), "description": r.get("snippet", "")}
            for r in data.get("organic", [])]

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "AI agent"
    api_key = os.environ.get("X-API-KEY")
    if not api_key:
        raise Exception("X-API-KEY not found in environment")
    results = serper_search(api_key, query)
    print(json.dumps(results, indent=2, ensure_ascii=False))