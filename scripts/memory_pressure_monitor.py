#!/usr/bin/env python3
"""
memory_pressure_monitor.py - 内存压力监控与自动防护 (v2)

用途: 定期检查系统可用内存，低于阈值时:
  1. 发送AgentMail/notify告警
  2. 清理chromium僵尸进程
  3. 清理page cache (drop_caches)
  4. 动态调整swappiness (OOM前先swap)
  5. 杀低优先级进程 (oom_score_adj>=500)

安装: crontab -e 添加
  */2 * * * * cd /home/admin/GenericAgent && python3 scripts/memory_pressure_monitor.py --threshold 200 >> temp/memory_monitor.log 2>&1

v2新增 (2026-06-07):
  - adjust_swappiness(): 内存压力时临时调高swappiness，过后恢复
  - drop_page_cache(): 紧急时清理page cache
  - kill_low_priority(): 杀低优进程释放内存
"""

import os
import sys
import json
import time
import subprocess
import argparse
import signal
from pathlib import Path

# 阈值配置
WARN_MB = 200   # 告警阈值
CRIT_MB = 100   # 紧急阈值
INTERVAL = 120  # 检查间隔(秒)

# swappiness原始值备份
_original_swappiness = None

def get_available_mem_mb():
    """获取可用内存(MB)"""
    try:
        with open('/proc/meminfo') as f:
            data = {}
            for line in f:
                parts = line.split()
                if parts:
                    data[parts[0].rstrip(':')] = int(parts[1])
        mem_avail = data.get('MemAvailable', 0)
        return mem_avail // 1024
    except Exception:
        return 0

def get_top_processes(n=5):
    """获取内存TOP进程"""
    try:
        result = subprocess.run(
            ['ps', 'aux', '--sort=-%mem'],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split('\n')[1:n+1]
        procs = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 11:
                procs.append({
                    'pid': parts[1],
                    'mem_pct': parts[3],
                    'rss_mb': round(int(parts[5]) / 1024, 1),
                    'cmd': ' '.join(parts[10:])[:60]
                })
        return procs
    except Exception as e:
        return [{'error': str(e)}]

def kill_zombie_chromium():
    """清理休眠的chromium进程"""
    killed = 0
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'chromium-browse.*--headless'],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                try:
                    status = open(f'/proc/{pid}/status').read()
                    state = ''
                    rss = 0
                    for line in status.split('\n'):
                        if line.startswith('State:'):
                            state = line.split()[1]
                        if line.startswith('VmRSS:'):
                            rss = int(line.split()[1])
                    if state in ('D', 'Z') or rss == 0:
                        os.kill(int(pid), 9)
                        killed += 1
                        print(f"  [killed zombie chromium pid={pid}]")
                except:
                    pass
    except:
        pass
    return killed

# ===== v2 新增自动响应策略 =====

def get_swappiness():
    """读取当前swappiness"""
    try:
        with open('/proc/sys/vm/swappiness') as f:
            return int(f.read().strip())
    except:
        return None

def set_swappiness(value):
    """设置swappiness值 (需root或sudo)"""
    try:
        # 尝试直接写入
        with open('/proc/sys/vm/swappiness', 'w') as f:
            f.write(str(value))
        return True
    except PermissionError:
        # 尝试sudo
        try:
            subprocess.run(
                ['sudo', 'sysctl', '-w', f'vm.swappiness={value}'],
                capture_output=True, text=True, timeout=5
            )
            return True
        except:
            return False
    except Exception:
        return False

def adjust_swappiness(mem_avail):
    """
    动态调整swappiness: 
    - 低于CRIT时 → 临时设为60 (主动swap)
    - 低于WARN时 → 临时设为20 (适度swap)
    - 正常时 → 恢复为0 (原值)
    """
    global _original_swappiness
    
    current = get_swappiness()
    if current is None:
        return 0, 0
    
    # 记录原始值 (仅第一次)
    if _original_swappiness is None:
        _original_swappiness = current
    
    if mem_avail < CRIT_MB:
        target = 60  # 紧急: 大范围swap
    elif mem_avail < WARN_MB:
        target = 20  # 告警: 适度swap
    else:
        target = _original_swappiness  # 恢复原始值
    
    if current != target:
        if set_swappiness(target):
            print(f"  [swappiness: {current}→{target}]")
            return current, target
        else:
            print(f"  [swappiness change failed: {current}→{target}]")
            return current, current
    return current, current

def drop_page_cache():
    """
    清理page cache (需要root/sudo)
    写入3到drop_caches: 清理page cache + dentries + inodes
    注意: 不会影响dirty page (需要先sync)
    """
    try:
        # 先sync (刷dirty pages到磁盘)
        os.system('sync')
        # 尝试直接写入
        with open('/proc/sys/vm/drop_caches', 'w') as f:
            f.write('3')
        return True
    except PermissionError:
        try:
            subprocess.run(
                ['sudo', 'sh', '-c', 'sync; echo 3 > /proc/sys/vm/drop_caches'],
                capture_output=True, text=True, timeout=10
            )
            return True
        except:
            return False
    except Exception:
        return False

def get_cached_mb():
    """获取当前cached内存大小(MB)"""
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('Cached:'):
                    return int(line.split()[1]) // 1024
    except:
        pass
    return 0

def kill_low_priority(min_rss_mb=50):
    """
    杀低优先级进程 (oom_score_adj >= 500) 且RSS > min_rss_mb
    这些进程在OOM时系统会优先杀，主动释放内存
    """
    killed = 0
    freed_mb = 0
    try:
        for proc_dir in os.listdir('/proc'):
            if not proc_dir.isdigit():
                continue
            pid = proc_dir
            try:
                # 读oom_score_adj
                with open(f'/proc/{pid}/oom_score_adj') as f:
                    adj = int(f.read().strip())
                if adj < 500:
                    continue
                # 读RSS
                with open(f'/proc/{pid}/status') as f:
                    rss = 0
                    comm = ''
                    for line in f:
                        if line.startswith('VmRSS:'):
                            rss = int(line.split()[1])
                        if line.startswith('Name:'):
                            comm = line.split()[1]
                if rss < min_rss_mb * 1024:
                    continue  # RSS太小，不值得杀
                # 跳过自己
                if pid == str(os.getpid()):
                    continue
                # 杀进程
                os.kill(int(pid), signal.SIGTERM)
                time.sleep(0.1)
                # 如果还活着，用SIGKILL
                try:
                    os.kill(int(pid), 0)
                    os.kill(int(pid), signal.SIGKILL)
                except:
                    pass  # 进程已死
                killed += 1
                freed_mb += rss // 1024
                print(f"  [killed low-pri pid={pid} adj={adj} rss={rss//1024}MB comm={comm}]")
            except (PermissionError, FileNotFoundError, ProcessLookupError):
                continue
            except Exception:
                continue
    except Exception:
        pass
    return killed, freed_mb

def send_alert(message):
    """通过AgentMail发送告警 (如果API可用) - 带5s超时"""
    try:
        import threading
        result = [None, None]  # [success, error_msg]
        
        def _do_send():
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'memory'))
                from keychain import keys
                api_key = keys.AGENTMAIL_API_KEY.use()
                os.environ['AGENTMAIL_API_KEY'] = api_key
                from agentmail import AgentMail
                client = AgentMail(api_key=api_key)
                INBOX = 'genericagent@agentmail.to'
                client.inboxes.messages.send(
                    inbox_id=INBOX,
                    to=[INBOX],
                    subject='[GA-ALERT] Memory Pressure',
                    text=message
                )
                result[0] = True
            except Exception as e:
                result[1] = str(e)
        
        t = threading.Thread(target=_do_send, daemon=True)
        t.start()
        t.join(timeout=5)  # 5s timeout
        if t.is_alive():
            print(f"  [Alert timeout after 5s]")
            return False
        if result[0]:
            return True
        if result[1]:
            print(f"  [Alert failed: {result[1]}]")
        return False
    except Exception as e:
        print(f"  [Alert error: {e}]")
        return False

def main():
    parser = argparse.ArgumentParser(description='Memory Pressure Monitor v2')
    parser.add_argument('--threshold', type=int, default=WARN_MB,
                       help=f'Warning threshold in MB (default: {WARN_MB})')
    parser.add_argument('--oneshot', action='store_true',
                       help='Run once and exit (for cron)')
    parser.add_argument('--restore-swappiness', action='store_true',
                       help='Restore original swappiness and exit')
    args = parser.parse_args()

    # 如果只是恢复swappiness
    if args.restore_swappiness:
        orig = _original_swappiness or 0
        set_swappiness(orig)
        print(f"Restored swappiness to {orig}")
        return 0

    threshold = args.threshold
    mem_avail = get_available_mem_mb()
    top_procs = get_top_processes()
    ts = time.strftime('%Y-%m-%d %H:%M:%S')

    # 格式化TOP进程
    top_str = '\n'.join(
        f"  {p.get('rss_mb','?')}MB [{p.get('mem_pct','?')}%] {p.get('cmd','?')[:50]}"
        for p in top_procs
    )

    actions = []
    status = f"[{ts}] MemAvailable={mem_avail}MB (threshold={threshold}MB)"

    if mem_avail < CRIT_MB:
        # ===== 紧急响应 =====
        
        # 1. 杀chromium僵尸
        killed_zombie = kill_zombie_chromium()
        if killed_zombie:
            actions.append(f"zombie_chromium_killed={killed_zombie}")
        
        # 2. 动态调swappiness
        old_swap, new_swap = adjust_swappiness(mem_avail)
        if old_swap != new_swap:
            actions.append(f"swappiness:{old_swap}→{new_swap}")
        
        # 3. 清理page cache
        cache_before = get_cached_mb()
        if cache_before > 100:  # cache > 100MB才值得清理
            if drop_page_cache():
                cache_after = get_cached_mb()
                freed = cache_before - cache_after
                actions.append(f"cache_freed={freed}MB")
                print(f"  [cache: {cache_before}MB→{cache_after}MB, freed={freed}MB]")
        
        # 4. 杀低优先级进程
        killed_lp, freed_lp = kill_low_priority(min_rss_mb=30)
        if killed_lp:
            actions.append(f"lowpri_killed={killed_lp} freed={freed_lp}MB")
        
        # 5. 告警
        action_str = ', '.join(actions) if actions else 'none'
        alert = (
            f"🔴 [CRITICAL] Memory critically low: {mem_avail}MB\n"
            f"Actions: {action_str}\n"
            f"Top processes:\n{top_str}"
        )
        send_alert(alert)
        print(f"🔴 {status} | {action_str} | ALERT SENT")

    elif mem_avail < threshold:
        # ===== 告警响应 =====
        
        # 1. 动态调swappiness (适度)
        old_swap, new_swap = adjust_swappiness(mem_avail)
        if old_swap != new_swap:
            actions.append(f"swappiness:{old_swap}→{new_swap}")
        
        # 2. 清理page cache (如果cache较大)
        cache_before = get_cached_mb()
        if cache_before > 200:
            if drop_page_cache():
                cache_after = get_cached_mb()
                freed = cache_before - cache_after
                if freed > 50:
                    actions.append(f"cache_freed={freed}MB")
        
        # 3. 杀chromium僵尸
        killed_zombie = kill_zombie_chromium()
        if killed_zombie:
            actions.append(f"zombie_chromium_killed={killed_zombie}")
        
        # 4. 告警
        action_str = ', '.join(actions) if actions else 'none'
        alert = (
            f"🟡 [WARNING] Memory low: {mem_avail}MB (threshold: {threshold}MB)\n"
            f"Actions: {action_str}\n"
            f"Top processes:\n{top_str}"
        )
        send_alert(alert)
        print(f"🟡 {status} | {action_str} | ALERT SENT")
    else:
        # 正常: 恢复swappiness原始值
        old_swap, new_swap = adjust_swappiness(mem_avail)
        if old_swap != new_swap:
            print(f"  [swappiness restored: {old_swap}→{new_swap}]")
        print(f"🟢 {status} | OK")

    # 输出JSON状态供其他工具消费
    state = {
        'timestamp': ts,
        'mem_available_mb': mem_avail,
        'threshold_mb': threshold,
        'status': 'ok' if mem_avail >= threshold else ('critical' if mem_avail < CRIT_MB else 'warning'),
        'top_processes': top_procs,
        'actions_taken': actions
    }
    state_path = Path('temp/memory_state.json')
    with open(state_path, 'w') as f:
        json.dump(state, f)

    return 0 if mem_avail >= CRIT_MB else 1

if __name__ == '__main__':
    sys.exit(main())
