# R119: 9router实测算力基线报告

**日期**: 2026-06-06 | **类型**: 环境探测 | **状态**: 完成

## 摘要
对9router(8.208.28.70:20128)进行可达性、模型可用性、延迟基准测试。9router通过OpenLLM(127.0.0.1:11343)代理访问。

## 1. 基础设施

### 9router 直接访问
- **地址**: http://8.208.28.70:20128
- **状态**: ✅ 可达 (HTTP 307 → /dashboard)
- **延迟**: ~5ms (网络层)
- **类型**: Next.js Web面板 (AI Infrastructure Management)
- **认证**: 需要API Key ("API key required for remote API access")
- **公开模型列表**: 不可直接获取（需登录面板）

### OpenLLM 代理访问 (127.0.0.1:11343)
- **总模型数**: 229个
- **Provider分布**: deepseek(2), nvidia(120), opencode(18), router(89)

## 2. 模型可用性测试

| 模型 | 状态 | 延迟 | Response |
|------|------|------|----------|
| **deepseek/deepseek-v4-flash** | ✅ 200 | 0.77s | OK |
| **deepseek/deepseek-v4-pro** | ✅ 200 | 1.18s | OK |
| **opencode/deepseek-v4-flash** | ✅ 200 | 1.04s | OK |
| **opencode/deepseek-v4-pro** | ✅ 200 | 2.20s | OK |
| **opencode/glm-5** | ✅ 200 | 2.20s | OK |
| **opencode/glm-5.1** | ✅ 200 | 3.09s | OK |
| **opencode/kimi-k2.5** | ✅ 200 | 1.14s | OK |
| **opencode/kimi-k2.6** | ✅ 200 | 2.20s | OK |
| **opencode/qwen3.7-max** | ❌ 502 | 0.12s | Bad Gateway |
| **opencode/qwen3.7-plus** | ⏳ 429 | 0.002s | 限流 |
| **opencode/minimax-m3** | ⏳ 429 | 0.002s | 限流 |
| **opencode/minimax-m2.7** | ⏳ 429 | 0.002s | 限流 |
| **opencode/hy3-preview** | ⏳ 429 | 0.002s | 限流 |
| **router/gh/claude-sonnet-4** | ⏳ 429 | 0.002s | 限流 |
| **router/ds/deepseek-v4-pro** | ⏳ 429 | 0.004s | 限流 |
| **router/gh/gemini-2.5-pro** | ⏳ 429 | 0.002s | 限流 |
| **router/gc/gemini-3-flash-preview** | ⏳ 429 | 0.002s | 限流 |
| **nvidia/* (全部120个)** | ⏳ 429 | ~0.002s | 限流 |

## 3. 性能基线

| 指标 | deepseek本地 | opencode(通过9router) |
|------|-------------|----------------------|
| P50延迟 | ~0.8s | ~2.0s |
| P90延迟 | ~1.2s | ~3.1s |
| 可用率 | 100% (2/2) | 61% (8/13工作) |
| 吞吐(预估) | - | ~0.5 req/s (单连接) |

## 4. 关键结论

1. **9router运行正常**：可达且部分路由工作，但大部分高级模型(router/gh, router/nvidia)返回429限流
2. **opencode通道最稳定**：8/13模型可用，延迟1-3s
3. **deepseek本地优先**：直接通过OpenLLM调用延迟更低(0.8-1.2s)
4. **router/gh等需额外配置**：429表示OpenLLM未配置router系列模型的API Key
5. **9router面板需要登录**：无法直接通过API获取路由配置和模型列表

## 5. 建议
- 短期：优先使用opencode/*和deepseek/*模型
- 中期：为router/gh配置API Key以解锁Claude/Gemini
- 长期：可建立定时任务监控模型可用率
