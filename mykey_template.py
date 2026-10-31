# GenericAgent 配置：复制为 mykey.py，下面两段选一段取消注释，填好三项即可。
# 按服务商的接口协议选择，不是按模型名字选择；第三方渠道换成它提供的地址。
# 填好后运行 python agentmain.py 或 python launch.pyw；桌面端也可直接「添加模型」。

# ── Claude / Anthropic 兼容接口 ──
# native_claude_config = {
#     'apibase': 'https://api.anthropic.com',  # API 地址
#     'apikey': '填你的 API Key',
#     'model': '填服务商提供的模型名',
# }
# Claude Code 透传渠道：在上面字典里加 'claude_compat': 'simple'（旧写法 'fake_cc_system_prompt': True 等价）；

# ── OpenAI 兼容接口（GPT、Gemini 等，取决于服务商）──
# native_oai_config = {
#     'apibase': 'https://api.openai.com/v1',  # API 地址
#     'apikey': '填你的 API Key',
#     'model': '填服务商提供的模型名',
# }
# 如果服务商要求 Responses 接口：在上面字典里加 'api_mode': 'responses',

# ===== 到这里就可以用了。以下均可跳过，需要时再加。=====

# ── 高级选项：把需要的行复制到上面的配置字典里，去掉开头的 # ──
# 以下数值只是示例，不是默认值；未填写的选项由程序处理。
#     'name': '主力模型',                 # 显示名；不填则用 model
#     'proxy': 'http://127.0.0.1:7890',   # 此模型的 HTTP 代理
#     'read_timeout': 180,              # 读取超时（秒）
#     'timeout': 10,                    # 连接超时（秒）
#     'max_retries': 3,                 # 请求重试次数
#     'context_win': 100000,            # 历史裁剪参考窗口，非模型硬上限
#     'max_tokens': 32768,              # 最大输出 token 数
#     'temperature': 1.0,              # 仅在模型支持时设置
#     'stream': False,                  # 渠道不支持流式时使用
#     'reasoning_effort': 'high',       # 推理强度，取值依模型而定
#     'thinking_type': 'adaptive',      # Claude 思考：adaptive / enabled / disabled
#     'thinking_budget_tokens': 32768,  # thinking_type='enabled' 时需要
#     'claude_compat': 'half',          # 需要 Claude Code 请求格式/指纹校验的透传渠道（simple=仅身份行，half=含 CC 主提示）
#     'api_key_header': 'x-api-key',    # Claude 鉴权头不匹配时指定；也支持 bearer
#     'api_mode': 'responses',          # OAI：默认 chat_completions，按渠道要求修改
# 运行中也可临时调整，例如：/session.reasoning_effort=high

# ── 多模型 / 自动故障转移 ──
# 复制配置块，变量名保留 native_claude_config / native_oai_config 前缀，加 1、2 等区分。
# 每个模型设置不同的 name；下面按 name 排优先级，先启用对应模型再启用此组。
# mixin_config = {
#     'llm_nos': ['主力模型', '备用模型'],
#     'max_retries': 5,
#     'base_delay': 0.5,
# }

# ── 聊天平台（可选；在文件末尾取消对应行的注释，不要放进模型字典）──
# 只启用需要的平台，并将 allowed_users 改成自己的用户 ID。
# tg_bot_token = '填 Telegram Bot Token'
# tg_allowed_users = [123456789]
# qq_app_id, qq_app_secret = '填 App ID', '填 App Secret'
# qq_allowed_users = ['填用户 OpenID']
# fs_app_id, fs_app_secret = '填 App ID', '填 App Secret'
# fs_allowed_users = ['填用户 OpenID']
# wecom_bot_id, wecom_secret = '填 Bot ID', '填 Secret'
# wecom_allowed_users = ['填用户 ID']
# dingtalk_client_id, dingtalk_client_secret = '填 App Key', '填 App Secret'
# dingtalk_allowed_users = ['填员工 ID']

# Langfuse 追踪（可选，同样放在模型字典外）
# langfuse_config = {'public_key': 'pk-lf-...', 'secret_key': 'sk-lf-...', 'host': 'https://cloud.langfuse.com'}
