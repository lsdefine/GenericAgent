"""
Task Monitor - 自动续发脚本
监控 task 模式的 output 文件，当 agent 自停（输出 [ROUND END] 但没有完成标记）时，
自动写入 reply.txt 让 agent 继续执行。

用法：
    python task_monitor.py <task_name> [--complete-marker MARKER] [--max-replies N] [--interval S]

示例：
    python task_monitor.py tri_axis_scan --complete-marker "[TRI_AXIS_SCAN_COMPLETE]" --max-replies 5
"""

import os, sys, time, argparse, glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)  # pc-agent-loop/
TEMP_DIR = os.path.join(PROJECT_ROOT, 'temp')


def get_latest_output(task_dir):
    """获取最新的 output 文件路径和内容"""
    # output.txt, output1.txt, output2.txt...
    outputs = glob.glob(os.path.join(task_dir, 'output*.txt'))
    if not outputs:
        return None, None
    # 按修改时间排序，取最新的
    outputs.sort(key=os.path.getmtime)
    latest = outputs[-1]
    try:
        with open(latest, 'r', encoding='utf-8') as f:
            content = f.read()
        return latest, content
    except Exception:
        return latest, None


def monitor(task_name, complete_marker, max_replies=5, interval=15):
    """
    主监控循环
    
    Args:
        task_name: task目录名
        complete_marker: 完成标记字符串，出现在output中表示任务完成
        max_replies: 最大自动续发次数（防止无限循环）
        interval: 检查间隔（秒）
    """
    task_dir = os.path.join(TEMP_DIR, task_name)
    reply_file = os.path.join(task_dir, 'reply.txt')
    
    print(f"[Monitor] 启动监控")
    print(f"  task_dir: {task_dir}")
    print(f"  complete_marker: {complete_marker}")
    print(f"  max_replies: {max_replies}")
    print(f"  interval: {interval}s")
    print(f"  reply_file: {reply_file}")
    print()
    
    if not os.path.exists(task_dir):
        print(f"[Monitor] 等待 task 目录创建...")
        for _ in range(60):  # 最多等2分钟
            time.sleep(2)
            if os.path.exists(task_dir):
                break
        else:
            print(f"[Monitor] ERROR: task 目录未创建，退出")
            return
    
    reply_count = 0
    last_output_path = None
    last_output_size = 0
    stall_count = 0  # 连续未变化次数
    
    while True:
        time.sleep(interval)
        
        # 获取最新output
        output_path, content = get_latest_output(task_dir)
        
        if output_path is None or content is None:
            continue
        
        # 检查是否已完成
        if complete_marker in content:
            print(f"[Monitor] ✓ 检测到完成标记，任务已完成！退出监控。")
            return
        
        # 检查是否有 [ROUND END]（agent停了）
        current_size = os.path.getsize(output_path)
        
        if output_path == last_output_path and current_size == last_output_size:
            # 文件没变化
            if content.rstrip().endswith('[ROUND END]'):
                stall_count += 1
            else:
                stall_count = 0
        else:
            # 文件有变化，重置
            last_output_path = output_path
            last_output_size = current_size
            stall_count = 0
            
            # 新的 [ROUND END] 出现
            if content.rstrip().endswith('[ROUND END]'):
                stall_count = 1
        
        # 连续2次检测到 [ROUND END] 且文件不再变化 → agent确实停了
        if stall_count >= 2:
            if reply_count >= max_replies:
                print(f"[Monitor] ⚠ 已达最大续发次数({max_replies})，停止监控。")
                print(f"  可能存在问题，请手动检查。")
                return
            
            # 确认 reply.txt 不存在（避免覆盖）
            if os.path.exists(reply_file):
                print(f"[Monitor] reply.txt 已存在，跳过本次")
                continue
            
            reply_count += 1
            print(f"[Monitor] → Agent 已停止（第{reply_count}次），写入 reply.txt 续发...")
            
            with open(reply_file, 'w', encoding='utf-8') as f:
                f.write("继续")
            
            print(f"[Monitor]   已写入 reply.txt，等待 agent 恢复...")
            stall_count = 0
            last_output_size = 0  # 重置，等待新的output
            
            # 等待agent消费reply.txt
            for _ in range(30):  # 最多等60秒
                time.sleep(2)
                if not os.path.exists(reply_file):
                    print(f"[Monitor]   ✓ reply.txt 已被消费，agent 已恢复")
                    break
            else:
                print(f"[Monitor]   ⚠ reply.txt 60秒未被消费，agent可能未在运行")
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Task Monitor - 自动续发')
    parser.add_argument('task_name', help='task目录名')
    parser.add_argument('--complete-marker', default='[TRI_AXIS_SCAN_COMPLETE]',
                        help='完成标记（默认: [TRI_AXIS_SCAN_COMPLETE]）')
    parser.add_argument('--max-replies', type=int, default=5,
                        help='最大自动续发次数（默认: 5）')
    parser.add_argument('--interval', type=int, default=15,
                        help='检查间隔秒数（默认: 15）')
    
    args = parser.parse_args()
    
    try:
        monitor(args.task_name, args.complete_marker, args.max_replies, args.interval)
    except KeyboardInterrupt:
        print("\n[Monitor] 手动中断，退出。")
