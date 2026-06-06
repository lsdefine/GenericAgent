#!/usr/bin/env python3
"""
MetricsAggregator — 提示词质量评分引擎
=======================================

评分维度（1-10）:
  A: 结构完整性 (Structure)
  B: 内容质量 (Content)
  C: 一致性 (Consistency)
  D: 可用性 (Usability)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── 评分规则 ──────────────────────────────────────────

def score_structure(text: str) -> Dict:
    """A 维度: 检查 prompt 文件的结构完整性"""
    issues = []
    points = 10.0

    if not re.search(r"tags:\s*\[", text):
        points -= 1.5
        issues.append("A2: 缺乏 tags 数组")

    if not re.search(r"#{1,2}\s*你的角色|角色定义|工作范围", text):
        points -= 1.5
        issues.append("A4: 缺少角色/职责描述段")

    if not re.search(r"[✅❌]\s*你只做|✅\s*你", text):
        points -= 1.5
        issues.append("A5: 缺少 ✅/❌ 边界段")

    has_sep = text.startswith("---")
    if not has_sep:
        points -= 1.0
        issues.append("A1: 缺少 frontmatter 分隔符")
    else:
        end = text.find("---", 3)
        if end > 0 and "role_id:" not in text[:end]:
            points -= 1.0
            issues.append("A3: 缺少 role_id")

    sections = re.findall(r"^#{1,3}\s+.+", text, re.MULTILINE)
    if len(sections) < 3:
        points -= 1.0
        issues.append("A6: 段落数量不足 (<3)")

    return {
        "score": max(0, round(points, 1)),
        "issues": issues,
    }


def score_content(text: str) -> Dict:
    """B 维度: 检查 prompt 的内容质量"""
    issues = []
    points = 10.0

    if not re.search(r"你只做|你的职责|你是|You are", text, re.IGNORECASE):
        points -= 1.5
        issues.append("B1: 职责描述不清晰")
    else:
        duty_lines = [l for l in text.split("\n") if re.search(r"[✅❌\-*]\s*", l)]
        if len(duty_lines) < 2:
            points -= 0.5
            issues.append("B1: 职责列表太少 (<2 条)")

    if not re.search(r"[❌❌]\s*你不|禁止|不要|Don't|do not", text, re.IGNORECASE):
        points -= 1.5
        issues.append("B2: 缺少禁止/边界说明")

    if "{task_text}" not in text and "{context}" not in text:
        points -= 1.0
        issues.append("B3: 缺少任务上下文占位符")

    if not re.search(r"输出规范|输出格式|{output_spec}", text):
        points -= 1.0
        issues.append("B4: 缺少输出规范/格式说明")

    if not re.search(r"不修改|不提供|不执行|除非|only when|only if", text, re.IGNORECASE):
        points -= 1.0
        issues.append("B5: 缺乏防越界规则")

    if len(text) < 100:
        points -= 1.0
        issues.append("B6: 文件过短 (<100 字符)")

    return {
        "score": max(0, round(points, 1)),
        "issues": issues,
    }


def score_consistency(text: str, filepath: str = "") -> Dict:
    """C 维度: 检查 prompt 的一致性"""
    issues = []
    points = 10.0

    if filepath:
        fname = Path(filepath).stem
        if not fname.startswith("_") and "role_id:" in text:
            m = re.search(r"role_id:\s*['\"]?(\w+)['\"]?", text)
            if m and m.group(1) != fname:
                points -= 2.0
                issues.append(f"C1: role_id ({m.group(1)}) 与文件名 ({fname}) 不匹配")

    placeholders = re.findall(r"\{(\w+)\}", text)
    if len(placeholders) > 5:
        points -= 0.5
        issues.append(f"C2: 占位符过多 ({len(placeholders)}个)")

    if text.count("```") % 2 != 0:
        points -= 1.0
        issues.append("C3: 代码块标记不匹配")

    return {
        "score": max(0, round(points, 1)),
        "issues": issues,
    }


def score_usability(text: str) -> Dict:
    """D 维度: 检查 prompt 的可用性"""
    issues = []
    points = 10.0

    if len(text) < 200:
        points -= 1.5
        issues.append("D1: 文档过短 (<200 字符)")
    elif len(text) < 500:
        points -= 0.5
        issues.append("D1: 文档偏短 (<500 字符)")

    if not re.search(r"示例|例如|for example|e\.g\.|如：", text):
        points -= 1.0
        issues.append("D2: 缺少示例/参考")

    headings = re.findall(r"^(#{1,3})\s", text, re.MULTILINE)
    if len(headings) < 2:
        points -= 1.0
        issues.append("D3: 层级标题不足")

    list_items = re.findall(r"^[\s]*[-*✅❌]\s+", text, re.MULTILINE)
    if len(list_items) < 3:
        points -= 0.5
        issues.append("D4: 列表项较少 (<3)")

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    repeated = set()
    for i, l in enumerate(lines):
        if l in lines[i+1:]:
            repeated.add(l)
    if repeated:
        points -= 1.0
        issues.append(f"D5: 存在重复行 ({len(repeated)}处)")

    return {
        "score": max(0, round(points, 1)),
        "issues": issues,
    }


# ── 聚合器 ────────────────────────────────────────────

def score_prompt(text: str, filepath: str = "") -> Dict:
    """对单个 prompt 文件进行全维度评分"""
    if not text.strip():
        return {"total": 0.0, "grade": "F", "dimensions": {}, "all_issues": ["EMPTY: 文件为空"], "weak_tags": []}

    A = score_structure(text)
    B = score_content(text)
    C = score_consistency(text, filepath)
    D = score_usability(text)

    total = round((A["score"] + B["score"] + C["score"] + D["score"]) / 4, 2)

    if total >= 4.5:
        grade = "A"
    elif total >= 3.5:
        grade = "B"
    elif total >= 2.5:
        grade = "C"
    else:
        grade = "D"

    all_issues = A["issues"] + B["issues"] + C["issues"] + D["issues"]
    weak_tags = sorted(set(i.split(":")[0].strip() for i in all_issues))

    return {
        "total": total,
        "grade": grade,
        "dimensions": {"A": A["score"], "B": B["score"], "C": C["score"], "D": D["score"]},
        "all_issues": all_issues,
        "weak_tags": weak_tags,
    }


def scan_directory(directory: str, pattern: str = "*.md") -> Dict[str, Dict]:
    """扫描目录下所有 prompt 文件并评分"""
    results = {}
    path = Path(directory)
    if not path.exists():
        return {"error": f"目录不存在: {directory}"}

    files = list(path.rglob(pattern)) + list(path.rglob("*.prompt"))
    for fpath in sorted(set(files)):
        if fpath.name.startswith("."):
            continue
        try:
            text = fpath.read_text(encoding="utf-8")
            relpath = str(fpath.relative_to(path.parent))
            results[relpath] = score_prompt(text, str(fpath))
        except Exception as e:
            results[str(fpath)] = {"error": str(e)}
    return results


# ── 报告输出 ──────────────────────────────────────────

def format_report(results: Dict[str, Dict], detailed: bool = False) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("  PROMPT QUALITY REPORT")
    lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)

    if "error" in results:
        lines.append(f"\n❌ {results['error']}")
        return "\n".join(lines)

    files_scored = {k: v for k, v in results.items() if "error" not in v}
    files_error = {k: v for k, v in results.items() if "error" in v}

    if not files_scored:
        lines.append("\n没有找到可评分的文件。")
        return "\n".join(lines)

    scores = [v["total"] for v in files_scored.values()]
    avg = sum(scores) / len(scores)
    grades = [v["grade"] for v in files_scored.values()]

    lines.append(f"\n📊 汇总: {len(files_scored)} 文件 | 平均分: {avg:.2f}")
    lines.append(f"   等级: A={grades.count('A')} B={grades.count('B')} C={grades.count('C')} D={grades.count('D')}")
    lines.append(f"   范围: {min(scores):.1f} ~ {max(scores):.1f}")
    lines.append("")

    lines.append(f"{'文件':<45} {'总分':>5} {'等级':>4} {'A':>5} {'B':>5} {'C':>5} {'D':>5}")
    lines.append("-" * 80)
    for fname, result in sorted(files_scored.items()):
        d = result["dimensions"]
        lines.append(f"{fname:<45} {result['total']:>5.1f} {result['grade']:>4} {d['A']:>5.1f} {d['B']:>5.1f} {d['C']:>5.1f} {d['D']:>5.1f}")

    if detailed:
        lines.append(f"\n{'─' * 80}")
        lines.append("弱项明细:")
        for fname, result in sorted(files_scored.items()):
            if result["all_issues"]:
                lines.append(f"\n  📄 {fname}")
                for issue in result["all_issues"]:
                    lines.append(f"    ⚠ {issue}")

    if files_error:
        lines.append(f"\n⚠ 读取失败: {', '.join(files_error.keys())}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def format_json(results: Dict[str, Dict]) -> str:
    output = {}
    for fname, result in results.items():
        if "error" not in result:
            output[fname] = {"total": result["total"], "grade": result["grade"],
                             "dimensions": result["dimensions"], "weak_tags": result["weak_tags"]}
        else:
            output[fname] = {"error": result["error"]}
    return json.dumps(output, indent=2, ensure_ascii=False)


# ── 历史记录 ──────────────────────────────────────────

HISTORY_FILE = Path.home() / ".prompt_optimize_history.jsonl"

def save_history(results: Dict[str, Dict]):
    scores = [v["total"] for v in results.values() if "error" not in v]
    if not scores:
        return
    record = {
        "timestamp": datetime.now().isoformat(),
        "file_count": len(scores),
        "avg_score": round(sum(scores) / len(scores), 2),
        "grades": {
            "A": sum(1 for v in results.values() if v.get("grade") == "A"),
            "B": sum(1 for v in results.values() if v.get("grade") == "B"),
            "C": sum(1 for v in results.values() if v.get("grade") == "C"),
            "D": sum(1 for v in results.values() if v.get("grade") == "D"),
        },
    }
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def show_history() -> str:
    if not HISTORY_FILE.exists():
        return "暂无历史记录。"
    records = []
    with open(HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if not records:
        return "暂无历史记录。"
    lines = ["=" * 60, "  PROMPT OPTIMIZATION HISTORY", "=" * 60,
             f"{'#':>3} {'时间':<20} {'文件数':>6} {'平均分':>7} {'A':>4} {'B':>4} {'C':>4} {'D':>4}", "-" * 60]
    for i, r in enumerate(records, 1):
        g = r.get("grades", {})
        lines.append(f"{i:>3} {r['timestamp'][:19]:<20} {r['file_count']:>6} {r['avg_score']:>7.2f} "
                     f"{g.get('A',0):>4} {g.get('B',0):>4} {g.get('C',0):>4} {g.get('D',0):>4}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ── 改进建议 ──────────────────────────────────────────

IMPROVEMENT_MAP = {
    "A1": "在文件开头添加 `---` frontmatter 分隔符",
    "A2": "在 frontmatter 中添加 `tags: [category, function]`",
    "A3": "在 frontmatter 中添加 `role_id:` 字段",
    "A4": "添加 `## 你的角色` 或 `## 工作范围` 段落",
    "A5": "添加 `✅ 你只做以下事情：` 和 `❌ 你不做以下事情：`",
    "A6": "增加段落数量，至少 3 个标题段",
    "B1": "明确职责描述，使用 `你只做以下事情：` 列表",
    "B2": "添加 `❌ 你不做以下事情：` 列举禁止项",
    "B3": "在适当位置添加 `{task_text}` 上下文占位符",
    "B4": "添加 `## 输出格式` 段和 `{output_spec}`",
    "B5": "添加防越界规则（不修改/不提供/不执行）",
    "B6": "扩充文件内容至 100 字符以上",
    "C1": "检查 role_id 与文件名是否一致",
    "C2": "减少占位符数量或整合模板变量",
    "C3": "修复代码块标记使其成对",
    "D1": "扩充文档内容至 200 字符以上",
    "D2": "添加示例或参考用例",
    "D3": "增加层级标题（## / ###）组织结构",
    "D4": "增加列表项提升可读性",
    "D5": "删除重复行",
}


def suggest_improvements(weak_tags: List[str]) -> List[str]:
    return [f"{tag}: {IMPROVEMENT_MAP[tag]}" for tag in weak_tags if tag in IMPROVEMENT_MAP]


# ── CLI ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="提示词质量评分引擎 — 自动评分/报告/优化建议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  %(prog)s --dir engine/roles/         扫描角色目录评分
  %(prog)s --dir . --report            详细报告
  %(prog)s --file prompt.md            单个文件评分
  %(prog)s --history                   查看历史趋势
  %(prog)s --dir . --suggest           评分+改进建议
        """)
    parser.add_argument("--dir", "-d", default=".", help="扫描目录")
    parser.add_argument("--file", "-f", help="对单个文件评分")
    parser.add_argument("--report", "-r", action="store_true", help="详细报告")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    parser.add_argument("--save", "-s", action="store_true", help="保存历史")
    parser.add_argument("--history", "-H", action="store_true", help="查看历史")
    parser.add_argument("--suggest", "-S", action="store_true", help="改进建议")
    parser.add_argument("--pattern", "-p", default="*.md", help="扫描模式")

    args = parser.parse_args()

    if args.history:
        print(show_history())
        return

    if args.file:
        fpath = Path(args.file)
        if not fpath.exists():
            print(f"❌ 文件不存在: {args.file}")
            sys.exit(1)
        text = fpath.read_text(encoding="utf-8")
        results = {str(fpath): score_prompt(text, str(fpath))}
    else:
        results = scan_directory(args.dir, args.pattern)

    if "error" in results:
        print(f"❌ {results['error']}")
        sys.exit(1)

    if args.save:
        save_history(results)

    if args.json:
        print(format_json(results))
    else:
        print(format_report(results, detailed=args.report))

    if args.suggest:
        weak_map = {f: suggest_improvements(r["weak_tags"])
                    for f, r in results.items() if "error" not in r and r["weak_tags"]}
        if weak_map:
            print(f"\n{'─' * 60}\n💡 改进建议：")
            for fname, suggestions in weak_map.items():
                print(f"\n  📄 {fname}")
                for s in suggestions[:5]:
                    print(f"    → {s}")
        else:
            print("\n✅ 没有需要改进的弱项。")

    scores = [v["total"] for v in results.values() if "error" not in v]
    if scores:
        avg = sum(scores) / len(scores)
        print(f"\n📊 平均分: {avg:.2f}", end=" ")
        if avg >= 4.5:
            print("🎉 优秀！")
        elif avg >= 3.5:
            print("👍 可继续优化。")
        elif avg >= 2.5:
            print("⚠ 需要改进。")
        else:
            print("❌ 急需修复。")


if __name__ == "__main__":
    main()
