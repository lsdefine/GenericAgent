import yaml, json, re

# 1. Get models from yaml
with open('litellm_config.yaml', 'r') as f:
    yaml_data = yaml.safe_load(f)
yaml_models = [m['model_name'] for m in yaml_data.get('model_list', [])]

# 2. Get models from mykey.py
with open('mykey.py', 'r', encoding='utf-8') as f:
    mykey_content = f.read()
# Find all native_oai_config_copilot_... blocks and extract model field
blocks = re.findall(r'native_oai_config_copilot_.*?\s*=\s*\{.*?\}', mykey_content, re.DOTALL)
mykey_models = []
for block in blocks:
    m = re.search(r'[\'\"]model[\'\"]\s*:\s*[\'\"](.*?)[\'\"]', block)
    if m:
        mykey_models.append(m.group(1))

# 3. Comparison
missing_in_litellm = [m for m in mykey_models if m not in yaml_models]
missing_in_mykey = [m for m in yaml_models if m not in mykey_models]

print(json.dumps({
    'yaml_models': yaml_models,
    'mykey_models': mykey_models,
    'missing_in_litellm': missing_in_litellm,
    'missing_in_mykey': missing_in_mykey
}))
