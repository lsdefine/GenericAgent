#!/usr/bin/env python3
"""
TMWebDriver Master 启动脚本
自动检测端口18766是否已有master运行，无则启动。
可集成到系统启动或scheduler中。
"""
import sys, os, time, signal, socket

MASTER_PORT = 18766
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def main():
    # 检查是否已有master运行
    if is_port_open(MASTER_PORT):
        print(f"[TMWebDriver] Master already running on :{MASTER_PORT}")
        return

    sys.path.insert(0, PROJECT_ROOT)
    from TMWebDriver import TMWebDriver

    driver = TMWebDriver()
    print(f"[TMWebDriver] Master started on :{MASTER_PORT-1} (WS) and :{MASTER_PORT} (HTTP)")

    # 捕获退出信号
    def shutdown(sig, frame):
        print("[TMWebDriver] Shutting down master")
        sys.exit(0)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Keep alive
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
