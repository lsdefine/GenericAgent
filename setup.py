#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════╗
║           GenericAgent — 交互式初始化向导 (setup.py)             ║
║           一键配置 LLM 模型 + 消息平台，自动生成 mykey.py         ║
╚═══════════════════════════════════════════════════════════════════╝

用法:
    python setup.py

说明:
    1. 选择 LLM 厂商并配置 API → 自动探测可用模型列表
    2. 配置消息平台 (可选)
    3. 自动生成 mykey.py
"""

import os, sys, shutil, re, json, webbrowser, subprocess, urllib.request, time
from datetime import datetime

# ── ANSI 颜色 ──────────────────────────────────────────────────────────────
C = {
    'reset': '\033[0m',
    'bold': '\033[1m',
    'dim': '\033[2m',
    'red': '\033[91m',
    'green': '\033[92m',
    'yellow': '\033[93m',
    'blue': '\033[94m',
    'magenta': '\033[95m',
    'cyan': '\033[96m',
    'white': '\033[97m',
}

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MYKPY_PATH = os.path.join(PROJECT_ROOT, 'mykey.py')
MYKPY_BACKUP = os.path.join(PROJECT_ROOT, f'mykey.py.bak.{datetime.now().strftime("%Y%m%d_%H%M%S")}')

# ── 模型厂商定义 ───────────────────────────────────────────────────────────

LLM_PROVIDERS = [
    {
        'id': 'deepseek',
        'name': 'DeepSeek V4 Flash (推荐首选)',
        'desc': '国产开源模型，速度快、性价比高，原生 OAI 协议',
        'type': 'native_oai',
        'template': {
            'name': 'deepseek-flash',
            'apikey': 'sk-<your-deepseek-key>',
            'apibase': 'https://api.deepseek.com',
            'model': 'deepseek-v4-flash',
            'api_mode': 'chat_completions',
            'reasoning_effort': 'high',
        },
        'key_hint': '在 https://platform.deepseek.com/api_keys 获取',
        'model_choices': [
            'deepseek-v4-flash',
            'deepseek-v3-premium',
        ],
    },
    {
        'id': 'openai',
        'name': 'OpenAI GPT-5 / o 系列',
        'desc': 'OpenAI 官方，支持 GPT-5、o 系列推理模型',
        'type': 'native_oai',
        'template': {
            'name': 'gpt-native',
            'apikey': 'sk-<your-openai-key>',
            'apibase': 'https://api.openai.com/v1',
            'model': 'gpt-5.4',
            'api_mode': 'chat_completions',
            'reasoning_effort': 'high',
            'max_retries': 3,
            'connect_timeout': 10,
            'read_timeout': 120,
        },
        'key_hint': '在 https://platform.openai.com/api-keys 获取',
        'model_choices': [
            'gpt-5.4',
            'o4-mini-high',
            'o4-mini',
        ],
    },
    {
        'id': 'anthropic',
        'name': 'Anthropic Claude 官方直连',
        'desc': 'Claude 官方 API，sk-ant- 开头，原生 tool 协议',
        'type': 'native_claude',
        'template': {
            'name': 'anthropic-direct',
            'apikey': 'sk-ant-<your-anthropic-key>',
            'apibase': 'https://api.anthropic.com',
            'model': 'claude-opus-4-7',
            'thinking_type': 'adaptive',
            'max_tokens': 32768,
            'temperature': 1,
        },
        'key_hint': '在 https://console.anthropic.com/ 获取',
        'model_choices': [
            'claude-opus-4-7',
            'claude-sonnet-4-6',
        ],
    },
    {
        'id': 'cc_relay',
        'name': 'CC Switch 透传 (社区常用)',
        'desc': '社区 Claude Code 透传渠道，需要 fake_cc_system_prompt=True',
        'type': 'native_claude',
        'template': {
            'name': 'cc-relay',
            'apikey': 'sk-user-<your-relay-key>',
            'apibase': 'https://<your-cc-switch-host>/claude/office',
            'model': 'claude-opus-4-7',
            'fake_cc_system_prompt': True,
            'thinking_type': 'adaptive',
        },
        'key_hint': '从你的 CC Switch 服务商获取 apikey 和 apibase',
        'model_choices': [
            'claude-opus-4-7',
            'claude-sonnet-4-6',
        ],
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://your-host/claude/office'},
            {'key': 'fake_cc_system_prompt', 'label': '是否需要 fake_cc_system_prompt', 'type': 'bool', 'default': True},
        ],
    },
    {
        'id': 'zhipu',
        'name': '智谱 GLM (Anthropic 兼容)',
        'desc': '智谱 GLM-5.1，走 Anthropic 兼容协议',
        'type': 'native_claude',
        'template': {
            'name': 'zhipu-glm',
            'apikey': 'sk-<your-zhipu-key>',
            'apibase': 'https://open.bigmodel.cn/api/paas/v4/claude',
            'model': 'GLM-5.1-Cloud',
            'fake_cc_system_prompt': False,
            'thinking_type': 'adaptive',
            'max_retries': 3,
            'connect_timeout': 10,
            'read_timeout': 180,
        },
        'key_hint': '在 https://open.bigmodel.cn/usercenter/apikeys 获取',
        'model_choices': [
            'GLM-5.1-Cloud',
            'GLM-5.1-Edge',
        ],
    },
    {
        'id': 'minimax',
        'name': 'MiniMax (推荐 Anthropic 路径 — 无 <think> 标签)',
        'desc': 'MiniMax M2.7，204K 上下文，支持 OAI / Anthropic 双路径',
        'type': 'native_claude',
        'template': {
            'name': 'minimax-anthropic',
            'apikey': 'eyJh...<your-minimax-key>',
            'apibase': 'https://api.minimaxi.com/anthropic',
            'model': 'MiniMax-M2.7',
            'max_retries': 3,
        },
        'key_hint': '在 https://platform.minimaxi.com/user-center/basic-information 获取',
        'model_choices': [
            'MiniMax-M2.7',
            'MiniMax-M2.5',
        ],
        'extra_fields': [
            {'key': 'api_path_choice', 'label': '接口路径', 'type': 'choice',
             'options': [
                 {'id': 'anthropic', 'desc': 'Anthropic 兼容 (/anthropic) — 推荐，无 <think>'},
                 {'id': 'oai', 'desc': 'OpenAI 兼容 (/v1) — 标准 OAI 格式'},
             ], 'default': 'anthropic'},
        ],
    },
    {
        'id': 'minimax_oai',
        'name': 'MiniMax (OpenAI 兼容路径)',
        'desc': 'MiniMax M2.7，走 /v1/chat/completions，匹配 GETTING_STARTED 示例',
        'type': 'native_oai',
        'template': {
            'name': 'minimax-oai',
            'apikey': 'eyJh...<your-minimax-key>',
            'apibase': 'https://api.minimax.io/v1',
            'model': 'MiniMax-M2.7',
        },
        'key_hint': '在 https://platform.minimaxi.com/user-center/basic-information 获取',
        'model_choices': [
            'MiniMax-M2.7',
            'MiniMax-M2.5',
        ],
    },
    {
        'id': 'kimi',
        'name': 'Kimi for Coding (Anthropic 兼容)',
        'desc': 'Kimi 官方 CC 兼容端点，kimi-for-coding 模型',
        'type': 'native_claude',
        'template': {
            'name': 'kimi-coding',
            'apikey': 'sk-kimi-<your-key>',
            'apibase': 'https://api.kimi.com/coding',
            'model': 'kimi-for-coding',
            'fake_cc_system_prompt': True,
            'thinking_type': 'adaptive',
        },
        'key_hint': '在 https://kimi.com/code 获取 API Key',
        'model_choices': [
            'kimi-for-coding',
            'kimi-thinking-plus',
        ],
    },
    {
        'id': 'openrouter',
        'name': 'OpenRouter (多模型中继)',
        'desc': '一个 Key 用所有模型，支持 Claude/GPT/Gemini 等',
        'type': 'native_oai',
        'template': {
            'name': 'openrouter',
            'apikey': 'sk-or-<your-openrouter-key>',
            'apibase': 'https://openrouter.ai/api/v1',
            'model': 'anthropic/claude-opus-4-7',
            'max_retries': 3,
            'connect_timeout': 10,
            'read_timeout': 120,
        },
        'key_hint': '在 https://openrouter.ai/keys 获取',
        'model_choices': [
            'anthropic/claude-opus-4-7',
            'openai/gpt-5.4',
        ],
    },
    {
        'id': 'crs',
        'name': 'CRS 反代 Claude Max',
        'desc': 'CRS 协议的反代 Claude，需要 fake_cc_system_prompt=True',
        'type': 'native_claude',
        'template': {
            'name': 'crs-claude-max',
            'apikey': 'cr_<your-crs-key>',
            'apibase': 'https://<your-crs-host>/api',
            'model': 'claude-opus-4-7[1m]',
            'fake_cc_system_prompt': True,
            'thinking_type': 'adaptive',
            'max_tokens': 32768,
            'max_retries': 3,
            'read_timeout': 180,
        },
        'key_hint': '从你的 CRS 服务商获取 key 和 host',
        'model_choices': [
            ('claude-opus-4-7[1m]', 'Opus 4 - 1M'),
            ('claude-sonnet-4-6', 'Sonnet 4 - 200K'),
        ],
        'extra_fields': [
            {'key': 'apibase', 'label': 'API 地址 (apibase)', 'default': 'https://your-crs-host/api'},
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
        'file': 'tgapp.py',
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
        'file': 'qqapp.py',
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
        'file': 'fsapp.py',
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
        'file': 'wecomapp.py',
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
        'file': 'dingtalkapp.py',
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
        'file': 'dcapp.py',
        'deps': ['discord.py'],
        'env_vars': [
            {'key': 'dc_bot_token', 'label': 'Bot Token', 'hint': 'Discord Developer Portal 获取'},
            {'key': 'dc_allowed_users', 'label': '允许的用户 ID（逗号分隔, 留空=所有人）', 'default': '[]', 'is_list': True},
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════
#  UI Helpers
# ═══════════════════════════════════════════════════════════════════════════

def cprint(text, color=None, bold=False, end='\n'):
    """Color print"""
    parts = []
    if color: parts.append(C.get(color, ''))
    if bold: parts.append(C['bold'])
    parts.append(text)
    parts.append(C['reset'])
    print(''.join(parts), end=end)

def banner():
    """显示横幅"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{C['cyan']}{C['bold']}")
    print("  ╔═══════════════════════════════════════════════════════════╗")
    print("  ║        GenericAgent — 交互式初始化向导 v1.0              ║")
    print("  ║   一键配置 LLM 模型 + 消息平台，自动生成 mykey.py        ║")
    print("  ╚═══════════════════════════════════════════════════════════╝")
    print(f"{C['reset']}")
    print(f"{C['dim']}  项目目录: {PROJECT_ROOT}{C['reset']}")
    print()

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
    """交互式输入"""
    display = prompt
    if hint:
        display += f"\n  {C['dim']}  {hint}{C['reset']}"
    if default is not None:
        display += f"\n  {C['dim']}  [默认: {default}]{C['reset']}"

    while True:
        val = input(f"\n  {C['yellow']}►{C['reset']} {display}: ").strip()
        if not val and default is not None:
            return default
        if val:
            return val
        print(f"  {C['red']}✗ 此项不能为空{C['reset']}")

def ask_yesno(prompt, default=True):
    """是/否选择"""
    hint = "Y/n" if default else "y/N"
    raw = input(f"\n  {C['yellow']}►{C['reset']} {prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw.startswith('y')


# ═══════════════════════════════════════════════════════════════════════════
#  LLM 配置逻辑
# ═══════════════════════════════════════════════════════════════════════════

def probe_models(provider, apikey, apibase=None):
    """调用 API 探测可用模型列表，返回模型 ID 列表或 None"""
    ptype = provider.get('type', 'native_oai')
    base = (apibase or provider['template'].get('apibase', '')).rstrip('/')

    if ptype == 'native_claude':
        url = f"{base}/v1/models"
        headers = {'x-api-key': apikey, 'anthropic-version': '2023-06-01'}
    else:
        url = f"{base}/models"
        headers = {'Authorization': f'Bearer {apikey}'}

    print(f"\n  {C['dim']}🔍 正在探测可用模型 ({url})...{C['reset']}", end='', flush=True)
    time.sleep(0.3)  # 短暂停顿，让用户看到提示

    try:
        req = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            models = data.get('data', [])
            ids = sorted(set(m['id'] for m in models if m.get('id')))
            if ids:
                print(f" {C['green']}✓ 发现 {len(ids)} 个模型{C['reset']}")
                return ids
            print(f" {C['yellow']}⚠ 返回为空{C['reset']}")
            return None
    except Exception as e:
        print(f" {C['red']}✗ 探测失败: {type(e).__name__}{C['reset']}")
        return None


def configure_llm(provider):
    """引导用户配置单个模型"""
    print(f"\n{C['cyan']}{'─'*60}{C['reset']}")
    print(f"{C['bold']}  配置: {provider['name']}{C['reset']}")
    print(f"  {C['dim']}{provider['desc']}{C['reset']}")
    print(f"{C['cyan']}{'─'*60}{C['reset']}")

    cfg = dict(provider['template'])  # 拷贝模板默认值

    # API Key
    cfg['apikey'] = ask_input(
        f"API Key",
        hint=provider.get('key_hint', '')
    )

    # 额外字段（如 apibase、fake_cc_system_prompt 等）
    for field in provider.get('extra_fields', []):
        if field['key'] == 'apibase':
            cfg['apibase'] = ask_input(
                field['label'],
                default=field.get('default', cfg.get('apibase', '')),
            )
        elif field.get('type') == 'bool':
            cfg['fake_cc_system_prompt'] = ask_yesno(
                field['label'],
                default=field.get('default', True)
            )

    # API 自动探测模型
    def _model_choices(model_list):
        if not model_list:
            return None
        return [{'id': '__refresh__', 'name': '🔄 重新探测模型列表'}] + [{'id': m, 'name': m} for m in model_list]

    def _fallback_model(provider):
        if provider.get('model_choices'):
            return ask_choice(
                "选择模型:",
                [{'id': m['id'], 'name': m['id'], 'desc': m['desc']} for m in provider['model_choices']]
            )
        default = cfg.get('model', '')
        return ask_input("请输入模型名称", default=default or None)

    model_list = probe_models(provider, cfg['apikey'], cfg.get('apibase'))
    choices = _model_choices(model_list)
    if choices:
        while True:
            picked = ask_choice("API 探测到以下可用模型，请选择:", choices)
            if picked == '__refresh__':
                print(f"  {C['dim']}再次探测...{C['reset']}")
                model_list = probe_models(provider, cfg['apikey'], cfg.get('apibase'))
                choices = _model_choices(model_list)
                if not choices:
                    print(f"  {C['yellow']}⚠ 再次探测失败，回退到预设列表{C['reset']}")
                    picked = _fallback_model(provider)
                    break
            else:
                break
        cfg['model'] = picked
    else:
        print(f"  {C['yellow']}⚠ 探测失败，使用预设模型列表{C['reset']}")
        picked = _fallback_model(provider)
        if picked:
            cfg['model'] = picked

    # 自定义 name（用于 mixin 引用）
    default_name = cfg.get('name', provider['id'])
    name = ask_input(
        "此配置的别名 (name，Mixin 引用用)",
        default=default_name
    )
    if name:
        cfg['name'] = name

    return cfg


def configure_llms():
    """配置 LLM 模型"""
    print(f"\n{C['bold']}{C['magenta']}╔══════════════════════════════════════╗")
    print(f"║     第一步: 配置 LLM 模型           ║")
    print(f"╚══════════════════════════════════════╝{C['reset']}")
    print(f"\n{C['dim']}  你可以配置最多 2 个模型组成故障转移 (Mixin) 列表。{C['reset']}")

    all_cfgs = []

    # 第 1 个模型
    provider_id = ask_choice(
        "选择模型厂商 (配置第 1 个模型):",
        LLM_PROVIDERS
    )
    provider = next(p for p in LLM_PROVIDERS if p['id'] == provider_id)
    cfg = configure_llm(provider)
    all_cfgs.append(cfg)

    # 是否加第 2 个做故障转移？
    if ask_yesno("再添加一个模型做故障转移？", default=False):
        # 第 2 个模型选项列表，首项加「不需要备选了」
        providers_ext = [
            {'id': '__stop__', 'name': '✓ 不需要备选了，先这样吧', 'desc': ''}
        ] + LLM_PROVIDERS
        provider_id = ask_choice(
            "选择模型厂商 (配置第 2 个模型 — 或选「不需要备选了」跳过):",
            providers_ext
        )
        if provider_id != '__stop__':
            provider = next(p for p in LLM_PROVIDERS if p['id'] == provider_id)
            cfg = configure_llm(provider)
            all_cfgs.append(cfg)
        # 选了 __stop__ 则只保留第 1 个模型

    return all_cfgs


# ═══════════════════════════════════════════════════════════════════════════
#  消息平台配置逻辑
# ═══════════════════════════════════════════════════════════════════════════

def configure_platforms():
    """配置消息平台"""
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
        return []

    selected_platforms = []
    for pid in platform_ids:
        platform = next(p for p in PLATFORMS if p['id'] == pid)

        print(f"\n{C['cyan']}{'─'*60}{C['reset']}")
        print(f"{C['bold']}  配置: {platform['name']}{C['reset']}")
        print(f"{C['cyan']}{'─'*60}{C['reset']}")

        env_vals = {}

        # ── 飞书特殊：使用 SDK 一键扫码创建应用 ──
        if pid == 'feishu' and ask_yesno("使用一键扫码创建应用？（推荐）", default=True):
            # 确保 lark-oapi 已安装
            try:
                import lark_oapi as lark
                import webbrowser, qrcode, threading, time
                from io import StringIO
            except ImportError:
                print(f"\n  {C['yellow']}⚠ lark-oapi 未安装，请运行: pip install lark-oapi{C['reset']}")
                print(f"  {C['dim']}  降级为手动配置...{C['reset']}")
                use_scan = False
            else:
                use_scan = True

            if use_scan:
                print(f"\n  {C['cyan']}📱 正在启动一键创建...{C['reset']}")
                print(f"  {C['dim']}  请用飞书 App 扫描终端二维码，完成授权后自动获取凭据。{C['reset']}\n")

                qr_printed = threading.Event()
                result_holder = {'data': None}

                def handle_qr(info):
                    url = info['url']
                    expire = info['expire_in']

                    # 终端显示二维码 (ASCII)
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

                print(f"  {C['cyan']}⏳ 正在获取二维码，请稍候...{C['reset']}")

                def run_register():
                    try:
                        result = lark.register_app(
                            on_qr_code=handle_qr,
                            on_status_change=handle_status,
                        )
                        result_holder['data'] = result
                    except lark.AppAccessDeniedError:
                        print(f"\n  {C['red']}✗ 用户拒绝授权{C['reset']}")
                    except lark.AppExpiredError:
                        print(f"\n  {C['red']}✗ 二维码已过期{C['reset']}")
                    except Exception as e:
                        print(f"\n  {C['red']}✗ 创建失败: {e}{C['reset']}")

                # 在后台线程执行（因为 register_app 是阻塞的）
                thread = threading.Thread(target=run_register, daemon=True)
                thread.start()

                # 等二维码生成
                qr_printed.wait(timeout=15)

                # 阻塞等待结果（最多 5 分钟）
                thread.join(timeout=300)

                if result_holder['data']:
                    result = result_holder['data']
                    env_vals['FEISHU_APP_ID'] = result['client_id']
                    env_vals['FEISHU_APP_SECRET'] = result['client_secret']
                    print(f"\n  {C['green']}✅ 应用创建成功！{C['reset']}")
                    print(f"  App ID:     {C['bold']}{result['client_id']}{C['reset']}")
                    print(f"  App Secret: {C['bold']}{result['client_secret']}{C['reset']}")
                    if result.get('user_info'):
                        print(f"  创建者: {result['user_info'].get('open_id', '?')} ({result['user_info'].get('tenant_brand', '?')})")
                else:
                    print(f"\n  {C['yellow']}⚠ 扫码创建未完成，降级为手动填写...{C['reset']}")
                    # 手动填写
                    for var in platform['env_vars']:
                        val = ask_input(
                            var['label'],
                            hint=var.get('hint', ''),
                            default=var.get('default')
                        )
                        env_vals[var['key']] = val

        if not env_vals:
            # 非飞书 / 飞书选择了手动 / 飞书扫码失败后已手动填完
            for var in platform['env_vars']:
                if var['key'] in env_vals:
                    continue  # 已通过扫码自动填写
                val = ask_input(
                    var['label'],
                    hint=var.get('hint', ''),
                    default=var.get('default')
                )
                if var.get('is_list'):
                    if val == '[]' or not val:
                        env_vals[var['key']] = []
                    else:
                        env_vals[var['key']] = [x.strip() for x in val.split(',') if x.strip()]
                else:
                    env_vals[var['key']] = val

        # 额外：welcome_message
        if ask_yesno("设置欢迎消息？", default=False):
            env_vals['welcome_message'] = ask_input("欢迎消息内容", default='你好，我在线上。')

        selected_platforms.append({
            'platform': platform,
            'config': env_vals,
        })

    return selected_platforms


# ═══════════════════════════════════════════════════════════════════════════
#  生成 mykey.py
# ═══════════════════════════════════════════════════════════════════════════

def generate_mykey(llm_cfgs, platform_configs):
    """生成 mykey.py 内容"""
    lines = []
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")
    lines.append(f"#  GenericAgent — mykey.py (由 setup.py 自动生成 @ {datetime.now().strftime('%Y-%m-%d %H:%M')})")
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")
    lines.append("")
    lines.append("# ── 停止符 ──────────────────────────────────────────────────────────────────")
    lines.append("_SETUP_DONE = True  # 删除此行可重新触发 setup.py")
    lines.append("")

    # Mixin 配置
    if len(llm_cfgs) > 1:
        lines.append("# ── Mixin 故障转移 ──────────────────────────────────────────────────────────")
        lines.append("mixin_config = {")
        lines.append(f"    'llm_nos': {[c['name'] for c in llm_cfgs]},")
        lines.append(f"    'max_retries': 10,")
        lines.append(f"    'base_delay': 0.5,")
        lines.append("}")
        lines.append("")

    # 各模型配置
    for i, cfg in enumerate(llm_cfgs):
        # 变量名前缀规则（参见 GETTING_STARTED.md 的命名对照表）：
        #   native_claude → native_claude_config → NativeClaudeSession
        #   native_oai    → native_oai_config    → NativeOAISession
        cfg_type = cfg.get('type', 'native_oai')
        if cfg_type == 'native_claude':
            var_prefix = 'native_claude_config'
            session_type = 'NativeClaudeSession'
        elif cfg_type == 'claude':
            var_prefix = 'claude_config'
            session_type = 'ClaudeSession'
        elif cfg_type == 'oai':
            var_prefix = 'oai_config'
            session_type = 'LLMSession'
        else:
            var_prefix = 'native_oai_config'
            session_type = 'NativeOAISession'

        var_name = f"{var_prefix}_{i}" if i > 0 else var_prefix

        lines.append(f"# ── {cfg['name']} ({session_type}) ─────────────────────────────────────────────")
        lines.append(f"{var_name} = {{")
        for key in ['name', 'apikey', 'apibase', 'model', 'api_mode',
                     'fake_cc_system_prompt', 'thinking_type', 'reasoning_effort',
                     'max_tokens', 'max_retries', 'connect_timeout', 'read_timeout',
                     'temperature']:
            if key in cfg:
                val = cfg[key]
                if isinstance(val, bool):
                    lines.append(f"    '{key}': {str(val)},")
                elif isinstance(val, int):
                    lines.append(f"    '{key}': {val},")
                elif isinstance(val, float):
                    lines.append(f"    '{key}': {val},")
                elif isinstance(val, str):
                    lines.append(f"    '{key}': '{val}',")
                else:
                    lines.append(f"    '{key}': {repr(val)},")
        lines.append("}")
        lines.append("")

    # 单模型不用 mixin，直接自动配
    if len(llm_cfgs) == 1:
        lines.append("# ── Mixin 故障转移（单模型也配，方便以后加）─────────────────────────────")
        lines.append("mixin_config = {")
        lines.append(f"    'llm_nos': ['{llm_cfgs[0]['name']}'],")
        lines.append(f"    'max_retries': 10,")
        lines.append(f"    'base_delay': 0.5,")
        lines.append("}")
        lines.append("")

    # 消息平台配置
    if platform_configs:
        lines.append("# ══════════════════════════════════════════════════════════════════════════════")
        lines.append("#  聊天平台集成")
        lines.append("# ══════════════════════════════════════════════════════════════════════════════")
        lines.append("")
        for pc in platform_configs:
            pid = pc['platform']['id']
            config = pc['config']
            for key, val in config.items():
                if isinstance(val, list):
                    if val:
                    # 普通列表
                        lines.append(f"{key} = {repr(val)}")
                    else:
                        lines.append(f"{key} = []  # 允许所有用户")
                elif isinstance(val, str):
                    lines.append(f"{key} = '{val}'")
                else:
                    lines.append(f"{key} = {repr(val)}")
            lines.append("")

    # 尾部提示
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")
    lines.append("#  配置完毕！运行: python agentmain.py  (终端 REPL)")
    if platform_configs:
        for pc in platform_configs:
            lines.append(f"#  或: python frontends/{pc['platform']['file']}  ({pc['platform']['name']})")
    lines.append("# ══════════════════════════════════════════════════════════════════════════════")

    return '\n'.join(lines)





# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    banner()

    # 第一步: LLM 模型配置
    llm_cfgs = configure_llms()

    if not llm_cfgs:
        print(f"\n  {C['red']}✗ 至少需要配置一个模型才能使用。退出。{C['reset']}")
        sys.exit(1)

    # 第二步: 消息平台
    platform_configs = configure_platforms()

    # 第三步: 生成 mykey.py
    content = generate_mykey(llm_cfgs, platform_configs)

    # 备份旧文件
    if os.path.exists(MYKPY_PATH):
        shutil.copy2(MYKPY_PATH, MYKPY_BACKUP)
        print(f"\n  {C['green']}✓ 旧配置已备份至:{C['reset']} {C['dim']}{MYKPY_BACKUP}{C['reset']}")

    # 写入
    with open(MYKPY_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"\n  {C['green']}✓ mykey.py 已生成!{C['reset']}")

    print(f"\n{C['bold']}{C['green']}╔══════════════════════════════════════╗")
    print(f"║      配置完成!                      ║")
    print(f"╚══════════════════════════════════════╝{C['reset']}")
    print()
    print(f"  启动方式:")
    print(f"  {C['cyan']}  1. 终端 REPL:{C['reset']}  python agentmain.py")
    if platform_configs:
        for pc in platform_configs:
            print(f"  {C['cyan']}  {platform_configs.index(pc)+2}. {pc['platform']['name']}:{C['reset']}  python frontends/{pc['platform']['file']}")
    print()

    print(f"\n  {C['green']}{C['bold']}🎉 一切就绪! 祝你使用愉快! 🎉{C['reset']}")
    print()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {C['yellow']}⚠ 用户中断{C['reset']}")
        sys.exit(0)
