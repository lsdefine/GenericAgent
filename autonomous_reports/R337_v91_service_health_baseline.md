# R337: v91#4 本机服务长稳健康基线

## 交付物

### 1. 服务健康采集脚本
- `temp/service_health_collector.py`
- 监控6个已知TCP服务: openllm(11343), 9router(20128), code-server(9090), nanobot-api(8900), nanobot-gateway(18790), chromedriver(54399)
- 测量: 连通性(up/down) + 连接延迟(ms) + HTTP状态码(如适用)
- 模式: `采集(默认)` / `--report(趋势报告)` / `--cron(采集+报告)`
- 数据: `temp/service_health.jsonl` (JSONL格式, 持续追加)

### 2. 每5分钟cron采集
```
*/5 * * * * cd /home/admin/GenericAgent && python3 temp/service_health_collector.py --cron >> temp/service_health_cron.log 2>&1
```

## 验收

| 验收项 | 结果 |
|--------|------|
| 6服务端口探测 | ✅ openllm=5.6ms/200, 9router=17.2ms/404, code-server=316.5ms/401, nanobot-api=11.9ms/200, nanobot-gateway=2.5ms/200, chromedriver=2.6ms/TCP |
| 趋势报告 | ✅ 可用率100%, avg/max延迟, 宕机事件 |
| cron每5min | ✅ 已注册到crontab |
| 24h报告待产出 | ⏳ cron持续采集中，24h后手动 `--report` 获取 |

## 初始基线 (2026-06-07 04:01)
```
openllm         | 100.0% | avg=4.9ms
9router         | 100.0% | avg=11.5ms  
code-server     | 100.0% | avg=116.2ms (含HTTP 401)
nanobot-api     | 100.0% | avg=5.3ms
nanobot-gateway | 100.0% | avg=2.9ms
chromedriver    | 100.0% | avg=0.1ms
```
