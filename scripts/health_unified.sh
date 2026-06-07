#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# health_unified.sh — 统一健康检查入口 (v110#6)
# 整合: ga_watchdog.sh + memory_pressure_monitor + hermes_health + service_health
# 用法: bash scripts/health_unified.sh
# Cron: */2 * * * * cd /home/admin/GenericAgent && bash scripts/health_unified.sh >> temp/health_unified.log 2>&1
# ═══════════════════════════════════════════════════════════════

GA_HOME="$HOME/GenericAgent"
PYTHON="$GA_HOME/.venv/bin/python3"
LOG="$GA_HOME/temp/health_unified.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "═══════ 统一健康检查开始 ═══════"

# ── 1. Watchdog: 检查并重启OOM进程 ──
log "▶ Watchdog: 检查GA进程..."
need_restart=0

# fsapp
if ! pgrep -f "python3.*frontends/fsapp.py" > /dev/null 2>&1; then
    log "  ⚠️  fsapp 未运行，正在启动..."
    cd "$GA_HOME"
    PYTHONUNBUFFERED=1 GA_LANG=zh nohup "$PYTHON" frontends/fsapp.py > temp/fsapp.log 2>&1 &
    sleep 2
    if pgrep -f "python3.*frontends/fsapp.py" > /dev/null 2>&1; then
        log "  ✅ fsapp 已启动"
    else
        log "  ❌ fsapp 启动失败"
    fi
    need_restart=1
fi

# scheduler
if ! pgrep -f "agentmain.py.*--reflect.*scheduler" > /dev/null 2>&1; then
    log "  ⚠️  scheduler 未运行，正在启动..."
    cd "$GA_HOME"
    PYTHONUNBUFFERED=1 GA_LANG=zh nohup "$PYTHON" agentmain.py --reflect reflect/scheduler.py > temp/scheduler.log 2>&1 &
    sleep 2
    if pgrep -f "agentmain.py.*--reflect.*scheduler" > /dev/null 2>&1; then
        log "  ✅ scheduler 已启动"
    else
        log "  ❌ scheduler 启动失败"
    fi
    need_restart=1
fi

# autonomous
if ! pgrep -f "agentmain.py.*--reflect.*autonomous" > /dev/null 2>&1; then
    log "  ⚠️  autonomous 未运行，正在启动..."
    cd "$GA_HOME"
    PYTHONUNBUFFERED=1 GA_LANG=zh nohup "$PYTHON" agentmain.py --reflect reflect/autonomous.py > temp/autonomous.log 2>&1 &
    sleep 2
    if pgrep -f "agentmain.py.*--reflect.*autonomous" > /dev/null 2>&1; then
        log "  ✅ autonomous 已启动"
    else
        log "  ❌ autonomous 启动失败"
    fi
    need_restart=1
fi

if [ "$need_restart" -eq 1 ]; then
    if [ -f "$GA_HOME/scripts/idle_guard.sh" ]; then
        bash "$GA_HOME/scripts/idle_guard.sh" record
        log "  ✅ idle_guard: 已记录恢复行动"
    fi
    log "  📊 状态: fsapp=$(pgrep -f 'frontends/fsapp.py' >/dev/null 2>&1 && echo 'RUN' || echo 'DOWN') scheduler=$(pgrep -f 'agentmain.py.*--reflect.*scheduler' >/dev/null 2>&1 && echo 'RUN' || echo 'DOWN') autonomous=$(pgrep -f 'agentmain.py.*--reflect.*autonomous' >/dev/null 2>&1 && echo 'RUN' || echo 'DOWN')"
fi

# ── 1.5 健康Dashboard看门狗 ──
if ! curl -s -o /dev/null -w "%{http_code}" http://localhost:8899/ 2>/dev/null | grep -q "200\|302"; then
    log "  ⚠️  健康Dashboard (8899) 未响应，正在重启..."
    bash "$GA_HOME/scripts/start_health_dashboard.sh" 2>&1 | while read line; do log "  dash: $line"; done
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:8899/ 2>/dev/null | grep -q "200\|302"; then
        log "  ✅ 健康Dashboard已恢复"
    else
        log "  ❌ 健康Dashboard重启失败，查看日志: /tmp/health_server.log"
    fi
fi

# ── 1.6 Hermes Gateway 看门狗 (v115#4) ──
# 8901 标准代理
if ! pgrep -f "hermes_api_proxy.py.*--port 8901" > /dev/null 2>&1; then
    log "  ⚠️  Hermes Gateway (8901) 未运行，正在启动..."
    cd "$GA_HOME"
    nohup "$PYTHON" scripts/hermes_api_proxy.py --port 8901 > temp/hermes_8901.log 2>&1 &
    sleep 2
    if pgrep -f "hermes_api_proxy.py.*--port 8901" > /dev/null 2>&1; then
        log "  ✅ Hermes Gateway (8901) 已启动"
    else
        log "  ❌ Hermes Gateway (8901) 启动失败"
    fi
else
    # HTTP健康检查
    http_code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8901/ 2>/dev/null || echo "000")
    if [ "$http_code" = "000" ]; then
        log "  ⚠️  Hermes Gateway (8901) HTTP无响应，检查进程..."
    fi
fi

# 8902 直连模式
if ! pgrep -f "hermes_api_proxy.py.*--direct.*--port 8902" > /dev/null 2>&1; then
    log "  ⚠️  Hermes Gateway (8902 direct) 未运行，正在启动..."
    cd "$GA_HOME"
    nohup python scripts/hermes_api_proxy.py --direct --port 8902 > temp/hermes_8902.log 2>&1 &
    sleep 2
    if pgrep -f "hermes_api_proxy.py.*--direct.*--port 8902" > /dev/null 2>&1; then
        log "  ✅ Hermes Gateway (8902 direct) 已启动"
    else
        log "  ❌ Hermes Gateway (8902 direct) 启动失败"
    fi
else
    # HTTP健康检查
    http_code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8902/ 2>/dev/null || echo "000")
    if [ "$http_code" = "000" ]; then
        log "  ⚠️  Hermes Gateway (8902) HTTP无响应，检查进程..."
    fi
fi

# ── 1.7 AgentMail 看门狗 (v115#4) ──
if ! pgrep -f "agentmail_cmd_handler.py.*--watch" > /dev/null 2>&1; then
    log "  ⚠️  AgentMail watch 未运行，正在启动..."
    cd "$GA_HOME"
    nohup "$PYTHON" scripts/agentmail_cmd_handler.py --watch > temp/agentmail_watch.log 2>&1 &
    sleep 2
    if pgrep -f "agentmail_cmd_handler.py.*--watch" > /dev/null 2>&1; then
        log "  ✅ AgentMail watch 已启动"
    else
        log "  ❌ AgentMail watch 启动失败"
    fi
fi

# ── 2. 内存压力监控 ──
log "▶ 内存压力监控..."
if [ -f "$GA_HOME/scripts/memory_pressure_monitor.py" ]; then
    "$PYTHON" "$GA_HOME/scripts/memory_pressure_monitor.py" --threshold 200 2>&1 | while read line; do log "  mem: $line"; done
else
    log "  ⚠️  memory_pressure_monitor.py 不存在，跳过"
fi

# ── 3. Hermes健康采集 ──
log "▶ Hermes健康采集..."
if [ -f "$GA_HOME/scripts/hermes_health_collector.py" ]; then
    "$PYTHON" "$GA_HOME/scripts/hermes_health_collector.py" --cron 2>&1 | while read line; do log "  hermes: $line"; done
else
    log "  ⚠️  hermes_health_collector.py 不存在，跳过"
fi

# ── 4. 服务健康采集 ──
log "▶ 服务健康采集..."
if [ -f "$GA_HOME/temp/service_health_collector.py" ]; then
    "$PYTHON" "$GA_HOME/temp/service_health_collector.py" --cron 2>&1 | while read line; do log "  svc: $line"; done
else
    log "  ⚠️  service_health_collector.py 不存在，跳过"
fi

log "═══════ 统一健康检查结束 ═══════"
exit 0
