# R365 | 本机内存高排查与优化报告

## 环境
- 总内存: 1.8Gi, 已用: 1.4Gi (78%), Swap: 657Mi/4Gi
- Available: 403Mi (临界)

## Top 内存进程

| PID | 进程 | RSS | 占比 | 备注 |
|-----|------|-----|------|------|
| 706028 | hermes gateway | 360MB | 18.8% | 主agent进程 |
| 706150 | fsapp.py | 166MB | 8.6% | 前端应用 |
| 712595 | nanobot serve | 137MB | 7.1% | LLM serve |
| 158373 | next-server | 107MB | 5.6% | Next.js |
| 712612 | mcp-remote (anysearch) | 69MB | 3.6% | 新实例(故障) |
| 2442 | mcp-remote (anysearch) | 29MB | 1.5% | **旧实例(Jun03起,4天未释放!)** |

## 发现问题

### ① 重复mcp-remote进程
- PID 2442: `mcp-remote https://api.anysearch.com/mcp` 自Jun03启动, 已存活4+天
- PID 712612: 同一命令的新实例
- 两个实例都连接失败(SSE断开), 属于死进程

### ② 大缓存目录
- `/tmp`: 529MB (npm缓存/tmp文件)
- `~/.npm`: 371MB
- `~/.cache`: 318MB
- 合计 ~1.2GB可回收

### ③ Swap使用
- 657Mi swap已使用 → 表明物理内存压力, 进程被换出

## 优化建议

### [高优先] 清理死进程
```bash
kill 2442  # 旧mcp-remote, 4天僵尸
```
可回收约29MB RSS + 未计算的swap占用。

### [中优先] 清理tmp/cache
```bash
rm -rf /tmp/npm-* ~/.npm/_cacache
npm cache clean --force
```
可回收500MB+磁盘空间并减轻内存压力(cache减少page cache).

### [低优先] 考虑增加swap
当前swap 4Gi → 可酌情增加到8Gi缓解OOM风险。

### 备注
内存可用403Mi处于临界但不紧急。hermes gateway(360MB)是正常负载, 
nanobot serve的MCP故障进程才是可优化的浪费点。
