#!/usr/bin/env bash
# hermes_process_manager.sh - Hermes进程生命周期管理
# 功能: 
#   1. 健康检查 (RSS阈值检测)
#   2. 自动重启 (防止内存泄漏积累)
#   3. status查询
# Usage: bash scripts/hermes_process_manager.sh [check|restart|status|force_restart]
set -euo pipefail

HERMES_HOME="/home/admin/.hermes/hermes-agent"
VENV_PYTHON="$HERMES_HOME/venv/bin/python"
START_CMD="$VENV_PYTHON -m hermes_cli.main gateway run --replace"
PID_FILE="/tmp/hermes_gateway.pid"
RSS_THRESHOLD_MB=450  # 超过此值触发重启 (cgroup上限500MB)
RESTART_LOG="/home/admin/GenericAgent/temp/hermes_restart.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$RESTART_LOG"
}

get_pid() {
    pgrep -f "hermes_cli.main gateway run" 2>/dev/null | head -1 || echo ""
}

get_rss_mb() {
    local pid="$1"
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
        rss_kb=$(grep VmRSS /proc/$pid/status 2>/dev/null | awk '{print $2}')
        echo $((rss_kb / 1024))
    else
        echo 0
    fi
}

get_uptime_sec() {
    local pid="$1"
    if [ -n "$pid" ] && [ -d "/proc/$pid" ]; then
        echo $(($(date +%s) - $(stat -c %Y /proc/$pid 2>/dev/null || echo $(date +%s))))
    else
        echo 0
    fi
}

check() {
    local pid=$(get_pid)
    if [ -z "$pid" ]; then
        log "❌ Hermes NOT RUNNING"
        return 1
    fi
    local rss=$(get_rss_mb "$pid")
    local uptime_sec=$(get_uptime_sec "$pid")
    local uptime_str=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
    log "✅ Hermes running PID=$pid RSS=${rss}MB uptime=$uptime_str threshold=$RSS_THRESHOLD_MB MB"
    
    if [ "$rss" -gt "$RSS_THRESHOLD_MB" ]; then
        log "⚠️  RSS ${rss}MB > threshold ${RSS_THRESHOLD_MB}MB, triggering restart"
        restart
        return $?
    fi
    return 0
}

restart() {
    local old_pid=$(get_pid)
    log "🔄 Restarting Hermes (old PID=$old_pid)..."
    
    # Kill old process gracefully
    if [ -n "$old_pid" ]; then
        kill "$old_pid" 2>/dev/null || true
        sleep 2
        # Force kill if still running
        if [ -d "/proc/$old_pid" ]; then
            kill -9 "$old_pid" 2>/dev/null || true
            sleep 1
        fi
    fi
    
    # Start new instance
    nohup $START_CMD > /dev/null 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"
    
    # Wait and verify
    sleep 3
    local verify_pid=$(get_pid)
    if [ -n "$verify_pid" ]; then
        local rss=$(get_rss_mb "$verify_pid")
        log "✅ Restart OK: new PID=$verify_pid RSS=${rss}MB"
        # Re-add to cgroup (if exists)
        if [ -d "/sys/fs/cgroup/memory/GenericAgent/hermes" ]; then
            echo "$verify_pid" > /sys/fs/cgroup/memory/GenericAgent/hermes/cgroup.procs 2>/dev/null || true
        fi
        return 0
    else
        log "❌ Restart FAILED - hermes did not start"
        return 1
    fi
}

force_restart() {
    log "🔴 Force restart requested"
    restart
}

status() {
    local pid=$(get_pid)
    if [ -z "$pid" ]; then
        echo "Hermes: ❌ NOT RUNNING"
        return 1
    fi
    local rss=$(get_rss_mb "$pid")
    local uptime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs)
    echo "Hermes: ✅ RUNNING"
    echo "  PID:     $pid"
    echo "  RSS:     ${rss}MB / ${RSS_THRESHOLD_MB}MB threshold"
    echo "  Uptime:  $uptime"
    echo "  Cgroup:  $(cat /proc/$pid/cgroup 2>/dev/null | grep memory || echo 'none')"
}

case "${1:-status}" in
    check) check ;;
    restart) restart ;;
    force_restart) force_restart ;;
    status) status ;;
    *)
        echo "Usage: $0 [check|restart|force_restart|status]"
        exit 1
        ;;
esac
