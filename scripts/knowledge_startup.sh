#!/bin/bash
# knowledge_startup.sh — 任务启动时注入相关知识资产
# 用法: bash scripts/knowledge_startup.sh
# 在 autonomous_operation_sop 启动流程中调用（get_todo 后）
# 
# 2026-06-07 v1

cd /home/admin/GenericAgent
echo "=== 🔍 知识资产注入 ==="
python3 -c "
import sys
sys.path.insert(0, '.')
from memory.tools.knowledge_mgmt import inject_print
inject_print()
" 2>&1 || echo "⚠️ knowledge_mgmt 不可用，跳过注入"
echo "=== ✅ 注入完成 ==="
