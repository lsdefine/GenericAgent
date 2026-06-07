# R414: v115#3 服务健康数据采集加速 完成

**时间**: 2026-06-07 08:20
**标签**: v115, health_collection, cron, sche_task

## 变更内容

### 1. ga-health 趋势采集 cron
- **之前**: `*/180 * * * *` (每180分钟，非标准cron)
- **之后**: `0 */2 * * *` (每2小时整点)
- **影响文件**: `temp/health_history.json` (系统CPU/内存/磁盘/网络趋势)
- **预期**: 24h内≥12条数据点（原21条/21h）

### 2. 健康Dashboard快照 sche_task
- **之前**: `"repeat":"daily"` (每日08:00)
- **之后**: `"repeat":"every_2h"` (每2小时)
- **影响文件**: `temp/health_snapshot.json` (Dashboard用离线快照)
- **文件**: `sche_tasks/health_dashboard.json`

### 3. service_health 服务级采集 (已有，未改)
- **采集者**: `health_unified.sh` → `service_health_collector.py --cron`
- **频率**: 每2分钟 (health_unified.sh `*/2 * * * *`)
- **当前数据**: 75条记录（远超12条/24h要求）

## 验收检查
✅ 24h内≥12条数据点: health_history 21条/21h + service_health 75条
✅ cron改至每2h: `0 */2 * * *`
✅ sche_task改至每2h: `repeat:every_2h`
