"""
llm_helper.py — 大模型调用统一接口（零外部依赖 + LLM 响应缓存）

渐进增强设计：
  - LLM 可用时（环境变量 SKILL_LLM_ENABLE=1 + LLM_API_BASE 可达）
  - 不可用时自动降级，不影响流程
  - 自动缓存 LLM 响应到磁盘，相同 prompt 不重复调用

环境变量：
  SKILL_LLM_ENABLE=1       启用 LLM 增强
  LLM_API_BASE             兼容 OpenAI Chat API 的端点（默认 http://localhost:11434/v1）
  LLM_API_KEY              可选 API Key
  LLM_MODEL                模型名（默认 qwen2.5:7b）
  LLM_TIMEOUT              HTTP 超时秒数（默认 30）
  LLM_CACHE_DIR            缓存目录（默认 {GA_ROOT}/.llm_cache）
  LLM_CACHE_TTL            缓存有效期秒数（默认 86400=1天）
"""

import json
import os
import urllib.request
import urllib.error
import sys
import hashlib
import time
from pathlib import Path

# ── 环境变量获取（仅读一次） ──
_ENABLED = os.environ.get("SKILL_LLM_ENABLE", "0") == "1"
_API_BASE = os.environ.get("LLM_API_BASE", "http://localhost:11434/v1").rstrip("/")
_API_KEY = os.environ.get("LLM_API_KEY", "")
_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")
_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "30"))

# ── 缓存配置 ──
_CACHE_ENABLED = os.environ.get("LLM_CACHE_ENABLE", "1") == "1"
_CACHE_TTL = int(os.environ.get("LLM_CACHE_TTL", "86400"))  # 默认1天
_GA_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", str(_GA_ROOT / ".llm_cache")))

# 可用性缓存
_availability = None


def _get_cache_key(prompt: str, system_prompt: str) -> str:
    """生成缓存键（prompt + system_prompt 的 SHA256 前 24 位）"""
    raw = f"{_MODEL}||{system_prompt}||{prompt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _load_cache(cache_key: str) -> str | None:
    """从磁盘加载缓存（过期返回 None）"""
    if not _CACHE_ENABLED:
        return None
    cache_file = _CACHE_DIR / cache_key
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if time.time() - data["ts"] > _CACHE_TTL:
            cache_file.unlink(missing_ok=True)
            return None
        return data["response"]
    except Exception:
        return None


def _save_cache(cache_key: str, response: str):
    """保存响应到磁盘缓存"""
    if not _CACHE_ENABLED or not response:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = _CACHE_DIR / cache_key
        cache_file.write_text(
            json.dumps({"ts": time.time(), "response": response}, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass


def llm_available() -> bool:
    """检查 LLM 是否可用（连接测试 + 环境变量开关）"""
    global _availability
    if _availability is not None:
        return _availability

    if not _ENABLED:
        print("  [LLM] SKIP: SKILL_LLM_ENABLE 未设置或不为 1")
        _availability = False
        return False

    # 快速连接测试
    try:
        test_url = f"{_API_BASE}/models"
        req = urllib.request.Request(test_url, method="GET")
        if _API_KEY:
            req.add_header("Authorization", f"Bearer {_API_KEY}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            _availability = resp.status == 200
            if _availability:
                print(f"  [LLM] OK: {_API_BASE}")
            else:
                print(f"  [LLM] FAIL: 端点返回状态码 {resp.status}")
            return _availability
    except Exception as e:
        print(f"  [LLM] FAIL: 连接 {_API_BASE} 失败 — {e}")
        _availability = False
        return False


def call_llm(
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant.",
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """
    调用 LLM（OpenAI 兼容 API），返回文本响应。
    自动缓存相同 prompt 的响应到磁盘。
    """
    if not llm_available():
        return ""

    # 低温度时启用缓存（高温度每次都新鲜调用）
    use_cache = _CACHE_ENABLED and temperature <= 0.3
    if use_cache:
        cache_key = _get_cache_key(prompt, system_prompt)
        cached = _load_cache(cache_key)
        if cached is not None:
            return cached

    payload = {
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    body = json.dumps(payload).encode("utf-8")
    url = f"{_API_BASE}/chat/completions"

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if _API_KEY:
        req.add_header("Authorization", f"Bearer {_API_KEY}")

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            content = content.strip()
            # 缓存非空响应（低温度才缓存）
            if use_cache and content:
                _save_cache(cache_key, content)
            return content
    except urllib.error.HTTPError as e:
        print(f"  [LLM] HTTP {e.code}: {e.read().decode('utf-8', errors='replace')[:200]}")
    except Exception as e:
        print(f"  [LLM] 调用失败: {e}")

    return ""


def call_llm_json(
    prompt: str,
    system_prompt: str = "You are a helpful AI assistant. Always output valid JSON.",
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> dict | list | None:
    """
    调用 LLM 并解析 JSON 响应。

    返回:
        解析后的 Python 对象（dict/list），失败或非 JSON 时返回 None
    """
    text = call_llm(prompt, system_prompt, temperature, max_tokens)
    if not text:
        return None

    # 尝试提取 JSON 块（处理 LLM 可能在 markdown 代码块中返回的情况）
    import re

    # 先找 ```json ... ``` 块
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if json_match:
        text = json_match.group(1).strip()

    # 再找 ``` ... ``` 块（不带标签）
    if not json_match:
        json_match = re.search(r"```\s*([\s\S]*?)\s*```", text)
        if json_match:
            text = json_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [LLM] JSON 解析失败: {e}")
        print(f"  [LLM] 原始响应前 200 字符: {text[:200]}")
        return None


def clear_cache():
    """清除所有 LLM 缓存"""
    if _CACHE_DIR.exists():
        import shutil
        shutil.rmtree(_CACHE_DIR)
        print(f"  [LLM] 缓存已清除: {_CACHE_DIR}")
