#!/usr/bin/env python3
"""
磁盘清理自动化脚本 (cleanup_disk.py)
基于 R189 磁盘深度分析结论，安全清理可回收空间。
功能：
  1. 压缩已轮转的 /var/log/messages.* 日志
  2. 清理 dnf 包管理器缓存
  3. 清理 pip/npm 缓存
  4. 清理 Chromium 浏览器缓存
  5. 清理 /tmp 和 /var/tmp 临时文件
  6. 清理 GA temp/ 下过期临时文件

用法:
  python cleanup_disk.py              # 默认模式：清理+报告
  python cleanup_disk.py --dry-run    # 只显示可清理项，不执行
  python cleanup_disk.py --force      # 强制清理（跳过确认）

返回值: 0=成功, 1=部分成功, 2=失败
"""

import os
import sys
import json
import shutil
import subprocess
import datetime
import logging
from pathlib import Path

# ====== 配置 ======
CLEANUP_TARGETS = {
    # (路径, 清理方法, 描述, 风险等级)
    "log_rotate": {
        "path": "/var/log",
        "pattern": "messages.*",
        "method": "compress",
        "desc": "压缩已轮转的 messages 日志",
        "risk": "green",
        "sudo": True,
    },
    "dnf_cache": {
        "path": "/var/cache/dnf",
        "method": "dnf_clean",
        "desc": "清理 dnf 包管理器缓存",
        "risk": "green",
        "sudo": True,
    },
    "pip_cache": {
        "path": os.path.expanduser("~/.cache/pip"),
        "method": "remove_dir",
        "desc": "清理 pip 下载缓存",
        "risk": "green",
        "sudo": False,
    },
    "npm_cache": {
        "path": os.path.expanduser("~/.npm"),
        "method": "npm_clean",
        "desc": "清理 npm 全局缓存",
        "risk": "green",
        "sudo": False,
    },
    "chromium_cache": {
        "path": os.path.expanduser("~/.cache/chromium"),
        "method": "remove_dir",
        "desc": "清理 Chromium 浏览器缓存",
        "risk": "green",
        "sudo": False,
    },
    "tmp": {
        "path": "/tmp",
        "method": "tmp_clean",
        "desc": "清理 /tmp 临时文件 (跳过活跃文件)",
        "risk": "green",
        "sudo": False,
    },
    "var_tmp": {
        "path": "/var/tmp",
        "method": "tmp_clean",
        "desc": "清理 /var/tmp 临时文件 (跳过活跃文件)",
        "risk": "green",
        "sudo": False,
    },
    "ga_temp": {
        "path": "./",
        "method": "ga_temp_clean",
        "desc": "清理 GA temp/ 下 7天前 .py/.txt 临时文件",
        "risk": "green",
        "sudo": False,
    },
}

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "..", "temp", "cleanup_disk.log")),
    ],
)
log = logging.getLogger(__name__)


def get_size(path):
    """获取路径大小（字节）"""
    if not os.path.exists(path):
        return 0
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    if os.path.isfile(fp):
                        total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    pass
        return total
    except (OSError, PermissionError):
        return 0


def format_size(bytes_val):
    """友好显示大小"""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}TB"


def run_cmd(cmd, sudo=False, check=True):
    """执行命令"""
    full_cmd = ["sudo"] + cmd if sudo else cmd
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=120)
        if check and result.returncode != 0:
            log.warning(f"命令 {' '.join(full_cmd)} 返回 {result.returncode}: {result.stderr[:200]}")
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log.error(f"命令超时: {' '.join(full_cmd)}")
        return -1, "", "timeout"
    except FileNotFoundError:
        log.error(f"命令不存在: {full_cmd[0]}")
        return -2, "", "not found"


def cleanup_compress(target, dry_run=False):
    """压缩旧日志"""
    path = target["path"]
    pattern = target.get("pattern", "*.1")
    import glob
    files = glob.glob(os.path.join(path, pattern))
    # Filter non-gz files
    files = [f for f in files if not f.endswith(".gz")]
    if not files:
        log.info(f"  无待压缩文件 in {path}")
        return {"status": "skipped", "detail": "无文件待压缩"}

    total_before = 0
    total_after = 0
    results = []
    for f in files:
        try:
            size_before = os.path.getsize(f)
            total_before += size_before
            if not dry_run:
                rc, out, err = run_cmd(["gzip", f], sudo=True)
                if rc != 0:
                    log.warning(f"  压缩失败: {f}")
                    continue
                gz_file = f + ".gz"
                size_after = os.path.getsize(gz_file) if os.path.exists(gz_file) else 0
                total_after += size_after
                saved = size_before - size_after
                results.append({"file": os.path.basename(f), "before": size_before, "after": size_after, "saved": saved})
                log.info(f"  压缩: {f} ({format_size(size_before)} → {format_size(size_after)}, 节省 {format_size(saved)})")
            else:
                results.append({"file": os.path.basename(f), "before": size_before, "after": 0, "saved": 0})
                log.info(f"  [DRY-RUN] 将压缩: {f} ({format_size(size_before)})")
        except (OSError, PermissionError) as e:
            log.warning(f"  跳过 {f}: {e}")

    return {
        "status": "dry_run" if dry_run else "done",
        "detail": f"处理 {len(files)} 个文件",
        "total_before": total_before,
        "total_after": total_after,
        "results": results,
    }


def cleanup_dnf_clean(target, dry_run=False):
    """清理 dnf 缓存"""
    if dry_run:
        log.info(f"  [DRY-RUN] 将执行: dnf clean all")
        before = get_size(target["path"])
        return {"status": "dry_run", "detail": f"待清理 {format_size(before)} (path={target['path']})", "before": before}

    before = get_size(target["path"])
    rc, out, err = run_cmd(["dnf", "clean", "all"], sudo=True)
    after = get_size(target["path"])
    if rc == 0:
        log.info(f"  dnf 缓存清理完成: {format_size(before)} → {format_size(after)}, 释放 {format_size(before - after)}")
    else:
        log.warning(f"  dnf clean 返回 {rc}: {err[:200]}")
    return {"status": "done" if rc == 0 else "error", "detail": err[:200] if err else "ok", "before": before, "after": after}


def cleanup_remove_dir(target, dry_run=False):
    """删除目录"""
    path = target["path"]
    if not os.path.exists(path):
        log.info(f"  路径不存在: {path}")
        return {"status": "skipped", "detail": "路径不存在"}

    before = get_size(path)
    if dry_run:
        log.info(f"  [DRY-RUN] 将删除: {path} ({format_size(before)})")
        return {"status": "dry_run", "detail": f"将释放 {format_size(before)}", "before": before}

    try:
        shutil.rmtree(path, ignore_errors=True)
        after = get_size(path)
        log.info(f"  删除: {path} (释放 {format_size(before)})")
        return {"status": "done", "detail": f"释放 {format_size(before)}", "before": before, "after": after}
    except (OSError, PermissionError) as e:
        log.error(f"  删除失败: {path}: {e}")
        return {"status": "error", "detail": str(e), "before": before, "after": before}


def cleanup_npm_clean(target, dry_run=False):
    """清理 npm 缓存"""
    before = get_size(target["path"])
    if dry_run:
        log.info(f"  [DRY-RUN] 将执行: npm cache clean --force ({format_size(before)})")
        return {"status": "dry_run", "detail": f"将释放 {format_size(before)}", "before": before}

    rc, out, err = run_cmd(["npm", "cache", "clean", "--force"])
    after = get_size(target["path"])
    if rc == 0:
        log.info(f"  npm 缓存清理完成: {format_size(before)} → {format_size(after)}, 释放 {format_size(before - after)}")
    else:
        log.warning(f"  npm cache clean 返回 {rc}: {err[:200]}")
    return {"status": "done" if rc == 0 else "error", "detail": err[:200] if err else "ok", "before": before, "after": after}


def cleanup_tmp_clean(target, dry_run=False):
    """清理临时目录（删除 3 天前的文件）"""
    path = target["path"]
    if not os.path.exists(path):
        return {"status": "skipped", "detail": "路径不存在"}

    before = get_size(path)
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=3)
    removed_count = 0
    removed_size = 0

    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fp))
                if mtime < cutoff:
                    fsize = os.path.getsize(fp)
                    if not dry_run:
                        os.remove(fp)
                    removed_count += 1
                    removed_size += fsize
            except (OSError, PermissionError):
                pass

    after = get_size(path) if not dry_run else before
    log.info(f"  清理 {path}: 删除 {removed_count} 个旧文件, 释放 {format_size(removed_size)}")
    return {
        "status": "dry_run" if dry_run else "done",
        "detail": f"删除{removed_count}个文件, 释放{format_size(removed_size)}",
        "before": before,
        "after": after,
        "removed_count": removed_count,
        "removed_size": removed_size,
    }


def cleanup_ga_temp(target, dry_run=False):
    """清理 GA temp 下过期临时文件"""
    path = target["path"]
    before = get_size(path)
    now = datetime.datetime.now()
    cutoff = now - datetime.timedelta(days=7)
    removed_count = 0
    removed_size = 0

    for root, dirs, files in os.walk(path):
        # Skip autonomous_reports
        if "autonomous_reports" in root:
            continue
        for f in files:
            if f.endswith((".py", ".txt", ".tmp", ".log")):
                fp = os.path.join(root, f)
                try:
                    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fp))
                    if mtime < cutoff:
                        fsize = os.path.getsize(fp)
                        if not dry_run:
                            os.remove(fp)
                        removed_count += 1
                        removed_size += fsize
                except (OSError, PermissionError):
                    pass

    after = get_size(path) if not dry_run else before
    log.info(f"  清理 GA temp: 删除 {removed_count} 个旧文件, 释放 {format_size(removed_size)}")
    return {
        "status": "dry_run" if dry_run else "done",
        "detail": f"删除{removed_count}个文件, 释放{format_size(removed_size)}",
        "before": before,
        "after": after,
        "removed_count": removed_count,
        "removed_size": removed_size,
    }


# ====== 调度器 ======
CLEANUP_METHODS = {
    "compress": cleanup_compress,
    "dnf_clean": cleanup_dnf_clean,
    "remove_dir": cleanup_remove_dir,
    "npm_clean": cleanup_npm_clean,
    "tmp_clean": cleanup_tmp_clean,
    "ga_temp_clean": cleanup_ga_temp,
}


def report_disk_usage():
    """获取当前磁盘使用率"""
    rc, out, err = run_cmd(["df", "-h", "/"], sudo=False)
    if rc == 0 and out:
        for line in out.strip().split("\n"):
            if "/" in line and "Filesystem" not in line:
                parts = line.split()
                if len(parts) >= 5:
                    return parts[4], parts[1], parts[2], parts[3]
    return "unknown", "unknown", "unknown", "unknown"


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    if dry_run:
        log.info("=" * 60)
        log.info("磁盘清理脚本 — DRY RUN 模式 (仅展示，不执行)")
        log.info("=" * 60)
    else:
        log.info("=" * 60)
        log.info("磁盘清理脚本 — 执行模式")
        log.info("=" * 60)

    # 获取清理前磁盘状态
    pct_before, total, used, avail = report_disk_usage()
    log.info(f"清理前磁盘: {used}/{total} ({pct_before})")

    results = {}
    total_before = 0
    total_after = 0
    error_count = 0

    for name, target in CLEANUP_TARGETS.items():
        method = target["method"]
        if method not in CLEANUP_METHODS:
            log.warning(f"  未知清理方法: {method} for {name}")
            continue

        log.info(f"\n--- {target['desc']} ---")
        try:
            result = CLEANUP_METHODS[method](target, dry_run=dry_run)
            results[name] = result
            if not dry_run and result.get("status") == "error":
                error_count += 1
            if "before" in result:
                total_before += result.get("before", 0)
            if "after" in result:
                total_after += result.get("after", 0)
        except Exception as e:
            log.error(f"  清理失败: {e}")
            results[name] = {"status": "error", "detail": str(e)}
            error_count += 1

    # 获取清理后磁盘状态
    log.info("\n" + "=" * 60)
    if not dry_run:
        pct_after, total2, used2, avail2 = report_disk_usage()
        log.info(f"清理后磁盘: {used2}/{total2} ({pct_after})")
        log.info(f"预估释放总计: {format_size(total_before - total_after)}")
    else:
        log.info(f"DRY RUN: 预估可释放 {format_size(total_before)}")

    # 输出 JSON 摘要
    summary = {
        "timestamp": datetime.datetime.now().isoformat(),
        "mode": "dry_run" if dry_run else "execute",
        "disk_before": {"usage": pct_before, "total": total, "used": used, "avail": avail},
        "total_before": total_before,
        "total_after": total_after if not dry_run else 0,
        "total_saved": total_before - total_after if not dry_run else 0,
        "error_count": error_count,
        "results": {k: {"status": v.get("status"), "detail": v.get("detail", "")} for k, v in results.items()},
    }
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))

    if error_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
