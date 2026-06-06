#!/usr/bin/env python3
"""
svc.py — GA 服务管理工具

管理 systemd 服务的 enable/disable/status:
  python3 scripts/svc.py list              # 列出所有 GA 服务
  python3 scripts/svc.py enable <name>     # 安装并启用 systemd unit
  python3 scripts/svc.py disable <name>    # 停用并移除 systemd unit
  python3 scripts/svc.py status <name>     # 查看服务状态
  python3 scripts/svc.py restart <name>    # 重启服务

可用服务:
  health-server   系统健康看板 HTTP 服务
"""

import os, sys, json, subprocess, shutil
from pathlib import Path

GA_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIT_DIR = "/etc/systemd/system"
VENV_PYTHON = "/home/admin/.hermes/hermes-agent/venv/bin/python3"
USER = os.environ.get("USER", "admin")


SERVICE_DEFS = {
    "health-server": {
        "description": "GA Health Dashboard HTTP Service",
        "exec": f"{VENV_PYTHON} {GA_HOME}/scripts/health_server.py --port 8081",
        "working_dir": GA_HOME,
        "restart": "always",
        "wants": "network-online.target",
    },
}


def _unit_path(name):
    sname = name.replace("_", "-")
    return os.path.join(UNIT_DIR, f"{sname}.service")


def _generate_unit(name, defn):
    return f"""[Unit]
Description={defn['description']}
After=network-online.target
Wants={defn.get('wants', 'network-online.target')}

[Service]
Type=simple
User={USER}
WorkingDirectory={defn['working_dir']}
ExecStart={defn['exec']}
Restart={defn.get('restart', 'always')}
RestartSec=5
StandardOutput=append:{GA_HOME}/temp/{name}.log
StandardError=append:{GA_HOME}/temp/{name}.log

[Install]
WantedBy=multi-user.target
"""


def _cmd_list():
    print("可用服务:")
    for name in SERVICE_DEFS:
        path = _unit_path(name)
        installed = "✅" if os.path.exists(path) else "⬜"
        print(f"  {installed} {name}  — {SERVICE_DEFS[name]['description']}")


def _cmd_enable(name):
    if name not in SERVICE_DEFS:
        print(f"未知服务: {name}")
        return False
    defn = SERVICE_DEFS[name]
    unit_content = _generate_unit(name, defn)
    unit_path = _unit_path(name)

    # Write unit file (need sudo)
    try:
        subprocess.run(["sudo", "tee", unit_path], input=unit_content,
                       capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ 写入 unit 文件失败: {e.stderr}")
        return False

    # Reload and enable
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", f"{name}.service"], check=True)
    subprocess.run(["sudo", "systemctl", "start", f"{name}.service"], check=True)
    print(f"✅ {name} 已启用并启动")
    return True


def _cmd_disable(name):
    unit_path = _unit_path(name)
    subprocess.run(["sudo", "systemctl", "stop", f"{name}.service"], capture_output=True)
    subprocess.run(["sudo", "systemctl", "disable", f"{name}.service"], capture_output=True)
    if os.path.exists(unit_path):
        subprocess.run(["sudo", "rm", unit_path], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    print(f"✅ {name} 已停用")
    return True


def _cmd_status(name):
    if name not in SERVICE_DEFS:
        print(f"未知服务: {name}")
        return
    r = subprocess.run(["systemctl", "status", f"{name}.service"],
                       capture_output=True, text=True)
    print(r.stdout[:2000] if r.stdout else r.stderr[:2000])


def _cmd_restart(name):
    subprocess.run(["sudo", "systemctl", "restart", f"{name}.service"], check=True)
    print(f"✅ {name} 已重启")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 scripts/svc.py <list|enable|disable|status|restart> [name]")
        sys.exit(1)

    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else ""

    if cmd == "list":
        _cmd_list()
    elif cmd == "enable":
        _cmd_enable(name)
    elif cmd == "disable":
        _cmd_disable(name)
    elif cmd == "status":
        _cmd_status(name)
    elif cmd == "restart":
        _cmd_restart(name)
    else:
        print(f"未知命令: {cmd}")
