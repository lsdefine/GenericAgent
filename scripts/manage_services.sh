#!/bin/bash
# ═══════════════════════════════════════════
# GenericAgent 服务管理脚本
# 管理：health_dashboard.py（系统健康看板生成器）
# 用法: bash manage_services.sh <start|stop|status|restart>
# ═══════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GA_HOME="$(dirname "$SCRIPT_DIR")"
PID_FILE="/tmp/ga_health_dashboard.pid"
LOG_FILE="/tmp/ga_health_dashboard.log"
SERVE_PID_FILE="/tmp/ga_health_dashboard_serve.pid"
HEALTH_SCRIPT="$SCRIPT_DIR/health_dashboard.py"
PORT=8090

ensure_stop() {
    local pid_file="$1"
    local name="$2"
    if [ -f "$pid_file" ]; then
        local old_pid=$(cat "$pid_file")
        if kill -0 "$old_pid" 2>/dev/null; then
            echo "  ⏹  停止 $name (PID $old_pid)..."
            kill "$old_pid" 2>/dev/null
            sleep 1
            if kill -0 "$old_pid" 2>/dev/null; then
                kill -9 "$old_pid" 2>/dev/null
            fi
        fi
        rm -f "$pid_file"
    fi
}

start_daemon() {
    echo "  🚀 启动健康看板数据采集守护进程..."
    # 无限循环: 每60秒采集一次数据，生成HTML报告
    nohup python3 -c "
import time, os, sys, json
sys.path.insert(0, '${SCRIPT_DIR}')
sys.path.insert(0, '${GA_HOME}')
sys.stdout = open('${LOG_FILE}', 'w', buffering=1)
sys.stderr = sys.stdout

# PID写入
with open('${PID_FILE}', 'w') as f:
    f.write(str(os.getpid()))

from health_dashboard import collect_data, log_snapshot, check_alerts, generate_html, save_report
from datetime import datetime
import traceback

while True:
    try:
        print(f'[{datetime.now().isoformat()}] 采集系统数据...')
        data = collect_data()
        log_snapshot(data)
        alerts = check_alerts(data)
        html = generate_html(data)
        report_path = os.path.join('${GA_HOME}', 'sche_tasks', 'done', datetime.now().strftime('%Y-%m-%d') + '_健康看板.html')
        save_report(html, report_path)
        print(f'  ✅ 报告已生成: {report_path}')
        if alerts:
            print(f'  ⚠️  告警: {len(alerts)} 条')
    except Exception as e:
        print(f'  ❌ 采集错误: {e}')
        traceback.print_exc()
    time.sleep(60)
" > /dev/null 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    echo "  ✅ 守护进程已启动 (PID $pid)"
    echo "  📄 日志: $LOG_FILE"
}

start_serve() {
    if [ -f "$SERVE_PID_FILE" ] && kill -0 $(cat "$SERVE_PID_FILE") 2>/dev/null; then
        echo "  ⚠️  HTTP服务已在运行"
        return
    fi
    echo "  🌐 启动HTTP预览服务 (端口 $PORT)..."
    nohup python3 -c "
import http.server, socketserver, os, sys, json
PORT = $PORT
DONE_DIR = '${GA_HOME}/sche_tasks/done'

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.path = '/index.html'
            # 列出最新的HTML报告
            files = sorted([f for f in os.listdir(DONE_DIR) if f.endswith('.html')], reverse=True)
            if files:
                self.path = '/' + files[0]
        return super().do_GET()
    
    def log_message(self, format, *args):
        pass  # 静默日志

os.chdir(DONE_DIR)
with open('${SERVE_PID_FILE}', 'w') as f:
    f.write(str(os.getpid()))
with socketserver.TCPServer(('', PORT), DashboardHandler) as httpd:
    print(f'Serving on port {PORT}')
    httpd.serve_forever()
" > /dev/null 2>&1 &
    local pid=$!
    echo "$pid" > "$SERVE_PID_FILE"
    echo "  ✅ HTTP服务已启动: http://localhost:$PORT"
}

case "${1:-}" in
    start)
        echo "📊 GenericAgent 服务启动..."
        ensure_stop "$PID_FILE" "采集守护进程"
        start_daemon
        start_serve
        echo "✅ 所有服务已启动"
        ;;
    stop)
        echo "⏹  GenericAgent 服务停止..."
        ensure_stop "$PID_FILE" "采集守护进程"
        ensure_stop "$SERVE_PID_FILE" "HTTP服务"
        echo "✅ 所有服务已停止"
        ;;
    status)
        echo "📊 GenericAgent 服务状态:"
        if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "  ✅ 采集守护进程: 运行中 (PID $(cat $PID_FILE))"
        else
            echo "  ❌ 采集守护进程: 未运行"
        fi
        if [ -f "$SERVE_PID_FILE" ] && kill -0 $(cat "$SERVE_PID_FILE") 2>/dev/null; then
            echo "  ✅ HTTP预览服务: 运行中 (PID $(cat $SERVE_PID_FILE))"
        else
            echo "  ❌ HTTP预览服务: 未运行"
        fi
        # 检查最近报告
        latest=$(ls -1t "$GA_HOME/sche_tasks/done/"*.html 2>/dev/null | head -1)
        if [ -n "$latest" ]; then
            echo "  📄 最新报告: $(basename "$latest") ($(du -h "$latest" | cut -f1))"
        else
            echo "  📄 尚无报告生成"
        fi
        echo "  📊 数据日志: $(wc -l < "$GA_HOME/temp/health_history.json" 2>/dev/null || echo 0) 行历史数据"
        ;;
    restart)
        echo "🔄 重启服务..."
        "$0" stop
        sleep 1
        "$0" start
        echo "✅ 重启完成"
        ;;
    *)
        echo "用法: $0 <start|stop|status|restart>"
        echo ""
        echo "  启动 GenericAgent 系统健康看板服务："
        echo "    - 采集守护进程 (每60秒生成报告)"
        echo "    - HTTP预览服务 (端口 8090)"
        echo ""
        echo "示例:"
        echo "  bash $0 start     # 启动所有服务"
        echo "  bash $0 status    # 查看服务状态"
        echo "  bash $0 stop      # 停止所有服务"
        echo "  bash $0 restart   # 重启所有服务"
        exit 1
        ;;
esac
