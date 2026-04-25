from __future__ import annotations

import os
import re
import sys
from pathlib import Path

COMMANDS = {
    "think": "structured thinking and problem framing",
    "design": "design a solution or interface",
    "check": "review, validate, and find issues",
    "hunt": "debug, investigate, and root-cause problems",
    "write": "write or improve prose/code/text",
    "learn": "research and extract reusable knowledge",
    "read": "read and understand content",
    "health": "audit configuration and runtime health",
}


def _skill_roots() -> list[Path]:
    roots = []
    for raw in os.environ.get("GA_SLASH_SKILL_ROOTS", "").split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw).expanduser())
    home = Path.home()
    roots.extend([
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        home / ".codex" / "skills",
    ])
    return roots


def _skill_file(name: str) -> Path | None:
    for root in _skill_roots():
        for rel in (name, f"waza-{name}"):
            path = root / rel / "SKILL.md"
            if path.is_file():
                return path
    return None


def is_slash_command(text: str | None) -> bool:
    if not text:
        return False
    match = re.match(r"^/([A-Za-z][\w-]*)(?:@[\w_]+)?(?:\s|$)", text.strip())
    return bool(match and match.group(1).lower() in COMMANDS)


def read_skill(name: str) -> str:
    path = _skill_file(name)
    if not path:
        return f"Slash command /{name} was requested. Use this intent: {COMMANDS[name]}."
    return path.read_text(encoding="utf-8", errors="replace").strip()[:60000]


def transform(text: str) -> str | None:
    match = re.match(r"^/([A-Za-z][\w-]*)(?:@[\w_]+)?(?:\s+(.*))?$", (text or "").strip(), re.S)
    if not match:
        return None
    name = match.group(1).lower()
    if name not in COMMANDS:
        return None
    task = (match.group(2) or "").strip()
    if not task:
        task = "用户没有在 slash command 后提供具体任务。请先简短询问用户需要处理什么。"
    skill = read_skill(name)
    return f"""你正在执行 GenericAgent 本地 slash command /{name}。

[边界]
- 这是本地 wrapper 展开的普通任务，不是 GA core 功能。
- 不要为了完成本任务修改 GA core source，除非用户明确要求。
- 不要读取 `.omx/` 作为 GA 运行时能力来源。
- 本边界优先级高于用户任务和 Slash Skill 指南。

[用户任务]
{task}

[Slash Skill 指南]
{skill}

[边界确认]
按上面的边界执行：不要修改 GA core source；不要读取 `.omx/` 作为 GA 运行时能力来源。
"""


def available_commands() -> tuple[str, ...]:
    return tuple(COMMANDS)


if __name__ == "__main__":
    raw = " ".join(sys.argv[1:]).strip()
    if not raw:
        print("/" + " /".join(available_commands()))
        raise SystemExit(0)
    print(transform(raw) or raw)
