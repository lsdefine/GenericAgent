# GenericAgent 能力画像 v2

> 更新日期: 2026-04-30
> 基于 MiniCase-E & MiniCase-F 训练完成

## 维度评分表

| 维度 | 当前分 | 目标分 | 强化来源 | 验证状态 |
|------|--------|--------|----------|----------|
| D1 (基础执行) | - | - | - | - |
| D2 (环境感知) | - | - | - | - |
| **D3 (多工具链编排)** | **70** | 75 | MiniCase-E | ✅ 已验证 |
| **D4 (跨Case经验迁移)** | **65** | 70 | MiniCase-F | ✅ 已验证 |
| D5 (复杂推理) | - | - | - | - |
| D6 (长期自主) | - | - | - | - |

## D3 强化详情
- **来源**: MiniCase-E 多工具链自适应编排
- **验证**: 编排链 navigate→scan→extract_fail→fallback→transform→store
- **产物**: `memory/web_extract_fallback_sop.md`

## D4 强化详情
- **来源**: MiniCase-F 跨Case经验迁移
- **验证**: classify_content_type() + extract_by_content_type() 已写入 utils.py
- **产物**: `memory/audit/minicase_f_transfer.md`

## 历史更新
- 2026-04-30: D3 65→70, D4 60→65 (MiniCase-E/F)
