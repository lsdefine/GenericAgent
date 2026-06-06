#!/bin/bash
# ============================================================
# 周心跳脚本
# 由 crontab 每周一 9:00 触发
# 功能: 记录GA活动心跳，确认系统正常运行
# ============================================================
set -e
GA_HOME="$HOME/GenericAgent"
DATE=$(date '+%Y-%m-%d %H:%M:%S')
LOG="${GA_HOME}/temp/heartbeat_weekly.log"

echo "[${DATE}] === GA心跳报告 ==="
echo "[${DATE}] 主机: $(hostname)"
echo "[${DATE}] 运行时间: $(uptime -p)"
echo "[${DATE}] 内核: $(uname -r)"
echo "[${DATE}] GA目录: ${GA_HOME}"
echo "[${DATE}] Git分支: $(cd ${GA_HOME} && git branch --show-current 2>/dev/null || echo 'unknown')"
echo "[${DATE}] 最近提交: $(cd ${GA_HOME} && git log --oneline -1 2>/dev/null || echo '无')"
echo "[${DATE}] 磁盘: $(df -h / | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')"
echo "[${DATE}] === 心跳完成 ==="

# 写入日志
DISK_INFO=$(df -h / | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')
echo "[${DATE}] === GA心跳报告 ===" >> "${LOG}"
echo "[${DATE}] 主机: $(hostname)" >> "${LOG}"
echo "[${DATE}] 运行时间: $(uptime -p)" >> "${LOG}"
echo "[${DATE}] 磁盘: ${DISK_INFO}" >> "${LOG}"
echo "[${DATE}] === 心跳完成 ===" >> "${LOG}"
