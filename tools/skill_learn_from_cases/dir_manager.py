"""
dir_manager.py — 技能版本目录管理

职责：检测已有版本、创建 revN 目录、继承上一版模式
"""

import os
import json
import shutil
from pathlib import Path
import re as _re

# GA 根目录（通过包路径推算）
GA_ROOT = Path(__file__).resolve().parents[2]
SKILL_LEARN_ROOT = GA_ROOT / "skills_learning"


def _sanitize_skill_name(skill_name: str) -> str:
    """
    清洗技能名：移除路径遍历字符（../..）和危险字符，
    确保只能用作单个目录名，不能进行路径穿越。
    """
    # 移除非字母数字下划线连字符和中文的字符
    sanitized = _re.sub(r'[^\w\-\u4e00-\u9fff]', '_', skill_name)
    # 防止空名和特殊前缀
    sanitized = sanitized.strip('_')
    if not sanitized:
        sanitized = "unnamed_skill"
    return sanitized


def _list_dirs(parent: Path) -> list[Path]:
    """列出目录下所有子目录"""
    if not parent.exists():
        return []
    return [d for d in parent.iterdir() if d.is_dir()]


def get_versions(skill_name: str) -> list[int]:
    """获取某技能已有的版本号列表，如 [1, 2, 3]"""
    skill_dir = SKILL_LEARN_ROOT / _sanitize_skill_name(skill_name)
    versions = []
    for d in _list_dirs(skill_dir):
        if d.name.startswith("rev"):
            try:
                versions.append(int(d.name[3:]))
            except ValueError:
                pass
    return sorted(versions)  # 数字排序，确保 rev9 < rev10


def next_version(skill_name: str) -> int:
    """返回下一个版本号"""
    versions = get_versions(skill_name)
    return (max(versions) + 1) if versions else 1



def ensure_root_exists():
    """确保 skills_learning 根目录存在，不存在则自动创建"""
    if not SKILL_LEARN_ROOT.exists():
        SKILL_LEARN_ROOT.mkdir(parents=True, exist_ok=True)
        print(f"  [OK] skills_learning/ 根目录已自动创建")


def get_skill_dir(skill_name: str) -> Path:
    """返回技能目录（路径注入防护：skill_name 经 _sanitize_skill_name 清洗）"""
    return SKILL_LEARN_ROOT / _sanitize_skill_name(skill_name)


def get_latest_revision_dir(skill_name: str) -> Path | None:
    """返回包含知识模式的最新版本 rev 目录（跳过空目录）"""
    safe_name = _sanitize_skill_name(skill_name)
    versions = get_versions(safe_name)
    if not versions:
        return None
    skill_dir = SKILL_LEARN_ROOT / safe_name
    # 从高往低找，取第一个有模式文件的版本
    for v in reversed(versions):
        patterns_file = skill_dir / f"rev{v}" / "patterns" / "knowledge_patterns.json"
        if patterns_file.exists():
            return skill_dir / f"rev{v}"
    # 实在找不到返回最高版本（可能为空）
    return skill_dir / f"rev{versions[-1]}"


def get_latest_patterns(skill_name: str) -> list[dict]:
    """继承上一版的知识模式，如果存在的话"""
    latest = get_latest_revision_dir(skill_name)
    if latest is None:
        return []
    patterns_file = latest / "patterns" / "knowledge_patterns.json"
    if patterns_file.exists():
        with open(patterns_file, encoding="utf-8") as f:
            return json.load(f)
    return []


def get_latest_cases(skill_name: str) -> list[dict]:
    """继承上一版的案例"""
    latest = get_latest_revision_dir(skill_name)
    if latest is None:
        return []
    cases_dir = latest / "cases"
    all_cases = []
    if cases_dir.exists():
        for f in cases_dir.iterdir():
            if f.suffix == ".json":
                try:
                    with open(f, encoding="utf-8") as fh:
                        data = json.load(fh)
                        if isinstance(data, list):
                            all_cases.extend(data)
                        else:
                            all_cases.append(data)
                except (json.JSONDecodeError, OSError):
                    pass
    return all_cases


def create_revision_dir(skill_name: str, version: int) -> Path:
    """
    创建 revN 目录结构:
    revN/
      ├── meta.json
      ├── cases/
      ├── patterns/
      ├── tools/
      ├── reports/
      └── iterations/
    """
    rev_dir = SKILL_LEARN_ROOT / _sanitize_skill_name(skill_name) / f"rev{version}"
    subdirs = ["cases", "patterns", "tools", "practice", "reports", "iterations"]
    for s in subdirs:
        (rev_dir / s).mkdir(parents=True, exist_ok=True)

    # 写入元数据
    meta = {
        "skill": skill_name,
        "version": version,
        "created_at": "2026-05-13",
        "status": "in_progress"
    }
    with open(rev_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return rev_dir


def get_all_skills() -> list[str]:
    """获取 skill_learning 下所有技能名称"""
    if not SKILL_LEARN_ROOT.exists():
        return []
    return sorted(d.name for d in _list_dirs(SKILL_LEARN_ROOT)
                  if d.is_dir())
