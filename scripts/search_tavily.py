#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tavily Search API Wrapper"""
import requests, json

def tavily_search(api_key, query, max_results=5):
    """Call Tavily Search API"""
    resp = requests.post(
        'https://api.tavily.com/search',
        json={'query': query, 'api_key': api_key, 'max_results': max_results},
        timeout=10
    )
    if resp.status_code != 200:
        raise Exception(f"Tavily API error: {resp.status_code}")
    data = resp.json()
    return [{'title': r.get('title', ''), 'url': r.get('url', ''), 'description': r.get('content', '')}
            for r in data.get('results', [])]