# history_insight P3+P4: 矩阵构建+判定+写入产物
# 输出格式对齐 reflect/analyzers/tri_axis_scanner.py
# 用法: python build_report.py [工作目录]
import json, os, sys, time
from datetime import datetime, date
from collections import defaultdict

t0 = time.time()
os.chdir(sys.argv[1] if len(sys.argv) > 1 else ".")
scan_results = json.load(open("scan_results.json", encoding="utf-8"))
normalize_map = json.load(open("normalize_map.json", encoding="utf-8"))

# 读取上次状态
prev_state = {}
if os.path.exists("scan_state.json"):
    prev_state = json.load(open("scan_state.json", encoding="utf-8"))
start_line = prev_state.get("emotion_last_line", 0)

# ============================================================
# Phase 3a: 提取情绪事件 (对齐 emotion.detections 格式)
# ============================================================
all_emotions = []
for batch in scan_results:
    for e in batch.get("emotions", []):
        # 对齐字段名: line→line_no, 补 traceback_query/occurrence_nth
        raw_text = e.get("text", "")
        # text 格式: "[USER]: 原文"
        text_with_prefix = raw_text if raw_text.startswith("[USER]:") else f"[USER]: {raw_text}"
        # traceback_query: 不带前缀的纯文本
        traceback_query = raw_text.lstrip("[USER]: ").strip() if raw_text.startswith("[USER]:") else raw_text.strip()

        all_emotions.append({
            "line_no": e.get("line_no", e.get("line", 0)),
            "label": e.get("label", "NEGATIVE"),
            "reason": e.get("reason", ""),
            "text": text_with_prefix,
            "traceback_query": traceback_query,
            "occurrence_nth": e.get("occurrence_nth", 0),
        })

# 按行号排序
all_emotions.sort(key=lambda x: x["line_no"])
max_line = max((e["line_no"] for e in all_emotions), default=start_line)

# 统计
total_user_lines = max_line  # 近似: 最大行号≈总用户行数
total_negative = sum(1 for e in all_emotions if e["label"] == "NEGATIVE")
total_positive = sum(1 for e in all_emotions if e["label"] == "POSITIVE")
scan_range = [start_line + 1, max_line] if start_line > 0 else [1, max_line]
new_lines_scanned = scan_range[1] - scan_range[0] + 1 if scan_range[1] >= scan_range[0] else 0

emotion_stats = {
    "total_user_lines": total_user_lines,
    "total_negative": total_negative,
    "total_positive": total_positive,
    "detection_rate": round(len(all_emotions) / max(total_user_lines, 1) * 100, 1),
}

# ============================================================
# Phase 3b: 构建活动矩阵 + task_sessions (用于 source_lines)
# ============================================================
matrix = defaultdict(lambda: defaultdict(int))
task_sessions = defaultdict(list)  # {task: [{text, session}]}

for batch in scan_results:
    for act in batch.get("activities", []):
        sess = act.get("session", "")
        try:
            mm, dd = int(sess[:2]), int(sess[2:4])
            week_str = f"2026-W{date(2026, mm, dd).isocalendar()[1]:02d}"
        except (ValueError, IndexError):
            continue
        for raw_tag in act.get("tasks", []):
            tag = normalize_map.get(raw_tag, raw_tag)
            matrix[tag][week_str] += 1
            # 收集 source_lines (每个task最多保留15条)
            if len(task_sessions[tag]) < 15:
                # 取该session中的一条代表性文本
                text_sample = act.get("text", raw_tag)
                task_sessions[tag].append({"text": text_sample, "session": sess})

# 合并已有矩阵（增量）
if os.path.exists("activity_matrix.json"):
    old_matrix = json.load(open("activity_matrix.json", encoding="utf-8"))
    for tag, weeks in old_matrix.items():
        for w, c in weeks.items():
            if w not in matrix[tag] or matrix[tag][w] == 0:
                matrix[tag][w] = c

# ============================================================
# Phase 3c: 习惯/消失判定 (对齐 tri_axis_scanner.py 格式)
# ============================================================
iso_now = date.today().isocalendar()
current_week = f"{iso_now[0]}-W{iso_now[1]:02d}"
recent_weeks = {current_week, f"{iso_now[0]}-W{max(iso_now[1]-1, 1):02d}"}

habits = []
abandoned = []

for task, week_counts in matrix.items():
    total_count = sum(week_counts.values())
    active_weeks = sorted(week_counts.keys())
    span = len(active_weeks)
    last_week = active_weeks[-1] if active_weeks else ""

    # 计算 gap（当前周 - 最后活跃周）
    try:
        cur_y, cur_w = current_week.split("-W")
        last_y, last_w = last_week.split("-W")
        gap = (int(cur_y) - int(last_y)) * 52 + (int(cur_w) - int(last_w))
    except:
        gap = 0

    is_recent = any(w in recent_weeks for w in active_weeks)

    # source_lines: 最多15条 (仅habits需要)
    sources = task_sessions.get(task, [])[:15]

    if span >= 2 and is_recent and total_count >= 3:
        habits.append({
            "task": task,
            "weeks_active": active_weeks,
            "total_count": total_count,
            "span": span,
            "source_lines": sources,
        })
    elif total_count >= 3 and not is_recent:
        abandoned.append({
            "task": task,
            "weeks_active": active_weeks,
            "total_count": total_count,
            "last_week": last_week,
            "gap": gap,
        })

# 排序+限制数量
habits.sort(key=lambda x: x["total_count"], reverse=True)
abandoned.sort(key=lambda x: x["total_count"], reverse=True)
habits = habits[:15]
abandoned = abandoned[:30]

elapsed = round(time.time() - t0, 1)

# ============================================================
# Phase 4: 输出报告 (对齐 tri_axis_scanner.py report 结构)
# ============================================================
summary = (
    f"情绪: {len(all_emotions)}条检出 | "
    f"习惯: {len(habits)}项 [{', '.join(h['task'] for h in habits[:3])}] | "
    f"消失: {len(abandoned)}项 [{', '.join(a['task'] for a in abandoned[:3])}]"
)

report = {
    "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "elapsed_seconds": elapsed,
    "emotion": {
        "count": len(all_emotions),
        "scan_range": scan_range,
        "new_lines_scanned": new_lines_scanned,
        "detections": all_emotions,
        "stats": emotion_stats,
    },
    "habits": {
        "count": len(habits),
        "items": habits,
    },
    "abandoned": {
        "count": len(abandoned),
        "items": abandoned,
    },
    "errors": [],
    "summary": summary,
}

# 写入产物
with open("scan_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

# activity_matrix: 转为普通dict写入
matrix_output = {k: dict(v) for k, v in matrix.items()}
with open("activity_matrix.json", "w", encoding="utf-8") as f:
    json.dump(matrix_output, f, ensure_ascii=False, indent=2)

# scan_state: 对齐字段
N = len(scan_results)
state = {
    "phase": "P4_COMPLETE",
    "batches_total": N,
    "batches_done": N,
    "p2_done": True,
    "p3_done": True,
    "last_scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "last_updated": date.today().isoformat(),
    "emotion_last_line": max_line,
    "scan_count": prev_state.get("scan_count", 0) + 1,
}
with open("scan_state.json", "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

# P4清理+验证
if os.path.exists("batches.json"):
    os.remove("batches.json")
for f_name in ["scan_report.json", "activity_matrix.json", "scan_state.json"]:
    json.load(open(f_name, encoding="utf-8"))

print(f"[BUILD_REPORT_DONE] emotions={len(all_emotions)}, habits={len(habits)}, abandoned={len(abandoned)}, matrix_tags={len(matrix)}")
print(f"  elapsed: {elapsed}s | summary: {summary}")
