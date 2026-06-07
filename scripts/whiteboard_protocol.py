#!/usr/bin/env python3
"""
whiteboard_protocol.py — Arena 白板通讯协议实现 🪧

基于 whiteboard_protocol SOP 的 Python 实现。
提供 create_board / read / post / subscribe 等操作，
支持子代理通过共享 Markdown 白板协作。

用法:
  # CLI
  python whiteboard_protocol.py create --task-id demo --title "示例任务"
  python whiteboard_protocol.py read --task-id demo
  python whiteboard_protocol.py post --task-id demo --section state --value "🟡 执行中"
  python whiteboard_protocol.py list

  # API
  from whiteboard_protocol import Whiteboard
  wb = Whiteboard("task_001")
  wb.create_board("标题", "描述", ["architect", "coder"])
  wb.post_state("🟡 执行中")
  data = wb.read()
"""

import os
import re
import time
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Callable, Any, Union

# ── 常量 ──────────────────────────────────────────────────────────────
DEFAULT_BASE = "temp"

# 白板状态枚举
STATE_PENDING = "⏳ 待开始"
STATE_READY = "🟢 待认领"
STATE_RUNNING = "🟡 执行中"
STATE_BLOCKED = "🔴 阻塞中"
STATE_DONE = "✅ 已完成"

ALL_STATES = [STATE_PENDING, STATE_READY, STATE_RUNNING, STATE_BLOCKED, STATE_DONE]


# ═══════════════════════════════════════════════════════════════════════
#  Whiteboard 核心类
# ═══════════════════════════════════════════════════════════════════════

class Whiteboard:
    """白板通讯协议的操作接口"""

    def __init__(self, task_id: str, base_dir: str = DEFAULT_BASE):
        self.task_id = task_id
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / task_id / "WHITEBOARD.md"
        self._subscribers: List[Callable[["Whiteboard"], None]] = []

    # ── 核心操作 ──────────────────────────────────────────────────────

    def create_board(self, title: str, description: str,
                     roles: Optional[List[str]] = None,
                     subsections: Optional[List[str]] = None,
                     overwrite: bool = False) -> str:
        """创建新白板。返回白板文件路径。"""
        if self.path.exists() and not overwrite:
            raise FileExistsError(f"白板已存在: {self.path}（使用 overwrite=True 覆盖）")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = self._render_template(title, description, roles or ["agent"],
                                        subsections or [])
        self.path.write_text(content, encoding="utf-8")
        self._notify()
        return str(self.path)

    def read(self) -> Dict[str, Any]:
        """读取并解析白板内容，返回结构化数据。"""
        if not self.path.exists():
            return {"error": f"白板不存在: {self.path}", "exists": False}
        text = self.path.read_text(encoding="utf-8")
        return self._parse(text)

    def read_raw(self) -> str:
        """读取白板原始 Markdown 内容。"""
        if not self.path.exists():
            return ""
        return self.path.read_text(encoding="utf-8")

    def post(self, section: str, content: str) -> bool:
        """向白板指定区域写入内容（追加或替换）。"""
        if not self.path.exists():
            raise FileNotFoundError(f"白板不存在: {self.path}")
        text = self.path.read_text(encoding="utf-8")
        # 按 section 类型处理
        if section == "state":
            text = self._update_state(text, content)
        elif section == "log":
            text = self._append_log(text, content)
        elif section == "deliverable":
            text = self._update_deliverable(text, content)
        elif section == "block":
            text = self._update_block(text, content)
        elif section == "heartbeat":
            text = self._append_heartbeat(text)
        elif section == "executor":
            text = self._update_executor(text, content)
        elif section in ("arena_decision", "arena_decision"):
            text = self._update_arena_decision(text, content)
        else:
            # 通用: 替换 `## {section}` 下的内容
            text = self._update_section(text, section, content)
        self.path.write_text(text, encoding="utf-8")
        self._notify()
        return True

    def post_state(self, state: str) -> bool:
        """快捷方法：更新状态字段（同时更新到 ## 任务信息 的状态行）。"""
        return self.post("state", state)

    def post_log(self, entry: str) -> bool:
        """快捷方法：追加进度日志条目。"""
        return self.post("log", entry)

    def post_heartbeat(self) -> bool:
        """快捷方法：写入心跳时间戳。"""
        return self.post("heartbeat", "")

    def post_block(self, reason: str, question: str) -> bool:
        """快捷方法：写入阻塞交流内容。"""
        block_content = f"- **卡住原因**: {reason}\n- **给 Arena 的问题**: {question}\n- **Arena 回复**: \n"
        return self.post("block", block_content)

    def post_deliverable(self, content: str) -> bool:
        """快捷方法：写入交付物。"""
        return self.post("deliverable", content)

    def get_state(self) -> str:
        """获取当前任务状态。"""
        data = self.read()
        return data.get("state", STATE_PENDING)

    def get_last_heartbeat(self) -> Optional[str]:
        """获取最后心跳时间。"""
        data = self.read()
        logs = data.get("progress_log", [])
        for entry in reversed(logs):
            if "[心跳]" in entry.get("content", ""):
                return entry.get("time")
        return None

    # ── 订阅机制 ──────────────────────────────────────────────────────

    def subscribe(self, callback: Callable[["Whiteboard"], None]):
        """注册白板变更回调。"""
        self._subscribers.append(callback)

    def _notify(self):
        """通知所有订阅者。"""
        for cb in self._subscribers:
            try:
                cb(self)
            except Exception as e:
                pass  # 静默失败

    # ── 模板渲染 ──────────────────────────────────────────────────────

    def _render_template(self, title: str, description: str,
                         roles: List[str], subsections: List[str]) -> str:
        """渲染 SOP 定义的白板模板。"""
        task_id = self.task_id
        now = datetime.now().strftime("%H:%M")

        # 角色工作区
        roles_section = ""
        for i, role in enumerate(roles):
            roles_section += f"""### 当前执行者：{role}
### 状态：{STATE_READY if i == 0 else STATE_PENDING}
### 最后心跳：{now}
### 进度日志：
| 时间 | 内容 | 类型 |
|------|------|------|
| {now} | 白板创建 | 初始化 |
### 交付物：
*(待填写)*

### 阻塞交流（需要时使用）
> 遇到需要决策的问题时在此描述
- **卡住原因**：
- **给 Arena 的问题**：
- **Arena 回复**：

"""
            if i < len(roles) - 1:
                roles_section += "---\n\n"

        # 子任务分解
        sub_list = "\n".join(f"- [ ] 子任务 {i+1}：{s}"
                            for i, s in enumerate(subsections)) if subsections else "*(待分解)*"

        template = f"""# 🪧 对抗式解题法白板

## 任务信息
- 任务ID: {task_id}
- 状态: {STATE_PENDING}
- 标题: {title}
- 创建时间: {datetime.now().isoformat()}

## 1️⃣ 任务要求（Arena 写入）
> 用户需求原文：{description}
>
- 核心目标：{title}
- 交付物：{', '.join(roles)} 协作完成
- 约束：无
- 参考素材：无

### 子任务分解（Arena 或解题者拆解）
{sub_list}

## 2️⃣ 解题者工作区
{roles_section}
## 3️⃣ 判别者工作区
### 当前评审：(待指派)
### 状态：⏳ 待评审
### 发现问题：
| 等级 | 分类 | 标题 | 说明 |
|------|------|------|------|
| *(待填写)* | | | |
### 结论：*(待评审)*

## 4️⃣ Arena 决策区
### 收敛评估：
- 最新轮次总分：0（阈值 —，需连续 — 轮 < 阈值）
- 当前 P0：0 | P1：0 | P2：0 | P3：0
- 收敛状态：⏳ 未开始
- 未收敛原因：等待首次执行
### 下一阶段指令：
- 等待解题者认领任务
"""
        return template

    # ── 解析器 ────────────────────────────────────────────────────────

    def _parse(self, text: str) -> Dict[str, Any]:
        """解析 Markdown 白板为结构化 Dict。"""
        result = {
            "task_id": self.task_id,
            "path": str(self.path),
            "exists": True,
            "state": STATE_PENDING,
            "title": "",
            "description": "",
            "executors": [],
            "progress_log": [],
            "deliverables": {},
            "block_issues": [],
            "review": {},
            "arena_decision": {},
        }

        # 状态提取
        m = re.search(r'-\s*\*?状态\*?\s*:\s*(.+)', text)
        if m:
            state = m.group(1).strip()
            result["state"] = state if state in ALL_STATES else STATE_PENDING

        # 标题提取
        m = re.search(r'-\s*\*?标题\*?\s*:\s*(.+)', text)
        if m:
            result["title"] = m.group(1).strip()

        # 提取任务要求
        m = re.search(r'>\s*用户需求原文[：:]\s*(.+)', text)
        if m:
            result["description"] = m.group(1).strip()

        # 提取执行者
        for m in re.finditer(r'###\s*当前执行者[：:]\s*(.+)', text):
            result["executors"].append(m.group(1).strip())

        # 提取进度日志
        in_log = False
        for line in text.split('\n'):
            if '| 时间 | 内容 | 类型 |' in line:
                in_log = True
                continue
            if in_log and line.startswith('|') and '|' in line[1:]:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 4:
                    result["progress_log"].append({
                        "time": parts[1],
                        "content": parts[2],
                        "type": parts[3],
                    })
            elif in_log and not line.startswith('|'):
                in_log = False

        # 提取交付物
        for m in re.finditer(r'###\s*交付物[：:]\s*\n(.*?)(?=###|\Z)', text, re.DOTALL):
            d_content = m.group(1).strip()
            if d_content and d_content != "*(待填写)*":
                result["deliverables"]["latest"] = d_content

        # 提取阻塞交流
        for m in re.finditer(r'\*\*卡住原因\*\*[：:]\s*(.*)', text):
            result["block_issues"].append({"reason": m.group(1).strip()})
        for i, m in enumerate(re.finditer(r'\*\*给 Arena 的问题\*\*[：:]\s*(.*)', text)):
            if i < len(result["block_issues"]):
                result["block_issues"][i]["question"] = m.group(1).strip()
        for i, m in enumerate(re.finditer(r'\*\*Arena 回复\*\*[：:]\s*(.*)', text)):
            if i < len(result["block_issues"]):
                result["block_issues"][i]["reply"] = m.group(1).strip()

        # 提取评审信息
        m = re.search(r'###\s*结论[：:]\s*(.+)', text)
        if m:
            result["review"]["conclusion"] = m.group(1).strip()

        # 提取收敛评估
        m = re.search(r'收敛状态[：:]\s*(.+)', text)
        if m:
            result["arena_decision"]["convergence"] = m.group(1).strip()

        return result

    # ── 更新方法 ──────────────────────────────────────────────────────

    def _update_state(self, text: str, new_state: str) -> str:
        """更新状态字段。"""
        return re.sub(
            r'(-\s*\*?状态\*?\s*:\s*).+',
            rf'\1{new_state}',
            text
        )

    def _append_log(self, text: str, entry: str) -> str:
        """在进度日志表后追加一行。"""
        now = datetime.now().strftime("%H:%M")
        # 找到第一个进度日志表的结尾（空行后的非 | 行）
        lines = text.split('\n')
        last_log_idx = -1
        for i, line in enumerate(lines):
            if line.startswith('|') and '时间' in line and '内容' in line:
                last_log_idx = i + 1  # skip header separator
            if last_log_idx > 0 and i > last_log_idx:
                if line.startswith('|'):
                    last_log_idx = i
                else:
                    break
        if last_log_idx > 0:
            lines.insert(last_log_idx + 1, f"| {now} | {entry} | 进度 |")
        else:
            # 没有找到日志表，追加一个
            lines.append(f"\n| 时间 | 内容 | 类型 |")
            lines.append(f"|------|------|------|")
            lines.append(f"| {now} | {entry} | 进度 |")
        return '\n'.join(lines)

    def _append_heartbeat(self, text: str) -> str:
        """追加心跳行。"""
        now = datetime.now().strftime("%H:%M")
        return self._append_log(text, f"[心跳]")

    def _update_deliverable(self, text: str, content: str) -> str:
        """更新交付物区域。"""
        pattern = r'(###\s*交付物[：:]\s*\n).*?(?=\n###|\Z)'
        replacement = rf'\1{content}\n'
        return re.sub(pattern, replacement, text, count=1, flags=re.DOTALL)

    def _update_block(self, text: str, block_content: str) -> str:
        """更新阻塞交流区域。"""
        pattern = r'(###\s*阻塞交流[^#]*?)(?=\n###|\Z)'
        replacement = f"### 阻塞交流（需要时使用）\n> 遇到需要决策的问题时在此描述\n{block_content}\n"
        return re.sub(pattern, replacement, text, count=1, flags=re.DOTALL)

    def _update_executor(self, text: str, executor: str) -> str:
        """更新当前执行者名称。"""
        return re.sub(
            r'###\s*当前执行者[：:]\s*.+',
            f'### 当前执行者：{executor}',
            text,
            count=1
        )

    def _update_arena_decision(self, text: str, decision: str) -> str:
        """更新 Arena 决策区内容。"""
        pattern = r'(##\s*4️⃣\s*Arena 决策区.*?)(?=\n##|\Z)'
        replacement = f"## 4️⃣ Arena 决策区\n{decision}\n"
        return re.sub(pattern, replacement, text, count=1, flags=re.DOTALL)

    def _update_section(self, text: str, section_name: str, content: str) -> str:
        """通用更新：替换或追加到指定 section 下方。"""
        pattern = rf'(##\s*{re.escape(section_name)}.*?)(?=\n##|\Z)'
        replacement = f"## {section_name}\n{content}\n"
        if re.search(pattern, text, flags=re.DOTALL):
            return re.sub(pattern, replacement, text, count=1, flags=re.DOTALL)
        # section 不存在则追加
        return text + f"\n## {section_name}\n{content}\n"


# ═══════════════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════════════

def list_boards(base_dir: str = DEFAULT_BASE) -> List[Dict]:
    """列出所有白板。"""
    boards = []
    base = Path(base_dir)
    if not base.exists():
        return boards
    for task_dir in sorted(base.iterdir()):
        wb_path = task_dir / "WHITEBOARD.md"
        if wb_path.exists():
            wb = Whiteboard(task_dir.name, base_dir)
            data = wb.read()
            boards.append({
                "task_id": task_dir.name,
                "path": str(wb_path),
                "state": data.get("state", STATE_PENDING),
                "title": data.get("title", ""),
                "executors": data.get("executors", []),
            })
    return boards


# ═══════════════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════════════

def _do_list(args):
    boards = list_boards(args.base_dir)
    if not boards:
        print("📭 无白板")
        return
    print(f"\n📋 白板列表 ({len(boards)}):")
    print(f"{'='*60}")
    for b in boards:
        state = b["state"]
        title = b["title"][:40] if b["title"] else "(无标题)"
        execs = ", ".join(b["executors"]) if b["executors"] else "(无执行者)"
        print(f"  {state} {b['task_id']:20s} | {title:40s} | {execs}")


def _do_create(args):
    wb = Whiteboard(args.task_id, args.base_dir)
    wb.create_board(
        title=args.title,
        description=args.description,
        roles=args.roles.split(",") if args.roles else None,
        subsections=args.subsections.split("|") if args.subsections else None,
        overwrite=args.overwrite,
    )
    print(f"✅ 白板已创建: {wb.path}")


def _do_read(args):
    wb = Whiteboard(args.task_id, args.base_dir)
    if args.raw:
        print(wb.read_raw())
    else:
        data = wb.read()
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _do_post(args):
    wb = Whiteboard(args.task_id, args.base_dir)
    wb.post(args.section, args.value)
    print(f"✅ 已写入 section={args.section}")


def _do_watch(args):
    """简单的白板监控 — 轮询状态变化。"""
    import time as _time
    wb = Whiteboard(args.task_id, args.base_dir)
    last_state = wb.get_state()
    print(f"🔍 监控白板: {wb.path}")
    print(f"   初始状态: {last_state}")
    print(f"   每 {args.interval}s 检查一次")
    try:
        while True:
            _time.sleep(args.interval)
            current = wb.read()
            state = current.get("state", "?")
            logs = current.get("progress_log", [])
            last_log = logs[-1]["content"] if logs else ""
            now = datetime.now().strftime("%H:%M:%S")
            if state != last_state:
                print(f"[{now}] 🔄 状态变更: {last_state} → {state}")
                last_state = state
            elif last_log:
                print(f"[{now}] 📝 {last_log[:60]}")
    except KeyboardInterrupt:
        print("\n👋 监控结束")


def main():
    parser = argparse.ArgumentParser(description="🪧 白板通讯协议工具")
    parser.add_argument("--base-dir", default=DEFAULT_BASE, help="白板根目录")

    sub = parser.add_subparsers(dest="action", required=True)

    # create
    p = sub.add_parser("create", help="创建白板")
    p.add_argument("--task-id", required=True)
    p.add_argument("--title", default="任务")
    p.add_argument("--description", default="")
    p.add_argument("--roles", default="agent")
    p.add_argument("--subsections", default="")
    p.add_argument("--overwrite", action="store_true")

    # read
    p = sub.add_parser("read", help="读取白板")
    p.add_argument("--task-id", required=True)
    p.add_argument("--raw", action="store_true", help="输出原始 Markdown")

    # post
    p = sub.add_parser("post", help="写入白板")
    p.add_argument("--task-id", required=True)
    p.add_argument("--section", required=True,
                   choices=["state", "log", "heartbeat", "deliverable",
                            "block", "executor", "arena_decision"])
    p.add_argument("--value", default="")

    # list
    p = sub.add_parser("list", help="列出所有白板")

    # watch
    p = sub.add_parser("watch", help="监控白板状态变化")
    p.add_argument("--task-id", required=True)
    p.add_argument("--interval", type=int, default=5, help="轮询间隔(秒)")

    args = parser.parse_args()
    dispatch = {
        "list": _do_list,
        "create": _do_create,
        "read": _do_read,
        "post": _do_post,
        "watch": _do_watch,
    }
    handler = dispatch.get(args.action)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
