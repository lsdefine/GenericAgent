"""
__main__.py — skill_learn_from_cases CLI 入口

用法:
    python -m tools.skill_learn_from_cases "docker_compose_production"
    python -m tools.skill_learn_from_cases --list
    python -m tools.skill_learn_from_cases "docker_compose_production" --dry-run
"""

import sys, argparse
from pathlib import Path

# 确保 GA 根目录在 sys.path
GA_ROOT = Path(__file__).resolve().parents[2]
if str(GA_ROOT) not in sys.path:
    sys.path.insert(0, str(GA_ROOT))

from tools.skill_learn_from_cases.engine import learn_skill
from tools.skill_learn_from_cases.dir_manager import get_all_skills


def main():
    parser = argparse.ArgumentParser(
        description="skill_learn_from_cases — 案例驱动技能学习工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m tools.skill_learn_from_cases "docker_compose_production"
  python -m tools.skill_learn_from_cases --list
  python -m tools.skill_learn_from_cases --help
        """
    )
    parser.add_argument(
        "skill_name",
        nargs="?",
        help="要学习的技能名称，如 docker_compose_production"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出已学习的技能"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅展示将要执行的操作，不实际运行"
    )

    args = parser.parse_args()

    if args.list:
        skills = get_all_skills()
        if skills:
            print("已学习的技能:")
            for s in skills:
                print(f"    [dir] {s}")
        else:
            print("尚未学习任何技能")
        return

    if not args.skill_name:
        parser.print_help()
        return

    skill_name = args.skill_name.strip()
    if args.dry_run:
        print(f"[DRY RUN] 将学习技能: {skill_name}")
        print(f"          流程: Phase 0→1→2→3→4→5")
        print(f"          将创建: skills_learning/{skill_name}/revN/")
        return

    learn_skill(skill_name)


if __name__ == "__main__":
    main()
