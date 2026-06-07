---
version: 1.0
task: v44-1
title: Hermes CLI capability map
date: 2026-06-06
status: completed
---

# Hermes CLI 能力地图

## 探索范围
- 子系统: memory / tools / skills / cron / sessions / insights / gateway / proxy / mcp / config / secrets
- 目标: 发现未利用能力, 评估接入价值

## 发现总览

### 🟢 高价值未利用能力（TOP 5）

| # | 能力 | 当前状态 | 接入价值 | 用途 |
|---|------|---------|---------|------|
| 1 | **Skills Hub (850+技能包)** | 仅安装36个, 87个官方optional未用 | ⭐⭐⭐⭐⭐ | 扩展Agent能力, 如agentmail/adversarial-test/bioinformatics |
| 2 | **Cron 任务调度** | 已有3个cron任务但未与自治调度整合 | ⭐⭐⭐⭐⭐ | 替代/补充当前scheduled_task_sop, 可编程管理定时任务 |
| 3 | **Gateway 消息网关** | 未配置 | ⭐⭐⭐⭐ | 打通Telegram/Discord/WhatsApp/微信, 实现跨平台通知 |
| 4 | **Insights 分析** | 已有7天数据(6.1K msg, 3.2K tools) | ⭐⭐⭐⭐ | Token/工具使用分析, 容量规划, 行为模式识别 |
| 5 | **MCP Server 扩展** | 已有3个MCP server, Hermes自身可serve | ⭐⭐⭐⭐ | 扩展工具链, 暴露Hermes能力给其他agent |

### 🟡 中价值能力

| # | 能力 | 说明 |
|---|------|------|
| 6 | Memory Provider 体系 | 7个外部provider: mem0已激活, 但byterover/hindsight/holographic/honcho/openviking/retaindb/supermemory未配置 |
| 7 | Sessions 管理 | 966 sessions, 443MB, 可用export/prune/optimize清理维护 |
| 8 | Proxy 代理 | 转发OpenAI兼容请求到OAuth provider |
| 9 | Disabled Toolsets | video/video_gen/x_search/moa/context_engine/homeassistant等可启用 |
| 10 | Secrets Manager | Bitwarden集成, 安全管理API keys |

### 🔴 低价值或已知

| # | 能力 | 说明 |
|---|------|------|
| 11 | Config 管理 | 已完成, config show/edit/set已具备 |
| 12 | 240 commits behind | 更新非紧急, 且需用户批准 |

## 系统现状快照

### 模型使用 (近7天)
| Model | Sessions | Tokens |
|-------|---------|--------|
| deepseek-v4-flash | 262 | 812,035,673 |
| coding-combo | 12 | 0 |

### 平台分布
| Platform | Sessions | Messages | Tokens |
|----------|---------|----------|--------|
| cron | 160 | 2,940 | 51,905,292 |
| cli | 61 | 374 | 11,236,252 |
| feishu | 53 | 2,823 | 748,894,129 |

### 活跃Cron任务
1. **StudyAI Daily Optimize** (0 3 * * *) — 每日优化
2. **StudyAI Weekly Review** (0 9 * * 1) — 每周评审
3. **Daily AI News** (0 8 * * *) — AI新闻简报+推送飞书

## 建议行动

1. **即时**: Skills Hub浏览安装 ≥3个高价值技能（建议: agentmail、某个研究类、某个自动化类）
2. **短期**: 将自治任务接入 Hermes Cron 调度, 替代手动 crontab
3. **中期**: 配置 Gateway 打通飞书/Telegram 通知通道
4. **长期**: 接入 Memory Provider 实现跨session持久记忆

## 已验证能力清单
- [x] hermes --version → v0.15.1
- [x] hermes memory status → mem0 active, 7 providers unconfigured
- [x] hermes tools list → 25 toolsets, 3 MCP servers
- [x] hermes skills list → 36 installed, 850 available
- [x] hermes cron list → 3 active jobs
- [x] hermes sessions stats → 966 sessions
- [x] hermes insights --days 7 → comprehensive analytics
- [x] hermes mcp list → 3 servers enabled
- [x] hermes config show → config path, model, api keys
- [x] hermes gateway --help → multi-platform messaging
- [x] hermes proxy --help → OAuth proxy
- [x] hermes secrets --help → Bitwarden integration
