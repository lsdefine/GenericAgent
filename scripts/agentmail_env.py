#!/usr/bin/env python3
"""
agentmail_env.py — 在环境中设置 AGENTMAIL_API_KEY

用法:
    python scripts/agentmail_env.py          # 打印 export 语句
    eval "$(python scripts/agentmail_env.py)" # 设置环境变量

集成到 .bashrc:
    source <(python ~/GenericAgent/scripts/agentmail_env.py)
"""

import os, sys

def main():
    # 尝试从 keychain 获取 AGENTMAIL_API_KEY
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from memory import keychain
        if hasattr(keychain, 'keys') and 'AGENTMAIL_API_KEY' in keychain.keys.ls():
            api_key = keychain.keys.AGENTMAIL_API_KEY.use()
            print(f'export AGENTMAIL_API_KEY="{api_key}"')
            return
    except Exception:
        pass
    
    # Fallback: 如果已有环境变量
    if os.environ.get('AGENTMAIL_API_KEY'):
        print(f'export AGENTMAIL_API_KEY="{os.environ["AGENTMAIL_API_KEY"]}"')
        return
    
    print("# AGENTMAIL_API_KEY not found. Use: python -c 'from memory.keychain import keys; keys.set(\"AGENTMAIL_API_KEY\", \"your_key\")'")
    sys.exit(1)

if __name__ == '__main__':
    main()
