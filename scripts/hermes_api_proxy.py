#!/usr/bin/env python3
"""Hermes API 代理 — 为 nanobot serve 补全缺失端点。

添加:
  - /v1/embeddings (基于hash的确定性嵌入)
  - /v1/completions (提示词→Chat包装代理)
  - 其余端点透传至 nanobot serve

直连模式 (--direct):
  - 绕过 nanobot，直接调用自定义 provider (8.208.28.70:20128)
  - 支持 fast model (gemini-3-flash-preview 等)
  - 首次响应 <3s

用法:
  python scripts/hermes_api_proxy.py [--port 8901] [--target http://127.0.0.1:8900]
  python scripts/hermes_api_proxy.py --direct [--port 8902] [--direct-base-url <url>] [--direct-api-key <key>]
"""

import sys, os, json, hashlib, math, asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

BASE = Path(__file__).resolve().parent.parent

app = FastAPI(title="Hermes API Proxy", version="0.2.0")
TARGET = "http://127.0.0.1:8900"
DIRECT_MODE = False
DIRECT_BASE = "http://8.208.28.70:20128/v1"
DIRECT_API_KEY = ""
client: httpx.AsyncClient = None

# ── 工具函数 ──────────────────────────────────────────────

def _hash_embedding(text: str, dim: int = 384) -> List[float]:
    """基于字符哈希确定性地生成固定维度嵌入向量。"""
    vec = [0.0] * dim
    for i, ch in enumerate(text):
        h = hashlib.md5(f"{i}:{ch}".encode()).digest()
        for j in range(min(len(h), dim)):
            vec[j % dim] += (h[j] / 255.0) * 2 - 1
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec[:dim]

# ── 端点 ──────────────────────────────────────────────────

@app.post("/v1/embeddings")
async def embeddings(request: Request):
    """生成文本嵌入向量。"""
    body = await request.json()
    model = body.get("model", "hermes")
    inputs = body.get("input", body.get("inputs", ""))
    if isinstance(inputs, str):
        inputs = [inputs]

    data = []
    for idx, text in enumerate(inputs):
        embedding = _hash_embedding(text)
        data.append({
            "object": "embedding",
            "index": idx,
            "embedding": embedding
        })

    return {
        "object": "list",
        "data": data,
        "model": model,
        "usage": {
            "prompt_tokens": sum(len(t) for t in inputs),
            "total_tokens": sum(len(t) for t in inputs)
        }
    }

@app.post("/v1/completions")
async def completions(request: Request):
    """Text completions — 包装为Chat对话并代理。"""
    body = await request.json()
    prompt = body.get("prompt", "")
    model = body.get("model", "hermes")
    max_tokens = body.get("max_tokens", 256)
    temperature = body.get("temperature", 0.7)
    stream = body.get("stream", False)

    messages = [{"role": "user", "content": prompt}]
    chat_body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream
    }

    async def proxy_stream():
        async with httpx.AsyncClient(timeout=120) as c:
            async with c.stream("POST", f"{TARGET}/v1/chat/completions", json=chat_body) as resp:
                async for chunk in resp.aiter_lines():
                    if chunk:
                        yield chunk + "\n"

    if stream:
        return StreamingResponse(proxy_stream(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=120) as c:
            resp = await c.post(f"{TARGET}/v1/chat/completions", json=chat_body)
            chat_resp = resp.json()
            text = chat_resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "id": chat_resp.get("id", ""),
                "object": "text_completion",
                "created": chat_resp.get("created", 0),
                "model": model,
                "choices": [{
                    "text": text,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": chat_resp.get("choices", [{}])[0].get("finish_reason", "stop")
                }],
                "usage": chat_resp.get("usage", {})
            }

# ── 透传代理 ──────────────────────────────────────────────

async def _get_headers(request: Request) -> dict:
    """构建代理请求头。直连模式注入API Key。"""
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    if DIRECT_MODE and DIRECT_API_KEY:
        headers["Authorization"] = f"Bearer {DIRECT_API_KEY}"
    return headers

async def _proxy_request(request: Request, path: str):
    """代理请求到目标服务器。（透传模式 → TARGET / 直连模式 → DIRECT_BASE）"""
    body = await request.body()
    headers = await _get_headers(request)

    base = DIRECT_BASE if DIRECT_MODE else TARGET
    url = f"{base}{path}"
    params = dict(request.query_params)

    # 直连模式：拼接API key到请求头（已由_get_headers处理）

    # 流式响应处理
    if headers.get("accept") == "text/event-stream" or (
        body and b'"stream":true' in body
    ):
        async def _stream():
            async with httpx.AsyncClient(timeout=120) as c:
                async with c.stream(
                    request.method, url,
                    content=body, headers=headers, params=params
                ) as resp:
                    async for chunk in resp.aiter_lines():
                        if chunk:
                            yield chunk + "\n"
        return StreamingResponse(_stream(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=120) as c:
        resp = await c.request(
            request.method, url,
            content=body, headers=headers, params=params
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers)
        )

@app.api_route("/v1/chat/completions", methods=["GET", "POST", "OPTIONS"])
async def proxy_chat(request: Request):
    return await _proxy_request(request, "/v1/chat/completions")

@app.api_route("/v1/models", methods=["GET", "OPTIONS"])
async def proxy_models(request: Request):
    return await _proxy_request(request, "/v1/models")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
async def proxy_catchall(request: Request, path: str):
    return await _proxy_request(request, f"/{path}")

# ── 入口 ──────────────────────────────────────────────────

def _read_api_key_from_config() -> str:
    """从 nanobot config.json 读取 API key。"""
    config_path = Path.home() / ".nanobot" / "config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            return cfg.get("providers", {}).get("9router", {}).get("apiKey", "")
        except Exception:
            pass
    return ""

def main():
    global TARGET, DIRECT_MODE, DIRECT_BASE, DIRECT_API_KEY
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8901

    # 直连模式
    if "--direct" in sys.argv:
        DIRECT_MODE = True
        if "--direct-base-url" in sys.argv:
            DIRECT_BASE = sys.argv[sys.argv.index("--direct-base-url") + 1]
        if "--direct-api-key" in sys.argv:
            DIRECT_API_KEY = sys.argv[sys.argv.index("--direct-api-key") + 1]
        else:
            DIRECT_API_KEY = _read_api_key_from_config()
        if not DIRECT_API_KEY:
            print("⚠️  未提供 API Key (--direct-api-key)，直连模式可能需要它")

    # 透传模式目标
    if not DIRECT_MODE and "--target" in sys.argv:
        TARGET = sys.argv[sys.argv.index("--target") + 1]

    mode_str = "🔗 直连 Provider" if DIRECT_MODE else f"⏩ 透传 → {TARGET}"
    print(f"🚀 Hermes API Proxy v0.2.0 | {mode_str} | 监听 :{port}")
    print(f"   ✅ /v1/models → {'直连' if DIRECT_MODE else '透传'}")
    print(f"   ✅ /v1/chat/completions → {'直连（含流式）' if DIRECT_MODE else '透传（含流式）'}")
    print(f"   🆕 /v1/embeddings → 基于hash生成384维向量")
    print(f"   🆕 /v1/completions → 提示词→Chat代理")
    if DIRECT_MODE:
        print(f"   📡 目标: {DIRECT_BASE}")
        print(f"   🔑 API Key: {'已配置' if DIRECT_API_KEY else '⚠️ 未配置'}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

if __name__ == "__main__":
    main()
