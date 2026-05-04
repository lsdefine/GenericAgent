#!/usr/bin/env python3
"""
Report Dashboard Web UI for GenericAgent
轻量级HTTP Dashboard, 展示报告/系统状态/事件日志
依赖: 纯stdlib (http.server + markdown rendering)
默认端口: 9900 (可通过 --port 参数修改)
"""

import os
import sys
import json
import time
import threading
import socketserver
import logging
import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_PORT = 9900
REPORTS_DIR = "./autonomous_reports"

class DashboardHandler(SimpleHTTPRequestHandler):
    """Dashboard HTTP Handler"""
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/' or parsed.path == '/index.html':
            self.serve_dashboard()
        elif parsed.path == '/api/reports':
            self.serve_api_reports()
        elif parsed.path == '/api/status':
            self.serve_api_status()
        elif parsed.path == '/api/logs':
            self.serve_api_logs()
        elif parsed.path.startswith('/reports/'):
            self.serve_report_file(parsed.path)
        else:
            super().do_GET()
    
    def serve_dashboard(self):
        html = self._generate_dashboard_html()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def _generate_dashboard_html(self):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        reports = self._list_reports()
        status = self._get_system_status()
        
        report_rows = ''
        for r in reports:
            report_rows += f"""
            <tr>
                <td><a href="/reports/{r['name']}">{r['name']}</a></td>
                <td>{r['modified']}</td>
                <td>{r['size']}KB</td>
            </tr>"""
        
        return f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GenericAgent Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; padding: 20px 0; border-bottom: 1px solid #334155; }}
        .header h1 {{ font-size: 24px; color: #38bdf8; }}
        .status-badge {{ background: #22c55e; color: #fff; padding: 4px 12px; border-radius: 12px; font-size: 12px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 20px 0; }}
        .card {{ background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }}
        .card h3 {{ color: #94a3b8; margin-bottom: 12px; font-size: 14px; text-transform: uppercase; }}
        .metric {{ font-size: 32px; color: #38bdf8; font-weight: bold; }}
        .metric-sub {{ color: #64748b; font-size: 12px; margin-top: 4px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; }}
        a {{ color: #38bdf8; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .refresh {{ background: #38bdf8; color: #0f172a; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; }}
        .refresh:hover {{ background: #7dd3fc; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>GenericAgent Dashboard</h1>
            <div>
                <span class="status-badge">● Online</span>
                <span style="margin-left: 12px; color: #64748b;">{now}</span>
                <button class="refresh" style="margin-left: 12px;" onclick="location.reload()">Refresh</button>
            </div>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>Reports</h3>
                <div class="metric">{len(reports)}</div>
                <div class="metric-sub">Total reports generated</div>
            </div>
            <div class="card">
                <h3>Python Files</h3>
                <div class="metric">{status['py_count']}</div>
                <div class="metric-sub">Scripts in temp/</div>
            </div>
            <div class="card">
                <h3>Memory L2</h3>
                <div class="metric">{status['l2_lines']}</div>
                <div class="metric-sub">Global memory lines</div>
            </div>
            <div class="card">
                <h3>Uptime</h3>
                <div class="metric">{status['uptime']}s</div>
                <div class="metric-sub">Since dashboard start</div>
            </div>
        </div>
        
        <div class="card">
            <h3>Recent Reports</h3>
            <table>
                <thead><tr><th>Name</th><th>Modified</th><th>Size</th></tr></thead>
                <tbody>{report_rows}</tbody>
            </table>
        </div>
    </div>
</body>
</html>"""
    
    def serve_api_reports(self):
        reports = self._list_reports()
        self._send_json(reports)
    
    def serve_api_status(self):
        self._send_json(self._get_system_status())
    
    def serve_api_logs(self):
        logs = self._get_recent_logs(50)
        self._send_json({"logs": logs})
    
    def serve_report_file(self, path):
        filepath = os.path.join(REPORTS_DIR, os.path.basename(path))
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/markdown; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
    
    def _list_reports(self):
        reports = []
        if os.path.exists(REPORTS_DIR):
            for f in sorted(os.listdir(REPORTS_DIR), reverse=True):
                if f.endswith('.md'):
                    fp = os.path.join(REPORTS_DIR, f)
                    stat = os.stat(fp)
                    reports.append({
                        'name': f,
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
                        'size': round(stat.st_size / 1024, 1)
                    })
        return reports
    
    def _get_system_status(self):
        py_count = len([f for f in os.listdir('.') if f.endswith('.py')])
        l2_path = "../memory/global_mem.txt"
        l2_lines = 0
        if os.path.exists(l2_path):
            with open(l2_path) as f:
                l2_lines = sum(1 for _ in f)
        return {
            'py_count': py_count,
            'l2_lines': l2_lines,
            'uptime': round(time.time() - self.server.start_time, 1),
            'reports_count': len(self._list_reports())
        }
    
    def _get_recent_logs(self, limit=50):
        logs = []
        log_files = ['dashboard.log', 'app.log']
        for lf in log_files:
            if os.path.exists(lf):
                with open(lf) as f:
                    logs = f.readlines()[-limit:]
                break
        return [l.strip() for l in logs]
    
    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def main():
    parser = argparse.ArgumentParser(description='GenericAgent Report Dashboard')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='Port (default: 9900)')
    parser.add_argument('--host', default='127.0.0.1', help='Host (default: 127.0.0.1)')
    args = parser.parse_args()
    
    server = ThreadedHTTPServer((args.host, args.port), DashboardHandler)
    server.start_time = time.time()
    logger.info(f"Dashboard running at http://{args.host}:{args.port}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down dashboard...")
        server.shutdown()

if __name__ == '__main__':
    main()
