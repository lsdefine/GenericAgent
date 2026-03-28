
# ══════════════════════════════════════════════════════════════════════════════
# apibase 填写规则（自动拼接端点路径）：
#   填到端口        'http://host:2001'                → 自动补 /v1/chat/completions
#   填到版本号      'http://host:2001/v1'             → 自动补 /chat/completions
#   填完整路径      'http://host:2001/v1/chat/completions'  → 直接使用，不再拼接
# ══════════════════════════════════════════════════════════════════════════════

# ── Mixin (实验性) ───────────────────────────────────────────────────────────────
# key命名含 'mixin' 触发 MixinSession：多key/endpoint自动fallback + 指数退避重试
# 约束：引用的session须同类型，不支持Native
# mixin_config = {'llm_nos': [1, 2], 'max_retries': 3, 'base_delay': 1.5}  # 序号含自身（此处mixin=0）

# ── OpenAI-compatible (chat/completions or responses API) ──────────────────────
# key命名含 'oai' 触发 LLMSession
oai_config = {
    'apikey': 'sk-...',
    'apibase': 'http://your-proxy:2001',
    'model': 'openai/gpt-5.1',
    'api_mode': 'chat_completions',  # 'chat_completions' | 'responses'
    # 'reasoning_effort': 'low',     # none|low|medium|high|xhigh (OpenAI o系列)
    # 'prompt_cache': False,
    'max_retries': 2,                # 429/timeout/5xx 重试次数
    'connect_timeout': 10,           # 秒
    'read_timeout': 120,             # 秒（流式读取）
    # 'proxy': 'http://127.0.0.1:2082',  # 单独代理，不填则不走代理
    # 'context_win': 16000,          # token估算上限，超出自动截断历史
}

# 可以定义多个，命名含 'oai' 即可
oai_config2 = {
    'apikey': 'sk-...',
    'apibase': 'http://your-proxy:2001',
    'model': 'claude-opus-4-6-20260206',
}

# ── Claude via OpenAI-compatible proxy ─────────────────────────────────────────
# key命名含 'claude'（不含'native'）触发 ClaudeSession（走OpenAI兼容层）
claude_config = {
    'apikey': 'sk-...',
    'apibase': 'http://your-proxy:2001',
    'model': 'claude-opus',
    # 'context_win': 12000,
    # 'prompt_cache': False,
}

# ── Claude Native API ───────────────────────────────────────────────────────────
# key命名同时含 'native' 和 'claude' 触发 NativeClaudeSession
# 原生工具调用格式，缓解弱模型指令遵循问题，但更耗token
native_claude_config = {
    'apikey': 'sk-ant-...',          # Anthropic原生apikey
    'apibase': 'https://api.anthropic.com',
    'model': 'claude-opus-4-5',
    # 'context_win': 24000,
}

# ── OpenAI-compatible Native API ─────────────────────────────────────────────
# key命名同时含 'native' 和 'oai' 触发 NativeOAISession
# 原生工具调用格式，缓解弱模型指令遵循问题，但更耗token
native_oai_config = {
    'apikey': 'sk-...',
    'apibase': 'http://your-proxy:2001',
    'model': 'gpt-4o',
    # 'context_win': 24000,
}

# ── Sider ───────────────────────────────────────────────────────────────────────
# key命名含 'sider' 触发 SiderLLMSession（需安装 sider_ai_api 包）
#sider_cookie = 'token=Bearer%20eyJhbGciOiJIUz...'


# If you need them
# tg_bot_token = '84102K2gYZ...'
# tg_allowed_users = [6806...]
# qq_app_id = '123456789'
# qq_app_secret = 'xxxxxxxxxxxxxxxx'
# qq_allowed_users = ['your_user_openid']  # 留空或 ['*'] 表示允许所有 QQ 用户
# fs_app_id = 'cli_xxxxxxxxxxxxxxxx'
# fs_app_secret = 'xxxxxxxxxxxxxxxx'
# fs_allowed_users = ['ou_xxxxxxxxxxxxxxxx']  # 留空或 ['*'] 表示允许所有飞书用户
# wecom_bot_id = 'your_bot_id'
# wecom_secret = 'your_bot_secret'
# wecom_allowed_users = ['your_user_id']  # 留空或 ['*'] 表示允许所有企业微信用户
# wecom_welcome_message = '你好，我在线上。'
# dingtalk_client_id = 'your_app_key'
# dingtalk_client_secret = 'your_app_secret'
# dingtalk_allowed_users = ['your_staff_id']  # 留空或 ['*'] 表示允许所有钉钉用户

# proxy = "http://127.0.0.1:2082"
