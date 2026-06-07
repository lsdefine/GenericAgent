#!/bin/bash
# start_health_dashboard.sh — 启动健康看板HTTP服务
# 用途: 确保 health_dashboard_server.py 在后台运行
# 可被 cron/sche_task/agent_resume.sh 调用

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${SCRIPT_DIR}/temp/health_server.pid"
PORT=8899

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "健康看板已在运行 (PID: $OLD_PID), 端口: $PORT"
        exit 0
    fi
    echo "过期PID文件, 移除"
    rm -f "$PID_FILE"
fi

# Start server
cd "$SCRIPT_DIR"
nohup python3 scripts/health_dashboard_server.py --port "$PORT" > /tmp/health_server.log 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
sleep 2

# Verify
if kill -0 "$NEW_PID" 2>/dev/null; then
    echo "✅ 健康看板已启动 (PID: $NEW_PID), 端口: $PORT"
    echo "   访问: http://localhost:$PORT/"
else
    echo "❌ 启动失败, 查看日志: /tmp/health_server.log"
    cat /tmp/health_server.log
    exit 1
fi
