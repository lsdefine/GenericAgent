import os

# ── 模型自动轮询配置（已启用，仅使用当前已验证可用模型）────────────────────

mixin_config = {
    'llm_nos': [
        'opencode-minimax',
        'copilot-gpt4',          
        'copilot-claude',           
        'copilot-gemini', 
        'opencode-big-pickle',        
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


# ══════飞书配置══════════════════
fs_app_id = 'cli_a9671506d0b81cce'
fs_app_secret = 'oCFJoIYb0t4dOejN3nOkac7Q5V35E41o'
fs_allowed_users = ['*']