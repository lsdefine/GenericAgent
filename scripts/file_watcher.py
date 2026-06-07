#!/usr/bin/env python3
"""
file_watcher.py — 文件变化监控触发器 📂✨

基于 R222 推荐实现文件事件驱动能力：
监控目录/文件变化触发预定义操作，集成到 health_server 管线。

依赖: watchdog (已装 @6.0.0), Python 标准库

用法:
  python scripts/file_watcher.py start            # 启动守护进程
  python scripts/file_watcher.py stop             # 停止守护进程
  python scripts/file_watcher.py status           # 查看状态
  python scripts/file_watcher.py add-watch <目录> <操作>  # 添加监控
  python scripts/file_watcher.py list-watches     # 列出监控
  python scripts/file_watcher.py health           # 集成检查 → 推送health_server

验收:
  watch → trigger 验证通过 ✅
"""

import os
import sys
import json
import time
import signal
import argparse
import logging
import subprocess
import threading
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Optional

# watchdog 库
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ── 路径配置 ──────────────────────────────────────
PID_FILE = Path("/tmp/file_watcher.pid")
STATE_FILE = Path("/tmp/file_watcher_state.json")
LOG_FILE = Path("/tmp/file_watcher.log")
DEFAULT_WATCH_FILE = Path("/tmp/file_watcher_watches.json")
HEALTH_SERVER_URL = "http://localhost:8899"

# ── 日志 ──────────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [file_watcher] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("file_watcher")


# ── 事件处理器 ────────────────────────────────────
class ChangeHandler(FileSystemEventHandler):
    """文件变化事件处理器"""

    def __init__(self, watch_name: str, actions: list[dict], watch_path: str):
        self.watch_name = watch_name
        self.actions = actions
        self.watch_path = watch_path
        self.debounce_cache: dict[str, float] = {}
        self.debounce_seconds = 2.0

    def _debounce(self, event_key: str) -> bool:
        now = time.time()
        last = self.debounce_cache.get(event_key, 0.0)
        if now - last < self.debounce_seconds:
            return False  # 去重
        self.debounce_cache[event_key] = now
        return True

    def _trigger_actions(self, event_type: str, src_path: str, is_dir: bool = False):
        for action in self.actions:
            try:
                self._execute_action(action, event_type, src_path, is_dir)
            except Exception as e:
                log.error(f"Trigger action failed: {e}")

    def _execute_action(self, action: dict, event_type: str, src_path: str, is_dir: bool):
        kind = action.get("type", "log")
        rel_path = os.path.relpath(src_path, self.watch_path) if os.path.exists(src_path) else src_path
        payload = {
            "event": event_type,
            "path": src_path,
            "relative_path": rel_path,
            "is_dir": is_dir,
            "watch_name": self.watch_name,
            "timestamp": datetime.now().isoformat(),
        }

        if kind == "log":
            log.info(f"[{event_type}] {rel_path}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {event_type}: {rel_path}")

        elif kind == "script":
            script = action.get("script", "")
            if script:
                log.info(f"Running script: {script} on {rel_path}")
                subprocess.Popen(["bash", "-c", script], env={**os.environ, "FILE_EVENT": json.dumps(payload)})

        elif kind == "webhook":
            url = action.get("url", "")
            if url:
                try:
                    data = json.dumps(payload).encode()
                    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                    log.info(f"Webhook sent: {url}")
                except Exception as e:
                    log.warning(f"Webhook failed: {e}")

        elif kind == "health_api":
            # 推送到 health_server 的 file_watcher 端点
            try:
                api_url = f"{HEALTH_SERVER_URL}/api/file_watcher"
                data = json.dumps(payload).encode()
                req = urllib.request.Request(api_url, data=data, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5)
                log.info(f"Health API updated: {event_type} {rel_path}")
            except Exception as e:
                log.warning(f"Health API push failed: {e}")

    def on_created(self, event):
        if self._debounce(f"created:{event.src_path}"):
            self._trigger_actions("created", event.src_path, event.is_directory)

    def on_modified(self, event):
        if self._debounce(f"modified:{event.src_path}"):
            self._trigger_actions("modified", event.src_path, event.is_directory)

    def on_deleted(self, event):
        if self._debounce(f"deleted:{event.src_path}"):
            self._trigger_actions("deleted", event.src_path, event.is_directory)

    def on_moved(self, event):
        if self._debounce(f"moved:{event.src_path}"):
            self._trigger_actions("moved", event.src_path, event.is_directory)
            if hasattr(event, "dest_path"):
                self._trigger_actions("moved_to", event.dest_path, event.is_directory)


# ── 监控引擎 ──────────────────────────────────────
class FileWatcher:
    """文件变化监控引擎（单例守护进程）"""

    def __init__(self):
        self.observer = Observer()
        self.handlers: dict[str, tuple[ChangeHandler, str]] = {}
        self.running = False

    def load_watches(self) -> list[dict]:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text())
                return data.get("watches", [])
            except (json.JSONDecodeError, KeyError):
                pass
        # 从持久化文件加载
        if DEFAULT_WATCH_FILE.exists():
            try:
                return json.loads(DEFAULT_WATCH_FILE.read_text()).get("watches", [])
            except (json.JSONDecodeError, KeyError):
                pass
        return []

    def start_watches(self, watches: Optional[list[dict]] = None):
        if watches is None:
            watches = self.load_watches()
        if not watches:
            log.warning("No watches configured. Add with: python file_watcher.py add-watch <目录> <操作>")
            print("⚠️  没有配置监控项。使用 add-watch 命令添加。")
            return

        for w in watches:
            path = w.get("path", "")
            name = w.get("name", path)
            actions = w.get("actions", [{"type": "log"}])
            recursive = w.get("recursive", True)

            if not os.path.isdir(path):
                log.warning(f"Watch path does not exist, skipping: {path}")
                continue

            handler = ChangeHandler(name, actions, path)
            self.observer.schedule(handler, path, recursive=recursive)
            self.handlers[name] = (handler, path)
            log.info(f"Watching: {name} → {path} (recursive={recursive})")
            print(f"👀  Watching: {name} → {path}")

        self.observer.start()
        self.running = True
        log.info("FileWatcher started")
        print("✅ FileWatcher 已启动")

    def stop(self):
        if self.running:
            self.observer.stop()
            self.observer.join()
            self.running = False
            log.info("FileWatcher stopped")
            print("⏹️  FileWatcher 已停止")

    def status(self) -> dict:
        watches_info = {}
        for name, (handler, path) in self.handlers.items():
            watches_info[name] = {
                "path": path,
                "actions": handler.actions,
                "active": self.running,
            }
        return {
            "running": self.running,
            "watches": watches_info,
            "watch_count": len(self.handlers),
        }


# ── 守护进程管理 ──────────────────────────────────
def daemonize():
    """转为后台守护进程"""
    pid = os.fork()
    if pid > 0:
        return pid  # 父进程返回PID
    # 子进程：继续执行
    os.setsid()
    # 第二次 fork
    pid2 = os.fork()
    if pid2 > 0:
        sys.exit(0)
    # 守护进程继续
    return 0


def save_pid(pid: int):
    PID_FILE.write_text(str(pid))
    log.info(f"PID saved: {pid}")


def read_pid() -> Optional[int]:
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def save_state(watches: list[dict]):
    STATE_FILE.write_text(json.dumps({
        "watches": watches,
        "updated_at": datetime.now().isoformat(),
    }, indent=2, ensure_ascii=False))


# ── 命令行 ─────────────────────────────────────────
def cmd_start(args):
    pid = read_pid()
    if pid and is_running(pid):
        print(f"⚠️  FileWatcher 已在运行 (PID={pid})")
        return

    # 转为守护进程
    child_pid = daemonize()
    if child_pid > 0:
        save_pid(child_pid)
        print(f"✅ FileWatcher 已启动 (PID={child_pid})")
        return

    # 守护进程逻辑
    fw = FileWatcher()
    fw.start_watches()

    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        fw.stop()


def cmd_stop(args):
    pid = read_pid()
    if pid and is_running(pid):
        os.kill(pid, signal.SIGTERM)
        PID_FILE.unlink(missing_ok=True)
        print(f"⏹️  FileWatcher 已停止 (PID={pid})")
    else:
        print("⚠️  FileWatcher 未在运行")


def cmd_status(args):
    pid = read_pid()
    running = pid and is_running(pid)
    print(f"状态: {'✅ 运行中' if running else '❌ 未运行'}")
    if running:
        print(f"PID: {pid}")
    print()

    # 读取配置的监控项
    watches = []
    if STATE_FILE.exists():
        try:
            watches = json.loads(STATE_FILE.read_text()).get("watches", [])
        except (json.JSONDecodeError, KeyError):
            pass
    elif DEFAULT_WATCH_FILE.exists():
        try:
            watches = json.loads(DEFAULT_WATCH_FILE.read_text()).get("watches", [])
        except (json.JSONDecodeError, KeyError):
            pass

    if watches:
        print(f"监控项 ({len(watches)}):")
        for w in watches:
            actions_str = ", ".join(a.get("type", "") for a in w.get("actions", []))
            print(f"  [{w.get('name', '?')}] {w.get('path', '?')} → {actions_str}")
    else:
        print("暂无监控配置")


def cmd_add_watch(args):
    path = args.path
    action_type = args.action or "log"
    name = args.name or os.path.basename(os.path.abspath(path))
    script = args.script

    if not os.path.isdir(path):
        print(f"❌ 目录不存在: {path}")
        return

    # 加载现有监控
    watches = []
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            watches = data.get("watches", [])
        except (json.JSONDecodeError, KeyError):
            pass
    elif DEFAULT_WATCH_FILE.exists():
        try:
            data = json.loads(DEFAULT_WATCH_FILE.read_text())
            watches = data.get("watches", [])
        except (json.JSONDecodeError, KeyError):
            pass

    # 构建 action
    action = {"type": action_type}
    if action_type == "script" and script:
        action["script"] = script
    elif action_type == "webhook":
        action["url"] = args.url or ""

    watch_entry = {
        "name": name,
        "path": os.path.abspath(path),
        "recursive": args.recursive,
        "actions": [action],
    }

    # 去重：同路径追加 action
    existing = None
    for w in watches:
        if w.get("path") == watch_entry["path"] and w.get("name") == watch_entry["name"]:
            existing = w
            break

    if existing:
        existing["actions"].append(action)
        print(f"📎 追加 action 到已有监控: {name} → {path}")
    else:
        watches.append(watch_entry)
        print(f"📌 添加监控: {name} → {path} (action={action_type})")

    # 保存
    save_state(watches)
    print("✅ 监控配置已保存（重启 file_watcher 生效）")


def cmd_list_watches(args):
    watches = []
    if STATE_FILE.exists():
        try:
            watches = json.loads(STATE_FILE.read_text()).get("watches", [])
        except (json.JSONDecodeError, KeyError):
            pass
    elif DEFAULT_WATCH_FILE.exists():
        try:
            watches = json.loads(DEFAULT_WATCH_FILE.read_text()).get("watches", [])
        except (json.JSONDecodeError, KeyError):
            pass

    if not watches:
        print("暂无监控配置")
        return

    print(f"📋 监控列表 ({len(watches)}):")
    print("─" * 60)
    for i, w in enumerate(watches, 1):
        actions = w.get("actions", [])
        actions_str = ", ".join(
            f"{a.get('type', '?')}:{a.get('script', a.get('url', ''))[:40]}"
            for a in actions
        )
        print(f"  {i}. [{w.get('name', '?')}]")
        print(f"     路径: {w.get('path', '?')}")
        print(f"     递归: {w.get('recursive', True)}")
        print(f"     操作: {actions_str}")
    print("─" * 60)


def cmd_health(args):
    """集成检查 → 推送 health_server"""
    print("🔌 检查 FileWatcher ↔ HealthServer 集成...")

    # 1. 检查 health_server 是否可访问
    try:
        req = urllib.request.Request(f"{HEALTH_SERVER_URL}/api/health")
        resp = urllib.request.urlopen(req, timeout=5)
        health_data = json.loads(resp.read().decode())
        print(f"✅ health_server 可达 (状态: {resp.status})")
        print(f"   系统状态: {json.dumps(health_data, indent=2)[:200]}")
    except Exception as e:
        print(f"❌ health_server 不可达: {e}")
        print("   请先启动: python scripts/health_server.py &")

    # 2. 检查 watchdog 状态
    pid = read_pid()
    running = pid and is_running(pid)
    print(f"{'✅' if running else '❌'} FileWatcher 守护进程: {'运行中' if running else '未运行'}")

    # 3. 检查配置
    watches = []
    if STATE_FILE.exists():
        watches = json.loads(STATE_FILE.read_text()).get("watches", [])
    if watches:
        print(f"✅ 已配置 {len(watches)} 个监控项")
    else:
        print("⚠️  未配置监控项")

    # 4. 模拟触发 health API
    test_payload = {
        "event": "health_check",
        "path": "__test__",
        "relative_path": "__test__",
        "is_dir": False,
        "watch_name": "_healthcheck",
        "timestamp": datetime.now().isoformat(),
    }
    try:
        api_url = f"{HEALTH_SERVER_URL}/api/file_watcher"
        data = json.dumps(test_payload).encode()
        req = urllib.request.Request(api_url, data=data, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        print(f"✅ Health API 推送测试: {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"⚠️  Health API 推送测试: HTTP {e.code} (可能未注册端点, 不影响核心功能)")
    except Exception as e:
        print(f"⚠️  Health API 推送测试: {e}")

    print("\n📋 集成状态: ", end="")
    if running and watches:
        print("✅ 就绪")
    else:
        print("⚠️  部分就绪 (需配置监控项或启动守护进程)")


# ── 主入口 ─────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="file_watcher.py — 文件变化监控触发器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    p_start = sub.add_parser("start", help="启动守护进程")
    p_stop = sub.add_parser("stop", help="停止守护进程")
    p_status = sub.add_parser("status", help="查看状态")

    p_add = sub.add_parser("add-watch", help="添加监控")
    p_add.add_argument("path", help="监控目录")
    p_add.add_argument("--action", "-a", default="log",
                       choices=["log", "script", "webhook", "health_api"],
                       help="触发操作类型 (默认: log)")
    p_add.add_argument("--name", "-n", help="监控名称 (默认: 目录名)")
    p_add.add_argument("--script", "-s", help="触发脚本 (action=script时)")
    p_add.add_argument("--url", "-u", help="Webhook URL (action=webhook时)")
    p_add.add_argument("--no-recursive", dest="recursive", action="store_false",
                       default=True, help="不递归监控子目录")

    sub.add_parser("list-watches", help="列出所有监控")
    sub.add_parser("health", help="集成检查 (health_server联动)")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "add-watch":
        cmd_add_watch(args)
    elif args.command == "list-watches":
        cmd_list_watches(args)
    elif args.command == "health":
        cmd_health(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
