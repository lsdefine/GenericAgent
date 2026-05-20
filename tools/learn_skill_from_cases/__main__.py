"""
__main__.py — learn_skill_from_cases CLI entry point

Usage:
    python -m tools.learn_skill_from_cases "docker_compose_production"
    python -m tools.learn_skill_from_cases --list
    python -m tools.learn_skill_from_cases "python_async" --dry-run
    python -m tools.learn_skill_from_cases "neo4j_modeling" --force
    python -m tools.learn_skill_from_cases --version
    python -m tools.learn_skill_from_cases --show docker_compose_production
"""
import sys, argparse, re, json
from pathlib import Path

GA_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GA_ROOT))

from tools.learn_skill_from_cases import dir_manager


def validate_english_only(name: str):
    """Reject skill names containing CJK characters. English only."""
    if re.search(r'[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', name):
        print("Error: Skill name must be in English only.")
        print("  Chinese characters, Japanese characters, and mixed-language inputs are not supported.")
        print("  Please provide a pure English skill name (e.g., 'docker_compose_production').")
        sys.exit(1)


def cmd_list():
    """List all learned skills with version info."""
    skills = dir_manager.get_all_skills()
    if not skills:
        print("No skills learned yet. Use:")
        print('  python -m tools.learn_skill_from_cases "your_skill_name"')
        return
    print(f"\nLearned skills ({len(skills)} total):")
    print("-" * 55)
    for skill in skills:
        versions = dir_manager.get_versions(skill)
        print(f"  {skill:30s} rev{versions[-1] if versions else '--'}")


def cmd_show(skill_name: str):
    """Show details of a specific skill (version list + patterns)."""
    skill_dir = dir_manager.get_skill_dir(skill_name)
    if not skill_dir.exists():
        print(f"Skill '{skill_name}' not found.")
        return
    versions = dir_manager.get_versions(skill_name)
    if not versions:
        print(f"Skill '{skill_name}' has no versions.")
        return
    print(f"\nSkill: {skill_name}")
    print("=" * 55)
    for v in versions:
        print(f"  rev{v}")
        patterns_file = skill_dir / f"rev{v}" / "patterns" / "knowledge_patterns.json"
        if patterns_file.exists():
            try:
                patterns = json.loads(patterns_file.read_text(encoding="utf-8"))
                for p in patterns:
                    print(f"     [{p.get('level','?')}] {p.get('principle','?')[:70]}")
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="learn_skill_from_cases — English-only skill learning from cases (simplified)",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("skill_name", nargs="?", help="English skill name to learn (e.g., docker_compose_production)")
    parser.add_argument("--list", action="store_true", help="List all learned skills")
    parser.add_argument("--show", metavar="NAME", help="Show details of a learned skill")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating files")
    parser.add_argument("--force", action="store_true", help="Skip inherited patterns, start fresh")
    parser.add_argument("--version", action="store_true", help="Show version")

    args = parser.parse_args()

    # Handle special commands
    if args.version:
        print("learn_skill_from_cases v1.0.0 (simplified English-only version)")
        return

    if args.list:
        cmd_list()
        return

    if args.show:
        cmd_show(args.show)
        return

    # Must have a skill name
    if not args.skill_name:
        parser.print_help()
        print("\nError: Please provide a skill name or use --list.")
        sys.exit(1)

    # Validate: English only
    validate_english_only(args.skill_name)

    # Run the learning pipeline
    from tools.learn_skill_from_cases.engine import run
    ctx = run(args.skill_name, dry_run=args.dry_run, force=args.force)

    if ctx.get("score", 0) >= 60:
        print(f"\n  Learning score: {ctx['score']:.1f}/100 — Good result!")
    elif ctx.get("score", 0) > 0:
        print(f"\n  Learning score: {ctx['score']:.1f}/100 — Consider adding more cases.")
    else:
        print(f"\n  Score not available. Review the output above.")


if __name__ == "__main__":
    main()
