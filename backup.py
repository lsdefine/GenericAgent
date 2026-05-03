#!/usr/bin/env python3
"""GA System Full Backup Script
Usage: python backup.py [--dry-run] [--restore <backup_zip>] [--schedule]
"""
import os
import sys
import shutil
import zipfile
import datetime
import argparse

GA_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(GA_ROOT, 'backups')
os.makedirs(BACKUP_ROOT, exist_ok=True)

def get_backup_list():
    """List existing backups"""
    if not os.path.exists(BACKUP_ROOT):
        print("No backups found.")
        return
    for f in sorted(os.listdir(BACKUP_ROOT)):
        if f.startswith('GA_backup_') and f.endswith('.zip'):
            full = os.path.join(BACKUP_ROOT, f)
            size = os.path.getsize(full) / 1024
            print(f"  {f} ({size:.1f} KB)")

def backup_dry_run():
    """List what would be backed up"""
    print("=== GA Backup Dry Run ===\n")
    
    files = []
    for rel in [
        'mykey.py', 'TODO.txt', 'reflect/scheduler.py',
        'memory/global_mem.txt', 'memory/global_mem_insight.txt',
        'memory/memory_management_sop.md', 'memory/backup_sop.md',
        'memory/vision_sop.md', 'memory/vision_api.py',
        'memory/tmwebdriver_sop.md', 'memory/ljqCtrl_sop.md',
        'memory/autonomous_operation_sop.md', 'memory/scheduled_task_sop.md',
    ]:
        full = os.path.join(GA_ROOT, rel)
        if os.path.exists(full):
            files.append((rel, os.path.getsize(full)))
            print(f"  ✅ {rel} ({os.path.getsize(full)} B)")
        else:
            print(f"  ⚠️ {rel} NOT FOUND")
    
    # Directories
    for rel_dir in ['memory/L4_raw_sessions', 'sche_tasks', 'temp/autonomous_reports']:
        full_dir = os.path.join(GA_ROOT, rel_dir)
        if os.path.exists(full_dir):
            count = len(os.listdir(full_dir))
            print(f"  📁 {rel_dir}/ ({count} items)")
    
    total = sum(s for _, s in files)
    print(f"\nTotal: {total/1024:.1f} KB")

def create_backup():
    """Create a full backup"""
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_name = f'GA_backup_{timestamp}.zip'
    zip_path = os.path.join(BACKUP_ROOT, zip_name)
    
    print(f"📦 Creating backup: {zip_name}")
    
    files_to_backup = []
    
    # Core files
    core_files = [
        'mykey.py', 'TODO.txt', 'reflect/scheduler.py',
        'memory/global_mem.txt', 'memory/global_mem_insight.txt',
        'memory/memory_management_sop.md', 'memory/backup_sop.md',
        'memory/vision_sop.md', 'memory/vision_api.py',
        'memory/tmwebdriver_sop.md', 'memory/ljqCtrl_sop.md',
        'memory/autonomous_operation_sop.md', 'memory/scheduled_task_sop.md',
        'memory/health_check_sop.md', 'memory/card_generator_sop.md',
    ]
    for rel in core_files:
        full = os.path.join(GA_ROOT, rel)
        if os.path.exists(full):
            files_to_backup.append((full, rel))
    
    # sche_tasks (excluding done/ large dirs)
    sche_dir = os.path.join(GA_ROOT, 'sche_tasks')
    if os.path.exists(sche_dir):
        for f in os.listdir(sche_dir):
            full = os.path.join(sche_dir, f)
            if os.path.isfile(full):
                files_to_backup.append((full, f'sche_tasks/{f}'))
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for full, arcname in files_to_backup:
            zf.write(full, arcname)
    
    size = os.path.getsize(zip_path) / 1024
    print(f"✅ Backup created: {zip_path} ({size:.1f} KB)")
    return zip_path

def restore_backup(backup_zip):
    """Restore from a backup"""
    if not os.path.exists(backup_zip):
        print(f"❌ Backup not found: {backup_zip}")
        return
    
    restore_dir = os.path.join(GA_ROOT, 'restored', datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(restore_dir, exist_ok=True)
    
    print(f"🔄 Restoring to: {restore_dir}")
    with zipfile.ZipFile(backup_zip, 'r') as zf:
        zf.extractall(restore_dir)
    print(f"✅ Restored {len(zf.namelist())} files")

def main():
    parser = argparse.ArgumentParser(description='GA System Backup')
    parser.add_argument('--dry-run', action='store_true', help='List files without creating backup')
    parser.add_argument('--restore', metavar='ZIP', help='Restore from backup zip')
    parser.add_argument('--list', action='store_true', help='List existing backups')
    parser.add_argument('--schedule', action='store_true', help='Add to scheduler')
    args = parser.parse_args()
    
    if args.list:
        get_backup_list()
    elif args.restore:
        restore_backup(args.restore)
    elif args.dry_run:
        backup_dry_run()
    elif args.schedule:
        print("📅 Schedule feature: Add to sche_tasks/backup.json")
        # Create scheduler task
        sched_task = {
            "schedule": "03:00",
            "repeat": "weekly",
            "enabled": True,
            "command": f"python {os.path.join(GA_ROOT, 'backup.py')}",
            "prompt": "Run GA system backup. Execute python backup.py and report result."
        }
        import json
        task_path = os.path.join(GA_ROOT, 'sche_tasks', 'backup.json')
        with open(task_path, 'w', encoding='utf-8') as f:
            json.dump(sched_task, f, indent=2, ensure_ascii=False)
        print(f"✅ Scheduler task created: {task_path}")
    else:
        create_backup()

if __name__ == "__main__":
    main()
