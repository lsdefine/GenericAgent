# ══════════════════════════════════════════════════════════════════════════════
#  GenericAgent — mykey.py 配置模板（复制为 mykey.py 后填入真实凭证）
# ══════════════════════════════════════════════════════════════════════════════
#
#  ┌─────────────────────────────────────────────────────────────────────────┐
#  │ 快速上手：只需 3 步                                                      │
#  │  1. 把本文件复制为 mykey.py                                              │
#  │  2. 在下面的"推荐最优配置"区域填入你的 apikey                              │
#  │  3. 运行 python agentmain.py / python launch.pyw                        │
#  └─────────────────────────────────────────────────────────────────────────┘
#
#  ────────── Session 类型速查 ──────────
#
#  agentmain.py 只扫描变量名同时包含 'api' / 'config' / 'cookie' 的条目，
#  根据变量名里的关键字决定实例化哪个 Session 类型：
#
#      变量名关键字                          → Session 类             → 工具协议
#      ─────────────────────────────────────────────────────────────────────────
#      含 'native' 且 'claude'             → NativeClaudeSession    → API 原生 tool 字段
#      含 'native' 且 'oai'               → NativeOAISession       → API 原生 tool 字段
#      含 'mixin'                          → MixinSession           → 多 session 故障转移
#                                                                      NativeClaudeSession 与
#                                                                      NativeOAISession 可混用
#
#  工具调用一律走 API 原生 tool 字段（function calling），与 Claude Code /
#  Codex 行为一致。Anthropic 协议渠道用 native_claude_*，OpenAI 兼容渠道用
#  native_oai_*，按上游端点协议选择即可。
#
#  ────────── Prompt Cache 说明 ──────────
#
#  NativeClaudeSession 恒开 prompt-caching-scope beta，缓存默认拉满，无需配置。
#  NativeOAISession 在 model 名含 'claude'/'anthropic' 时自动在最后两条 user
#  打 cache_control: ephemeral，默认也是开启的。
#  prompt_cache 字段默认 True，仅在上游 relay 不认 cache_control 字段会直接报错
#  时才需设 False。因此模板中不再显式写 prompt_cache，了解即可。
#
# ══════════════════════════════════════════════════════════════════════════════
#  apibase 自动拼接规则：
#      'http://host:2001'                      → 补 /v1/chat/completions
#      'http://host:2001/v1'                   → 补 /chat/completions
#      'http://host:2001/v1/chat/completions'  → 原样使用
#  NativeClaudeSession 会额外附加 ?beta=true，用于触发 Anthropic beta 协议。
#
# ══════════════════════════════════════════════════════════════════════════════
#  运行时参数调整：在 GA REPL 里输入
#      /session.reasoning_effort=high
#      /session.thinking_type=adaptive
#      /session.thinking_budget_tokens=32768
#      /session.temperature=0.3
#      /session.max_tokens=16384
#  会在当前 session 的 backend 上做 setattr，当场生效，直到换模型或重启。
#  reasoning_effort 合法值: none / minimal / low / medium / high / xhigh
#  thinking_type 合法值:     adaptive / enabled / disabled
#
# ══════════════════════════════════════════════════════════════════════════════
#  所有字段速查（按 BaseSession.__init__ 顺序）
# ─── 鉴权 / 路由 ─────────────────────────────────────────────────────────────
#   apikey          必填。sk-ant-* 用 x-api-key 头；其它（sk-*, cr_*, amp_*…）
#                   一律用 Authorization: Bearer，由 NativeClaudeSession 自动判断。
#   apibase         必填。参见上方 apibase 自动拼接规则。
#   model           必填。后缀 '[1m]' 触发 context-1m-2025-08-07 beta（发出前会
#                   自动去掉 [1m]）。
#   name            可选。展示名；也是 mixin_config['llm_nos'] 引用的凭据。不填
#                   默认取 model。
#   proxy           可选。单 session 代理，'http://127.0.0.1:2082' 这种。不填则
#                   即使全局设置了 proxy 也不走。
# ─── 容量 / 超时 ─────────────────────────────────────────────────────────────
#   context_win     默认 30000（DeepSeek 默认 70000）。用于历史裁剪，并联动
#                   压缩频率和工具结果上限；不是硬上下文限制。
#   trim_keep_prefix 默认 0。硬删时保留最前 K 条，切点插 "..." 并剥尾部 tool_use。不影响 tag 压缩。
#   max_retries     默认 1。_openai_stream 遇到 429/408/5xx 的自动重试次数。
#   connect_timeout 连接超时秒数，默认 5。
#   read_timeout    流式读取超时秒数，默认 30。
# ─── 推理 / 思考 ─────────────────────────────────────────────────────────────
#   reasoning_effort  OpenAI o 系列或 Responses API 的思考预算等级。Claude 侧
#                     会映射到 output_config.effort（xhigh → max）。
#   thinking_type     Claude 原生 thinking 块。
#                     'adaptive'  (CC 默认)   → 让模型自己决定预算
#                     'enabled'                → 必须配合 thinking_budget_tokens
#                     'disabled'               → 不发送 thinking 字段
#   thinking_budget_tokens  仅当 thinking_type='enabled' 时生效。参考:
#                     low≈4096, medium≈10240, high≈32768
# ─── 采样 ──────────────────────────────────────────────────────────────────
#   temperature     默认 1.0。Kimi/Moonshot 会被强制改成 1.0；MiniMax 会被夹到
#                   (0, 1]。
#   max_tokens      默认 8192。
# ─── 传输 ──────────────────────────────────────────────────────────────────
#   stream          默认 True。NativeClaudeSession 会根据此值决定走 SSE 流式
#                   还是一次性 JSON。流式更及时；某些被 CDN 截断 SSE 的渠道可
#                   以改成 False 先保命。
#   api_mode        'chat_completions'（默认）或 'responses'。仅对
#                   NativeOAISession 生效。
# ─── NativeClaudeSession 专属 ───────────────────────────────────────────────
#   fake_cc_system_prompt
#                   默认 False。关键字段：**所有反代/镜像 Claude Code 协议的渠道
#                   都必须置 True**（CC switch、anyrouter、claude-relay-service
#                   等）。真 Anthropic 端点（sk-ant-）不需要开。
#   user_agent      默认 'claude-cli/2.1.113 (external, cli)'。可传入任意版本号
#                   字符串覆盖。某些第三方中转（tabcode、anyrouter 等）会按 UA
#                   白名单校验，CC 升版本后被拒可在此 pin 老版本绕过。
# ══════════════════════════════════════════════════════════════════════════════



# ╔═══════════════════════════════════════════════════════════════════════════╗
# ║                     ★ 推荐最优配置（新手从这里开始）★                      ║
# ╚═══════════════════════════════════════════════════════════════════════════╝
#
#  推荐使用 mixin 故障转移 + 多个 native session 的方式。
#  mixin 会按 llm_nos 列表顺序尝试，第一个失败自动切下一个，非常省心。
#  填好下面的 apikey/apibase 后即可使用。


# ── Mixin 故障转移（最推荐的方式）──────────────────────────────────────────
#  llm_nos 里的字符串必须和被引用 session 的 'name' 字段匹配（也可以写整数索
#  引）。NativeClaudeSession 和 NativeOAISession 可以混用。
mixin_config = {
    'llm_nos': [],               # 默认空：桌面端会显示一个空的「渠道组（自动故障转移）」，添加模型后
                                 # 在设置里用 ➕ 把基本模型加进来即可（也可在此手填名字）
    # 'llm_nos': ['cc-relay-1', 'cc-relay-2', 'gpt-native'],  # 按优先级排列；Claude 与 GPT 混用，注意: 启用时需要启用'cc-relay-1', 'cc-relay-2'配置!
    'max_retries': 10,           # int；整个 rotation 的总重试次数上限
    'base_delay': 0.5,           # float 秒；指数退避起始延迟（retry n 时延迟≈base_delay * 2^n）
    # 'spring_back': 300,        # int 秒；切到备用节点后多久再尝试回到第一个节点
}



# ══════════════════════════════════════════════════════════════════════════════
#  1. NativeClaudeSession — Anthropic 原生协议 + 原生工具（推荐首选）
# ══════════════════════════════════════════════════════════════════════════════
#
#  大部分用户使用的是 CC switch 适配的 Claude 透传渠道（非官方直连），这类渠道
#  把 Claude Code 的请求透传到上游，需要 fake_cc_system_prompt=True。
#  这是目前社区最常见的接入方式。

# ── 1a. CC switch 适配渠道（最常用）────────────────────────────────────────
#  这类渠道把 Claude Code 协议透传到上游，apikey 格式各异（sk-user-*, sk-*, cr_*
#  等），统一走 Bearer 鉴权。必须设置 fake_cc_system_prompt=True。
# native_claude_config0 = {
#     'name': 'cc-relay-1',                        # /llms 显示名 & mixin 引用名
#     'apikey': 'sk-user-<your-relay-key>',        # 非 sk-ant- 前缀 → Bearer 鉴权
#     'apibase': 'https://<your-cc-switch-host>/claude/office',   # CC switch 端点
#     'model': 'claude-opus-4-7',                  # 或 claude-sonnet-4-6
#     'fake_cc_system_prompt': True,               # CC 透传渠道必须置 True
#     'thinking_type': 'adaptive',                 # 某些渠道必须要求填写thinking_type字段
# }

# native_claude_config1 = {
#     'name': 'cc-relay-2',                        # /llms 显示名 & mixin 引用名
#     'apikey': 'sk-<your-second-relay-key>',
#     'apibase': 'https://<your-second-host>',
#     'model': 'claude-opus-4-7[1m]',              # [1m] 触发 1m 上下文 beta
#     'fake_cc_system_prompt': True,
#     'thinking_type': 'adaptive',                 # 某些渠道必须要求填写thinking_type字段
#     'max_retries': 3,
#     'read_timeout': 300,                         # 1m 上下文响应可能较慢
#     'stream': False,                             # 某些渠道不支持 SSE 流式时改 False
#     # 'user_agent': 'claude-cli/2.1.113 (external, cli)',
# }
# ── 1b. Anthropic 官方直连 ──────────────────────────────────────────────────
#  官方端点，apikey 以 sk-ant- 开头 → 自动切到 x-api-key 鉴权。
#  真 Anthropic 端点不需要 fake_cc_system_prompt。
# native_claude_config_anthropic = {
#     'name': 'anthropic-direct',              # /llms 显示名 & mixin 引用名
#     'apikey': 'sk-ant-<your-anthropic-key>', # sk-ant- 前缀 → 自动走 x-api-key 头
#     'apibase': 'https://api.anthropic.com',  # NativeClaudeSession 自动附加 ?beta=true
#     'model': 'claude-opus-4-7[1m]',          # [1m] 触发 1m 上下文 beta
#     # ── 思考控制（thinking_type 与 reasoning_effort 独立，可同时写）──
#     'thinking_type': 'adaptive',             # 合法值: 'adaptive' / 'enabled' / 'disabled'
#                                              #   adaptive = Claude Code 默认，模型自决预算
#                                              #   enabled  = 必须配 thinking_budget_tokens
#                                              #   disabled = 发送 {"type":"disabled"}
#     # 'thinking_type': 'enabled',
#     # 'thinking_budget_tokens': 32768,       # int，仅 thinking_type='enabled' 生效
#                                              #   参考: low≈4096 / medium≈10240 / high≈32768
#     # ── 推理等级（Claude 侧写进 payload.output_config.effort）──
#     #   合法值: 'none' / 'minimal' / 'low' / 'medium' / 'high' / 'xhigh'
#     #   映射:  low/medium/high 原值传递；xhigh → 'max'；
#     #          none/minimal 被 llmcore 打 WARN 丢弃（Claude 不支持这两档）
#     #   运行时可覆盖: REPL 输入 /session.reasoning_effort=high 当场生效
#     # 'reasoning_effort': 'high',
#     'temperature': 1,                        # float 默认 1.0
#     'max_tokens': 32768,                     # int 默认 8192；Claude 回复最大 token 数
#     # 'context_win': 800000,                 # int 默认 30000；历史裁剪及工具上限参考
#     # 'stream': True,                        # bool 默认 True；False → 一次性 JSON（CDN 截断 SSE 时用）
#     # 'max_retries': 3,                      # int 默认 1
#     # 'connect_timeout': 10,                 # int 秒 默认 5（最小 1）
#     # 'read_timeout': 180,                   # int 秒 默认 30（最小 5）
#     # 'fake_cc_system_prompt': False,        # bool 默认 False；真 Anthropic 端点不需开
# }

# ── 1b′. Anthropic Messages 端点 + 手动指定鉴权头（api_key_header）──────────────
#  某些中转渠道（如 opencode.ai）提供 Anthropic /v1/messages 端点，但 apikey 非
#  sk-ant- 前缀。NativeClaudeSession 对非 sk-ant- 的 key 默认发 Authorization: Bearer；
#  若目标端点只接受 x-api-key（如 opencode.ai 的 /v1/messages 只认 x-api-key，
#  Bearer 会返回 401 Missing API key），用 api_key_header 手动强制鉴权头。
#  api_key_header 合法值: 'auto'（默认，按 sk-ant- 前缀自动判断）
#                        / 'x-api-key'（强制 x-api-key 头）
#                        / 'bearer'（强制 Authorization: Bearer 头）
# native_claude_config_opencode = {
#     'name': 'opencode-deepseek-native',
#     'apikey': '<your-key>',                  # 非 sk-ant- 前缀
#     'apibase': 'https://opencode.ai/zen/go/v1',
#     'model': 'deepseek-v4-flash',
#     'api_key_header': 'x-api-key',           # ← 强制 x-api-key（否则 auto 发 Bearer→401）
#     'thinking_type': 'adaptive',
#     'reasoning_effort': 'low',
#     'max_retries': 5,
#     'read_timeout': 180,
# }

# ── 1c. CRS 反代 Claude Max ─────────────────────────────────────────────────
#  CRS 需要 fake_cc_system_prompt=True
# native_claude_config_crs = {
#     'name': 'crs-claude-max',                # /llms 显示名
#     'apikey': 'cr_<your-crs-key>',           # cr_ 开头 → Bearer 鉴权（64 位 hex）
#     'apibase': 'https://<your-crs-host>/api',# CRS 的 Anthropic 兼容路径
#     'model': 'claude-opus-4-7[1m]',          # [1m] 触发 1m beta
#     'fake_cc_system_prompt': True,           # bool 必填 True；CRS 也校验 CC 系统串
#     'thinking_type': 'adaptive',             # 'adaptive'/'enabled'/'disabled'
#     # 'reasoning_effort': 'high',            # 可选；写进 output_config.effort
#     'max_tokens': 32768,                     # int；CRS 允许大 max_tokens
#     'max_retries': 3,                        # int
#     'read_timeout': 180,                     # int 秒
# }


# ── 1d. 其他 Anthropic 兼容渠道（GLM / Kimi / MiniMax 等）───────────────────
#  很多厂商都提供 Anthropic Messages 兼容端点，直接照 1a~1c 的写法填对应
#  apibase / model 即可，无需专门配置：
#
#      厂商        apibase                                     model              备注
#      ──────────────────────────────────────────────────────────────────────────────
#      智谱 GLM    https://open.bigmodel.cn/api/anthropic      glm-5.1            key 形如 xxx.yyy
#      Kimi Coding https://api.kimi.com/coding                 kimi-for-coding    必须 fake_cc_system_prompt=True
#      MiniMax     https://api.minimaxi.com/anthropic          MiniMax-M3         温度自动夹到 (0,1]
#
# native_claude_config_vendor = {
#     'name': 'glm-5.1',                       # /llms 显示名 & mixin 引用名
#     'apikey': '<your-vendor-apikey>',        # 非 sk-ant- 前缀 → Bearer 鉴权
#     'apibase': 'https://open.bigmodel.cn/api/anthropic',
#     'model': 'glm-5.1',
#     # 'fake_cc_system_prompt': True,         # 仅 CC 透传类端点需要（如 Kimi Coding）
#     'max_retries': 3,                        # int
#     'read_timeout': 180,                     # int 秒
# }

# ══════════════════════════════════════════════════════════════════════════════
#  2. NativeOAISession — OpenAI 协议 + 原生工具
# ══════════════════════════════════════════════════════════════════════════════
#  变量名含 'native' 且 'oai'。走 OpenAI chat/completions 或 responses 端点，
#  但工具调用使用 API 原生 function calling 字段（与 Claude Code/Codex 一致）。
#  适合 GPT/o 系列、Gemini 或任何 OAI 兼容且支持原生 tool 字段的模型。
#  和 NativeClaudeSession 共用大部分逻辑（继承关系），只是请求走 OAI 协议。

# 默认整段注释：新装时「独立模型」列表为空。在桌面端「添加模型」填好 apikey 后会
# 自动生成同类 native_oai_config 变量；或取消下面注释手动填。
# native_oai_config = {
#     'name': 'gpt-native',                           # /llms 显示名 & mixin 引用名
#     'apikey': 'sk-<your-openai-key>',                # Bearer 鉴权
#     'apibase': 'https://api.openai.com/v1',          # 补齐到 /v1/chat/completions
#     'model': 'gpt-5.4',                              # gpt-5/o 系列
#     'api_mode': 'chat_completions',                  # 'chat_completions'（默认）|'responses'
#     # 'reasoning_effort': 'high',                    # none|minimal|low|medium|high|xhigh
#                                                      # chat_completions → payload.reasoning_effort
#                                                      # responses        → payload.reasoning.effort
#     'max_retries': 3,                                # int 默认 1
#     'connect_timeout': 10,                           # int 秒 默认 5（最小 1）
#     'read_timeout': 120,                             # int 秒 默认 30（最小 5）
#     # 'temperature': 1.0,                            # float 默认 1.0
#     # 'max_tokens': 8192,                            # int 默认 8192
#     # 'proxy': 'http://127.0.0.1:2082',              # 可选单 session HTTP 代理
#     # 'context_win': 16000,                          # int 默认 30000；历史裁剪及工具上限参考
# }

# ── 也可以走 Responses API ──────────────────────────────────────────────────
#  对接 OpenAI /v1/responses 端点。reasoning_effort 会以 reasoning.effort
#  字段写进 payload；运行时也可用 /session.reasoning_effort=high 现场调。
# native_oai_config_responses = {
#     'name': 'gpt-responses',                       # /llms 显示名
#     'apikey': 'sk-<your-openai-key>',              # Bearer 鉴权
#     'apibase': 'https://api.openai.com/v1',        # 补齐到 /v1/responses（因为 api_mode=responses）
#     'model': 'gpt-5.4',                            # gpt-5/o 系列
#     'api_mode': 'responses',                       # 改走 /v1/responses 端点
#     'reasoning_effort': 'high',                    # none|minimal|low|medium|high|xhigh
#                                                    # responses 模式下写进 payload.reasoning.effort
#     'max_retries': 2,                              # int 默认 1
#     'read_timeout': 120,                           # int 秒 默认 30
# }


# ── 其他 OAI 兼容渠道 ──────────────────────────────────────────────────────
#  Moonshot/Kimi、MiniMax、OpenRouter、智谱等的 OAI 端点同样照上面写法填即可：
#
#      厂商        apibase                           model                        备注
#      ──────────────────────────────────────────────────────────────────────────────
#      Moonshot    https://api.moonshot.cn/v1        kimi-k2-turbo-preview        温度被强制 1.0
#      MiniMax     https://api.minimaxi.com/v1       MiniMax-M3                   回复带 <think> 标签，
#                                                                                 建议改用 Anthropic 路径(1d)
#      OpenRouter  https://openrouter.ai/api/v1      anthropic/claude-opus-4-7    provider/model 格式


# ══════════════════════════════════════════════════════════════════════════════
#  全局 HTTP 代理（所有没有单独指定 proxy 的 session 共用）
# ══════════════════════════════════════════════════════════════════════════════
# proxy = 'http://127.0.0.1:2082'


# ══════════════════════════════════════════════════════════════════════════════
#  聊天平台集成（可选；未填写的平台不会启动对应 adapter）
# ══════════════════════════════════════════════════════════════════════════════
# tg_bot_token = '84102K2gYZ...'
# tg_allowed_users = [6806...]
# qq_app_id = '123456789'
# qq_app_secret = 'xxxxxxxxxxxxxxxx'
# qq_allowed_users = ['your_user_openid']           # 留空或 ['*'] 表示允许所有 QQ 用户
# fs_app_id = 'cli_xxxxxxxxxxxxxxxx'
# fs_app_secret = 'xxxxxxxxxxxxxxxx'
# fs_allowed_users = ['ou_xxxxxxxxxxxxxxxx']        # 留空或 ['*'] 表示允许所有飞书用户
# wecom_bot_id = 'your_bot_id'
# wecom_secret = 'your_bot_secret'
# wecom_allowed_users = ['your_user_id']            # 留空或 ['*'] 表示允许所有企业微信用户
# wecom_welcome_message = '你好，我在线上。'
# dingtalk_client_id = 'your_app_key'
# dingtalk_client_secret = 'your_app_secret'
# dingtalk_allowed_users = ['your_staff_id']        # 留空或 ['*'] 表示允许所有钉钉用户

# 可选：Langfuse 追踪。不设此项则不 import langfuse，零影响
# langfuse_config = {
#     'public_key': 'pk-lf-...',
#     'secret_key': 'sk-lf-...',
#     'host': 'https://cloud.langfuse.com',   # 或自托管地址
# }
