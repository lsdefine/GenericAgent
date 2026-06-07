# R405: 自愈看门狗扩展 (v115#4)

## 概述
为 AgentMail + Hermes Gateway (8901/8902) 添加 health_unified.sh 同款看门狗，实现进程DOWN后≤2min自动恢复。

## 改动清单

### 1. `scripts/health_unified.sh`
- **1.6 Hermes Gateway 看门狗** (Line 85-122)
  - 8901标准代理: pgrep检测+重启, HTTP 404健康检查
  - 8902直连模式: pgrep检测+重启, HTTP 308健康检查
  
- **1.7 AgentMail 看门狗** (Line 124-135)
  - AgentMail原为sche_task每10min轮询，改为`--watch`持久daemon模式
  - pgrep检测进程存活，DOWN后自动重启

### 2. AgentMail daemon化
- 启动 `scripts/agentmail_cmd_handler.py --watch` 作为持久进程
- 每60s轮询收件箱，替代原sche_task每10min触发

### 3. 测试验证
- 测试脚本: `bash temp/test_watchdog.sh` (已清理)
- AgentMail: PID 763811 → kill → 看门狗检测 → 重启 → PID 764123 ✅
- Hermes 8902: PID 763797 → kill → 看门狗检测 → 重启 → PID 764150 ✅
- Hermes 8901: 全程稳定运行 ✅
- 最终状态: 3服务均 ✅ RUN

## 验收标准
| 标准 | 结果 |
|------|------|
| AgentMail看门狗注入 | ✅ health_unified.sh Line 124-135 |
| Hermes Gateway 8901看门狗 | ✅ health_unified.sh Line 87-103 |
| Hermes Gateway 8902看门狗 | ✅ health_unified.sh Line 106-122 |
| 模拟DOWN后≤2min自动恢复 | ✅ 测试通过 |
