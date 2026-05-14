"""
__main__.py — skill_learn_from_cases CLI 入口

用法:
    python -m tools.skill_learn_from_cases "docker_compose_production"
    python -m tools.skill_learn_from_cases --list
    python -m tools.skill_learn_from_cases "docker_compose_production" --dry-run
"""

import sys, argparse, json
from pathlib import Path

# 确保 GA 根目录在 sys.path
GA_ROOT = Path(__file__).resolve().parents[2]
if str(GA_ROOT) not in sys.path:
    sys.path.insert(0, str(GA_ROOT))

from tools.skill_learn_from_cases.engine import learn_skill
from tools.skill_learn_from_cases.dir_manager import get_all_skills
from tools.skill_learn_from_cases.name_converter import convert_name


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
    parser.add_argument(
        "--show", "-s",
        type=str,
        help="查看指定技能的最新学习详情（支持中文名）"
    )
    parser.add_argument(
        "--version", "-V",
        action="store_true",
        help="显示工具版本"
    )
    parser.add_argument(
        "--delete",
        type=str,
        help="删除指定技能的所有学习记录"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制刷新搜索案例（跳过继承）"
    )

    args = parser.parse_args()

    if args.list:
        skills = get_all_skills()
        if skills:
            lines_out = []
            for s in sorted(skills):
                stats = ""
                rev_dir = GA_ROOT / "skills_learning" / s
                if rev_dir.exists():
                    revs = sorted([d.name for d in rev_dir.iterdir() if d.name.startswith("rev")], 
                                  key=lambda x: int(x.replace("rev","")))
                    if revs:
                        latest_rev = revs[-1]
                        stats += f"v{latest_rev.replace('rev','')}"
                        meta_file = rev_dir / latest_rev / "meta.json"
                        if meta_file.exists():
                            try:
                                m = json.loads(meta_file.read_text(encoding="utf-8"))
                                score = m.get("score", "?")
                                stats += f"  {score:>3}/100"
                            except: pass
                        patterns_dir = rev_dir / latest_rev / "patterns"
                        if patterns_dir.exists():
                            pf = patterns_dir / "knowledge_patterns.json"
                            if pf.exists():
                                try:
                                    pats = json.loads(pf.read_text(encoding="utf-8"))
                                    stats += f"  {len(pats)}模式"
                                except: pass
                lines_out.append((s, stats))
            
            # 动态计算列宽（支持中文）
            name_width = max(len(s.encode('utf-8')) for s, _ in lines_out)
            # 显示用宽度（中文占2字符宽度的近似）
            display_width = max(20, len(max((s for s,_ in lines_out), key=len)) + 2)
            
            print("已学习的技能:")
            header = f"  {'技能名':<{display_width}}  版本  评分   模式数  原始名"
            print(header)
            print(f"  {'─'*display_width}  ─────────────────────────────────")
            for s, stats in lines_out:
                dname = ""
                rev_dir = GA_ROOT / "skills_learning" / s
                if rev_dir.exists():
                    revs = sorted([d.name for d in rev_dir.iterdir() if d.name.startswith("rev")],
                                 key=lambda x: int(x.replace("rev","")))
                    if revs:
                        latest_rev = revs[-1]
                        meta_file = rev_dir / latest_rev / "meta.json"
                        if meta_file.exists():
                            try:
                                m = json.loads(meta_file.read_text(encoding="utf-8"))
                                dname = m.get("display_name", "")
                            except: pass
                print(f"  {s:<{display_width}}  {stats}  {dname}")
        else:
            print("尚未学习任何技能")
        return

    if args.show:
        show_name = convert_name(args.show)
        show_dir = GA_ROOT / "skills_learning" / show_name
        if not show_dir.exists():
            print(f"技能 '{args.show}' 未学习")
            return
        revs = sorted([d.name for d in show_dir.iterdir() if d.name.startswith("rev")],
                     key=lambda x: int(x.replace("rev","")))
        if not revs:
            print(f"技能 '{args.show}' 无版本记录")
            return
        latest = revs[-1]
        print(f"\n技能: {args.show}")
        print(f"目录: {show_name}")
        meta_file = show_dir / latest / "meta.json"
        if meta_file.exists():
            m = json.loads(meta_file.read_text(encoding="utf-8"))
            for k, v in m.items():
                print(f"  {k}: {v}")
        report_file = show_dir / latest / "reports" / "learning_report.md"
        if report_file.exists():
            print(f"\n  📄 学习报告: skills_learning/{show_name}/{latest}/reports/learning_report.md")
        return

    if args.version:
        print("skill_learn_from_cases v2.0")
        print("案例驱动技能学习CLI工具")
        print("工具目录: tools/skill_learn_from_cases/")
        return

    if args.delete:
        del_name = convert_name(args.delete)
        del_dir = GA_ROOT / "skills_learning" / del_name
        if not del_dir.exists():
            print(f"技能 '{args.delete}' 未学习")
            return
        import shutil
        shutil.rmtree(del_dir)
        print(f"已删除: {del_name}")
        return

    if not args.skill_name:
        parser.print_help()
        return

    skill_name = args.skill_name.strip()
    en_name = convert_name(skill_name)
    if en_name != skill_name:
        print(f"  原始: {skill_name}")
        print(f"  目录: {en_name}")

    if args.dry_run:
        print(f"[DRY RUN] 将学习技能: {skill_name}")
        print(f"          目录名: {en_name}")
        print(f"          流程: Phase 0→1→2→3→4→5")
        print(f"          将创建: skills_learning/{en_name}/revN/")
        # 环境探测
        try:
            from tools.skill_learn_from_cases.env_detector import detect_all
            env = detect_all()
            available = [k for k, v in env.items() if v.get("available")]
            print(f"          环境: {', '.join(available) if available else '无可用服务'}")
            print(f"          LLM: {'启用('+__import__('os').environ.get('LLM_MODEL','?')+')' if __import__('os').environ.get('SKILL_LLM_ENABLE')=='1' else '未启用'}")
        except Exception as e:
            print(f"          环境探测失败: {e}")
        print(f"          提示: 运行 python -m tools.skill_learn_from_cases {skill_name} --force 可强制刷新案例")
        return

    if args.force:
        os.environ["SKILL_FORCE_REFRESH"] = "1"
        print("  [--force] 将强制刷新搜索案例")

    learn_skill(en_name)

    # 自动清理旧版本（保留最近3个）
    skill_dir = GA_ROOT / "skills_learning" / en_name
    if skill_dir.exists():
        import shutil
        revs = sorted(
            [d.name for d in skill_dir.iterdir() if d.name.startswith("rev")],
            key=lambda x: int(x.replace("rev",""))
        )
        while len(revs) > 3:
            old = skill_dir / revs.pop(0)
            shutil.rmtree(old)
            print(f"  自动清理: {old.name}（保留最近3版）")

    # 保存原始显示名到 meta.json
    if en_name != skill_name:
        # meta.json 在 rev{ver}/ 下，找到最新版本
        skill_dir = GA_ROOT / "skills_learning" / en_name
        if skill_dir.exists():
            revs = sorted([d.name for d in skill_dir.iterdir() if d.name.startswith("rev")],
                         key=lambda x: int(x.replace("rev","")))
            if revs:
                meta_file = skill_dir / revs[-1] / "meta.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        meta["display_name"] = skill_name
                        meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                    except Exception as _e:
                        import sys
                        print(f"  [meta] 保存显示名失败: {_e}", file=sys.stderr)


if __name__ == "__main__":
    main()
