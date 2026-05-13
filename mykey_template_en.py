# ══════════════════════════════════════════════════════════════════════════════
#  GenericAgent — mykey.py configuration template (copy to mykey.py and fill in)
# ══════════════════════════════════════════════════════════════════════════════
#
#  Quick start:
#    1. Copy this file to mykey.py
#    2. Uncomment one of the configs below and fill in your apikey
#    3. Run `python agentmain.py` or `python launch.pyw`
#
#  GA auto-detects any variable whose name contains 'api'/'config'/'cookie'
#  and picks the session class by keyword:
#      name contains 'native' + 'claude'  → NativeClaudeSession  (Anthropic API)
#      name contains 'native' + 'oai'     → NativeOAISession     (OpenAI API)
#      name contains 'copilot' + 'sdk'    → CopilotSDKSession    (github-copilot-sdk)
#      name contains 'mixin'              → MixinSession         (failover)
#
#  Native = tools go in the API's native `tool` field (function calling), same
#  way Claude Code and Codex do it. Recommended for GPT / Claude / Gemini.
#
#  Tip: runtime overrides via `/session.<attr>=<val>` in the REPL, e.g.
#      /session.reasoning_effort=high
#      /session.thinking_type=adaptive
#      /session.temperature=0.3
#
# ══════════════════════════════════════════════════════════════════════════════


# ── 1. NativeClaudeSession — Anthropic direct ────────────────────────────────
#  Official Anthropic endpoint. apikey starting with 'sk-ant-' is auto-sent
#  as x-api-key; any other prefix uses Authorization: Bearer.
#  Model suffix '[1m]' triggers the 1M-context beta (stripped before sending).
native_claude_config = {
    'name': 'claude',                         # display name & mixin reference
    'apikey': 'sk-ant-<your-anthropic-key>',
    'apibase': 'https://api.anthropic.com',
    'model': 'claude-opus-4-7[1m]',           # or 'claude-sonnet-4-6'
    'thinking_type': 'adaptive',              # 'adaptive' | 'enabled' | 'disabled'
    # 'thinking_budget_tokens': 32768,        # required if thinking_type='enabled'
    # 'max_retries': 3,
    # 'read_timeout': 180,
}


# ── 2. NativeOAISession — OpenAI direct ──────────────────────────────────────
#  Standard OpenAI chat/completions endpoint. Also works for any OpenAI-
#  compatible provider that supports native function-calling tool fields.
native_oai_config = {
    'name': 'gpt',                            # display name & mixin reference
    'apikey': 'sk-<your-openai-key>',
    'apibase': 'https://api.openai.com/v1',
    'model': 'gpt-5.4',                       # or 'o4', 'gpt-5.3-codex', etc.
    'api_mode': 'chat_completions',           # or 'responses' for /v1/responses
    # 'reasoning_effort': 'high',             # none|minimal|low|medium|high|xhigh
    # 'max_retries': 3,
    # 'read_timeout': 120,
}


# ── 2b. CopilotSDKSession — GitHub Copilot SDK (optional) ────────────────────
#  Requires: `pip install .[copilot-sdk]` (Python 3.11+)
#  Uses the official github-copilot-sdk runtime (Copilot CLI under the hood).
#  Can be referenced by name in mixin_config llm_nos (mixed with other non-Native sessions).
# copilot_sdk_config = {
#     'name': 'copilot-sdk',                        # display name & mixin reference name
#     'model': 'gpt-5',                             # any model available in Copilot
#     'github_token': 'ghp_<your_github_token>',    # optional if CLI login / GH_TOKEN / GITHUB_TOKEN is already available
#     # 'copilot_home': './temp/copilot_home',       # optional writable home dir
#     # 'cli_path': '/path/to/copilot',              # optional custom copilot CLI
#     # 'cli_args': ['--some-flag'],                 # optional extra flags passed to the Copilot CLI
#     # 'cli_log_level': 'debug',                   # optional CLI log level
#     # 'cli_log_to_console': True,                 # optional forward CLI stderr logs to this console
# }
#
#  Example: add CopilotSDKSession to a mixin failover pool (non-Native sessions only):
# mixin_copilot_config = {
#     'llm_nos': ['copilot-sdk', 'my-oai-proxy'],   # copilot first, fall back to oai on error
#     'max_retries': 3,
# }



# ── 3. Mixin failover (optional) ─────────────────────────────────────────────
#  List sessions by 'name'; if one fails, the next is tried automatically.
#  Constraint: all referenced sessions must be in the same group — either all
#  Native (NativeClaudeSession / NativeOAISession) or all non-Native
#  (LLMSession / ClaudeSession / CopilotSDKSession). Mixing groups is not supported.
# mixin_config = {
#     'llm_nos': ['claude', 'gpt'],
#     'max_retries': 5,
#     'base_delay': 0.5,
# }


# ── 4. Global HTTP proxy (optional) ──────────────────────────────────────────
#  Applies to every session that doesn't set its own 'proxy' field.
# proxy = 'http://127.0.0.1:7890'


# ── 5. Chat platform integrations (optional) ─────────────────────────────────
# tg_bot_token = '...'
# tg_allowed_users = [123456789]
