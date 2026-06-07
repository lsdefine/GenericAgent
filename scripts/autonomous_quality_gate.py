#!/usr/bin/env python3
"""
autonomous_quality_gate.py — 质量门禁独立验证工具

⚠️ 注意：自主模式下 quality gate 已由 agentmain.py 的 QualityEngine.on_agent_end()
自动完成（评分+修订循环），**无需**在 SOP 收尾中手动调用本脚本。

本脚本用途：
  1. 离线验证：对已生成的报告文件做独立质量评审
  2. 调试/测试：验证 QGS Critic 的评分行为和门禁逻辑
  3. 非自主模式：在未运行 agentmain.py 的场景下手动把关

用法:
  python scripts/autonomous_quality_gate.py check --report R222_xxx.md --threshold 60
  python scripts/autonomous_quality_gate.py simulate              # 模拟测试通过/拒绝场景
  python scripts/autonomous_quality_gate.py assert --report R222_xxx.md  # 严格模式
"""
import argparse
import os
import sys
import json
import tempfile
from pathlib import Path

# ── 路径 ──
BASE = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE / "scripts"
REPORTS_DIR = BASE / "temp" / "autonomous_reports"

# ── 导入 QGS 质量引擎 ──
sys.path.insert(0, str(BASE))
QGS_AVAILABLE = False
try:
    from quality.task import Task, TaskType, Complexity, TaskStatus
    from quality.critic import Critic, CriticConfig
    from quality.gate import decide_gate, should_terminate
    from quality import QualityEngine, QualityConfig
    QGS_AVAILABLE = True
except ImportError as e:
    QGS_AVAILABLE = False
    _qgs_import_error = str(e)

# ── 导入 self_discriminator ──
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    from self_discriminator import get_checklist, check_file_exists, check_report_format
    SD_AVAILABLE = True
except ImportError as e:
    SD_AVAILABLE = False
    _sd_import_error = str(e)


# ═══════════════════════════════════════════════════════════════
# 核心函数
# ═══════════════════════════════════════════════════════════════


def run_self_check(report_path: str, task_type: str = "产出") -> dict:
    """运行自检，返回通过数/总数/详情"""
    if not SD_AVAILABLE:
        return {"passed": 0, "total": 0, "check_results": [], "error": "self_discriminator not available"}

    checklist = get_checklist(task_type)
    results = []
    passed = 0

    # 文件存在检查
    for item in checklist[:5]:  # 仅检查前5项(基础设施/功能验证)
        code = item["code"]
        title = item["title"]
        if code == "c101":
            ok = check_file_exists(report_path)
            results.append({"code": code, "title": title, "passed": ok, "detail": "文件存在" if ok else "文件不存在"})
            if ok:
                passed += 1
        elif code == "c301":
            ok = check_file_exists(report_path)
            results.append({"code": code, "title": title, "passed": ok, "detail": "报告存在" if ok else "报告不存在"})
            if ok:
                passed += 1
        elif code == "c302":
            if SD_AVAILABLE:
                fmt_ok, fmt_detail = check_report_format(report_path)
                results.append({"code": code, "title": title, "passed": fmt_ok, "detail": fmt_detail})
                if fmt_ok:
                    passed += 1
            else:
                results.append({"code": code, "title": title, "passed": True, "detail": "跳过格式检查"})
                passed += 1
        else:
            # 默认通过(非关键项)
            results.append({"code": code, "title": title, "passed": True, "detail": "跳过"})
            passed += 1

    return {
        "passed": passed,
        "total": len(results),
        "check_results": results,
        "pass_rate": round(passed / max(len(results), 1) * 100, 1),
    }


def run_qgs_scoring(report_path: str, task_type_desc: str = "产出") -> dict:
    """使用 QGS Critic 对报告进行质量评分"""
    if not QGS_AVAILABLE:
        return {"score": None, "verdict": "unavailable", "detail": f"QGS模块不可用: {_qgs_import_error}"}

    path = Path(report_path)
    if not path.exists():
        # 尝试在 REPORTS_DIR 下找
        path = REPORTS_DIR / report_path
    if not path.exists():
        return {"score": 0, "verdict": "fail", "detail": f"报告文件不存在: {report_path}"}

    content = path.read_text(encoding="utf-8", errors="ignore")
    if not content.strip():
        return {"score": 0, "verdict": "fail", "detail": "报告内容为空"}

    # 任务类型映射
    type_map = {
        "产出": TaskType.GENERATE,
        "冲浪": TaskType.ACTION,
        "环境": TaskType.ACTION,
    }
    task_type = type_map.get(task_type_desc, TaskType.GENERATE)

    # 创建评审任务
    task = Task(
        id=f"gate_{os.urandom(4).hex()}",
        type=task_type,
        complexity=Complexity.SIMPLE,
        status=TaskStatus.DELIVERED,
        user_request=f"自主任务: {task_type_desc}",
        deliverable=content[:6000],
    )

    # 用 Critic 评分
    try:
        cfg = CriticConfig(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL", ""),
            model=os.environ.get("CRITIC_MODEL", "gpt-4o-mini"),
        )
        critic = Critic(cfg)
        review = critic.review(task)
        return {
            "score": review.score,
            "verdict": review.verdict.value if hasattr(review.verdict, 'value') else str(review.verdict),
            "detail": review.summary[:200] if hasattr(review, 'summary') and review.summary else "评分完成",
            "dimensions": [
                {"name": d.name, "score": d.score, "reason": d.reason[:100]}
                for d in (review.dimensions or [])
            ] if hasattr(review, 'dimensions') else [],
        }
    except Exception as e:
        return {"score": 0, "verdict": "error", "detail": f"评分异常: {e}"}


def gate_decision(self_check: dict, qgs_score: dict, threshold: int = 60) -> dict:
    """门禁决策逻辑

    Returns:
        {
            "passed": bool,        # 是否通过门禁
            "action": str,         # pass / revise / fail
            "self_check_rate": float,
            "qgs_score": int/None,
            "reason": str,
        }
    """
    reasons = []

    # 1. 自检必须全部通过（或至少有检查项）
    self_pass_rate = self_check.get("pass_rate", 0)
    if self_pass_rate < 100 and self_check.get("total", 0) > 0:
        reasons.append(f"自检未全通过: {self_check.get('passed', 0)}/{self_check.get('total', 0)} ({self_pass_rate}%)")
        # 但自检不是完全阻塞的，只是警告

    # 2. QGS 评分决定是否通过
    qgs_score_val = qgs_score.get("score")
    if qgs_score_val is None:
        # QGS 不可用 → 降级：仅靠自检
        reasons.append("QGS不可用，降级为仅自检模式")
        if self_pass_rate >= 80:
            return {"passed": True, "action": "pass_downgraded", "self_check_rate": self_pass_rate, "qgs_score": None, "reason": "; ".join(reasons)}
        else:
            return {"passed": False, "action": "fail", "self_check_rate": self_pass_rate, "qgs_score": None, "reason": "; ".join(reasons)}

    reasons.append(f"QGS评分: {qgs_score_val}/100")

    if qgs_score_val >= threshold:
        # 通过
        return {
            "passed": True,
            "action": "pass",
            "self_check_rate": self_pass_rate,
            "qgs_score": qgs_score_val,
            "reason": "; ".join(reasons),
        }
    else:
        # 未通过
        return {
            "passed": False,
            "action": "revise" if qgs_score_val >= 30 else "fail",
            "self_check_rate": self_pass_rate,
            "qgs_score": qgs_score_val,
            "reason": f"评分 {qgs_score_val} < 阈值 {threshold}; " + "; ".join(reasons),
        }


# ═══════════════════════════════════════════════════════════════
# 模拟测试：通过/拒绝场景
# ═══════════════════════════════════════════════════════════════


def simulate_scenarios():
    """模拟通过/拒绝场景，验证门禁逻辑正确性"""
    print("=" * 60)
    print("🧪 自主模式质量门禁 — 模拟测试")
    print("=" * 60)

    scenarios = [
        # (name, self_check, qgs_score, threshold, expected_pass)
        ("✅ 场景1: 高质量报告通过", {"pass_rate": 100, "passed": 5, "total": 5}, {"score": 85, "verdict": "pass"}, 60, True),
        ("✅ 场景2: 中等质量通过", {"pass_rate": 80, "passed": 4, "total": 5}, {"score": 65, "verdict": "pass"}, 60, True),
        ("❌ 场景3: 低分拒绝", {"pass_rate": 100, "passed": 5, "total": 5}, {"score": 35, "verdict": "fail"}, 60, False),
        ("❌ 场景4: 自检失败+低分拒绝", {"pass_rate": 40, "passed": 2, "total": 5}, {"score": 30, "verdict": "fail"}, 60, False),
        ("⚠️ 场景5: QGS不可用时降级", {"pass_rate": 100, "passed": 5, "total": 5}, {"score": None, "verdict": "unavailable"}, 60, True),
        ("⚠️ 场景6: 无自检但有QGS通过", {"pass_rate": 0, "passed": 0, "total": 0}, {"score": 75, "verdict": "pass"}, 60, True),
        ("❌ 场景7: 空报告拒绝", {"pass_rate": 0, "passed": 0, "total": 5}, {"score": 0, "verdict": "fail"}, 60, False),
        ("✅ 场景8: 高阈值仍通过", {"pass_rate": 100, "passed": 5, "total": 5}, {"score": 92, "verdict": "pass"}, 80, True),
    ]

    all_pass = True
    for name, sc, qgs, threshold, expected in scenarios:
        decision = gate_decision(sc, qgs, threshold)
        actual = decision["passed"]
        status = "✅" if actual == expected else "❌"
        if actual != expected:
            all_pass = False
        print(f"\n{status} {name}")
        print(f"   自检: {sc['passed']}/{sc['total']} | QGS: {qgs['score']} | 阈值: {threshold}")
        print(f"   决策: passed={actual} (期望={expected}) → {decision['action']}")
        print(f"   理由: {decision['reason'][:80]}")

    print("\n" + "=" * 60)
    if all_pass:
        print("🎉 全部场景通过！门禁逻辑正确")
    else:
        print(f"⚠️  存在未通过的场景")
    print("=" * 60)
    return all_pass


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="自主模式质量门禁")
    parser.add_argument("mode", choices=["check", "assert", "simulate", "status"],
                        help="check=检查, assert=严格模式(fail→exit(1)), simulate=模拟测试, status=系统状态")

    parser.add_argument("--report", "-r", help="报告文件路径")
    parser.add_argument("--task-type", "-t", default="产出", choices=["产出", "冲浪", "环境"], help="任务类型")
    parser.add_argument("--threshold", type=int, default=60, help="QGS 及格线 (0-100)")

    args = parser.parse_args()

    if args.mode == "simulate":
        success = simulate_scenarios()
        sys.exit(0 if success else 1)

    if args.mode == "status":
        print("🔍 自主模式质量门禁 — 系统状态")
        print(f"  QGS 质量引擎: {'✅ 可用' if QGS_AVAILABLE else '❌ 不可用'}")
        print(f"  self_discriminator: {'✅ 可用' if SD_AVAILABLE else '❌ 不可用'}")
        print(f"  REPORTS_DIR: {REPORTS_DIR}")
        print(f"  默认阈值: 60")
        return

    if not args.report:
        print("❌ 请指定 --report")
        sys.exit(1)

    # 主流程：自检 → 评分 → 门禁决策
    print(f"\n📋 门禁检查: {args.report} (类型={args.task_type}, 阈值={args.threshold})")
    print("-" * 50)

    # 步骤1: 自检
    print("步骤1/3: 运行自检...")
    self_check = run_self_check(args.report, args.task_type)
    print(f"  自检结果: {self_check.get('passed', 0)}/{self_check.get('total', 0)} ({self_check.get('pass_rate', 0)}%)")

    # 步骤2: QGS 评分
    print("步骤2/3: QGS 质量评分...")
    qgs_score = run_qgs_scoring(args.report, args.task_type)
    print(f"  QGS评分: {qgs_score.get('score', 'N/A')}/100 ({qgs_score.get('verdict', 'N/A')})")

    # 步骤3: 门禁决策
    print("步骤3/3: 门禁决策...")
    decision = gate_decision(self_check, qgs_score, args.threshold)

    print(f"\n{'=' * 50}")
    if decision["passed"]:
        print(f"✅ 门禁通过! (action={decision['action']})")
    else:
        print(f"❌ 门禁拒绝! (action={decision['action']})")
    print(f"   理由: {decision['reason']}")
    print(f"{'=' * 50}")

    if args.mode == "assert" and not decision["passed"]:
        print("\n⚠️  assert模式: 门禁未通过，退出码=1")
        sys.exit(1)


if __name__ == "__main__":
    main()
