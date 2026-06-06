#!/usr/bin/env python3
"""
sop_recommender.py — SOP推荐器
================================
根据任务描述推荐相关SOP, 解决R25/R45发现"40+未读SOP但从不利用"的P0问题.

用法:
  python scripts/sop_recommender.py "写浏览器自动化脚本"
  python scripts/sop_recommender.py "我需要分析系统性能"
  python scripts/sop_recommender.py --list              # 列出所有SOP分类
  python scripts/sop_recommender.py --json "修复bug"    # JSON格式输出
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"


# ── SOP知识库: 手动精选的任务类型→SOP映射 ──────────────
# 持续更新: 发现新匹配关系时追加
SOP_KNOWLEDGE = [
    # 浏览器/视觉
    (("浏览器", "自动化", "交互"),
     ["tmwebdriver_sop", "vision_sop", "ocr_utils.py"]),
    (("视觉", "OCR", "截图", "图像"),
     ["vision_sop", "ocr_utils.py", "vision_api.template"]),
    (("UI", "界面", "点击", "表单"),
     ["tmwebdriver_sop", "ljqCtrl_sop", "ui_detect.py", "adb_ui.py"]),

    # 移动端
    (("手机", "ADB", "安卓", "移动"),
     ["adb_ui.py", "vision_sop"]),

    # 规划/决策
    (("规划", "计划", "复杂任务", "多步骤"),
     ["plan_sop", "brainstorming_sop", "mirothinker_sop", "autonomous_operation_sop"]),
    (("目标", "长期", "后台", "持续优化"),
     ["goal_sop", "goal_hive_sop", "goal_hive_master_duty", "scheduled_task_sop"]),
    (("头脑风暴", "方案", "创意", "分析"),
     ["brainstorming_sop", "whiteboard_protocol", "mirothinker_sop"]),

    # 质量/验证
    (("测试", "验证", "质量", "benchmark"),
     ["arena_sop", "verification_sop", "verify_sop", "self_discriminate_sop",
      "delivery_verification_sop"]),
    (("评审", "审计", "检查"),
     ["review_sop", "code_review_principles", "self_discriminate_sop",
      "discriminator_reality_checker_sop", "discriminator_performance_benchmarker_sop"]),
    (("bug", "错误", "修复", "问题"),
     ["incubator_sop", "verify_sop", "review_sop"]),

    # 代码/开发
    (("脚本", "编程", "开发"),
     ["code_review_principles", "solver_writer_sop", "morphling_sop",
      "understand_project_sop", "prompt_optimization_loop_sop"]),
    (("Git", "版本", "提交"),
     ["github_contribution_sop", "code_review_principles"]),
    (("提示词", "prompt", "优化"),
     ["prompt_optimization_loop_sop", "brainstorming_sop"]),

    # 安全
    (("安全", "密钥", "泄露", "环境变量"),
     ["keychain", "env_sanitizer.py"]),

    # 学习/改进
    (("学习", "训练", "能力"),
     ["adversarial_training_sop", "self_improve_sop", "incubator_sop"]),
    (("自省", "改进", "元分析"),
     ["self_improve_sop", "self_discriminate_sop", "mirothinker_sop"]),

    # 多Agent/协作
    (("协作", "团队", "Agent", "Hive"),
     ["solver_team_index", "solver_architect_sop", "solver_hunter_sop",
      "solver_researcher_sop", "solver_writer_sop", "whiteboard_protocol",
      "goal_hive_sop", "goal_hive_master_duty", "supervisor_sop"]),
    (("判别", "评估", "打分"),
     ["discriminator_reality_checker_sop", "discriminator_performance_benchmarker_sop",
      "discriminator_api_tester_sop", "discriminator_accessibility_auditor_sop"]),

    # 运维/部署
    (("部署", "发布", "上线"),
     ["web_setup_sop", "scheduled_task_sop", "autonomous_operation_sop",
      "incubator_sop"]),
    (("维护", "清理", "内存"),
     ["memory_cleanup_sop", "compaction_recovery_sop", "procmem_scanner_sop",
      "procmem_scanner"]),
    (("定时", "调度", "cron"),
     ["scheduled_task_sop", "autonomous_operation_sop"]),
    (("博客", "blog", "内容"),
     ["blog_maintenance_sop", "web_setup_sop"]),

    # 记忆/知识
    (("记忆", "知识", "存档"),
     ["memory_management_sop", "memory_cleanup_sop", "checklist_sop",
      "checklist_helper", "procmem_scanner_sop"]),
    (("邮件", "AgentMail"),
     ["agentmail_sop"]),

    # 特定框架
    (("Solver", "解题者", "专家"),
     ["solver_team_index", "solver_architect_sop", "solver_hunter_sop",
      "solver_researcher_sop", "solver_writer_sop"]),
    (("框架", "平台", "脚手架"),
     ["incubator_sop", "morphling_sop", "arena_sop"]),
]


def find_sops_by_task(task_desc: str, top_n: int = 5) -> list:
    """根据任务描述推荐SOP"""
    task_lower = task_desc.lower()
    scores = {}  # sop_name -> score

    for keywords, sops in SOP_KNOWLEDGE:
        # 每个关键字命中+1分
        for kw in keywords:
            if kw.lower() in task_lower:
                for sop in sops:
                    scores[sop] = scores.get(sop, 0) + 1

    # 排序
    sorted_sops = sorted(scores.items(), key=lambda x: -x[1])
    return sorted_sops[:top_n]


def scan_memory_sops() -> list:
    """扫描memory目录列出所有可用SOP名"""
    sops = []
    if MEMORY_DIR.exists():
        for f in sorted(MEMORY_DIR.iterdir()):
            if f.suffix in ('.md', '.py') and not f.name.startswith('.'):
                sops.append(f.stem)
    return sops


def list_all_categories() -> list:
    """列出所有分类"""
    seen = {}
    for keywords, sops in SOP_KNOWLEDGE:
        primary = keywords[0]
        for sop in sops:
            if sop not in seen:
                seen[sop] = []
            seen[sop].append(primary)
    return seen


def main():
    pa = argparse.ArgumentParser(
        description="sop_recommender.py — 根据任务描述推荐SOP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/sop_recommender.py "写浏览器自动化脚本"
  python scripts/sop_recommender.py "测试benchmark" --json
  python scripts/sop_recommender.py --list
        """
    )
    pa.add_argument("task", nargs="?", help="任务描述")
    pa.add_argument("--list", action="store_true", help="列出所有SOP分类")
    pa.add_argument("--json", action="store_true", help="JSON格式输出")
    pa.add_argument("--top", type=int, default=5, help="返回前N个推荐")

    args = pa.parse_args()

    if args.list:
        categories = list_all_categories()
        if args.json:
            print(json.dumps(categories, indent=2, ensure_ascii=False))
        else:
            print("=== SOP 分类索引 ===")
            for sop, cats in sorted(categories.items()):
                print(f"  {sop:45s} → {', '.join(cats)}")
        return

    if not args.task:
        pa.print_help()
        sys.exit(1)

    # 推荐
    sops = find_sops_by_task(args.task, args.top)
    all_sops = set(scan_memory_sops())

    result = []
    for sop_name, score in sops:
        exists = sop_name in all_sops or (MEMORY_DIR / f"{sop_name}.md").exists()
        # 检查scripts目录
        if not exists:
            scripts_dir = MEMORY_DIR.parent / "scripts"
            exists = (scripts_dir / sop_name).exists()
        result.append({
            "sop": sop_name,
            "score": score,
            "exists": exists,
        })

    if args.json:
        print(json.dumps({
            "task": args.task,
            "recommendations": result,
        }, indent=2, ensure_ascii=False))
    else:
        print(f"\n📋 任务: {args.task}")
        print(f"推荐SOP ({len(result)} 项):")
        print("=" * 60)
        for r in result:
            marker = "✅" if r["exists"] else "❌"
            print(f"  {marker} {r['sop']:40s} (匹配度: {r['score']})")
        print()
        # 提示可用SOP总数
        print(f"提示: memory/ 下共有 {len(all_sops)} 个可用SOP")
        print("      使用 --list 查看所有分类\n")


if __name__ == "__main__":
    main()
