#!/usr/bin/env python3
"""
system_snapshot_db.py — 系统快照持久化+漂移检测工具
基于 system_utils.py (R123 morphling/jc) 构建

功能:
  1. take_snapshot(comment) — 采集全系统快照并存SQLite
  2. list_snapshots() — 列出所有快照
  3. diff(id1, id2) — 对比两快照，输出漂移报告
  4. auto_detect(threshold_days) — 自动对比最近与指定天数前快照

用法:
  python scripts/system_snapshot_db.py take "before upgrade"
  python scripts/system_snapshot_db.py list
  python scripts/system_snapshot_db.py diff 1 2
  python scripts/system_snapshot_db.py auto --days 7
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保可从任何cwd导入
_SCRIPT_DIR = Path(__file__).parent.resolve()
_BASE_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_BASE_DIR))

from scripts.system_utils import (
    ps_info,
    disk_info,
    disk_inodes,
    mem_info,
    uptime_info,
    network_connections,
    network_sockets,
    users,
    top_processes,
)

DB_DIR = _BASE_DIR / "temp" / "snapshot_db"
DB_PATH = DB_DIR / "snapshots.db"


# ── 数据库 ──

def _ensure_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            taken_at TEXT NOT NULL,
            comment TEXT DEFAULT '',
            data TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _get_snapshot_data(conn, snap_id):
    row = conn.execute("SELECT data FROM snapshots WHERE id=?", (snap_id,)).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


# ── 快照采集 ──

def take_snapshot(comment=""):
    """采集全系统快照并存储"""
    now = datetime.now(timezone.utc).isoformat()

    # 基础指标
    procs = ps_info()
    disks = disk_info()
    diski = disk_inodes()
    mem = mem_info()
    upt = uptime_info()
    net_conns = network_connections()
    net_socks = network_sockets()
    users_list = users()
    top10_cpu = top_processes(10, "cpu_percent")
    top10_mem = top_processes(10, "rss")

    # 聚合指标
    total_mem = int(mem.get("total", 0))
    used_mem = int(mem.get("used", 0))
    mem_pct = round(used_mem / total_mem * 100, 1) if total_mem else 0

    # 磁盘汇总
    disk_summary = []
    for d in disks:
        raw = d.get("use_percent", "0")
        if isinstance(raw, str):
            raw = raw.replace("%", "")
        try:
            pct = int(raw)
        except (ValueError, AttributeError):
            pct = 0
        disk_summary.append({
            "filesystem": d.get("filesystem", ""),
            "size": d.get("size", ""),
            "used": d.get("used", ""),
            "avail": d.get("avail", ""),
            "use_percent": pct,
            "mounted": d.get("mounted_on", ""),
        })

    # 连接统计
    port_summary = {}
    for c in net_conns:
        addr = c.get("local_address", "")
        if ":" in addr:
            _, port = addr.rsplit(":", 1)
            port_summary[port] = port_summary.get(port, 0) + 1

    uptime_seconds = int(upt.get("uptime_total_seconds", 0) or 0)
    uptime_days = uptime_seconds // 86400

    snapshot = {
        "timestamp": now,
        "comment": comment,
        "hostname": os.uname().nodename,
        "kernel": os.uname().release,
        "processes": {
            "count": len(procs),
            "top_cpu": [
                {"pid": p.get("pid"), "cpu": float(p.get("cpu_percent", 0) or 0), "cmd": p.get("command", "")[:60]}
                for p in top10_cpu
            ],
            "top_mem": [
                {"pid": p.get("pid"), "rss": p.get("rss", 0), "cmd": p.get("command", "")[:60]}
                for p in top10_mem
            ],
        },
        "memory": {
            "total_mb": total_mem,
            "used_mb": used_mem,
            "free_mb": int(mem.get("free", 0)),
            "used_pct": mem_pct,
        },
        "disks": disk_summary,
        "disk_inodes": [
            {"fs": d.get("filesystem", ""), "use_pct": d.get("use_percent", "")}
            for d in diski
        ],
        "uptime_seconds": uptime_seconds,
        "uptime_days": uptime_days,
        "network": {
            "listening_ports": len(net_conns),
            "port_summary": port_summary,
        },
        "users": [{"user": u.get("user", ""), "from": u.get("from", "")} for u in users_list],
    }

    # 持久化
    conn = _ensure_db()
    conn.execute(
        "INSERT INTO snapshots (taken_at, comment, data) VALUES (?, ?, ?)",
        (now, comment, json.dumps(snapshot, ensure_ascii=False, default=str)),
    )
    conn.commit()
    snap_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # 清理旧快照: 保留最近96条
    conn.execute("""
        DELETE FROM snapshots WHERE id NOT IN (
            SELECT id FROM snapshots ORDER BY id DESC LIMIT 96
        )
    """)
    deleted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()

    if deleted:
        print(f"   🧹 已清理 {deleted} 条旧快照 (保留最近96条)")

    return snap_id, snapshot


# ── 趋势查询 ──

def query_trend_data(days=7):
    """
    从快照DB提取趋势数据 (内存/磁盘/进程数时间序列)
    返回列表, 按时间升序, 每条包含 timestamp/mem_pct/disk_pct/proc_count
    """
    from datetime import datetime as dt, timedelta
    import json as _json

    conn = _ensure_db()
    cutoff = dt.now() - timedelta(days=days)
    rows = conn.execute(
        "SELECT id, taken_at, data FROM snapshots WHERE taken_at >= ? ORDER BY taken_at",
        (cutoff.isoformat()[:19],)
    ).fetchall()
    conn.close()

    result = []
    for row in rows:
        taken_at, raw = row[1], row[2]
        if isinstance(raw, str):
            try:
                snap = _json.loads(raw)
            except _json.JSONDecodeError:
                continue
        else:
            snap = raw
        # 提取关键指标
        mem_pct = snap.get("memory", {}).get("used_pct", None)
        disks = snap.get("disks", [])
        # 找根分区(/)的磁盘使用率，找不到则取第一个
        disk_pct = None
        for d in disks:
            if d.get("mounted", "") == "/" or d.get("filesystem", "").startswith("/dev/"):
                pct = d.get("use_percent")
                if pct is not None and pct > 0:
                    disk_pct = pct
                elif d.get("used") and d.get("size"):
                    # use_percent为空时手动计算
                    disk_pct = round(d["used"] / d["size"] * 100, 1)
                if d.get("mounted", "") == "/":
                    break
        if disk_pct is None and disks:
            disk_pct = disks[0].get("use_percent")
        proc_count = snap.get("processes", {}).get("count", None)
        result.append({
            "timestamp": taken_at[:16],
            "mem_pct": mem_pct,
            "disk_pct": disk_pct,
            "proc_count": proc_count,
            "uptime_days": snap.get("uptime_days", None),
        })
    return result

# ── 列出 ──

def list_snapshots():
    conn = _ensure_db()
    rows = conn.execute(
        "SELECT id, taken_at, comment FROM snapshots ORDER BY id"
    ).fetchall()
    conn.close()
    return rows


# ── 对比 ──

def diff_snapshots(id1, id2):
    conn = _ensure_db()
    s1 = _get_snapshot_data(conn, id1)
    s2 = _get_snapshot_data(conn, id2)
    conn.close()

    if s1 is None or s2 is None:
        return {"error": f"快照不存在: id={id1 if s1 is None else id2}"}

    diff = {
        "snapshot_1": {"id": id1, "time": s1["timestamp"], "comment": s1.get("comment", "")},
        "snapshot_2": {"id": id2, "time": s2["timestamp"], "comment": s2.get("comment", "")},
        "time_delta_hours": _hours_between(s1["timestamp"], s2["timestamp"]),
        "drifts": [],
        "critical": [],
    }

    # 进程数变化
    p1 = s1["processes"]["count"]
    p2 = s2["processes"]["count"]
    delta_p = p2 - p1
    if abs(delta_p) > 5:
        diff["drifts"].append({
            "metric": "进程数",
            "before": p1, "after": p2, "delta": delta_p,
            "severity": "warning" if abs(delta_p) > 20 else "info",
        })

    # 内存变化
    mp1 = s1["memory"]["used_pct"]
    mp2 = s2["memory"]["used_pct"]
    delta_mem = round(mp2 - mp1, 1)
    if abs(delta_mem) > 5:
        diff["drifts"].append({
            "metric": "内存使用率(%)",
            "before": mp1, "after": mp2, "delta": delta_mem,
            "severity": "critical" if mp2 > 90 else "warning",
        })

    # 磁盘变化
    disk_map1 = {d["mounted"]: d for d in s1["disks"]}
    disk_map2 = {d["mounted"]: d for d in s2["disks"]}
    all_mounts = set(disk_map1.keys()) | set(disk_map2.keys())
    for mnt in sorted(all_mounts):
        d1 = disk_map1.get(mnt)
        d2 = disk_map2.get(mnt)
        if d1 and d2:
            diff_pct = d2["use_percent"] - d1["use_percent"]
            if abs(diff_pct) > 3:
                diff["drifts"].append({
                    "metric": f"磁盘使用率({mnt})",
                    "before": f"{d1['use_percent']}%",
                    "after": f"{d2['use_percent']}%",
                    "delta": f"{diff_pct:+.0f}%",
                    "severity": "critical" if d2["use_percent"] > 85 else "warning",
                })
        elif d1 is None:
            diff["critical"].append(f"挂载点消失: {mnt}")
        else:
            diff["critical"].append(f"新挂载点: {mnt}")

    # 监听端口变化
    ports1 = set(s1["network"]["port_summary"].keys())
    ports2 = set(s2["network"]["port_summary"].keys())
    new_ports = ports2 - ports1
    gone_ports = ports1 - ports2
    for p in sorted(new_ports):
        diff["critical"].append(f"新监听端口: {p}")
    for p in sorted(gone_ports):
        diff["critical"].append(f"端口停止监听: {p}")

    # uptime变化(重启检测)
    u1 = float(s1.get("uptime_seconds", 0) or 0)
    u2 = float(s2.get("uptime_seconds", 0) or 0)
    if u2 < u1 - 60:  # uptime减少 >1min → 可能重启
        diff["critical"].append(f"⚠️ 系统可能重启: uptime从{u1}s→{u2}s")

    return diff


def _hours_between(t1, t2):
    try:
        dt1 = datetime.fromisoformat(t1)
        dt2 = datetime.fromisoformat(t2)
        return round(abs((dt2 - dt1).total_seconds()) / 3600, 1)
    except Exception:
        return 0


# ── CLI ──

def main():
    if len(sys.argv) < 2:
        print("用法: system_snapshot_db.py <take|list|diff|auto> [args]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "take":
        comment = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        snap_id, data = take_snapshot(comment)
        print(f"✅ 快照 #{snap_id} 已保存 [{data['timestamp']}]")
        print(f"   主机: {data['hostname']} | 内核: {data['kernel']}")
        print(f"   进程: {data['processes']['count']} | 内存: {data['memory']['used_pct']}% | 监听端口: {data['network']['listening_ports']}")
        disks_str = ", ".join(f'{d["mounted"]}={d["use_percent"]}%' for d in data['disks'][:5])
        print(f"   磁盘: {disks_str}")
        if comment:
            print(f"   备注: {comment}")
        return

    if cmd == "list":
        rows = list_snapshots()
        if not rows:
            print("📭 暂无快照")
            return
        print(f"{'ID':>3}  {'时间':<28}  {'备注'}")
        print("-" * 60)
        for r in rows:
            print(f"{r[0]:>3}  {r[1]:<28}  {r[2]}")
        print(f"\n共 {len(rows)} 条快照，存储于 {DB_PATH}")
        return

    if cmd == "diff":
        if len(sys.argv) < 4:
            print("用法: system_snapshot_db.py diff <id1> <id2>")
            sys.exit(1)
        result = diff_snapshots(int(sys.argv[2]), int(sys.argv[3]))
        if "error" in result:
            print(f"❌ {result['error']}")
            sys.exit(1)
        print("=" * 60)
        print(f"📊 快照对比: #{sys.argv[2]} vs #{sys.argv[3]}")
        print(f"   #{sys.argv[2]}: {result['snapshot_1']['time']}")
        print(f"   #{sys.argv[3]}: {result['snapshot_2']['time']}")
        print(f"   间隔: {result['time_delta_hours']} 小时")
        print("=" * 60)
        if result["critical"]:
            print("\n🔴 关键漂移:")
            for c in result["critical"]:
                print(f"  • {c}")
        if result["drifts"]:
            print("\n🟡 指标漂移:")
            for d in result["drifts"]:
                level = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(d["severity"], "ℹ️")
                print(f"  {level} {d['metric']}: {d['before']} → {d['after']} ({d.get('delta', '')})")
        if not result["critical"] and not result["drifts"]:
            print("\n✅ 无显著漂移")
        return

    if cmd == "auto":
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--days", type=int, default=1)
        args, _ = parser.parse_known_args(sys.argv[2:])
        rows = list_snapshots()
        if len(rows) < 2:
            print("❌ 至少需要2条快照才能对比")
            sys.exit(1)
        # 取最新和指定天数前
        latest = rows[-1]
        target_time = datetime.fromisoformat(latest[1]).timestamp() - args.days * 86400
        old = None
        for r in reversed(rows):
            if datetime.fromisoformat(r[1]).timestamp() <= target_time:
                old = r
                break
        if old is None:
            old = rows[0]
        print(f"自动对比: #{old[0]}({old[1][:10]}) vs #{latest[0]}({latest[1][:10]})")
        result = diff_snapshots(old[0], latest[0])
        if "error" in result:
            print(f"❌ {result['error']}")
            sys.exit(1)
        # 打印简略版
        if result["critical"]:
            print(f"\n🔴 {len(result['critical'])} 项关键漂移:")
            for c in result["critical"]:
                print(f"  • {c}")
        if result["drifts"]:
            print(f"\n🟡 {len(result['drifts'])} 项指标漂移:")
            for d in result["drifts"][:5]:
                print(f"  • {d['metric']}: {d['before']} → {d['after']}")
        if not result["critical"] and not result["drifts"]:
            print("\n✅ 无显著漂移")
        return

    print(f"未知命令: {cmd}")
    sys.exit(1)


if __name__ == "__main__":
    main()
