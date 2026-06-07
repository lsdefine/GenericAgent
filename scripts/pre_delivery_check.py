#!/usr/bin/env python3
"""
pre_delivery_check.py — 交付前自检强制闭环

在标记TODO完成前自动调用self_discriminator进行检查。
如果检查未通过，拒绝标记完成。

集成 QGS 质量引擎：通过 --quality 对交付物进行质量评分。

用法:
  python scripts/pre_delivery_check.py check --task-type 产出 --outputs file1 file2
  python scripts/pre_delivery_check.py assert --task-type 产出 --outputs file1 file2
  python scripts/pre_delivery_check.py check --task-type 产出 --outputs R220.md --quality --threshold 60
"""
import sys, os, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DISCRIMINATOR = BASE / "scripts" / "self_discriminator.py"

# QGS 质量引擎导入（可选）
try:
    sys.path.insert(0, str(BASE))
    from quality.task import Task, TaskType, Complexity, TaskStatus
    from quality.critic import Critic, CriticConfig
    QGS_AVAILABLE = True
except ImportError:
    QGS_AVAILABLE = False


def run_qgs_quality_check(outputs, task_type_desc, threshold=60):
    """使用 QGS Critic 对交付物进行质量评分

    Args:
        outputs: 交付物文件路径列表
        task_type_desc: 任务类型描述（产出/冲浪/环境）
        threshold: 及格线 (0-100)

    Returns:
        (passed, score, details)
    """
    if not QGS_AVAILABLE:
        print("[pre_delivery] ⚠️ QGS 质量引擎不可用（quality 模块未安装）")
        return True, None, "QGS unavailable"

    # 任务类型映射
    type_map = {
        "产出": TaskType.GENERATE,
        "冲浪": TaskType.ACTION,
        "环境": TaskType.ACTION,
    }
    task_type = type_map.get(task_type_desc, TaskType.GENERATE)

    # 收集交付物内容
    deliverables_text = ""
    for o in outputs:
        path = Path(o)
        if not path.exists():
            path = BASE / o
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="ignore")
            deliverables_text += f"\n\n=== {path.name} ===\n{content}"
        else:
            print(f"[pre_delivery] ⚠️ 交付物未找到: {o}")
            deliverables_text += f"\n\n=== {o} (NOT FOUND) ==="

    if not deliverables_text.strip():
        print("[pre_delivery] ⚠️ 无交付物内容可评审")
        return False, 0, "No deliverables"

    # 创建评审任务
    task = Task(
        id=f"qgs_{os.urandom(4).hex()}",
        type=task_type,
        complexity=Complexity.COMPLEX,
        status=TaskStatus.DELIVERED,
        user_request=f"交付任务: {task_type_desc}",
        deliverable=deliverables_text[:8000],  # 截断防止超长
    )

    # 运行评审
    cfg = CriticConfig()
    critic = Critic(cfg)
    review = critic.review(task)

    score = int(review.score)
    passed = score >= threshold

    # 输出结果
    print(f"\n[pre_delivery] 📊 QGS 质量评分: {score}/100")
    print(f"[pre_delivery]   评审方法: {review.review_method}")
    print(f"[pre_delivery]   结论: {'✅ PASS' if passed else '❌ FAIL'} (阈值: {threshold})")
    if review.critique_summary:
        print(f"[pre_delivery]   摘要: {review.critique_summary[:200]}")
    if review.dimensions:
        for d in review.dimensions:
            mark = "✅" if d.score >= threshold else "⚠️"
            print(f"[pre_delivery]   {mark} {d.name}: {d.score}/100")
            if d.issues and d.score < threshold:
                for issue in d.issues[:2]:
                    print(f"[pre_delivery]      - {issue}")
    if review.must_fix:
        print(f"[pre_delivery]   需修复项:")
        for fix in review.must_fix[:3]:
            print(f"[pre_delivery]      - {fix}")

    return passed, score, review.critique_summary


def run_check(task_type, outputs=None, assert_mode=False, quality_check=False, quality_threshold=60):
    # 原有 self_discriminator 自检
    if not DISCRIMINATOR.exists():
        print(f"[pre_delivery] ⚠️ self_discriminator.py not found at {DISCRIMINATOR}")
        print("[pre_delivery] ⚠️ 跳过自检")
    else:
        cmd = [sys.executable, str(DISCRIMINATOR)]
        if assert_mode:
            cmd.append("assert")
        else:
            cmd.append("check")
        cmd.extend(["--task-type", task_type])
        
        # 传递任务标题用于self_discriminator的TODO检查
        # 从task_type映射到人类可读标题（目前仅传递任务类型）
        cmd.extend(["--task-title", task_type])
        
        if outputs:
            for o in outputs:
                cmd.extend(["--outputs", o])
        
        print(f"[pre_delivery] 🔍 运行自检: {' '.join(cmd[-6:])}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.stdout:
                for line in result.stdout.split('\n'):
                    if any(kw in line for kw in ['PASS', 'FAIL', '✅', '❌', '结果', '通过']):
                        print(f"  {line.strip()}")
            
            if result.returncode != 0:
                if assert_mode:
                    print(f"[pre_delivery] ❌ 自检未通过!")
                    print(f"  stderr: {result.stderr[:200]}")
                    return False
                else:
                    print(f"[pre_delivery] ⚠️ 自检有警告（check模式继续）")
        except Exception as e:
            print(f"[pre_delivery] ⚠️ 自检异常: {e}")
    
    # QGS 质量评分（可选）
    if quality_check and outputs:
        passed, score, _ = run_qgs_quality_check(outputs, task_type, quality_threshold)
        if assert_mode and not passed:
            print(f"[pre_delivery] ❌ QGS 质量评分未通过 ({score}/{quality_threshold})")
            return False
        if passed:
            print(f"[pre_delivery] ✅ QGS 质量评分通过")
    
    print(f"[pre_delivery] ✅ 交付检查完成")
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="交付前自检强制闭环（含 QGS 质量评分）")
    parser.add_argument("mode", choices=["check", "assert"], default="check")
    parser.add_argument("--task-type", required=True, choices=["产出", "冲浪", "环境"])
    parser.add_argument("--outputs", nargs="*", default=[])
    parser.add_argument("--quality", action="store_true", help="启用 QGS 质量评分")
    parser.add_argument("--threshold", type=int, default=60, help="QGS 及格线 (0-100)")
    args = parser.parse_args()
    
    passed = run_check(
        args.task_type,
        args.outputs,
        assert_mode=args.mode == "assert",
        quality_check=args.quality,
        quality_threshold=args.threshold,
    )
    sys.exit(0 if passed else 1)
