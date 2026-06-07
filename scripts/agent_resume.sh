#!/bin/bash
# GenericAgent resume script — runs on startup/restart
# Automatically starts essential services
#
# v87#2: Integration with idle_guard → reset guard state on resume

GA_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "[agent_resume] GA root: $GA_ROOT"

# ─── TMWebDriver Master ──────────────────────────────────────────
# Auto-start if not already running (port 18766)
if ! ss -tlnp | grep -q ':18766'; then
    echo "[agent_resume] Starting TMWebDriver master..."
    nohup python3 "$GA_ROOT/scripts/start_tmwd_master.py" \
        > "$GA_ROOT/temp/tmwd_master.log" 2>&1 &
    echo "[agent_resume] TMWebDriver master launched (PID $!)"
else
    echo "[agent_resume] TMWebDriver master already running on :18766"
fi

# ─── idle_guard 集成 ────────────────────────────────────────────
# 恢复后重置守卫状态：记录行动时间 + 重置待命计数器
if [ -f "$GA_ROOT/scripts/idle_guard.sh" ]; then
    bash "$GA_ROOT/scripts/idle_guard.sh" record
    bash "$GA_ROOT/scripts/idle_guard.sh" reset
    echo "[agent_resume] ✅ idle_guard: 已记录恢复行动并重置计数器"
fi

# ─── SESSION-STATE 更新 ─────────────────────────────────────────
# 标记本次恢复
STATE_FILE="$GA_ROOT/temp/SESSION-STATE.md"
if [ -f "$STATE_FILE" ]; then
    echo "# SESSION-STATE (resumed at $(date '+%Y-%m-%d %H:%M'))" > "$STATE_FILE"
    echo "current_task: \"$(cat "$STATE_FILE" | grep 'current_task' | head -1 | cut -d: -f2-)\"" >> "$STATE_FILE"
    echo "progress: \"自动恢复 | $(date '+%Y-%m-%d %H:%M')\"" >> "$STATE_FILE"
fi

# ─── ga_watchdog 检查 ───────────────────────────────────────────
# 若crontab中无ga_watchdog，尝试安装
if ! crontab -l 2>/dev/null | grep -q 'ga_watchdog'; then
    echo "[agent_resume] ⚠️  ga_watchdog 不在crontab中，建议手动添加:"
    echo "  * * * * * cd $GA_ROOT && bash scripts/ga_watchdog.sh"
fi
