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
#      含 'claude'（不含 native）          → ClaudeSession          → 文本协议工具 (deprecated)
#      含 'oai'（不含 native）             → LLMSession             → 文本协议工具 (deprecated)
#      含 'mixin'                          → MixinSession           → 多 session 故障转移
#                                                                      NativeClaudeSession 与
#                                                                      NativeOAISession 可混用
#
#  优先级自上而下：native_claude_xxx 会走 NativeClaudeSession；如果变量名只写
#  oai_claude_xxx 则依然会被 'claude' 抢先匹配，去走 ClaudeSession，所以命名要
#  注意含义。
#
#  ────────── Native vs 非 Native 的区别 ──────────
#
#  「Native」 = 工具调用走 API 文档里的 tool 字段（function calling）。
#  这是 Claude Code / Codex 的原生方式——训到 overfit 的模型只认 API tool 字段，
#  其他格式的工具描述都会被忽略。要模拟 CC/Codex 的行为，必须用 Native。
#
#  「非 Native」 = 工具描述放在 text 字段里（文本协议），兼容性更强，
#  但对于被 API tool 字段训 overfit 的模型（如 Claude Opus/Sonnet），效果可能打折。
#
#  → 新手推荐：优先用 native_claude_config / native_oai_config
#
#  ────────── Prompt Cache 说明 ──────────
#
#  NativeClaudeSession 恒开 prompt-caching-scope beta，缓存默认拉满，无需配置。
#  LLMSession / NativeOAISession 在 model 名含 'claude'/'anthropic' 时自动在
#  最后两条 user 打 cache_control: ephemeral，默认也是开启的。
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
#   context_win     默认 24000（NativeClaudeSession 默认 28000）。仅作为历史裁
#                   剪阈值，不是硬上下文限制。
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
#   api_mode        'chat_completions'（默认）或 'responses'。仅对 LLMSession /
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
#  引）。约束：引用的 session 必须全是 Native 系列（NativeClaudeSession 和
#  NativeOAISession 可以混用）或者全不是 Native，不能 Native 与非 Native 混。
#  请你按需
mixin_config = {
    'llm_nos': ['gpt-native'],   # 按优先级排列；Claude 与 GPT 混用
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
#     # 'context_win': 800000,                 # int 默认 28000（NativeClaudeSession）；历史裁剪阈值
#     # 'stream': True,                        # bool 默认 True；False → 一次性 JSON（CDN 截断 SSE 时用）
#     # 'max_retries': 3,                      # int 默认 1
#     # 'connect_timeout': 10,                 # int 秒 默认 5（最小 1）
#     # 'read_timeout': 180,                   # int 秒 默认 30（最小 5）
#     # 'fake_cc_system_prompt': False,        # bool 默认 False；真 Anthropic 端点不需开
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

# ── 1d. CRS Gemini Ultra (Antigravity 通道) ─────────────────────────────────
#  CRS 把 Google Antigravity (Gemini Ultra) 包装成 Anthropic 风格接口。
#  URL 路径带 /antigravity/api：
#    - 'claude-opus-4-7-thinking'  (CRS 原始名)
#    - 'claude-opus-4-7[1m]'       (触发 1m beta，CRS 会忽略多余的 beta)
#    - 'claude-opus-4-7'           (最简)
#  ⚠ 此通道不支持 SSE 流式，必须 stream=False。
# native_claude_config_crs_gemini = {
#     'name': 'crs-gemini-ultra',              # /llms 显示名
#     'apikey': 'cr_<your-crs-gemini-key>',    # cr_ 前缀 → Bearer
#     'apibase': 'https://<your-crs-gemini-host>/antigravity/api',
#     'model': 'claude-opus-4-7-thinking',     # 或 'claude-opus-4-7[1m]' 或 'claude-opus-4-7'
#     'stream': False,                         # Antigravity 不支持 SSE 流式，stream=True 会返回伪错误
#     'max_tokens': 32768,                     # int
#     'max_retries': 3,                        # int
#     'read_timeout': 180,                     # int 秒
# }

# ── 1e. 智谱 GLM-5.1 (Anthropic 兼容协议) ──────────────────────────────────
#  智谱提供了 Anthropic 兼容接口 /api/anthropic，走 NativeClaudeSession。
#  变量名含 'native' + 'claude' 即可。apikey 是智谱格式 (xxx.yyy)。
# native_claude_glm_config = {
#     'name': 'glm-5.1',                               # /llms 显示名
#     'apikey': '<your-zhipu-apikey>',                 # 形如 f0f1b798xxxx.F8SSbzxxxx；非 sk-ant- → Bearer
#     'apibase': 'https://open.bigmodel.cn/api/anthropic',  # 智谱 Anthropic 兼容端点
#     'model': 'glm-5.1',                              # 智谱 model id，无 [1m] 支持
#     'max_retries': 3,                                # int
#     'connect_timeout': 10,                           # int 秒
#     'read_timeout': 180,                             # int 秒
#     # 'fake_cc_system_prompt': False,                # 智谱不做 CC 指纹校验，保持默认 False
# }

# ── 1f. MiniMax Anthropic 路径（推荐——无额外 <think> 标签）────────────────
#  MiniMax 同时提供 OAI 和 Anthropic 兼容接口，同一个 key 两个端点都能用：
#    - /v1             → chat/completions (LLMSession)
#    - /anthropic      → Anthropic Messages (NativeClaudeSession)
#  Anthropic 路径更简洁，OAI 路径会返回 <think> 标签（M2.7 自带思考）。
#  温度自动修正为 (0, 1]，支持 M2.7 / M2.5 全系列，204K 上下文。
# native_claude_config_minimax = {
#     'name': 'minimax-anthropic',                   # /llms 显示名
#     'apikey': 'sk-<your-minimax-key>',             # 与 OAI 路径同一个 key
#     'apibase': 'https://api.minimaxi.com/anthropic',  # Anthropic Messages 兼容端点
#     'model': 'MiniMax-M2.7',
#     'max_retries': 3,                              # int
#     # 'fake_cc_system_prompt': False,              # MiniMax 不做 CC 指纹校验
# }


# ══════════════════════════════════════════════════════════════════════════════
#  2. NativeOAISession — OpenAI 协议 + 原生工具
# ══════════════════════════════════════════════════════════════════════════════
#  变量名含 'native' 且 'oai'。走 OpenAI chat/completions 或 responses 端点，
#  但工具调用使用 API 原生 function calling 字段（与 Claude Code/Codex 一致）。
#  适合 GPT/o 系列、Gemini 或任何 OAI 兼容且支持原生 tool 字段的模型。
#  和 NativeClaudeSession 共用大部分逻辑（继承关系），只是请求走 OAI 协议。

native_oai_config = {
    'name': 'gpt-native',                           # /llms 显示名 & mixin 引用名
    'apikey': 'sk-<your-openai-key>',                # Bearer 鉴权
    'apibase': 'https://api.openai.com/v1',          # 补齐到 /v1/chat/completions
    'model': 'gpt-5.4',                              # gpt-5/o 系列
    'api_mode': 'chat_completions',                  # 'chat_completions'（默认）|'responses'
    # 'reasoning_effort': 'high',                    # none|minimal|low|medium|high|xhigh
                                                     # chat_completions → payload.reasoning_effort
                                                     # responses        → payload.reasoning.effort
    'max_retries': 3,                                # int 默认 1
    'connect_timeout': 10,                           # int 秒 默认 5（最小 1）
    'read_timeout': 120,                             # int 秒 默认 30（最小 5）
    # 'temperature': 1.0,                            # float 默认 1.0
    # 'max_tokens': 8192,                            # int 默认 8192
    # 'proxy': 'http://127.0.0.1:2082',              # 可选单 session HTTP 代理
    # 'context_win': 16000,                          # int 默认 24000；历史裁剪阈值
}

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


# ══════════════════════════════════════════════════════════════════════════════
#  3. LLMSession / ClaudeSession — 非 Native 文本协议工具（deprecated）
# ══════════════════════════════════════════════════════════════════════════════
#  ⚠ 后续版本可能移除非 Native session。新用户请直接使用上面的 Native 配置。
#  非 Native 把工具描述放在 text 字段里，兼容性广但对 overfit 模型效果打折。
#  变量名含 'oai'（不含 native）→ LLMSession；含 'claude'（不含 native）→ ClaudeSession。
#
# oai_config = {
#     'name': 'my-oai-proxy',                          # /llms 显示名 & mixin 引用名
#     'apikey': 'sk-<your-proxy-key>',                 # Bearer 鉴权
#     'apibase': 'http://<your-proxy-host>:2001',      # 自动补 /v1/chat/completions
#     'model': 'gpt-5.4',                              # 或 claude-opus-4-7、gemini-3-flash 等
#     'api_mode': 'chat_completions',                  # 'chat_completions'（默认）|'responses'
#     # 'reasoning_effort': 'high',                    # none|minimal|low|medium|high|xhigh
#     'max_retries': 3,                                # int 默认 1
#     'connect_timeout': 10,                           # int 秒 默认 5（最小 1）
#     'read_timeout': 120,                             # int 秒 默认 30（最小 5）
#     # 'temperature': 1.0,                            # float 默认 1.0
#     # 'max_tokens': 8192,                            # int 默认 8192
#     # 'proxy': 'http://127.0.0.1:2082',              # 可选单 session HTTP 代理
#     # 'context_win': 16000,                          # int 默认 24000；历史裁剪阈值
# }
#
# # 多配几个也行，变量名含 'oai' 即可
# # oai_config2 = {
# #     'apikey': 'sk-...',
# #     'apibase': 'http://your-proxy:2001',
# #     'model': 'claude-opus-4-7',
# # }


# ══════════════════════════════════════════════════════════════════════════════
#  4. 其他 Native 兼容渠道
# ══════════════════════════════════════════════════════════════════════════════

# ── 4a. MiniMax OAI 路径 (/v1 chat/completions) ────────────────────────────
#  OAI 路径会返回 <think> 标签（M2.7 自带思考）；Anthropic 路径更简洁（见 1f）。
#  温度自动修正为 (0, 1]，支持 M2.7/M2.5 全系列，204K 上下文。
# oai_config_minimax = {
#     'name': 'minimax-oai',                           # /llms 显示名
#     'apikey': 'sk-<your-minimax-key>',               # 形如 sk-cp-xxxxxxxxx；Bearer 鉴权
#     'apibase': 'https://api.minimaxi.com/v1',        # OAI 兼容端点
#     'model': 'MiniMax-M2.7',                         # 名含 'minimax' → temp 夹到 (0.01,1.0]
#     'context_win': 50000,                            # int；MiniMax 204K 上下文，此处是裁剪阈值
# }


# ── 4b. Kimi / Moonshot (OAI 兼容) ──────────────────────────────────────────
#  注意：Kimi/Moonshot 温度会被 llmcore.py 强制改为 1.0，写什么都会被覆盖。
# oai_config_kimi = {
#     'name': 'kimi-k2',                             # /llms 显示名
#     'apikey': 'sk-<your-moonshot-key>',            # Bearer 鉴权
#     'apibase': 'https://api.moonshot.cn/v1',       # Moonshot OAI 端点
#     'model': 'kimi-k2-turbo-preview',              # 名含 'kimi' 或 'moonshot' → temperature 被强制 1.0
#     # 'temperature': 0.3,                          # ← 无效，会被 llmcore 覆盖为 1.0
#     # 'max_tokens': 8192,                          # int 默认 8192
# }


# ── 4c. OpenRouter (OAI 协议多模型中继) ─────────────────────────────────────
#  OpenRouter 是最通用的多模型 OAI 中继，https://openrouter.ai/api/v1。
#  model 名用 provider/model 格式（如 anthropic/claude-opus-4-7）。
# oai_config_openrouter = {
#     'name': 'openrouter-claude',                   # /llms 显示名 & mixin 引用名；省略则取 model
#     'apikey': 'sk-or-<your-openrouter-key>',       # OpenRouter key 形如 sk-or-xxx；Bearer 鉴权
#     'apibase': 'https://openrouter.ai/api/v1',     # 补齐到 /v1/chat/completions
#     'model': 'anthropic/claude-opus-4-7',          # provider/model 格式
#     'max_retries': 3,                              # int 默认 1
#     'connect_timeout': 10,                         # int 秒 默认 5（最小 1）
#     'read_timeout': 120,                           # int 秒 默认 30（最小 5）
# }


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
