#!/bin/bash
# cron_python.sh — Cron环境下获取可靠Python解释器
# 用途: 在cron环境(PATH=/usr/bin:/bin)下返回兼容的python解释器
# 用法: PYTHON=$(bash cron_python.sh) 或直接作为前缀
#       或: scripts/cron_python.sh your_script.py [args...]
#
# 优先级:
#   1. /home/admin/.hermes/hermes-agent/venv/bin/python3.11 (Hermes venv, 有所有依赖)
#   2. /home/admin/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11
#   3. python3 (系统默认, 可能是3.6)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="/home/admin/.hermes/hermes-agent/venv/bin/python3.11"
UV_PYTHON="/home/admin/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11"

if [ -x "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
elif [ -x "$UV_PYTHON" ]; then
    PYTHON="$UV_PYTHON"
else
    PYTHON="python3"
fi

# If arguments provided, run as python script runner
if [ $# -ge 1 ]; then
    exec "$PYTHON" "$@"
else
    echo "$PYTHON"
fi
