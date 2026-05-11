"""
ga_cli/cli.py - GenericAgent 命令行分发系统

通过 python -m ga_cli <命令> 或 ga <命令> 调用
"""
import os, sys, subprocess, argparse, textwrap

# Windows GBK 终端兼容
if sys.platform == "win32" and sys.stdout.encoding and sys.stdout.encoding.lower() in ("gbk", "gb2312"):
    sys.stdout.reconfigure(errors="replace") if hasattr(sys.stdout, "reconfigure") else None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)


def _frontends():
    return os.path.join(PROJECT_DIR, "frontends")

def _reflect():
    return os.path.join(PROJECT_DIR, "reflect")


def launch_frontend(cmd_parts, args=None):
    """启动前端/工具进程"""
    full_cmd = []
    for part in cmd_parts:
        part = part.replace("{PROJECT_DIR}", PROJECT_DIR)
        part = part.replace("{FRONTENDS}", _frontends())
        part = part.replace("{REFLECT}", _reflect())
        full_cmd.append(part)

    # 插入额外参数
    if args:
        full_cmd.extend(args)

    print(f"🚀 {' '.join(full_cmd)}")
    sys.stdout.flush()
    os.chdir(PROJECT_DIR)
    proc = subprocess.Popen(full_cmd)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        sys.exit(0)


COMMANDS = {
    "gui": {
        "help": "启动桌面GUI (qtapp)",
        "desc": "启动基于 PyQt5 的完整桌面聊天界面（气泡代码高亮、文件拖拽、历史搜索）",
        "cmd": ["python", "{FRONTENDS}/qtapp.py"],
    },
    "web": {
        "help": "启动Web增强版 (stapp2)  加 --native 使用 webview 桌面壳",
        "desc": "启动 Streamlit Web 界面，浏览器访问，适合远程/跨设备",
        "cmd": ["python", "-m", "streamlit", "run", "{FRONTENDS}/stapp2.py",
                "--server.headless", "true"],
        "flags": {"--native": {"help": "用 webview 原生窗口启动(stapp基础版)", "cmd": ["python", "{PROJECT_DIR}/launch.pyw"]}},
    },
    "configure": {
        "help": "运行初始配置向导 (configure_mykey.py)",
        "desc": "首次安装后配置 API Key、模型参数等基础设置",
        "cmd": ["python", "{PROJECT_DIR}/assets/configure_mykey.py"],
    },
    "hub": {
        "help": "启动 Hub 管理器 (launcher)",
        "desc": "启动 hub 前端管理面板（系统托盘 + 浏览器界面）",
        "cmd": ["python", "{PROJECT_DIR}/hub.pyw"],
    },
    "pet": {
        "help": "启动桌面宠物",
        "desc": "启动桌面宠物皮肤系统，桌面上陪伴你的虚拟宠物",
        "cmd": ["python", "{FRONTENDS}/desktop_pet_v2.pyw"],
    },
    "tui": {
        "help": "启动终端 TUI (tuiapp)",
        "desc": "启动终端图形界面（Textual），适合纯终端环境或 SSH",
        "cmd": ["python", "{FRONTENDS}/tuiapp.py"],
    },
    "cli": {
        "help": "启动 CLI 对话 (agentmain)",
        "desc": "启动命令行交互对话模式，最轻量的使用方式",
        "cmd": ["python", "{PROJECT_DIR}/agentmain.py"],
    },
    "launch": {
        "help": "启动 webview 桌面壳 (launch.pyw)",
        "desc": "以原生窗口形式包装 stapp Web 界面（基于 pywebview）",
        "cmd": ["python", "{PROJECT_DIR}/launch.pyw"],
    },
    "status": {
        "help": "检查运行状态",
        "desc": "检查当前是否已有 GenericAgent 进程在运行",
        "cmd": None,
        "internal": True,
    },
    "update": {
        "help": "更新项目 (git pull + pip install)",
        "desc": "从 Git 拉取最新代码并更新依赖",
        "cmd": None,
        "internal": True,
    },
    "list": {
        "help": "列出所有可用前端/服务",
        "desc": "显示所有注册的命令",
        "cmd": None,
        "internal": True,
    },
}


def cmd_list():
    """展示所有可用命令"""
    print()
    frontend_cmds = [(k, v) for k, v in sorted(COMMANDS.items()) if v["cmd"] is not None]
    internal_cmds = [(k, v) for k, v in sorted(COMMANDS.items()) if v["cmd"] is None]

    print(f"  {'命令':20s}  {'说明'}")
    print(f"  {'━'*20}  {'━'*40}")
    for name, info in frontend_cmds:
        print(f"  {name:20s}  {info.get('help', info['desc'][:40])}")
    print()
    for name, info in internal_cmds:
        print(f"  {name:20s}  {info.get('help', info['desc'][:40])}")
    print()


def cmd_status():
    """检查进程状态"""
    import psutil
    running = [p for p in psutil.process_iter(['pid', 'name', 'cmdline'])
               if p.info['cmdline'] and any('agentmain' in c for c in p.info['cmdline'])]
    if running:
        print(f"🟢 运行中: {len(running)} 个进程")
        for p in running:
            print(f"   PID {p.info['pid']} — {' '.join(p.info['cmdline'][:3])}")
    else:
        print("⚫ GenericAgent 进程未运行")


def cmd_update():
    """git pull + pip install"""
    os.chdir(PROJECT_DIR)
    print("🔄 git pull...")
    r = subprocess.run(["git", "pull"], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
    print("📦 pip install...")
    r2 = subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."],
                        capture_output=True, text=True)
    print(r2.stdout[-500:] if r2.stdout else "")
    if r2.returncode != 0:
        print(r2.stderr[-500:])


def main():
    parser = argparse.ArgumentParser(
        prog="ga",
        description="GenericAgent 全局命令入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              ga gui               启动桌面 GUI
              ga web               启动 Web 增强版
              ga web --native      启动 Web 基础版(桌面壳)
              ga pet               启动桌面宠物 v2
              ga launch            启动 webview 桌面壳
              ga list              列出所有命令
        """),
    )
    parser.add_argument("command", nargs="?", help="命令名")
    parser.add_argument("args", nargs="*", help="子命令参数")
    parser.add_argument("-v", "--version", action="store_true", help="显示版本")

    args, unknown = parser.parse_known_args()

    if args.version:
        print("GenericAgent v0.1.0")
        return

    cmd = args.command

    if not cmd or cmd == "help":
        parser.print_help()
        print("\n--- 命令列表 ---")
        cmd_list()
        return

    if cmd == "list":
        cmd_list()
        return

    if cmd == "status":
        cmd_status()
        return

    if cmd == "update":
        cmd_update()
        return

    if cmd not in COMMANDS:
        print(f"❌ 未知命令: {cmd}")
        print(f"   使用 'ga list' 查看可用命令")
        sys.exit(1)

    info = COMMANDS[cmd]

    # 内置命令走内部逻辑
    if info.get("internal"):
        print(f"❌ 命令 {cmd} 没有配置启动命令")
        sys.exit(1)

    extra = list(args.args) + unknown

    # === 处理命令特有 flags ===
    cmd_parts = list(info["cmd"])

    # 处理 flags (如 --native)
    flags = info.get("flags", {})
    for flag_name, flag_info in flags.items():
        if flag_name in extra:
            cmd_parts = list(flag_info["cmd"])
            extra.remove(flag_name)
            break

    launch_frontend(cmd_parts, extra if extra else None)


if __name__ == "__main__":
    main()
