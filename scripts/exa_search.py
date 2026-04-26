#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exa Semantic Search API Wrapper"""
import requests, json, sys, os

def exa_search(api_key, query, type="auto", count=5):
    """Call Exa Semantic Search API"""
    params = {
        "query": query,
        "numResults": count,
        "type": type
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.post("https://api.exa.ai/search", json=params, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Exa API error: {resp.status_code} {resp.text}")
    data = resp.json()
    return [{'title': r.get('title', ''), 'url': r.get('url', ''), 'description': r.get('text', '')}
            for r in data.get('results', [])]

if __name__ == '__main__':
    query = sys.argv[1] if len(sys.argv) > 1 else "AI agent"
    api_key = os.environ.get('EXA_API_KEY')
    if not api_key:
        raise Exception("EXA_API_KEY not found")
    results = exa_search(api_key, query)
    print(json.dumps(results, indent=2, ensure_ascii=False))