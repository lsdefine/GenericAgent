"""
dir_manager.py — Skill version directory management (simplified, English-only)

Responsibilities: detect existing versions, create revN directories, inherit previous patterns.
"""
import os, json, shutil, re
from pathlib import Path

GA_ROOT = Path(__file__).resolve().parents[2]
SKILL_LEARN_ROOT = GA_ROOT / "skills_learning"


def _sanitize_skill_name(skill_name: str) -> str:
    """Sanitize skill name: only allow alphanumeric, underscore, hyphen. No path traversal."""
    sanitized = re.sub(r'[^\w\-]', '_', skill_name)
    sanitized = sanitized.strip('_')
    return sanitized or "unnamed_skill"


def _list_dirs(parent: Path) -> list[Path]:
    if not parent.exists():
        return []
    return [d for d in parent.iterdir() if d.is_dir()]


def get_versions(skill_name: str) -> list[int]:
    """Get existing version numbers for a skill, e.g. [1, 2, 3]"""
    skill_dir = SKILL_LEARN_ROOT / _sanitize_skill_name(skill_name)
    versions = []
    for d in _list_dirs(skill_dir):
        if d.name.startswith("rev"):
            try:
                versions.append(int(d.name[3:]))
            except ValueError:
                pass
    return sorted(versions)


def next_version(skill_name: str) -> int:
    """Return the next version number."""
    versions = get_versions(skill_name)
    return (max(versions) + 1) if versions else 1


def ensure_root_exists():
    """Ensure skills_learning/ root directory exists."""
    if not SKILL_LEARN_ROOT.exists():
        SKILL_LEARN_ROOT.mkdir(parents=True, exist_ok=True)
        print("  [OK] skills_learning/ root directory created")


def get_skill_dir(skill_name: str) -> Path:
    """Return skill directory (path injection protected)."""
    return SKILL_LEARN_ROOT / _sanitize_skill_name(skill_name)


def get_latest_revision_dir(skill_name: str) -> Path | None:
    """Return the latest rev directory that has knowledge patterns."""
    safe_name = _sanitize_skill_name(skill_name)
    versions = get_versions(safe_name)
    if not versions:
        return None
    skill_dir = SKILL_LEARN_ROOT / safe_name
    for v in reversed(versions):
        patterns_file = skill_dir / f"rev{v}" / "patterns" / "knowledge_patterns.json"
        if patterns_file.exists():
            return skill_dir / f"rev{v}"
    return skill_dir / f"rev{versions[-1]}"


def get_latest_patterns(skill_name: str) -> list[dict]:
    """Inherit knowledge patterns from the latest revision."""
    latest = get_latest_revision_dir(skill_name)
    if latest is None:
        return []
    patterns_file = latest / "patterns" / "knowledge_patterns.json"
    if patterns_file.exists():
        with open(patterns_file, encoding="utf-8") as f:
            return json.load(f)
    return []


def get_latest_cases(skill_name: str) -> list[dict]:
    """Inherit cases from the latest revision."""
    latest = get_latest_revision_dir(skill_name)
    if not latest:
        return []
    cases_file = latest / "cases" / "all_cases.json"
    if cases_file.exists():
        try:
            with open(cases_file, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, OSError):
            pass
    return []


def create_revision_dir(skill_name: str, version: int) -> Path:
    """
    Create revN directory structure:
    revN/
      ├── meta.json
      ├── cases/
      ├── patterns/
      ├── tools/
      ├── reports/
      └── practice/
    """
    rev_dir = SKILL_LEARN_ROOT / _sanitize_skill_name(skill_name) / f"rev{version}"
    subdirs = ["cases", "patterns", "tools", "practice", "reports"]
    for s in subdirs:
        (rev_dir / s).mkdir(parents=True, exist_ok=True)

    meta = {
        "skill": skill_name,
        "version": version,
        "created_at": "2026-05-15",
        "status": "in_progress"
    }
    with open(rev_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return rev_dir


def get_all_skills() -> list[str]:
    """Get all skill names under skills_learning/."""
    if not SKILL_LEARN_ROOT.exists():
        return []
    return sorted(d.name for d in _list_dirs(SKILL_LEARN_ROOT) if d.is_dir())
