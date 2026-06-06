# R336: v91#3 benchmark趋势自动报警

## 交付物

### 1. `check_and_notify()` → benchmark_viz.py
- 新增函数: 加载trend → detect_anomalies + detect_success_anomalies → 调用`notify()`
- CLI: `python -m memory.tools.benchmark_viz --alert`
- exit code: 0=无异常, 1=有报警

### 2. 集成到每日基准管线
- `temp/run_benchmark_daily.sh` 新增第三步: benchmark运行后自动调 `--alert`
- 随每日 cron (0 5 * * *) 自动执行

## 验收

| 验收项 | 结果 |
|--------|------|
| 趋势退化自动检测 | ✅ detect_anomalies() 捕获4命令退化 |
| notify报警 | ✅ 4通道激活 (GA notify + 日志) |
| 集成benchmark运行后 | ✅ run_benchmark_daily.sh 第三步 |
| 异常详情输出 | ✅ 退化百分比+成功率异常+时间戳 |

## 测试输出
```
🚨 退化异常 (4 命令):
  chat_medium | +53% | chat_short | +48%
  doctor | +100%, +35% | gateway_status | +115%
⚠️ 成功率异常 (4 条): 含0%和50%
📊 通知通道: 4
```
