#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# GenericAgent 看门狗 — 检查并自动重启被 OOM 杀死的进程
# 用法: bash scripts/ga_watchdog.sh
# 建议: 每 3 分钟运行一次 (cron)
# ═══════════════════════════════════════════════════════════════

GA_HOME="$HOME/GenericAgent"
PYTHON="$GA_HOME/.venv/bin/python3"
LOG="$GA_HOME/temp/watchdog.log"

# 端口锁 — scheduler 的 bind 端口
SCHEDULER_PORT=45762

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

need_restart=0

# ── 0. 前置: idle_guard 自愈信号 ─────────────────
# 若本轮任何服务重启，结束后记录行动→idle_guard可感知"系统刚恢复"
record_action_if_restarted() {
    if [ "$need_restart" -eq 1 ]; then
        if [ -f "$GA_HOME/scripts/idle_guard.sh" ]; then
            bash "$GA_HOME/scripts/idle_guard.sh" record
            log "✅ idle_guard: 已记录恢复行动"
        fi
    fi
}

# ── 1. fsapp (飞书前端) ──────────────────────────
if ! pgrep -f "python3.*frontends/fsapp.py" > /dev/null 2>&1; then
    log "⚠️  fsapp 未运行，正在启动..."
    cd "$GA_HOME"
    PYTHONUNBUFFERED=1 GA_LANG=zh nohup "$PYTHON" frontends/fsapp.py \
        > temp/fsapp.log 2>&1 &
    sleep 2
    if pgrep -f "python3.*frontends/fsapp.py" > /dev/null 2>&1; then
        log "✅ fsapp 已启动 (PID=$(pgrep -f 'frontends/fsapp.py' | head -1))"
    else
        log "❌ fsapp 启动失败"
    fi
    need_restart=1
fi

# ── 2. scheduler (任务调度器) ─────────────────────
# 检测方式：端口锁 或 agentmain.py --reflect scheduler
if ! pgrep -f "agentmain.py.*--reflect.*scheduler" > /dev/null 2>&1; then
    # 检查端口锁是否还活着
    if ! ss -tlnp | grep -q ":$SCHEDULER_PORT "; then
        log "⚠️  scheduler 未运行，正在启动..."
        cd "$GA_HOME"
        PYTHONUNBUFFERED=1 GA_LANG=zh nohup "$PYTHON" agentmain.py \
            --reflect reflect/scheduler.py \
            > temp/scheduler.log 2>&1 &
        sleep 2
        if pgrep -f "agentmain.py.*--reflect.*scheduler" > /dev/null 2>&1; then
            log "✅ scheduler 已启动 (PID=$(pgrep -f 'agentmain.py.*--reflect.*scheduler' | head -1))"
        else
            log "❌ scheduler 启动失败"
        fi
        need_restart=1
    else
        log "⚠️  scheduler 端口锁(%SCHEDULER_PORT) 仍存在但进程丢失，清理..."
        # 端口锁被残留占用，不需要额外操作，新进程会替换
    fi
fi

# ── 3. autonomous (自主智能体) ────────────────────
if ! pgrep -f "agentmain.py.*--reflect.*autonomous" > /dev/null 2>&1; then
    log "⚠️  autonomous 未运行，正在启动..."
    cd "$GA_HOME"
    PYTHONUNBUFFERED=1 GA_LANG=zh nohup "$PYTHON" agentmain.py \
        --reflect reflect/autonomous.py \
        > temp/autonomous.log 2>&1 &
    sleep 2
    if pgrep -f "agentmain.py.*--reflect.*autonomous" > /dev/null 2>&1; then
        log "✅ autonomous 已启动 (PID=$(pgrep -f 'agentmain.py.*--reflect.*autonomous' | head -1))"
    else
        log "❌ autonomous 启动失败"
    fi
    need_restart=1
fi

# ── 状态报告 ────────────────────────────────────
if [ "$need_restart" -eq 1 ]; then
    log "📊 当前状态: fsapp=$(pgrep -f 'frontends/fsapp.py' >/dev/null 2>&1 && echo 'RUN' || echo 'DOWN') \
scheduler=$(pgrep -f 'agentmain.py.*--reflect.*scheduler' >/dev/null 2>&1 && echo 'RUN' || echo 'DOWN') \
autonomous=$(pgrep -f 'agentmain.py.*--reflect.*autonomous' >/dev/null 2>&1 && echo 'RUN' || echo 'DOWN')"
fi

# ── 4. 后置: idle_guard联动 ──────────────────────
record_action_if_restarted

exit 0
