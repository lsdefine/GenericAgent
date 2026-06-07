# R364 | nanobot serve LLM 超时诊断报告

## 任务
诊断 `:8900/v1/chat/completions` 超时根因

## 系统架构

```
nanobot serve (:8900)  v0.2.0  [model: hermes]
  ├── MCP-remote → api.anysearch.com/mcp ❌ SSE断开循环
  └── Provider → 8.208.28.70:20128/v1 (OpenAI-compatible)
```

## 诊断发现

### ① nanobot serve 进程详情
- PID: 712595 (运行 ~3h)
- 内存: 7.4% (143MB RSS)
- MCP子进程: 712612 (mcp-remote, Node.js)

### ② 后端 Provider 状态 (8.208.28.70:20128)
- ✅ API可达, 响应正常
- ✅ 支持 60+ 模型
- ⚡ 速度对比: `gc/gemini-3-flash-preview` ≈ **1s** | `hermes` ≈ **18s** (1-token)
- 端点: `/v1/chat/completions`, `/v1/models`, `/v1/embeddings`

### ③ MCP 远程故障 (根因#1)
- 子进程 `mcp-remote https://api.anysearch.com/mcp` 持续抛错
- 错误: `SSE stream disconnected: TypeError: terminated`
- API域名解析到 CloudFront (CDN)
- MCP初始化失败 → 资源循环 → 主请求被阻滞

### ④ LLM 响应慢 (根因#2)
- 默认模型 "hermes" 在provider端返回极慢(~18s/token)
- nanobot serve 内部超时 120s
- 实际请求在MCP循环 + 慢模型双重影响下, 120s后超时

## 根因结论

**双重因素叠加:**
1. **MCP远程服务不可用** — `api.anysearch.com/mcp` SSE连接持续断开, 导致子进程无限重试, 消耗并发资源
2. **hermes模型延迟高** — provider端该模型需~18s/response, 远高于其他模型(~1s)

## 修复建议

| 方案 | 操作 | 预期效果 |
|------|------|---------|
| A. 直接替换模型 | 向 :8900 发送 `model:gc/gemini-3-flash-preview` | 响应时间从~18s→~1s |
| B. 重启无MCP | `kill $(pgrep -f mcp-remote)` 断开MCP子进程 | 消除MCP错误循环 |
| C. 配置绕行 | 修改 config.json 设置 models.default 为快模型 | 持久化修复 |
| D. 使用direct API | 绕过nanobot, 直接调用 8.208.28.70:20128 | 最快路径(已验证) |

## 验收标准
- [x] 找出根因并产出一份诊断报告
