<!-- EXECUTION PROTOCOL (每轮必读，这是你的执行指南)
1. file_read(plan.md)，找到第一个 [ ] 项
2. 该步标注了SOP → file_read 该SOP的🔑速查段
3. 执行该步骤 + Mini验证产出
4. file_patch 标记 [ ] → [✓]+简要结果，然后回到步骤1继续下一个[ ]
5. 所有步骤（包括验证步骤）标记完成后 → 终止检查：file_read(plan.md)确认0个[ ]残留
⚠ 禁止凭记忆执行 | 禁止跳过验证步骤 | 禁止未经终止检查就结束 | 禁止停下来输出纯文字汇报
-->
# v98 版本规划 (2026-06-07)
需求：系统管线巡检+健康报告+清理维护 | 约束：优先未完成事项，避免引入新功能

## 探索发现
- service_health_collector 5min cron已运行多时但--report趋势报告未生成
- benchmark_trend.json在正确路径(temp/autonomous_reports/)但未验证数据完整性
- temp/目录40MB，含大量历史日志和中间产物
- scheduler有多个任务定义，需检查运行健康度

## 执行计划
1. [ ] **服务健康趋势报告生成** — 运行service_health_report.py --report输出趋势图/JSON
   SOP: (无)
2. [ ] **benchmark管线数据验证** — 读取benchmark_trend.json检查数据完整性+最新采集时间
   SOP: (无)
3. [ ] **temp/目录清理** — 删除>30天旧日志+临时文件，保留配置/关键数据
   SOP: (无)

---

## 验证检查点
4. [ ] **[VERIFY] 启动独立验证subagent**
     SOP: plan_sop.md
     操作：确认3项交付物完整，逐项核验
