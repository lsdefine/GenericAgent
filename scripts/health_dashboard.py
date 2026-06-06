#!/usr/bin/env python3
"""
系统健康看板脚本
==============
采集CPU/内存/磁盘/网络数据 → 生成HTML报告

定时任务：配合 scheduled_task_sop 部署，自动生成日报告
手动运行：python health_dashboard.py [--output /path/to/report.html]

依赖：psutil
"""

import os, sys, json, shutil
import subprocess
from datetime import datetime, timezone

# 延迟导入 quality metrics（仅在生成时按需加载）
_metrics_aggregator = None
def _get_metrics_aggregator():
    global _metrics_aggregator
    if _metrics_aggregator is None:
        try:
            # 确保engine在sys.path中
            _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from engine.metrics import metrics_aggregator
            _metrics_aggregator = metrics_aggregator
        except ImportError:
            _metrics_aggregator = False
        except Exception:
            _metrics_aggregator = False
    return _metrics_aggregator

# 历史数据路径
DATA_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'temp', 'health_history.json')
DATA_LOG_PATH = os.path.normpath(DATA_LOG_PATH)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<title>系统健康看板 - {hostname}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background:#0f0f1a; color:#e0e0e0; padding:20px; }}
h1 {{ color:#7c3aed; font-size:1.5em; margin-bottom:5px; }}
.subtitle {{ color:#888; font-size:0.85em; margin-bottom:20px; }}
.dashboard {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(280px,1fr)); gap:15px; }}
.card {{ background:#1a1a2e; border-radius:12px; padding:18px; border:1px solid #2a2a4a; }}
.card h2 {{ font-size:0.9em; color:#a78bfa; margin-bottom:12px; text-transform:uppercase; letter-spacing:0.5px; }}
.stat-row {{ display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid #222; font-size:0.9em; }}
.stat-row:last-child {{ border-bottom:none; }}
.label {{ color:#999; }}
.value {{ font-weight:600; }}
.value.warning {{ color:#f59e0b; }}
.value.critical {{ color:#ef4444; }}
.value.good {{ color:#22c55e; }}
.bar-bg {{ background:#222; border-radius:4px; height:8px; margin:6px 0; overflow:hidden; }}
.bar-fill {{ height:100%; border-radius:4px; transition:width 1s; }}
.bar-fill.green {{ background:#22c55e; }}
.bar-fill.yellow {{ background:#f59e0b; }}
.bar-fill.red {{ background:#ef4444; }}
.process-list {{ font-size:0.8em; }}
.process-list div {{ display:flex; justify-content:space-between; padding:3px 0; color:#bbb; }}
.footer {{ text-align:center; color:#555; font-size:0.75em; margin-top:25px; padding-top:15px; border-top:1px solid #222; }}
</style>
</head>
<body>
<h1>📊 系统健康看板</h1>
<div class="subtitle">{hostname} | {timestamp} | 运行时间: {uptime}</div>

<div class="dashboard">

<div class="card">
<h2>💾 内存</h2>
<div class="stat-row"><span class="label">总计</span><span class="value">{mem_total}</span></div>
<div class="stat-row"><span class="label">已用</span><span class="value {mem_percent_class}">{mem_used} ({mem_percent}%)</span></div>
<div class="stat-row"><span class="label">可用</span><span class="value">{mem_available}</span></div>
<div class="stat-row"><span class="label">缓存/缓冲区</span><span class="value">{mem_cached}</span></div>
<div class="bar-bg"><div class="bar-fill {mem_percent_class}" style="width:{mem_percent}%"></div></div>
</div>

<div class="card">
<h2>🔀 Swap</h2>
<div class="stat-row"><span class="label">总计</span><span class="value">{swap_total}</span></div>
<div class="stat-row"><span class="label">已用</span><span class="value {swap_percent_class}">{swap_used} ({swap_percent}%)</span></div>
<div class="bar-bg"><div class="bar-fill {swap_percent_class}" style="width:{swap_percent}%"></div></div>
</div>

<div class="card">
<h2>🧠 CPU</h2>
<div class="stat-row"><span class="label">型号</span><span class="value">{cpu_model}</span></div>
<div class="stat-row"><span class="label">核心</span><span class="value">{cpu_cores} 核</span></div>
<div class="stat-row"><span class="label">使用率</span><span class="value {cpu_percent_class}">{cpu_percent}%</span></div>
<div class="stat-row"><span class="label">1min负载</span><span class="value {load1_class}">{load1}</span></div>
<div class="stat-row"><span class="label">5min负载</span><span class="value">{load5}</span></div>
<div class="stat-row"><span class="label">15min负载</span><span class="value">{load15}</span></div>
<div class="bar-bg"><div class="bar-fill {cpu_percent_class}" style="width:{cpu_percent}%"></div></div>
</div>

<div class="card">
<h2>💽 磁盘</h2>
{disk_rows}
</div>

<div class="card">
<h2>🌐 网络</h2>
<div class="stat-row"><span class="label">主机名</span><span class="value">{hostname}</span></div>
<div class="stat-row"><span class="label">IP地址</span><span class="value">{ip_addr}</span></div>
<div class="stat-row"><span class="label">发送</span><span class="value">{net_sent}</span></div>
<div class="stat-row"><span class="label">接收</span><span class="value">{net_recv}</span></div>
</div>

<div class="card">
<h2>📋 进程 TOP 5 (按内存)</h2>
<div class="process-list">{top_processes}</div>
</div>

<div class="card">
<h2>⏱️ 系统信息</h2>
<div class="stat-row"><span class="label">OS</span><span class="value">{os_name}</span></div>
<div class="stat-row"><span class="label">内核</span><span class="value">{kernel}</span></div>
<div class="stat-row"><span class="label">用户</span><span class="value">{users}</span></div>
<div class="stat-row"><span class="label">当前进程</span><span class="value">{num_processes}</span></div>
<div class="stat-row"><span class="label">打开句柄</span><span class="value">{num_fds}</span></div>
</div>


{services_card}
{prompt_quality_card}
{trend_chart_card}
{anomaly_card}
</div>
<div class="footer">由 GenericAgent 自动采集 · 报告路径: {report_path}</div>
</body>
</html>"""


def collect_data():
    """采集系统数据"""
    import psutil
    data = {}
    
    # CPU
    data['cpu_percent'] = psutil.cpu_percent(interval=0.5)
    data['cpu_cores'] = psutil.cpu_count()
    data['cpu_model'] = _read_cpu_model()
    load1, load5, load15 = psutil.getloadavg()
    data['load1'] = round(load1, 2)
    data['load5'] = round(load5, 2)
    data['load15'] = round(load15, 2)
    
    # Memory
    mem = psutil.virtual_memory()
    data['mem_total'] = _fmt_bytes(mem.total)
    data['mem_used'] = _fmt_bytes(mem.used)
    data['mem_percent'] = mem.percent
    data['mem_available'] = _fmt_bytes(mem.available)
    data['mem_cached'] = _fmt_bytes(mem.cached + mem.buffers if hasattr(mem, 'buffers') else 0)
    
    # Swap
    swap = psutil.swap_memory()
    data['swap_total'] = _fmt_bytes(swap.total)
    data['swap_used'] = _fmt_bytes(swap.used)
    data['swap_percent'] = swap.percent
    
    # Disk
    data['disks'] = []
    for part in psutil.disk_partitions():
        if part.fstype and ('ext' in part.fstype or 'xfs' in part.fstype or 'btrfs' in part.fstype):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                data['disks'].append({
                    'mount': part.mountpoint,
                    'device': part.device,
                    'total': _fmt_bytes(usage.total),
                    'used': _fmt_bytes(usage.used),
                    'percent': usage.percent,
                    'free': _fmt_bytes(usage.free),
                })
            except:
                pass
    
    # Network
    net = psutil.net_io_counters()
    data['net_sent'] = _fmt_bytes(net.bytes_sent)
    data['net_recv'] = _fmt_bytes(net.bytes_recv)
    data['net_sent_raw'] = net.bytes_sent
    data['net_recv_raw'] = net.bytes_recv
    
    # Processes
    procs = sorted(psutil.process_iter(['name', 'memory_percent', 'cpu_percent']),
                   key=lambda p: p.info['memory_percent'] or 0, reverse=True)[:5]
    data['top_processes'] = [(p.info['name'] or '?', round(p.info['memory_percent'] or 0, 1)) for p in procs]
    
    # System
    data['hostname'] = os.uname().nodename
    data['kernel'] = os.uname().release
    data['os_name'] = _read_os_name()
    data['uptime'] = _format_uptime(psutil.boot_time())
    data['num_processes'] = len(psutil.pids())
    try:
        data['num_fds'] = sum(p.num_fds() for p in psutil.process_iter(['num_fds']))
    except Exception:
        data['num_fds'] = 'N/A (权限不足)'
    data['users'] = ', '.join(u.name for u in psutil.users()) or '无远程用户'
    
    # IP
    ip_addr = '127.0.0.1'
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_addr = s.getsockname()[0]
        s.close()
    except:
        pass
    data['ip_addr'] = ip_addr
    
    # 服务健康检查
    services, disk_warnings = _check_services()
    data['services'] = services
    data['disk_warnings'] = disk_warnings
    
    return data


def _read_cpu_model():
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if 'model name' in line:
                    return line.split(':')[1].strip()
    except:
        pass
    return 'Unknown'


def _read_os_name():
    try:
        import platform
        return platform.platform()
    except:
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME'):
                        return line.split('=')[1].strip().strip('"')
        except:
            pass
    return 'Unknown'


def _format_uptime(boot_time):
    delta = datetime.now() - datetime.fromtimestamp(boot_time)
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days: parts.append(f"{days}天")
    if hours: parts.append(f"{hours}小时")
    parts.append(f"{minutes}分钟")
    return ''.join(parts)


def _fmt_bytes(b):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if b < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


def _percent_class(val, warn=70, crit=90):
    if val >= crit: return 'critical'
    if val >= warn: return 'warning'
    return 'good'


def _check_services():
    """检测关键本地服务的端口可达性/进程存活/响应时间"""
    services = []

    # 定义待检服务 (name, port/None, proc_keyword/None, url/None)
    checks = [
        ("🤖 Hermes Router", 20128, "hermes"),
        ("🌐 Node App (9090)", 9090, "node"),
        ("🖥️ Chrome", None, "chrome"),
        ("🔧 ChromeDriver", None, "chromedriver"),
        ("🧭 Firefox", None, "firefox"),
        ("📧 AgentMail", 443, None, "https://agentmail.to"),
    ]

    import socket
    import time
    for entry in checks:
        name = entry[0]
        port = entry[1] if len(entry) > 1 else None
        proc_keyword = entry[2] if len(entry) > 2 else None
        url = entry[3] if len(entry) > 3 else None

        port_ok = None
        proc_ok = None
        url_ok = None
        resp_time_ms = None  # 响应时间(ms)

        if port:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            t0 = time.time()
            result = sock.connect_ex(('127.0.0.1', port))
            resp_time_ms = int((time.time() - t0) * 1000)
            port_ok = (result == 0)
            sock.close()

        if proc_keyword:
            try:
                proc_ok = len(os.popen(f'pgrep -f "{proc_keyword}"').read().strip().split()) > 0
            except:
                proc_ok = False

        if url:
            try:
                import urllib.request
                req = urllib.request.Request(url, method='HEAD')
                t0 = time.time()
                resp = urllib.request.urlopen(req, timeout=3)
                resp_time_ms = int((time.time() - t0) * 1000)
                url_ok = (resp.status < 500)
            except:
                url_ok = False
                resp_time_ms = -1

        healthy = port_ok or proc_ok or url_ok
        status = '✅' if healthy else ('⚠️' if (port_ok is False) else '❌')
        detail_parts = []
        if port is not None:
            detail_parts.append(f"端口:{'✓' if port_ok else '✗'}" if port_ok is not None else "端口:N/A")
        if proc_keyword:
            detail_parts.append(f"进程:{'✓' if proc_ok else '✗'}" if proc_ok is not None else "进程:N/A")
        if url:
            detail_parts.append(f"URL:{'✓' if url_ok else '✗'}" if url_ok is not None else "URL:N/A")
        if resp_time_ms is not None and resp_time_ms >= 0:
            detail_parts.append(f"{resp_time_ms}ms")

        services.append({
            'name': name,
            'status': status,
            'detail': ' | '.join(detail_parts),
            'healthy': healthy,
            'resp_time_ms': resp_time_ms,
        })

    # 系统资源预警
    import psutil
    disk_warnings = []
    for part in psutil.disk_partitions():
        if part.fstype and ('ext' in part.fstype or 'xfs' in part.fstype or 'btrfs' in part.fstype):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                if usage.percent > 85:
                    disk_warnings.append(f"{part.mountpoint} ({usage.percent}%)")
            except:
                pass

    return services, disk_warnings



def log_snapshot(data):
    """将当前数据快照写入历史JSON（保留最近96条 ≈ 1.5h@60s间隔）"""
    # 收集服务响应时间
    svc_times = {}
    for s in data.get('services', []):
        if s.get('resp_time_ms') is not None and s['resp_time_ms'] >= 0:
            svc_times[s['name']] = s['resp_time_ms']

    record = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'cpu_percent': data['cpu_percent'],
        'mem_percent': data['mem_percent'],
        'swap_percent': data.get('swap_percent', 0),
        'load1': data['load1'],
        'disk_percent': max((d['percent'] for d in data['disks']), default=0),
        'net_sent': data.get('net_sent_raw', ''),
        'net_recv': data.get('net_recv_raw', ''),
        'service_times': svc_times,
    }
    history = []
    if os.path.exists(DATA_LOG_PATH):
        try:
            with open(DATA_LOG_PATH) as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    history.append(record)
    history = history[-96:]
    os.makedirs(os.path.dirname(DATA_LOG_PATH), exist_ok=True)
    with open(DATA_LOG_PATH, 'w') as f:
        json.dump(history, f, indent=2)
    return history


def load_history():
    """读取历史数据 (兼容对象/数组格式)"""
    if os.path.exists(DATA_LOG_PATH):
        try:
            with open(DATA_LOG_PATH) as f:
                data = json.load(f)
            # 兼容两种格式: {"records": [...]} 或 [...]
            if isinstance(data, dict) and "records" in data:
                return data["records"]
            return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def detect_anomalies(current_data, history, z_threshold=2.0):
    """
    异常检测：基于滚动窗口的z-score算法
    对比当前值与历史均值，偏差超过z_threshold×stddev标记为异常
    返回: [(metric_name, direction, severity, message), ...]
    """
    if len(history) < 3:
        return []

    anomalies = []
    metrics = [
        ('cpu_percent', 'CPU使用率', 'up', True),
        ('mem_percent', '内存使用率', 'up', True),
        ('disk_percent', '磁盘使用率', 'up', True),
        ('load1', '1分钟负载', 'both', True),
    ]

    for key, label, direction, enabled in metrics:
        if not enabled:
            continue
        values = [h.get(key, 0) for h in history[-12:]]  # 最近12个采样点
        if len(values) < 3:
            continue

        mean_val = sum(values) / len(values)
        if mean_val == 0:
            continue
        variance = sum((v - mean_val) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
        if std_dev == 0:
            std_dev = mean_val * 0.05  # 防止除零

        curr = current_data.get(key, 0)
        z_score = (curr - mean_val) / std_dev

        if direction in ('up', 'both') and z_score > z_threshold:
            pct_change = ((curr - mean_val) / mean_val) * 100
            anomalies.append((
                key, '📈', 'spike',
                f'{label} 突升: {curr:.1f} (均值{mean_val:.1f}, +{pct_change:.0f}%, z={z_score:.1f})'
            ))
        elif direction in ('down', 'both') and z_score < -z_threshold:
            pct_change = ((curr - mean_val) / mean_val) * 100
            anomalies.append((
                key, '📉', 'drop',
                f'{label} 突降: {curr:.1f} (均值{mean_val:.1f}, {pct_change:.0f}%, z={z_score:.1f})'
            ))

    # 服务响应时间异常检测
    current_times = {s['name']: s['resp_time_ms'] for s in current_data.get('services', [])
                     if s.get('resp_time_ms') is not None and s['resp_time_ms'] >= 0}

    if current_times and len(history) >= 3:
        for svc_name, curr_time in current_times.items():
            times = []
            for h in history[-12:]:
                st = h.get('service_times', {})
                if svc_name in st and st[svc_name] >= 0:
                    times.append(st[svc_name])
            if len(times) < 3:
                continue
            mean_t = sum(times) / len(times)
            if mean_t == 0:
                continue
            variance = sum((v - mean_t) ** 2 for v in times) / len(times)
            std_t = variance ** 0.5 or mean_t * 0.05
            z = (curr_time - mean_t) / std_t
            if z > z_threshold:
                pct = ((curr_time - mean_t) / mean_t) * 100
                anomalies.append((
                    f'svc_{svc_name}', '⏱️', 'spike',
                    f'服务 [{svc_name}] 响应时间突升: {curr_time}ms (均值{mean_t:.0f}ms, +{pct:.0f}%, z={z:.1f})'
                ))

    return anomalies


def generate_html(data, report_path=''):
    """生成HTML报告（含历史趋势图+异常检测+服务响应时间趋势）"""
    # 加载历史数据
    history = load_history()
    # 准备趋势图表数据（最多7天）
    trend_labels = [h.get('timestamp', '')[:10] for h in history[-7:]]
    trend_cpu = [h.get('cpu_percent', 0) for h in history[-7:]]
    trend_mem = [h.get('mem_percent', 0) for h in history[-7:]]
    trend_load = [h.get('load1', 0) for h in history[-7:]]
    trend_disk = [h.get('disk_percent', h.get('disk_used_percent', 0)) for h in history[-7:]]

    # 趋势图表卡片
    if trend_labels:
        trend_card = f'''
<div class="card">
<h2>📈 7天趋势</h2>
<canvas id="trendChart" height="200"></canvas>
</div>
<script>
const ctx = document.getElementById('trendChart').getContext('2d');
new Chart(ctx, {{
    type: 'line',
    data: {{
        labels: {json.dumps(trend_labels)},
        datasets: [
            {{label:'CPU %', data:{json.dumps(trend_cpu)}, borderColor:'#ef4444', tension:0.3, pointRadius:3}},
            {{label:'内存 %', data:{json.dumps(trend_mem)}, borderColor:'#22c55e', tension:0.3, pointRadius:3}},
            {{label:'磁盘 %', data:{json.dumps(trend_disk)}, borderColor:'#f59e0b', tension:0.3, pointRadius:3}},
            {{label:'负载', data:{json.dumps(trend_load)}, borderColor:'#a78bfa', tension:0.3, pointRadius:3, yAxisID:'y1'}}
        ]
    }},
    options:{{
        responsive:true,
        maintainAspectRatio:false,
        scales:{{y:{{beginAtZero:true,max:100,grid:{{color:'#333'}}}},y1:{{position:'right',grid:{{display:false}}}}}},
        plugins:{{legend:{{labels:{{color:'#ccc'}}}}}}
    }}
}});
</script>'''
    else:
        trend_card = '<div class="card"><h2>📈 7天趋势</h2><p style="color:#888;">暂无历史数据（下次采集后显示）</p></div>'

    data['trend_chart_card'] = trend_card

    # ── 异常检测 ──
    anomalies = detect_anomalies(data, history)
    if anomalies:
        anom_rows = ''.join(
            f'<div class="stat-row" style="color:{"#ef4444" if a[2]=="spike" else "#f59e0b"};">'
            f'<span class="label">{a[1]} {a[3].split(":")[0]}</span>'
            f'<span class="value" style="color:{"#ef4444" if a[2]=="spike" else "#f59e0b"};">{a[3].split(":")[1] if ":" in a[3] else a[3]}</span>'
            f'</div>'
            for a in anomalies
        )
        data['anomaly_card'] = f'''
<div class="card" style="border-color:#ef4444;">
<h2 style="color:#ef4444;">🚨 异常检测 ({len(anomalies)})</h2>
{anom_rows}
</div>'''
    else:
        data['anomaly_card'] = '<div class="card"><h2>✅ 异常检测</h2><p style="color:#22c55e;">无异常（z-score在正常范围）</p></div>'

    # 服务健康卡片
    svc_rows = []
    for svc in data.get('services', []):
        cls = 'good' if svc['healthy'] else 'critical'
        svc_rows.append(
            f'<div class="stat-row">'
            f'<span class="label">{svc["status"]} {svc["name"]}</span>'
            f'<span class="value {cls}">{svc["detail"]}</span>'
            f'</div>'
        )
    # 服务响应时间趋势（最近7次）
    if len(history) >= 2:
        for svc in data.get('services', []):
            svc_name = svc['name']
            times = []
            for h in history[-8:]:
                st = h.get('service_times', {})
                if svc_name in st and st[svc_name] >= 0:
                    times.append(st[svc_name])
            if len(times) >= 2:
                trend_indicators = ''
                for i in range(1, len(times)):
                    if times[i] > times[i-1] * 1.5:
                        trend_indicators += '📈'
                    elif times[i] < times[i-1] * 0.5:
                        trend_indicators += '📉'
                    else:
                        trend_indicators += '→'
                svc_rows.append(
                    f'<div class="stat-row" style="font-size:0.8em;color:#888;padding-left:20px;">'
                    f'<span>响应趋势</span>'
                    f'<span>{trend_indicators} ({times[-1]}ms)</span>'
                    f'</div>'
                )

    warnings = data.get('disk_warnings', [])
    if warnings:
        svc_rows.append(
            f'<div class="stat-row" style="color:#f59e0b;">'
            f'<span class="label">⚠️ 磁盘预警</span>'
            f'<span class="value warning">{" · ".join(warnings)}</span>'
            f'</div>'
        )
    data['services_card'] = '\n'.join([
        '<div class="card">',
        '<h2>🔍 服务健康 + 响应趋势</h2>',
        *svc_rows,
        '</div>',
    ]) if svc_rows else ''

    # ── Prompt Quality Card (from metrics_aggregator) ──
    pq_rows = []
    ma = _get_metrics_aggregator()
    if ma:
        try:
            # 扫描最近的prompt文件
            code_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            prompt_files = []
            for root, dirs, files in os.walk(code_root):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__' and d != 'node_modules']
                for f in files:
                    if f.endswith('.py') or f.endswith('.md'):
                        fp = os.path.join(root, f)
                        if os.path.getsize(fp) < 50000:
                            prompt_files.append(fp)
                    if len(prompt_files) >= 8:
                        break
                if len(prompt_files) >= 8:
                    break
            scores = []
            for fp in prompt_files:
                try:
                    text = open(fp, 'r', errors='replace').read(2000)
                    result = ma.score_prompt(text, fp)
                    if result and 'total' in result:
                        scores.append((os.path.basename(fp), result['total']))
                except:
                    pass
            scores.sort(key=lambda x: x[1], reverse=True)
            for name, s in scores[:6]:
                cls = 'green' if s >= 7 else ('yellow' if s >= 4 else 'red')
                pq_rows.append(
                    f'<div class="stat-row"><span class="label">{name}</span>'
                    f'<span class="value {cls}">{s:.1f}</span></div>'
                )
        except Exception as e:
            pq_rows.append(f'<div class="stat-row"><span class="label">Metrics Error</span><span class="value">{e}</span></div>')
    else:
        pq_rows.append('<div class="stat-row"><span class="label" style="color:#666;">engine.metrics 未加载</span></div>')
    data['prompt_quality_card'] = '\n'.join([
        '<div class="card">',
        '<h2>📊 Prompt 质量评分 (MetricsAggregator)</h2>',
        *pq_rows,
        '</div>',
    ]) if pq_rows else ''

    # CPU percent class
    cpu_cls = _percent_class(data['cpu_percent'], 70, 90)
    # Load relative to cores
    load_ratio = data['load1'] / data['cpu_cores'] if data['cpu_cores'] > 0 else 0
    load_cls = _percent_class(load_ratio * 100, 70, 90)

    # Disk rows
    disk_rows = []
    for d in data['disks']:
        cls = _percent_class(d['percent'], 80, 92)
        bar_cls = 'yellow' if cls == 'warning' else ('red' if cls == 'critical' else 'green')
        disk_rows.append(
            f'<div class="stat-row"><span class="label">{d["mount"]}</span>'
            f'<span class="value {cls}">{d["percent"]}%</span></div>'
            f'<div class="stat-row" style="font-size:0.8em;color:#888;">'
            f'{d["used"]} / {d["total"]}</div>'
            f'<div class="bar-bg"><div class="bar-fill {bar_cls}" style="width:{d["percent"]}%"></div></div>'
        )
    data['disk_rows'] = '\n'.join(disk_rows)

    # Top processes
    proc_rows = [f'<div><span>{name}</span><span>{mem}%</span></div>' for name, mem in data['top_processes']]
    data['top_processes'] = '\n'.join(proc_rows) if proc_rows else '<div>无数据</div>'

    # Format timestamps
    data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['mem_percent_class'] = _percent_class(data['mem_percent'], 80, 92)
    data['cpu_percent_class'] = cpu_cls
    data['load1_class'] = load_cls
    data['swap_percent_class'] = _percent_class(data['swap_percent'], 50, 80)
    data['report_path'] = report_path

    return HTML_TEMPLATE.format(**data)


def save_report(html, output_path):
    """保存HTML报告"""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ 报告已保存: {output_path} ({os.path.getsize(output_path)} bytes)")
    return output_path


def check_alerts(data, alert_file=''):
    """
    阈值告警检测
    - CPU > 90% → CRITICAL
    - CPU > 80% → WARNING
    - 内存 > 92% → CRITICAL
    - 内存 > 85% → WARNING
    - 磁盘 > 95% → CRITICAL
    - 磁盘 > 90% → WARNING
    输出到 stderr，可选持久化到 alert_file
    """
    import sys, json
    alerts = []

    # CPU 告警
    cpu = data.get('cpu_percent', 0)
    if cpu > 90:
        alerts.append(('CRITICAL', f'CPU使用率 {cpu}% > 90%'))
    elif cpu > 80:
        alerts.append(('WARNING', f'CPU使用率 {cpu}% > 80%'))

    # 内存告警
    mem = data.get('mem_percent', 0)
    if mem > 92:
        alerts.append(('CRITICAL', f'内存使用率 {mem}% > 92%'))
    elif mem > 85:
        alerts.append(('WARNING', f'内存使用率 {mem}% > 85%'))

    # 磁盘告警
    for d in data.get('disks', []):
        pct = d.get('percent', 0)
        if pct > 95:
            alerts.append(('CRITICAL', f'磁盘 {d["mount"]} 使用率 {pct}% > 95%'))
        elif pct > 90:
            alerts.append(('WARNING', f'磁盘 {d["mount"]} 使用率 {pct}% > 90%'))

    # 输出告警
    if alerts:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n⚠️  系统告警 [{timestamp}]", file=sys.stderr)
        for level, msg in alerts:
            icon = '🔴' if level == 'CRITICAL' else '🟡'
            print(f"  {icon} [{level}] {msg}", file=sys.stderr)

        # 持久化到告警文件
        if alert_file:
            existing = []
            if os.path.exists(alert_file):
                try:
                    with open(alert_file) as f:
                        existing = json.load(f)
                except:
                    pass
            existing.append({
                'timestamp': timestamp,
                'alerts': [{'level': l, 'message': m} for l, m in alerts]
            })
            # 只保留最近100条
            existing = existing[-100:]
            os.makedirs(os.path.dirname(alert_file) or '.', exist_ok=True)
            with open(alert_file, 'w') as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
    else:
        print("  ✅ 所有指标正常（无告警）", file=sys.stderr)

    return len([a for a in alerts if a[0] == 'CRITICAL'])


def send_agentmail_alert(alerts, data):
    """通过AgentMail发送告警邮件"""
    try:
        from memory.keychain import keys
        from agentmail import AgentMail
        api_key = keys.AGENTMAIL_API_KEY
        client = AgentMail(api_key=api_key.use())
        resp = client.inboxes.list()
        if not resp.inboxes:
            print("  ❌ 无inbox，无法发送告警邮件", file=sys.stderr)
            return
        inbox_id = resp.inboxes[0].inbox_id
        to_email = resp.inboxes[0].email
        lines = [
            '<h2>⚠️ 系统告警通知</h2>',
            f'<p><b>时间：</b>{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>',
            f'<p><b>主机：</b>{data.get("hostname", "?")}</p>',
            '<h3>告警列表</h3><ul>']
        for level, msg in alerts:
            icon = '🔴' if level == 'CRITICAL' else '🟡'
            lines.append(f'<li>{icon} <b>{level}</b>: {msg}</li>')
        lines.append('</ul>')
        lines.append(f'<p>CPU: {data.get("cpu_percent", "?")}% | 内存: {data.get("mem_percent", "?")}% | '
                     f'磁盘: {[d["percent"] for d in data.get("disks", [])]}</p>')
        client.inboxes.messages.send(
            inbox_id=inbox_id, to=[to_email],
            subject=f'🔴 GA告警 - {alerts[0][1][:50]}',
            html=''.join(lines))
        print(f"  ✅ 告警已发送到 {to_email}", file=sys.stderr)
    except Exception as e:
        print(f"  ❌ 告警发送失败: {e}", file=sys.stderr)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='系统健康看板 - 生成HTML报告 + 阈值告警 + AgentMail通知')
    parser.add_argument('--output', '-o', default='', help='报告输出路径')
    parser.add_argument('--alert-file', default='/tmp/health_alerts.json', help='告警持久化文件 (默认: /tmp/health_alerts.json)')
    parser.add_argument('--agentmail', action='store_true', help='CRITICAL告警时通过AgentMail发送通知')
    parser.add_argument('--open', action='store_true', help='生成后用浏览器打开')
    args = parser.parse_args()
    
    print("📊 系统健康看板 - 数据采集中...")
    data = collect_data()
    # 记录历史快照
    log_snapshot(data)
    print(f"  CPU: {data['cpu_percent']}% | 内存: {data['mem_percent']}% | 磁盘: {[d['percent'] for d in data['disks']]}")
    
    # ── 阈值告警检测 ──
    critical_count = check_alerts(data, alert_file=args.alert_file)
    
    # ── AlertManager 告警引擎（可配置阈值 + 多通道通知）──
    try:
        from scripts.alert_manager import AlertManager
        am = AlertManager()
        # 使用收集到的数据检查并触发告警
        am.check_and_dispatch(data)
        # 如果配置了 webhook 或 email，也会通过相应通道推送
    except ImportError:
        pass  # alert_manager 未安装不影响主功能
    except Exception as e:
        print(f"  ⚠️ AlertManager 异常: {e}", file=sys.stderr)
    
    # ── AgentMail告警通知 ──
    if args.agentmail and critical_count > 0:
        alerts = []
        cpu = data.get('cpu_percent', 0)
        if cpu > 90: alerts.append(('CRITICAL', f'CPU使用率 {cpu}% > 90%'))
        mem = data.get('mem_percent', 0)
        if mem > 92: alerts.append(('CRITICAL', f'内存使用率 {mem}% > 92%'))
        for d in data.get('disks', []):
            if d['percent'] > 95: alerts.append(('CRITICAL', f'磁盘 {d["mount"]} 使用率 {d["percent"]}%'))
        send_agentmail_alert(alerts, data)
    
    # Default output path
    if not args.output:
        date_str = datetime.now().strftime('%Y-%m-%d')
        args.output = f"/home/admin/GenericAgent/sche_tasks/done/{date_str}_健康看板.html"
    
    html = generate_html(data, report_path=args.output)
    save_report(html, args.output)
    
    if args.open:
        import webbrowser
        webbrowser.open(f'file://{os.path.abspath(args.output)}')
    
    # 告警退出码: 有CRITICAL告警则返回1
    if critical_count > 0:
        sys.exit(1)
    
    return args.output


if __name__ == '__main__':
    main()
