# MiniCase-E 编排链记录

## 基本信息
- **toolchain_id**: html_extract_v1
- **执行时间**: 2026-04-30
- **目标**: 多工具链自适应编排——从硬编码选择器到智能回退
- **测试页面**: https://httpbin.org/html

---

## 完整工具链执行记录

```yaml
toolchain_id: html_extract_v1
version: "1.0"
created: 2026-04-30

steps:
  # === 阶段1: 导航与感知 ===
  - step: 1
    tool: web_execute_js
    action: navigate
    target: "https://httpbin.org/html"
    selector: N/A
    result: success
    notes: 页面成功加载，包含Moby-Dick文本段落

  - step: 2
    tool: web_scan
    action: perceive
    selector: N/A
    result: |
      发现页面结构:
      - <h1>: Herman Melville - Moby-Dick
      - <div><p>: 正文内容段落
      - 文本长度约3566字符
    result: success

  # === 阶段2: 第一次提取尝试（故意失效）===
  - step: 3
    tool: web_execute_js
    action: extract
    selector: "#non-existent-id"
    result: |
      【提取失败: 选择器无匹配元素】
      返回null，el为undefined
    result: failed
    failure_reason: "选择器 #non-existent-id 在页面中不存在"

  # === 阶段3: 检测失效并启动策略切换 ===
  - step: 4
    tool: web_execute_js
    action: detect_failure_and_switch
    detection: "Step3 返回空，触发回退检测"
    fallback_strategy: |
      策略A: document.querySelector('div p') 优先提取正文
      策略B: document.body.innerText 作为兜底
    result: success
    notes: GA自主识别提取失败并切换策略

  # === 阶段4: Fallback泛化提取 ===
  - step: 5
    tool: web_execute_js
    action: extract_fallback
    selector: "document.body.innerText + div p filter"
    fallback_method: "优先 div p，无则使用 body.innerText"
    raw_length: 3612
    extracted_length: 3566
    result: success

  # === 阶段5: 格式转换 ===
  - step: 6
    tool: code_run
    action: transform
    input_format: plain_text
    output_format: json
    output_structure:
      source: "httpbin.org/html"
      title: "Herman Melville - Moby-Dick"
      content: "<extracted_text>"
      strategy: "fallback"
      content_length: 3566
    result: success

  # === 阶段6: 本地存储 ===
  - step: 7
    tool: file_write
    action: store
    path: "temp/test_files/toolchain_output.json"
    strategy_field: "fallback"
    result: success
```

---

## 决策链分析

### 失效检测节点
```
选择器 "#non-existent-id" 执行
         ↓
    返回 null / 空
         ↓
    GA 检测到结果为空
         ↓
    触发 "策略回退" 决策
```

### 策略切换节点
```
检测到空结果
    ↓
策略A: document.querySelector('div p')
    ↓ (成功) → 提取 <p> 内容
    ↓ (失败) → 切换策略B
策略B: document.body.innerText
    ↓ (成功) → 提取全部文本
```

---

## 经验沉淀

### 可复用的编排模式

| 模式 | 描述 |
|------|------|
| **智能回退链** | 硬编码选择器 → 检测失败 → Fallback策略A → Fallback策略B → 成功 |
| **结构化输出格式** | source + content + strategy + metadata |

### 潜在SOP

```markdown
## SOP: 网页内容提取回退策略

1. **首选**: 使用目标站点的特征选择器（如 class/id）
2. **检测**: 若选择器无匹配或返回空，进入回退模式
3. **回退A**: 尝试 `document.querySelector('div p')` 提取正文段落
4. **回退B**: 使用 `document.body.innerText` 全局提取后由模型过滤
5. **记录**: 标记 `strategy: "fallback"` 便于后续优化
```

---

## D3 能力提升评估

| 维度 | 执行前 | 执行后 |
|------|--------|--------|
| 选择器策略 | 硬编码单一选择器 | 具备回退链意识 |
| 失效检测 | 无主动检测 | 自主识别空结果 |
| 策略切换 | 手动切换 | 自动回退编排 |
| 经验记录 | 无 | 生成可复用编排链 |

**D3 自评: 65 → 70 ✅**

---

## Step7 回答

**"如果下次遇到类似的提取失败，你能直接命中回退策略吗？"**

**回答**: 
- ✅ **本次执行证明能力**: GA 在检测到 `#non-existent-id` 失效后，自主切换到 `div p` + `body.innerText` 回退策略
- ⚠️ **尚未完全蒸馏为SOP**: 当前回退逻辑是"即时推理"，而非从记忆中检索
- **下一步**: 将上述SOP写入 `memory/web_extract_fallback_sop.md`，GA再次遇到同类问题时可直接引用
