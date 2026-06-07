#!/usr/bin/env python3
"""todo_goal_sync.py — TODO ↔ goal_state.json 双向同步工具

用法:
  python assets/todo_goal_sync.py                      # 双向同步 (TODO→goal + goal→TODO)
  python assets/todo_goal_sync.py --todo-to-goal       # 仅 TODO→goal_state 方向
  python assets/todo_goal_sync.py --goal-to-todo       # 仅 goal_state→TODO 方向
  python assets/todo_goal_sync.py --status             # 显示当前同步状态

设计:
  - TODO→Goal: 解析 TODO.txt 中 [x] 完成项 → 更新 goal_state.json 的 objective 字段
  - Goal→TODO: 如果 goal_state.json 的 status='completed'/'budget_exhausted',
    则将目标描述匹配的 TODO 项标记为 [x]
"""

import os, sys, json, re

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODO_PATH = os.path.join(CODE_ROOT, 'temp', 'TODO.txt')
GOAL_STATE_PATH = os.path.join(CODE_ROOT, 'temp', 'goal_state.json')


def parse_todo_items(todo_path=TODO_PATH):
    """解析 TODO.txt，返回 { 'done': [...], 'pending': [...], 'all': [...] }"""
    if not os.path.isfile(todo_path):
        print(f"[sync] TODO 文件不存在: {todo_path}")
        return {'done': [], 'pending': [], 'all': []}

    done, pending, all_items = [], [], []
    with open(todo_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip()
            m = re.match(r'^\[([ x])\]\s+(.+)$', line)
            if m:
                checked = m.group(1) == 'x'
                content = m.group(2).strip()
                item = {'checked': checked, 'content': content, 'raw': line}
                all_items.append(item)
                if checked:
                    done.append(item)
                else:
                    pending.append(item)
    return {'done': done, 'pending': pending, 'all': all_items}


def load_goal_state():
    """加载 goal_state.json，不存在返回 None"""
    if not os.path.isfile(GOAL_STATE_PATH):
        return None
    with open(GOAL_STATE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_goal_state(state):
    """保存 goal_state.json"""
    with open(GOAL_STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def todo_to_goal():
    """方向1: TODO → goal_state — 将 TODO 完成进度写入 goal_state.objective"""
    todo = parse_todo_items()
    if not todo['all']:
        print("[sync] TODO 为空，跳过 TODO→Goal 同步")
        return False

    state = load_goal_state()
    if state is None:
        print("[sync] goal_state.json 不存在，创建新状态文件")
        state = {
            "objective": "",
            "budget_seconds": 0,
            "start_time": 0,
            "turns_used": 0,
            "max_turns": 0,
            "status": "running",
            "done_prompt": ""
        }

    total = len(todo['all'])
    done_count = len(todo['done'])
    pending_count = len(todo['pending'])

    # 构建 goal_state 的 objective 更新
    summary_parts = [f"[TODO 同步] 进度: {done_count}/{total} 项完成"]
    if done_count > 0:
        summary_parts.append("已完成:")
        for item in todo['done'][:10]:  # 最多10个已完成项
            summary_parts.append(f"  ✅ {item['content'][:60]}")
    if pending_count > 0:
        summary_parts.append("待办:")
        for item in todo['pending'][:10]:
            summary_parts.append(f"  ⬜ {item['content'][:60]}")

    new_objective = "\n".join(summary_parts)

    old_obj = state.get('objective', '')
    if old_obj:
        # 保留原目标，追加同步信息
        state['objective'] = f"{old_obj}\n\n---\n{new_objective}"
    else:
        state['objective'] = new_objective

    save_goal_state(state)
    print(f"[sync] ✅ TODO→Goal 同步完成 | 进度 {done_count}/{total} | 已更新 goal_state.json")
    return True


def goal_to_todo():
    """方向2: goal_state → TODO — 当 goal 完成时更新 TODO"""
    state = load_goal_state()
    if state is None:
        print("[sync] goal_state.json 不存在，跳过 Goal→TODO 同步")
        return False

    status = state.get('status', '')
    objective = state.get('objective', '')

    # 只有 goal 完成/耗尽/停止时才更新 TODO
    if status not in ('completed', 'budget_exhausted', 'stopped', 'done'):
        print(f"[sync] goal 状态为 '{status}'，尚未完成，跳过 Goal→TODO 同步")
        return False

    print(f"[sync] goal 已完成 (status={status})，检查 TODO 同步...")

    todo = parse_todo_items()
    if not todo['pending']:
        print("[sync] TODO 已全部完成，无需更新")
        return True

    # 尝试从 objective 中提取目标任务描述，与 TODO 待办匹配
    # 简化策略：如果 goal_state 的 objective 包含某个 TODO 项的关键词，标记为完成
    updated = 0
    with open(TODO_PATH, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        m = re.match(r'^\[ \]\s+(.+)$', line)
        if m:
            content = m.group(1)
            # 检查 objective 是否提到这个 TODO 的关键词
            # 简单匹配：取 TODO 标题的前 20 个字
            short_title = content[:40].strip()
            if short_title in objective:
                new_lines.append(f"[x] {content}\n")
                updated += 1
                print(f"  ✅ 标记完成: {content[:50]}...")
                continue
        new_lines.append(line)

    if updated > 0:
        with open(TODO_PATH, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"[sync] ✅ Goal→TODO 同步完成 | 更新了 {updated} 项 TODO")
    else:
        print("[sync] 未找到匹配的 TODO 项，尝试将当前 TODO 进度写入 goal_state...")
        # 回退：将 TODO 状态写入 goal_state
        todo_to_goal()

    return True


def show_status():
    """显示当前同步状态"""
    print("=== TODO ↔ goal_state 同步状态 ===\n")

    todo = parse_todo_items()
    total = len(todo['all'])
    done_count = len(todo['done'])
    pending_count = len(todo['pending'])
    print(f"📋 TODO.txt: {total} 项 ({done_count} 完成, {pending_count} 待办)")

    state = load_goal_state()
    if state:
        status = state.get('status', 'unknown')
        obj_preview = state.get('objective', '')[:80]
        print(f"🎯 goal_state.json: status={status}")
        print(f"   目标预览: {obj_preview}...")
    else:
        print("🎯 goal_state.json: (不存在)")

    print()
    if total > 0:
        print(f"   同步状态: TODO→Goal {'就绪' if True else '跳过'}")
        print(f"   同步状态: Goal→TODO {'就绪' if state else '跳过'}")
        if state and state.get('status') in ('completed', 'budget_exhausted'):
            print(f"   建议: Goal 已完成，运行 --goal-to-todo 同步到 TODO")
    else:
        print("   暂无同步项")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == '--todo-to-goal':
            todo_to_goal()
        elif arg == '--goal-to-todo':
            goal_to_todo()
        elif arg == '--status':
            show_status()
        else:
            print(f"用法: {sys.argv[0]} [--todo-to-goal | --goal-to-todo | --status]")
    else:
        # 默认：双向同步（先 TODO→Goal，再 Goal→TODO）
        todo_to_goal()
        goal_to_todo()
        print("[sync] 双向同步完成")
