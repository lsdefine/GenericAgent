import os

import requests


def _api_key():
    key = os.environ.get("TINYFISH_API_KEY", "").strip()
    if key: return key
    try:
        import mykey
    except ImportError:
        return ""
    return str(getattr(mykey, "tinyfish_api_key", "") or getattr(mykey, "tinyfish_apikey", "")).strip()


def search(query, location="US", language="en", page=0, max_results=10):
    key = _api_key()
    if not key:
        return {"status": "error", "msg": "TinyFish API key missing. Set TINYFISH_API_KEY or tinyfish_api_key in mykey.py."}
    params = {"query": query, "page": int(page or 0)}
    if location: params["location"] = location
    if language: params["language"] = language
    resp = requests.get("https://api.search.tinyfish.ai", headers={"X-API-Key": key}, params=params, timeout=30)
    if resp.status_code >= 400:
        return {"status": "error", "http_status": resp.status_code, "msg": resp.text[:1000]}
    data = resp.json()
    data["results"] = data.get("results", [])[:max(1, min(int(max_results or 10), 20))]
    return {"status": "success", **data}
