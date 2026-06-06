#!/usr/bin/env python3
"""
health_dashboard.py — 系统健康一体化仪表盘 (v111#1)

聚合: system状态 + 服务状态(service_health.jsonl) + 内存压力 + benchmark趋势 + 健康日志
用法:
    python3 scripts/health_dashboard.py                  # 打印仪表盘
    python3 scripts/health_dashboard.py --output report  # 追加到报告文件
"""

import subprocess, json, os, sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / 'memory/tools'))
sys.path.insert(0, str(BASE / 'memory'))

from rich_renderer import render_summary, render_table, render_panel

# ── 工具函数 ──────────────────────────────────────────────

def run(cmd, timeout=5):
    """运行命令返回stdout, 超时/异常返回空"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def mem_usage():
    """内存使用摘要"""
    mem = {}
    for line in run(["free", "-h"]).splitlines():
        if line.startswith("Mem:"):
            parts = line.split()
            mem = {"total": parts[1], "used": parts[2], "free": parts[3], "avail": parts[6]}
    return mem

def disk_usage():
    """磁盘使用摘要"""
    disk = {}
    for line in run(["df", "-h", "/"]).splitlines():
        if line.startswith("/"):
            parts = line.split()
            disk = {"size": parts[1], "used": parts[2], "avail": parts[3], "use_pct": parts[4]}
    return disk

def load_avg():
    """CPU负载"""
    uptime = run(["uptime"])
    # Extract load average
    if "load average:" in uptime:
        loads = uptime.split("load average:")[1].strip()
        return loads
    return uptime

def uptime_str():
    """系统运行时间"""
    u = run(["uptime", "-p"]).replace("up ", "")
    return u

def process_count():
    """关键进程数"""
    procs = {}
    for name, pattern in [
        ("fsapp", "python3.*frontends/fsapp"),
        ("scheduler", "agentmain.*reflect.*scheduler"),
        ("openllm", "openllm"),
        ("nanobot", "nanobot"),
    ]:
        out = run(["pgrep", "-f", pattern, "-c"])
        procs[name] = int(out) if out.isdigit() else 0
    return procs

def service_status():
    """从service_health.jsonl读取最新服务状态"""
    fpath = BASE / 'temp/service_health.jsonl'
    if not fpath.exists():
        return []
    entries = [json.loads(l) for l in fpath.read_text().strip().splitlines() if l.strip()]
    if not entries:
        return []
    latest = entries[-1]
    services = latest.get("services", [])
    return services

def benchmark_summary():
    """benchmark趋势摘要"""
    fpath = BASE / 'temp/autonomous_reports/benchmark_trend.json'
    if not fpath.exists():
        return None
    try:
        data = json.loads(fpath.read_text())
        runs = data.get("runs", [])
        if not runs:
            return None
        # Get latest and extract key metrics
        latest = runs[-1] if isinstance(runs, list) else runs
        if isinstance(latest, dict):
            return {
                "total_runs": len(runs),
                "last_run": latest.get("timestamp", "N/A"),
                "last_score": latest.get("score", "N/A"),
            }
    except Exception:
        return None
    return None

def memory_pressure():
    """内存压力检测"""
    fpath = BASE / 'scripts/memory_pressure_monitor.py'
    if fpath.exists():
        out = run(["python3", str(fpath), "--oneshot"], timeout=10)
        # Extract key lines (last 5)
        lines = [l for l in out.splitlines() if l.strip()]
        return lines[-5:] if len(lines) > 5 else lines
    return []

def recent_health_logs(n=5):
    """最近健康日志中的警告"""
    fpath = BASE / 'temp/health_unified.log'
    if not fpath.exists():
        return []
    lines = fpath.read_text().splitlines()
    # Look for lines with ⚠️ or ❌
    issues = [l for l in lines if "⚠️" in l or "❌" in l]
    return issues[-n:] if issues else lines[-3:] if lines else []

# ── 仪表盘主函数 ──────────────────────────────────────────

def build_dashboard(output_to_report=False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 1. 系统状态 ──
    mem = mem_usage()
    disk = disk_usage()
    load = load_avg()
    upt = uptime_str()
    procs = process_count()

    sys_metrics = {}
    if mem:
        sys_metrics["内存"] = f"{mem.get('used','?')} / {mem.get('total','?')} (avail: {mem.get('avail','?')})"
    if disk:
        sys_metrics["磁盘"] = f"{disk.get('used','?')} / {disk.get('size','?')} ({disk.get('use_pct','?')})"
    if load:
        sys_metrics["负载"] = load
    if upt:
        sys_metrics["运行时间"] = upt
    for name, count in procs.items():
        sys_metrics[f"进程/{name}"] = str(count)

    # ── 2. 服务状态 ──
    services = service_status()
    svc_rows = []
    svc_all_up = True
    for svc in services:
        name = svc.get("name", "?")
        up = svc.get("up", False)
        latency = svc.get("latency_ms", "N/A")
        if up:
            lat_str = f"{latency}ms" if isinstance(latency, (int, float)) else str(latency)
            svc_rows.append([name, "✅ UP", lat_str])
        else:
            svc_all_up = False
            err = svc.get("error", "unknown")
            svc_rows.append([name, f"❌ DOWN", err[:30]])

    # ── 3. Benchmark趋势 ──
    bench = benchmark_summary()

    # ── 4. 内存压力 ──
    pressure = memory_pressure()

    # ── 5. 健康日志警告 ──
    issues = recent_health_logs(5)

    # ── 渲染 ──
    print()  # spacing
    render_summary(
        f"🩺 系统健康仪表盘 — {now}",
        metrics=sys_metrics,
        recommendations=[],
        width=80,
    )

    # 服务状态表
    if svc_rows:
        render_table(
            ["服务", "状态", "延迟/错误"],
            svc_rows,
            title=f"服务状态 (共{len(services)}个, {'全部正常' if svc_all_up else '部分异常'})",
            width=80,
        )
    else:
        render_panel("⚠️ 无服务状态数据 (service_health.jsonl 为空)", style="warn", width=80)

    # Benchmark
    if bench:
        render_panel(
            f"📊 Benchmark: 共{bench['total_runs']}次 | 最近: {bench.get('last_run','?')} | 评分: {bench.get('last_score','?')}",
            style="info", width=80,
        )

    # 内存压力
    if pressure:
        p_text = "\n".join(pressure)
        render_panel(f"🧠 内存压力监测:\n{p_text}", style="info", width=80)

    # 健康日志警告
    if issues:
        issue_text = "\n".join(issues)
        style = "warn" if any("❌" in l for l in issues) else "info"
        render_panel(f"📋 最近健康日志异常 ({len(issues)}条):\n{issue_text}", style=style, width=80)
    else:
        render_panel("✅ 最近健康日志无异常", style="success", width=80)

    # 尾部
    render_panel("💡 提示: 使用 --output report 追加到报告文件", style="info", width=80)

    # 可选: 追加到报告
    if output_to_report:
        report_dir = BASE / 'temp/autonomous_reports'
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"health_dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        with open(report_path, 'a') as f:
            f.write(f"\n## 健康仪表盘快照 ({now})\n\n")
            if sys_metrics:
                f.write("### 系统状态\n")
                for k, v in sys_metrics.items():
                    f.write(f"- {k}: {v}\n")
            if svc_rows:
                f.write("\n### 服务状态\n")
                f.write("| 服务 | 状态 | 延迟/错误 |\n")
                f.write("|------|------|----------|\n")
                for row in svc_rows:
                    f.write(f"| {' | '.join(row)} |\n")
            if bench:
                f.write(f"\n### Benchmark\n- 总执行: {bench['total_runs']}\n")
                f.write(f"- 最近: {bench.get('last_run','?')}\n")
                f.write(f"- 评分: {bench.get('last_score','?')}\n")
            if issues:
                f.write(f"\n### 健康日志异常\n```\n{chr(10).join(issues)}\n```\n")
            f.write("\n---\n")
        print(f"\n📝 报告已追加到: {report_path}")

    return sys_metrics, svc_rows, bench

if __name__ == "__main__":
    output_report = "--output" in sys.argv and "report" in sys.argv
    build_dashboard(output_to_report=output_report)
