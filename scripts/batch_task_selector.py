#!/usr/bin/env python3
"""批量任务选择器 — 根据待办数量智能决定本次取几条 (R190)

用法:
  python3 scripts/batch_task_selector.py
    → 输出: PENDING=N  BATCH=M  TASK=条目  TASK=条目 ...

逻辑:
  - TODO >= 6 条 → 取 3 条
  - TODO >= 3 条 → 取 2 条
  - TODO <  3 条 → 取 1 条 (原SOP行为)

设计原则:
  - 不修改 SOP, 作为辅助工具供自主行动模块调用
  - 保留 SOP "取一条" 作为最小行为, 仅当待办积压时自动扩容
"""

import re, sys, os

GA_HOME = os.environ.get('GA_HOME', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TODO_PATH = os.path.join(GA_HOME, 'temp', 'TODO.txt')


def get_pending_tasks() -> list:
    """读取 TODO 文件, 返回未完成项 (不含 [x] 前缀)"""
    try:
        with open(TODO_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []

    pending = []
    for line in lines:
        line = line.rstrip()
        if re.match(r'^\[ \]', line):
            pending.append(line)
    return pending


def suggest_batch_count(pending_count: int) -> int:
    """根据待办数建议本次取几条"""
    if pending_count >= 6:
        return 3
    elif pending_count >= 3:
        return 2
    else:
        return 1


if __name__ == '__main__':
    pending = get_pending_tasks()
    count = len(pending)
    batch = suggest_batch_count(count)

    print(f'PENDING={count}')
    print(f'BATCH={batch}')
    for task in pending[:batch]:
        print(f'TASK={task}')
