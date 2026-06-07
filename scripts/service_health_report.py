#!/usr/bin/env python3
"""service_health_report.py — 从service_health.jsonl生成自动健康报告

用法:
  python3 service_health_report.py                     # 输出文本报告
  python3 service_health_report.py --json              # JSON格式输出
  python3 service_health_report.py --min-samples 24    # 数据不足24跳过低报告

依赖: 无 (纯stdlib)
数据源: temp/service_health.jsonl
"""
import json, sys, os, statistics, argparse
from datetime import datetime, timedelta

JSONL_PATH = os.path.join(os.path.dirname(__file__) or '.', '..', 'temp', 'service_health.jsonl')
ALERT_THRESHOLD_LATENCY_MS = 100  # 单次延迟超过此值报警
ALERT_THRESHOLD_LATENCY_CHANGE = 0.5  # 比均值高50%报警

def load_records(path=JSONL_PATH):
    if not os.path.exists(path):
        print(f"⚠️ 未找到数据: {path}")
        sys.exit(1)
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]

def compute(records, min_samples=24):
    if len(records) < min_samples:
        return {"status": "insufficient", "samples": len(records), "needed": min_samples}
    
    # 时间范围
    t0 = datetime.strptime(records[0]['timestamp'], '%Y-%m-%d %H:%M:%S')
    t1 = datetime.strptime(records[-1]['timestamp'], '%Y-%m-%d %H:%M:%S')
    
    # 服务列表
    services = set()
    for r in records:
        for s in r['services']:
            services.add(s['name'])
    
    report = {
        "status": "ok",
        "time_range": {"from": str(t0), "to": str(t1), "hours": round((t1 - t0).total_seconds() / 3600, 1)},
        "samples": len(records),
        "services": {}
    }
    
    for svc in sorted(services):
        latencies = []
        ups = []
        for r in records:
            for s in r['services']:
                if s['name'] == svc:
                    latencies.append(s['latency_ms'])
                    ups.append(s['up'])
                    break
        
        avg_lat = statistics.mean(latencies) if latencies else 0
        max_lat = max(latencies) if latencies else 0
        uptime = sum(ups) / len(ups) * 100 if ups else 0
        
        # 检测退化: 最后1/3 vs 前2/3
        mid = len(latencies) // 3
        recent_avg = statistics.mean(latencies[-mid:]) if mid > 1 else avg_lat
        early_avg = statistics.mean(latencies[:mid]) if mid > 1 else avg_lat
        drift = (recent_avg - early_avg) / early_avg * 100 if early_avg > 0 else 0
        
        alerts = []
        if uptime < 100:
            alerts.append(f"宕机{100-uptime:.0f}%")
        if max_lat > ALERT_THRESHOLD_LATENCY_MS:
            alerts.append(f"峰值延迟{max_lat:.0f}ms")
        if drift > ALERT_THRESHOLD_LATENCY_CHANGE * 100:
            alerts.append(f"上升趋势+{drift:.0f}%")
        
        report["services"][svc] = {
            "avg_latency_ms": round(avg_lat, 1),
            "max_latency_ms": max_lat,
            "uptime_pct": round(uptime, 1),
            "drift_pct": round(drift, 1),
            "alerts": alerts
        }
    
    return report

def format_report(report):
    lines = [f"# 📊 服务健康报告 (auto-generated)"]
    
    if report["status"] == "insufficient":
        lines.append(f"**数据不足**: 当前{report['samples']}条, 需≥{report['needed']}条(≈{report['needed']*5//60}h)")
        lines.append(f"等待数据积累后重新生成。")
        return "\n".join(lines)
    
    tr = report["time_range"]
    lines.append(f"**时间**: {tr['from']} → {tr['to']} ({tr['hours']}h)")
    lines.append(f"**采样**: {report['samples']}条\n")
    
    has_alerts = any(s['alerts'] for s in report['services'].values())
    
    for svc, info in sorted(report['services'].items()):
        status_icon = "🔴" if info['alerts'] else "🟢"
        line = f"{status_icon} **{svc}**: avg={info['avg_latency_ms']}ms max={info['max_latency_ms']}ms uptime={info['uptime_pct']}%"
        if info['drift_pct'] != 0:
            line += f" drift={info['drift_pct']:+.0f}%"
        lines.append(line)
        if info['alerts']:
            for a in info['alerts']:
                lines.append(f"    ⚠️ {a}")
    
    if not has_alerts:
        lines.append("\n✅ 所有服务健康，无异常。")
    else:
        lines.append(f"\n⚠️ {sum(len(s['alerts']) for s in report['services'].values())}项告警")
    
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--min-samples', type=int, default=24, help='最小样本数')
    parser.add_argument('--path', default=JSONL_PATH, help='数据路径')
    args = parser.parse_args()
    
    records = load_records(args.path)
    report = compute(records, args.min_samples)
    
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

if __name__ == '__main__':
    main()
