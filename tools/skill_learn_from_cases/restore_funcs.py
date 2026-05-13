"""
restore_funcs.py — 从原 engine.py 恢复缺失的核心函数

这些函数在 engine.py 的文件损坏修复过程中丢失，独立成模块避免再次损坏。
"""

import sys
import os
import json
import subprocess
import importlib
from pathlib import Path

GA_ROOT = Path(__file__).resolve().parents[2]


def _import_skill_search():
    """延迟导入 skill_search，失败时降级"""
    try:
        from skill_search import search
        return search
    except Exception:
        return None


def _import_web_search():
    """导入搜索引擎模块（优先级：环境变量 → metaso_search 自动发现 → Wikipedia fallback）"""
    # 1. 环境变量显式指定（最高优先级）
    module_name = os.environ.get("SEARCH_ENGINE_MODULE")
    func_name = os.environ.get("SEARCH_ENGINE_FUNC", "search")
    if module_name:
        try:
            mod = importlib.import_module(module_name)
            return getattr(mod, func_name)
        except Exception:
            pass

    # 2. 自动尝试 metaso_search
    for try_module, try_func in [
        ("memory.metaso_search", "metaso_search"),
        ("memory.metaso_search", "metaso_search_text"),
    ]:
        try:
            mod = importlib.import_module(try_module)
            fn = getattr(mod, try_func, None)
            if fn:
                return fn
        except Exception:
            continue

    # 3. Wikipedia fallback
    return _web_search_wikipedia


def _web_search_wikipedia(keyword: str, size: int = 5) -> list[dict]:
    """Wikipedia API 搜索 fallback"""
    import urllib.request as _ur, urllib.parse as _up
    try:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": keyword,
            "format": "json",
            "srlimit": min(size, 10),
        }
        url = f"https://en.wikipedia.org/w/api.php?{_up.urlencode(params)}"
        req = _ur.Request(url, headers={"User-Agent": "skill_learn/1.0"})
        with _ur.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for item in data.get("query", {}).get("search", []):
            title = item.get("title", "")
            snippet = item.get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
            page_url = f"https://en.wikipedia.org/wiki/{_up.quote(title.replace(' ', '_'))}"
            results.append({
                "title": title,
                "url": page_url,
                "snippet": snippet[:300],
                "score": "medium"
            })
        return results
    except Exception:
        return []
