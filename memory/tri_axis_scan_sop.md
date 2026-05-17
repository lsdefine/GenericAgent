# 三轴扫描 SOP (tri_axis_scan_sop)

从历史对话中提取三轴信息：情绪波动点(emotion)、习惯事项(habits)、消失事项(abandoned)。
本SOP指导Agent自身完成扫描，Agent作为LLM直接分析文本，无需调用外部脚本。

## 触发条件
定时任务触发（scheduler注入prompt），或用户手动要求"执行三轴扫描"。

## 关键路径（相对于项目根）
```
数据源:     memory/L4_raw_sessions/all_user_histories.txt
状态文件:   reflect/analyzers/scan_state.json
中间产物:   reflect/analyzers/_scan_results.json
归一化映射: reflect/analyzers/_normalize_map.json
最终报告:   reflect/analyzers/scan_report.json
活动矩阵:   reflect/analyzers/activity_matrix.json
```

---

## Phase 0: 数据准备（code_run）

用code_run执行以下逻辑：
1. 读取 `scan_state.json`，获取 `emotion_last_line`（增量起点，首次为0）
2. 读取 `all_user_histories.txt`，按 `SESSION:` 头分割
3. 提取每个session中的 `[USER]:` 行（忽略长度≤5的）
4. 只保留行号 > emotion_last_line 的新增行
5. 分批：每批最多120行（按session为单位装入批次）
6. 将批次列表写入 `_batches.json`（JSON数组，每个元素=[{session, lines:[[行号,文本],...]}]）
7. 输出批次数量。若为0则无新数据，直接跳到Phase 4读取现有报告并结束
8. 启动 task_monitor 后台进程（自动续发保护，防止Agent自停导致任务中断）：

```python
import subprocess, sys, os

# 启动monitor后台进程
monitor_script = "reflect/task_monitor.py"
task_name = "tri_axis_scan"  # 与task目录名一致
python_exe = sys.executable.replace('pythonw.exe', 'python.exe')

proc = subprocess.Popen(
    [python_exe, monitor_script, task_name,
     "--complete-marker", "[TRI_AXIS_SCAN_COMPLETE]",
     "--max-replies", "5",
     "--interval", "15"],
    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
print(f"Monitor started (PID={proc.pid}), will auto-reply if agent stalls")
```

---
## Phase 1: 情绪+活动提取（code_run循环驱动，严格逐批）

⛔ **核心约束（防止质量退化，已验证的失败教训）：**
- **每轮只处理1批** —— 由code_run控制数据输出，Agent不可自行读取多批
- 每轮固定结构：`code_run(读第N批)` → Agent分析 → `code_run(写入结果)`
- **禁止为了效率一次处理多批** —— 这会导致后半段数据编造，是已验证的失败模式
- 分析必须基于当前轮code_run输出的实际文本，禁止凭记忆/概括
- 49批就是49轮循环，不可压缩。慢是正常的，质量优先

### 步骤A: code_run读取当前批次

每轮开始时执行code_run，读取并打印第N批文本：

```python
import json, os

batches_file = "reflect/analyzers/_batches.json"
results_file = "reflect/analyzers/_scan_results.json"

with open(batches_file, 'r', encoding='utf-8') as f:
    batches = json.load(f)

# 确定当前批次（断点恢复：检查已完成的批次数）
done = 0
if os.path.exists(results_file):
    with open(results_file, 'r', encoding='utf-8') as f:
        done = len(json.load(f))

if done >= len(batches):
    print("ALL_DONE: 所有批次已处理完毕，进入Phase 2")
else:
    batch = batches[done]
    print(f"=== 批次 {done}/{len(batches)} ===")
    for item in batch:
        print(f"\n--- SESSION: {item['session']} ---")
        for line_no, text in item['lines']:
            print(f"[{line_no}] {text}")
    print(f"\n--- END BATCH {done} ---")
```

### 步骤B: Agent分析（严格按以下规则执行）

阅读步骤A输出的文本，按以下规则分析：

**情绪检测规则（只找出用户情绪强烈爆发的瞬间）：**

仅标记以下情况：
- 累积不满后的爆发（连续多轮不满后终于发火）
- 明确的愤怒/质问/责备（不是普通追问，是真的生气了）
- 强烈讽刺挖苦（带攻击性的，不是随口吐槽）
- 极度惊喜或感激（远超正常反应，如反复感叹）

不标记（即使有轻微情绪）：
- 普通的不耐烦、催促
- 对结果不满意但语气平和的反馈
- 简单的抱怨或吐槽
- 任何可以理解为"正常沟通中的语气波动"的内容

判断技巧：去掉情绪化修饰后信息量是否减少？减少则标记。

label只用 NEGATIVE 或 POSITIVE。

**活动识别规则：**
- 为每个session提取用户实际在做的事情
- 标签格式：动词+宾语，4-8字（如"配置远程服务器"、"学习力扣算法"）
- 每个session至少1条，通常2-5条
- 不明确的session标记为 ["不明确"]

### 步骤C: code_run写入结果

分析完成后，用code_run将结果写入：

```python
import json, os

results_file = "reflect/analyzers/_scan_results.json"
results = []
if os.path.exists(results_file):
    with open(results_file, 'r', encoding='utf-8') as f:
        results = json.load(f)

# Agent填入本批分析结果
new_result = {
    "batch_idx": len(results),
    "emotions": [
        # {"line": 行号, "text": "原文前30字", "label": "NEGATIVE", "reason": "一句话理由"}
    ],
    "activities": [
        # {"session": "session名", "tasks": ["标签1", "标签2"]}
    ]
}

results.append(new_result)
with open(results_file, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

total = len(json.load(open("reflect/analyzers/_batches.json")))
print(f"OK batch {new_result['batch_idx']} done, progress {len(results)}/{total}")
```

### 步骤D: 循环

重复步骤A-B-C，直到步骤A输出 `ALL_DONE`。
每5批可输出一次简短进度，但不可跳过任何批次。

---
## Phase 2: 标签归一化（数据驱动，非凭记忆）

⛔ **必须执行本阶段，不可跳过。即使你认为标签已经足够清晰，也必须走归一化流程生成 `_normalize_map.json`。Phase 3+4 依赖此文件。**

### 步骤A: code_run提取所有标签

```python
import json

results_file = "reflect/analyzers/_scan_results.json"
with open(results_file, 'r', encoding='utf-8') as f:
    results = json.load(f)

all_tags = set()
for r in results:
    for act in r.get('activities', []):
        for t in act.get('tasks', []):
            if t != "不明确":
                all_tags.add(t)

tags_sorted = sorted(all_tags)
print(f"共{len(tags_sorted)}个独立标签：")
# 分批输出（每批50个）
for i in range(0, len(tags_sorted), 50):
    batch_tags = tags_sorted[i:i+50]
    print(f"\n--- 标签批次 {i//50} ({len(batch_tags)}个) ---")
    for t in batch_tags:
        print(f"  {t}")
```

### 步骤B: Agent归一化（逐批处理）

对步骤A输出的每批50个标签，按以下规则归一化：
- 同一件事的不同表述合并（选最清晰简洁的作为归一化名）
- 例如："编写单元测试"、"补充测试用例"、"写测试" -> "编写测试"
- 例如："部署服务"、"部署到生产环境"、"上线服务" -> "部署服务"
- **保守合并**：只合并明确同义词，不确定的保持独立
- "调试bug"和"修复bug"应保持独立（动作不同）
- 独立标签映射为自身

输出格式：{"原标签": "归一化名称", ...}

若标签数>50，必须分批处理（每批50个），每批独立分析后合并。禁止一次性处理100+标签。

### 步骤C: code_run写入映射

```python
import json

normalize_map = {
    # Agent填入归一化映射（所有批次合并后的完整映射）
}

normalize_file = "reflect/analyzers/_normalize_map.json"
with open(normalize_file, 'w', encoding='utf-8') as f:
    json.dump(normalize_map, f, ensure_ascii=False, indent=2)
print(f"OK normalize_map written, {len(normalize_map)} entries")
```

---
## Phase 3+4: 矩阵构建 + 习惯/消失判定（完整code_run，直接复制执行）

⛔ **以下代码必须完整复制到code_run中执行，禁止修改、简化或用其他方式替代。输出文件名（scan_report.json, activity_matrix.json, scan_state.json）和JSON格式不可更改，禁止输出markdown报告代替。**

```python
import json, os
from datetime import datetime, date

# === 路径 ===
base = "reflect/analyzers"
results_file = f"{base}/_scan_results.json"
normalize_file = f"{base}/_normalize_map.json"
report_file = f"{base}/scan_report.json"
matrix_file = f"{base}/activity_matrix.json"
state_file = f"{base}/scan_state.json"
data_file = "memory/L4_raw_sessions/all_user_histories.txt"

# === 1. 读取数据 ===
with open(results_file, 'r', encoding='utf-8') as f:
    results = json.load(f)
with open(normalize_file, 'r', encoding='utf-8') as f:
    norm_map = json.load(f)

# === 2. 汇总情绪 ===
all_emotions = []
for r in results:
    for e in r.get('emotions', []):
        all_emotions.append(e)

# === 3. 构建活动矩阵 ===
today = date.today()
current_week = today.isocalendar()
current_week_str = f"{current_week[0]}-W{current_week[1]:02d}"

# 从session名提取周次
def session_to_week(session_name):
    """从 MMdd_HHmm 格式提取周次"""
    try:
        parts = session_name.split('_')
        mm = int(parts[0][:2])
        dd = int(parts[0][2:4])
        d = date(2026, mm, dd)
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except:
        return None

# 构建 {归一化标签: {week: count}}
matrix = {}
for r in results:
    for act in r.get('activities', []):
        session = act.get('session', '')
        week = session_to_week(session)
        if not week:
            continue
        for task in act.get('tasks', []):
            if task == "\u4e0d\u660e\u786e":  # "不明确"
                continue
            # 应用归一化
            normalized = norm_map.get(task, task)
            if normalized not in matrix:
                matrix[normalized] = {}
            matrix[normalized][week] = matrix[normalized].get(week, 0) + 1

# === 4. 计算每个标签的统计 ===
def week_str_to_date(w):
    """将 2026-W11 转为该周的周一日期"""
    year, wk = int(w.split('-W')[0]), int(w.split('-W')[1])
    return datetime.strptime(f"{year}-W{wk:02d}-1", "%Y-W%W-%w").date()

# 计算当前周和上一周的周次字符串
from datetime import timedelta
last_2_weeks = set()
for i in range(2):
    d = today - timedelta(weeks=i)
    iso = d.isocalendar()
    last_2_weeks.add(f"{iso[0]}-W{iso[1]:02d}")

task_stats = {}
for task, weeks_data in matrix.items():
    total = sum(weeks_data.values())
    active_weeks = len(weeks_data)
    sorted_weeks = sorted(weeks_data.keys())
    last_week = sorted_weeks[-1] if sorted_weeks else ""
    is_recent = bool(set(weeks_data.keys()) & last_2_weeks)
    
    # 计算距今周数
    gap_weeks = 0
    if last_week and not is_recent:
        try:
            last_d = week_str_to_date(last_week)
            gap_weeks = (today - last_d).days // 7
        except:
            gap_weeks = 99
    
    task_stats[task] = {
        "total": total,
        "active_weeks": active_weeks,
        "last_week": last_week,
        "is_recent": is_recent,
        "gap_weeks": gap_weeks,
        "weeks_detail": weeks_data
    }

# === 5. 判定 habits ===
habits = []
for task, s in task_stats.items():
    if s["active_weeks"] >= 2 and s["is_recent"] and s["total"] >= 3:
        habits.append({"task": task, "total": s["total"], "active_weeks": s["active_weeks"], "last_week": s["last_week"]})
habits.sort(key=lambda x: x["total"], reverse=True)
habits = habits[:15]

# === 6. 判定 abandoned ===
abandoned = []
for task, s in task_stats.items():
    if s["total"] >= 3 and not s["is_recent"]:
        abandoned.append({"task": task, "total": s["total"], "active_weeks": s["active_weeks"], "last_week": s["last_week"], "gap_weeks": s["gap_weeks"]})
abandoned.sort(key=lambda x: x["total"], reverse=True)
abandoned = abandoned[:30]

# === 7. 写入 scan_report.json ===
report = {
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "emotions": {
        "count": len(all_emotions),
        "items": all_emotions
    },
    "habits": habits,
    "abandoned": abandoned,
    "summary": f"本次扫描: {len(all_emotions)}条情绪波动, {len(habits)}项习惯, {len(abandoned)}项消失事项"
}
with open(report_file, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# === 8. 写入 activity_matrix.json ===
matrix_output = {}
for task, s in sorted(task_stats.items(), key=lambda x: x[1]["total"], reverse=True):
    matrix_output[task] = {
        "total": s["total"],
        "active_weeks": s["active_weeks"],
        "last_week": s["last_week"],
        "is_recent": s["is_recent"],
        "weeks": s["weeks_detail"]
    }
with open(matrix_file, 'w', encoding='utf-8') as f:
    json.dump(matrix_output, f, ensure_ascii=False, indent=2)

# === 9. 更新 scan_state.json ===
# 读取数据文件总行数
with open(data_file, 'r', encoding='utf-8') as f:
    total_lines = sum(1 for _ in f)

old_state = {}
if os.path.exists(state_file):
    with open(state_file, 'r', encoding='utf-8') as f:
        old_state = json.load(f)

new_state = {
    "emotion_last_line": total_lines,
    "scan_count": old_state.get("scan_count", 0) + 1,
    "last_scan_date": today.strftime("%Y-%m-%d"),
    "status": "completed"
}
with open(state_file, 'w', encoding='utf-8') as f:
    json.dump(new_state, f, ensure_ascii=False, indent=2)

# === 10. 输出摘要 ===
print(f"=== Phase 3+4 完成 ===")
print(f"情绪波动: {len(all_emotions)}条")
print(f"习惯事项: {len(habits)}项")
print(f"消失事项: {len(abandoned)}项")
print(f"活动矩阵: {len(matrix_output)}个标签")
print(f"\n已写入:")
print(f"  {report_file}")
print(f"  {matrix_file}")
print(f"  {state_file}")
print(f"\nscan_state: emotion_last_line={total_lines}")
```

---
## Phase 5: 清理 + 验证

⛔ **必须执行以下清理代码。最后一行 `print("[TRI_AXIS_SCAN_COMPLETE]")` 是task_monitor判断任务完成的关键标记，不可省略。**

用code_run执行：

```python
import json, os

base = "reflect/analyzers"
batches_file = f"{base}/_batches.json"

# 1. 删除临时批次文件
if os.path.exists(batches_file):
    os.remove(batches_file)
    print(f"已删除: {batches_file}")

# 2. 验证所有输出文件存在且格式正确
required = ["scan_report.json", "activity_matrix.json", "scan_state.json"]
for fname in required:
    path = f"{base}/{fname}"
    if not os.path.exists(path):
        print(f"ERROR: 缺失 {fname}")
        continue
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"OK: {fname} ({os.path.getsize(path)} bytes)")

# 3. 输出最终摘要
with open(f"{base}/scan_report.json", 'r', encoding='utf-8') as f:
    report = json.load(f)
print(f"\n=== 最终报告摘要 ===")
print(report["summary"])
print(f"\n保留中间产物供下次增量: _scan_results.json, _normalize_map.json")
print("\n[TRI_AXIS_SCAN_COMPLETE]")
```

---

## 周次推算规则

session名格式为 `MMdd_HHmm-MMdd_HHmm`，需要结合当前年份推算：
- 提取第一个MMdd
- 用 `datetime(2026, MM, DD).isocalendar()` 获取周次
- 输出格式: `2026-Wxx`

---

## 断点恢复

若执行中断：
1. 检查 `_batches.json` 是否存在 -> 存在则跳过Phase0
2. 检查 `_scan_results.json` 已处理的batch_idx -> 从下一个继续Phase1
3. 检查 `_normalize_map.json` 是否存在 -> 存在则跳过Phase2

---

## 注意事项
- Agent自身就是LLM，直接阅读文本分析即可，不需要调用任何外部LLM API
- 每个Phase都是独立的code_run或分析步骤，单步不会超时
- Phase1是严格循环：每批2次code_run（读+写）+ 1次分析，约25批需50轮工具调用
- 若挂载到task模式运行，配合 `reflect/task_monitor.py` 自动续发（防止agent自停）
- 情绪检测高阈值：宁可漏检不可误检，只标记真正的情绪爆发
- 活动标签要具体：避免过于笼统（如"编程"），应该是"调试API接口"这样的粒度
- Phase2归一化保守合并：只合并明确同义词，不确定的保持独立
