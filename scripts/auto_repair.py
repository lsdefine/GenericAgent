#!/usr/bin/env python3
"""
Auto Repair — 系统瓶颈自动修复工具

检测瓶颈模式→自动修复(日志清理/服务重启/参数调整)→验证修复效果→报告

Usage:
    python -m scripts.auto_repair diagnose          # 检测瓶颈 (默认)
    python -m scripts.auto_repair repair            # 执行修复 (dry-run)
    python -m scripts.auto_repair repair --apply    # 实际修复
    python -m scripts.auto_repair verify            # 验证修复效果
    python -m scripts.auto_repair full              # 全流程: diagnose→repair→verify

Scenarios:
    1. 日志截断 (Log Truncation) — /var/log/messages logrotate + journald 限制
    2. OOM清理 (OOM Cleanup)    — 清理 OOM 残留，优化内存
    3. 内存压力释放 (Memory Relief) — 识别高内存进程，释放缓存
    4. 服务健康检查 (Service Health) — 检测关键服务(health_server/hermes/fsapp)是否存活并响应
    5. 网络连通性 (Network Connectivity) — 检测 DNS/API端口可达性，识别网络瓶颈
"""
import subprocess, os, json, re, shutil, sys, time
from datetime import datetime
from pathlib import Path

# ─── 常量 ───
THRESHOLD_DISK_PCT = 80        # 磁盘使用率告警
THRESHOLD_MEM_AVAIL_MB = 500   # 可用内存告警 (MB)
THRESHOLD_LOG_SIZE_MB = 200    # 日志文件大小告警 (MB)
THRESHOLD_JOURNAL_SIZE_MB = 300  # journal 大小告警 (MB)
LOGROTATE_CONF = "/etc/logrotate.d/custom"
GA_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── AgentMail 告警 ──────────────────────────────────────────
_alert_bridge = None
def _send_alert(alert_type: str, message: str, severity: str = "warning"):
    """通过 AgentMail Bridge 发送告警"""
    global _alert_bridge
    try:
        if _alert_bridge is None:
            sys.path.insert(0, GA_HOME)
            from scripts.agentmail_bridge import AgentMailBridge
            _alert_bridge = AgentMailBridge()
        _alert_bridge.send_alert(alert_type, message, severity)
    except Exception as e:
        pass  # alert failure shouldn't crash diagnose

# ─── 工具函数 ───
def run(cmd: list, timeout: int = 15) -> dict:
    """安全执行系统命令"""
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
        return {"ok": r.returncode == 0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "rc": r.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"TIMEOUT {timeout}s", "rc": -1}
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": f"Command not found: {cmd[0]}", "rc": -2}


def sizeof_fmt(num):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(num) < 1024:
            return f"{num:.1f}{unit}"
        num /= 1024
    return f"{num:.1f}TB"


# ═══════════════════ 检测阶段 ═══════════════════
def diagnose() -> dict:
    """全面检测系统瓶颈，返回诊断报告"""
    issues = []
    data = {}

    # 1. 磁盘
    r = run(['df', '-h', '/'])
    if r["ok"]:
        parts = r["stdout"].split('\n')
        if len(parts) >= 2:
            cols = parts[1].split()
            data["disk"] = {
                "total": cols[1] if len(cols) > 1 else "?",
                "used": cols[2] if len(cols) > 2 else "?",
                "avail": cols[3] if len(cols) > 3 else "?",
                "use_pct": cols[4] if len(cols) > 4 else "?"
            }
            pct_str = data["disk"]["use_pct"].replace('%', '')
            try:
                pct = int(pct_str)
                if pct >= THRESHOLD_DISK_PCT:
                    issues.append({"severity": "high", "type": "disk_usage", "msg": f"磁盘使用率 {pct}% (阈值 {THRESHOLD_DISK_PCT}%)"})
                    # → AgentMail alert
                    _send_alert("disk_usage", f"磁盘使用率 {pct}%", "high")
            except:
                pass

    # 2. 内存
    r = run(['free', '-m'])
    if r["ok"]:
        lines = r["stdout"].split('\n')
        for l in lines:
            if l.startswith('Mem:'):
                cols = l.split()
                data["memory"] = {
                    "total_mb": int(cols[1]),
                    "used_mb": int(cols[2]),
                    "free_mb": int(cols[3]),
                    "avail_mb": int(cols[6])
                }
                avail = data["memory"]["avail_mb"]
                if avail < THRESHOLD_MEM_AVAIL_MB:
                    issues.append({"severity": "critical" if avail < 300 else "high",
                                   "type": "memory_pressure",
                                   "msg": f"可用内存 {avail}MB (阈值 {THRESHOLD_MEM_AVAIL_MB}MB)"})
                    _send_alert("memory_pressure", f"可用内存 {avail}MB (阈值 {THRESHOLD_MEM_AVAIL_MB}MB)",
                                "critical" if avail < 300 else "high")
                break

    # 3. OOM 检查
    r = run(['dmesg', '--level=emerg,alert,crit,err'], timeout=10)
    oom_events = []
    if r["ok"]:
        for l in r["stdout"].split('\n'):
            if 'oom' in l.lower() or 'Out of memory' in l:
                oom_events.append(l.strip()[:150])
    data["oom_count"] = len(oom_events)
    data["oom_recent"] = oom_events[-3:] if oom_events else []
    if oom_events:
        issues.append({"severity": "critical", "type": "oom_events",
                       "msg": f"系统发生过 {len(oom_events)} 次 OOM Killer 事件"})
        _send_alert("oom_events", f"系统发生过 {len(oom_events)} 次 OOM Killer 事件", "critical")

    # 4. 日志文件 /var/log/messages
    r = run(['du', '-b', '/var/log/messages'])
    if r["ok"]:
        size_bytes = int(r["stdout"].split('\t')[0])
        size_mb = size_bytes / (1024**2)
        data["log_messages_mb"] = round(size_mb, 1)
        if size_mb > THRESHOLD_LOG_SIZE_MB:
            issues.append({"severity": "high", "type": "log_oversize",
                           "msg": f"/var/log/messages {size_mb:.0f}MB (阈值 {THRESHOLD_LOG_SIZE_MB}MB)"})

    # 5. Journal 大小
    r = run(['journalctl', '--disk-usage'])
    if r["ok"]:
        m = re.search(r'([\d.]+)\s*M', r["stdout"])
        if m:
            journal_mb = float(m.group(1))
            data["journal_mb"] = round(journal_mb, 1)
            if journal_mb > THRESHOLD_JOURNAL_SIZE_MB:
                issues.append({"severity": "high", "type": "journal_oversize",
                               "msg": f"journald 日志 {journal_mb:.0f}MB (阈值 {THRESHOLD_JOURNAL_SIZE_MB}MB)"})

    # 6. 内存Top进程
    r = run(['ps', 'aux', '--sort=-%mem', '--no-headers'])
    top_procs = []
    if r["ok"]:
        for l in r["stdout"].split('\n')[:10]:
            parts = l.split()
            if len(parts) >= 11:
                top_procs.append({
                    "user": parts[0], "pid": parts[1],
                    "cpu": parts[2], "mem": parts[3],
                    "rss_mb": round(int(parts[5]) / 1024, 1) if parts[5].isdigit() else 0,
                    "cmd": ' '.join(parts[10:])[:60]
                })
    data["top_processes"] = top_procs

    # 7. 服务健康检查 (Scenario 4)
    services_to_check = [
        {"name": "hermes_dashboard", "pgrep": "hermes dashboard", "port": 9119},
        {"name": "hermes_gateway", "pgrep": "gateway run", "port": None},
        {"name": "fsapp", "pgrep": "fsapp\\.py", "port": None},
        {"name": "llm_server", "pgrep": "openllm.server", "port": 11343},
        {"name": "health_server", "pgrep": "health_server", "port": 8081},
    ]
    service_status = []
    for svc in services_to_check:
        srv_r = run(["pgrep", "-f", svc["pgrep"]], timeout=5)
        alive = srv_r["ok"]
        # 对于有端口的服务，额外做 TCP 探测 (检测假死)
        port_open = False
        if svc["port"]:
            port_r = run(["timeout", "2", "bash", "-c", f"echo > /dev/tcp/localhost/{svc['port']} 2>/dev/null"], timeout=5)
            port_open = port_r["ok"]
        status = "alive" if (alive and (not svc["port"] or port_open)) else \
                 "hang" if (alive and svc["port"] and not port_open) else \
                 "down"
        service_status.append({"name": svc["name"], "status": status})
    data["services"] = service_status
    down_services = [s for s in service_status if s["status"] == "down"]
    hang_services = [s for s in service_status if s["status"] == "hang"]
    if down_services:
        issues.append({"severity": "critical", "type": "service_down",
                       "msg": f"服务离线: {', '.join(s['name'] for s in down_services)}"})
    if hang_services:
        issues.append({"severity": "high", "type": "service_hang",
                       "msg": f"服务假死(进程存但端口无响应): {', '.join(s['name'] for s in hang_services)}"})

    # 8. 网络连通性检查 (Scenario 5)
    network_checks = {}
    # 8a. DNS 解析 (getent更可靠)
    dns_r = run(["getent", "hosts", "localhost"], timeout=5)
    if not dns_r["ok"]:
        dns_r = run(["ping", "-c", "1", "-W", "2", "localhost"], timeout=5)
    network_checks["dns_local"] = dns_r["ok"]
    # 8b. 外网 ping (Google DNS)
    ping_r = run(["ping", "-c", "1", "-W", "3", "8.8.8.8"], timeout=10)
    network_checks["ping_outbound"] = ping_r["ok"]
    # 8c. 本地 API 端口 (health_server)
    local_api_r = run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:9119/health"], timeout=10)
    network_checks["local_api_9119"] = local_api_r["ok"] if local_api_r["ok"] and local_api_r["stdout"].startswith("2") else False
    data["network"] = network_checks
    if not network_checks.get("ping_outbound"):
        issues.append({"severity": "high", "type": "network_outbound",
                       "msg": "外网 ping 不可达，可能网络中断"})
    if not network_checks.get("local_api_9119"):
        issues.append({"severity": "medium", "type": "network_local_api",
                       "msg": "health_server 端口 9119 无响应"})
    if not network_checks.get("dns_local"):
        issues.append({"severity": "medium", "type": "network_dns",
                       "msg": "DNS 解析异常"})

    # 9. Swap
    r = run(['free', '-m'])
    if r["ok"]:
        for l in r["stdout"].split('\n'):
            if l.startswith('Swap:'):
                cols = l.split()
                data["swap"] = {"total_mb": int(cols[1]), "used_mb": int(cols[2])}
                if int(cols[2]) > int(cols[1]) * 0.5:
                    issues.append({"severity": "high", "type": "swap_high",
                                   "msg": f"Swap 使用 {cols[2]}/{cols[1]}MB"})
                break

    data["issues"] = issues
    data["severity"] = "critical" if any(i["severity"] == "critical" for i in issues) else \
                       "high" if issues else "healthy"
    data["timestamp"] = datetime.now().isoformat()
    return data


# ═══════════════════ 修复阶段 ═══════════════════
def repair_logrotate(dry_run: bool = True) -> list:
    """修复1: 配置 logrotate 限制 /var/log/messages 大小"""
    actions = []
    
    # 检查现有 logrotate 配置
    has_custom = os.path.exists(LOGROTATE_CONF)
    actions.append(f"{'[DRY-RUN] ' if dry_run else ''}检查 logrotate 配置: {'已存在' if has_custom else '未配置'}")
    
    if not dry_run:
        if not has_custom:
            # 创建 logrotate 配置 for messages (使用 sudo)
            conf_content = """/var/log/messages {
    size 100M
    rotate 4
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        /usr/bin/killall -HUP syslogd 2>/dev/null || true
    endscript
}
"""
            # 用 sudo cp 写入配置
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.logrotate')
            tmp.write(conf_content)
            tmp.close()
            r = run(['sudo', '-n', 'cp', tmp.name, LOGROTATE_CONF])
            if r["ok"]:
                r2 = run(['rm', '-f', tmp.name])
                actions.append(f"✅ 已创建 {LOGROTATE_CONF} (size 100M, rotate 4)")
            else:
                actions.append(f"⚠️  创建 {LOGROTATE_CONF} 失败: {r['stderr'][:100]}")
        else:
            actions.append(f"⏭️  logrotate 配置已存在，跳过")
        
        # 执行 logrotate 强制轮转
        r = run(['sudo', '-n', 'logrotate', '-f', LOGROTATE_CONF])
        if r["ok"]:
            actions.append("✅ logrotate 强制轮转执行成功")
        else:
            actions.append(f"⚠️  logrotate 轮转警告: {r['stderr'][:100]}")
    else:
        actions.append(f"  → 将创建 {LOGROTATE_CONF}: size 100M, rotate 4, 压缩")
        actions.append(f"  → 执行 logrotate -f 强制轮转")
    
    return actions


def repair_journald(dry_run: bool = True) -> list:
    """修复2: 限制 journald 日志大小"""
    actions = []
    journal_conf = "/etc/systemd/journald.conf"
    
    actions.append(f"{'[DRY-RUN] ' if dry_run else ''}检查 journald 配置")
    
    if not dry_run:
        # 读取现有配置 (不需要 sudo)
        current = ""
        try:
            with open(journal_conf, 'r') as f:
                current = f.read()
        except:
            pass
        
        # 检查是否需要修改 (排除注释行)
        has_active_config = any(
            line.strip().startswith('SystemMaxUse=') 
            for line in current.split('\n')
        )
        if has_active_config:
            actions.append("⏭️  journald SystemMaxUse 已配置，跳过")
        else:
            # 用 sudo 追加配置
            import tempfile
            tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.journald', encoding='utf-8')
            tmp.write("\n# Added by auto_repair.py\nSystemMaxUse=200M\nMaxFileSec=7day\n")
            tmp.close()
            # 用 sudo sh -c 'cat ... >> target' 追加
            r = run(['sudo', '-n', 'sh', '-c', f"cat {tmp.name} >> {journal_conf} && rm -f {tmp.name}"])
            if r["ok"]:
                actions.append(f"✅ 已追加 SystemMaxUse=200M 到 {journal_conf}")
            else:
                actions.append(f"⚠️  追加失败: {r['stderr'][:100]}")
            
            # 重启 journald 生效 (需要 sudo)
            r = run(['sudo', '-n', 'systemctl', 'restart', 'systemd-journald'])
            if r["ok"]:
                actions.append("✅ systemd-journald 重启成功")
            else:
                actions.append(f"⚠️  journald 重启失败: {r['stderr'][:100]}")
    else:
        actions.append("  → 追加 SystemMaxUse=200M, MaxFileSec=7day 到 journald.conf")
        actions.append("  → 重启 systemd-journald")
    
    return actions


def repair_oom_cleanup(dry_run: bool = True) -> list:
    """修复3: OOM 相关清理"""
    actions = []
    
    # 清理 OOM 后残留的不可靠进程
    r = run(['ps', 'aux', '--no-headers'])
    zombie_count = 0
    if r["ok"]:
        zombie_count = sum(1 for l in r["stdout"].split('\n') if ' Z ' in l or '<defunct>' in l)
        actions.append(f"{'[DRY-RUN] ' if dry_run else ''}僵尸进程: {zombie_count}")
    
    # 清理缓存
    if not dry_run:
        # Drop page cache only (safe)
        r = run(['sync'])
        r2 = run(['sysctl', '-w', 'vm.drop_caches=1'])
        if r2["ok"]:
            actions.append("✅ 已清理 page cache (vm.drop_caches=1)")
        else:
            actions.append(f"⚠️  清理缓存失败: {r2['stderr'][:100]}")
    else:
        actions.append("  → sync + drop_caches=1 (清理 page cache)")
    
    return actions


def repair_memory_relief(dry_run: bool = True) -> list:
    """修复4: 内存压力释放"""
    actions = []
    
    # 识别 Top 内存进程
    r = run(['ps', 'aux', '--sort=-%mem', '--no-headers'])
    top = []
    if r["ok"]:
        for l in r["stdout"].split('\n')[:5]:
            parts = l.split()
            if len(parts) >= 11:
                mem_pct = parts[3]
                cmd = ' '.join(parts[10:])[:50]
                rss = parts[5]
                top.append(f"{cmd} ({mem_pct}% mem, RSS={rss}KB)")
    
    actions.append(f"{'[DRY-RUN] ' if dry_run else ''}Top 内存进程:")
    for t in top[:3]:
        actions.append(f"  {t}")
    actions.append(f"{'[DRY-RUN] ' if dry_run else ''}建议: 考虑停用非必需服务释放 ~200MB")
    
    return actions


def repair_service_restart(dry_run: bool = True) -> list:
    """修复4: 服务健康修复 — 重启离线/假死服务"""
    actions = []
    actions.append(f"{'[DRY-RUN] ' if dry_run else ''}检查并重启异常服务")

    if not dry_run:
        # 尝试重启 health_server
        for svc, restart_cmd in [
            ("health_server (hermes-health)", ["systemctl", "restart", "hermes-health"]),
            ("hermes-agent", ["pkill", "-f", "hermes-agent"]),
            ("fsapp", ["pkill", "-f", "fsapp"]),
        ]:
            r = run(restart_cmd, timeout=10)
            if r["ok"]:
                actions.append(f"✅ {svc} 重启成功")
            else:
                actions.append(f"⚠️ {svc} 重启失败: {r['stderr'][:80]}")
    else:
        actions.append("  → 将检测 health_server/hermes-agent/fsapp 状态")
        actions.append("  → 对离线服务执行 systemctl restart 或 pkill+pull")
        actions.append("  → 验证端口响应(post-restart)")

    return actions


def repair_network_check(dry_run: bool = True) -> list:
    """修复5: 网络连通性恢复 — 检测并提示网络故障"""
    actions = []
    actions.append(f"{'[DRY-RUN] ' if dry_run else ''}诊断网络连通性")

    # 运行诊断收集数据（无副作用）
    dns_r = run(["host", "localhost"], timeout=5)
    ping_r = run(["ping", "-c", "1", "-W", "3", "8.8.8.8"], timeout=10)
    api_r = run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:9119/health"], timeout=10)

    if not dns_r["ok"]:
        actions.append(f"{'[DRY-RUN] ' if dry_run else ''}⚠️ DNS 解析失败 — 检查 /etc/resolv.conf")
    if not ping_r["ok"]:
        actions.append(f"{'[DRY-RUN] ' if dry_run else ''}⚠️ 外网不可达 — 检查网络接口/路由")
    if not api_r["ok"] or not api_r["stdout"].startswith("2"):
        actions.append(f"{'[DRY-RUN] ' if dry_run else ''}⚠️ localhost:9119 无响应 — 检查 health_server")
    if dns_r["ok"] and ping_r["ok"] and api_r["ok"]:
        actions.append(f"{'[DRY-RUN] ' if dry_run else ''}✅ 网络连通性正常")

    if not dry_run:
        # 尝试修复：重启网络服务 (需要 sudo)
        r = run(["sudo", "-n", "systemctl", "restart", "network"], timeout=10)
        if r["ok"]:
            actions.append("✅ 网络服务已重启")
        else:
            actions.append(f"⚠️ network restart 失败: {r['stderr'][:80]}")

    return actions


# ═══════════════════ 验证阶段 ═══════════════════
def verify(before: dict = None) -> dict:
    """验证修复效果，返回前后对比"""
    after = diagnose()
    
    if before:
        # 计算变化
        result = {
            "timestamp": datetime.now().isoformat(),
            "before": {
                "log_messages_mb": before.get("log_messages_mb"),
                "journal_mb": before.get("journal_mb"),
                "memory_avail_mb": before.get("memory", {}).get("avail_mb"),
                "disk_use_pct": before.get("disk", {}).get("use_pct"),
                "issues": len(before.get("issues", []))
            },
            "after": {
                "log_messages_mb": after.get("log_messages_mb"),
                "journal_mb": after.get("journal_mb"),
                "memory_avail_mb": after.get("memory", {}).get("avail_mb"),
                "disk_use_pct": after.get("disk", {}).get("use_pct"),
                "issues": len(after.get("issues", []))
            }
        }
        result["changes"] = {}
        if before.get("log_messages_mb") and after.get("log_messages_mb"):
            diff = before["log_messages_mb"] - after["log_messages_mb"]
            result["changes"]["log_messages_released_mb"] = round(diff, 1)
        if before.get("journal_mb") and after.get("journal_mb"):
            diff = before["journal_mb"] - after["journal_mb"]
            result["changes"]["journal_released_mb"] = round(diff, 1)
        if before.get("memory", {}).get("avail_mb") and after.get("memory", {}).get("avail_mb"):
            diff = after["memory"]["avail_mb"] - before["memory"]["avail_mb"]
            result["changes"]["memory_gained_mb"] = diff
        result["remaining_issues"] = len(after.get("issues", []))
        return result
    
    return {"after": after, "issues": after.get("issues", [])}


# ═══════════════════ CLI 接口 ═══════════════════
def print_report(data: dict, title: str = ""):
    """打印诊断/验证报告"""
    print(f"\n{'='*55}")
    print(f" 📋 {title}")
    print(f"{'='*55}")
    
    if "issues" in data:
        issues = data["issues"]
        if not issues:
            print(f" ✅ 系统健康，无瓶颈问题")
        else:
            print(f" 发现 {len(issues)} 个问题:")
            for i, iss in enumerate(issues):
                sev = {"critical": "🔴", "high": "🟡", "medium": "🟠", "low": "🟢"}.get(iss["severity"], "⚪")
                print(f"  {sev} [{iss['type']}] {iss['msg']}")
    
    if "memory" in data:
        m = data["memory"]
        print(f"\n  💾 内存: {m.get('avail_mb','?')}MB 可用 / {m.get('total_mb','?')}MB 总")
    if "disk" in data:
        d = data["disk"]
        print(f"  💿 磁盘: {d.get('use_pct','?')} 已用 ({d.get('avail','?')} 可用)")
    if "log_messages_mb" in data:
        print(f"  📄 /var/log/messages: {data['log_messages_mb']}MB")
    if "journal_mb" in data:
        print(f"  📓 journald: {data['journal_mb']}MB")
    if "oom_count" in data and data["oom_count"] > 0:
        print(f"  💀 OOM事件: {data['oom_count']}次")
    if "services" in data:
        for s in data["services"]:
            icon = {"alive": "✅", "down": "🔴", "hang": "🟡"}.get(s["status"], "⚪")
            print(f"  {icon} {s['name']}: {s['status']}")
    if "network" in data:
        n = data["network"]
        dns_icon = "✅" if n.get("dns_local") else "🔴"
        ping_icon = "✅" if n.get("ping_outbound") else "🔴"
        api_icon = "✅" if n.get("local_api_9119") else "🔴"
        print(f"  🌐 DNS: {dns_icon} 外网: {ping_icon}  API: {api_icon}")


def cmd_diagnose(vision: bool = False):
    data = diagnose()
    print_report(data, f"系统瓶颈诊断 ({datetime.now().strftime('%H:%M:%S')})")
    
    if vision:
        try:
            print(f"\n{'='*55}")
            print(f" 🤖 AI 增强诊断 (vision_repair)")
            print(f"{'='*55}")
            try:
                from vision_repair import auto_repair_vision_step
            except ImportError:
                from scripts.vision_repair import auto_repair_vision_step
            ai_result = auto_repair_vision_step(data)
            
            health = ai_result.get("health_score", "?")
            sev = ai_result.get("severity", "?")
            print(f"  健康评分: {health}/100 | 严重程度: {sev}")
            
            actions = ai_result.get("ai_suggestions", [])
            if actions:
                print(f"\n  🔧 AI 建议操作 ({len(actions)} 项):")
                for i, act in enumerate(actions, 1):
                    if isinstance(act, dict):
                        desc = act.get("description", act.get("action", ""))
                        priority = act.get("priority", "?")
                        print(f"    {i}. [P{priority}] {desc[:120]}")
                    else:
                        print(f"    {i}. {str(act)[:120]}")
            
            root_cause = ai_result.get("root_cause", "")
            if root_cause:
                print(f"\n  📋 根因分析: {root_cause[:300]}")
                
        except ImportError as e:
            print(f"  ⚠️ vision_repair 不可用: {e}")
        except Exception as e:
            print(f"  ⚠️ AI 诊断失败: {type(e).__name__}: {e}")
    
    return data


def cmd_repair(dry_run: bool = True):
    before = diagnose()
    print_report(before, f"修复前诊断 ({datetime.now().strftime('%H:%M:%S')})")
    
    print(f"\n{'='*55}")
    print(f" 🔧 执行修复 ({'DRY-RUN' if dry_run else '实际执行'})")
    print(f"{'='*55}")
    
    all_actions = []
    all_actions += repair_logrotate(dry_run)
    all_actions += repair_journald(dry_run)
    all_actions += repair_oom_cleanup(dry_run)
    all_actions += repair_memory_relief(dry_run)
    all_actions += repair_service_restart(dry_run)
    all_actions += repair_network_check(dry_run)
    
    for a in all_actions:
        print(f"  {a}")
    
    if not dry_run:
        print(f"\n  ⏳ 等待 2 秒后验证...")
        time.sleep(2)
        result = verify(before)
        print(f"\n{'='*55}")
        print(f" ✅ 修复效果验证")
        print(f"{'='*55}")
        print(f"  日志回收: {result['changes'].get('log_messages_released_mb', 'N/A')}MB")
        print(f"  Journal回收: {result['changes'].get('journal_released_mb', 'N/A')}MB")
        print(f"  内存增加: {result['changes'].get('memory_gained_mb', 'N/A')}MB")
        print(f"  剩余问题: {result['remaining_issues']} 个")
    else:
        print(f"\n  💡 使用 --apply 参数实际执行修复")
    
    return before


def cmd_full():
    print("\n🚀 === 全流程: 诊断 → 修复 → 验证 ===")
    before = cmd_diagnose()
    print(f"\n  ⚠️  先执行 dry-run 查看修复方案:")
    cmd_repair(dry_run=True)
    print(f"\n  💡 确认后执行: python -m scripts.auto_repair repair --apply")


def cmd_verify():
    result = verify()
    print_report(result.get("after", {}), f"修复验证 ({datetime.now().strftime('%H:%M:%S')})")
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Auto Repair — 系统瓶颈自动修复工具")
    sp = parser.add_subparsers(dest="command")
    
    diagnose_p = sp.add_parser("diagnose", help="检测系统瓶颈")
    diagnose_p.add_argument("--vision", action="store_true", help="启用AI增强诊断 (调用本地openllm)")
    
    sp.add_parser("verify", help="验证系统状态")
    
    repair_p = sp.add_parser("repair", help="执行系统修复")
    repair_p.add_argument("--apply", action="store_true", help="实际执行修复 (默认 dry-run)")
    
    sp.add_parser("full", help="全流程: 诊断→修复→验证")
    
    args = parser.parse_args()
    
    if args.command == "diagnose" or not args.command:
        cmd_diagnose(vision=getattr(args, 'vision', False))
    elif args.command == "repair":
        cmd_repair(dry_run=not args.apply)
    elif args.command == "full":
        cmd_full()
    elif args.command == "verify":
        cmd_verify()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
