#!/usr/bin/env python3
"""
Memory Tool — 记忆自动管理与压缩工具

统一CLI封装：L4会话压缩→历史提取→旧数据冷存→memory大小监控→超阈值告警

Usage:
    python -m scripts.memory_tool status          # 查看memory状态
    python -m scripts.memory_tool compress        # 执行完整压缩流程 (dry-run)
    python -m scripts.memory_tool compress --run  # 实际执行
    python -m scripts.memory_tool monitor         # 监控模式
    python -m scripts.memory_tool monitor --threshold 15  # 阈值告警(MB)
"""
import os, sys, json, time, textwrap, zipfile
from datetime import datetime
from pathlib import Path

GA_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.join(GA_HOME, 'memory')
L4_DIR = os.path.join(MEMORY_DIR, 'L4_raw_sessions')
TEMP_DIR = os.path.join(GA_HOME, 'temp')
ARCHIVE_DIR = os.path.join(MEMORY_DIR, 'archive')
MODEL_RESP_DIR = os.path.join(TEMP_DIR, 'model_responses')

# 阈值配置 (MB)
DEFAULT_THRESHOLD_MB = 15

def get_dir_size(path):
    """递归计算目录大小(MB)"""
    total = 0
    if not os.path.exists(path):
        return 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except:
                pass
    return total / (1024 * 1024)

def fmt_size(mb):
    """格式化显示大小"""
    if mb < 1:
        return f"{mb*1024:.1f}KB"
    return f"{mb:.2f}MB"

def status():
    """获取memory状态快照"""
    mem_mb = get_dir_size(MEMORY_DIR)
    l4_mb = get_dir_size(L4_DIR)
    archive_mb = get_dir_size(ARCHIVE_DIR)
    
    # L4文件详情
    l4_files = []
    if os.path.isdir(L4_DIR):
        for f in sorted(os.listdir(L4_DIR)):
            fpath = os.path.join(L4_DIR, f)
            if os.path.isfile(fpath):
                size_kb = os.path.getsize(fpath) / 1024
                l4_files.append((f, size_kb, 'zip' if f.endswith('.zip') else 'file'))
    
    # 原始待处理文件
    raw_files = []
    if os.path.isdir(MODEL_RESP_DIR):
        for f in sorted(os.listdir(MODEL_RESP_DIR)):
            fpath = os.path.join(MODEL_RESP_DIR, f)
            if os.path.isfile(fpath) and f.endswith('.txt'):
                raw_files.append(f)
    
    return {
        'memory_mb': mem_mb,
        'l4_mb': l4_mb,
        'archive_mb': archive_mb,
        'l4_files': l4_files,
        'raw_pending': raw_files,
        'threshold_mb': DEFAULT_THRESHOLD_MB,
        'healthy': mem_mb < DEFAULT_THRESHOLD_MB
    }

def print_status(st):
    """格式化输出状态"""
    mem_color = "✅" if st['healthy'] else "⚠️"
    print(f"\n{'='*50}")
    print(f" 🧠 记忆状态报告 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*50}")
    print(f"  {mem_color} memory/ 总大小:  {fmt_size(st['memory_mb'])}")
    print(f"     ├─ L4_raw_sessions/: {fmt_size(st['l4_mb'])}")
    print(f"     └─ archive/:          {fmt_size(st['archive_mb'])}")
    print(f"  阈值: {st['threshold_mb']}MB ({'健康' if st['healthy'] else '⚠️ 超限'})")
    
    if st['l4_files']:
        print(f"\n  📂 L4_raw_sessions/ 文件:")
        for name, size_kb, typ in st['l4_files']:
            icon = '📦' if typ == 'zip' else '📄'
            print(f"     {icon} {name} ({size_kb:.1f}KB)")
    
    if st['raw_pending']:
        print(f"\n  📥 待处理原始文件 ({len(st['raw_pending'])}):")
        for f in st['raw_pending']:
            print(f"     {f}")
    else:
        print(f"\n  ✅ 无待处理原始会话文件")
    
    print(f"{'='*50}\n")
    return st['healthy']

def compress(run=False):
    """执行压缩流程：先扫描原始文件，调用compress_session处理"""
    before_mb = get_dir_size(MEMORY_DIR)
    before_l4 = get_dir_size(L4_DIR)
    
    print(f"🔍 压缩前: memory/ {fmt_size(before_mb)}, L4/ {fmt_size(before_l4)}")
    
    # 检查待处理文件
    raw_files = []
    if os.path.isdir(MODEL_RESP_DIR):
        for f in sorted(os.listdir(MODEL_RESP_DIR)):
            fpath = os.path.join(MODEL_RESP_DIR, f)
            if os.path.isfile(fpath) and f.endswith('.txt'):
                # 跳过2小时内的文件（可能正在写入）
                if time.time() - os.path.getmtime(fpath) > 7200:
                    raw_files.append(f)
                else:
                    print(f"  ⏭️  跳过近期文件(仍在写入): {f}")
    
    if not raw_files:
        print("  ℹ️  无待压缩的原始文件")
        # 仍然执行归档操作
        _run_archive_pass(run)
    else:
        print(f"  📥 发现 {len(raw_files)} 个待压缩原始文件")
        if not run:
            print("  💡 使用 --run 执行实际压缩")
            for f in raw_files:
                fpath = os.path.join(MODEL_RESP_DIR, f)
                print(f"     📄 {f} ({os.path.getsize(fpath)/1024:.1f}KB)")
        else:
            _run_compress_pipeline(run)
    
    # 执行冷存检查（旧数据→archive）
    _run_cold_storage(run)
    
    after_mb = get_dir_size(MEMORY_DIR)
    after_l4 = get_dir_size(L4_DIR)
    
    print(f"\n📊 前后对比:")
    print(f"  memory/: {fmt_size(before_mb)} → {fmt_size(after_mb)} ({'+' if after_mb>before_mb else ''}{after_mb-before_mb:.2f}MB)")
    print(f"  L4/:     {fmt_size(before_l4)} → {fmt_size(after_l4)} ({'+' if after_l4>before_l4 else ''}{after_l4-before_l4:.2f}MB)")
    
    # 告警检查
    if after_mb > DEFAULT_THRESHOLD_MB:
        print(f"\n⚠️  告警: memory/ 大小 {fmt_size(after_mb)} 超过阈值 {DEFAULT_THRESHOLD_MB}MB!")
        print(f"  建议: 检查L4_raw_sessions/ 中是否有可归档的旧会话，或运行 archive 子命令")
    else:
        print(f"\n✅ memory/ 大小健康 ({fmt_size(after_mb)} < {DEFAULT_THRESHOLD_MB}MB)")
    
    return {'before_mb': before_mb, 'after_mb': after_mb, 'healthy': after_mb < DEFAULT_THRESHOLD_MB}

def _run_compress_pipeline(run):
    """调用 compress_session.py 的 batch_process 进行压缩"""
    sys.path.insert(0, L4_DIR)
    try:
        from compress_session import batch_process
        print("  🔄 执行压缩管道...")
        result = batch_process(MODEL_RESP_DIR, dry_run=not run)
        if run:
            print(f"  ✅ 压缩完成: {result.get('processed', 0)} 个会话处理")
        else:
            print(f"  ℹ️  模拟运行: {result.get('processed', 0)} 个会话待处理")
    except Exception as e:
        print(f"  ❌ 压缩管道出错: {e}")

def _run_archive_pass(run):
    """调用 archive_l4_sessions.py 进行归档清理"""
    sys.path.insert(0, os.path.join(GA_HOME, 'scripts'))
    try:
        from archive_l4_sessions import main as archive_main
        print("  🔄 执行归档清理...")
        if run:
            archive_main()
        else:
            print("  ℹ️  (--run 未指定，跳过真实归档)")
    except Exception as e:
        print(f"  ℹ️  归档检查: {e} (可能无操作)")

def _run_cold_storage(run):
    """冷存：将30天前的L4会话移到archive/"""
    cutoff = time.time() - 30 * 86400
    candidates = []
    
    if os.path.isdir(L4_DIR):
        for f in os.listdir(L4_DIR):
            fpath = os.path.join(L4_DIR, f)
            if not os.path.isfile(fpath) or f.endswith(('.py', '.pyc', '.zip')) or f.startswith('.'):
                continue
            mtime = os.path.getmtime(fpath)
            if mtime < cutoff:
                candidates.append((f, fpath, mtime))
    
    if candidates:
        print(f"\n  ❄️  冷存候选 ({len(candidates)} 个30天前的文件):")
        for name, fpath, mtime in sorted(candidates, key=lambda x: x[2]):
            age_days = (time.time() - mtime) / 86400
            size_kb = os.path.getsize(fpath) / 1024
            print(f"     {name} ({size_kb:.1f}KB, {age_days:.0f}天前)")
        
        if run:
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            for name, fpath, _ in candidates:
                import shutil
                dst = os.path.join(ARCHIVE_DIR, name)
                shutil.move(fpath, dst)
                print(f"     ✅ 已移至 archive/: {name}")
        else:
            print(f"     💡 使用 --run 执行冷存")
    else:
        print(f"\n  ✅ 无30天前的文件需冷存")

def monitor(threshold_mb=DEFAULT_THRESHOLD_MB, interval=60, count=1):
    """监控模式：周期性检查memory大小"""
    print(f"📊 监控模式 (阈值: {threshold_mb}MB, 间隔: {interval}s, 次数: {count})")
    
    for i in range(count):
        st = status()
        st['threshold_mb'] = threshold_mb
        st['healthy'] = st['memory_mb'] < threshold_mb
        healthy = print_status(st)
        
        if not healthy:
            print(f"⚠️  告警: memory/ {fmt_size(st['memory_mb'])} > {threshold_mb}MB!")
        
        if i < count - 1:
            time.sleep(interval)

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Memory Tool — 记忆自动管理与压缩',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(__doc__).split('Usage:')[0])
    
    sub = parser.add_subparsers(dest='command', help='子命令')
    
    # status
    p_status = sub.add_parser('status', help='查看memory状态')
    p_status.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD_MB,
                          help=f'告警阈值MB (默认{DEFAULT_THRESHOLD_MB})')
    
    # compress
    p_compress = sub.add_parser('compress', help='执行完整压缩流程')
    p_compress.add_argument('--run', action='store_true', help='实际执行（默认dry-run）')
    
    # monitor
    p_monitor = sub.add_parser('monitor', help='监控模式')
    p_monitor.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD_MB)
    p_monitor.add_argument('--interval', type=int, default=60, help='检查间隔(秒)')
    p_monitor.add_argument('--count', type=int, default=1, help='检查次数')
    
    args = parser.parse_args()
    
    if args.command == 'status':
        st = status()
        st['threshold_mb'] = args.threshold
        st['healthy'] = st['memory_mb'] < args.threshold
        print_status(st)
    
    elif args.command == 'compress':
        compress(run=args.run)
    
    elif args.command == 'monitor':
        monitor(threshold_mb=args.threshold, interval=args.interval, count=args.count)
    
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
