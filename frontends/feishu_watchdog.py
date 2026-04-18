# frontends/feishu_watchdog.py
"""
飞书机器人守护进程 - 自动重启崩溃的fsapp.py
用法: python feishu_watchdog.py
"""
import subprocess
import time
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FSAPP_PATH = os.path.join(SCRIPT_DIR, "fsapp.py")
LOG_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "feishu_bot.log")
CHECK_INTERVAL = 10  # 检查间隔（秒）

def start_bot():
    """启动飞书机器人"""
    # 清空旧日志
    with open(LOG_PATH, 'w', encoding='gbk') as f:
        f.write('')
    
    proc = subprocess.Popen(
        [sys.executable, FSAPP_PATH],
        stdout=open(LOG_PATH, 'a', encoding='gbk'),
        stderr=subprocess.STDOUT,
        cwd=os.path.dirname(SCRIPT_DIR),
        creationflags=0x08000000  # CREATE_NO_WINDOW
    )
    return proc

def main():
    print(f"[守护] 飞书机器人守护进程启动")
    print(f"[守护] 目标脚本: {FSAPP_PATH}")
    print(f"[守护] 日志文件: {LOG_PATH}")
    
    proc = start_bot()
    restart_count = 0
    
    while True:
        time.sleep(CHECK_INTERVAL)
        
        if proc.poll() is not None:
            # 进程已退出
            restart_count += 1
            print(f"[守护] 检测到进程退出 (返回码: {proc.returncode})，第 {restart_count} 次重启")
            time.sleep(3)  # 等待几秒再重启
            proc = start_bot()
            print(f"[守护] 新进程已启动 (PID: {proc.pid})")

if __name__ == "__main__":
    main()