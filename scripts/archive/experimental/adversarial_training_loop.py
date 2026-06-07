#!/usr/bin/env python3
"""
adversarial_training_loop.py — 对抗训练循环自动化 🔄

运行 adversarial_challenge.py, 检测失败, 更新训练日志,
并将失败场景记录为"discriminator更新"(下次更严格).

用法:
  python scripts/adversarial_training_loop.py              # 运行一次
  python scripts/adversarial_training_loop.py --report     # 只查看历史
  python scripts/adversarial_training_loop.py --schedule   # 生成调度任务配置
"""

import json, os, sys, subprocess
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"
TEMP = BASE / "temp"
CHALLENGE = SCRIPTS / "adversarial_challenge.py"
RESULT_FILE = TEMP / "adversarial_challenge_result.json"
LOG_FILE = TEMP / "adversarial_training_log.json"
SCHEDULE_FILE = BASE / "sche_tasks" / "adversarial_training.json"


def run_challenge() -> dict:
    """运行 adversarial_challenge.py, 返回结果"""
    if not CHALLENGE.exists():
        print(f"❌ 找不到 {CHALLENGE}")
        return {"error": "challenge script not found"}

    print(f"🚀 运行对抗测试: {CHALLENGE}")
    result = subprocess.run(
        [sys.executable, str(CHALLENGE)],
        capture_output=True, text=True, timeout=600
    )
    print(result.stdout)

    if result.returncode != 0:
        print(f"⚠️  退出码: {result.returncode} (有失败)")
        if result.stderr:
            print(f"stderr: {result.stderr[:500]}")
    else:
        print("✅ 全部通过")

    # 读取结果文件
    if RESULT_FILE.exists():
        with open(RESULT_FILE) as f:
            data = json.load(f)
        return data

    return {
        "date": datetime.now().isoformat(),
        "total": 0,
        "passed": 0,
        "failed": 0,
        "results": [],
        "note": "结果文件未生成, 使用退出码推断",
        "exit_code": result.returncode
    }


def load_history() -> list:
    """加载历史训练日志"""
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except (json.JSONDecodeError, Exception):
            return []
    return []


def save_history(history: list):
    """保存历史训练日志"""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


def update_discriminator(result: dict) -> list:
    """根据失败结果生成 discriminator 更新建议"""
    updates = []
    for r in result.get("results", []):
        if not r.get("passed", True):
            scenario = r.get("scenario", "unknown")
            test_name = r.get("test", "unknown")
            updates.append({
                "scenario": scenario,
                "test": test_name,
                "failed_detail": r.get("detail", ""),
                "suggested_action": f"增强 {scenario} 场景的 {test_name} 测试边界",
                "timestamp": datetime.now().isoformat()
            })
    return updates


def train():
    """执行一轮训练"""
    print("=" * 60)
    print(f"  对抗训练循环")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 运行挑战
    result = run_challenge()
    if "error" in result:
        print(f"❌ 错误: {result['error']}")
        return

    # 加载历史
    history = load_history()

    # 生成 discriminator 更新
    updates = update_discriminator(result)

    # 构造本轮记录
    record = {
        "date": datetime.now().isoformat(),
        "total": result.get("total", 0),
        "passed": result.get("passed", 0),
        "failed": result.get("failed", 0),
        "pass_rate": round(result.get("passed", 0) / max(result.get("total", 1), 1) * 100, 1),
        "discriminator_updates": updates,
        "updates_count": len(updates)
    }
    history.append(record)

    # 只保留最近 100 条
    if len(history) > 100:
        history = history[-100:]

    save_history(history)

    # 输出摘要
    print(f"\n{'='*60}")
    print(f"  本轮: {record['passed']}/{record['total']} 通过 ({record['pass_rate']}%)")
    if updates:
        print(f"  🎯 discriminator更新: {len(updates)} 项")
        for u in updates:
            print(f"     - [{u['scenario']}] {u['test']}")
    else:
        print(f"  ✅ 无需更新")
    print(f"{'='*60}")

    # 输出历史趋势
    if len(history) >= 2:
        rates = [h.get("pass_rate", 0) for h in history[-5:]]
        print(f"  最近{len(rates)}轮通过率: {rates}")
        if len(rates) >= 2 and rates[-1] >= rates[-2]:
            print(f"  📈 趋势: 上升 ({(rates[-1] - rates[-2]):+.1f}%)")
        elif len(rates) >= 2:
            print(f"  📉 趋势: 下降 ({(rates[-1] - rates[-2]):+.1f}%)")

    return record


def show_report():
    """显示训练历史报告"""
    history = load_history()
    if not history:
        print("📭 无训练记录")
        return

    print(f"\n{'='*60}")
    print(f"  对抗训练历史报告")
    print(f"  共 {len(history)} 轮训练")
    print(f"{'='*60}")

    for i, h in enumerate(history[-10:], 1):
        date = h.get("date", "?")[:19]
        passed = h.get("passed", 0)
        total = h.get("total", 0)
        rate = h.get("pass_rate", 0)
        updates = h.get("updates_count", 0)
        marker = "✅" if rate >= 90 else "⚠️" if rate >= 70 else "❌"
        print(f"  #{len(history)-len(history)+i:2d} {marker} {date} | {passed}/{total} ({rate}%) | 更新: {updates}")

    latest = history[-1]
    print(f"\n  最新一轮:")
    print(f"    通过率: {latest.get('pass_rate', 0)}%")
    print(f"    更新: {latest.get('updates_count', 0)} 项")
    if latest.get("updates_count", 0) > 0:
        for u in latest.get("discriminator_updates", [])[:3]:
            print(f"      - [{u['scenario']}] {u['test']}")


def create_schedule():
    """创建调度任务配置"""
    config = {
        "schedule": "06:00",
        "repeat": "daily",
        "enabled": True,
        "prompt": "执行对抗训练循环: 运行adversarial_challenge.py套件, 失败自动记录discriminator更新",
        "max_delay_hours": 6,
        "commands": [
            f"python3 {CHALLENGE}",
            f"python3 {SCRIPTS / 'adversarial_training_loop.py'}"
        ]
    }
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    print(f"✅ 调度任务配置已生成: {SCHEDULE_FILE}")
    return config


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="对抗训练循环")
    parser.add_argument("--report", action="store_true", help="查看历史报告")
    parser.add_argument("--schedule", action="store_true", help="生成调度任务配置")
    args = parser.parse_args()

    if args.report:
        show_report()
    elif args.schedule:
        create_schedule()
    else:
        train()
