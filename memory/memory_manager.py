#!/usr/bin/env python3
"""
记忆管理自动化脚本
==================
功能：
1. 解析L2 (global_mem.txt) 中的SECTION列表，同步到L1的L2关键词行
2. 扫描L3 (memory/ 下的SOP/脚本/Skill目录)，同步到L1的L3极简索引
3. 只添加缺失关键词，不搬运细节；默认不删除旧索引，只提示可能过期项

验收标准：
- L2变更时自动patch L1索引
- L3新增SOP/Skill/关键工具时自动patch L1索引
- 只添加关键词，不搬细节
- 不破坏现有L1结构

使用方法：
    python memory_manager.py                  # 检查并同步
    python memory_manager.py --check          # 只检查不同步
    python memory_manager.py --dry-run        # 预览模式
    python memory_manager.py --rebuild-l3     # 按SOP>文件夹>独立py重建L3索引（显式清理重复项）

规则（来自META-SOP）：
- L1只写关键词/名称，禁搬细节
- 新增场景：L1加入极简关键词
- 删除场景：默认只提示stale，不自动删（避免误删已验证经验）
- 修改值：若不影响场景定位则不动L1
"""

import os
import re
import argparse
from datetime import datetime
from pathlib import Path

# Paths (relative to this file)
MEMORY_DIR = Path(__file__).resolve().parent
L1_PATH = MEMORY_DIR / "global_mem_insight.txt"
L2_PATH = MEMORY_DIR / "global_mem.txt"

# L3扫描排除项：排除缓存/数据/备份/密钥等（通用，不针对特定技能）
EXCLUDE_NAMES = {
    "__pycache__",
    "downloads",
    "L4_raw_sessions",
    "chat_history.json",
    "file_access_stats.json",
    "global_mem.txt",
    "global_mem_insight.txt",
    "memory_management_sop.md",
    "memory_manager.py",  # 管理器自身不放L3索引，L0/L2已有入口
    "vision_api.template.py",
}
EXCLUDE_SUFFIXES = {".json", ".jsonl", ".txt", ".log", ".db", ".sqlite", ".pyc"}


# ── 解析辅助函数 ──

def parse_l2_sections(l2_content):
    """Parse L2 content to extract SECTION names. Section name should use safe tokens like OCR_VISION."""
    sections = []
    for line in l2_content.splitlines():
        match = re.match(r'^## \[([^\]]+)\]', line)
        if match:
            section = match.group(1).strip()
            if section:
                sections.append(section)
    return sections


def parse_l1_l2_topics(l1_content):
    """Parse L1 L2 line. L2 uses '/' as topic delimiter, so L2 section names must not contain '/'."""
    for line in l1_content.splitlines():
        if line.startswith('L2:'):
            parts = line.replace('L2:', '', 1).strip().split('/')
            return [p.strip() for p in parts if p.strip()]
    return []


def extract_l3_block(lines):
    """Return (start, end, block_lines) for L3 block. Continuation lines start with '|'."""
    start = None
    for i, line in enumerate(lines):
        if line.startswith('L3:'):
            start = i
            break
    if start is None:
        return None, None, []
    end = start + 1
    while end < len(lines) and lines[end].startswith('|'):
        end += 1
    return start, end, lines[start:end]


def parse_l1_l3_entries(l1_content):
    """Parse L1 L3 block into existing display entries."""
    lines = l1_content.splitlines()
    _, _, block = extract_l3_block(lines)
    if not block:
        return []
    entries = []
    for line in block:
        if line.startswith('L3:'):
            text = line.replace('L3:', '', 1).strip()
        else:
            text = line.strip().lstrip('|').strip()
        entries.extend([p.strip() for p in text.split('|') if p.strip()])
    return entries


def l3_base_name(path):
    """Return rough skill base for grouping SOP/folder/py."""
    name = path.name
    if path.is_dir():
        return name
    if name.endswith('_sop.md'):
        return name[:-7]  # remove _sop.md
    if name.endswith('.md'):
        return name[:-3]
    if name.endswith('.py'):
        return name[:-3]
    return name


def sop_represented_py(path, sop_bases):
    """Check if a .py file should be represented by an existing SOP.

    Two rules:
    1. Prefix match: py file name starts with any SOP base (e.g. vision_api -> vision_sop)
    2. Content scan: SOP document references the py file (e.g. vision_sop.md mentions ocr_utils)
    """
    if not path.is_file() or path.suffix != '.py':
        return False
    stem = path.stem  # e.g. vision_api, ocr_utils
    # Rule 1: prefix match
    for base in sop_bases:
        if stem == base or stem.startswith(base + '_'):
            return True
    # Rule 2: content scan - check if any SOP doc references this py file
    for sop_path in MEMORY_DIR.glob('*_sop.md'):
        try:
            content = sop_path.read_text(encoding='utf-8')
            # Match: import ocr_utils, ocr_utils.py, from ocr_utils, ocr_utils.
            if re.search(rf'\b{re.escape(stem)}\b', content):
                return True
        except Exception:
            continue
    return False


def should_ignore_l3_path(path):
    """Common ignore filter for L3 scan."""
    name = path.name
    if name.startswith('.') or name in EXCLUDE_NAMES:
        return True
    if path.is_file() and path.suffix in EXCLUDE_SUFFIXES:
        return True
    return False


def is_sop_file(path):
    return path.is_file() and path.suffix == '.md' and not should_ignore_l3_path(path)


def is_folder_skill(path):
    """Check if directory qualifies as a skill folder.
    A folder is a skill only if it contains at least one .md or .py file inside.
    Empty folders, data-only folders (e.g. evolution with only .json/.jsonl), 
    and backup folders are excluded.
    """
    if not path.is_dir() or should_ignore_l3_path(path):
        return False
    for child in path.iterdir():
        if child.is_file() and child.suffix in {'.md', '.py'}:
            return True
    return False


def is_py_skill(path):
    return path.is_file() and path.suffix == '.py' and not should_ignore_l3_path(path)


# ── 通用显示名规则（无需修改即可适配其他仓库）──

def display_name_for_sop(path):
    """SOP显示名：去掉.md后缀，保留_sop标识"""
    return path.stem  # e.g. vision_sop.md -> vision_sop


def display_name_for_folder(path):
    """文件夹显示名：直接用文件夹名"""
    return path.name


def display_name_for_py(path):
    """独立脚本显示名：直接用文件名（含.py）"""
    return path.name


def scan_l3_candidates():
    """Scan memory directory for L3 index candidates using SOP > folder > py priority.

    Rules (通用，不依赖硬编码映射):
    1. SOP优先：若存在SOP文档（*_sop.md），则同名/归属文件夹或.py由SOP代表，避免重复。
    2. 文件夹优先：若无SOP但存在技能文件夹，则以文件夹名索引，忽略内部/同名py。
    3. 独立脚本：既无SOP也无归属文件夹时，以.py全名索引，且排在最后一组。
    """
    paths = [p for p in MEMORY_DIR.iterdir() if not should_ignore_l3_path(p)]

    # 1) SOP first
    sop_entries = []
    sop_bases = set()
    for path in sorted([p for p in paths if is_sop_file(p)], key=lambda p: p.name.lower()):
        display = display_name_for_sop(path)
        sop_entries.append(display)
        sop_bases.add(l3_base_name(path))

    # 2) folders only when not represented by SOP
    folder_entries = []
    folder_bases = set()
    for path in sorted([p for p in paths if is_folder_skill(p)], key=lambda p: p.name.lower()):
        base = l3_base_name(path)
        if base in sop_bases:
            continue
        folder_entries.append(display_name_for_folder(path))
        folder_bases.add(base)

    # 3) py last only when independent and not represented by SOP
    py_entries = []
    py_bases = set()
    for path in sorted([p for p in paths if is_py_skill(p)], key=lambda p: p.name.lower()):
        base = l3_base_name(path)
        if base in sop_bases or base in folder_bases:
            continue
        if sop_represented_py(path, sop_bases):
            continue
        if base in py_bases:
            continue
        py_entries.append(display_name_for_py(path))
        py_bases.add(base)

    # de-duplicate while preserving group order
    seen = set()
    result = []
    for item in sop_entries + folder_entries + py_entries:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def generate_l2_patch(l1_content, new_sections):
    """Generate L1 content with new L2 section keywords appended."""
    if not new_sections:
        return l1_content
    lines = l1_content.splitlines()
    out = []
    for line in lines:
        if line.startswith('L2:'):
            current = line.replace('L2:', '', 1).strip()
            all_topics = current + '/' + '/'.join(new_sections) if current else '/'.join(new_sections)
            out.append(f'L2: {all_topics}')
        else:
            out.append(line)
    return '\n'.join(out) + ('\n' if l1_content.endswith('\n') else '')


def format_l3_block(entries, max_per_line=7):
    """Format L3 entries as compact multi-line block.

    Independent .py skills are kept in a final py-only row to distinguish them
    from SOP/folder skills while preserving the legacy L3 pipe-list style.
    """
    if not entries:
        return ['L3:']
    py_entries = [e for e in entries if e.endswith('.py')]
    main_entries = [e for e in entries if not e.endswith('.py')]
    lines = []
    groups = []
    for i in range(0, len(main_entries), max_per_line):
        groups.append(main_entries[i:i + max_per_line])
    if py_entries:
        groups.append(py_entries)
    for i, chunk in enumerate(groups):
        prefix = 'L3: ' if i == 0 else '| '
        lines.append(prefix + ' | '.join(chunk))
    return lines


def generate_l3_patch(l1_content, new_l3_entries):
    """Generate L1 content with new L3 entries appended to L3 block."""
    if not new_l3_entries:
        return l1_content
    lines = l1_content.splitlines()
    start, end, block = extract_l3_block(lines)
    existing = parse_l1_l3_entries(l1_content)
    merged = existing + [e for e in new_l3_entries if e not in existing]
    new_block = format_l3_block(merged)
    if start is None:
        # insert after L2 line if L3 block missing
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith('L2:'):
                insert_at = i + 1
                break
        lines[insert_at:insert_at] = new_block
    else:
        lines[start:end] = new_block
    return '\n'.join(lines) + ('\n' if l1_content.endswith('\n') else '')


def rebuild_l3_patch(l1_content, l3_entries):
    """Rebuild the entire L3 block from canonical grouped candidates.

    Explicit mode only: used to remove duplicated py/script entries already represented by SOP/folder.
    """
    lines = l1_content.splitlines()
    start, end, _ = extract_l3_block(lines)
    new_block = format_l3_block(l3_entries)
    if start is None:
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith('L2:'):
                insert_at = i + 1
                break
        lines[insert_at:insert_at] = new_block
    else:
        lines[start:end] = new_block
    return '\n'.join(lines) + ('\n' if l1_content.endswith('\n') else '')


def main():
    parser = argparse.ArgumentParser(description='记忆管理自动化脚本')
    parser.add_argument('--check', action='store_true', help='只检查不同步')
    parser.add_argument('--dry-run', action='store_true', help='预览模式')
    parser.add_argument('--rebuild-l3', action='store_true', help='按SOP>文件夹>独立py重建L3索引，清理重复项')
    parser.add_argument('--validate', action='store_true', help='验证记忆完整性和规范性（不写入）')
    args = parser.parse_args()

    print('=' * 60)
    print('记忆管理自动化脚本')
    print('=' * 60)
    print(f"⏰ 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    print('\n[1] 读取L1/L2...')
    if not L1_PATH.exists():
        print(f'✗ L1文件不存在: {L1_PATH}')
        return 1
    if not L2_PATH.exists():
        print(f'✗ L2文件不存在: {L2_PATH}')
        return 1
    l1_content = L1_PATH.read_text(encoding='utf-8')
    l2_content = L2_PATH.read_text(encoding='utf-8')
    print(f'✓ L1已读取 ({len(l1_content)} bytes)')
    print(f'✓ L2已读取 ({len(l2_content)} bytes)')

    print('\n[2] 解析L2 SECTION...')
    l2_sections = parse_l2_sections(l2_content)
    l1_l2_topics = parse_l1_l2_topics(l1_content)
    print(f'✓ L2 SECTION: {l2_sections}')
    print(f'✓ L1 L2索引: {l1_l2_topics}')
    unsafe = [s for s in l2_sections if '/' in s]
    if unsafe:
        print(f'⚠ L2 SECTION含分隔符/，建议改为下划线: {unsafe}')
    new_l2_sections = [s for s in l2_sections if s not in l1_l2_topics]
    stale_l2_topics = [t for t in l1_l2_topics if t not in l2_sections]
    print(f'✓ L2待添加: {new_l2_sections or []}')
    print(f'ℹ L2可能过期(不自动删除): {stale_l2_topics or []}')

    print('\n[3] 扫描L3候选...')
    l3_candidates = scan_l3_candidates()
    l1_l3_entries = parse_l1_l3_entries(l1_content)
    new_l3_entries = [e for e in l3_candidates if e not in l1_l3_entries]
    stale_l3_entries = [e for e in l1_l3_entries if e not in l3_candidates]
    print(f'✓ L3候选({len(l3_candidates)}): {l3_candidates}')
    print(f'✓ L1 L3现有({len(l1_l3_entries)}): {l1_l3_entries}')
    print(f'✓ L3待添加: {new_l3_entries or []}')
    print(f'ℹ L3可能过期/人工别名(不自动删除): {stale_l3_entries or []}')

    if args.check:
        print('\n' + '=' * 60)
        print('检查完成（不同步）')
        print('=' * 60)
        return 0

    if args.validate:
        errors = []
        # L1 size check
        l1_lines = [l for l in l1_content.split('\n') if l.strip()]
        if len(l1_lines) > 30:
            errors.append(f'L1行数超标({len(l1_lines)}>30)')
        # L2 naming check
        unsafe = [s for s in l2_sections if '/' in s]
        if unsafe:
            errors.append(f'L2 SECTION含非法字符/: {unsafe}')
        for s in l2_sections:
            if not re.match(r'^[A-Z][A-Z_]*$', s):
                errors.append(f'L2 SECTION命名不规范(应全大写+下划线): {s}')
        # L3 duplicates (within current L1)
        l3_cur = parse_l1_l3_entries(l1_content)
        if len(l3_cur) != len(set(l3_cur)):
            errors.append('L3条目有重复(同一显示名出现多次)')
        # L3 py entries at end check
        py_idx = [i for i, e in enumerate(l3_cur) if e.endswith('.py')]
        non_py_idx = [i for i, e in enumerate(l3_cur) if not e.endswith('.py')]
        if py_idx and non_py_idx and max(non_py_idx) > min(py_idx):
            errors.append('独立.py技能未排列在最后')
        # L3 stale entries
        if stale_l3_entries:
            errors.append(f'L3可能过期条目(清理后会丢失): {stale_l3_entries}')
        
        print('\n' + '=' * 60)
        print('验证报告')
        print('=' * 60)
        print(f'  L2 SECTION: {l2_sections}')
        print(f'  L3候选: {l3_candidates}')
        print(f'  L2待添加: {new_l2_sections or []}')
        print(f'  L3待添加: {new_l3_entries or []}')
        print(f'  L1总行数: {len(l1_lines)} (≤30=达标)')
        if errors:
            print(f'\n⚠ 发现问题:')
            for e in errors:
                print(f'  ❌ {e}')
        else:
            print(f'\n✅ 验证通过，无问题')
        print('=' * 60)
        return 0

    new_content = l1_content
    if new_l2_sections:
        new_content = generate_l2_patch(new_content, new_l2_sections)
    if args.rebuild_l3:
        print('ℹ --rebuild-l3: 将按当前SOP>文件夹>独立py规则重建L3块')
        new_content = rebuild_l3_patch(new_content, l3_candidates)
    elif new_l3_entries:
        new_content = generate_l3_patch(new_content, new_l3_entries)

    if new_content == l1_content:
        print('\n✓ L1无需更新')
    elif args.dry_run:
        print('\n[预览模式] 不实际写入')
        print('-' * 60)
        print(new_content)
        print('-' * 60)
    else:
        L1_PATH.write_text(new_content, encoding='utf-8')
        print('\n✓ L1已更新')

    print('\n' + '=' * 60)
    print('✅ 记忆管理完成')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
