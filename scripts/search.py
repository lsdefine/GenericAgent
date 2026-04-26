#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified Search Entry - GA 搜索工具统一入口
支持：Baidu,Tavily,Brave,Serper,Exa,Jina
调用示例:
  python search.py "query text"
  python search.py '{"query": "...", "engine": "tavily", "count": 5}'
"""
import sys, io, os, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def parse_query(args):
    """解析输入参数: 支持纯文本和JSON"""
    if not args:
        return {"query": "", "count": 5, "engine": "baidu"}
    first = args[0]
    if first.startswith('{'):
        try:
            return json.loads(first)
        except:
            pass
    return {"query": first, "count": 5, "engine": "baidu"}

def call_baidu(query, count=5):
    """调用Baidu Search API"""
    from search_baidu import baidu_search
    current_time = __import__('datetime').datetime.now()
    from datetime import timedelta
    request_body = {"query": query, "count": count}
    results = baidu_search(os.environ['BAIDU_API_KEY'], request_body)
    return results

def call_tavily(query, count=5):
    """调用Tavily Search API"""
    from search_tavily import tavily_search
    api_key = os.environ['TAVILY_API_KEY']
    results = tavily_search(api_key, query, count)
    return results

def call_brave(query, count=5):
    """调用Brave Search API"""
    import requests
    api_key = os.environ['BRAVE_API_KEY']
    resp = requests.get(
        'https://api.search.brave.com/res/v1/web/search',
        params={'q': query, 'count': count},
        headers={'X-Subscription-Token': api_key},
        timeout=10
    )
    if resp.status_code != 200:
        raise Exception(f"Brave API error: {resp.status_code}")
    data = resp.json()
    return [{'title': r.get('title'), 'url': r.get('url'), 'description': r.get('description')} 
            for r in data.get('web', {}).get('results', [])]

def call_serper(query, count=5):
    """调用Serper (Google) API"""
    import requests
    api_key = os.environ['GOOGLE_SERPER_API_KEY']
    resp = requests.post(
        'https://google.serper.dev/search',
        json={'q': query, 'num': count},
        headers={'X-API-KEY': api_key},
        timeout=10
    )
    if resp.status_code != 200:
        raise Exception(f"Serper API error: {resp.status_code}")
    data = resp.json()
    return [{'title': r.get('title'), 'url': r.get('link'), 'description': r.get('snippet')}
            for r in data.get('organic', [])]

def call_exa(query, count=5):
    """调用Exa Semantic Search"""
    import requests
    api_key = os.environ['EXA_API_KEY']
    resp = requests.post(
        'https://api.exa.ai/search',
        json={'query': query, 'numResults': count},
        headers={'Authorization': f'Bearer {api_key}'},
        timeout=10
    )
    if resp.status_code != 200:
        raise Exception(f"Exa API error: {resp.status_code}")
    data = resp.json()
    return [{'title': r.get('title', ''), 'url': r.get('url', ''), 'description': r.get('text', '')}
            for r in data.get('results', [])]

def call_jina_read(query, count=5):
    """调用Jina Reader (search mode)"""
    import requests
    api_key = os.environ['JINA_API_KEY']
    resp = requests.post(
        'https://r.jina.ai/search',
        json={'query': query, 'limit': count},
        headers={'Authorization': f'Bearer {api_key}'},
        timeout=10
    )
    if resp.status_code != 200:
        raise Exception(f"Jina API error: {resp.status_code}")
    data = resp.json()
    return [{'title': r.get('title', ''), 'url': r.get('url', ''), 'description': r.get('description', '')}
            for r in data.get('results', [])]

def main():
    params = parse_query(sys.argv[1:])
    query = params.get('query', '')
    count = int(params.get('count', params.get('max_results', 5)))
    engine = params.get('engine', 'baidu').lower()
    
    if not query:
        print("Usage: python search.py 'query' [count] or {'query': '...', 'engine': '...'}")
        sys.exit(1)
    
    try:
        if engine == 'baidu':
            results = call_baidu(query, count)
        elif engine == 'tavily':
            results = call_tavily(query, count)
        elif engine == 'brave':
            results = call_brave(query, count)
        elif engine == 'serper':
            results = call_serper(query, count)
        elif engine == 'exa':
            results = call_exa(query, count)
        elif engine == 'jina':
            results = call_jina_read(query, count)
        else:
            print(f"Unknown engine: {engine}")
            sys.exit(1)
        
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()