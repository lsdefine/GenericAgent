# R339: v91#5 SOP老旧审计v2

**审计时间**: 2026-06-07 04:06
**扫描SOP数**: 47 .md + 6 .py = 53
**审计工具**: sop_frontmatter_check.py + sop_script_audit.py + 手动一致性检查

---

## 发现汇总 (≥5项)

### 🔴 1. vision_sop.md 引用路径错误
**严重度**: HIGH | 影响: 使用者找不到对应脚本
- 第3行`last_updated`格式错误: `"2026-06-07 (v90#5)"` → 应纯YAML日期
- 引用 `memory/vision_api.py` → 实际在 `scripts/vision_api.py`
- **修复建议**: 改路径为 `scripts/vision_api.py`，日期去括号

### 🔴 2. 6个SOP完全缺少frontmatter
**严重度**: HIGH | 影响: metrics_aggregator无法评分
- `checklist_sop.md`, `computer_use.md`, `goal_hive_master_duty.md`, `report_digest.md`, `self_improve_sop.md`, `working-buffer.md`
- **修复建议**: 逐个添加YAML frontmatter（version/last_updated/title/tags）

### 🟡 3. goal_sop.md 引用已归档文件
**严重度**: MEDIUM | 影响: 引用漂移/用户困惑
- 引用 `goal_hive_sop.md` → 已移至 `memory/archive/goal_hive_sop.md`
- 引用 `goal_mode_sop.md` → 已移至 `memory/archive/goal_mode_sop.md`
- 引用 `temp/goal_state.json` → 不存在（示例文件在`temp/goal_state_v80_demo.bak.json`）
- **修复建议**: 更新路径或注明已归档

### 🟡 4. autonomous_operation_sop.md 引用目录不存在
**严重度**: MEDIUM | 影响: 路径困惑
- 引用 `memory/autonomous_reports/` → 实际在 `temp/autonomous_reports/`
- **修复建议**: 统一路径引用

### 🟡 5. 30+ SOP在v1.0停留超8天 (2026-05-30)
**严重度**: LOW | 影响: 版本滞后
- 自创建以来从未版本升级，诸多SOP内容已与实际行为有偏差
- 例如: vision_sop.md v1.4 → 自上次审计后新增内容需版本号升级
- **修复建议**: 对新增/修改过的SOP做版本号+日期刷新

### 🟡 6. 35+ SOP缺失title/tags字段
**严重度**: MEDIUM | 影响: 检索/分类困难
- 前次审计(R275)遗留问题，仅部分修复
- **修复建议**: 批量补充title和tags

### 🔵 7. self_improve_sop.md 引用已归档脚本
**严重度**: LOW | 影响: 引用漂移
- 引用 `temp/agent_budget_controller.py` → 已移至 `temp/archive_backup/agent_budget_controller.py`
- **修复建议**: 删除或更新引用路径

### 🔵 8. knowledge_assets.md 含3个不存在引用
**严重度**: LOW | 影响: 模板残留
- `deepseek/deepseek-v4-flash`, `provider/name`, `trend.json` 均不存在
- **修复建议**: 清理模板占位符

---

## 可操作修复建议 (≥3条)

| # | 修复项 | 优先级 | 预估工作量 |
|---|--------|--------|-----------|
| 1 | vision_sop.md: `memory/vision_api.py` → `scripts/vision_api.py` + 日期格式修正 | 🔴 HIGH | 2min |
| 2 | 6个缺失frontmatter的SOP添加YAML头 | 🔴 HIGH | 15min |
| 3 | goal_sop.md: 更新存档引用路径 | 🟡 MEDIUM | 5min |
| 4 | autonomous_operation_sop.md: 修复autonomous_reports路径引用 | 🟡 MEDIUM | 2min |
| 5 | 批量补充35+ SOP的title/tags字段 | 🟡 MEDIUM | 20min |
| 6 | knowledge_assets.md清理模板占位符 | 🔵 LOW | 3min |

---

## 结论

**验收**: ✅ ≥5项发现(8项) | ✅ ≥3条可操作修复建议(6条)
**对比上次审计(R275)**: 前次发现159问题，本次发现166问题(+7)，说明修复覆盖率不足
**建议**: 下次v92优先执行修复SOP计划(P1-P4)
