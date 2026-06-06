#!/usr/bin/env python3
"""
service_health_dashboard.py — Service 健康状态每日看板生成器

读取 temp/service_health.jsonl → rich_renderer排版 → 输出到终端 + HTML

用法:
    python3 scripts/service_health_dashboard.py                   # 打印看板
    python3 scripts/service_health_dashboard.py --html-only       # 仅保存HTML
    python3 scripts/service_health_dashboard.py --clip            # 追加到clip.md
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from memory.tools.rich_renderer import render_summary

DATA_FILE = BASE / 'temp/service_health.jsonl'
HTML_FILE = BASE / 'temp/service_health_dashboard.html'

def load_entries():
    entries = []
    for line in DATA_FILE.read_text().strip().splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries

def build_dashboard(entries):
    services = {}
    for entry in entries:
        for svc in entry.get('services', []):
            name = svc['name']
            if name not in services:
                services[name] = {'up': 0, 'total': 0, 'latencies': [], 'port': svc.get('port')}
            services[name]['total'] += 1
            if svc.get('up'):
                services[name]['up'] += 1
            if svc.get('latency_ms') is not None:
                services[name]['latencies'].append(svc['latency_ms'])

    metrics = {}
    overall_up = sum(s['up'] for s in services.values())
    overall_total = sum(s['total'] for s in services.values())
    metrics['总体可用率'] = f"{overall_up/overall_total*100:.1f}%"
    metrics['采样点数'] = len(entries)
    metrics['服务数'] = len(services)
    metrics['周期'] = f"{entries[0]['timestamp'][:16]} ~ {entries[-1]['timestamp'][:16]}"

    recommendations = []
    for name, svc in sorted(services.items()):
        uptime = svc['up'] / svc['total'] * 100
        avg_lat = sum(svc['latencies']) / len(svc['latencies']) if svc['latencies'] else 0
        max_lat = max(svc['latencies']) if svc['latencies'] else 0
        status = "✅" if uptime == 100 else "⚠️"
        metrics[f"{status} {name} (:{svc['port']})"] = f"可用率 {uptime:.0f}% | avg={avg_lat:.1f}ms max={max_lat:.1f}ms"

    if not recommendations:
        recommendations.append("✅ 全部服务健康，无需处理")

    return metrics, recommendations, services, entries, overall_up, overall_total

def save_html(entries, services, overall_up, overall_total, recommendations):
    ps = 'font-family'
    pt = 'window'
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Service Health Dashboard</title>
<style>
body {{ {ps}: monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
h1 {{ color: #00d4ff; }} table {{ border-collapse: collapse; width: 100%; }}
th {{ background: #16213e; color: #0f3460; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #333; }}
.ok {{ color: #4caf50; }} .warn {{ color: #ff9800; }}
</style></head><body>
<h1>📊 Service 健康状态每日摘要</h1>
<p>周期: {entries[0]['timestamp'][:16]} ~ {entries[-1]['timestamp'][:16]} | 采样: {len(entries)} 次 | 服务: {len(services)} 个</p>
<table>
<tr><th>状态</th><th>服务</th><th>端口</th><th>可用率</th><th>平均延迟</th><th>最大延迟</th></tr>"""

    for name, svc in sorted(services.items()):
        uptime = svc['up'] / svc['total'] * 100
        avg_lat = sum(svc['latencies']) / len(svc['latencies']) if svc['latencies'] else 0
        max_lat = max(svc['latencies']) if svc['latencies'] else 0
        status_icon = "✅" if uptime == 100 else "⚠️"
        cls = "ok" if uptime == 100 else "warn"
        html += f'<tr><td class="{cls}">{status_icon}</td><td>{name}</td><td>{svc["port"]}</td><td>{uptime:.0f}%</td><td>{avg_lat:.1f}ms</td><td>{max_lat:.1f}ms</td></tr>'

    html += f"""</table>
<p>总体可用率: {overall_up/overall_total*100:.1f}% ({overall_up}/{overall_total})</p>
<p>建议: {"全部健康" if not recommendations else ' | '.join(r for r in recommendations)}</p>
<p><small>生成时间: {entries[-1]['timestamp'][:19]}</small></p>
</body></html>"""
    HTML_FILE.write_text(html)
    return html

def main():
    entries = load_entries()
    metrics, recommendations, services, _, overall_up, overall_total = build_dashboard(entries)

    if '--html-only' in sys.argv:
        save_html(entries, services, overall_up, overall_total, recommendations)
        print(f"✅ HTML看板已保存: {HTML_FILE}")
        return

    render_summary("📊 Service 健康状态每日摘要", metrics=metrics, recommendations=recommendations, border_style="cyan")
    save_html(entries, services, overall_up, overall_total, recommendations)
    print(f"\n✅ HTML看板已保存: {HTML_FILE}")

    if '--clip' in sys.argv:
        clip = BASE / 'temp/clip.md'
        clip.write_text(f"<!-- {metrics['周期']} -->\n" + json.dumps(metrics, ensure_ascii=False, indent=2))
        print(f"✅ 已写入 {clip}")

if __name__ == '__main__':
    main()
