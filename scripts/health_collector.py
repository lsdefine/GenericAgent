#!/usr/bin/env python3
"""离线健康数据采集器 - 采集系统数据输出JSON"""
import sys, os, json, argparse, socket
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.system_utils import mem_info, disk_info, uptime_info, ps_info

def collect():
    mem = mem_info()
    disk_data = disk_info()
    upt = uptime_info()
    procs = ps_info()
    load_1 = upt.get("load_1m", 0) or upt.get("load", {}).get("min1", 0) or 0
    load_5 = upt.get("load_5m", 0) or 0
    load_15 = upt.get("load_15m", 0) or 0
    cpu_pct = upt.get("cpu_percent", 0) or procs.get("cpu_percent", 0) if isinstance(procs, dict) else 0

    total_mb = float(mem.get("total", 0))
    used_mb = float(mem.get("used", 0))
    total_gb = round(total_mb / 1024, 1)
    used_gb = round(used_mb / 1024, 1)
    mem_pct = round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": os.uname().nodename,
        "cpu": {"percent": cpu_pct, "count": os.cpu_count() or 0},
        "memory": {"percent": mem_pct, "total_gb": total_gb, "used_gb": used_gb},
        "load_avg": [float(load_1), float(load_5), float(load_15)],
        "process_count": len(procs) if isinstance(procs, list) else 0,
        "disk": [],
        "uptime": upt.get("uptime", ""),
        "services": {},
    }

    for d in disk_data[:10]:
        if isinstance(d, dict):
            snapshot["disk"].append({
                "mount": d.get("mount", "") or d.get("mounted", "") or "",
                "total_gb": round(float(d.get("total", 0)) / (1024**3), 1) if d.get("total") else 0,
                "used_gb": round(float(d.get("used", 0)) / (1024**3), 1) if d.get("used") else 0,
                "percent": round(float(d.get("use_percent", 0) or 0), 1),
            })

    for port, name in [(8081, "health_server"), (11343, "openllm"), (20241, "cloudflared"), (18790, "nanobot")]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex(('127.0.0.1', port))
            snapshot["services"][name] = "running" if result == 0 else "stopped"
            s.close()
        except:
            snapshot["services"][name] = "unknown"

    return snapshot

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='temp/health_snapshot.json')
    args = parser.parse_args()
    data = collect()
    out_dir = os.path.dirname(args.output) or '.'
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"✅ 健康快照: {args.output}")
    print(f"   CPU: {data['cpu']['percent']}% | 内存: {data['memory']['percent']}% | 进程: {data['process_count']}")
