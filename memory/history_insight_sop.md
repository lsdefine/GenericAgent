# 历史洞察扫描 SOP (history_insight_sop)

从 L4 历史对话中提取三类有价值信息：情绪爆发、持续习惯、消失事项。

## 路径
- 数据源: `../memory/L4_raw_sessions/all_user_histories.txt`
- 产物全部在 `./`（temp目录）: `batches.json`, `scan_results.json`, `normalize_map.json`, `scan_report.json`, `activity_matrix.json`, `scan_state.json`

## 流程概览
P0数据准备 → P1逐批提取(循环) → P2标签归一化+执行脚本

---

## P0: 数据准备
前置依赖（若数据源不存在则按顺序生成）：
1. 运行 `compress_session.py` → 生成 `all_histories.txt`
2. 从 `all_histories.txt` 过滤掉 `[Agent]:` 行 → 生成 `all_user_histories.txt`

读 `scan_state.json` 获取 `emotion_last_line`（增量起点，首次=0）。读数据源按 `SESSION:` 分割，提取 `[USER]:` 行（忽略≤5字的），只保留行号>起点的新增行。按session为单位装入批次（每批≤120行），写 `batches.json`。格式：`[{session: "名", lines: [[全局行号, "文本"], ...]}, ...]`。

## P1: 逐批提取（核心循环）

⛔ **严格单批处理。已验证：合并多批→后半段数据被编造。**

每轮固定3步，不可变形：
1. code_run：从`batches.json`读第N批（N=已有结果数），打印格式 `[行号] 文本`
2. 分析当前输出文本（禁止凭记忆补充、禁止预读下一批）
3. code_run：将本批结果追加到`scan_results.json`，打印进度`done X/total`

读取脚本自动计算进度：`done = len(已有结果)`，只输出`batches[done]`。N批就是N轮循环，不可压缩。

⛔ **最后一批写入后必须打印提醒：** `print("P1完成！下一步：P2写normalize_map.json → P3执行 python ../memory/build_report.py .")`

### 情绪检测（高阈值，宁漏不误）

仅标记：
- 累积不满后的爆发（连续多轮后终于发火）
- 明确愤怒/质问/责备（真的生气，不是追问）
- 强烈讽刺挖苦（带攻击性）
- 极度惊喜感激（远超正常反应）

**不标记**：普通不耐烦、催促、语气平和的不满、日常吐槽。判断技巧：去掉情绪修饰后信息量是否减少？减少才标记。

label: NEGATIVE / POSITIVE。输出: `{"line_no": 行号, "text": "[USER]: 前30字", "label": "X", "reason": "一句话", "traceback_query": "前30字(无[USER]:前缀)", "occurrence_nth": 0}`

`occurrence_nth`: 该文本在全文中第几次出现（从0开始），供 `session_traceback.py` 精确溯源。大多数情况为0。

### 活动识别
每session提取用户在做什么。标签格式：动词+宾语 4-8字（如"配置远程服务器"）。每session 1-5条。不明确标 `["不明确"]`。

输出: `{"session": "名", "tasks": ["标签1", ...], "text": "该session中最能代表活动的一句用户原文(前30字)"}`

`text` 字段供 `build_report.py` 生成 `source_lines`，用于后续 `session_traceback.py` 溯源。

## P2: 标签归一化

⛔ **不可跳过，P3脚本读 `normalize_map.json`，不存在则报错。**

⛔ **归一化前必须 code_run 读取已有 `activity_matrix.json` 的标签列表（若存在）。新标签优先映射到已有标签（语义一致时），保证跨次运行标签一致性。**

提取所有标签去重排序，每批50个进行同义合并。规则：
- 新标签与已有matrix标签语义一致时，映射到已有标签名（优先级最高）
- 保守合并：只合并明确同义词，不确定保持独立
- 同一功能的子步骤合并为功能级（如"X功能重构"+"X功能测试"+"X功能PR"→"X功能开发"），跨性质保持独立（开发≠文档≠部署）
- "调试bug"≠"修复bug"（动作不同）
- 输出完整映射 `{"原标签": "归一化名", ...}`，独立标签映射为自身

⛔ **归一化完成后必须 code_run 写入 `normalize_map.json`，同一个 code_run 内紧接着执行：**
```python
import subprocess, sys
r = subprocess.run([sys.executable.replace("pythonw","python"), "../memory/build_report.py", "."], capture_output=True, text=True)
print(r.stdout); print(r.stderr)
```
看到 `[BUILD_REPORT_DONE]` 即全部完成。未看到则读stderr排错。

---

## 坑点
- session名格式 `MMdd_HHmm-MMdd_HHmm`，取第一个MMdd推算周次
- `week_str_to_date` 用 `"%Y-W%W-%w"` 格式解析
- 归一化时标签数可能300+，必须分批处理避免质量退化
- activity_matrix结构是 `{归一化标签: {week: count}}`（按标签分组），不是 `{week: {标签: count}}`（按周分组）
