#!/usr/bin/env python3
"""
knowledge_inject_trigger.py — 任务启动时的知识注入触发器

在开始执行 TODO 任务前调用此脚本，自动从 TODO.txt 提取关键词，
匹配 knowledge_assets 中的相关模式(pattern)和陷阱(trap)，输出注入内容。

用法:
    python scripts/knowledge_inject_trigger.py              # 从TODO.txt自动提取关键词
    python scripts/knowledge_inject_trigger.py "vision"     # 手动指定查询词
    python scripts/knowledge_inject_trigger.py --verbose    # 详细输出(含匹配过程)

集成到工作流:
    在 autonomous_operation_sop.md 的 "执行" 部分加入:
    ```
    # 任务前注入知识
    python scripts/knowledge_inject_trigger.py
    ```
    或:
    ```
    from memory.tools.knowledge_mgmt import inject_print
    inject_print()
    ```
"""

import sys
import os

# Ensure we're in project root
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, '.')
from memory.tools.knowledge_mgmt import inject_print, inject


def main():
    verbose = '--verbose' in sys.argv
    query = None
    
    # Parse arguments
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if args:
        query = args[0]
    
    # Run injection
    if verbose:
        print("=" * 60)
        print("🔍 知识注入触发器 — 准备任务知识上下文")
        if query:
            print(f"查询词: {query}")
        else:
            print("查询源: TODO.txt (自动提取关键词)")
        print("=" * 60)
        print()
    
    result = inject_print(query)
    
    if verbose and result:
        print()
        print(f"📊 统计: {len(result.get('matched_patterns', []))} 模式 + "
              f"{len(result.get('matched_traps', []))} 陷阱")
        
        # Also print keywords used
        keywords = result.get('query_keywords', [])
        if keywords:
            print(f"🏷️  关键词: {', '.join(keywords)}")
    
    return result


if __name__ == '__main__':
    result = main()
    # Return exit code based on whether any matches found
    if result and (result.get('matched_patterns') or result.get('matched_traps')):
        sys.exit(0)
    else:
        sys.exit(1)
