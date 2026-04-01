"""Conftest to allow importing llmcore without mykey.py/mykey.json."""
import os
import json
import sys

# Create a minimal mykey.json so llmcore can be imported in test environments
_repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_mykey_path = os.path.join(_repo_dir, 'mykey.json')
if not os.path.exists(_mykey_path) and not os.path.exists(os.path.join(_repo_dir, 'mykey.py')):
    with open(_mykey_path, 'w') as f:
        json.dump({}, f)
    import atexit
    atexit.register(lambda: os.path.exists(_mykey_path) and os.unlink(_mykey_path))

# Create temp/ dir needed by _write_llm_log
_temp_dir = os.path.join(_repo_dir, 'temp')
os.makedirs(_temp_dir, exist_ok=True)
