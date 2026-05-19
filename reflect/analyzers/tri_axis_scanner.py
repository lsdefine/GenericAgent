"""tri_axis_scanner.py - 统一扫描器
一次扫描同时输出：情绪波动点 + 活动标签，再通过归一化+矩阵判定习惯/消失。
支持增量扫描，输出 scan_report.json / scan_state.json / activity_matrix.json。
"""
import sys, os, json, time, re
from collections import defaultdict
from datetime import datetime, date

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from llmcore import fast_ask

CFG = os.environ.get("SCANNER_LLM_CFG", "claude_config")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
L4_DIR = os.path.join(PROJECT_ROOT, 'memory', 'L4_raw_sessions')
DATA_PATH = os.path.join(L4_DIR, 'all_user_histories.txt')
REPORT_FILE = os.path.join(BASE_DIR, "scan_report.json")
STATE_FILE = os.path.join(BASE_DIR, "scan_state.json")
MATRIX_FILE = os.path.join(BASE_DIR, "activity_matrix.json")


def prepare_data():
    """调用compress_session生成all_histories.txt，再过滤出仅含USER行的all_user_histories.txt"""
    import importlib.util
    compress_script = os.path.join(L4_DIR, 'compress_session.py')
    if not os.path.exists(compress_script):
        return
    # 动态加载compress_session模块
    spec = importlib.util.spec_from_file_location("compress_session", compress_script)
    cs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cs)
    # 执行batch_process更新all_histories.txt
    raw_dir = os.path.join(PROJECT_ROOT, 'temp', 'model_responses')
    if os.path.isdir(raw_dir):
        cs.batch_process(raw_dir, l4_dir=L4_DIR, dry_run=False)
    # 从all_histories.txt过滤出仅USER行 → all_user_histories.txt
    all_hist = os.path.join(L4_DIR, 'all_histories.txt')
    if not os.path.exists(all_hist):
        return
    with open(all_hist, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('SESSION:') or stripped.startswith('=' * 10) or stripped.startswith('[USER]:'):
                f.write(line)


def p(msg):
    print(msg, flush=True)


# ============================================================
# PROMPTS
# ============================================================
UNIFIED_PROMPT = """你是一个精确的对话分析器，同时执行两个任务：

## 任务1: 情绪波动检测
只找出用户情绪强烈爆发的瞬间。

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

## 任务2: 活动标注
为每个session标注1-3个活动标签，描述用户主动发起的目标或项目（动词+宾语）。
- 只标注用户真正想做的事，忽略AI的中间执行步骤
- 如果session内容不明确或太短，标注为"不明确"

## 输入格式
多个session，每个session有编号和多条用户发言（带行号）。

## 输出格式
严格JSON，包含两个数组：
{
  "emotions": [{"line": 行号, "label": "NEGATIVE"|"POSITIVE", "reason": "一句话理由"}],
  "activities": [{"session": session编号, "tasks": ["标签1", "标签2"]}]
}

- emotions: 只输出强烈情绪爆发的行，没有则为空数组。
- activities: 每个session都要有一条

只输出JSON，不要其他内容。"""

NORMALIZE_PROMPT = """你是一个标签归一化器。给定一组活动标签，将含义相同或高度相关的标签合并为统一名称。

规则：
- 同一件事的不同表述合并为一个（选最清晰简洁的）
- 例如："编写单元测试"、"补充测试用例"、"写测试" -> "编写测试"
- 例如："部署服务"、"部署到生产环境"、"上线服务" -> "部署服务"
- 独立标签保持原样，不强行合并

输出JSON对象: {"原标签": "归一化名称", ...}
只输出JSON。"""


# ============================================================
# 工具函数
# ============================================================
def robust_json_parse(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()
    try:
        return json.loads(text)
    except:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                return json.loads(m.group())
            except:
                pass
    return None


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"last_scan_time": None, "emotion_last_line": 0, "habits_last_scan": None, "scan_count": 0}


def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_week(session_name):
    """从session名提取周标识"""
    m = re.match(r'(\d{4})(\d{2})(\d{2})', session_name)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return f"{d.year}-W{d.isocalendar()[1]:02d}"
        except:
            pass
    m = re.match(r'(\d{2})(\d{2})_', session_name)
    if m:
        try:
            d = date(date.today().year, int(m.group(1)), int(m.group(2)))
            return f"{d.year}-W{d.isocalendar()[1]:02d}"
        except:
            pass
    return "unknown"


def get_current_week():
    today = date.today()
    return f"{today.year}-W{today.isocalendar()[1]:02d}"


# ============================================================
# 数据加载
# ============================================================
def load_sessions(start_line=0):
    """加载数据，返回 [(session_name, [(global_line_no, text), ...])]
    如果 start_line > 0，只加载该行之后的内容（增量模式）。
    同时返回文件总行数。
    """
    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    total_lines = len(lines)
    sessions = []
    current_session = None
    current_lines = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('SESSION:'):
            if current_session and current_lines:
                # 只保留有新行的session
                new_lines = [(ln, t) for ln, t in current_lines if ln > start_line]
                if new_lines:
                    sessions.append((current_session, current_lines))  # 保留完整session用于上下文
            current_session = stripped[8:].strip()
            current_lines = []
        elif stripped.startswith('=' * 10):
            continue
        elif stripped.startswith('[USER]:'):
            text = stripped[7:].strip()
            if text and len(text) > 5:
                current_lines.append((i, text))

    if current_session and current_lines:
        new_lines = [(ln, t) for ln, t in current_lines if ln > start_line]
        if new_lines:
            sessions.append((current_session, current_lines))

    return sessions, total_lines


# ============================================================
# 分批
# ============================================================
def build_batches(sessions, max_lines_per_batch=60):
    batches = []
    current_batch = []
    current_lines_count = 0

    for session_name, session_lines in sessions:
        if len(session_lines) > max_lines_per_batch:
            if current_batch:
                batches.append(current_batch)
                current_batch = []
                current_lines_count = 0
            batches.append([(session_name, session_lines)])
            continue

        if current_lines_count + len(session_lines) > max_lines_per_batch:
            batches.append(current_batch)
            current_batch = []
            current_lines_count = 0

        current_batch.append((session_name, session_lines))
        current_lines_count += len(session_lines)

    if current_batch:
        batches.append(current_batch)

    return batches


def format_batch(batch):
    parts = []
    for idx, (session_name, session_lines) in enumerate(batch, 1):
        parts.append(f"--- Session {idx}: {session_name} ---")
        for line_no, text in session_lines:
            parts.append(f"  [{line_no}] {text}")
        parts.append("")
    return '\n'.join(parts)


# ============================================================
# 主流程
# ============================================================
def main():
    t0 = time.time()
    p(f"[TriAxisScanner] 启动, cfg={CFG}")

    # Phase 0: 数据准备 - 压缩原始日志并提取USER行
    prepare_data()

    # 加载状态（增量扫描）
    state = load_state()
    start_line = state.get('emotion_last_line', 0)
    is_incremental = start_line > 0
    p(f"[模式] {'增量' if is_incremental else '全量'} (从第{start_line}行开始)")

    # Phase 0: 加载数据
    sessions, total_file_lines = load_sessions(start_line)
    total_user_lines = sum(len(lines) for _, lines in sessions)
    new_lines_count = sum(1 for _, lines in sessions for ln, _ in lines if ln > start_line)
    p(f"[数据] {len(sessions)} sessions, {total_user_lines} USER行 (新增{new_lines_count}行)")

    if not sessions:
        p("[完成] 无新数据需要扫描")
        return

    # 分批
    batches = build_batches(sessions, max_lines_per_batch=60)
    p(f"[分批] {len(batches)} 批")

    # 加载已有报告（增量模式下合并）
    existing_emotions = []
    if is_incremental and os.path.exists(REPORT_FILE):
        with open(REPORT_FILE, 'r', encoding='utf-8') as f:
            old_report = json.load(f)
        existing_emotions = old_report.get('emotion', {}).get('detections', [])
        p(f"[增量] 已有{len(existing_emotions)}条情绪记录")

    # Phase 1: 统一扫描
    p("\n[Phase1] 统一扫描...")
    all_emotions = list(existing_emotions)  # 保留旧数据
    all_activities = []  # [(session_name, [tasks], [(line_no, text)])]
    emotion_counter = defaultdict(int)  # 用于occurrence_nth

    for batch_idx, batch in enumerate(batches):
        user_content = format_batch(batch)
        prompt = UNIFIED_PROMPT + "\n\n## 待分析内容\n" + user_content

        try:
            result = fast_ask(prompt, CFG)
            parsed = robust_json_parse(result)

            if not parsed:
                p(f"  Batch {batch_idx+1}/{len(batches)}: PARSE FAILED")
                for session_name, session_lines in batch:
                    all_activities.append((session_name, ["不明确"], session_lines))
                continue

            # 提取情绪
            emotions = parsed.get('emotions', [])
            for emo in emotions:
                try:
                    line_no = int(emo.get('line', 0))
                except (ValueError, TypeError):
                    continue
                # 找到对应的原文
                text = ""
                for _, session_lines in batch:
                    for ln, t in session_lines:
                        if ln == line_no:
                            text = t
                            break
                    if text:
                        break

                label = emo.get('label', 'NEGATIVE')
                emotion_counter[label] += 1

                all_emotions.append({
                    'line_no': line_no,
                    'label': label,
                    'reason': emo.get('reason', ''),
                    'text': f"[USER]: {text}",
                    'traceback_query': text,
                    'occurrence_nth': emotion_counter[label] - 1,
                })

            # 提取活动
            activities = parsed.get('activities', [])
            for act in activities:
                try:
                    sess_idx = int(act.get('session', 1)) - 1
                except (ValueError, TypeError):
                    sess_idx = 0
                tasks = act.get('tasks', ['不明确'])
                if 0 <= sess_idx < len(batch):
                    session_name, session_lines = batch[sess_idx]
                    all_activities.append((session_name, tasks, session_lines))

            # 补充没被标注的session
            tagged_indices = set()
            for act in activities:
                try:
                    tagged_indices.add(int(act.get('session', 0)) - 1)
                except (ValueError, TypeError):
                    pass
            for i, (session_name, session_lines) in enumerate(batch):
                if i not in tagged_indices:
                    all_activities.append((session_name, ["不明确"], session_lines))

            p(f"  Batch {batch_idx+1}/{len(batches)}: OK (emo={len(emotions)}, sessions={len(batch)})")

        except Exception as e:
            p(f"  Batch {batch_idx+1}/{len(batches)}: ERROR {e}")
            for session_name, session_lines in batch:
                all_activities.append((session_name, ["不明确"], session_lines))

    p(f"\n[Phase1完成] 情绪={len(all_emotions)}, 活动标注={len(all_activities)} sessions")

    # Phase 2: 归一化活动标签
    p("[Phase2] 归一化标签...")
    all_tags = set()
    for _, tasks, _ in all_activities:
        for t in tasks:
            if t != "不明确":
                all_tags.add(t)

    all_tags = sorted(all_tags)
    p(f"  原始标签数: {len(all_tags)}")

    normalize_map = {}
    if all_tags:
        batch_size = 150
        for i in range(0, len(all_tags), batch_size):
            chunk = all_tags[i:i+batch_size]
            prompt = NORMALIZE_PROMPT + "\n\n标签列表:\n" + json.dumps(chunk, ensure_ascii=False)
            try:
                result = fast_ask(prompt, CFG)
                parsed = robust_json_parse(result)
                if parsed and isinstance(parsed, dict):
                    normalize_map.update(parsed)
                    p(f"  归一化批次 {i//batch_size+1}: {len(parsed)} 条映射")
            except Exception as e:
                p(f"  归一化批次 {i//batch_size+1}: ERROR {e}")

    p(f"  归一化映射总数: {len(normalize_map)}")

    # Phase 3: 构建活动矩阵
    p("[Phase3] 构建矩阵...")

    # 矩阵: {normalized_task: {week: count}}
    matrix = defaultdict(lambda: defaultdict(int))
    task_sessions = defaultdict(list)  # {task: [(session_name, text)]}

    for session_name, tasks, session_lines in all_activities:
        week = get_week(session_name)
        for task in tasks:
            if task == "不明确":
                continue
            normalized = normalize_map.get(task, task)
            matrix[normalized][week] += 1
            # 收集source_lines（每个task最多保留15条）
            for ln, text in session_lines[:3]:
                task_sessions[normalized].append({'text': text, 'session': session_name})

    # 收集所有周
    all_weeks = sorted(set(w for task_weeks in matrix.values() for w in task_weeks.keys()))
    p(f"  任务数: {len(matrix)}, 周数: {len(all_weeks)}")

    # 输出 activity_matrix.json
    matrix_output = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'weeks': all_weeks,
        'tasks': {}
    }
    for task, week_counts in sorted(matrix.items(), key=lambda x: sum(x[1].values()), reverse=True):
        matrix_output['tasks'][task] = {
            'total': sum(week_counts.values()),
            'by_week': dict(week_counts),
        }

    with open(MATRIX_FILE, 'w', encoding='utf-8') as f:
        json.dump(matrix_output, f, ensure_ascii=False, indent=2)
    p(f"  activity_matrix.json 已保存 ({len(matrix_output['tasks'])} tasks)")

    # Phase 4: 判定习惯和消失
    p("[Phase4] 判定习惯/消失...")

    current_week = get_current_week()
    recent_weeks = all_weeks[-4:] if len(all_weeks) >= 4 else all_weeks

    habits = []
    abandoned = []

    for task, week_counts in matrix.items():
        total_count = sum(week_counts.values())
        active_weeks = sorted(week_counts.keys())
        span = len(active_weeks)
        last_week = active_weeks[-1] if active_weeks else ""

        # 计算gap（当前周 - 最后活跃周）
        try:
            cur_y, cur_w = current_week.split('-W')
            last_y, last_w = last_week.split('-W')
            gap = (int(cur_y) - int(last_y)) * 52 + (int(cur_w) - int(last_w))
        except:
            gap = 0

        is_recent = any(w in recent_weeks for w in active_weeks)

        # source_lines: 最多15条
        sources = task_sessions.get(task, [])[:15]

        if span >= 2 and is_recent and total_count >= 3:
            habits.append({
                'task': task,
                'weeks_active': active_weeks,
                'total_count': total_count,
                'span': span,
                'source_lines': sources,
            })
        elif total_count >= 3 and not is_recent:
            abandoned.append({
                'task': task,
                'weeks_active': active_weeks,
                'total_count': total_count,
                'last_week': last_week,
                'gap': gap,
            })

    # 排序
    habits.sort(key=lambda x: x['total_count'], reverse=True)
    abandoned.sort(key=lambda x: x['total_count'], reverse=True)

    # 限制数量
    habits = habits[:15]
    abandoned = abandoned[:30]

    elapsed = round(time.time() - t0, 1)

    # Phase 5: 输出报告
    p("[Phase5] 输出报告...")

    # 情绪排序（按行号）
    all_emotions.sort(key=lambda x: x['line_no'])

    # 统计
    total_negative = sum(1 for e in all_emotions if e['label'] == 'NEGATIVE')
    total_positive = sum(1 for e in all_emotions if e['label'] == 'POSITIVE')
    stats = {
        'total_user_lines': total_user_lines,
        'total_negative': total_negative,
        'total_positive': total_positive,
        'detection_rate': round(len(all_emotions) / max(total_user_lines, 1) * 100, 1),
    }

    scan_range = [start_line + 1, total_file_lines] if is_incremental else [1, total_file_lines]

    summary = (
        f"情绪: {len(all_emotions)}条检出 | "
        f"习惯: {len(habits)}项 [{', '.join(h['task'] for h in habits[:3])}] | "
        f"消失: {len(abandoned)}项 [{', '.join(a['task'] for a in abandoned[:3])}]"
    )

    report = {
        'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'elapsed_seconds': elapsed,
        'emotion': {
            'count': len(all_emotions),
            'scan_range': scan_range,
            'new_lines_scanned': new_lines_count,
            'detections': all_emotions,
            'stats': stats,
        },
        'habits': {
            'count': len(habits),
            'items': habits,
        },
        'abandoned': {
            'count': len(abandoned),
            'items': abandoned,
        },
        'errors': [],
        'summary': summary,
    }

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 更新状态
    state['last_scan_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    state['emotion_last_line'] = total_file_lines
    state['habits_last_scan'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    state['scan_count'] = state.get('scan_count', 0) + 1
    save_state(state)

    p(f"\n{'='*60}")
    p(f"完成 ({elapsed}s)")
    p(f"输出: {REPORT_FILE}")
    p(f"{'='*60}")
    p(f"\n{summary}")


if __name__ == '__main__':
    main()
