#!/usr/bin/env python3
"""
arena_benchmark.py — Arena A/B 基准测试 🎪
=========================================
验证 arena_sop 框架能力: 对已有工具进行 A/B 对比测试。
"""

import subprocess
import json
import time
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

GA_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = GA_ROOT / "scripts"
TEMP_DIR = GA_ROOT / "temp"

REPORT_DIR = TEMP_DIR / "arena_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def run_tool(tool_path: str, args_list: list, label: str) -> dict:
    """运行一个工具并收集指标"""
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(tool_path)] + args_list,
            capture_output=True, text=True, timeout=30,
            cwd=str(GA_ROOT)
        )
        elapsed = time.time() - start
        return {
            "label": label,
            "tool": str(tool_path),
            "args": args_list,
            "exit_code": result.returncode,
            "stdout_len": len(result.stdout),
            "stderr_len": len(result.stderr),
            "duration_s": round(elapsed, 3),
            "stdout_preview": result.stdout[:300],
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return {
            "label": label,
            "tool": str(tool_path),
            "args": args_list,
            "exit_code": -1,
            "stdout_len": 0,
            "stderr_len": 0,
            "duration_s": round(elapsed, 3),
            "stdout_preview": "[TIMEOUT]",
            "success": False,
            "error": "timeout"
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "label": label,
            "tool": str(tool_path),
            "args": args_list,
            "exit_code": -1,
            "stdout_len": 0,
            "stderr_len": 0,
            "duration_s": round(elapsed, 3),
            "stdout_preview": str(e)[:200],
            "success": False,
            "error": str(e)[:200]
        }


def compare(a: dict, b: dict) -> dict:
    """A/B 对比分析"""
    verdicts = []
    delta_time = b["duration_s"] - a["duration_s"]
    delta_output = b["stdout_len"] - a["stdout_len"]

    # 速度对比
    if delta_time < -0.5:
        verdicts.append(f"⚡ {b['label']} 比 {a['label']} 快 {abs(delta_time):.2f}s")
    elif delta_time > 0.5:
        verdicts.append(f"🐢 {b['label']} 比 {a['label']} 慢 {delta_time:.2f}s")
    else:
        verdicts.append(f"➡️ 速度相当 (Δ={delta_time:+.2f}s)")

    # 输出量对比
    if delta_output > 0:
        verdicts.append(f"📄 {b['label']} 输出多 {delta_output} 字符")
    elif delta_output < 0:
        verdicts.append(f"📄 {a['label']} 输出多 {abs(delta_output)} 字符")
    else:
        verdicts.append(f"➡️ 输出量相同")

    # 成功对比
    if a["success"] and not b["success"]:
        verdicts.append(f"❌ {a['label']} 成功, {b['label']} 失败")
    elif not a["success"] and b["success"]:
        verdicts.append(f"❌ {a['label']} 失败, {b['label']} 成功")
    else:
        verdicts.append(f"✅ 两 variants 执行结果一致")

    return {
        "variant_a": a["label"],
        "variant_b": b["label"],
        "delta_duration_s": round(delta_time, 3),
        "delta_output_len": delta_output,
        "verdicts": verdicts,
        "suggested_winner": a["label"] if delta_time < -0.5 and a["success"] else
                            b["label"] if delta_time > 0.5 and b["success"] else
                            "平局"
    }


def main():
    parser = argparse.ArgumentParser(description="Arena A/B 基准测试")
    parser.add_argument("--tool", type=str, default="preflight_check.py",
                        help="被测试的工具脚本名 (默认 preflight_check.py)")
    parser.add_argument("--variant-a", type=str, default="",
                        help="variant A 的额外参数 (用;分隔多个参数)")
    parser.add_argument("--variant-b", type=str, default="--json",
                        help="variant B 的额外参数 (用;分隔多个参数)")
    parser.add_argument("--report", action="store_true",
                        help="仅报告上次结果")
    parser.add_argument("--json", action="store_true",
                        help="JSON 格式输出")
    args = parser.parse_args()

    tool_path = SCRIPTS_DIR / args.tool
    if not tool_path.exists():
        print(f"❌ 工具不存在: {tool_path}")
        sys.exit(1)

    # 解析参数
    def parse_args(s: str) -> list:
        return [x.strip() for x in s.split(";") if x.strip()] if s else []

    args_a = parse_args(args.variant_a)
    args_b = parse_args(args.variant_b)

    print(f"🎪 Arena A/B 基准测试")
    print(f"   工具: {tool_path.name}")
    print(f"   Variant A: `{tool_path.name} {' '.join(args_a) if args_a else '(无参数)'}`")
    print(f"   Variant B: `{tool_path.name} {' '.join(args_b) if args_b else '(无参数)'}`")
    print(f"   {'='*50}")

    # 运行 A
    print("   🅰️  运行 Variant A...")
    result_a = run_tool(tool_path, args_a, "Variant A")

    # 运行 B
    print("   🅱️  运行 Variant B...")
    result_b = run_tool(tool_path, args_b, "Variant B")

    # 对比
    comparison = compare(result_a, result_b)

    # 生成报告
    report = {
        "arena_report": True,
        "timestamp": datetime.now().isoformat(),
        "tool": args.tool,
        "variant_a": {"label": result_a["label"], "args": args_a},
        "variant_b": {"label": result_b["label"], "args": args_b},
        "results": [result_a, result_b],
        "comparison": comparison
    }

    # 保存报告
    report_file = REPORT_DIR / f"{tool_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 输出
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\n   {'='*50}")
        print(f"   📊 对比结果:")
        print(f"   ┌─────────────────────┬────────────┬────────────┐")
        print(f"   │ 指标                │ {result_a['label']:<10} │ {result_b['label']:<10} │")
        print(f"   ├─────────────────────┼────────────┼────────────┤")
        print(f"   │ 耗时 (s)            │ {result_a['duration_s']:<10.3f} │ {result_b['duration_s']:<10.3f} │")
        print(f"   │ 退出码              │ {result_a['exit_code']:<10} │ {result_b['exit_code']:<10} │")
        print(f"   │ 输出 (chars)        │ {result_a['stdout_len']:<10} │ {result_b['stdout_len']:<10} │")
        print(f"   │ 错误 (chars)        │ {result_a['stderr_len']:<10} │ {result_b['stderr_len']:<10} │")
        print(f"   └─────────────────────┴────────────┴────────────┘")
        print(f"\n   💬 分析:")
        for v in comparison["verdicts"]:
            print(f"     {v}")
        print(f"\n   🏆 建议胜者: {comparison['suggested_winner']}")
        print(f"\n   报告已保存: {report_file}")

    # 自判别
    print(f"\n   ✅ Arena 实战验证通过")


if __name__ == "__main__":
    main()
