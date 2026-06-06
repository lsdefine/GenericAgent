#!/usr/bin/env python3
"""
Hermes API Wrapper — OpenLLM Gateway HTTP API 客户端
=====================================================
直接通过 HTTP 访问 OpenLLM (Hermes Gateway) 的 OpenAI 兼容 API。
端口: 11343 | 基础 URL: http://127.0.0.1:11343

用法:
    from hermes_api_wrapper import HermesAPI
    
    api = HermesAPI()
    api.health()                          # 健康检查
    api.list_models()                     # 列出所有模型
    api.chat("deepseek/deepseek-v4-flash", "Hello!")  # 简单对话
    api.chat_stream(...)                  # 流式对话 (generator)

安装: 无需 pip, 仅依赖标准库
"""

import json
import urllib.request
import urllib.error
from typing import Generator, Optional


class HermesAPIError(Exception):
    """Hermes API 调用异常"""
    pass


class HermesAPI:
    """Hermes Gateway API 客户端"""

    def __init__(self, base_url: str = "http://127.0.0.1:11343", timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        """底层 HTTP 请求"""
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise HermesAPIError(f"HTTP {e.code}: {e.read().decode()[:200]}")
        except urllib.error.URLError as e:
            raise HermesAPIError(f"连接失败: {e.reason}")
        except json.JSONDecodeError as e:
            raise HermesAPIError(f"JSON 解析失败: {e}")

    # ── 公开 API ──

    def health(self) -> dict:
        """健康检查 — GET /health"""
        return self._request('GET', '/health')

    def list_models(self) -> list:
        """列出所有可用模型 — GET /v1/models
        
        Returns:
            list[dict]: 模型列表, 每项包含 id / object / owned_by
        """
        result = self._request('GET', '/v1/models')
        return result.get('data', [])

    def chat(self, model: str, message: str, system: Optional[str] = None,
             max_tokens: int = 1024, temperature: float = 0.7) -> str:
        """对话 — POST /v1/chat/completions (非流式)
        
        Args:
            model: 模型 ID, 如 'deepseek/deepseek-v4-flash'
            message: 用户消息
            system: 可选的系统提示
            max_tokens: 最大输出 token 数
            temperature: 采样温度
            
        Returns:
            str: 模型回复文本
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        result = self._request('POST', '/v1/chat/completions', payload)
        try:
            return result['choices'][0]['message']['content']
        except (KeyError, IndexError) as e:
            raise HermesAPIError(f"响应格式异常: {e} | 原始: {json.dumps(result)[:200]}")

    def chat_stream(self, model: str, message: str, system: Optional[str] = None,
                    max_tokens: int = 1024, temperature: float = 0.7) -> Generator[str, None, None]:
        """对话 — POST /v1/chat/completions (流式, generator)
        
        Args:
            同上
            
        Yields:
            str: 每个 chunk 的 delta 文本
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        body = json.dumps(payload).encode()
        url = f"{self.base_url}/v1/chat/completions"
        req = urllib.request.Request(url, data=body, headers=self._headers, method='POST')

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                buffer = ""
                while True:
                    chunk = resp.read(1).decode('utf-8', errors='replace')
                    if not chunk:
                        break
                    buffer += chunk
                    if buffer.endswith('\n'):
                        line = buffer.strip()
                        buffer = ""
                        if line.startswith('data: '):
                            data_str = line[6:]
                            if data_str == '[DONE]':
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data.get('choices', [{}])[0].get('delta', {})
                                content = delta.get('content', '')
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                pass
        except urllib.error.HTTPError as e:
            raise HermesAPIError(f"HTTP {e.code}: {e.read().decode()[:200]}")
        except urllib.error.URLError as e:
            raise HermesAPIError(f"连接失败: {e.reason}")

    def multi_turn_chat(self, model: str, messages: list, **kwargs) -> str:
        """多轮对话 — 直接传入完整的 messages 列表
        
        Args:
            model: 模型 ID
            messages: [{"role": "user/assistant", "content": "..."}, ...]
            
        Returns:
            str: 模型回复
        """
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get('max_tokens', 1024),
            "temperature": kwargs.get('temperature', 0.7),
        }
        result = self._request('POST', '/v1/chat/completions', payload)
        try:
            return result['choices'][0]['message']['content']
        except (KeyError, IndexError) as e:
            raise HermesAPIError(f"响应格式异常: {e}")


# ── CLI 入口 ──
if __name__ == '__main__':
    import sys
    api = HermesAPI()

    if len(sys.argv) < 2:
        print("用法: python hermes_api_wrapper.py <command> [args...]")
        print("命令: health | models | chat <模型> <消息>")
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        if cmd == 'health':
            print(json.dumps(api.health(), indent=2, ensure_ascii=False))
        elif cmd == 'models':
            models = api.list_models()
            print(f"共 {len(models)} 个模型:\n")
            for m in models:
                print(f"  {m['id']} (provider: {m.get('owned_by', '?')})")
        elif cmd == 'chat' and len(sys.argv) >= 4:
            reply = api.chat(sys.argv[2], sys.argv[3])
            print(reply)
        elif cmd == 'chat-stream' and len(sys.argv) >= 4:
            for chunk in api.chat_stream(sys.argv[2], sys.argv[3]):
                print(chunk, end='', flush=True)
            print()
        else:
            print(f"未知命令: {cmd}")
    except HermesAPIError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
