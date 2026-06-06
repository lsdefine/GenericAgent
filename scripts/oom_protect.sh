#!/bin/bash
# oom_protect.sh - OOM防护配置脚本
# 用途: 设置进程OOM优先级 + 内存限制 + sysctl调优
# 用法: bash scripts/oom_protect.sh [apply|status]
# 适用: v108 OOM根因修复

ACTION="${1:-status}"

case "$ACTION" in
  apply)
    echo "=== 应用OOM防护配置 ==="

    # 1. 保护关键服务不被OOM killer优先杀死
    # hermes gateway (最大内存消费者, 当前391MB)
    for pid in $(pgrep -f "hermes_cli.main gateway" 2>/dev/null); do
      echo -500 > /proc/$pid/oom_score_adj 2>/dev/null && \
        echo "  ✅ hermes gateway PID=$pid → oom_score_adj=-500 (受保护)"
    done

    # fsapp (160MB)
    for pid in $(pgrep -f "frontends/fsapp.py" 2>/dev/null); do
      echo -200 > /proc/$pid/oom_score_adj 2>/dev/null && \
        echo "  ✅ fsapp PID=$pid → oom_score_adj=-200 (受保护)"
    done

    # nanobot serve (119MB)
    for pid in $(pgrep -f "nanobot serve" 2>/dev/null); do
      echo -100 > /proc/$pid/oom_score_adj 2>/dev/null && \
        echo "  ✅ nanobot serve PID=$pid → oom_score_adj=-100 (受保护)"
    done

    # agentmain reflect (自治Agent, 37MB)
    for pid in $(pgrep -f "agentmain.py.*--reflect" 2>/dev/null); do
      echo -300 > /proc/$pid/oom_score_adj 2>/dev/null && \
        echo "  ✅ agentmain PID=$pid → oom_score_adj=-300 (受保护)"
    done

    # 2. chromium-browse标记为优先牺牲 (oom_score_adj 提高)
    # 默认已200-300, 但这里确保一致性
    for pid in $(pgrep -f "chromium-browse\|chromium.*headless" 2>/dev/null); do
      echo 500 > /proc/$pid/oom_score_adj 2>/dev/null && \
        echo "  ⚠️  chromium PID=$pid → oom_score_adj=500 (优先回收)"
    done

    # 3. 设置vm.swappiness (当前0, 太保守, 设为10以主动使用swap缓解压力)
    sysctl -w vm.swappiness=10 2>/dev/null && \
      echo "  ✅ vm.swappiness=10 (适度使用swap)"
    # 持久化
    if grep -q "vm.swappiness" /etc/sysctl.conf 2>/dev/null; then
      sed -i 's/vm.swappiness=.*/vm.swappiness=10/' /etc/sysctl.conf 2>/dev/null
    else
      echo "vm.swappiness=10" >> /etc/sysctl.conf 2>/dev/null
    fi

    echo ""
    echo "=== 当前OOM配置 ==="
    echo "vm.swappiness=$(sysctl -n vm.swappiness)"
    for pid in $(pgrep -f "hermes_cli\|frontends/fsapp\|nanobot serve\|agentmain.*reflect\|chromium" 2>/dev/null); do
      name=$(cat /proc/$pid/comm 2>/dev/null)
      adj=$(cat /proc/$pid/oom_score_adj 2>/dev/null)
      echo "  $name PID=$pid adj=$adj"
    done
    ;;

  status)
    echo "=== OOM防护状态 ==="
    echo "vm.swappiness=$(sysctl -n vm.swappiness)"
    echo ""
    echo "关键进程oom_score_adj:"
    for pattern in "hermes_cli.main gateway" "frontends/fsapp" "nanobot serve" "agentmain.*reflect" "chromium"; do
      for pid in $(pgrep -f "$pattern" 2>/dev/null); do
        name=$(cat /proc/$pid/comm 2>/dev/null)
        adj=$(cat /proc/$pid/oom_score_adj 2>/dev/null)
        rss=$(grep VmRSS /proc/$pid/status 2>/dev/null | awk '{print $2}')
        echo "  $name PID=$pid adj=$adj RSS=$((${rss:-0}/1024))MB"
      done
    done
    echo ""
    echo "总OOM事件: $(dmesg 2>/dev/null | grep -c 'oom_kill\|OOM')"
    ;;

  *)
    echo "用法: $0 [apply|status]"
    exit 1
    ;;
esac
