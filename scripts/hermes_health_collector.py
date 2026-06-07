#!/usr/bin/env python3
"""
Hermes Health Collector - 延迟/错误率/RSS 采集
用法:
  python3 scripts/hermes_health_collector.py           # 采集一次并追加到JSONL
  python3 scripts/hermes_health_collector.py --report  # 生成HTML状态页
  python3 scripts/hermes_health_collector.py --cron    # 采集+自动报告
"""
import json, os, subprocess, sys, time, glob
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE, 'temp/hermes_health.jsonl')
HTML_FILE = os.path.join(BASE, 'temp/hermes_status.html')
HERMES_URL = 'http://localhost:11343'
MODEL = 'deepseek/deepseek-v4-flash'

def collect_hermes_metrics():
    """采集一次Hermes指标"""
    now = datetime.utcnow()
    ts = now.strftime('%Y-%m-%d %H:%M:%S')
    unix_ts = time.time()
    
    metrics = {
        'timestamp': ts,
        'unix_ts': unix_ts,
        'api_healthy': False,
        'latency_ms': None,
        'error': None,
        'processes': []
    }
    
    # 1. 测试API健康/延迟 (非streaming, 1 token)
    try:
        start = time.time()
        r = subprocess.run(
            ['curl', '-s', '-w', '\n%{http_code}', 
             f'{HERMES_URL}/v1/chat/completions',
             '-X', 'POST',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps({
                 'model': MODEL,
                 'messages': [{'role': 'user', 'content': 'ping'}],
                 'max_tokens': 1,
                 'stream': False
             }),
             '--connect-timeout', '5', '--max-time', '15'],
            capture_output=True, text=True, timeout=20
        )
        latency = time.time() - start
        parts = r.stdout.strip().rsplit('\n', 1)
        if len(parts) == 2:
            body, code = parts
            metrics['latency_ms'] = round(latency * 1000, 1)
            metrics['api_healthy'] = code == '200'
            if code != '200':
                metrics['error'] = f'HTTP_{code}'
    except Exception as e:
        metrics['error'] = str(e)[:100]
    
    # 2. 检查/health端点
    try:
        r = subprocess.run(
            ['curl', '-s', '-w', '\n%{http_code}', f'{HERMES_URL}/health',
             '--connect-timeout', '3', '--max-time', '5'],
            capture_output=True, text=True, timeout=8
        )
        parts = r.stdout.strip().rsplit('\n', 1)
        if len(parts) == 2:
            metrics['health_endpoint'] = parts[1]
    except:
        metrics['health_endpoint'] = 'error'
    
    # 3. 采集进程RSS
    try:
        r = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
        hermes_procs = []
        for line in r.stdout.split('\n'):
            if 'hermes' in line.lower():
                parts = line.split()
                if len(parts) >= 11:
                    hermes_procs.append({
                        'pid': parts[1],
                        'cpu_pct': parts[2],
                        'mem_pct': parts[3],
                        'rss_mb': round(int(parts[5]) / 1024, 1) if parts[5].isdigit() else 0,
                        'cmd': ' '.join(parts[10:])[:80]
                    })
        metrics['processes'] = hermes_procs
    except:
        pass
    
    # 4. 系统负载快照
    try:
        with open('/proc/loadavg') as f:
            loads = f.read().strip().split()[:3]
            metrics['load'] = [float(x) for x in loads]
    except:
        pass
    
    return metrics


def save_metrics(metrics):
    """追加到JSONL"""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, 'a') as f:
        f.write(json.dumps(metrics) + '\n')
    print(f"✅ Recorded at {metrics['timestamp']}")


def load_history(n=100):
    """读取历史JSONL"""
    if not os.path.isfile(DATA_FILE):
        return []
    with open(DATA_FILE) as f:
        lines = f.readlines()
    records = []
    for line in lines[-n:]:
        try:
            records.append(json.loads(line.strip()))
        except:
            pass
    return records


def generate_html(records):
    """生成HTML状态页"""
    latest = records[-1] if records else {}
    
    # 计算统计
    if len(records) >= 2:
        latencies = [r.get('latency_ms') for r in records if r.get('latency_ms') is not None]
        errors = [r for r in records if not r.get('api_healthy')]
        avg_latency = sum(latencies)/len(latencies) if latencies else 0
        max_latency = max(latencies) if latencies else 0
        error_rate = len(errors)/len(records)*100 if records else 0
    else:
        avg_latency = max_latency = error_rate = 0
        latencies = []
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hermes 健康状态页</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background: #0d1117; color: #e6edf3; padding: 20px; }}
  h1 {{ font-size: 1.5em; margin-bottom: 16px; color: #58a6ff; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }}
  .card h3 {{ font-size: 0.85em; color: #8b949e; margin-bottom: 4px; }}
  .card .value {{ font-size: 1.8em; font-weight: 700; }}
  .good {{ color: #3fb950; }}
  .warn {{ color: #d29922; }}
  .bad {{ color: #f85149; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #30363d; }}
  th {{ color: #8b949e; font-weight: 500; }}
  .footer {{ margin-top: 20px; font-size: 0.8em; color: #484f58; }}
  .chart-bar {{ display: inline-block; height: 8px; border-radius: 4px; margin-right: 4px; }}
  .proc-table {{ margin-top: 16px; }}
</style>
</head>
<body>
<h1>🤖 Hermes 健康状态页</h1>

<div class="grid">
  <div class="card">
    <h3>API 状态</h3>
    <div class="value {'good' if latest.get('api_healthy') else 'bad'}">{'🟢 正常' if latest.get('api_healthy') else '🔴 异常'}</div>
  </div>
  <div class="card">
    <h3>延迟 (最近)</h3>
    <div class="value {'good' if (latest.get('latency_ms') or 0) < 2000 else 'warn'}">{latest.get('latency_ms', 'N/A')} ms</div>
  </div>
  <div class="card">
    <h3>平均延迟 ({len(records)}次)</h3>
    <div class="value">{avg_latency:.0f} ms</div>
  </div>
  <div class="card">
    <h3>错误率</h3>
    <div class="value {'good' if error_rate < 5 else 'warn' if error_rate < 20 else 'bad'}">{error_rate:.1f}%</div>
  </div>
</div>

<div class="card">
  <h3>延迟趋势 (最近{len(records)}次)</h3>
  <div style="display: flex; align-items: flex-end; gap: 2px; height: 80px; margin-top: 8px;">
"""
    # 简单条形图
    if latencies:
        max_l = max(latencies) or 1
        for l in latencies[-60:]:  # 最多60条
            h = max(3, int(l/max_l * 72))
            color = '#3fb950' if l < 2000 else '#d29922' if l < 5000 else '#f85149'
            html += f'    <div style="width: 8px; height: {h}px; background: {color}; border-radius: 2px;" title="{l:.0f}ms"></div>\n'
    
    html += """  </div>
</div>

<div class="card proc-table">
  <h3>Hermes 进程</h3>
  <table>
    <tr><th>PID</th><th>CPU%</th><th>MEM%</th><th>RSS</th><th>命令</th></tr>
"""
    for p in latest.get('processes', []):
        html += f"""    <tr><td>{p['pid']}</td><td>{p['cpu_pct']}</td><td>{p['mem_pct']}</td><td>{p['rss_mb']}MB</td><td style="font-size:0.8em;color:#8b949e">{p['cmd'][:60]}</td></tr>\n"""
    
    html += """  </table>
</div>

<div class="card" style="margin-top:12px;">
  <h3>系统负载</h3>
  <p>"""
    loads = latest.get('load', [])
    if loads:
        html += f'1min: {loads[0]:.2f} / 5min: {loads[1]:.2f} / 15min: {loads[2]:.2f}'
    html += f"""</p>
  <p style="font-size:0.8em;color:#8b949e">最后采集: {latest.get('timestamp', 'N/A')}</p>
</div>

<div class="footer">
  由 GenericAgent Hermes Health Collector 自动采集 · 
  数据: {DATA_FILE} · 
  记录数: {len(records)}
</div>
</body>
</html>"""
    
    with open(HTML_FILE, 'w') as f:
        f.write(html)
    print(f"✅ HTML report: {HTML_FILE}")


if __name__ == '__main__':
    if '--report' in sys.argv:
        records = load_history()
        if records:
            generate_html(records)
        else:
            print("❌ 无历史数据，先采集")
    elif '--cron' in sys.argv:
        metrics = collect_hermes_metrics()
        save_metrics(metrics)
        records = load_history()
        if records:
            generate_html(records)
    else:
        metrics = collect_hermes_metrics()
        save_metrics(metrics)
        print(json.dumps(metrics, indent=2))
