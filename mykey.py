import os

# ── 模型自动轮询配置（已启用，仅使用当前已验证可用模型）────────────────────

mixin_config = {
    'llm_nos': [
        'copilot-gpt4',              # 首选：已验证可用
        'copilot-claude',            # 兜底：已验证可用
        'copilot-gemini',            # 兜底：已验证可用
        'dashscope-glm-5',           # 兜底：已验证可用
    ],
    'max_retries': 4,              # 两模型间轮询重试，避免长时间无效重试
    'base_delay': 0.5,             # 指数退避起始延迟
}

# opencode-go-minimax-m2.5-free
native_oai_config_opencode_minimax = {
    'name': 'opencode-minimax',
    'apikey': os.environ.get('OPENCODE_API_KEY', ''),
    'apibase': 'https://opencode.ai/zen/v1',
    'model': 'minimax-m2.5-free',
    'api_mode': 'chat_completions',
    'proxy': None,
    'stream': True,
}

# opencode-go-big_pickle
native_oai_config_opencode_big_pickle = {
    'name': 'opencode-big-pickle',
    'apikey': os.environ.get('OPENCODE_API_KEY', ''),
    'apibase': 'https://opencode.ai/zen/v1',
    'model': 'big-pickle',
    'api_mode': 'chat_completions',
    'proxy': None,
    'stream': True,
}


# GLM-5 - DashScope 兼容模式 API（直连，不走代理）
native_oai_config_dashscope_glm_5 = {
    'name': 'dashscope-glm-5',
    'apikey': os.environ.get('DASHSCOPE_API_KEY', ''),
    'apibase': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'model': 'glm-5',
    'api_mode': 'chat_completions',
    'proxy': None,
    'stream': True,
}

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

# cliproxyapi Gemini3.1-Pro-Preview
native_oai_config_cliproxyapi_Gemini_3_1_Pro_Preview = {  
    'name': 'Gemini 3.1 Pro Preview',
    'apikey': 'hGlReGWt12IwLjqJMfBa3CPu4kMM6FcTZJOePGUUDtc=',
    'apibase': 'http://172.18.80.1:8317/v1',
    'model': 'gemini-3.1-pro-preview',
    'api_mode': 'chat_completions',
    'stream': True,
}

# cliproxyapi Gemini 3.1 Flash Lite Preview
native_oai_config_cliproxyapi_Gemini_3_1_Flash_Lite_Preview = {  
    'name': 'Gemini 3.1 Flash Lite Preview',
    'apikey': 'hGlReGWt12IwLjqJMfBa3CPu4kMM6FcTZJOePGUUDtc=',
    'apibase': 'http://172.18.80.1:8317/v1',
    'model': 'gemini-3.1-flash-lite-preview',
    'api_mode': 'chat_completions',
    'stream': True,
}

# cliproxyapi gemini-2.5-flash
native_oai_config_cliproxyapi_gemini_2_5_flash = {  
    'name': 'Gemini 2.5 Flash',
    'apikey': 'hGlReGWt12IwLjqJMfBa3CPu4kMM6FcTZJOePGUUDtc=',
    'apibase': 'http://172.18.80.1:8317/v1',
    'model': 'gemini-2.5-flash',
    'api_mode': 'chat_completions',
    'stream': True,
}

# cliproxyapi gemini 2.5 flash lite
native_oai_config_cliproxyapi_gemini_2_5_flash_lite = {  
    'name': 'gemini 2.5 flash lite',
    'apikey': 'hGlReGWt12IwLjqJMfBa3CPu4kMM6FcTZJOePGUUDtc=',
    'apibase': 'http://172.18.80.1:8317/v1',
    'model': 'gemini-2.5-flash-lite',
    'api_mode': 'chat_completions',
    'stream': True,
}

# cliproxyapi gemma 4 31b
native_oai_config_cliproxyapi_gemma_4_31b = {  
    'name': 'gemma 4 31b',
    'apikey': 'hGlReGWt12IwLjqJMfBa3CPu4kMM6FcTZJOePGUUDtc=',
    'apibase': 'http://172.18.80.1:8317/v1',
    'model': 'gemma-4-31b',
    'api_mode': 'chat_completions',
    'stream': True,
}

# cliproxyapi gemma 4 26b
native_oai_config_cliproxyapi_gemma_4_26b = {  
    'name': 'gemma 4 26b',
    'apikey': 'hGlReGWt12IwLjqJMfBa3CPu4kMM6FcTZJOePGUUDtc=',
    'apibase': 'http://172.18.80.1:8317/v1',
    'model': 'gemma-4-26b',
    'api_mode': 'chat_completions',
    'stream': True,
}

# ══════飞书配置══════════════════
fs_app_id = 'cli_a9671506d0b81cce'
fs_app_secret = 'oCFJoIYb0t4dOejN3nOkac7Q5V35E41o'
fs_allowed_users = ['*']