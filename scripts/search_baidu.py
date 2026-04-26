#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baidu Search API Wrapper"""
import requests, json

def baidu_search(api_key, request_body):
    """Call Baidu Search API"""
    url = "https://ai.baidu.com/aisearch"
    headers = {"Content-Type": "application/json"}
    params = {"ak": api_key}
    resp = requests.post(url, params=params, json=request_body, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Baidu API error: {resp.status_code} {resp.text}")
    data = resp.json()
    results = []
    for r in data.get('results', []):
        results.append({
            'title': r.get('title', ''),
            'url': r.get('url', ''),
            'description': r.get('abstract', '')
        })
    return results