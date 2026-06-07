#!/usr/bin/env python3
"""
sop_script_audit.py — SOP引用验证
===================================
扫描SOP文件中引用的脚本路径, 验证存在性。
发现"引用漂移"(SOP引用了不存在的文件/脚本)。

用法:
  python scripts/sop_script_audit.py                          # 全量扫描
  python scripts/sop_script_audit.py --json                   # JSON输出
  python scripts/sop_script_audit.py --fix                    # 生成patch建议
  python scripts/sop_script_audit.py --sop autonomous_operation_sop  # 只扫一个SOP
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

GA_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = GA_ROOT / "memory"
SCRIPTS_DIR = GA_ROOT / "scripts"

# 需要排除的引用模式 (自带路径的引用)
IGNORE_PATTERNS = [
    r'https?://',       # URL
    r'^#',              # 注释/标题
    r'^\s*[-*+]\s',     # 列表项本身
    r'^chrome://',      # 浏览器内部URL
    r'^/',              # 绝对路径/URL (如/review)
]

# 已知废弃/合并的文件 (引用它们不算漂移)
DEPRECATED_FILES = {
    "verifier_sop.md", "verify_sop.md",
    "solver_coder_sop.md", "solver_designer_sop.md", "solver_ops_sop.md",
}

# 运行时生成的动态文件 (subagent创建, 非SOP引用错误)
RUNTIME_FILES = {
    "./subagent_plan.md", "./plan_XXX/",
    "subagent_plan.md",
}

# 外部项目引用 (agency-agents-zh系列)
EXTERNAL_PROJECT_PREFIXES = {"agency-agents-zh/", "engine/", "agentmail-to/"}

# 已知跨领域引用 (本系统内但路径特殊的)
KNOWN_ALIASES = {
    # SOP名→实际文件名
    "solver_role_sops": "solver_writer_sop",
    "vision_api.template": "vision_api.template",
    "keychain": "keychain",  # 目录
    "procmem_scanner": "procmem_scanner",
    "ui_detect.py": "ui_detect.py",
    "ocr_utils.py": "ocr_utils.py",
    "adb_ui.py": "adb_ui.py",
}

# 常见的非文件引用 (引用的目录/别名)
DIRECTORY_NAMES = {"keychain", "procmem_scanner", "L4_raw_sessions", "utils",
                   "templates", "subagent", "agents"}


def extract_references(text: str, source_file: str) -> list:
    """从文本中提取文件名引用"""
    refs = set()

    # 模式1: markdown 链接 [text](path)
    for m in re.finditer(r'\[([^\]]+)\]\(([^)]+)\)', text):
        path = m.group(2).strip()
        if not any(p.match(path) for p in [re.compile(x) for x in IGNORE_PATTERNS]):
            if len(path) < 200 and path[0].isalnum() or path.startswith(('/', '.', '~')):
                refs.add(path)

    # 模式2: 内联代码中的引用 `path/to/file.py` — 仅匹配明确文件路径
    for m in re.finditer(r'`([^`]+)`', text):
        path = m.group(1).strip()
        if len(path) > 200 or len(path) < 3:
            continue
        # 必须包含文件扩展名或路径分隔符
        has_ext = any(path.endswith(ext) for ext in ('.py', '.md', '.sh', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg', '.conf'))
        has_slash = '/' in path
        if not (has_ext or has_slash):
            continue
        # 必须是字母/数字/./-/开头 (过滤中文内容)
        if not path[0].isalnum() and path[0] not in ('.', '/', '_', '~'):
            continue
        # 过滤明显不是引用的 (含空格、换行、中文)
        if any(c in path for c in ('\n', ' ')):
            continue
        if not any(p.match(path) for p in [re.compile(x) for x in IGNORE_PATTERNS]):
            refs.add(path)

    # 模式3: 文件路径模式 (如 scripts/xxx.py)
    for m in re.finditer(r'(?:scripts|tools?|utils?|lib)/[\w./_-]+\.(?:py|sh|md|txt|json|yaml|yml|toml|cfg|conf)',
                         text):
        refs.add(m.group(0))

    # 模式4: memory/ 下文件名 — 严格匹配
    for m in re.finditer(r'memory/[\w./_-]+\.(?:md|py|txt)', text):
        refs.add(m.group(0))

    return sorted(refs)


def resolve_path(ref: str, source_sop: str) -> tuple:
    """尝试解析引用路径, 返回 (exists: bool, resolved_path: str)"""
    ref = ref.strip()

    # 直接绝对/相对路径
    if ref.startswith('/'):
        p = Path(ref)
        return (p.exists(), str(p))

    # 相对 GA_ROOT (处理 memory/xxx, scripts/xxx 等完整相对路径)
    candidate_root = GA_ROOT / ref
    if candidate_root.exists():
        return (True, str(candidate_root))

    # 相对 memory/ 目录
    for base_dir in [MEMORY_DIR, SCRIPTS_DIR, GA_ROOT / "temp"]:
        candidate = base_dir / ref
        if candidate.exists():
            return (True, str(candidate))
        # 尝试去掉目录前缀
        if ref.startswith('../'):
            alt = GA_ROOT / ref[3:]
            if alt.exists():
                return (True, str(alt))

    # 别名检查
    ref_stem = Path(ref).stem
    if ref_stem in KNOWN_ALIASES:
        alias = KNOWN_ALIASES[ref_stem]
        for base_dir in [MEMORY_DIR, SCRIPTS_DIR]:
            candidate = base_dir / alias
            if candidate.exists():
                return (True, str(candidate))
            # 加上后缀
            if not alias.endswith('.md') and not alias.endswith('.py'):
                for ext in ['.md', '.py']:
                    c2 = base_dir / f"{alias}{ext}"
                    if c2.exists():
                        return (True, str(c2))

    # 目录检查
    if ref_stem in DIRECTORY_NAMES:
        for base_dir in [MEMORY_DIR, SCRIPTS_DIR, GA_ROOT / "temp"]:
            candidate = base_dir / ref_stem
            if candidate.is_dir():
                return (True, str(candidate))

    return (False, f"(not found)")


def scan_sop(sop_path: Path) -> list:
    """扫描单个SOP文件, 返回引用记录"""
    results = []
    try:
        text = sop_path.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        return [{"file": sop_path.name, "error": str(e)}]

    refs = extract_references(text, sop_path.name)

    for ref in refs:
        exists, resolved = resolve_path(ref, sop_path.name)
        is_drift = not exists
        results.append({
            "sop_file": sop_path.name,
            "reference": ref,
            "exists": exists,
            "resolved_to": resolved,
            "is_drift": is_drift,
        })

    return results


def main():
    pa = argparse.ArgumentParser(
        description="sop_script_audit.py — SOP引用验证",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/sop_script_audit.py                # 全量扫描
  python scripts/sop_script_audit.py --json --fix   # JSON输出+修复建议
  python scripts/sop_script_audit.py --sop plan_sop   # 只扫一个
        """)
    pa.add_argument("--sop", help="只扫描指定SOP (不含路径)")
    pa.add_argument("--json", action="store_true", help="JSON输出")
    pa.add_argument("--fix", action="store_true", help="生成修复建议(不自动修改)")
    pa.add_argument("--min-score", type=int, default=0, help="最低漂移分数才显示")
    args = pa.parse_args()

    # 收集SOP文件
    sop_files = []
    if args.sop:
        for ext in ['.md', '.py']:
            p = MEMORY_DIR / f"{args.sop}{ext}"
            if p.exists():
                sop_files.append(p)
                break
        else:
            print(f"❌ 未找到SOP: {args.sop}")
            sys.exit(1)
    else:
        for f in sorted(MEMORY_DIR.iterdir()):
            if f.suffix in ('.md', '.py') and not f.name.startswith('.'):
                sop_files.append(f)

    # 扫描
    all_results = []
    drift_count = 0
    total_refs = 0

    for sf in sop_files:
        refs = scan_sop(sf)
        all_results.extend(refs)
        for r in refs:
            if r.get("is_drift"):
                drift_count += 1
            total_refs += 1

    # 最终过滤: 排除模板/变量路径
    filtered = []
    for r in all_results:
        ref = r.get("reference", "")
        # 排除含模板变量的路径 ({xxx})
        if '{' in ref or '}' in ref:
            continue
        # 排除示例名 (RXX_、Tx.md)
        if re.match(r'^R\d+X?_', ref) or ref in ('input.txt', 'context.json', 'WHITEBOARD.md',
           'exploration_findings.md', 'goal_state.json', 'design-image-prompt-engineer.md'):
            continue
        # 排除纯中文引用 (非ASCII占多数)
        non_ascii = sum(1 for c in ref if ord(c) > 127)
        if non_ascii > len(ref) * 0.3:
            continue
        # 排除已知废弃文件 (被合并/重命名)
        if ref in DEPRECATED_FILES:
            continue
        # 排除运行时生成文件
        if ref in RUNTIME_FILES or any(ref.startswith(p) for p in RUNTIME_FILES):
            continue
        # 排除外部项目引用
        if any(ref.startswith(p) for p in EXTERNAL_PROJECT_PREFIXES):
            continue
        # 排除模板路径 (含XXX)
        if 'XXX' in ref:
            continue
        # 排除BBS_CWD等变量赋值
        if '=' in ref and len(ref) > 20:
            continue
        # 排除路径警告中的错误示例 (如 `../memory/autonomous_reports/`)
        if ref.startswith('../memory/') or ref.startswith('../autonomous_reports/'):
            continue
        # 排除文档中的文本非路径 (如 `proxy-pool/(代理池)`)
        if '/(代理' in ref or '/(中文' in ref:
            continue
        # 排除URL占位符 (Markdown链接中的文字URL)
        if ref in ('URL', '仅rapid'):
            continue
        # 排除含中文括号的示例
        if '（' in ref:
            continue
        filtered.append(r)

    all_results = filtered
    drift_count = sum(1 for r in all_results if r.get("is_drift"))
    total_refs = len(all_results)

    # 按漂移排序
    drifts = [r for r in all_results if r.get("is_drift")]
    valid = [r for r in all_results if not r.get("is_drift")]

    if args.json:
        output = {
            "total_sops": len(sop_files),
            "total_refs": total_refs,
            "drift_count": drift_count,
            "valid_refs": len(valid),
            "drifts": drifts,
            "valid": valid if not args.json else [],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(f"\n🔍 SOP引用审计报告")
        print(f"   扫描SOP数: {len(sop_files)}")
        print(f"   总引用数:  {total_refs}")
        print(f"   有效引用:  {len(valid)}")
        print(f"   ❌ 漂移:   {drift_count}")
        print()

        if drifts:
            print("=" * 70)
            print("❌ 发现引用漂移 (SOP引用不存在的文件):")
            print("=" * 70)
            for d in sorted(drifts, key=lambda x: x["sop_file"]):
                print(f"  📄 {d['sop_file']}")
                print(f"     引用: `{d['reference']}`")
                print(f"     状态: ❌ 不存在 (尝试: {d['resolved_to']})")
                print()
        else:
            print("🎉 没有发现引用漂移! 所有引用均有效。")

        if args.fix and drifts:
            print("\n🔧 修复建议 (--fix模式, 不自动修改):")
            print("=" * 70)
            for d in drifts:
                ref = d['reference']
                print(f"  📄 {d['sop_file']}: 引用 `{ref}` 不存在")
                # 找相似文件名
                ref_stem = Path(ref).stem
                suggestions = []
                for pattern in [MEMORY_DIR / f"{ref_stem}*", SCRIPTS_DIR / f"{ref_stem}*"]:
                    for match in GA_ROOT.glob(str(pattern.relative_to(GA_ROOT))):
                        if match.exists() and match.name != ref:
                            suggestions.append(match.name)
                if suggestions:
                    print(f"     相似文件: {', '.join(suggestions[:3])}")
                print()
            print("  提示: 手动检查后, 使用 file_patch 更新SOP中的引用路径。\n")


if __name__ == "__main__":
    main()
