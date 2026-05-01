import argparse
import json
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

try:
    import winreg
except Exception:
    winreg = None


TIMEOUT = 15

PROFILE_SPECS = [
    {
        "alias": "copilot-gpt4",
        "config_var": "native_oai_config_copilot_gpt4",
        "section": "OpenAI Models",
        "preferred_models": ["gpt-5.4", "gpt-5.2", "gpt-5-mini", "gpt-4.1", "gpt-4o", "gpt-4"],
        "titles": {
            "gpt-5.4": "GPT-5.4 - 当前可用最高版本",
            "gpt-5.2": "GPT-5.2 - 高能力版本",
            "gpt-5-mini": "GPT-5 Mini - 轻量高版本",
            "gpt-4.1": "GPT-4.1 - 稳定增强版本",
            "gpt-4o": "GPT-4o - 多模态版本",
            "gpt-4": "GPT-4 - 兼容兜底版本",
        },
    },
    {
        "alias": "copilot-claude",
        "config_var": "native_oai_config_copilot_claude",
        "section": "Anthropic Models",
        "preferred_models": ["claude-sonnet-4.6", "claude-sonnet-4.5", "claude-sonnet-4", "claude-haiku-4.5"],
        "titles": {
            "claude-sonnet-4.6": "Claude Sonnet 4.6 - 当前可用最高 Sonnet 版本",
            "claude-sonnet-4.5": "Claude Sonnet 4.5 - 长上下文支持 (200K+)",
            "claude-sonnet-4": "Claude Sonnet 4 - 兼容兜底版本",
            "claude-haiku-4.5": "Claude Haiku 4.5 - 轻量 Claude 版本",
        },
    },
    {
        "alias": "copilot-gemini",
        "config_var": "native_oai_config_copilot_gemini",
        "section": "Google Models",
        "preferred_models": ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-3-flash-preview"],
        "titles": {
            "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview - 当前可用最高版本",
            "gemini-2.5-pro": "Gemini 2.5 Pro - 稳定多模态版本",
            "gemini-3-flash-preview": "Gemini 3 Flash Preview - 轻量高版本",
        },
    },
]

MODEL_TO_PROFILE = {
    model: profile
    for profile in PROFILE_SPECS
    for model in profile["preferred_models"]
}

HEADER_LINES = [
    '        Editor-Version: "vscode/1.95.0"',
    '        Editor-Plugin-Version: "copilot-chat/0.26.7"',
    '        Copilot-Integration-Id: "vscode-chat"',
    '        User-Agent: "GitHubCopilotChat/0.26.7"',
]
TOKEN_REF = "os.environ/GITHUB_COPILOT_TOKEN"


def _all_candidate_models():
    models = []
    for profile in PROFILE_SPECS:
        for model in profile["preferred_models"]:
            if model not in models:
                models.append(model)
    return models


def _profile_for_model(model_id):
    return MODEL_TO_PROFILE.get(model_id)


def _title_for_model(model_id):
    profile = _profile_for_model(model_id)
    if not profile:
        return model_id
    return profile["titles"].get(model_id, model_id)


def _selected_alias_targets(models):
    pairs = []
    for model in models:
        profile = _profile_for_model(model)
        if not profile:
            continue
        pairs.append({"alias": profile["alias"], "model": model})
    return pairs


def select_preferred_models(results):
    selected = []
    for profile in PROFILE_SPECS:
        for model in profile["preferred_models"]:
            if results.get(model, {}).get("success"):
                selected.append(model)
                break
    return selected


def _resolve_wininet_proxy_url():
    if os.name != "nt" or winreg is None:
        return ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if int(proxy_enable) != 1 or not proxy_server:
            return ""

        value = str(proxy_server).strip()
        if "=" in value:
            mapping = {}
            for part in value.split(";"):
                if "=" in part:
                    key_part, value_part = part.split("=", 1)
                    mapping[key_part.strip().lower()] = value_part.strip()
            value = mapping.get("https") or mapping.get("http") or next(iter(mapping.values()), "")

        if value and "://" not in value:
            value = "http://" + value
        return value
    except Exception:
        return ""


def detect_proxy_state():
    wininet_url = _resolve_wininet_proxy_url()
    env_proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("GA_PROXY_URL")
        or ""
    )
    proxy_url = wininet_url or env_proxy_url
    info = {
        "proxy_env_url": proxy_url,
        "proxy_source": "wininet" if wininet_url else ("env" if env_proxy_url else "none"),
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
        if not (host and port):
            info["proxy_mode"] = "proxy-configured-invalid"
            return info

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            info["proxy_reachable"] = True
            info["proxy_mode"] = "proxy-configured"
        else:
            info["proxy_reachable"] = False
            info["proxy_mode"] = "proxy-configured-unreachable"
    except Exception:
        info["proxy_mode"] = "proxy-configured-unreachable"
    return info


def _get_copilot_runtime():
    token_dir = Path(
        os.getenv(
            "GITHUB_COPILOT_TOKEN_DIR",
            os.path.expanduser("~/.config/litellm/github_copilot"),
        )
    )
    api_key_file = token_dir / os.getenv("GITHUB_COPILOT_API_KEY_FILE", "api-key.json")
    data = json.loads(api_key_file.read_text(encoding="utf-8"))
    api_key = data["token"]
    api_base = (
        data.get("endpoints", {}).get("api")
        or os.getenv("GITHUB_COPILOT_API_BASE")
        or "https://api.githubcopilot.com"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
        "copilot-integration-id": "vscode-chat",
        "editor-version": "vscode/1.95.0",
        "editor-plugin-version": "copilot-chat/0.26.7",
        "user-agent": "GitHubCopilotChat/0.26.7",
        "openai-intent": "conversation-panel",
        "x-github-api-version": "2025-04-01",
    }
    return api_base.rstrip("/"), headers


def get_base_models():
    api_base, headers = _get_copilot_runtime()
    resp = requests.get(f"{api_base}/models", headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    visible = []
    for model in data.get("data", []):
        model_id = model.get("id")
        if not model_id or model_id not in MODEL_TO_PROFILE or model_id in visible:
            continue
        visible.append(model_id)
    return visible


def get_yaml_models(path: Path):
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [model.get("model_name") for model in data.get("model_list", []) if model.get("model_name")]


def get_mykey_models(path: Path):
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"native_oai_config_copilot_.*?\s*=\s*\{.*?\}", text, flags=re.DOTALL)
    models = []
    for block in blocks:
        match = re.search(r"['\"]model['\"]\s*:\s*['\"](.*?)['\"]", block)
        if match:
            models.append(match.group(1))
    return models


def probe_model(model_id: str):
    api_base, headers = _get_copilot_runtime()
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "reply only pong"}],
        "stream": False,
    }
    try:
        resp = requests.post(f"{api_base}/chat/completions", headers=headers, json=payload, timeout=TIMEOUT)
        ok = 200 <= resp.status_code < 300
        err = "" if ok else (resp.text or "")[:180]
        return {"status": resp.status_code, "success": ok, "error": err}
    except Exception as e:
        return {"status": 0, "success": False, "error": str(e)[:180]}


def render_litellm_config(models):
    groups = {}
    for model in models:
        profile = _profile_for_model(model)
        if not profile:
            continue
        groups.setdefault(profile["section"], []).append(model)

    lines = ["model_list:"]
    for section in ["OpenAI Models", "Anthropic Models", "Google Models"]:
        section_models = groups.get(section, [])
        if not section_models:
            continue
        lines.append(f"  # {section}")
        for model in section_models:
            profile = _profile_for_model(model)
            lines.extend([
                f"  - model_name: {model}",
                "    litellm_params:",
                f"      model: github_copilot/{model}",
                f"      api_key: {TOKEN_REF}",
                "      extra_headers:",
                *HEADER_LINES,
                "",
            ])
    if lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _supported_copilot_names(models):
    names = []
    for model in models:
        profile = _profile_for_model(model)
        if not profile:
            continue
        if profile["alias"] not in names:
            names.append(profile["alias"])
    return names


def _render_copilot_blocks(models):
    blocks = []
    for model in models:
        profile = _profile_for_model(model)
        if not profile:
            continue
        blocks.append(
            "\n".join([
                f"# {_title_for_model(model)}",
                f"{profile['config_var']} = {{  ",
                f"    'name': '{profile['alias']}',",
                "    'apikey': 'anything',",
                "    'apibase': 'http://localhost:8000/v1',",
                f"    'model': '{model}',",
                "    'api_mode': 'chat_completions',",
                "    'stream': True,",
                "}",
            ])
        )
    return ("\n\n".join(blocks) + "\n\n") if blocks else ""


def update_mykey_text(original_text, supported_models):
    supported_models = [model for model in supported_models if model in MODEL_TO_PROFILE]
    supported_names = set(_supported_copilot_names(supported_models))

    mixin_match = re.search(r"mixin_config\s*=\s*\{[\s\S]*?\n\}", original_text)
    if mixin_match:
        mixin_block = mixin_match.group(0)
        llm_nos_match = re.search(r"('llm_nos'\s*:\s*\[)([\s\S]*?)(\])", mixin_block)
        if llm_nos_match:
            existing_names = re.findall(r"['\"]([^'\"]+)['\"]", llm_nos_match.group(2))
            new_names = []
            for name in existing_names:
                if name.startswith("copilot-") and name not in supported_names:
                    continue
                if name not in new_names:
                    new_names.append(name)
            for name in _supported_copilot_names(supported_models):
                if name not in new_names:
                    new_names.append(name)
            rebuilt_names = "\n" + "\n".join(f"        '{name}'," for name in new_names) + "\n    "
            mixin_block = mixin_block[:llm_nos_match.start(2)] + rebuilt_names + mixin_block[llm_nos_match.end(2):]
            original_text = original_text[:mixin_match.start()] + mixin_block + original_text[mixin_match.end():]

    replacement = _render_copilot_blocks(supported_models)
    block_pattern = re.compile(r"(?:\n?# .*?\nnative_oai_config_copilot_[\s\S]*?\n\}\n?)+", re.MULTILINE)
    match = block_pattern.search(original_text)
    if match:
        original_text = original_text[:match.start()] + ("\n" + replacement if replacement else "\n") + original_text[match.end():]
    elif replacement:
        insert_at = original_text.find("# ══════")
        if insert_at == -1:
            insert_at = len(original_text)
        original_text = original_text[:insert_at].rstrip() + "\n\n" + replacement + original_text[insert_at:]

    return original_text


def apply_updates(models, litellm_config_path=None, mykey_path=None, allow_empty=False):
    supported = [model for model in models if model in MODEL_TO_PROFILE]
    if not supported and not allow_empty:
        raise ValueError(
            "Refusing to apply empty Copilot model set; keeping existing litellm_config.yaml and mykey.py unchanged."
        )

    litellm_config_path = Path(litellm_config_path or "litellm_config.yaml")
    mykey_path = Path(mykey_path or "mykey.py")
    litellm_config_path.write_text(render_litellm_config(supported), encoding="utf-8")

    original_text = mykey_path.read_text(encoding="utf-8")
    updated_text = update_mykey_text(original_text, supported)
    mykey_path.write_text(updated_text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Verify Copilot models and optionally apply available models.")
    parser.add_argument("--dry-run", action="store_true", help="Print the models that would be written without modifying files.")
    parser.add_argument("--apply", action="store_true", help="Write the currently available models back to litellm_config.yaml and mykey.py.")
    parser.add_argument("--quiet", action="store_true", help="Print only a compact one-line summary.")
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
    results = {model: probe_model(model) for model in _all_candidate_models()}
    available_models = [model for model, result in results.items() if result["success"]]
    selected_models = select_preferred_models(results)
    output = {
        "proxy_state": proxy_state,
        "base_models": base_models,
        "yaml_models": yaml_models,
        "mykey_models": mykey_models,
        "diffs": diffs,
        "test_results": results,
        "available_models": available_models,
        "selected_models": selected_models,
        "selected_aliases": _selected_alias_targets(selected_models),
    }

    if args.dry_run or args.apply:
        output["would_apply_models"] = selected_models
    if args.apply:
        try:
            apply_updates(selected_models)
            output["applied"] = True
        except Exception as e:
            output["applied"] = False
            output["apply_error"] = str(e)
            if args.quiet:
                print(json.dumps({"applied": False, "error": str(e)}, ensure_ascii=False))
            else:
                print(json.dumps(output, ensure_ascii=False, indent=2))
            raise SystemExit(1)

    if args.quiet:
        print(json.dumps({
            "selected_models": selected_models,
            "selected_aliases": _selected_alias_targets(selected_models),
            "applied": output.get("applied", False) if args.apply else None,
        }, ensure_ascii=False))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

