import os

# ── 模型自动轮询配置（已启用，仅使用当前已验证可用模型）────────────────────

mixin_config = {
    'llm_nos': [
        'opencode-minimax',
        'copilot-gpt4',
        'copilot-gemini',
        'opencode-big-pickle',
        'copilot-claude',
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

# GPT-5.4 - 当前可用最高版本
native_oai_config_copilot_gpt4 = {  
    'name': 'copilot-gpt4',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-5.4',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Claude Sonnet 4.6 - 当前可用最高 Sonnet 版本
native_oai_config_copilot_claude = {  
    'name': 'copilot-claude',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'claude-sonnet-4.6',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Gemini 3.1 Pro Preview - 当前可用最高版本
native_oai_config_copilot_gemini = {  
    'name': 'copilot-gemini',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gemini-3.1-pro-preview',
    'api_mode': 'chat_completions',
    'stream': True,
}















# ══════飞书配置══════════════════
fs_app_id = 'cli_a9671506d0b81cce'
fs_app_secret = 'oCFJoIYb0t4dOejN3nOkac7Q5V35E41o'
fs_allowed_users = ['*']