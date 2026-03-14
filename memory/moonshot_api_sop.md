# Moonshot API (Kimi) 使用指南

## 核心约束

### Temperature 参数限制
**重要**：Moonshot API 只接受 `temperature=1.0`（必须是1.0），其他值均会返回 HTTP 400 错误。

#### 验证测试结果
- ✅ temperature=1.0 → 成功
- ❌ temperature=0 → 400 错误
- ❌ temperature=0.5 → 400 错误  
- ❌ temperature=0.7 → 400 错误
- ❌ temperature=1.5 → 400 错误
- ❌ temperature=2.0 → 400 错误

## 代码实现

在 `llmcore.py` 中已实现自动检测：
