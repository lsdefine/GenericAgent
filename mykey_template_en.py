# GenericAgent: copy to mykey.py, uncomment ONE block below, and fill in its three fields.
# Choose by the provider's API protocol, not the model name; use your provider's URL.
# Run python agentmain.py or python launch.pyw. Desktop users can also use "Add model".

# ── Claude / Anthropic-compatible API ──
# native_claude_config = {
#     'apibase': 'https://api.anthropic.com',  # API URL
#     'apikey': 'YOUR_API_KEY',
#     'model': 'YOUR_PROVIDER_MODEL_ID',
# }
# For Claude Code relays, add 'claude_compat': 'simple' (legacy 'fake_cc_system_prompt': True maps to simple).

# ── OpenAI-compatible API (GPT, Gemini, etc., depending on the provider) ──
# native_oai_config = {
#     'apibase': 'https://api.openai.com/v1',  # API URL
#     'apikey': 'YOUR_API_KEY',
#     'model': 'YOUR_PROVIDER_MODEL_ID',
# }
# If your provider requires Responses, add 'api_mode': 'responses', inside the dict above.

# ===== Ready to go. Everything below is optional. =====

# ── Advanced options: copy needed lines INSIDE your config dict and remove the leading # ──
# Values below are examples, not defaults. Omitted options are handled by the program.
#     'name': 'primary',                 # Display name; defaults to model
#     'proxy': 'http://127.0.0.1:7890',   # HTTP proxy for this model
#     'read_timeout': 180,              # Read timeout in seconds
#     'timeout': 10,                    # Connection timeout in seconds
#     'max_retries': 3,                 # Request retries
#     'context_win': 100000,            # History trimming window, not a hard model limit
#     'max_tokens': 32768,              # Maximum output tokens
#     'temperature': 1.0,              # Set only if the model supports it
#     'stream': False,                  # For providers that do not support streaming
#     'reasoning_effort': 'high',       # Reasoning level; supported values vary by model
#     'thinking_type': 'adaptive',      # Claude thinking: adaptive / enabled / disabled
#     'thinking_budget_tokens': 32768,  # Required when thinking_type='enabled'
#     'claude_compat': 'half',          # Relays requiring CC request format/fingerprint (simple=identity only, half=+CC main prompt)
#     'api_key_header': 'x-api-key',    # Override Claude auth header; also supports bearer
#     'api_mode': 'responses',          # OAI: default is chat_completions; follow provider docs
# Temporary runtime overrides also work, e.g. /session.reasoning_effort=high

# ── Multiple models / automatic failover ──
# Copy a config block; keep the native_claude_config / native_oai_config prefix and add 1, 2, etc.
# Give each model a unique name. Enable the referenced models before enabling this group.
# mixin_config = {
#     'llm_nos': ['primary', 'backup'],  # Model names in priority order
#     'max_retries': 5,
#     'base_delay': 0.5,
# }

# ── Chat platforms (optional; uncomment at file level, NOT inside a model dict) ──
# Enable only the platforms you need, and replace allowed_users with your own user IDs.
# tg_bot_token = 'YOUR_TELEGRAM_BOT_TOKEN'
# tg_allowed_users = [123456789]
# qq_app_id, qq_app_secret = 'YOUR_APP_ID', 'YOUR_APP_SECRET'
# qq_allowed_users = ['YOUR_USER_OPENID']
# fs_app_id, fs_app_secret = 'YOUR_APP_ID', 'YOUR_APP_SECRET'
# fs_allowed_users = ['YOUR_USER_OPENID']
# wecom_bot_id, wecom_secret = 'YOUR_BOT_ID', 'YOUR_SECRET'
# wecom_allowed_users = ['YOUR_USER_ID']
# dingtalk_client_id, dingtalk_client_secret = 'YOUR_APP_KEY', 'YOUR_APP_SECRET'
# dingtalk_allowed_users = ['YOUR_STAFF_ID']

# Langfuse tracing (optional; also outside the model dict)
# langfuse_config = {'public_key': 'pk-lf-...', 'secret_key': 'sk-lf-...', 'host': 'https://cloud.langfuse.com'}
