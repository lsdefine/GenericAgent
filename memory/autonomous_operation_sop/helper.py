"""
autonomous_task.py - 自主行动任务管理API
放置: memory/autonomous_operation_sop/
用法: import autonomous_task (或 from autonomous_operation_sop import autonomous_task)

5个函数:
  get_todo()        → 返回TODO内容
  get_history(n)    → 返回最近n条历史
  complete_task()   → 移报告+编号+写history+返回改TODO指令
  set_todo()        → 返回TODO真实路径
  run_subagent()    → 启动subagent执行一次性任务（绝对路径防cwd bug）
"""

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

# ── 路径计算（基于模块自身位置） ──
_MODULE_DIR = Path(__file__).resolve().parent          # memory/autonomous_operation_sop/
_MEMORY_DIR = _MODULE_DIR.parent                       # memory/
_AGENT_DIR = _MEMORY_DIR.parent                        # GenericAgent/
_TEMP_DIR = _AGENT_DIR / "temp"                        # GenericAgent/temp/
_REPORTS_DIR = _TEMP_DIR / "autonomous_reports"
_HISTORY_FILE = _REPORTS_DIR / "history.txt"
_TODO_FILE = _TEMP_DIR / "TODO.txt"

def _next_report_number() -> int:
    """扫 history.txt 第一行提取最大 RXX 编号，返回下一个"""
    if not _HISTORY_FILE.exists():
        return 1
    with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    # 匹配所有 R 后跟数字的模式
    nums = [int(m) for m in re.findall(r'R(\d+)', content)]
    if not nums:
        return 1
    return max(nums) + 1


def run_subagent(task_name: str, input_content: str) -> dict:
    """
    启动 subagent 执行一次性任务（文件IO模式）。
    使用绝对路径，避免 cwd 拼接 bug。
    
    Args:
        task_name: 任务目录名（无特殊字符，用于 temp/{task_name}）
        input_content: 任务描述文本（写入 input.txt 供agent读取）
    
    Returns:
        dict: {success: bool, task_dir: str|None, pid: int|None, error: str|None}
    """
    import subprocess
    import platform
    
    ga_root = str(_AGENT_DIR)
    task_dir = os.path.join(ga_root, 'temp', task_name)
    
    try:
        os.makedirs(task_dir, exist_ok=True)
        
        # 写入 input.txt
        in_file = os.path.join(task_dir, 'input.txt')
        with open(in_file, 'w', encoding='utf-8') as f:
            f.write(input_content)
        
        # 启动 agentmain.py --task (无 --nobg → 自动进入background mode)
        agentmain = os.path.join(ga_root, 'agentmain.py')
        cmd = [sys.executable, agentmain, '--task', task_name]
        creationflags = 0x08000000 if platform.system() == 'Windows' else 0  # CREATE_NO_WINDOW
        
        proc = subprocess.Popen(
            cmd, cwd=ga_root,
            creationflags=creationflags,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        # agentmain.py background mode prints PID to stdout then exits
        stdout, stderr = proc.communicate(timeout=10)
        pid_str = stdout.strip()
        pid = int(pid_str) if pid_str.isdigit() else None
        
        if proc.returncode != 0:
            return {
                'success': False,
                'task_dir': task_dir,
                'pid': None,
                'error': f'agentmain exited code={proc.returncode}, stderr={stderr[:200]}'
            }
        
        return {
            'success': True,
            'task_dir': task_dir,
            'pid': pid,
            'error': None
        }
    except subprocess.TimeoutExpired:
        proc.kill()
        return {'success': False, 'task_dir': task_dir, 'pid': None, 'error': 'Timeout waiting for agentmain to spawn'}
    except Exception as e:
        return {'success': False, 'task_dir': task_dir, 'pid': None, 'error': str(e)}


def get_todo() -> str:
    """返回 TODO.txt 的内容。若文件不存在返回提示。"""
    if not _TODO_FILE.exists(): return f"[autonomous_task] TODO.txt 不存在，路径: {_TODO_FILE}"
    with open(_TODO_FILE, "r", encoding="utf-8") as f: return f.read()

def get_history(n: int = 20) -> str:
    """返回 history.txt 的前 n 行（最新在前）。"""
    if not _HISTORY_FILE.exists():
        return f"[autonomous_task] history.txt 不存在，路径: {_HISTORY_FILE}"
    with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[:n])


def set_todo(*args, **kwargs) -> str:
    """返回 TODO.txt 的真实绝对路径，供 agent/子agent 自行读写。"""
    return f'路径: {str(_TODO_FILE)}'


def _update_todo(rnum: int, taskname: str, historyline: str) -> str:
    """
    自动更新 TODO.txt：
    1. 按 taskname 关键词匹配待执行项，移除匹配行
    2. 追加 [✅] R{rnum} | {historyline核心} 到已完成区
    """
    if not _TODO_FILE.exists():
        return "TODO.txt 不存在，跳过"

    with open(_TODO_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    # 提取 taskname 中的关键词（去常见停用词）
    keywords = set(re.findall(r'[\w]+', taskname.lower()))
    stopwords = {'修复', '实施', '设计', '改造', '集成', '优化', 'the', 'a', 'an', 'of', 'and', 'to', 'in'}
    keywords -= stopwords
    if not keywords:
        keywords = set(re.findall(r'[\w]+', taskname.lower()))

    # 找待执行区并匹配（只移除最高分匹配行）
    pending_start = None
    done_start = None
    best_match_idx = None
    best_match_score = 0
    best_match_line = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## ") and "待执行" in stripped:
            pending_start = i
        elif stripped.startswith("## ") and "已完成" in stripped:
            done_start = i

        if pending_start is not None and done_start is None and stripped.startswith("[ ]"):
            line_lower = stripped.lower()
            match_score = sum(1 for kw in keywords if kw in line_lower)
            if match_score > best_match_score and match_score >= max(1, len(keywords) // 2):
                best_match_score = match_score
                best_match_idx = i
                best_match_line = stripped

    # 移除最佳匹配行
    new_lines = [line for i, line in enumerate(lines) if i != best_match_idx]
    removed_line = best_match_line

    # 如果没匹配到，不报错，只追加到已完成
    # 找已完成区，在第一行 [✅] 或 [x] 前插入
    if done_start is not None:
        insert_idx = None
        for i in range(done_start + 1, len(new_lines)):
            if new_lines[i].strip().startswith("[✅]") or new_lines[i].strip().startswith("[x]"):
                insert_idx = i
                break
        if insert_idx is None:
            insert_idx = done_start + 1

        # 从 historyline 提取核心描述（去编号和日期）
        core = historyline.strip()
        core = re.sub(r'^R\d+\s*\|\s*', '', core)
        core = re.sub(r'^\d{4}-\d{2}-\d{2}\s*\|\s*', '', core)
        # 只保留类型|主题|结论（去掉冗长的验收详情）
        parts = [p.strip() for p in core.split("|")]
        if len(parts) > 3:
            core = " | ".join(parts[:3])

        done_entry = "[✅] R{} | {}".format(rnum, core)
        new_lines.insert(insert_idx, done_entry)

    with open(_TODO_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines))

    if removed_line:
        return "移除 [{}] + 追加已完成项".format(removed_line[:40])
    return "未匹配待执行项，仅追加已完成项"


def complete_task(taskname: str, historyline: str, report_path: str) -> str:
    """
    完成任务的原子操作：
    1. 移动 report_path → autonomous_reports/R{XX}_{taskname}.md（自动编号）
    2. prepend historyline 到 history.txt（校验必须单行）
    3. 返回字符串指示 agent 自己去改 TODO
    Args:
        taskname: 任务简短名称（用于报告文件名，如 "晨间简报"）
        historyline: 历史记录内容（必须单行，日期自动添加，如 "工程 | 晨间简报 | 完成7模块聚合"）
        report_path: agent 已写好的报告文件路径（绝对或相对于cwd）
    Returns:
        成功消息 + 改TODO指令，或错误消息
    """
    errors = []

    # ── 校验 ──
    if "\n" in historyline.strip():
        return "[ERROR] historyline 必须是单行，不能包含换行符"

    report = Path(report_path).resolve()
    if not report.exists():
        return f"[ERROR] 报告文件不存在: {report_path}"

    if not _REPORTS_DIR.exists():
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1. 移动报告 ──
    rnum = _next_report_number()
    # 清理 taskname 中的非法文件名字符
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', taskname).strip()
    dest_name = f"R{rnum}_{safe_name}.md"
    dest_path = _REPORTS_DIR / dest_name

    try:
        shutil.move(str(report), str(dest_path))
    except Exception as e:
        return f"[ERROR] 移动报告失败: {e}"

    # ── 2. prepend history ──
    # 自动加编号 + 日期（剥离 agent 可能已写的编号/日期，统一重建）
    line = historyline.strip()
    line = re.sub(r'^R\d+\s*\|\s*', '', line)           # 剥离 R 编号
    line = re.sub(r'^\d{4}-\d{2}-\d{2}\s*\|\s*', '', line)  # 剥离日期
    today = datetime.now().strftime('%Y-%m-%d')
    line = f"R{rnum} | {today} | {line}"

    try:
        existing = ""
        if _HISTORY_FILE.exists():
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                existing = f.read()
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write(line + "\n" + existing)
    except Exception as e:
        # 回滚：把报告移回去
        try:
            shutil.move(str(dest_path), str(report))
        except:
            pass
        return f"[ERROR] 写入 history 失败: {e}（报告已回滚）"

    # ── 3. 同步重建 report_index.json（确保查询立即可用） ──
    try:
        sys.path.insert(0, str(_TEMP_DIR))
        from rebuild_report_index import main as rebuild_index
        rebuild_index()
    except Exception as e:
        # 索引重建失败不影响主流程，仅记录
        print(f"[WARN] 索引自动重建失败: {e}")

    # ── 4. 自动更新 TODO ──
    todo_msg = _update_todo(rnum, taskname, line)

    return (
        f"✅ 完成！报告已保存: {dest_name}\n"
        f"历史已记录: {line}\n"
        f"TODO已更新: {todo_msg}"
    )


# ── 快速自检 ──
if __name__ == "__main__":
    print(f"TEMP_DIR:    {_TEMP_DIR}")
    print(f"REPORTS_DIR: {_REPORTS_DIR}")
    print(f"HISTORY:     {_HISTORY_FILE}")
    print(f"TODO:        {_TODO_FILE}")
    print(f"Next R#:     R{_next_report_number()}")
    print(f"\n--- TODO ---\n{get_todo()[:200]}")
    print(f"\n--- History (5) ---\n{get_history(5)}")
