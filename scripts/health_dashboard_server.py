#!/usr/bin/env python3
"""
health_dashboard_server.py — 轻量健康看板 HTTP 服务

基于 health_dashboard.py 的 build_dashboard() 提供实时系统状态 HTML 页面。
用法:
    python3 scripts/health_dashboard_server.py [--port PORT] [--daemon]
"""

import sys, os, json, subprocess, signal, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Add project root
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'memory/tools'))
sys.path.insert(0, os.path.join(ROOT, 'memory'))

from scripts.health_dashboard import build_dashboard
from memory.tools.rich_renderer import render_summary, render_table, render_panel

PORT = int(sys.argv[sys.argv.index('--port') + 1]) if '--port' in sys.argv else 8899

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}\n")

    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path.rstrip("/") or "/"
        
        if path == "/api/health":
            self.send_json(self._get_data())
        elif path == "/api/health.txt":
            self.send_text(self._get_terminal_output())
        elif path == "/api/benchmark":
            self.send_json(self._get_benchmark_data())
        elif path == "/api/benchmark/html":
            self.send_html(self._get_benchmark_html())
        elif path == "/benchmark":
            self.send_html(self._get_benchmark_html())
        else:
            self.send_html(self._get_html_page())

    def _get_data(self):
        """Build dashboard data dict"""
        buf = []
        build_dashboard(output_to_report=False)  # prints to terminal
        # Re-import to capture the output
        data = {"status": "ok", "timestamp": datetime.now().isoformat()}
        return data

    def _get_terminal_output(self):
        """Capture terminal output of build_dashboard"""
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            build_dashboard()
        return f.getvalue()

    def _get_html_page(self):
        """Generate HTML page from dashboard data"""
        terminal_out = self._get_terminal_output()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="30">
<title>系统健康看板</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Courier New', monospace; background: #1e1e2e; color: #cdd6f4; padding: 20px; }}
  h1 {{ color: #89b4fa; font-size: 1.4em; margin-bottom: 15px; }}
  .container {{ max-width: 900px; margin: 0 auto; }}
  .meta {{ color: #6c7086; font-size: 0.85em; margin-bottom: 20px; }}
  pre {{ background: #181825; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 0.9em; line-height: 1.5; color: #cdd6f4; white-space: pre-wrap; word-break: break-all; }}
  .footer {{ margin-top: 20px; color: #6c7086; font-size: 0.75em; text-align: center; }}
  a {{ color: #89b4fa; text-decoration: none; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75em; }}
  .badge-ok {{ background: #a6e3a1; color: #1e1e2e; }}
  .badge-api {{ background: #89b4fa; color: #1e1e2e; }}
</style>
</head>
<body>
<div class="container">
  <h1>🩺 系统健康看板 <span class="badge badge-ok">LIVE</span></h1>
  <div class="meta">
    <span>更新: {now}</span> |
    <span>自动刷新: 30s</span> |
    <a href="/api/health.txt"><span class="badge badge-api">API 文本</span></a>
    <a href="/api/health"><span class="badge badge-api">API JSON</span></a>
    <a href="/benchmark"><span class="badge badge-api">📊 Benchmark</span></a>
  </div>
  <pre>{terminal_out}</pre>
  <div class="footer">GenericAgent v112 · 健康看板 · <a href="/api/health.txt">文本模式</a> · <a href="/benchmark">Benchmark趋势</a></div>
</div>
</body>
</html>"""
        return html

    def send_html(self, content):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def send_text(self, text):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(text.encode('utf-8'))

    def _get_benchmark_data(self):
        """Read benchmark trend data from autonomous_reports"""
        bpath = ROOT + '/autonomous_reports/benchmark_trend.json'
        if not os.path.exists(bpath):
            return {"status": "no_data", "message": "benchmark_trend.json not found"}
        try:
            data = json.loads(open(bpath).read())
            runs = data.get("runs", [])
            chart_data = []
            for run in runs:
                ts = run.get("timestamp", "")
                results = run.get("results", {})
                point = {"timestamp": ts[:16]}
                for test_name, metrics in results.items():
                    if isinstance(metrics, dict):
                        point[f"{test_name}_avg"] = metrics.get("avg_duration_s", 0)
                        point[f"{test_name}_sr"] = metrics.get("success_rate", 0)
                chart_data.append(point)
            tests = list(runs[0].get("results", {}).keys()) if runs else []
            return {"status": "ok", "runs": chart_data, "tests": tests}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _get_benchmark_html(self):
        """Generate standalone benchmark trend page with Chart.js"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Benchmark 性能趋势</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Courier New', monospace; background: #1e1e2e; color: #cdd6f4; padding: 20px; }}
  h1 {{ color: #89b4fa; font-size: 1.4em; margin-bottom: 10px; }}
  .container {{ max-width: 1000px; margin: 0 auto; }}
  .meta {{ color: #6c7086; font-size: 0.85em; margin-bottom: 20px; }}
  .chart-wrap {{ background: #181825; border-radius: 8px; padding: 15px; margin-bottom: 20px; }}
  canvas {{ max-height: 300px; }}
  .nav a {{ color: #89b4fa; text-decoration: none; margin-right: 15px; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; margin-top: 15px; }}
  .stat-card {{ background: #181825; padding: 10px 15px; border-radius: 6px; }}
  .stat-card .val {{ font-size: 1.3em; color: #a6e3a1; }}
  .stat-card .label {{ font-size: 0.8em; color: #6c7086; }}
</style>
</head>
<body>
<div class="container">
  <h1>📊 Benchmark 性能趋势</h1>
  <div class="meta">
    <span>更新: {now}</span> | <span class="nav"><a href="/">← 返回看板</a></span> | <span class="nav"><a href="/api/benchmark">API JSON</a></span>
  </div>
  <div class="chart-wrap">
    <h3 style="color:#a6e3a1;margin-bottom:10px;">⏱ 各测试平均延迟趋势 (s)</h3>
    <canvas id="latencyChart"></canvas>
  </div>
  <div class="chart-wrap">
    <h3 style="color:#a6e3a1;margin-bottom:10px;">✅ 成功率趋势 (%)</h3>
    <canvas id="srChart"></canvas>
  </div>
  <div id="stats" class="stat-grid"></div>
</div>
<script>
async function loadData() {{
  const resp = await fetch('/api/benchmark');
  const data = await resp.json();
  if (data.status !== 'ok') {{ document.body.innerHTML += '<p style="color:#f38ba8">数据不可用: ' + data.message + '</p>'; return; }}
  const runs = data.runs, tests = data.tests;
  if (!runs.length) return;
  const labels = runs.map(r => r.timestamp);
  const colors = ['#89b4fa','#a6e3a1','#f9e2af','#f38ba8','#cba6f7','#94e2d5'];
  new Chart(document.getElementById('latencyChart'), {{
    type: 'line',
    data: {{ labels, datasets: tests.map((t,i) => ({{ label:t, data:runs.map(r=>r[t+'_avg']||0), borderColor:colors[i%6], backgroundColor:colors[i%6]+'33', tension:0.3, fill:false }})) }},
    options: {{ responsive:true, plugins:{{ legend:{{ labels:{{ color:'#cdd6f4' }} }} }}, scales:{{ x:{{ ticks:{{ color:'#6c7086' }}, grid:{{ color:'#313244' }} }}, y:{{ beginAtZero:true, ticks:{{ color:'#6c7086' }}, grid:{{ color:'#313244' }} }} }} }}
  }});
  new Chart(document.getElementById('srChart'), {{
    type: 'line',
    data: {{ labels, datasets: tests.map((t,i) => ({{ label:t, data:runs.map(r=>r[t+'_sr']||0), borderColor:colors[i%6], backgroundColor:colors[i%6]+'33', tension:0.3, fill:false }})) }},
    options: {{ responsive:true, plugins:{{ legend:{{ labels:{{ color:'#cdd6f4' }} }} }}, scales:{{ x:{{ ticks:{{ color:'#6c7086' }}, grid:{{ color:'#313244' }} }}, y:{{ min:0, max:100, ticks:{{ color:'#6c7086' }}, grid:{{ color:'#313244' }} }} }} }}
  }});
  const latest = runs[runs.length-1];
  tests.forEach(t => {{ const avg=(latest[t+'_avg']||0).toFixed(2); const sr=(latest[t+'_sr']||0).toFixed(0); document.getElementById('stats').innerHTML += '<div class=\"stat-card\"><div class=\"val\">'+avg+'s</div><div class=\"label\">'+t+' · 成功率 '+sr+'%</div></div>'; }});
}}
loadData();
</script>
</body>
</html>"""

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"🩺 健康看板服务启动: http://localhost:{PORT}")
    print(f"   HTML页面: http://localhost:{PORT}/")
    print(f"   文本API:  http://localhost:{PORT}/api/health.txt")
    print(f"   JSON API: http://localhost:{PORT}/api/health")
    print(f"   Benchmark: http://localhost:{PORT}/benchmark")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务停止")
        server.server_close()