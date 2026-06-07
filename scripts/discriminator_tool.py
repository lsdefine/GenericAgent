#!/usr/bin/env python3
"""
discriminator_tool.py — 统一判别工具

整合4个判别者角色（现实检验者/性能基准师/API测试员/无障碍审核员）为统一CLI。
基于：
  - discriminator_reality_checker_sop.md
  - discriminator_performance_benchmarker_sop.md
  - discriminator_api_tester_sop.md
  - discriminator_accessibility_auditor_sop.md
  - self_discriminate_sop.md

CLI:
  python discriminator_tool.py list                        # 列出所有判别者
  python discriminator_tool.py check <role> [--outputs ...] # 运行单个判别者
  python discriminator_tool.py full [--outputs ...]         # 全部判别者运行
  python discriminator_tool.py report [--json]              # 生成聚合报告
  python discriminator_tool.py assert <role> [--outputs ...] # 严格模式(exit非0)

角色:
  reality_checker    🎯 现实检验者 — 幻想式审批阻止
  perf_benchmarker   ⚡ 性能基准师 — 数据驱动的性能评审
  api_tester         🔌 API测试员 — 全维度API验证
  accessibility      ♿ 无障碍审核员 — 包容性审计
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════
# 判别者定义
# ═══════════════════════════════════════════════════════════

DISCRIMINATORS = {
    "reality_checker": {
        "emoji": "🎯",
        "name": "现实检验者",
        "desc": "阻止幻想式审批，基于证据的认证",
        "color": "red",
        "report_format": (
            "### 当前评审：🎯 现实检验者\n"
            "### 状态：✅ 已完成\n"
            "### 发现问题：\n"
            "| 等级 | 分类 | 标题 | 说明 |\n"
            "|------|------|------|------|\n"
            "| {sev} | {cat} | {title} | {desc} |\n"
            "### 结论：{conclusion}\n"
        ),
    },
    "perf_benchmarker": {
        "emoji": "⚡",
        "name": "性能基准师",
        "desc": "没有基准测试不算优化——用数据说话",
        "color": "orange",
        "report_format": (
            "### 当前评审：⚡ 性能基准师\n"
            "### 状态：✅ 已完成\n"
            "### 发现问题：\n"
            "| 等级 | 分类 | 标题 | 说明 |\n"
            "|------|------|------|------|\n"
            "| {sev} | {cat} | {title} | {desc} |\n"
            "### 结论：{conclusion}\n"
        ),
    },
    "api_tester": {
        "emoji": "🔌",
        "name": "API测试员",
        "desc": "全面API覆盖——确保每个接口都经过严格验证",
        "color": "cyan",
        "report_format": (
            "### 当前评审：🔌 API 测试员\n"
            "### 状态：✅ 已完成\n"
            "### 发现问题：\n"
            "| 等级 | 分类 | 标题 | 说明 |\n"
            "|------|------|------|------|\n"
            "| {sev} | {cat} | {title} | {desc} |\n"
            "### 结论：{conclusion}\n"
        ),
    },
    "accessibility": {
        "emoji": "♿",
        "name": "无障碍审核员",
        "desc": "默认找问题——确保产品对所有人可用",
        "color": "yellow",
        "report_format": (
            "### 当前评审：♿ 无障碍审核员\n"
            "### 状态：✅ 已完成\n"
            "### 发现问题：\n"
            "| 等级 | 分类 | 标题 | 说明 |\n"
            "|------|------|------|------|\n"
            "| {sev} | {cat} | {title} | {desc} |\n"
            "### 结论：{conclusion}\n"
        ),
    },
}

# ═══════════════════════════════════════════════════════════
# 检查清单（从 SOP 中提取）
# ═══════════════════════════════════════════════════════════

CHECKLISTS = {
    "reality_checker": [
        # 功能完整性
        ("P1", "功能", "是否实现了任务要求的所有功能？"),
        ("P2", "功能", "输出格式是否与要求一致？"),
        ("P2", "功能", "是否有超出范围的功能（功能膨胀）？"),
        # 证据检查
        ("P0", "证据", "是否有充足的理由支持每个决策？"),
        ("P0", "证据", "声明是否有数据或演示支撑？"),
        ("P1", "证据", "交付物是否可被第三方验证？"),
        # 安全与注入检查 (v2.1)
        ("P0", "安全", "任务描述是否包含可疑的指令覆盖（忽略上述指令、override SOP）？"),
        ("P1", "安全", "交付物输出是否存在prompt注入迹象？"),
        ("P2", "安全", "被评审的agent是否读取并遵循了其角色SOP？"),
        ("P0", "安全", "交付物中的代码/脚本是否包含高危操作（rm -rf, curl恶意地址, 密钥泄露）？"),
        # 风格检查（文本）
        ("P2", "风格", "语言是否清晰易懂？"),
        ("P3", "风格", "结构是否合理？（有引言、正文、总结）"),
        ("P3", "风格", "图文配置是否适当？"),
        # 风格检查（代码）
        ("P2", "风格", "代码是否可读？"),
        ("P3", "风格", "是否有注释说明关键逻辑？"),
        ("P3", "风格", "命名是否规范？"),
    ],
    "perf_benchmarker": [
        # 证据与数据
        ("P0", "证据", "是否有基准测试数据支撑优化声明？"),
        ("P1", "证据", "测量方法是否可靠（测量次数足够？多次取均值？）"),
        ("P1", "证据", "是否提供了优化前/后的对比数据？"),
        ("P2", "证据", "改进幅度是否在统计误差之上？"),
        ("P2", "证据", "是否标明了测量单位和误差范围？"),
        ("P2", "证据", "性能提升的代价是什么？（内存增加？代码复杂度？）"),
        # 负载与压力
        ("P1", "负载", "是否测试了不同负载级别下的表现？"),
        ("P1", "负载", "是否测试了峰值负载和极限情况？"),
        ("P2", "负载", "是否存在性能拐点（吞吐量突然下降）？"),
        ("P3", "负载", "资源消耗（CPU、内存、IO）是否在可接受范围？"),
        # 端到端验证
        ("P1", "端到端", "微基准测试之外是否做了真实场景测试？"),
        ("P2", "端到端", "用户感知性能（TTFB/FP/LCP等指标）是否测量？"),
        ("P3", "端到端", "是否对比了业界基线或竞品表现？"),
    ],
    "api_tester": [
        # 覆盖度
        ("P0", "覆盖度", "所有公开端点是否都有测试覆盖？"),
        ("P1", "覆盖度", "是否覆盖了所有HTTP方法（GET/POST/PUT/DELETE）？"),
        ("P2", "覆盖度", "异常路径是否覆盖（4xx/5xx）？"),
        ("P2", "覆盖度", "测试数据是否包含边界值和特殊字符？"),
        ("P1", "覆盖度", "API文档是否与实现一致（OpenAPI Schema）？"),
        ("P2", "覆盖度", "状态码使用是否符合HTTP规范？"),
        # 请求验证
        ("P1", "请求", "是否需要认证？认证失败返回什么？"),
        ("P2", "请求", "参数校验：缺少、类型错误、超出范围"),
        ("P2", "请求", "请求体格式校验：非法JSON、缺少必填字段"),
        ("P3", "请求", "分页参数：limit/offset/page边界"),
        # 响应验证
        ("P1", "响应", "成功响应是否包含所有承诺字段"),
        ("P1", "响应", "错误响应是否包含可读的error message"),
        ("P2", "响应", "响应时间是否符合SLA"),
        ("P2", "响应", "幂等性：重复请求是否产生副作用"),
        # 安全测试（基础）
        ("P0", "安全", "鉴权绕过尝试"),
        ("P1", "安全", "IDOR（水平越权）检查"),
        ("P2", "安全", "输入注入测试"),
        ("P3", "安全", "速率限制是否存在"),
    ],
    "accessibility": [
        # 键盘导航
        ("P0", "键盘", "所有交互元素是否可用键盘操作？"),
        ("P0", "键盘", "焦点顺序是否符合视觉顺序？"),
        ("P1", "键盘", "是否有焦点陷阱（focus trap）？"),
        ("P2", "键盘", "跳过导航链接（skip-to-content）是否存在？"),
        # 屏幕阅读器
        ("P1", "屏幕阅读器", "图片是否有有意义的alt文本？"),
        ("P2", "屏幕阅读器", "装饰性图片是否正确标记（alt=\"\"或role=\"presentation\"）？"),
        ("P2", "屏幕阅读器", "图标是否有替代文本？"),
        ("P2", "屏幕阅读器", "ARIA属性使用是否正确？"),
        ("P3", "屏幕阅读器", "动态内容更新是否有ARIA live region通知？"),
        # 色彩与对比度
        ("P1", "对比度", "文本与背景的对比度是否达到4.5:1（AA）？"),
        ("P2", "对比度", "大文本是否达到3:1？"),
        ("P2", "对比度", "颜色是否不是传递信息的唯一方式？"),
        ("P3", "对比度", "焦点环对比度是否充足？"),
        # 表单与交互
        ("P1", "表单", "错误提示是否有文字描述？"),
        ("P2", "表单", "必填字段是否有标识？"),
        ("P2", "表单", "表单提交后是否有成功/失败反馈？"),
        ("P3", "表单", "自动完成/输入建议是否无障碍？"),
        # 多媒体
        ("P2", "多媒体", "视频是否有字幕和文字稿？"),
        ("P3", "多媒体", "音频是否有文字稿？"),
        ("P3", "多媒体", "动画是否可关闭（prefers-reduced-motion）？"),
    ],
}

# 等级权重
SEVERITY_WEIGHTS = {
    "P0": 100,
    "P1": 50,
    "P2": 20,
    "P3": 10,
    "P4": 5,
}

SEVERITY_LABELS = {
    "P0": "🔴 致命缺陷",
    "P1": "🟠 严重缺陷",
    "P2": "🟡 一般缺陷",
    "P3": "🔵 轻微缺陷",
    "P4": "⚪ 建议改进",
}


# ═══════════════════════════════════════════════════════════
# 核心逻辑
# ═══════════════════════════════════════════════════════════

class DiscriminatorResult:
    """一个判别者的评审结果"""
    def __init__(self, role: str):
        info = DISCRIMINATORS[role]
        self.role = role
        self.emoji = info["emoji"]
        self.name = info["name"]
        self.timestamp = datetime.now().isoformat()
        self.issues = []  # [(severity, category, title, desc)]
        self.passed = True
        self.conclusion = "✅ 通过"

    def add_issue(self, severity: str, category: str, title: str, desc: str = ""):
        self.issues.append((severity, category, title, desc))
        if severity in ("P0",):
            self.passed = False
            self.conclusion = "❌ 不通过"

    def finalize(self):
        """确定最终结论"""
        if not self.issues:
            self.conclusion = "✅ 通过"
            self.passed = True
            return

        has_p0 = any(sev == "P0" for sev, _, _, _ in self.issues)
        has_p1 = any(sev == "P1" for sev, _, _, _ in self.issues)

        if has_p0:
            self.conclusion = "❌ 不通过"
            self.passed = False
        elif has_p1:
            self.conclusion = "🔶 需修改"
            self.passed = False
        else:
            self.conclusion = "✅ 通过"
            self.passed = True

    def to_markdown(self) -> str:
        self.finalize()
        lines = []
        lines.append(f"### 当前评审：{self.emoji} {self.name}")
        lines.append(f"### 状态：✅ 已完成")
        lines.append("")
        lines.append("### 发现问题：")

        if not self.issues:
            lines.append("*无报告问题*")
        else:
            lines.append("| 等级 | 分类 | 检查项 |")
            lines.append("|------|------|--------|")
            for sev, cat, title, desc in self.issues:
                label = SEVERITY_LABELS.get(sev, sev)
                lines.append(f"| {label} | {cat} | {title} |")

        lines.append("")
        lines.append(f"### 结论：{self.conclusion}")
        if not self.passed:
            lines.append("- P0 问题必须修复后才能再次评审")
            if any(sev == "P1" for sev, _, _, _ in self.issues):
                lines.append("- P1 问题建议优化")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        self.finalize()
        return {
            "role": self.role,
            "name": self.name,
            "emoji": self.emoji,
            "timestamp": self.timestamp,
            "passed": self.passed,
            "conclusion": self.conclusion,
            "issues": [
                {"severity": s, "category": c, "title": t, "desc": d}
                for s, c, t, d in self.issues
            ],
        }


def run_discriminator(role: str, outputs: list = None) -> DiscriminatorResult:
    """
    运行指定角色的判别检查。
    outputs: 待检查的文件路径列表
    """
    result = DiscriminatorResult(role)
    checklist = CHECKLISTS.get(role, [])

    if not outputs:
        # 无待查文件时只输出清单项（报告检查清单本身）
        for sev, cat, title in checklist:
            result.add_issue(sev, cat, title, "待人工确认")
        result.finalize()
        return result

    # 有待查文件时，尝试自动化检查
    for output_path in outputs:
        p = Path(output_path)
        if not p.exists():
            result.add_issue("P0", "文件完整性", f"输出文件不存在: {output_path}")
            continue
        if p.stat().st_size == 0:
            result.add_issue("P1", "文件完整性", f"输出文件为空: {output_path}")
            continue

        # 根据角色运行特定检查
        content = None
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            result.add_issue("P2", "文件完整性", f"无法读取文件: {output_path}")

        if content:
            _run_role_checks(role, content, output_path, result, checklist)

    result.finalize()
    return result


def _run_role_checks(role: str, content: str, path: str, result: DiscriminatorResult, checklist: list):
    """根据角色运行内容级检查"""
    content_lower = content.lower()

    if role == "reality_checker":
        # 检查是否有方案描述模糊不清
        if "大概" in content or "差不多" in content or "可能" in content:
            result.add_issue("P2", "功能", f"方案描述不精确（含模糊词）")
        # 检查高危操作
        if "rm -rf" in content:
            result.add_issue("P0", "安全", f"包含 rm -rf 高危操作: {path}")
        # 检查是否有数据支撑
        if len(content.split()) < 50:
            result.add_issue("P1", "证据", f"报告内容过于简短: {path}")

    elif role == "perf_benchmarker":
        # 检查是否包含性能指标
        perf_keywords = ["ms", "秒", "qps", "吞吐", "延迟", "latency", "benchmark", "基准"]
        has_perf_data = any(kw in content_lower for kw in perf_keywords)
        if not has_perf_data:
            result.add_issue("P0", "证据", f"缺少性能数据: {path}")
        # 检查是否有优化声明但无对比
        if ("优化" in content or "提升" in content or "加速" in content):
            if not any(kw in content_lower for kw in ["之前", "之前", "before", "after", "对比", "提升率"]):
                result.add_issue("P1", "证据", "有优化声明但缺少优化前/后对比数据")

    elif role == "api_tester":
        # 检查是否有API测试覆盖率信息
        if not any(kw in content_lower for kw in ["端点", "endpoint", "api", "接口", "路由", "route"]):
            result.add_issue("P1", "覆盖度", f"缺少API端点清单: {path}")
        # 检查是否有状态码覆盖
        if "200" not in content and "201" not in content:
            result.add_issue("P2", "覆盖度", "缺少成功响应(200/201)测试")
        if "400" not in content and "401" not in content and "404" not in content:
            result.add_issue("P2", "覆盖度", "缺少错误响应(400/401/404)测试")
        # 安全测试
        if "auth" not in content_lower and "认证" not in content:
            result.add_issue("P1", "安全", "缺少认证测试用例")

    elif role == "accessibility":
        # 检查alt文本
        if "alt" not in content_lower and "aria" not in content_lower:
            result.add_issue("P1", "屏幕阅读器", f"缺少alt/ARIA使用信息: {path}")
        # 检查对比度
        if "对比度" not in content and "contrast" not in content_lower:
            result.add_issue("P1", "对比度", f"缺少对比度检查: {path}")
        # 键盘导航
        if "键盘" not in content and "focus" not in content_lower and "tab" not in content_lower:
            result.add_issue("P1", "键盘", f"缺少键盘导航测试: {path}")


def run_all(outputs: list = None) -> dict:
    """运行所有判别者"""
    results = {}
    for role in DISCRIMINATORS:
        results[role] = run_discriminator(role, outputs)
    return results


def generate_aggregate_report(results: dict, task_type: str = "产出") -> str:
    """生成聚合报告"""
    lines = []
    lines.append("# 判别者聚合评审报告")
    lines.append("")
    lines.append(f"**日期**: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**任务类型**: {task_type}")
    lines.append("")

    # 汇总表
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 判别者 | 结论 | 问题数(P0/P1/P2/P3) |")
    lines.append("|--------|------|---------------------|")

    total_passed = 0
    for role, result in results.items():
        info = DISCRIMINATORS[role]
        p0 = sum(1 for s, _, _, _ in result.issues if s == "P0")
        p1 = sum(1 for s, _, _, _ in result.issues if s == "P1")
        p2 = sum(1 for s, _, _, _ in result.issues if s == "P2")
        p3 = sum(1 for s, _, _, _ in result.issues if s == "P3")
        if result.passed:
            total_passed += 1
        lines.append(f"| {info['emoji']} {result.name} | {result.conclusion} | {p0}/{p1}/{p2}/{p3} |")

    lines.append("")
    lines.append(f"**通过率**: {total_passed}/{len(results)}")
    lines.append("")

    # 详细报告
    lines.append("## 详细评审")
    lines.append("")
    for role, result in results.items():
        lines.append(result.to_markdown())
        lines.append("")
        lines.append("---")
        lines.append("")

    # 总评
    lines.append("## 总评")
    lines.append("")
    if all(r.passed for r in results.values()):
        lines.append("✅ **全部通过** — 交付物通过所有判别者评审")
    elif any(r.passed for r in results.values()):
        lines.append("🔶 **部分通过** — 需修复问题后重新评审")
    else:
        lines.append("❌ **未通过** — 存在严重问题需全面修复")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════

def cmd_list():
    """列出所有可用判别者"""
    print("可用判别者：\n")
    for role, info in DISCRIMINATORS.items():
        print(f"  {info['emoji']} {info['name']:　<8s} ({role})")
        print(f"      {info['desc']}")
        items = CHECKLISTS.get(role, [])
        p0 = sum(1 for s, _, _ in items if s == "P0")
        p1 = sum(1 for s, _, _ in items if s == "P1")
        p2 = sum(1 for s, _, _ in items if s == "P2")
        p3 = sum(1 for s, _, _ in items if s == "P3")
        print(f"      检查项: {len(items)}项 (P0={p0}, P1={p1}, P2={p2}, P3={p3})")
        print()
    print("使用: python discriminator_tool.py check <role> [--outputs file1 file2 ...]")


def cmd_check(args):
    """运行单个判别者"""
    outputs = args.outputs
    role = args.role
    if role not in DISCRIMINATORS:
        print(f"错误: 未知角色 '{role}'")
        print(f"可用角色: {', '.join(DISCRIMINATORS.keys())}")
        sys.exit(1)

    result = run_discriminator(role, outputs)
    print(result.to_markdown())
    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    if args.assert_mode and not result.passed:
        sys.exit(1)
    return result.passed


def cmd_full(args):
    """运行所有判别者"""
    outputs = args.outputs
    results = run_all(outputs)
    report = generate_aggregate_report(results, args.task_type)
    print(report)

    if args.json:
        print("\n--- JSON ---")
        data = {r: results[r].to_dict() for r in results}
        print(json.dumps(data, ensure_ascii=False, indent=2))

    if args.assert_mode:
        if not all(r.passed for r in results.values()):
            sys.exit(1)

    return all(r.passed for r in results.values())


def cmd_report(args):
    """生成聚合报告"""
    results = run_all(args.outputs)
    report = generate_aggregate_report(results, args.task_type)

    # 写文件
    reports_dir = Path(os.environ.get("REPORTS_DIR", "./autonomous_reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"discriminator_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    report_path.write_text(report, encoding="utf-8")

    if args.json:
        json_path = report_path.with_suffix(".json")
        data = {r: results[r].to_dict() for r in results}
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"报告已写入: {report_path}")
    if args.json:
        print(f"JSON已写入: {json_path}")
    return all(r.passed for r in results.values())


def main():
    parser = argparse.ArgumentParser(
        description="Discriminator Tool — 统一判别工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # list
    p_list = sub.add_parser("list", help="列出所有判别者")

    # check
    p_check = sub.add_parser("check", help="运行单个判别者")
    p_check.add_argument("role", choices=list(DISCRIMINATORS.keys()), help="判别者角色")
    p_check.add_argument("--outputs", nargs="*", default=None, help="待检查的文件路径列表")
    p_check.add_argument("--json", action="store_true", help="输出JSON")
    p_check.add_argument("--assert", dest="assert_mode", action="store_true", help="严格模式")

    # full
    p_full = sub.add_parser("full", help="运行所有判别者")
    p_full.add_argument("--outputs", nargs="*", default=None, help="待检查的文件路径列表")
    p_full.add_argument("--task-type", default="产出", help="任务类型")
    p_full.add_argument("--json", action="store_true", help="输出JSON")
    p_full.add_argument("--assert", dest="assert_mode", action="store_true", help="严格模式")

    # report
    p_report = sub.add_parser("report", help="生成聚合报告")
    p_report.add_argument("--outputs", nargs="*", default=None, help="待检查的文件路径列表")
    p_report.add_argument("--task-type", default="产出", help="任务类型")
    p_report.add_argument("--json", action="store_true", help="同时输出JSON")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list()
    elif args.command == "check":
        return 0 if cmd_check(args) else 1
    elif args.command == "full":
        return 0 if cmd_full(args) else 1
    elif args.command == "report":
        return 0 if cmd_report(args) else 1
    else:
        parser.print_help()
        return 0  # help shown, not an error


if __name__ == "__main__":
    sys.exit(main())
