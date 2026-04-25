import requests
import yaml
import json
import re
import os

def get_base_models():
    try:
        resp = requests.get("http://127.0.0.1:8000/v1/models", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return [m['id'] for m in data.get('data', [])]
    except Exception as e:
        pass
    return []

def get_yaml_models():
    try:
        with open("litellm_config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return [m['model_name'] for m in config.get('model_list', [])]
    except Exception as e:
        return []

def get_mykey_models():
    models = []
    try:
        if os.path.exists("mykey.py"):
            with open("mykey.py", "r", encoding="utf-8") as f:
                content = f.read()
                matches = re.finditer(r"native_oai_config_copilot_.*?=.*?\{.*?'model':\s*['\"](.*?)['\"]", content, re.DOTALL)
                for match in matches:
                    models.append(match.group(1))
    except Exception:
        pass
    return list(set(models))

def test_model(model_id):
    url = "http://127.0.0.1:8000/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "reply only pong"}],
        "stream": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        status = resp.status_code
        success = 200 <= status < 300
        error = "" if success else resp.text[:100]
        return {"status": status, "success": success, "error": error}
    except Exception as e:
        return {"status": 0, "success": False, "error": str(e)}

base_models = get_base_models()
yaml_models = get_yaml_models()
mykey_models = get_mykey_models()

diffs = {
    "base_minus_yaml": list(set(base_models) - set(yaml_models)),
    "yaml_minus_base": list(set(yaml_models) - set(base_models)),
    "mykey_minus_base": list(set(mykey_models) - set(base_models)),
    "base_minus_mykey": list(set(base_models) - set(mykey_models))
}

test_results = {}
if base_models:
    for m in base_models:
        test_results[m] = test_model(m)

output = {
    "base_models": base_models,
    "yaml_models": yaml_models,
    "mykey_models": mykey_models,
    "diffs": diffs,
    "test_results": test_results
}

print(json.dumps(output, indent=2))
