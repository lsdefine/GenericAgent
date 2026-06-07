# R338: v91#2 prompt_optimization_loop_sop实战化

## 优化循环摘要

**候选prompt:** `engine/roles/vision_describer.prompt` — 视觉图片描述角色prompt
（对应vision_browser_pipeline的`ask_vision(prompt="详细描述这张图片的内容")`的正式化角色prompt）

### 迭代过程

| 版本 | 总分 | 维度ABCD | 弱项数 | 对比基线 |
|------|------|----------|--------|----------|
| v1 (baseline) | 7.25 | A=4.5 B=5.5 C=10.0 D=9.0 | 5 | — |
| v2 (修复结构) | 8.75 | A=10.0 B=7.0 C=10.0 D=8.0 | 5 | +1.50 |
| v3 (修复内容+示例) | **9.75** | A=10.0 B=10.0 C=10.0 D=9.0 | 1 | **+2.50** |

### 修复的弱项
- A2: 添加 tags 数组 ✅
- A3: 添加 role_id ✅
- A4: 添加"你的角色"段 ✅
- A5: 添加 ✅/❌ 边界段 ✅
- B2: 添加禁止项 ❌ 段 ✅
- B3: 添加 `{task_text}` 占位符 ✅
- B4: 添加 `{output_spec}` ✅
- B5: 添加防越界规则 ✅
- D2: 添加使用示例 ✅

### 余1弱项（D5: 删除重复行，轻微）

## 交付物

| 文件 | 说明 |
|------|------|
| `engine/roles/vision_describer_v3.prompt` | 最终优化版 (9.75分) |
| `engine/roles/vision_describer_v2.prompt` | 中间版本 |
| `engine/roles/vision_describer.prompt` | 原始基线 (7.25分) |
| 历史记录 | `engine/metrics/` metrics history |

## 验收标准

- [x] 走通定义→测试→分析→优化→验证全流程
- [x] 优化前后质量分对比: **7.25 → 9.75 (+2.50)**
- [x] ≥1条可量化提升 ✅
