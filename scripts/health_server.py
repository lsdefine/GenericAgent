#!/usr/bin/env python3
"""
health_server.py — 系统健康看板 HTTP 服务 📡

将 health_dashboard 从静态 HTML 文件转为 HTTP 服务，
支持实时刷新 + JSON API。

用法:
  python scripts/health_server.py --port 8080     # 启动服务（默认 8899）
  curl http://localhost:8899/api/health           # 获取 JSON 指标
  curl http://localhost:8899/api/history          # 获取历史趋势
  curl http://localhost:8899/                     # 获取完整 HTML 看板

依赖: Python 标准库（无需额外安装）
"""

import os, sys, json, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from urllib.parse import urlparse, parse_qs

# 添加项目根到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.health_dashboard import (
    collect_data,
    load_history,
    detect_anomalies,
    generate_html,
    check_alerts,
    DATA_LOG_PATH,
)
from scripts.alert_manager import AlertManager, ALERT_LOG
from scripts.system_utils import ps_info, disk_info  # 孤儿工具整合


def _parse_size(val):
    """Parse health_dashboard size strings like '27.4GB' → float (GB).
    Also accepts raw numbers (treated as GB)."""
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().upper()
    if not s:
        return 0.0
    multipliers = {"KB": 1/1024/1024, "MB": 1/1024, "GB": 1.0, "TB": 1024.0,
                   "K": 1/1024/1024, "M": 1/1024, "G": 1.0, "T": 1024.0}
    for unit, factor in multipliers.items():
        if s.endswith(unit):
            try:
                return float(s[:-len(unit)]) * factor
            except ValueError:
                return 0.0
    if s.endswith("B"):
        try:
            return float(s[:-1]) / (1024**3)
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""
    
    # 禁用日志缓冲
    def log_message(self, format, *args):
        sys.stderr.write(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}\n")
    
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        
        try:
            if path == "/api/health":
                self._handle_api_health()
            elif path == "/api/history":
                self._handle_api_history()
            elif path == "/api/anomalies":
                self._handle_api_anomalies()
            elif path == "/api/alerts":
                self._handle_api_alerts()
            elif path == "/vue" or path == "/dashboard":
                self._handle_vue_dashboard()
            elif path == "/api/scheduler":
                self._handle_api_scheduler()
            elif path == "/schedule":
                self._handle_scheduler_html()
            elif path == "/api/code_dep":
                self._handle_api_code_dep()
            elif path == "/api/agentmail":
                self._handle_api_agentmail()
            elif path == "/code_dep":
                self._handle_code_dep_html()
            elif path == "/":
                self._handle_html()
            else:
                self._send_json(404, {"error": "Not Found", "path": path})
        except Exception as e:
            self._send_json(500, {"error": str(e)})
    
    def _collect_data(self):
        """收集数据并触发告警"""
        data = collect_data()
        # 触发 alert_manager 告警
        try:
            AlertManager().check_and_dispatch(data)
        except Exception:
            pass
        return data
    
    def _handle_html(self):
        """返回完整 HTML 看板"""
        data = self._collect_data()
        history = load_history()
        anomalies = detect_anomalies(collect_data(), history) if history else []
        html = generate_html(data, report_path="")
        
        # 注入自动刷新 JS
        refresh_script = """
        <script>
        window.addEventListener('DOMContentLoaded', function() {
            setTimeout(function() { location.reload(); }, 30000);
        });
        </script>
        """
        if "</body>" in html:
            html = html.replace("</body>", refresh_script + "\n</body>")
        else:
            html += refresh_script
        
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Refresh", "30")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    
    def _handle_api_health(self):
        """返回 JSON 格式的当前健康指标"""
        data = self._collect_data()
        
        # 简化数据
        result = {
            "timestamp": datetime.now().isoformat(),
            "cpu": {
                "percent": float(data.get("cpu_percent", 0)),
                "count": int(data.get("cpu_count", 0)),
                "model": str(data.get("cpu_model", "")),
            },
            "memory": {
                "percent": float(data.get("mem_percent", 0)),
                "used_gb": _parse_size(data.get("mem_used", 0)),
                "total_gb": _parse_size(data.get("mem_total", 0)),
                "available_gb": _parse_size(data.get("mem_available", 0)),
            },
            "disk": [
                {
                    "mount": d.get("mount", ""),
                    "percent": float(d.get("percent", 0)),
                    "used_gb": _parse_size(d.get("used", 0)),
                    "total_gb": _parse_size(d.get("total", 0)),
                }
                for d in data.get("disks", [])
            ],
            "uptime": str(data.get("uptime", "")),
            "load_avg": [float(x) for x in data.get("load_avg", [0, 0, 0])],
            "services": data.get("services", {}),
            "process_count": int(data.get("process_count", 0)),
        }
        self._send_json(200, result)
    
    def _handle_api_history(self):
        """返回历史趋势数据"""
        history = load_history()
        limit = None
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if "limit" in qs:
            try:
                limit = int(qs["limit"][0])
            except ValueError:
                pass
        
        if limit and limit > 0:
            history = history[-limit:]
        
        # 提取趋势字段
        trend = []
        for snap in history:
            entry = {
                "timestamp": snap.get("timestamp", ""),
                "cpu_percent": snap.get("cpu_percent", 0),
                "mem_percent": snap.get("mem_percent", 0),
            }
            disks = snap.get("disks", [])
            if disks:
                entry["disk_percent"] = max(d["percent"] for d in disks)
            else:
                entry["disk_percent"] = 0
            trend.append(entry)
        
        result = {
            "total": len(trend),
            "data": trend,
        }
        self._send_json(200, result)
    
    def _handle_api_anomalies(self):
        """返回异常检测结果"""
        try:
            current_data = self._collect_data()
            history = load_history()
            if not history:
                self._send_json(200, {"anomalies": [], "message": "历史数据不足，无法进行异常检测"})
                return
            
            anomalies = detect_anomalies(current_data, history)
            result = {
                "timestamp": datetime.now().isoformat(),
                "current": {
                    "cpu_percent": current_data.get("cpu_percent", 0),
                    "mem_percent": current_data.get("mem_percent", 0),
                    "disk_percent": max(d.get("percent", 0) for d in current_data.get("disks", [{}])),
                },
                "anomalies": anomalies,
                "anomaly_count": len(anomalies),
            }
            self._send_json(200, result)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
    
    def _handle_api_alerts(self):
        """返回告警历史"""
        import json
        from pathlib import Path
        try:
            alert_log = Path(ALERT_LOG)
            if alert_log.exists():
                alerts = json.loads(alert_log.read_text())
            else:
                alerts = []
            self._send_json(200, {
                "timestamp": datetime.now().isoformat(),
                "alert_count": len(alerts),
                "alerts": alerts[-50:]  # 返回最近50条
            })
        except Exception as e:
            self._send_json(500, {"error": str(e)})
    
    def _handle_vue_dashboard(self):
        """返回 Vue 3 健康看板页面"""
        import os
        vue_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vue_health_dashboard.html")
        if os.path.exists(vue_path):
            with open(vue_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self._send_json(404, {"error": "Vue dashboard not found"})
    
    def _handle_api_scheduler(self):
        """返回调度任务状态 JSON"""
        import os, json
        from pathlib import Path
        sche_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sche_tasks")
        tasks = []
        try:
            for f in sorted(os.listdir(sche_dir)):
                if not f.endswith('.json') or f in ('scheduler.log', 'budget_log.log.bak'):
                    continue
                fp = os.path.join(sche_dir, f)
                try:
                    with open(fp) as fh:
                        data = json.load(fh)
                    tasks.append({
                        "name": f.replace('.json', ''),
                        "schedule": data.get('schedule', '?'),
                        "repeat": data.get('repeat', '?'),
                        "enabled": data.get('enabled', False),
                        "commands": data.get('commands', data.get('command', '')),
                        "last_run": "N/A",
                        "description": data.get('description', ''),
                    })
                except:
                    tasks.append({"name": f.replace('.json',''), "error": "parse failed"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(tasks),
            "enabled": sum(1 for t in tasks if t.get('enabled')),
            "tasks": tasks,
        })
    
    def _handle_scheduler_html(self):
        """返回调度任务看板 HTML"""
        import os
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheduler_dashboard.html")
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self._send_json(404, {"error": "Scheduler dashboard not found"})
    
    def _handle_api_code_dep(self):
        """返回代码依赖图 JSON"""
        try:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from scripts.dep_scanner import build_graph
            graph = build_graph()
            self._send_json(200, graph)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
    
    def _handle_code_dep_html(self):
        """返回代码依赖图 HTML 看板"""
        import os
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "code_dep_dashboard.html")
        if os.path.exists(html_path):
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self._send_json(404, {"error": "Code dep dashboard not found"})
    
    def _handle_api_agentmail(self):
        """AgentMail 桥接 API — 发送报告/告警"""
        from urllib.parse import parse_qs
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        params = parse_qs(urlparse(self.path).query)
        action = (params.get("action") or [""])[0]
        to = (params.get("to") or [""])[0]
        subject = (params.get("subject") or [""])[0]
        body = (params.get("body") or [""])[0]
        
        if not action:
            self._send_json(400, {"error": "Missing ?action= (alert|report|summary)"})
            return
        
        try:
            from scripts.agentmail_bridge import AgentMailBridge
            bridge = AgentMailBridge()
            
            if action == "alert":
                r = bridge.send_alert(params.get("type", ["generic"])[0], body or "Alert", params.get("severity", ["info"])[0])
                self._send_json(200, {"sent": True, "result": str(r)})
            elif action == "report":
                r = bridge.send_report(subject or "Report", body or "(empty)", to or None)
                self._send_json(200, {"sent": True, "result": str(r)})
            elif action == "summary":
                import json
                metrics = json.loads(body) if body else {}
                r = bridge.daily_summary(metrics)
                self._send_json(200, {"sent": True, "result": str(r)})
            elif action == "inboxes":
                inboxes = bridge.list_inboxes()
                self._send_json(200, {"inboxes": inboxes})
            else:
                self._send_json(400, {"error": f"Unknown action: {action}"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})
    
    def _send_json(self, status, data):
        """发送 JSON 响应"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="系统健康看板 HTTP 服务")
    parser.add_argument("--port", "-p", type=int, default=8899, help="监听端口 (默认: 8899)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    args = parser.parse_args()
    
    server = HTTPServer((args.host, args.port), HealthHandler)
    print(f"📡 系统健康看板服务启动 ├ 地址: http://{args.host}:{args.port}")
    print(f"  ├ HTML 看板:  http://{args.host}:{args.port}/")
    print(f"  ├ JSON 指标:  http://{args.host}:{args.port}/api/health")
    print(f"  ├ 历史趋势:   http://{args.host}:{args.port}/api/history")
    print(f"  ├ 异常检测:   http://{args.host}:{args.port}/api/anomalies")
    print(f"  ├ AgentMail:  http://{args.host}:{args.port}/api/agentmail?action=alert&body=test")
    print(f"  └ 代码依赖:   http://{args.host}:{args.port}/api/code_dep")
    print("  按 Ctrl+C 停止服务")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
