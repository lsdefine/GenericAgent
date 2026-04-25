# ── GitHub Copilot Pro (多模型配置) ─────────────────────────────────────
# 启动方式：先启动 litellm 代理（使用 .venv），然后在 UI 中选择模型
# .venv\Scripts\litellm.exe --config litellm_config.yaml --port 8000

# GPT-4 - 平衡性能与成本
native_oai_config_copilot_gpt4 = {  
    'name': 'copilot-gpt4',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-4',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Claude Sonnet 4.5 - 长上下文支持 (200K+)
native_oai_config_copilot_claude = {  
    'name': 'copilot-claude',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'claude-sonnet-4.5',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Gemini 2.5 Pro - 强多模态支持
native_oai_config_copilot_gemini = {  
    'name': 'copilot-gemini',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gemini-2.5-pro',
    'api_mode': 'chat_completions',
    'stream': True,
}

# ── 模型自动轮询配置（已启用，仅使用当前已验证可用模型）────────────────────
mixin_config = {
    'llm_nos': [
        'copilot-gpt4',            # 首选：已验证可用
        'copilot-claude',            # 兜底：已验证可用
        'copilot-gemini',            # 兜底：已验证可用
    ],
    'max_retries': 4,              # 两模型间轮询重试，避免长时间无效重试
    'base_delay': 0.5,             # 指数退避起始延迟
}
