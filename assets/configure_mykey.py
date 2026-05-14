#!/usr/bin/env python3
"""
GenericAgent — 交互式初始化向导 (configure.py)
一键配置 LLM 模型 + 消息平台，自动生成 mykey.py

用法:
    python configure.py
"""

import os
import sys
import re
import shutil
import json
import urllib.request
from datetime import datetime

# ── ANSI 颜色 ──────────────────────────────────────────────────────────────
C = {
    'reset': '\033[0m', 'bold': '\033[1m', 'dim': '\033[2m',
    'red': '\033[91m', 'green': '\033[92m', 'yellow': '\033[93m',
    'blue': '\033[94m', 'magenta': '\033[95m', 'cyan': '\033[96m', 'white': '\033[97m',
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MYKPY_PATH = os.path.join(PROJECT_ROOT, 'mykey.py')

# ── 模型厂商定义 ───────────────────────────────────────────────────────────

LLM_PROVIDERS = [
    # ═══════════════════════════ 直连 API（按旗舰能力降序）═══════════════════════════
    {
        'id': 'anthropic',
        'name': 'Anthropic Claude 官方直连',
        'desc': 'Claude Opus #1 最强模型，原生 tool 协议，sk-ant- 开头',
        'type': 'native_claude',
        'template': {
            'name': 'anthropic-direct', 'apikey': 'sk-ant-<your-anthropic-key>',
            'apibase': 'https://api.anthropic.com', 'model': 'claude-opus-4-7',
            'thinking_type': 'adaptive', 'max_tokens': 32768, 'temperature': 1,
        },
        'key_hint': '在 https://console.anthropic.com/ 获取',
        'model_choices': ['claude-opus-4-7', 'claude-sonnet-4-6'],
    },
    {
        'id': 'openai',
        'name': 'OpenAI GPT-5.5 / o 系列',
        'desc': 'GPT-5.5 旗舰，与 Claude Opus 同级',
        'type': 'native_oai',
        'template': {
            'name': 'gpt-native', 'apikey': 'sk-<your-openai-key>',
            'apibase': 'https://api.openai.com/v1', 'model': 'gpt-5.5',
            'api_mode': 'chat_completions', 'reasoning_effort': 'high',
            'max_retries': 3, 'connect_timeout': 10, 'read_timeout': 120,
        },
        'key_hint': '在 https://platform.openai.com/api-keys 获取',
        'model_choices': ['gpt-5.5', 'gpt-5.4'],
    },
    {
        'id': 'deepseek',
        'name': 'DeepSeek (v4-Pro / Flash)',
        'desc': '最强开源模型，v4-Pro 旗舰 1M 上下文',
        'type': 'native_oai',
        'template': {
            'name': 'deepseek', 'apikey': 'sk-<your-deepseek-key>',
            'apibase': 'https://api.deepseek.com', 'model': 'deepseek-v4-flash',
            'api_mode': 'chat_completions', 'reasoning_effort': 'high',
        },
        'key_hint': '在 https://platform.deepseek.com/api_keys 获取',
        'model_choices': ['deepseek-v4-pro', 'deepseek-v4-flash'],
    },
    {
        'id': 'kimi',
        'name': 'Kimi (k2.6 / k2.5) 双协议',
        'desc': '月之暗面，国内顶尖，支持 Anthropic 和 OAI 双协议',
        'type': 'native_claude',
        'template': {
            'name': 'kimi', 'apikey': 'sk-kimi-<your-key>',
            'apibase': 'https://api.kimi.com/coding',
            'model': 'kimi-for-coding', 'fake_cc_system_prompt': True,
            'thinking_type': 'adaptive',
        },
        'key_hint': '在 https://kimi.com/code 或 https://platform.moonshot.cn/ 获取',
        'model_choices': ['kimi-k2.6', 'kimi-k2.5'],
        'extra_fields': [
            {
                'key': '_protocol', 'label': '选择 API 协议',
                'type': 'choice',
                'options': [
                    {'id': 'native_claude', 'name': 'Anthropic 兼容 (推荐)', 'desc': 'kimi-for-coding 端点，CC 兼容', 'apibase': 'https://api.kimi.com/coding', 'fake_cc_system_prompt': True, 'model': 'kimi-for-coding'},
                    {'id': 'native_oai', 'name': 'OpenAI 协议', 'desc': 'Moonshot OAI 端点，kimi-k2 系列', 'apibase': 'https://api.moonshot.cn/v1', 'model': 'kimi-k2.6'},
                ],
            },
        ],
    },
    {
        'id': 'qwen',
        'name': '阿里通义千问 (Qwen3.5 / 百炼)',
        'desc': '阿里云百炼，Qwen3 系列百万级上下文',
        'type': 'native_oai',
        'template': {
            'name': 'qwen', 'apikey': 'sk-<your-dashscope-key>',
            'apibase': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'model': 'qwen3.5-plus',
            'api_mode': 'chat_completions',
        },
        'key_hint': '在 https://bailian.console.aliyun.com/ 获取 API Key',
        'model_choices': ['qwen3.5-plus', 'qwen3-coder-plus'],
        'extra_fields': [
            {
                'key': '_endpoint', 'label': '选择端点',
                'type': 'choice',
                'options': [
                    {'id': 'standard', 'name': '标准按量付费', 'desc': 'dashscope.aliyuncs.com，兼容模式', 'apibase': 'https://dashscope.aliyuncs.com/compatible-mode/v1'},
                    {'id': 'coding_plan', 'name': '百炼 Coding Plan (订阅)', 'desc': 'coding-intl.dashscope.aliyuncs.com，100万上下文', 'apibase': 'https://coding-intl.dashscope.aliyuncs.com/v1', 'context_win': 1000000},
                ],
            },
        ],
    },
    {
        'id': 'zhipu',
        'name': '智谱 GLM-5.1 (Coding Plan)',
        'desc': '智谱 GLM，支持 Coding Plan CN (Anthropic) 和 Global (OAI) 双端点',
        'type': 'native_claude',
        'template': {
            'name': 'zhipu-glm', 'apikey': 'sk-<your-zhipu-key>',
            'apibase': 'https://open.bigmodel.cn/api/anthropic',
            'model': 'GLM-5.1-Cloud', 'fake_cc_system_prompt': False,
            'thinking_type': 'adaptive', 'max_retries': 3,
            'connect_timeout': 10, 'read_timeout': 180,
        },
        'key_hint': 'CN 在 https://open.bigmodel.cn/ 获取；Global 在 https://z.ai/ 获取',
        'model_choices': ['GLM-5.1-Cloud', 'glm-4.7'],
        'extra_fields': [
            {
                'key': '_plan', 'label': '选择 Coding Plan',
                'type': 'choice',
                'options': [
                    {'id': 'native_claude', 'name': 'Coding Plan CN (Anthropic)', 'desc': 'open.bigmodel.cn，推荐国内用户', 'apibase': 'https://open.bigmodel.cn/api/anthropic', 'fake_cc_system_prompt': False},
                    {'id': 'native_oai', 'name': 'Coding Plan Global (OAI)', 'desc': 'api.z.ai，OpenAI 协议，全球可用', 'apibase': 'https://api.z.ai/api/paas/v4'},
                ],
            },
        ],
    },
    {
        'id': 'minimax',
        'name': 'MiniMax M2.7 (双协议)',
        'desc': 'MiniMax M2.7，支持 Anthropic 和 OpenAI 双协议',
        'type': 'native_claude',
        'template': {
            'name': 'minimax', 'apikey': 'eyJh...<your-minimax-key>',
            'apibase': 'https://api.minimaxi.com/anthropic',
            'model': 'MiniMax-M2.7', 'max_retries': 3,
        },
        'key_hint': '在 https://platform.minimaxi.com/user-center/basic-information 获取',
        'model_choices': ['MiniMax-M2.7', 'MiniMax-M2.5'],
        'extra_fields': [
            {
                'key': '_protocol', 'label': '选择 API 协议',
                'type': 'choice',
                'options': [
                    {'id': 'native_claude', 'name': 'Anthropic 协议 (推荐)', 'desc': '无 <think> 标签，原生 Claude 兼容', 'apibase': 'https://api.minimaxi.com/anthropic'},
                    {'id': 'native_oai', 'name': 'OpenAI 协议', 'desc': '走 /v1/chat/completions', 'apibase': 'https://api.minimaxi.com/v1', 'context_win': 50000},
                ],
            },
        ],
    },
    {
        'id': 'stepfun',
        'name': '阶跃星辰 Step-3.5 (推理强)',
        'desc': '阶跃星辰 Step 系列，支持标准和 Step Plan 双端点',
        'type': 'native_oai',
        'template': {
            'name': 'stepfun', 'apikey': 'sk-<your-stepfun-key>',
            'apibase': 'https://api.stepfun.com/v1',
            'model': 'step-3.5-flash',
            'api_mode': 'chat_completions',
            'context_win': 262144,
        },
        'key_hint': '在 https://platform.stepfun.com/ 获取 API Key',
        'model_choices': ['step-3.5-flash', 'step-3.5-flash-2603'],
        'extra_fields': [
            {
                'key': '_endpoint', 'label': '选择端点',
                'type': 'choice',
                'options': [
                    {'id': 'standard', 'name': '标准端点', 'desc': 'api.stepfun.com/v1，按量付费', 'apibase': 'https://api.stepfun.com/v1', 'context_win': 262144},
                    {'id': 'step_plan', 'name': 'Step Plan (订阅)', 'desc': 'api.stepfun.com/step_plan/v1，订阅制', 'apibase': 'https://api.stepfun.com/step_plan/v1', 'context_win': 262144},
                ],
            },
        ],
    },
    {
        'id': 'qianfan',
        'name': '百度千帆 (ERNIE 5.0 / 第三方)',
        'desc': '百度智能云千帆，文心一言 ERNIE 5.0 + DeepSeek 等',
        'type': 'native_oai',
        'template': {
            'name': 'baidu-qianfan', 'apikey': '<your-qianfan-key>',
            'apibase': 'https://qianfan.baidubce.com/v2',
            'model': 'ernie-5.0-thinking-preview',
            'api_mode': 'chat_completions',
        },
        'key_hint': '在 https://console.bce.baidu.com/qianfan/ 创建应用获取 API Key',
        'model_choices': ['ernie-5.0-thinking-preview', 'deepseek-v3.2'],
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://qianfan.baidubce.com/v2'},
        ],
    },
    {
        'id': 'volcengine',
        'name': '火山引擎 (豆包 / Ark)',
        'desc': '字节跳动火山引擎，支持标准 Ark 和 Ark Coding Plan',
        'type': 'native_oai',
        'template': {
            'name': 'volc-ark', 'apikey': '<your-ark-api-key>',
            'apibase': 'https://ark.cn-beijing.volces.com/api/v3',
            'model': 'doubao-seed-code-preview-251028',
            'api_mode': 'chat_completions',
        },
        'key_hint': '在 https://console.volcengine.com/ark/ 创建推理接入点后获取 API Key',
        'model_choices': ['doubao-seed-code-preview-251028', 'doubao-seed-1-8-251228'],
        'extra_fields': [
            {
                'key': '_endpoint', 'label': '选择端点',
                'type': 'choice',
                'options': [
                    {'id': 'standard', 'name': '标准 Ark', 'desc': 'ark.cn-beijing.volces.com/api/v3，按量付费', 'apibase': 'https://ark.cn-beijing.volces.com/api/v3'},
                    {'id': 'coding_plan', 'name': 'Ark Coding Plan (订阅)', 'desc': 'ark.cn-beijing.volces.com/api/coding/v3', 'apibase': 'https://ark.cn-beijing.volces.com/api/coding/v3'},
                ],
            },
        ],
    },
    {
        'id': 'xiaomi',
        'name': '小米 MiMo (MiMo 2.5 Pro / TokenPlan)',
        'desc': '小米 MiMo 系列，超大上下文窗口，支持 TokenPlan 预付费',
        'type': 'native_oai',
        'template': {
            'name': 'xiaomi-mimo', 'apikey': 'sk-<your-xiaomi-key>',
            'apibase': 'https://api.xiaomimimo.com/v1',
            'model': 'mimo-v2.5-pro',
            'api_mode': 'chat_completions',
        },
        'key_hint': '在 https://x.xiaomi.com/ 获取 API Key',
        'model_choices': ['mimo-v2.5-pro', 'mimo-v2-flash'],
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://api.xiaomimimo.com/v1'},
        ],
    },
    {
        'id': 'tencent_tokenhub',
        'name': '腾讯混元 TokenHub (Hy3 / TokenPlan)',
        'desc': '腾讯云 TokenHub，混元 Hy3 系列，TokenPlan 预付费',
        'type': 'native_oai',
        'template': {
            'name': 'tencent-tokenhub', 'apikey': 'sk-<your-tokenhub-key>',
            'apibase': 'https://tokenhub.tencentmaas.com/v1',
            'model': 'hy3-preview',
            'api_mode': 'chat_completions',
        },
        'key_hint': '在 https://console.cloud.tencent.com/tokenhub 获取 API Key',
        'model_choices': ['hy3-preview'],
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://tokenhub.tencentmaas.com/v1'},
        ],
    },
    # ═══════════════════════════ 代理 / 中继（支持 Claude/GPT 等顶级模型）══════════
    {
        'id': 'cc_relay',
        'name': 'CC Switch 透传 (社区常用)',
        'desc': '社区 Claude Code 透传渠道，可接入 Claude Opus',
        'type': 'native_claude',
        'template': {
            'name': 'cc-relay', 'apikey': 'sk-user-<your-relay-key>',
            'apibase': 'https://<your-cc-switch-host>/claude/office',
            'model': 'claude-opus-4-7', 'fake_cc_system_prompt': True,
            'thinking_type': 'adaptive',
        },
        'key_hint': '从你的 CC Switch 服务商获取 apikey 和 apibase',
        'model_choices': ['claude-opus-4-7', 'claude-sonnet-4-6'],
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://your-host/claude/office'},
            {'key': 'fake_cc_system_prompt', 'label': 'fake_cc_system_prompt', 'type': 'bool', 'default': True},
        ],
    },
    {
        'id': 'openrouter',
        'name': 'OpenRouter (多模型中继)',
        'desc': '一个 Key 通吃 Claude/GPT/DeepSeek/Qwen 等',
        'type': 'native_oai',
        'template': {
            'name': 'openrouter', 'apikey': 'sk-or-<your-openrouter-key>',
            'apibase': 'https://openrouter.ai/api/v1',
            'model': 'anthropic/claude-opus-4-7',
            'max_retries': 3, 'connect_timeout': 10, 'read_timeout': 120,
        },
        'key_hint': '在 https://openrouter.ai/keys 获取',
        'model_choices': ['anthropic/claude-opus-4-7', 'openai/gpt-5.5'],
    },
    {
        'id': 'crs',
        'name': 'CRS 反代 (Claude Max 多通道)',
        'desc': 'CRS 协议的反代服务，支持 Claude Max / Gemini Ultra 通道',
        'type': 'native_claude',
        'template': {
            'name': 'crs', 'apikey': 'cr_<your-crs-key>',
            'apibase': 'https://<your-crs-host>/api',
            'model': 'claude-opus-4-7[1m]', 'fake_cc_system_prompt': True,
            'thinking_type': 'adaptive', 'max_tokens': 32768,
            'max_retries': 3, 'read_timeout': 180,
        },
        'key_hint': '从你的 CRS 服务商获取 key 和 host',
        'model_choices': ['claude-opus-4-7[1m]', 'claude-sonnet-4-6'],
        'extra_fields': [
            {
                'key': '_channel', 'label': '选择 CRS 通道',
                'type': 'choice',
                'options': [
                    {'id': 'claude_max', 'name': 'Claude Max (默认)', 'desc': '标准 CRS Claude 通道', 'apibase': 'https://<your-crs-host>/api'},
                    {'id': 'gemini_ultra', 'name': 'Gemini Ultra (Antigravity)', 'desc': 'CRS 包装的 Google Antigravity，不支持 SSE 流式', 'apibase': 'https://<your-crs-gemini-host>/antigravity/api', 'model': 'claude-opus-4-7-thinking', 'stream': False},
                ],
            },
        ],
    },
    {
        'id': 'gmi',
        'name': 'GMI Serving (通用模型中继)',
        'desc': 'GMI 通用模型推理服务，支持多种开源/闭源（手动输入模型名）',
        'type': 'native_oai',
        'template': {
            'name': 'gmi', 'apikey': '<your-gmi-key>',
            'apibase': 'https://api.gmi-serving.com/v1',
            'model': 'gmi-default',
            'api_mode': 'chat_completions',
        },
        'key_hint': '从 GMI 服务商获取 API Key，探测失败时手动输入模型名',
        'model_choices': [],  # 中继服务，模型由服务商提供，探测失败时手动输入
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://api.gmi-serving.com/v1'},
        ],
    },
]

# ── 消息平台定义 ────────────────────────────────────────────────────────────
PLATFORMS = [
    {
        'id': 'none',
        'name': '不使用消息平台（纯终端 REPL）',
        'desc': '直接用 python agentmain.py 在终端交互',
        'deps': [],
    },
    {
        'id': 'telegram',
        'name': 'Telegram 机器人',
        'desc': '通过 Telegram Bot 与 Agent 对话',
        'file': 'frontends/tgapp.py',
        'deps': ['python-telegram-bot'],
        'env_vars': [
            {'key': 'tg_bot_token', 'label': 'Bot Token', 'hint': '从 @BotFather 获取'},
            {'key': 'tg_allowed_users', 'label': '允许的用户 ID（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
    {
        'id': 'qq',
        'name': 'QQ 机器人',
        'desc': '通过 QQ 官方机器人 API 接入',
        'file': 'frontends/qqapp.py',
        'deps': ['qq-botpy'],
        'env_vars': [
            {'key': 'qq_app_id', 'label': 'App ID', 'hint': 'QQ 开放平台获取'},
            {'key': 'qq_app_secret', 'label': 'App Secret'},
            {'key': 'qq_allowed_users', 'label': '允许的用户 OpenID（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
    {
        'id': 'feishu',
        'name': '飞书机器人',
        'desc': '通过飞书应用与 Agent 对话',
        'file': 'frontends/fsapp.py',
        'deps': ['lark-oapi'],
        'env_vars': [
            {'key': 'fs_app_id', 'label': 'App ID', 'hint': '飞书开放平台获取'},
            {'key': 'fs_app_secret', 'label': 'App Secret'},
            {'key': 'fs_allowed_users', 'label': '允许的用户（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
    {
        'id': 'wecom',
        'name': '企业微信机器人',
        'desc': '通过企业微信 Bot 接入',
        'file': 'frontends/wecomapp.py',
        'deps': ['wecombot'],
        'env_vars': [
            {'key': 'wecom_bot_id', 'label': 'Bot ID'},
            {'key': 'wecom_secret', 'label': 'Bot Secret'},
            {'key': 'wecom_allowed_users', 'label': '允许的用户（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
    {
        'id': 'dingtalk',
        'name': '钉钉机器人',
        'desc': '通过钉钉应用接入',
        'file': 'frontends/dingtalkapp.py',
        'deps': ['dingtalk-sdk'],
        'env_vars': [
            {'key': 'dingtalk_client_id', 'label': 'Client ID (App Key)'},
            {'key': 'dingtalk_client_secret', 'label': 'Client Secret (App Secret)'},
            {'key': 'dingtalk_allowed_users', 'label': '允许的用户 StaffID（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
    {
        'id': 'discord',
        'name': 'Discord 机器人',
        'desc': '通过 Discord Bot 接入',
        'file': 'frontends/dcapp.py',
        'deps': ['discord.py'],
        'env_vars': [
            {'key': 'dc_bot_token', 'label': 'Bot Token', 'hint': 'Discord Developer Portal 获取'},
            {'key': 'dc_allowed_users', 'label': '允许的用户 ID（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
    {
        'id': 'wechat',
        'name': '微信 (iLink 协议)',
        'desc': '通过微信个人号与 Agent 对话，扫码自动登录',
        'file': 'frontends/wechatapp.py',
        'deps': ['requests', 'qrcode', 'pycryptodome'],
        'env_vars': [],
    },
]


def _masked(v, reveal, tail):
    """生成脱敏字符串：前 reveal 位明文 + * + 后 tail 位明文"""
    if len(v) > reveal + tail:
        return v[:reveal] + '*' * min(len(v) - reveal - tail, 8) + v[-tail:]
    elif len(v) > reveal:
        return v[:reveal] + '*' * (len(v) - reveal)
    return v

def masked_input(prompt, reveal=6, tail=4):
    """密文输入，支持粘贴：批读取 + 延迟重绘，避免快速键入时丢字符。

    prompt 必须为单行（不含 \\n）。
    """
    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars = []

    def _repaint():
        m = _masked(''.join(chars), reveal, tail)
        sys.stdout.write(f'\r{prompt}{m}     \r{prompt}{m}')
        sys.stdout.flush()

    def _process(c):
        """处理单个字符，返回 True 表示应退出。"""
        if c in ('\r', '\n'):
            return True
        if c in ('\x03', '\x04'):
            raise KeyboardInterrupt
        if c in ('\x08', '\x7f'):
            if chars:
                chars.pop()
        elif c.isprintable() or c == ' ':
            chars.append(c)
        return False

    if os.name == 'nt':
        import msvcrt
        while True:
            c = msvcrt.getwch()
            if _process(c):
                break
            if c in ('\x08', '\x7f'):
                _repaint()          # 退格立即重绘
                continue
            if not (c.isprintable() or c == ' '):
                continue
            # 批量读取：粘贴时一次取完
            while msvcrt.kbhit():
                c2 = msvcrt.getwch()
                if _process(c2):
                    value = ''.join(chars)
                    _repaint()
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    return value
            _repaint()
    else:
        import tty, termios, select
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                c = sys.stdin.read(1)
                if _process(c):
                    break
                if c in ('\x08', '\x7f'):
                    _repaint()      # 退格立即重绘
                    continue
                if not (c.isprintable() or c == ' '):
                    continue
                # 批量读取：只要 stdin 有数据就继续读，不重绘
                while select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                    c2 = sys.stdin.read(1)
                    if _process(c2):
                        value = ''.join(chars)
                        _repaint()
                        termios.tcsetattr(fd, termios.TCSADRAIN, old)
                        sys.stdout.write('\n')
                        sys.stdout.flush()
                        return value
                _repaint()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    value = ''.join(chars)
    _repaint()
    sys.stdout.write('\n')
    sys.stdout.flush()
    return value


# ═══════════════════════════════════════════════════════════════════════════
#  UI Helpers
# ═══════════════════════════════════════════════════════════════════════════

def cprint(text, color=None, bold=False, end='\n'):
    parts = []
    if color: parts.append(C.get(color, ''))
    if bold: parts.append(C['bold'])
    parts.append(text)
    parts.append(C['reset'])
    print(''.join(parts), end=end)

def banner():
    print('\033[2J\033[H', end='')  # ANSI 清屏，跨平台
    print(f"{C['cyan']}{C['bold']}")
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║        GenericAgent — 交互式初始化向导 v1.2              ║")
    print("  ║   一键配置 LLM 模型 + 消息平台，自动生成 mykey.py        ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print(f"{C['reset']}")
    print(f"{C['dim']}  项目目录: {PROJECT_ROOT}{C['reset']}")
    print()

def _check_python():
    """检查 Python 版本，返回 (ok, msg)"""
    vi = sys.version_info
    if vi < (3, 10):
        return False, f"Python {vi.major}.{vi.minor} 不满足最低要求 (≥ 3.10)"
    if vi[:2] == (3, 12):
        return True, ''
    return True, f"⚠ 当前 Python {vi.major}.{vi.minor}，推荐使用 Python 3.12"

def ask_choice(prompt, choices, allow_multi=False, default=None):
    """交互式选择，返回 selected_id 或 [selected_ids]"""
    print(f"\n{C['bold']}{prompt}{C['reset']}")
    if allow_multi:
        print(f"{C['dim']}  (可多选，输入序号用逗号分隔，如: 1,3,5；输入 a 全选；回车跳过){C['reset']}")
    else:
        print(f"{C['dim']}  (输入序号，如: 1){C['reset']}")
    for i, c in enumerate(choices, 1):
        desc = c.get('desc', '')
        print(f"  {C['green']}{i}.{C['reset']} {C['bold']}{c['name']}{C['reset']}  {C['dim']}{desc}{C['reset']}")
    while True:
        raw = input(f"\n  {C['yellow']}►{C['reset']} ").strip()
        if not raw and default is not None:
            return default
        if allow_multi:
            if raw.lower() == 'a':
                return [c['id'] for c in choices]
            parts = [p.strip() for p in raw.split(',') if p.strip()]
            selected = []
            for p in parts:
                try:
                    idx = int(p) - 1
                    if 0 <= idx < len(choices):
                        selected.append(choices[idx]['id'])
                except ValueError:
                    pass
            if selected:
                return selected
        else:
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]['id']
            except ValueError:
                pass
        print(f"  {C['red']}✗ 请输入有效序号{C['reset']}")

def ask_input(prompt, default=None, secret=False, hint=None):
    """交互式输入。secret=True 时使用脱敏输入。"""
    if hint:
        cprint(f"  {hint}", 'dim')
    if default is not None:
        cprint(f"  [默认: {default}]", 'dim')
    prompt_line = f"  {C['yellow']}►{C['reset']} {prompt}: "
    while True:
        if secret:
            val = masked_input(prompt_line).strip()
        else:
            val = input(prompt_line).strip()
        if not val and default is not None:
            return default
        if val:
            return val
        cprint("✗ 此项不能为空", 'red')

def ask_yesno(prompt, default=True):
    hint = "Y/N"
    raw = input(f"\n  {C['yellow']}►{C['reset']} {prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw.startswith('y')


# ═══════════════════════════════════════════════════════════════════════════
#  LLM 配置逻辑
# ═══════════════════════════════════════════════════════════════════════════

def _get_proxy_handler():
    """从环境变量读取代理配置，返回 ProxyHandler 或 None"""
    for var in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
        url = os.environ.get(var)
        if url:
            return urllib.request.ProxyHandler({'https': url, 'http': url})
    return None

def probe_models(provider, apikey, apibase=None):
    """调用 API 探测可用模型列表，返回模型 ID 列表或 None"""
    ptype = provider.get('type', 'native_oai')
    base = (apibase or provider['template'].get('apibase', '')).rstrip('/')

    if ptype == 'native_claude':
        url = f"{base}/v1/models"
        headers = {'x-api-key': apikey, 'anthropic-version': '2023-06-01', 'User-Agent': 'GenericAgent/1.0'}
    else:
        url = f"{base}/models"
        headers = {'Authorization': f'Bearer {apikey}', 'User-Agent': 'GenericAgent/1.0'}

    print(f"\n  {C['dim']}🔍 正在探测可用模型 ({base}/models)...{C['reset']}", end='', flush=True)
    if ptype == 'native_claude':
        print(f" {C['dim']}(Anthropic 协议，探测可能失败){C['reset']}", end='', flush=True)

    opener = urllib.request.build_opener()
    ph = _get_proxy_handler()
    if ph:
        opener = urllib.request.build_opener(ph)
        print(f" {C['dim']}(via proxy){C['reset']}", end='', flush=True)

    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers, method='GET')
            with opener.open(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = data.get('data', [])
                ids = sorted(set(m['id'] for m in models if isinstance(m, dict) and m.get('id')))
                if ids:
                    print(f" {C['green']}✓ 发现 {len(ids)} 个模型{C['reset']}")
                    return ids
                print(f" {C['yellow']}⚠ 返回为空{C['reset']}")
                return None
        except Exception as e:
            if attempt == 0 and 'timeout' in type(e).__name__.lower():
                print(f" {C['yellow']}⏱ 超时，重试...{C['reset']}", end='', flush=True)
                continue
            print(f" {C['yellow']}⚠ 探测失败: {type(e).__name__}（将使用预设列表）{C['reset']}")
            return None
    return None

def _normalize_model_choices(choices):
    """统一 model_choices 格式为 [{'id': str, 'name': str}]"""
    if not choices:
        return []
    result = []
    for item in choices:
        if isinstance(item, str):
            result.append({'id': item, 'name': item})
        elif isinstance(item, dict):
            result.append(item)
        elif isinstance(item, (tuple, list)) and len(item) >= 1:
            result.append({'id': item[0], 'name': item[1] if len(item) > 1 else item[0]})
    return result

def _configure_advanced(provider, cfg):
    """配置高级可选字段: proxy, context_win, stream, user_agent, thinking_budget_tokens"""
    print(f"\n  {C['dim']}── 高级选项（回车跳过，使用默认值）{C['reset']}")
    proxy = ask_input("HTTP 代理地址 (proxy)", default='', hint='如 http://127.0.0.1:2082，留空跳过')
    if proxy:
        cfg['proxy'] = proxy
    cw = ask_input("上下文窗口阈值 (context_win)", default='', hint='NativeClaude 默认 28000，其他默认 24000')
    if cw:
        cfg['context_win'] = int(cw)
    if cfg.get('thinking_type') == 'enabled':
        tbt = ask_input("thinking_budget_tokens", default='', hint='low≈4096, medium≈10240, high≈32768')
        if tbt:
            cfg['thinking_budget_tokens'] = int(tbt)
    if cfg.get('type', provider['type']) == 'native_claude':
        ua = ask_input("User-Agent 版本号", default='', hint='某些中转按 UA 白名单校验，pin 老版本用')
        if ua:
            cfg['user_agent'] = ua
    stream_default = cfg.get('stream', True)
    if ask_yesno("启用 SSE 流式 (stream)", default=stream_default):
        cfg['stream'] = True
    else:
        cfg['stream'] = False

def configure_llm(provider):
    """引导用户配置单个模型"""
    print(f"\n{C['cyan']}{'─'*60}{C['reset']}")
    print(f"{C['bold']}  配置: {provider['name']}{C['reset']}")
    print(f"  {C['dim']}{provider['desc']}{C['reset']}")
    print(f"{C['cyan']}{'─'*60}{C['reset']}")

    cfg = dict(provider['template'])

    # API Key（密文输入）
    cfg['apikey'] = ask_input(
        f"API Key",
        hint=provider.get('key_hint', ''),
        secret=True,
    )

    # 额外字段
    for field in provider.get('extra_fields', []):
        if field['key'] == 'apibase':
            cfg['apibase'] = ask_input(
                field['label'],
                default=field.get('default', cfg.get('apibase', '')),
            )
        elif field.get('type') == 'bool':
            cfg[field['key']] = ask_yesno(
                field['label'],
                default=field.get('default', True)
            )
        elif field.get('type') == 'choice':
            picked = ask_choice(field['label'], field['options'])
            chosen = next(o for o in field['options'] if o['id'] == picked)
            for opt_key, opt_val in chosen.items():
                if opt_key not in ('id', 'name', 'desc'):
                    cfg[opt_key] = opt_val

    # 模型选择
    manual_choice = {'id': '__manual__', 'name': '✏️ 手动输入模型名', 'desc': '自定义模型 ID，不依赖探测结果'}
    model_list = probe_models(provider, cfg['apikey'], cfg.get('apibase'))
    if model_list:
        refresh_choice = {'id': '__refresh__', 'name': '🔄 重新探测'}
        choices = [refresh_choice, manual_choice] + [{'id': m, 'name': m} for m in model_list]
        while True:
            picked = ask_choice("API 探测到以下可用模型（或手动输入）:", choices)
            if picked == '__refresh__':
                print(f"  {C['dim']}再次探测...{C['reset']}")
                model_list = probe_models(provider, cfg['apikey'], cfg.get('apibase'))
                if not model_list:
                    print(f"  {C['yellow']}⚠ 再次探测失败{C['reset']}")
                    picked = _fallback_model(provider, manual_choice)
                    break
                choices = [refresh_choice, manual_choice] + [{'id': m, 'name': m} for m in model_list]
            elif picked == '__manual__':
                picked = ask_input("请输入模型名", default=cfg.get('model', ''))
                break
            else:
                break
        cfg['model'] = picked
    else:
        cfg['model'] = _fallback_model(provider, manual_choice)

    # 别名
    default_name = cfg.get('name', provider['id'])
    name = ask_input("此配置的别名 (name，Mixin 引用用)", default=default_name)
    if name:
        cfg['name'] = name

    # 高级选项
    if ask_yesno("配置高级选项（proxy / context_win / stream 等）？", default=False):
        _configure_advanced(provider, cfg)

    return cfg

def _fallback_model(provider, manual_choice=None):
    """使用预设模型列表让用户选择，始终提供手动输入选项"""
    manual_choice = manual_choice or {'id': '__manual__', 'name': '✏️ 手动输入模型名', 'desc': '自定义模型 ID'}
    normalized = _normalize_model_choices(provider.get('model_choices', []))
    if normalized:
        choices = [manual_choice] + normalized
        picked = ask_choice("选择模型（或手动输入）:", choices)
        if picked == '__manual__':
            return ask_input("请输入模型名", default=provider['template'].get('model', ''))
        return picked
    return ask_input("请输入模型名", default=provider['template'].get('model', ''))

def configure_llms():
    """配置 LLM 模型"""
    print(f"\n{C['bold']}{C['magenta']}╔══════════════════════════════════════╗")
    print(f"║     第一步: 配置 LLM 模型           ║")
    print(f"╚══════════════════════════════════════╝{C['reset']}")
    print(f"\n{C['dim']}  你可以配置最多 2 个模型组成故障转移 (Mixin) 列表。{C['reset']}")

    all_cfgs = []
    provider_id = ask_choice("选择模型厂商 (配置第 1 个模型):", LLM_PROVIDERS)
    provider = next(p for p in LLM_PROVIDERS if p['id'] == provider_id)
    cfg = configure_llm(provider)
    all_cfgs.append(cfg)

    if ask_yesno("再添加一个模型做故障转移？", default=False):
        providers_ext = [{'id': '__stop__', 'name': '✓ 不需要备选了', 'desc': ''}] + LLM_PROVIDERS
        provider_id = ask_choice(
            "选择模型厂商 (配置第 2 个模型 — 或选「不需要备选了」跳过):",
            providers_ext
        )
        if provider_id != '__stop__':
            provider = next(p for p in LLM_PROVIDERS if p['id'] == provider_id)
            cfg = configure_llm(provider)
            all_cfgs.append(cfg)

    return all_cfgs


# ═══════════════════════════════════════════════════════════════════════════
#  消息平台配置逻辑
# ═══════════════════════════════════════════════════════════════════════════

def configure_platforms():
    """配置消息平台，返回 (platform_configs, pip_hints)"""
    print(f"\n{C['bold']}{C['magenta']}╔══════════════════════════════════════╗")
    print(f"║     第二步: 配置消息平台             ║")
    print(f"╚══════════════════════════════════════╝{C['reset']}")
    print(f"\n{C['dim']}  消息平台用于从聊天软件与 Agent 交互。{C['reset']}")
    print(f"{C['dim']}  你也可以跳过此步，直接用终端 REPL。{C['reset']}")

    platform_ids = ask_choice(
        "选择消息平台 (可多选，选 '不使用' 则跳过):",
        PLATFORMS,
        allow_multi=True,
        default=['none']
    )

    if 'none' in platform_ids:
        return [], set()

    selected_platforms = []
    pip_hints = set()

    for pid in platform_ids:
        platform = next(p for p in PLATFORMS if p['id'] == pid)
        pip_hints.update(platform.get('deps', []))

        print(f"\n{C['cyan']}{'─'*60}{C['reset']}")
        print(f"{C['bold']}  配置: {platform['name']}{C['reset']}")
        print(f"{C['cyan']}{'─'*60}{C['reset']}")

        env_vals = {}

        if pid == 'feishu' and ask_yesno("使用一键扫码创建应用？（推荐）", default=True):
            env_vals = _feishu_scan(platform)

        for var in platform['env_vars']:
            if var['key'] not in env_vals:
                env_vals.update(_manual_platform_var(var))

        if pid == 'wecom' and ask_yesno("设置欢迎消息？", default=False):
            env_vals['wecom_welcome_message'] = ask_input("欢迎消息内容", default='你好，我在线上。')

        selected_platforms.append({'platform': platform, 'config': env_vals})

    return selected_platforms, pip_hints

def _manual_platform_var(var):
    """手动填写单个平台变量"""
    val = ask_input(var['label'], hint=var.get('hint', ''), default=var.get('default'))
    if var.get('is_list'):
        if val == '[]' or not val:
            return {var['key']: []}
        return {var['key']: [x.strip() for x in val.split(',') if x.strip()]}
    return {var['key']: val}

def _feishu_scan(platform):
    """飞书一键扫码创建应用，返回 env_vals 或空 dict"""
    from io import StringIO
    try:
        import lark_oapi as lark
        import qrcode, threading
    except ImportError:
        print(f"\n  {C['yellow']}⚠ lark-oapi 未安装，降级为手动配置{C['reset']}")
        return {}

    print(f"\n  {C['cyan']}📱 正在启动一键创建...{C['reset']}")
    print(f"  {C['dim']}  请用飞书 App 扫描终端二维码，完成授权后自动获取凭据。{C['reset']}\n")

    qr_printed = threading.Event()
    result_holder = {'data': None}

    def handle_qr(info):
        url = info['url']
        expire = info['expire_in']
        qr = qrcode.QRCode(border=1, box_size=1)
        qr.add_data(url)
        buf = StringIO()
        qr.print_ascii(out=buf)
        qr_art = buf.getvalue()
        print(f"\n  {C['bold']}请用飞书扫描下方二维码，或复制链接在浏览器打开:{C['reset']}")
        print(f"  {C['green']}{qr_art.replace(chr(27), '')}{C['reset']}")
        print(f"  {C['dim']}  链接: {url}{C['reset']}")
        print(f"  {C['dim']}  有效期 {expire} 秒{C['reset']}")
        qr_printed.set()

    def handle_status(info):
        status = info['status']
        if status == 'polling':
            print(f"  {C['yellow']}⏳ 等待扫码...{C['reset']}")
        elif status == 'slow_down':
            print(f"  {C['yellow']}⏳ 等待中... (间隔 {info.get('interval', '?')}s){C['reset']}")
        elif status == 'domain_switched':
            print(f"  {C['cyan']}🌐 已切换认证域名{C['reset']}")

    def run_register():
        try:
            result = lark.register_app(
                on_qr_code=handle_qr,
                on_status_change=handle_status,
            )
            result_holder['data'] = result
        except Exception as e:
            print(f"\n  {C['red']}✗ 创建失败: {e}{C['reset']}")

    thread = threading.Thread(target=run_register, daemon=True)
    thread.start()
    qr_printed.wait(timeout=15)
    thread.join(timeout=300)

    if result_holder['data']:
        result = result_holder['data']
        print(f"\n  {C['green']}✅ 应用创建成功！{C['reset']}")
        print(f"  App ID:     {C['bold']}{result['client_id']}{C['reset']}")
        print(f"  App Secret: {C['bold']}{result['client_secret']}{C['reset']}")
        return {
            'fs_app_id': result['client_id'],
            'fs_app_secret': result['client_secret'],
        }
    else:
        print(f"\n  {C['yellow']}⚠ 扫码创建未完成，降级为手动填写...{C['reset']}")
        return {}



# ═══════════════════════════════════════════════════════════════════════════
#  生成 mykey.py
# ═══════════════════════════════════════════════════════════════════════════

def _var_type_info(cfg):
    """根据配置类型返回 (var_prefix, session_type)"""
    cfg_type = cfg.get('type', 'native_oai')
    if cfg_type == 'native_claude':
        return 'native_claude_config', 'NativeClaudeSession'
    elif cfg_type == 'claude':
        return 'claude_config', 'ClaudeSession'
    elif cfg_type == 'oai':
        return 'oai_config', 'LLMSession'
    else:
        return 'native_oai_config', 'NativeOAISession'


def generate_mykey(llm_cfgs, platform_configs):
    """生成 mykey.py 内容"""
    lines = []
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")
    lines.append(f"#  GenericAgent — mykey.py (由 configure.py 自动生成 @ {datetime.now().strftime('%Y-%m-%d %H:%M')})")
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")
    lines.append("")
    lines.append("# ── 停止符 ──────────────────────────────────────────────────────────────────")
    lines.append("_SETUP_DONE = 'configure.py'  # 删除此行可重新触发配置向导")
    lines.append("")

    # Mixin 配置
    names = [c['name'] for c in llm_cfgs]
    lines.append("# ── Mixin 故障转移 ──────────────────────────────────────────────────────────")
    lines.append("mixin_config = {")
    lines.append(f"    'llm_nos': {names},")
    lines.append("    'max_retries': 10,")
    lines.append("    'base_delay': 0.5,")
    lines.append("}")
    lines.append("")

    # 各模型配置
    type_counts = {}
    for cfg in llm_cfgs:
        cfg_type = cfg.get('type', 'native_oai')
        type_counts[cfg_type] = type_counts.get(cfg_type, 0) + 1

    type_indices = {}
    for i, cfg in enumerate(llm_cfgs):
        cfg_type = cfg.get('type', 'native_oai')
        var_prefix, session_type = _var_type_info(cfg)
        idx = type_indices.get(cfg_type, 0)
        type_indices[cfg_type] = idx + 1

        if type_counts[cfg_type] > 1:
            var_name = f"{var_prefix}_{idx}"
        else:
            var_name = var_prefix

        lines.append(f"# ── {cfg['name']} ({session_type}) ─────────────────────────────────────────────")
        lines.append(f"{var_name} = {{")
        _write_config_fields(lines, cfg)
        lines.append("}")
        lines.append("")

    # 平台配置
    if platform_configs:
        lines.append("# ══════════════════════════════════════════════════════════════════════════════")
        lines.append("#  聊天平台集成")
        lines.append("# ══════════════════════════════════════════════════════════════════════════════")
        lines.append("")
        for pc in platform_configs:
            for key, val in pc['config'].items():
                _write_platform_value(lines, key, val)
            lines.append("")

    # 尾部
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")
    lines.append("#  配置完毕！运行: python agentmain.py  (终端 REPL)")
    if platform_configs:
        for pc in platform_configs:
            p = pc['platform']
            lines.append(f"#  或: python {p['file']}  ({p['name']})")
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")

    return '\n'.join(lines)

def _write_config_fields(lines, cfg):
    """写入配置字典的键值对（缩进的 'key': value, 格式）"""
    for key in ['name', 'apikey', 'apibase', 'model', 'api_mode',
                'fake_cc_system_prompt', 'thinking_type', 'thinking_budget_tokens',
                'reasoning_effort', 'max_tokens', 'max_retries', 'connect_timeout',
                'read_timeout', 'temperature', 'context_win',
                'proxy', 'user_agent', 'stream']:
        if key not in cfg:
            continue
        val = cfg[key]
        if isinstance(val, bool):
            lines.append(f"    '{key}': {str(val)},")
        elif isinstance(val, (int, float)):
            lines.append(f"    '{key}': {val},")
        elif isinstance(val, str):
            lines.append(f"    '{key}': '{val}',")
        else:
            lines.append(f"    '{key}': {repr(val)},")

def _write_platform_value(lines, key, val):
    """写入顶级变量（平台配置等）"""
    if isinstance(val, list):
        if val:
            lines.append(f"{key} = {repr(val)}")
        else:
            lines.append(f"{key} = []  # 允许所有用户")
    elif isinstance(val, str):
        lines.append(f"{key} = '{val}'")
    else:
        lines.append(f"{key} = {repr(val)}")


def _parse_existing_mykey():
    """解析已有 mykey.py，返回 (model_names, platform_infos)

    llm_cfgs: [{'name': str, 'type': str, ...}]  — 模型配置字典列表
    platform_infos: [{'id': str, 'vars': [{'key': str, 'val': ...}]}]  — 平台信息
    解析失败时返回 ([], [])
    """
    if not os.path.exists(MYKPY_PATH):
        return [], []

    with open(MYKPY_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # 解析模型名
    model_names = []
    m = re.search(r"'llm_nos':\s*\[([^\]]*)\]", content)
    if m:
        model_names = re.findall(r"'([^']+)'", m.group(1))

    # 解析平台变量 → 平台 ID
    platform_id_map = {
        'tg_bot_token': 'telegram', 'qq_app_id': 'qq',
        'fs_app_id': 'feishu', 'wecom_bot_id': 'wecom',
        'dingtalk_client_id': 'dingtalk', 'dc_bot_token': 'discord',
    }
    platform_infos = []
    for var_key, pid in platform_id_map.items():
        m_var = re.search(rf"^{var_key}\s*=\s*'([^']*)'", content, re.MULTILINE)
        if m_var:
            platform_infos.append({'id': pid, 'vars': [{'key': var_key, 'val': m_var.group(1)}]})

    return model_names, platform_infos


def _backup_with_name(model_names, platform_ids):
    """按 mykey+模型名+机器人名 格式备份旧 mykey.py"""
    parts = ['mykey']
    for m in model_names[:3]:
        parts.append(m.replace('/', '-').replace('\\', '-'))
    for pid in platform_ids:
        pid_clean = pid.replace('_', '')
        if pid_clean not in parts:
            parts.append(pid_clean)
    safe_name = '_'.join(parts)
    if len(safe_name) > 100:
        safe_name = safe_name[:100]
    backup_path = os.path.join(PROJECT_ROOT, f'{safe_name}.py')
    shutil.copy2(MYKPY_PATH, backup_path)
    return backup_path


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    banner()

    # Python 版本检查
    ok, msg = _check_python()
    if not ok:
        print(f"  {C['red']}✗ {msg}{C['reset']}")
        sys.exit(1)
    if msg:
        color = 'yellow' if '⚠' in msg else 'green'
        print(f"  {C[color]}{msg}{C['reset']}\n")

    # ── 决策流程 ──
    llm_cfgs = []
    platform_configs = []
    platform_deps = set()
    is_modify = False
    is_new = False

    if os.path.exists(MYKPY_PATH):
        model_names, platform_infos = _parse_existing_mykey()
        cur_models = ', '.join(model_names) if model_names else '(未知)'
        cur_platforms = ', '.join(p['id'] for p in platform_infos) if platform_infos else '(无)'
        print(f"  {C['dim']}  当前: 模型=[{cur_models}], 平台=[{cur_platforms}]{C['reset']}")

        mode = ask_choice(
            "检测到已有 mykey.py，请选择操作",
            [
                {'id': 'modify', 'name': '修改现有配置', 'desc': '保留未改部分，只重新配置选定项'},
                {'id': 'new', 'name': '新建配置（备份旧文件）', 'desc': '备份为 mykey+模型+平台.py，然后全新配置'},
            ],
            default=None,
        )

        if mode == 'new':
            backup_path = _backup_with_name(model_names, [p['id'] for p in platform_infos])
            print(f"  {C['green']}✓ 旧配置已备份至:{C['reset']} {C['dim']}{backup}{C['reset']}")
            is_new = True
        else:
            is_modify = True
            scope = ask_choice(
                "你要修改什么？",
                [
                    {'id': 'both', 'name': '两项都重新配置', 'desc': 'LLM + 平台全部更新'},
                    {'id': 'llm', 'name': '重新配置 LLM 模型', 'desc': f'当前: {cur_models}'},
                    {'id': 'platform', 'name': '重新配置消息平台', 'desc': f'当前: {cur_platforms}'},
                ],
            )
            if scope in ('llm', 'both'):
                llm_cfgs = _do_llm()
            if scope in ('platform', 'both'):
                platform_configs, platform_deps = configure_platforms()
            if scope == 'llm' and platform_infos:
                for pi in platform_infos:
                    p = next((x for x in PLATFORMS if x['id'] == pi['id']), None)
                    if p:
                        config_dict = {v['key']: v['val'] for v in pi['vars']}
                        platform_configs.append({'platform': p, 'config': config_dict})
            elif scope == 'platform' and model_names:
                print(f"\n  {C['yellow']}⚠ 只修改平台时若未提供 LLM 配置将无法使用。{C['reset']}")
                cprint(f"    建议两项都重新配置。", 'dim')

    if not is_modify:
        if is_new:
            hint = "已备份旧配置，请完成全新设置"
        else:
            hint = "首次配置，建议同时设置模型和消息平台"
        print(f"  {C['dim']}  {hint}。{C['reset']}")

        scope = ask_choice(
            "你想配置什么？",
            [
                {'id': 'both', 'name': '两项都配置 (推荐)', 'desc': 'LLM 模型 + 消息平台，完整初始化'},
                {'id': 'llm', 'name': '仅 LLM 模型', 'desc': '只配置模型，稍后再配平台'},
                {'id': 'platform', 'name': '仅消息平台', 'desc': '只配平台，稍后再配模型'},
            ],
            default='both',
        )

        if scope in ('llm', 'both'):
            llm_cfgs = _do_llm()
            if scope == 'llm':
                if ask_yesno("是否继续配置消息平台？", default=True):
                    platform_configs, platform_deps = configure_platforms()

        if scope == 'both':
            platform_configs, platform_deps = configure_platforms()

        if scope == 'platform':
            platform_configs, platform_deps = configure_platforms()
            if ask_yesno("是否继续配置 LLM 模型？", default=True):
                llm_cfgs = _do_llm()

    # ── 生成 mykey.py ──
    if not llm_cfgs and not platform_configs:
        print(f"\n  {C['yellow']}⚠ 没有配置任何内容，退出。{C['reset']}")
        sys.exit(0)

    content = generate_mykey(llm_cfgs, platform_configs)

    # 备份旧文件
    if os.path.exists(MYKPY_PATH):
        backup = os.path.join(PROJECT_ROOT, f'mykey.py.bak.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
        shutil.copy2(MYKPY_PATH, backup)
        print(f"\n  {C['green']}✓ 旧配置已备份至:{C['reset']} {C['dim']}{backup}{C['reset']}")

    # 写入
    with open(MYKPY_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"\n  {C['green']}✓ mykey.py 已生成!{C['reset']}")

    # ── 完成提示 ──
    print(f"\n{C['bold']}{C['green']}╔══════════════════════════════════════╗")
    print(f"║      配置完成!                      ║")
    print(f"╚══════════════════════════════════════╝{C['reset']}")
    print()
    if llm_cfgs:
        print(f"  {C['cyan']}  终端 REPL:{C['reset']}  python agentmain.py")
    if platform_configs:
        for i, pc in enumerate(platform_configs, 1):
            p = pc['platform']
            print(f"  {C['cyan']}  平台 {i} ({p['name']}):{C['reset']}  python {p['file']}")
    print()

    # pip 依赖提示
    all_deps = sorted(platform_deps)
    if all_deps:
        print(f"  {C['yellow']}💡 提示：你需要安装以下依赖以使消息平台正常工作:{C['reset']}")
        print(f"     {C['cyan']}pip install {' '.join(all_deps)}{C['reset']}")
        print()

    # ── 入门示例 ──
    print(f"  {C['bold']}试试这些命令:{C['reset']}")
    examples = [
        "帮我在桌面创建一个 hello.txt，内容是 Hello World",
        "请查看你的代码，安装所有用得上的 python 依赖",
        "执行 web setup sop，解锁 web 工具",
        "打开淘宝，搜索 iPhone 16，按价格排序",
        "用rapidocr配置你的ocr能力并存入记忆",
        "git 更新你的代码，然后看看 commit 有什么新功能",
        "把这个记到你的记忆里",
    ]
    for ex in examples:
        print(f"    {C['dim']}{ex}{C['reset']}")
    print()

    print(f"  {C['green']}{C['bold']}合抱之木，生于毫末{C['reset']}\n")


def _do_llm():
    """配置 LLM 模型，失败则 exit。"""
    cfgs = configure_llms()
    if not cfgs:
        print(f"\n  {C['red']}✗ 至少需要配置一个模型才能使用。退出。{C['reset']}")
        sys.exit(1)
    return cfgs


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {C['yellow']}⚠ 用户中断{C['reset']}")
        sys.exit(0)
