#!/usr/bin/env python3
"""
AI Model Router & Fallback for GenericAgent
智能模型路由: 多LLM后端管理、自动降级、成本优化、请求路由
支持: OpenAI/Claude/Ollama/本地模型, 优先级链, 失败重试
"""

import os
import json
import time
import logging
import random
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class ModelConfig:
    name: str
    provider: str
    api_base: str
    api_key: str
    model_id: str
    max_tokens: int
    cost_per_1k: float
    priority: int
    timeout: int = 30
    enabled: bool = True

class ModelRouter:
    def __init__(self, config_file: str = "model_router_config.json"):
        self.models: List[ModelConfig] = []
        self.stats: Dict[str, Dict] = {}
        self.config_file = config_file
        self._load_config()
    
    def _load_config(self):
        if os.path.exists(self.config_file):
            with open(self.config_file) as f:
                data = json.load(f)
            for m in data.get('models', []):
                self.add_model(ModelConfig(**m))
    
    def add_model(self, config: ModelConfig):
        self.models.append(config)
        self.models.sort(key=lambda m: m.priority)
        self.stats[config.name] = {'requests': 0, 'failures': 0, 'tokens': 0, 'latency_ms': []}
    
    def select_model(self, task_type: str = None, budget: float = None) -> Optional[ModelConfig]:
        candidates = [m for m in self.models if m.enabled]
        if budget is not None:
            candidates = [m for m in candidates if m.cost_per_1k <= budget]
        return candidates[0] if candidates else None
    
    def route_request(self, messages: List[Dict], task_type: str = None, 
                      max_retries: int = 2, **kwargs) -> Dict:
        selected = self.select_model(task_type)
        if not selected:
            return {'error': 'No available model', 'status': 'failed'}
        
        for attempt in range(max_retries + 1):
            start = time.perf_counter()
            try:
                result = self._call_model(selected, messages, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                self._update_stats(selected.name, success=True, latency=elapsed, 
                                 tokens=result.get('usage', {}).get('total_tokens', 0))
                result['model_used'] = selected.name
                result['latency_ms'] = round(elapsed, 1)
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - start) * 1000
                self._update_stats(selected.name, success=False, latency=elapsed)
                logger.warning(f"Model {selected.name} failed (attempt {attempt+1}): {e}")
                if attempt < max_retries:
                    selected = self._get_fallback(selected)
                    if not selected:
                        break
                else:
                    return {'error': str(e), 'status': 'failed', 'model_used': selected.name}
        
        return {'error': 'All models exhausted', 'status': 'failed'}
    
    def _call_model(self, model: ModelConfig, messages: List[Dict], **kwargs) -> Dict:
        if model.provider == 'openai':
            return self._call_openai(model, messages, **kwargs)
        elif model.provider == 'ollama':
            return self._call_ollama(model, messages, **kwargs)
        else:
            return self._call_generic(model, messages, **kwargs)
    
    def _call_openai(self, model: ModelConfig, messages: List[Dict], **kwargs):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=model.api_key, base_url=model.api_base)
            resp = client.chat.completions.create(
                model=model.model_id, messages=messages, 
                max_tokens=model.max_tokens, **kwargs
            )
            return {
                'content': resp.choices[0].message.content,
                'usage': {'total_tokens': resp.usage.total_tokens} if resp.usage else {}
            }
        except ImportError:
            raise RuntimeError("openai package not installed")
    
    def _call_ollama(self, model: ModelConfig, messages: List[Dict], **kwargs):
        import requests
        resp = requests.post(f"{model.api_base}/api/chat", json={
            'model': model.model_id, 'messages': messages, 'stream': False
        }, timeout=model.timeout)
        resp.raise_for_status()
        data = resp.json()
        return {'content': data.get('message', {}).get('content', ''), 'usage': {}}
    
    def _call_generic(self, model: ModelConfig, messages: List[Dict], **kwargs):
        import requests
        resp = requests.post(f"{model.api_base}/v1/chat/completions", json={
            'model': model.model_id, 'messages': messages, **kwargs
        }, headers={'Authorization': f'Bearer {model.api_key}'}, timeout=model.timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data.get('choices', [{}])[0].get('message', {}).get('content', '')
        usage = data.get('usage', {})
        return {'content': content, 'usage': usage}
    
    def _get_fallback(self, current: ModelConfig) -> Optional[ModelConfig]:
        current_idx = self.models.index(current)
        for m in self.models[current_idx+1:]:
            if m.enabled:
                return m
        return None
    
    def _update_stats(self, name: str, success: bool, latency: float, tokens: int = 0):
        s = self.stats[name]
        s['requests'] += 1
        if not success:
            s['failures'] += 1
        s['tokens'] += tokens
        s['latency_ms'].append(round(latency, 1))
        if len(s['latency_ms']) > 100:
            s['latency_ms'] = s['latency_ms'][-100:]
    
    def get_stats(self) -> Dict:
        result = {}
        for name, s in self.stats.items():
            avg_lat = sum(s['latency_ms']) / len(s['latency_ms']) if s['latency_ms'] else 0
            result[name] = {
                'requests': s['requests'],
                'failures': s['failures'],
                'success_rate': round((s['requests'] - s['failures']) / max(s['requests'], 1) * 100, 1),
                'tokens': s['tokens'],
                'avg_latency_ms': round(avg_lat, 1)
            }
        return result
    
    def save_config(self):
        data = {'models': [m.__dict__ for m in self.models]}
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)

if __name__ == '__main__':
    router = ModelRouter()
    
    router.add_model(ModelConfig(
        name="mimo-primary", provider="openai",
        api_base="https://token-plan-cn.xiaomimimo.com/v1",
        api_key=os.getenv("MIMO_API_KEY", "demo"),
        model_id="mimo-v2", max_tokens=4096, cost_per_1k=0.01, priority=1
    ))
    router.add_model(ModelConfig(
        name="ollama-local", provider="ollama",
        api_base="http://localhost:11434",
        api_key="", model_id="llama3", max_tokens=2048, cost_per_1k=0.0, priority=2
    ))
    
    print("=== Router Stats ===")
    print(json.dumps(router.get_stats(), indent=2))
    
    print("\n=== Model Selection ===")
    selected = router.select_model()
    print(f"Selected: {selected.name if selected else 'None'}")
    
    router.save_config()
    print(f"\nConfig saved to model_router_config.json")
