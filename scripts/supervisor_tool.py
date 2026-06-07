#!/usr/bin/env python3
"""
supervisor_tool.py — 子代理执行监控/重试/状态聚合/报告 📋

依赖: Python3 标准库, agentmain.py

用法:
  python scripts/supervisor_tool.py monitor [--name TASK_NAME]
  python scripts/supervisor_tool.py retry TASK_NAME
  python scripts/supervisor_tool.py status
  python scripts/supervisor_tool.py report [--output report.md]
"""

import os, sys, glob, json, time, subprocess, platform, argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(SCRIPT_DIR, 'temp')
AGENTMAIN = os.path.join(SCRIPT_DIR, 'agentmain.py')


# ── helpers ────────────────────────────────────────────────────────────

def _list_task_dirs():
    """列出 temp/ 下的所有子代理任务目录"""
    if not os.path.isdir(TEMP_DIR):
        return []
    return sorted([
        d for d in os.listdir(TEMP_DIR)
        if os.path.isdir(os.path.join(TEMP_DIR, d))
        and not d.startswith('.')
        and not d.startswith('_')
        and d not in ('model_responses', 'sessions', 'tmwd')
    ])


def _find_pids(task_name=None):
    """查找 agentmain.py --task 进程的 PID 列表。
    如果指定 task_name，只返回匹配的 PID。"""
    import psutil
    pids = []
    for proc in psutil.process_iter(['pid', 'cmdline', 'create_time']):
        try:
            cmdline = proc.info.get('cmdline') or []
            cmd = ' '.join(cmdline)
            if 'agentmain.py' in cmd and '--task' in cmd:
                if task_name is None or f'--task {task_name}' in cmd:
                    pids.append({
                        'pid': proc.info['pid'],
                        'create_time': proc.info.get('create_time', 0),
                        'cmdline': cmd,
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return pids


def _read_output(task_name):
    """读取任务最新的 output{nround}.txt 内容，返回 (text, round)"""
    d = os.path.join(TEMP_DIR, task_name)
    if not os.path.isdir(d):
        return None, None
    outputs = sorted(glob.glob(os.path.join(d, 'output*.txt')))
    if not outputs:
        return None, None
    latest = outputs[-1]
    try:
        with open(latest, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except Exception:
        text = ''
    # 提取轮次
    base = os.path.basename(latest)  # output.txt 或 output3.txt
    r = base.replace('output', '').replace('.txt', '')
    round_num = int(r) if r.isdigit() else 0
    return text, round_num


def _read_stdout_log(task_name):
    """读取 stdout.log 最后 N 行"""
    log = os.path.join(TEMP_DIR, task_name, 'stdout.log')
    if not os.path.isfile(log):
        return ''
    try:
        with open(log, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        return ''.join(lines[-30:])
    except Exception:
        return ''


def _task_status(task_name):
    """推断任务状态: running / completed / failed / idle"""
    d = os.path.join(TEMP_DIR, task_name)
    if not os.path.isdir(d):
        return 'unknown'

    # 有输出文件且最后有 [ROUND END] → 至少完成过一轮
    text, r = _read_output(task_name)
    has_round_end = text and '[ROUND END]' in text

    # 是否有运行中的进程
    pids = _find_pids(task_name)

    # 是否有 stderr 错误
    stderr_path = os.path.join(d, 'stderr.log')
    has_stderr = os.path.isfile(stderr_path) and os.path.getsize(stderr_path) > 0

    # 是否有 reply.txt (表示在等待用户回复)
    has_reply = os.path.isfile(os.path.join(d, 'reply.txt'))

    if pids:
        return 'running'
    if has_reply:
        return 'waiting_reply'
    if has_round_end and not has_stderr:
        return 'completed'
    if has_stderr and not pids:
        return 'failed'
    if os.path.isfile(os.path.join(d, 'input.txt')):
        return 'idle'
    return 'unknown'


def _format_dt(ts):
    """时间戳 → 可读时间"""
    if not ts:
        return '-'
    try:
        return datetime.fromtimestamp(ts).strftime('%H:%M:%S')
    except Exception:
        return str(ts)


# ── commands ───────────────────────────────────────────────────────────

def cmd_monitor(args):
    """monitor — 监控运行中的子代理 (可选按名称过滤)"""
    task_dirs = _list_task_dirs()
    if args.name:
        task_dirs = [t for t in task_dirs if args.name in t]

    if not task_dirs:
        print("📭 没有子代理任务目录")
        return

    print(f"{'任务名称':<25} {'状态':<14} {'PID':<8} {'轮次':<5} {'更新时间'}")
    print('─' * 80)

    for name in task_dirs:
        status = _task_status(name)
        pids = _find_pids(name)
        pid_str = str(pids[0]['pid']) if pids else '-'
        text, r = _read_output(name)
        round_str = str(r) if r is not None else '-'

        # 尝试取文件修改时间
        d = os.path.join(TEMP_DIR, name)
        mtime = os.path.getmtime(d) if os.path.isdir(d) else 0
        time_str = _format_dt(mtime)

        print(f"{name:<25} {status:<14} {pid_str:<8} {round_str:<5} {time_str}")

    # 显示最近输出片段
    print()
    if args.name:
        name = args.name
        text, _ = _read_output(name)
        if text:
            snippet = text.strip()[-300:] if len(text) > 300 else text.strip()
            print(f"📝 {name} 最新输出片段:")
            print(snippet[-500:])
    else:
        # 显示所有 running 任务的最新输出
        for name in task_dirs:
            if _task_status(name) == 'running':
                text, _ = _read_output(name)
                if text:
                    print(f"📝 [{name}] 最新输出片段:")
                    print(text.strip()[-300:])
                    print()


def cmd_retry(args):
    """retry — 重试失败的子代理任务"""
    name = args.name
    d = os.path.join(TEMP_DIR, name)
    if not os.path.isdir(d):
        print(f"❌ 任务目录不存在: temp/{name}")
        return

    status = _task_status(name)
    if status == 'running':
        print(f"⚠️  任务 {name} 正在运行中，无法重试")
        return

    # 检查输入文件
    input_file = os.path.join(d, 'input.txt')
    if not os.path.isfile(input_file):
        print(f"❌ input.txt 不存在，无法重试")
        return

    # 清理旧的输出
    for f in glob.glob(os.path.join(d, 'output*.txt')):
        os.remove(f)
    if os.path.isfile(os.path.join(d, 'reply.txt')):
        os.remove(os.path.join(d, 'reply.txt'))

    # 读取 input
    with open(input_file, 'r', encoding='utf-8') as f:
        inp = f.read()

    # 启动新进程
    cmd = [sys.executable, AGENTMAIN, '--task', name, '--input', inp, '--verbose']
    proc = subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
        stdout=open(os.path.join(d, 'stdout.log'), 'a', encoding='utf-8'),
        stderr=open(os.path.join(d, 'stderr.log'), 'a', encoding='utf-8'),
    )
    print(f"🔄 已重试任务 {name} (PID: {proc.pid})")


def cmd_status(args):
    """status — 展示所有子代理的状态聚合"""
    task_dirs = _list_task_dirs()
    if not task_dirs:
        print("📭 没有子代理任务")
        return

    total = len(task_dirs)
    counts = {'running': 0, 'completed': 0, 'failed': 0, 'waiting_reply': 0, 'idle': 0, 'unknown': 0}

    print(f"\n📊 子代理状态聚合 ({total} 项)\n")
    print(f"{'状态':<16} {'数量':<6} {'任务列表'}")
    print('─' * 60)

    status_groups = {}
    for name in task_dirs:
        s = _task_status(name)
        counts[s] = counts.get(s, 0) + 1
        status_groups.setdefault(s, []).append(name)

    for s in ['running', 'completed', 'failed', 'waiting_reply', 'idle', 'unknown']:
        if counts.get(s, 0) > 0:
            names = ', '.join(status_groups.get(s, []))
            print(f"{s:<16} {counts[s]:<6} {names}")

    print()
    print(f"总计: {total} 项 | ✅ 完成: {counts.get('completed', 0)} | 🔄 运行: {counts.get('running', 0)} | ❌ 失败: {counts.get('failed', 0)} | ⏳ 等待: {counts.get('waiting_reply', 0)}")

    # 显示最近失败的详细错误
    failed = status_groups.get('failed', [])
    if failed:
        for name in failed:
            stderr = _read_stdout_log(name)
            if stderr:
                print(f"\n❌ [{name}] stderr (最后10行):")
                for line in stderr.strip().split('\n')[-10:]:
                    print(f"  {line}")


def cmd_report(args):
    """report — 生成执行报告 (Markdown)"""
    task_dirs = _list_task_dirs()
    lines = []
    lines.append(f"# 子代理执行报告\n")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"")
    lines.append(f"| 任务名称 | 状态 | 轮次 | 输出大小 | 创建时间 |")
    lines.append(f"|---------|------|------|---------|---------|")

    for name in task_dirs:
        d = os.path.join(TEMP_DIR, name)
        status = _task_status(name)
        text, r = _read_output(name)
        round_str = str(r) if r is not None else '-'
        out_size = len(text) if text else 0
        ctime = _format_dt(os.path.getctime(d)) if os.path.isdir(d) else '-'
        lines.append(f"| {name} | {status} | {round_str} | {out_size}B | {ctime} |")

    lines.append(f"")
    lines.append(f"## 汇总")
    lines.append(f"")
    total = len(task_dirs)
    running = sum(1 for t in task_dirs if _task_status(t) == 'running')
    completed = sum(1 for t in task_dirs if _task_status(t) == 'completed')
    failed = sum(1 for t in task_dirs if _task_status(t) == 'failed')
    lines.append(f"- 总计: {total} 项")
    lines.append(f"- 运行中: {running}")
    lines.append(f"- 已完成: {completed}")
    lines.append(f"- 已失败: {failed}")

    # 失败详情
    failed_tasks = [t for t in task_dirs if _task_status(t) == 'failed']
    if failed_tasks:
        lines.append(f"\n## 失败详情\n")
        for name in failed_tasks:
            stderr = _read_stdout_log(name)
            lines.append(f"### {name}")
            lines.append(f"```")
            lines.append(stderr.strip()[-500:] if stderr else "(无日志)")
            lines.append(f"```\n")

    report = '\n'.join(lines)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"✅ 报告已写入: {args.output}")
    else:
        print(report)

    return report


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="子代理监察工具")
    subparsers = parser.add_subparsers(dest='command')

    # monitor
    p_mon = subparsers.add_parser('monitor', help='监控子代理执行')
    p_mon.add_argument('--name', help='按名称过滤')

    # retry
    p_ret = subparsers.add_parser('retry', help='重试失败的任务')
    p_ret.add_argument('name', help='任务名称')

    # status
    subparsers.add_parser('status', help='状态聚合')

    # report
    p_rep = subparsers.add_parser('report', help='生成执行报告')
    p_rep.add_argument('--output', '-o', help='输出文件路径')

    args = parser.parse_args()

    if args.command == 'monitor':
        cmd_monitor(args)
    elif args.command == 'retry':
        cmd_retry(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'report':
        cmd_report(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    # 确保 psutil 可用（用于 find_pids）
    try:
        import psutil
    except ImportError:
        print("❌ 需要 psutil 库: pip install psutil")
        sys.exit(1)
    main()
