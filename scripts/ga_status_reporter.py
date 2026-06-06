#!/usr/bin/env python3
"""ga_status_reporter.py — GenericAgent 状态报告自动报送（通过AgentMail）

用途：
  - 收集GA系统健康信息（CPU/内存/磁盘/进程/最近任务）
  - 通过AgentMail发送到指定inbox
  - 支持--to参数自定义收件人，支持--once参数单次执行

典型用法：
  python3 scripts/ga_status_reporter.py                    # 发送到默认inbox（自检）
  python3 scripts/ga_status_reporter.py --to user@mail.com  # 发送到指定邮箱
  python3 scripts/ga_status_reporter.py --once              # 单次发送后退出

集成到cron：
  0 */6 * * * cd /home/admin/GenericAgent && python3 scripts/ga_status_reporter.py --once
"""
import os, sys, json, platform, datetime, subprocess, argparse

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if not os.path.isdir(os.path.join(CODE_ROOT, 'memory')):
    CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODE_ROOT)

def get_system_info():
    """收集系统健康信息"""
    info = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'hostname': platform.node(),
        'platform': platform.platform(),
        'python': sys.version.split()[0],
    }
    # CPU
    try:
        load = os.getloadavg()
        info['cpu_load_1min'] = round(load[0], 2)
        info['cpu_load_5min'] = round(load[1], 2)
        info['cpu_load_15min'] = round(load[2], 2)
    except Exception:
        pass
    # Memory
    try:
        import psutil
        mem = psutil.virtual_memory()
        info['memory_total_gb'] = round(mem.total / 1024**3, 1)
        info['memory_used_gb'] = round(mem.used / 1024**3, 1)
        info['memory_percent'] = mem.percent
        disk = psutil.disk_usage('/')
        info['disk_total_gb'] = round(disk.total / 1024**3, 1)
        info['disk_used_gb'] = round(disk.used / 1024**3, 1)
        info['disk_percent'] = disk.percent
    except ImportError:
        pass
    # GA process
    try:
        result = subprocess.run(['ps', '-eo', 'pid,user,%cpu,%mem,comm', '--sort=-%cpu'], 
                              capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split('\n')
        ga_procs = [l for l in lines if 'python' in l.lower() or 'agent' in l.lower()]
        info['ga_processes'] = ga_procs[:5]
        info['total_processes'] = len(lines) - 1 if len(lines) > 1 else 0
    except Exception:
        pass
    return info

def get_recent_tasks():
    """读取最近任务历史"""
    hist_path = os.path.join(CODE_ROOT, 'temp', 'autonomous_reports', 'history.txt')
    tasks = []
    if os.path.exists(hist_path):
        with open(hist_path) as f:
            lines = f.readlines()
        # 取最后10条非空行
        for line in reversed(lines):
            line = line.strip()
            if line and '|' in line:
                tasks.append(line)
                if len(tasks) >= 10:
                    break
    return tasks

def get_todo_status():
    """读取TODO状态"""
    todo_path = os.path.join(CODE_ROOT, 'temp', 'TODO.txt')
    todos = []
    if os.path.exists(todo_path):
        with open(todo_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('[ ]') or line.startswith('[x]'):
                    todos.append(line)
    return todos

def build_report():
    """构建HTML报告"""
    sys_info = get_system_info()
    tasks = get_recent_tasks()
    todos = get_todo_status()
    
    lines = []
    lines.append('<h2>🤖 GenericAgent 状态报告</h2>')
    lines.append(f'<p><b>时间：</b>{sys_info["timestamp"]}</p>')
    lines.append(f'<p><b>主机：</b>{sys_info["hostname"]}</p>')
    lines.append(f'<p><b>平台：</b>{sys_info["platform"]}</p>')
    
    # 系统资源
    lines.append('<h3>📊 系统资源</h3>')
    lines.append('<table border="1" cellpadding="4" style="border-collapse:collapse">')
    lines.append('<tr><th>指标</th><th>值</th></tr>')
    for k, v in sys_info.items():
        if k in ('timestamp', 'hostname', 'platform', 'python', 'ga_processes', 'total_processes'):
            continue
        lines.append(f'<tr><td>{k}</td><td>{v}</td></tr>')
    lines.append(f'<tr><td>Python</td><td>{sys_info.get("python", "N/A")}</td></tr>')
    lines.append(f'<tr><td>总进程</td><td>{sys_info.get("total_processes", "N/A")}</td></tr>')
    lines.append('</table>')
    
    # GA进程
    ga_procs = sys_info.get('ga_processes', [])
    if ga_procs:
        lines.append('<h4>🧵 GA相关进程 (top5)</h4>')
        lines.append('<pre>' + '\n'.join(ga_procs) + '</pre>')
    
    # 最近任务
    if tasks:
        lines.append('<h3>📋 最近任务</h3>')
        lines.append('<ul>')
        for t in tasks:
            lines.append(f'<li>{t}</li>')
        lines.append('</ul>')
    
    # TODO
    if todos:
        lines.append('<h3>📌 待办</h3>')
        lines.append('<ul>')
        for t in todos:
            status = '✅' if t.startswith('[x]') else '⏳'
            lines.append(f'<li>{status} {t[4:]}</li>')
        lines.append('</ul>')
    
    return '\n'.join(lines)

def send_report(to_email=None):
    """通过AgentMail发送报告"""
    from memory.keychain import keys
    from agentmail import AgentMail
    
    api_key = keys.AGENTMAIL_API_KEY
    client = AgentMail(api_key=api_key.use())
    
    # 获取默认inbox
    resp = client.inboxes.list()
    if not resp.inboxes:
        print("ERROR: No inbox found")
        return False
    
    default_inbox = resp.inboxes[0]
    inbox_id = default_inbox.inbox_id
    
    if not to_email:
        to_email = default_inbox.email
    
    html_body = build_report()
    
    result = client.inboxes.messages.send(
        inbox_id=inbox_id,
        to=[to_email],
        subject=f'🤖 GA Status Report - {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}',
        html=html_body
    )
    print(f"✅ 报告已发送到 {to_email}")
    print(f"   消息ID: {result.message_id}")
    return True

def main():
    parser = argparse.ArgumentParser(description='GenericAgent Status Reporter via AgentMail')
    parser.add_argument('--to', help='收件人邮箱（默认发给自己）')
    parser.add_argument('--once', action='store_true', help='单次发送后退出')
    args = parser.parse_args()
    
    if args.once:
        send_report(args.to)
        return
    
    # 交互模式
    print("=" * 50)
    print("GA Status Reporter")
    print("=" * 50)
    send_report(args.to)

if __name__ == '__main__':
    main()
