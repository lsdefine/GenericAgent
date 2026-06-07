#!/bin/bash
# ============================================================
# idle_guard.sh — 自主模式预检守卫
# 功能: 在每次[AUTO]触发前检查是否真正需要唤醒，实现退避
# 
# R190方案A实现: 减少57%深度待命
# 原理: 用一个轻量级shell检查状态，比唤醒LLM全栈便宜几个数量级
# ============================================================
# 用法:
#   bash scripts/idle_guard.sh check   → 返回 0 (需唤醒) 或 1 (跳过)
#   bash scripts/idle_guard.sh status  → 打印守卫状态
#   bash scripts/idle_guard.sh reset   → 重置计数器
# ============================================================
# 约定路径
GA_HOME="$HOME/GenericAgent"
STATE_DIR="${GA_HOME}/temp"
COUNTER_FILE="${STATE_DIR}/idle_counter.txt"
LAST_ACTION_FILE="${STATE_DIR}/idle_last_action.txt"
TODO_FILE="${STATE_DIR}/TODO.txt"

mkdir -p "${STATE_DIR}"

# ── 工具函数 ──

get_idle_count() {
    if [ -f "${COUNTER_FILE}" ]; then
        cat "${COUNTER_FILE}"
    else
        echo 0
    fi
}

set_idle_count() {
    echo "$1" > "${COUNTER_FILE}"
}

increment_idle() {
    local cur
    cur=$(get_idle_count)
    cur=$((cur + 1))
    set_idle_count "$cur"
    echo "$cur"
}

reset_idle() {
    set_idle_count 0
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 重置待命计数器 → 0" >> "${STATE_DIR}/idle_guard.log"
}

record_action() {
    date '+%s' > "${LAST_ACTION_FILE}"
}

time_since_last_action() {
    if [ -f "${LAST_ACTION_FILE}" ]; then
        local last=$(cat "${LAST_ACTION_FILE}")
        local now=$(date '+%s')
        echo $(( now - last ))
    else
        echo 99999
    fi
}

has_pending_todo() {
    if [ -f "${TODO_FILE}" ]; then
        # 检查是否有未完成的TODO条目（不含已完成的）
        if grep -q '^\[ \]' "${TODO_FILE}" 2>/dev/null; then
            return 0  # 有待办
        fi
    fi
    # 也检查根目录的TODO
    if [ -f "${GA_HOME}/TODO.txt" ]; then
        if grep -q '（待执行）' "${GA_HOME}/TODO.txt" 2>/dev/null; then
            return 0
        fi
    fi
    return 1  # 无待办
}

is_likely_active_session() {
    # 检查是否有agent正在运行的迹象
    # 1. 检查agentmain进程
    if pgrep -f "agentmain.py" > /dev/null 2>&1; then
        # 进一步检查是否刚启动（30分钟内）
        local pid
        pid=$(pgrep -f "agentmain.py" | head -1)
        if [ -n "$pid" ]; then
            local age_sec
            age_sec=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
            if [ -n "$age_sec" ] && [ "$age_sec" -lt 1800 ]; then
                return 0  # 活跃会话
            fi
        fi
    fi
    
    # 2. 检查health_server是否在运行 (作为有活跃工作的代理信号)
    if ! curl -s --connect-timeout 2 http://127.0.0.1:8081/api/health > /dev/null 2>&1; then
        # health_server不在运行，说明环境未准备好
        return 0  # 需要唤醒去启动服务
    fi
    
    return 1  # 无活跃会话
}

# ── 主逻辑 ──

case "${1:-check}" in
    check)
        IDLE_COUNT=$(get_idle_count)
        TIME_SINCE=$(time_since_last_action)
        
        # 日志
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] idle_guard check: idle=${IDLE_COUNT}, last_action=${TIME_SINCE}s ago" >> "${STATE_DIR}/idle_guard.log"
        
        # 规则1: 如果有待办TODO，需要唤醒
        if has_pending_todo; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] → 有待办，需唤醒" >> "${STATE_DIR}/idle_guard.log"
            reset_idle
            exit 0  # 需要唤醒
        fi
        
        # 规则2: 检查是否有活跃会话
        if is_likely_active_session; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] → 活跃会话存在，跳过" >> "${STATE_DIR}/idle_guard.log"
            increment_idle
            exit 1  # 跳过
        fi
        
        # 规则3: 指数退避 (R190)
        #   基数30分钟, 每多一次待命加倍: 30m → 1h → 2h → 4h → 8h(max)
        #   使用上次真实行动时间判断是否已过足够间隔
        BASE_MIN=30
        MAX_MIN=480  # 8h
        # bash整数位移: 30 * 2^IDLE_COUNT
        INTERVAL_MIN=$(( BASE_MIN * (1 << IDLE_COUNT) ))
        [ $INTERVAL_MIN -gt $MAX_MIN ] && INTERVAL_MIN=$MAX_MIN
        
        if [ "$TIME_SINCE" -lt $(( INTERVAL_MIN * 60 )) ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] → 退避: interval=${INTERVAL_MIN}m, elapsed=$((TIME_SINCE/60))m, need ${INTERVAL_MIN}m, skip" >> "${STATE_DIR}/idle_guard.log"
            increment_idle
            # 防止计数器无限增长
            if [ "$(get_idle_count)" -gt 10 ]; then
                set_idle_count 5
            fi
            exit 1  # 跳过
        fi
        
        # 默认: 需要唤醒
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] → 默认唤醒" >> "${STATE_DIR}/idle_guard.log"
        reset_idle
        exit 0
        ;;
    
    status)
        echo "=== idle_guard 状态 ==="
        echo "待命计数器: $(get_idle_count)"
        echo "上次行动: $(if [ -f "${LAST_ACTION_FILE}" ]; then date -d "@$(cat ${LAST_ACTION_FILE})" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'unknown'; else echo 'never'; fi)"
        echo "待办存在: $(if has_pending_todo; then echo '是'; else echo '否'; fi)"
        echo "活跃会话: $(if is_likely_active_session; then echo '是'; else echo '否'; fi)"
        echo ""
        echo "=== TODO状态 ==="
        if [ -f "${TODO_FILE}" ]; then
            echo "⊙ temp/TODO.txt:"
            grep '^\[ \]' "${TODO_FILE}" 2>/dev/null | head -3 || echo "  无未完成项"
        fi
        if [ -f "${GA_HOME}/TODO.txt" ]; then
            echo "⊙ TODO.txt(根):"
            grep '（待执行）' "${GA_HOME}/TODO.txt" 2>/dev/null | head -3 || echo "  无未完成项"
        fi
        echo ""
        echo "=== 最近日志 ==="
        tail -5 "${STATE_DIR}/idle_guard.log" 2>/dev/null || echo "  无"
        ;;
    
    reset)
        reset_idle
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 手动重置" >> "${STATE_DIR}/idle_guard.log"
        echo "✅ 已重置待命计数器"
        ;;
    
    record)
        record_action
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 记录行动" >> "${STATE_DIR}/idle_guard.log"
        echo "✅ 已记录行动时间"
        ;;
    
    *)
        echo "用法: bash scripts/idle_guard.sh {check|status|reset|record}"
        echo "  check  → 返回 0 (需唤醒) 或 1 (跳过)"
        echo "  status → 打印守卫状态"
        echo "  reset  → 重置待命计数器"
        echo "  record → 记录当前时间为最近行动"
        exit 1
        ;;
esac
