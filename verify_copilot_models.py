import argparse
import json
import os
import re
import socket
from urllib.parse import urlparse
from pathlib import Path

import requests
import yaml

BASE_URL = "http://127.0.0.1:8000"
MODELS_URL = f"{BASE_URL}/v1/models"
CHAT_URL = f"{BASE_URL}/v1/chat/completions"
TIMEOUT = 15

MODEL_SPECS = {
    "gpt-4": {
        "section": "OpenAI Models",
        "backend_model": "github_copilot/gpt-4",
        "config_var": "native_oai_config_copilot_gpt4",
        "name": "copilot-gpt4",
        "title": "GPT-4 - 平衡性能与成本",
    },
    "claude-sonnet-4.5": {
        "section": "Anthropic Models",
        "backend_model": "github_copilot/claude-sonnet-4.5",
        "config_var": "native_oai_config_copilot_claude",
        "name": "copilot-claude",
        "title": "Claude Sonnet 4.5 - 长上下文支持 (200K+)",
    },
    "gemini-2.5-pro": {
        "section": "Google Models",
        "backend_model": "github_copilot/gemini-2.5-pro",
        "config_var": "native_oai_config_copilot_gemini",
        "name": "copilot-gemini",
        "title": "Gemini 2.5 Pro - 强多模态支持",
    },
}

HEADER_LINES = [
    '        Editor-Version: "vscode/1.85.1"',
    '        Editor-Plugin-Version: "copilot/1.155.0"',
    '        Copilot-Integration-Id: "vscode-chat"',
    '        User-Agent: "GitHubCopilotChat/0.35.0"',
]
TOKEN_REF = "os.environ/GITHUB_COPILOT_TOKEN"


def detect_proxy_state():
    proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("ALL_PROXY")
        or ""
    )
    info = {
        "proxy_env_url": proxy_url,
        "proxy_configured": bool(proxy_url),
        "proxy_reachable": False,
        "proxy_mode": "direct",
    }
    if not proxy_url:
        return info

    try:
        parsed = urlparse(proxy_url)
        host = parsed.hostname
        port = parsed.port
        if host and port:
            with socket.create_connection((host, port), timeout=1.2):
                info["proxy_reachable"] = True
                info["proxy_mode"] = "proxy-active"
        else:
            info["proxy_mode"] = "proxy-configured-invalid"
    except Exception:
        info["proxy_mode"] = "proxy-configured-unreachable"
    return info


def get_base_models():
    resp = requests.get(MODELS_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def get_yaml_models(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [m.get("model_name") for m in data.get("model_list", []) if m.get("model_name")]


def get_mykey_models(path: Path):
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"native_oai_config_copilot_.*?\s*=\s*\{.*?\}", text, flags=re.DOTALL)
    models = []
    for block in blocks:
        m = re.search(r"['\"]model['\"]\s*:\s*['\"](.*?)['\"]", block)
        if m:
            models.append(m.group(1))
    return models


def probe_model(model_id: str):
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "reply only pong"}],
        "stream": False,
    }
    try:
        resp = requests.post(CHAT_URL, json=payload, timeout=TIMEOUT)
        ok = 200 <= resp.status_code < 300
        err = "" if ok else (resp.text or "")[:180]
        return {"status": resp.status_code, "success": ok, "error": err}
    except Exception as e:
        return {"status": 0, "success": False, "error": str(e)[:180]}


def render_litellm_config(models):
    groups = {}
    for model in models:
        spec = MODEL_SPECS[model]
        groups.setdefault(spec["section"], []).append(model)

    lines = ["model_list:"]
    for section in ["OpenAI Models", "Anthropic Models", "Google Models"]:
        section_models = groups.get(section, [])
        if not section_models:
            continue
        lines.append(f"  # {section}")
        for model in section_models:
            spec = MODEL_SPECS[model]
            lines.extend([
                f"  - model_name: {model}",
                "    litellm_params:",
                f"      model: {spec['backend_model']}",
                f"      api_key: {TOKEN_REF}",
                "      extra_headers:",
                *HEADER_LINES,
                "",
            ])
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_mykey(models):
    config_blocks = [
        "\n".join([
            "# GLM-5 - DashScope 兼容模式 API（直连，不走代理）",
            "native_oai_config_dashscope_glm_5 = {",
            "    'name': 'dashscope-glm-5',",
            "    'apikey': os.environ.get('DASHSCOPE_API_KEY', ''),",
            "    'apibase': 'https://dashscope.aliyuncs.com/compatible-mode/v1',",
            "    'model': 'glm-5',",
            "    'api_mode': 'chat_completions',",
            "    'proxy': None,",
            "    'stream': True,",
            "}",
        ])
    ]
    for model in models:
        spec = MODEL_SPECS[model]
        config_blocks.append(
            "\n".join([
                f"# {spec['title']}",
                f"{spec['config_var']} = {{  ",
                f"    'name': '{spec['name']}',",
                "    'apikey': 'anything',",
                "    'apibase': 'http://localhost:8000/v1',",
                f"    'model': '{model}',",
                "    'api_mode': 'chat_completions',",
                "    'stream': True,",
                "}",
            ])
        )

    llm_nos = ["dashscope-glm-5"]
    if "gpt-4" in models:
        llm_nos.append("copilot-gpt4")
    if "claude-sonnet-4.5" in models:
        llm_nos.append("copilot-claude")
    if "gemini-2.5-pro" in models:
        llm_nos.append("copilot-gemini")

    lines = [
        "import os",
        "",
        "# ── GitHub Copilot Pro (多模型配置) ─────────────────────────────────────",
        "# 启动方式：先启动 litellm 代理（使用 .venv），然后在 UI 中选择模型",
        "# .venv\\Scripts\\litellm.exe --config litellm_config.yaml --port 8000",
        "",
        "\n\n".join(config_blocks),
        "",
        "# ── 模型自动轮询配置（已启用，仅使用当前已验证可用模型）────────────────────",
        "mixin_config = {",
        "    'llm_nos': [",
    ]
    for llm_name in llm_nos:
        comment = "首选：已验证可用" if llm_name == llm_nos[0] else "兜底：已验证可用"
        lines.append(f"        '{llm_name}',            # {comment}")
    lines.extend([
        "    ],",
        "    'max_retries': 4,              # 两模型间轮询重试，避免长时间无效重试",
        "    'base_delay': 0.5,             # 指数退避起始延迟",
        "}",
        "",
    ])
    return "\n".join(lines)


def apply_updates(models):
    supported = [m for m in models if m in MODEL_SPECS]
    Path("litellm_config.yaml").write_text(render_litellm_config(supported), encoding="utf-8")
    Path("mykey.py").write_text(render_mykey(supported), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Verify Copilot models and optionally apply available models.")
    parser.add_argument("--dry-run", action="store_true", help="Print the models that would be written without modifying files.")
    parser.add_argument("--apply", action="store_true", help="Write the currently available models back to litellm_config.yaml and mykey.py.")
    args = parser.parse_args()

    base_models = get_base_models()
    proxy_state = detect_proxy_state()
    yaml_models = get_yaml_models(Path("litellm_config.yaml"))
    mykey_models = get_mykey_models(Path("mykey.py"))

    diffs = {
        "base_minus_yaml": sorted(set(base_models) - set(yaml_models)),
        "yaml_minus_base": sorted(set(yaml_models) - set(base_models)),
        "mykey_minus_base": sorted(set(mykey_models) - set(base_models)),
        "base_minus_mykey": sorted(set(base_models) - set(mykey_models)),
    }

    results = {m: probe_model(m) for m in base_models}

    available_models = [m for m, result in results.items() if result["success"] and m in MODEL_SPECS]

    output = {
        "proxy_state": proxy_state,
        "base_models": base_models,
        "yaml_models": yaml_models,
        "mykey_models": mykey_models,
        "diffs": diffs,
        "test_results": results,
        "available_models": available_models,
    }

    if args.dry_run or args.apply:
        output["would_apply_models"] = available_models
    if args.apply:
        apply_updates(available_models)
        output["applied"] = True

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
