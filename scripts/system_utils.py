"""
system_utils.py — GA系统信息工具
Morphling吸收目标: jc (CLI-to-JSON转换器)
类型: 调用型 morphling — 封装jc为GA可用的Python接口

用法:
    from scripts.system_utils import ps_info, disk_info, network_info, ...
"""

import subprocess
import json
import os
from typing import Optional


def _jc_parse(cmd: str, parser: str) -> list:
    """执行命令并通过jc解析输出为JSON (安全: 无shell=True)"""
    import shlex
    try:
        p1 = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        result = subprocess.run(
            ['jc', f'--{parser}'],
            stdin=p1.stdout,
            capture_output=True,
            text=True,
            timeout=10,
        )
        p1.stdout.close()
        p1.wait(timeout=5)
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired, Exception):
        return []


def ps_info() -> list:
    """获取进程列表(ps aux → JSON)"""
    return _jc_parse("ps aux", "ps")


def disk_info() -> list:
    """获取磁盘使用(df -h → JSON)"""
    return _jc_parse("df -h", "df")


def disk_inodes() -> list:
    """获取inode使用(df -i → JSON)"""
    return _jc_parse("df -i", "df")


def network_connections() -> list:
    """获取网络连接(ss -tlnp → JSON)"""
    return _jc_parse("ss -tlnp", "ss")


def network_sockets() -> list:
    """获取所有套接字(ss -tulanp → JSON)"""
    return _jc_parse("ss -tulanp", "ss")


def mem_info() -> dict:
    """获取内存信息(free -m → JSON)"""
    data = _jc_parse("free -m", "free")
    if data and len(data) > 0:
        return data[0]
    return {}


def uptime_info() -> dict:
    """获取运行时间(uptime → JSON)"""
    data = _jc_parse("uptime", "uptime")
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data:
        return data[0]
    return {}


def users() -> list:
    """获取登录用户(who → JSON)"""
    return _jc_parse("who", "who")


def system_snapshot() -> dict:
    """全系统快照"""
    return {
        "processes": len(ps_info()),
        "disk": disk_info(),
        "memory": mem_info(),
        "uptime": uptime_info(),
        "network_ports": len(network_connections()),
        "users": users(),
    }


def top_processes(limit: int = 10, sort_by: str = "cpu_percent") -> list:
    """获取Top N进程"""
    procs = ps_info()
    if not procs:
        return []
    # 按指定字段降序排序
    sorted_procs = sorted(procs, key=lambda p: float(p.get(sort_by, 0) or 0), reverse=True)
    return sorted_procs[:limit]


# ============================================================
# 自检
# ============================================================
if __name__ == "__main__":
    import sys

    snap = system_snapshot()
    print(f"系统快照:")
    print(f"  进程数: {snap['processes']}")
    print(f"  内存: {snap['memory'].get('total', '?')}MB total, {snap['memory'].get('used', '?')}MB used")
    print(f"  Uptime: {snap['uptime'].get('uptime', '?')}")
    print(f"  监听端口: {snap['network_ports']}")
    print(f"  登录用户: {snap['users']}")
    print()
    print(f"Top 5 CPU进程:")
    for p in top_processes(5, "cpu_percent"):
        print(f"  {p.get('pid','?'):>6}  {float(p.get('cpu_percent',0)):>5.1f}%  {p.get('command','')[:60]}")
    print()
    print("✅ system_utils.py morphling 吸收完成")
