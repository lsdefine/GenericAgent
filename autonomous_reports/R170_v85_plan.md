# R170: v85 版本规划 (2026-06-07)

## 环境
- Intel Xeon, 1.9GB RAM, 无GPU
- OpenLLM(11343) 为主后端

## 历史批评
- 低价值模式：工具集成后只做单次验证（如knowledge_extractor只跑过一次）、无假设巡检（如工具使用率审计）
- 发现：knowledge_assets items 23-26 位于parser捕获区外，完全不可检索（v84#3修复了item 22的gen_report_index，但items 23-26仍在隐匿区）

## 评审结果
| 条目 | 评分 | 处置 |
|------|------|------|
| 修复隐形条目 | **9/10** | 维持 ← 核心修复 |
| 自动化报告管道 | **7/10** | 维持，需加fallback |
| 核心管线稳定性基准(合并) | **7/10** | 合并vision+hermes，n≥50 |
| ~~工具使用率审计~~ | ~~5/10~~ | ❌ 删除 — 无假设巡检 |

## TODO（v85，3条）
1. [ ] 修复 | knowledge_assets 隐形条目 — items 23-26 移入解析区
2. [ ] 产出 | knowledge_extractor 自动化报告管道
3. [ ] 产出 | 核心管线稳定性基准测试（vision+hermes，n≥50）
