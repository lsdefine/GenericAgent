#!/usr/bin/env python3
"""L4会话自动归档清理：压缩→按月归档→清理30天前旧会话"""
import os, sys, json, zipfile, re, shutil
from datetime import datetime, timedelta
from pathlib import Path

GA_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L4_DIR = os.path.join(GA_HOME, 'memory', 'L4_raw_sessions')
MODEL_RESP_DIR = os.path.join(GA_HOME, 'temp', 'model_responses')
DONE_DIR = os.path.join(GA_HOME, 'sche_tasks', 'done')
RETENTION_DAYS = 30

def _ts_from_filename(fname):
    """Extract timestamp from filename like model_responses_180618.txt → 18:06:18 today"""
    m = re.search(r'_(\d{6})\.(txt|md)$', fname)
    if m:
        try:
            h, m_s, s = int(m.group(1)[:2]), int(m.group(1)[2:4]), int(m.group(1)[4:6])
            if 0 <= h <= 23 and 0 <= m_s <= 59 and 0 <= s <= 59:
                return datetime.now().replace(hour=h, minute=m_s, second=s, microsecond=0)
        except ValueError:
            pass
    return None

def _file_age_days(path):
    """Return file age in days"""
    return (datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))).days

def archive_file(src_path, month_prefix):
    """Add file to monthly zip archive in L4_DIR"""
    zip_name = f"{month_prefix}.zip"
    zip_path = os.path.join(L4_DIR, zip_name)
    
    arcname = os.path.basename(src_path)
    # Open existing or create new zip
    mode = 'a' if os.path.exists(zip_path) else 'w'
    with zipfile.ZipFile(zip_path, mode, zipfile.ZIP_DEFLATED) as zf:
        # Check if already in zip
        existing = set(zf.namelist())
        if arcname not in existing:
            zf.write(src_path, arcname)
    return zip_path

def main():
    actions = []
    
    # 1. Process temp/model_responses/ (new raw sessions)
    if os.path.isdir(MODEL_RESP_DIR):
        for f in sorted(os.listdir(MODEL_RESP_DIR)):
            fpath = os.path.join(MODEL_RESP_DIR, f)
            if not os.path.isfile(fpath) or not f.endswith('.txt'):
                continue
            
            ts = _ts_from_filename(f) or datetime.fromtimestamp(os.path.getmtime(fpath))
            month_prefix = ts.strftime('%Y-%m')
            
            # Try to compress via compress_session.py
            try:
                sys.path.insert(0, L4_DIR)
                from compress_session import compress_session
                dst, stats = compress_session(fpath, dst_dir=L4_DIR) or (None, 'skip')
                if dst and os.path.exists(dst):
                    actions.append(f"📦 压缩: {f} → {os.path.basename(dst)}")
                    # Archive compressed file
                    archive_file(dst, month_prefix)
                    actions.append(f"🗄️  归档: {os.path.basename(dst)} → {month_prefix}.zip")
                    os.remove(dst)  # Remove compressed file after archiving
                    os.remove(fpath)  # Remove original file
                    actions.append(f"🗑️  删除原始: {f}")
                else:
                    # Directly archive if compression skipped
                    archive_file(fpath, month_prefix)
                    actions.append(f"🗄️  直接归档: {f} → {month_prefix}.zip")
                    os.remove(fpath)
                    actions.append(f"🗑️  删除原始: {f}")
            except Exception as e:
                # Fallback: archive raw file
                archive_file(fpath, month_prefix)
                actions.append(f"🗄️  归档(原始): {f} → {month_prefix}.zip ({e})")
                os.remove(fpath)
                actions.append(f"🗑️  删除原始: {f}")
    
    # 2. Cleanup old files (30+ days)
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    
    # Clean model_responses/ files
    if os.path.isdir(MODEL_RESP_DIR):
        for f in os.listdir(MODEL_RESP_DIR):
            fpath = os.path.join(MODEL_RESP_DIR, f)
            if not os.path.isfile(fpath):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
                actions.append(f"🧹 清理旧会话: {f} ({(datetime.now()-mtime).days}天前)")
    
    # Clean L4_DIR raw .md/.txt (not zip, not py)
    if os.path.isdir(L4_DIR):
        for f in os.listdir(L4_DIR):
            if f.endswith(('.zip', '.py', '.pyc')) or os.path.isdir(os.path.join(L4_DIR, f)):
                continue
            fpath = os.path.join(L4_DIR, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff and _file_age_days(fpath) > RETENTION_DAYS:
                os.remove(fpath)
                actions.append(f"🧹 清理L4旧文件: {f}")
    
    # 3. Output summary
    if actions:
        print(f"📋 L4会话归档清理完成 ({datetime.now().strftime('%Y-%m-%d %H:%M')}):")
        for a in actions:
            print(f"  {a}")
    else:
        print("✅ 无需要处理的会话文件")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
