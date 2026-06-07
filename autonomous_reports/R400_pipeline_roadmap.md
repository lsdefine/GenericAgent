---
title: 管线接入路线图 — v112#1 摸底结果
version: 1.0
last_updated: "2026-06-07"
tags: [pipeline, roadmap, v112, R400]
---

# 管线接入路线图

> 摸底时间: 2026-06-07 | 基于R395分类 + 全量调用链分析

## 核心发现

发现 **13个 memory/tools/ 工具在日常管线中0引用** — 大量暗资产从未接入任何管道。

## 高ROI候选（Top 3）

### 1. ⭐ knowledge_lookup.py (P0)
- **现状**: 286行，独立可用，无外部依赖
- **接入方式**: 在agent启动时注入 `from memory.tools import knowledge_lookup`，每次任务前自动知识查询
- **收益**: 提高任务质量，减少重复查询
- **成本**: 0.5h（添加1-2行注入代码）

### 2. ⭐ knowledge_injector + knowledge_extractor (P0)
- **现状**: 已有`scripts/knowledge_inject_trigger.py`但从未被任何cron/sche_task调用
- **接入方式**: 创建sche_task每日自动运行extract→inject管线，或接入session_end钩子
- **收益**: 知识资产自动沉淀，减少手动管理
- **成本**: 0.5h（创建sche_task配置）

### 3. ⭐ report_digest.py (P1)
- **现状**: 376行，可自动消化R-report提炼洞察
- **接入方式**: session结束后自动调用，提取新模式写入knowledge_assets
- **收益**: 任务洞察自动化积累
- **成本**: 1h（需集成到session结束流程）

## 其他候选

| 候选 | 优先级 | 接入成本 | 收益 | 说明 |
|------|--------|---------|------|------|
| benchmark_viz.py | P1 | 1h | 中 | 整合到health_dashboard管道 |
| nanobot_api.py | P2 | 0.5h | 中 | 与Phase2#3 Gateway合并 |
| gen_report_index.py | P2 | 0.5h | 低 | 接入session_end钩子 |
| chart_plotter.py | P2 | 0.3h | 低 | plotext终端图，轻量 |
| fd_search.py | P2 | 0.3h | 低 | 文件搜索，少数场景 |

## 接入总成本估算
- P0: ~1h (2项)
- P1: ~2h (2项)
- P2: ~1.6h (5项)
- **总计**: ~4.6h 盘活全部暗资产

## 建议行动
1. **立即P0**: 在agent启动时注入knowledge_lookup（约5行代码）
2. **v112#1后续**: 创建knowledge_inject_trigger的sche_task调度
3. **v112 Phase2整合**: 将report_digest/benchmark_viz整合到Dashboard管道
