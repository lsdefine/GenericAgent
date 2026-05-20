# 历史洞察扫描 SOP

从历史对话中提取：情绪波动点、持续习惯、已完成/消失事项。

## 路径

- 数据源: `../memory/L4_raw_sessions/all_user_histories.txt`
- 生成方式: 若不存在，先运行 `compress_session.py` → 产出 `all_histories.txt`（含Agent行） → 过滤掉 `[Agent] ` 开头的行（空格不是冒号） → 另存为 `all_user_histories.txt`
- ⚠️ `all_histories.txt` 不是数据源，必须用过滤后的 `all_user_histories.txt`
- 产物目录: `./`（temp）
- 下游: `session_traceback.py` — `traceback(query, context_chars=1500, nth=0)` 返回前后文

## 产物

| 文件 | 持久 | 格式 |
|------|------|------|
| `activity_matrix.json` | ✅ 增量累积 | `{"weeks": ["2025-W11",...], "matrix": {"标签": {"2025-W11": 3}}}` |
| `scan_state.json` | ✅ | `{"last_session": "0519_xxx"}` |
| `scan_report.json` | 每次覆盖写 | 见下方 |
| `task_dict.json` | ❌ 临时 | P2完成后删除 |
| `scan_results.json` | ❌ 临时 | P2完成后删除 |
| `batches.json` | ❌ 临时 | P2完成后删除 |

scan_report.json 格式：
```json
{
  "scan_date": "2025-05-19",
  "data_range": "0401-0519",
  "total_sessions": 42,
  "emotions": [
    {"session": "0501_xxx", "week": "2025-W18", "trigger": "连续3次修复失败后爆发", "expression": "用户原话前50字", "traceback_query": "用于session_traceback溯源的原文片段"}
  ],
  "habits": [{"label": "编写SOP", "sessions": ["0501_xxx", "0508_yyy", "0515_zzz"]}],
  "abandoned": ["搭建博客", "学习Rust"]
}
```

## 流程

P0 准备 → P1 逐批扫描(循环) → P2 汇总

### P0

过滤 `[Agent]` 行并按 session 分割：`sessions = re.findall(r'={5,}\nSESSION:\s*(.+?)\n={5,}\n(.*?)(?=\n={5,}\nSESSION:|\Z)', content, re.DOTALL)`（content 为去掉 `startswith("[Agent] ")` 行后的全文，注意[Agent]后是空格不是冒号）。 以 session 为单位装入批次（每批≤500 行，不拆分 session）。若 `scan_state.json` 存在，跳过 session 名 ≤ `last_session` 的所有 session，只处理之后的。若 `activity_matrix.json` 已存在，提取其标签名列表供 P1 归类参考。
启动锚定：`update_working_checkpoint: "history_insight | P1逐批中 | P2: scan_report顶层key严格=scan_date,data_range,total_sessions,emotions,habits,abandoned(6个禁自创) | habits项格式={label,sessions[]} | 临时文件仅删task_dict/scan_results/batches | scan_state持久禁删 | 禁止: 自创阶段/自创产物/跳过P2"`

### P1: 逐批扫描

⛔ 每轮只处理 1 批（合并多批会超出注意力窗口，导致 session 名编造）。禁止在一个 code_run 内用循环/批量处理多批；处理完 1 批后必须结束当前 code_run，下一批在下一轮处理。

每轮一个 code_run，固定结构：先从 batches.json 加载当前批次 session 列表 → `valid_sessions`，`batch_index = scan_state.get("last_batch", -1) + 1`，assert `batch_index < len(batches)`（未越界）。处理完毕后 assert 本轮写入的所有 session ∈ valid_sessions。每批结束时增量更新 `activity_matrix.json`（从本批 task_dict 新增条目统计计数）并更新 `scan_state.json`：`{"last_session": ..., "last_batch": batch_index}`。若本批有 emotions，assert 每条 `set(e.keys()) == {"session","week","trigger","expression","traceback_query"}`。

1. **情绪检测** — 标记明显的情绪波动。

   标记：愤怒/质问/责备、讽刺挖苦、惊喜感激、反复纠正后语气变化、沮丧/无奈表达、预期落空后的失望或方向突变。
   不标记：纯功能性指令、语气始终平和的反馈。

   结果追加 `scan_results.json`，每批一个对象：`{"batch": N, "emotions": [{"session", "week", "trigger", "expression", "traceback_query"}]}`。traceback_query = 用户原话中最具辨识度的连续片段（15-40字，供下游精确匹配）。

2. **活动归类** — 增量维护 `task_dict.json`（key=动宾短语4-10字）。匹配已有 key 则追加，否则新建。每条：`{"session", "week", "text"}`。归类原则：含相同专有名词才归同一 key；通用动作不归入特定项目；宁多建 key 不错误合并。
3. **更新矩阵** — 用本轮新构建的 entries 增量更新 `activity_matrix.json`（标签×周 +1）。若文件不存在则新建。
   ```python
   # new_entries: 本轮新构建的list，⛔禁止从task_dict.json全量遍历重新统计
   for e in new_entries:
       matrix.setdefault(e["label"], {})[e["week"]] = matrix.get(e["label"], {}).get(e["week"], 0) + 1
   ```
   写完验证：`assert set(json.load(open("activity_matrix.json")).keys()) == {"weeks", "matrix"}`

P1 终止：当前批次号 == batches.json 总批次数时，**下一轮重读本 SOP P2 段落并执行**，禁止继续处理或自行总结。

### P2: 汇总

⛔ P1 全部完成后必须执行以下步骤，禁止自行生成其他产物文件。

1. **验证矩阵**：确认 `activity_matrix.json` 已由 P1 增量生成。验证：`assert set(json.load(open("activity_matrix.json")).keys()) == {"weeks", "matrix"}`

2. **生成报告**：读 activity_matrix 判定 habits/abandoned，汇总 scan_results 中的情绪，写 `scan_report.json`。
   - habits — 各周计数之和≥3 且性质为「可复用技能」（周期性维护/持续使用的工具能力），⛔ 只出现1-2次 → 忽略
   - abandoned — 曾活跃但已完成/放弃的事项（具体项目开发、一次性配置/调研），只需标签名字符串
   - ⛔ habits 必须用 sessions 数量交叉验证（matrix 计数可能因 bug 虚高），`len(sessions) >= 2` 才可放入
   顶层 key 严格为 6 个：`scan_date, data_range, total_sessions, emotions, habits, abandoned`（禁止自创 key）。
   写完验证：`assert set(report.keys()) == {"scan_date","data_range","total_sessions","emotions","habits","abandoned"}`；`assert all(len(h["sessions"]) >= 2 for h in habits)`；若 emotions 非空：`assert set(emotions[0].keys()) == {"session","week","trigger","expression","traceback_query"}`；habits 非空：`assert set(habits[0].keys()) == {"label","sessions"}`；abandoned：`assert all(isinstance(a, str) for a in abandoned)`

3. **收尾（缺一不可）**：单个 code_run 内完成 ① 更新 `scan_state.json`（持久产物，禁止删除） ② 删除且仅删除 `task_dict.json`、`scan_results.json`、`batches.json` 三个临时文件 ③ assert 三个临时文件不存在 + `assert os.path.exists("scan_state.json")` + `assert os.path.exists("activity_matrix.json")` ④ 结束，禁止生成其他文件

## 坑点

- week 从 session 名首个日期 `MMdd` 推算 `YYYY-Wnn`（今年）
- task_dict key 数量 100+ 是正常的
- P1 禁止代码 if-elif 硬编码判断内容，必须自然语言阅读后用 code_run 写 JSON
- P2 每个产物的 json.dump 和 assert 必须在同一个 code_run 内
- P2 emotions 只从 scan_results 汇总，禁止凭记忆补充
- 所有产物文件名严格按本 SOP，禁止改名
- ⛔ P1 结束后必须进入 P2（生成 scan_report + 清理临时文件），禁止跳过 P2 直接输出总结或生成其他文件
