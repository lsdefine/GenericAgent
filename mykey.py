import os

# ── 模型自动轮询配置 ──────────────────────────────────────────────────────────
# 轮询顺序按额度成本排列：0x免费 → 0.33x低廉 → 1x标准 → 外部兜底
# Copilot Pro 每月 300 premium requests，0x模型不消耗配额可无限使用

# mixin_config = {
#     'llm_nos': [
#         # 0x 免费（不消耗 premium requests）
#         'copilot-free',        # GPT-5 mini，快速通用
#         'opencode-minimax',
#         'copilot-free-gpt41',  # GPT-4.1，稳定通用
#         'copilot-free-gpt4o',  # GPT-4o，多模态备用
#         # 0.33x 低成本
#         'copilot-haiku',       # Claude Haiku 4.5，轻量任务
#         'copilot-flash',       # Gemini 3 Flash，轻量任务
#         # 1x 标准（用于复杂任务，受自动路由优先调度）
#         'copilot-gpt4',        # GPT-5.4，代码任务首选
#         'copilot-claude',      # Claude Sonnet 4.6，长上下文/推理首选
#         'copilot-gemini',      # Gemini 3.1 Pro，多模态首选
#         'copilot-gpt52',
#         'copilot-gemini25',
#         # 外部兜底
#         'opencode-big-pickle',
#     ],
#     'max_retries': 4,
#     'base_delay': 0.5,
# }

# ── 外部模型（OpenCode） ──────────────────────────────────────────────────────

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

# ── Copilot 免费模型（0x，不消耗 premium requests）────────────────────────────

# GPT-5 mini - 0x 免费，速度快，适合常规任务
native_oai_config_copilot_free = {
    'name': 'copilot-free',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-5-mini',
    'api_mode': 'chat_completions',
    'stream': True,
}

# GPT-4.1 - 0x 免费，稳定通用，适合默认任务
native_oai_config_copilot_free_gpt41 = {
    'name': 'copilot-free-gpt41',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-4.1',
    'api_mode': 'chat_completions',
    'stream': True,
}

# GPT-4o - 0x 免费，多模态能力，免费层备选
native_oai_config_copilot_free_gpt4o = {
    'name': 'copilot-free-gpt4o',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-4o',
    'api_mode': 'chat_completions',
    'stream': True,
}

# ── Copilot 低成本模型（0.33x）────────────────────────────────────────────────

# Claude Haiku 4.5 - 0.33x，轻量 Claude，适合 fast 路由
native_oai_config_copilot_haiku = {
    'name': 'copilot-haiku',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'claude-haiku-4.5',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Gemini 3 Flash - 0.33x，轻量 Gemini，适合 fast 路由
native_oai_config_copilot_flash = {
    'name': 'copilot-flash',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gemini-3-flash-preview',
    'api_mode': 'chat_completions',
    'stream': True,
}

# ── Copilot 标准模型（1x，消耗 premium requests）──────────────────────────────

# GPT-5.4 - 1x，顶级代码模型，coding 路由首选
native_oai_config_copilot_gpt4 = {
    'name': 'copilot-gpt4',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-5.4',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Claude Sonnet 4.6 - 1x，长上下文/推理首选
native_oai_config_copilot_claude = {
    'name': 'copilot-claude',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'claude-sonnet-4.6',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Gemini 3.1 Pro Preview - 1x，多模态旗舰
native_oai_config_copilot_gemini = {
    'name': 'copilot-gemini',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gemini-3.1-pro-preview',
    'api_mode': 'chat_completions',
    'stream': True,
}

# GPT-5.2 - 1x，备用 OpenAI 标准模型
native_oai_config_copilot_gpt52 = {
    'name': 'copilot-gpt52',
    'apikey': 'anything',
    'apibase': 'http://localhost:8000/v1',
    'model': 'gpt-5.2',
    'api_mode': 'chat_completions',
    'stream': True,
}

# Gemini 2.5 Pro - 1x，备用 Gemini 标准模型
native_oai_config_copilot_gemini25 = {
    'name': 'copilot-gemini25',
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