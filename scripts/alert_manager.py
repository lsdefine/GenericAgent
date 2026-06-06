#!/usr/bin/env python3
"""
alert_manager.py — 系统告警管理器 🚨

基于 system_resources 实时指标，按照规则判定是否告警，
并通过多种通道（桌面通知/Webhook/邮件）推送通知。

用法:
  python alert_manager.py config                   # 查看当前规则
  python alert_manager.py config --set cpu=90,mem=85,disk=92  # 配置阈值
  python alert_manager.py check                    # 检查当前状态并触发告警
  python alert_manager.py trigger --metric cpu --value 95  # 手动触发
  python alert_manager.py push --channel webhook --msg "test"  # 测试推送

集成到 health_dashboard.py:
  from scripts.alert_manager import AlertManager
  mgr = AlertManager()
  alerts = mgr.check_and_alert()  # 返回触发的告警列表
"""

import os, sys, json, time, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

# ── 默认配置 ──────────────────────────────────────────────────────────
DEFAULT_RULES = {
    "cpu_percent": {
        "warning": 80.0,
        "critical": 90.0,
        "description": "CPU 使用率 %",
    },
    "memory_percent": {
        "warning": 75.0,
        "critical": 90.0,  # TODO要求 Mem>90%
        "description": "内存使用率 %",
    },
    "disk_percent": {
        "warning": 85.0,
        "critical": 92.0,
        "description": "磁盘使用率 %",
    },
    "load_avg": {
        "warning": 5.0,
        "critical": 10.0,  # TODO要求 Load>10
        "description": "系统负载平均值 (1min)",
    },
}

DEFAULT_CONFIG = {
    "rules": DEFAULT_RULES,
    "channels": {
        "desktop": {"enabled": True},
        "webhook": {"enabled": False, "url": ""},
        "email": {"enabled": True, "smtp_server": "", "to": "genericagent@agentmail.to", "use_agentmail": True},
        "feishu": {"enabled": True, "chat_id": "", "use_direct_api": True},
    },
    "cooldown_seconds": 300,  # 同一规则5分钟内不重复告警
}

CONFIG_PATH = "temp/alert_config.json"
ALERT_LOG = "temp/alert_log.json"


# ═══════════════════════════════════════════════════════════════════════
#  AlertManager 核心类
# ═══════════════════════════════════════════════════════════════════════

class AlertManager:
    """系统告警管理器"""

    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = Path(config_path)
        self.log_path = Path(ALERT_LOG)
        self.config = self._load_config()

    # ── 配置管理 ──────────────────────────────────────────────────────

    def _load_config(self) -> Dict:
        """加载配置，不存在则创建默认配置"""
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text())
            except (json.JSONDecodeError, Exception):
                pass
        return self._save_config(DEFAULT_CONFIG.copy())

    def _save_config(self, cfg: Dict) -> Dict:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        return cfg

    def get_config(self) -> Dict:
        return self.config

    def set_rules(self, overrides: Dict[str, Dict]) -> Dict:
        """动态设置告警阈值规则"""
        for metric, vals in overrides.items():
            if metric in self.config["rules"]:
                self.config["rules"][metric].update(vals)
            else:
                self.config["rules"][metric] = vals
        return self._save_config(self.config)

    def set_channel(self, channel: str, cfg: Dict) -> Dict:
        """配置通知通道"""
        if channel in self.config["channels"]:
            self.config["channels"][channel].update(cfg)
        else:
            self.config["channels"][channel] = cfg
        return self._save_config(self.config)

    # ── 指标采集 ──────────────────────────────────────────────────────

    def _get_cpu(self) -> float:
        """获取 CPU 使用率"""
        try:
            import psutil
            return psutil.cpu_percent(interval=0.5)
        except ImportError:
            # fallback: 读取 /proc/stat
            try:
                with open("/proc/stat") as f:
                    for line in f:
                        if line.startswith("cpu "):
                            parts = [int(x) for x in line.split()[1:]]
                            total = sum(parts)
                            idle = parts[3]
                            return round(100 * (1 - idle / total), 1)
            except Exception:
                return 0.0

    def _get_memory(self) -> float:
        """获取内存使用率"""
        try:
            import psutil
            return psutil.virtual_memory().percent
        except ImportError:
            try:
                with open("/proc/meminfo") as f:
                    mem = {}
                    for line in f:
                        k, v = line.split(":")[0], line.split()[1]
                        mem[k] = int(v)
                    total = mem.get("MemTotal", 1)
                    available = mem.get("MemAvailable", 0) or (mem.get("MemFree", 0))
                    return round(100 * (1 - available / total), 1)
            except Exception:
                return 0.0

    def _get_disk(self) -> float:
        """获取磁盘使用率 (/)"""
        try:
            import psutil
            return psutil.disk_usage("/").percent
        except ImportError:
            try:
                st = os.statvfs("/")
                total = st.f_frsize * st.f_blocks
                free = st.f_frsize * st.f_bfree
                return round(100 * (1 - free / total), 1)
            except Exception:
                return 0.0

    def _get_load_avg(self) -> float:
        """获取系统负载平均值 (1min)"""
        try:
            import psutil
            avg = psutil.getloadavg()
            return avg[0]
        except ImportError:
            try:
                with open("/proc/loadavg") as f:
                    parts = f.read().strip().split()
                    return float(parts[0])
            except Exception:
                return 0.0

    def get_metrics(self) -> Dict[str, float]:
        """获取当前系统指标"""
        return {
            "cpu_percent": self._get_cpu(),
            "memory_percent": self._get_memory(),
            "disk_percent": self._get_disk(),
            "load_avg": self._get_load_avg(),
        }

    # ── 告警判定 ──────────────────────────────────────────────────────

    def _check_rule(self, metric: str, value: float, rules: Dict) -> Optional[Dict]:
        """检查单条规则，返回告警信息或 None"""
        rule = rules.get(metric)
        if not rule:
            return None
        level = None
        if value >= rule.get("critical", 999):
            level = "critical"
        elif value >= rule.get("warning", 999):
            level = "warning"
        if not level:
            return None
        # 冷却检查
        if self._in_cooldown(metric, level):
            return None
        return {
            "metric": metric,
            "value": value,
            "level": level,
            "threshold": rule.get(level, 0),
            "description": rule.get("description", metric),
            "timestamp": datetime.now().isoformat(),
        }

    def _in_cooldown(self, metric: str, level: str) -> bool:
        """检查是否在冷却期"""
        if not self.log_path.exists():
            return False
        try:
            logs = json.loads(self.log_path.read_text())
            cooldown = self.config.get("cooldown_seconds", 300)
            for entry in reversed(logs):
                if entry.get("metric") == metric and entry.get("level") == level:
                    t = datetime.fromisoformat(entry["timestamp"])
                    if (datetime.now() - t).total_seconds() < cooldown:
                        return True
                    break
        except Exception:
            pass
        return False

    def _log_alert(self, alert: Dict):
        """记录告警到日志"""
        logs = []
        if self.log_path.exists():
            try:
                logs = json.loads(self.log_path.read_text())
            except Exception:
                pass
        logs.append(alert)
        # 最多保留100条
        if len(logs) > 100:
            logs = logs[-100:]
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(logs, indent=2, ensure_ascii=False))

    # ── 通知通道 ──────────────────────────────────────────────────────

    def _notify_desktop(self, alert: Dict) -> bool:
        """桌面通知"""
        title = f"🚨 {'CRITICAL' if alert['level']=='critical' else '⚠️ WARNING'}: {alert['description']}"
        msg = f"{alert['description']}: {alert['value']:.1f}% (阈值: {alert['threshold']}%)"
        try:
            subprocess.run(
                ["notify-send", title, msg, "-u", "critical" if alert['level']=='critical' else "normal"],
                timeout=3, capture_output=True
            )
            return True
        except Exception:
            pass
        # fallback: 写console
        print(f"\n{'='*50}")
        print(f"  🚨 桌面通知: {title}")
        print(f"  {msg}")
        print(f"{'='*50}\n")
        return True

    def _notify_webhook(self, alert: Dict) -> bool:
        """Webhook 通知 (POST JSON)"""
        url = self.config["channels"].get("webhook", {}).get("url", "")
        if not url:
            return False
        try:
            import urllib.request
            data = json.dumps(alert).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
            return True
        except Exception:
            return False

    def _notify_email(self, alert: Dict) -> bool:
        """邮件通知 (AgentMail / SMTP / 日志)"""
        email_cfg = self.config["channels"].get("email", {})
        use_agentmail = email_cfg.get("use_agentmail", False)

        # ── AgentMail 通道 ──
        if use_agentmail:
            try:
                to = email_cfg.get("to", "")
                if not to:
                    return False
                # 使用 agentmail_tool 发送（通过 keychain 自动获取 key）
                import sys, subprocess
                tool_path = os.path.join(os.path.dirname(__file__), "agentmail_tool.py")
                subject = f"[GA Alert] {alert['level']}: {alert['description']}"
                body = json.dumps(alert, indent=2, ensure_ascii=False)
                result = subprocess.run(
                    [sys.executable, tool_path, "send", to, subject, body],
                    capture_output=True, text=True, timeout=15
                )
                return result.returncode == 0
            except Exception:
                return False

        # ── SMTP 通道 ──
        smtp = self.config["channels"].get("email", {}).get("smtp_server", "")
        if not smtp:
            # 无配置时写 alert_email.log
            log_line = f"[{alert['timestamp']}] {alert['level']} {alert['metric']}={alert['value']:.1f}%\n"
            with open("temp/alert_email.log", "a") as f:
                f.write(log_line)
            return True
        # 真实邮件发送 (需要 smtplib)
        try:
            import smtplib
            from email.message import EmailMessage
            to = self.config["channels"]["email"].get("to", "")
            if not to:
                return False
            msg = EmailMessage()
            msg.set_content(json.dumps(alert, indent=2, ensure_ascii=False))
            msg["Subject"] = f"[GA Alert] {alert['level']}: {alert['description']}"
            msg["To"] = to
            with smtplib.SMTP(smtp, timeout=10) as s:
                s.send_message(msg)
            return True
        except Exception:
            return False

    def _notify_feishu(self, alert: Dict) -> bool:
        """飞书通知 (使用 feishu_bridge)"""
        feishu_cfg = self.config["channels"].get("feishu", {})
        if not feishu_cfg.get("enabled", False):
            return False
        try:
            from scripts.feishu_bridge import FeishuBridge
            chat_id = feishu_cfg.get("chat_id", "") or None
            bridge = FeishuBridge(chat_id=chat_id)
            emoji = "🚨" if alert["level"] == "critical" else "⚠️"
            message = (
                f"{emoji} *[{alert['level'].upper()}] {alert['description']}*\n"
                f"• 当前值: {alert['value']:.1f}\n"
                f"• 阈值: {alert['threshold']}\n"
                f"• 时间: {alert.get('timestamp', '')}\n"
                f"• 指标: {alert['metric']}"
            )
            # 附加进程快照
            try:
                import subprocess
                ps = subprocess.run(
                    ["ps", "aux", "--sort=-%mem"],
                    capture_output=True, text=True, timeout=5
                )
                if ps.stdout:
                    lines = ps.stdout.strip().split('\n')
                    snapshot = '\n'.join(lines[:11])  # 标题行 + top 10
                    message += f"\n\n📋 进程快照 (Top 10 by MEM):\n```\n{snapshot[:1000]}\n```"
            except Exception:
                pass
            ok = bridge.send_message(message, msg_type="text")
            return ok
        except Exception as e:
            print(f"[AlertManager] feishu 通知失败: {e}")
            return False

    def dispatch_alert(self, alert: Dict) -> bool:
        """通过已启用的通道发送告警通知"""
        sent = False
        channels = self.config.get("channels", {})
        if channels.get("desktop", {}).get("enabled"):
            if self._notify_desktop(alert):
                sent = True
        if channels.get("webhook", {}).get("enabled"):
            if self._notify_webhook(alert):
                sent = True
        if channels.get("email", {}).get("enabled"):
            if self._notify_email(alert):
                sent = True
        if channels.get("feishu", {}).get("enabled"):
            if self._notify_feishu(alert):
                sent = True
        # fallback: 至少日志记录
        if not sent:
            print(f"[ALERT] {alert['level']}: {alert['description']} = {alert['value']:.1f}%")
        self._log_alert(alert)
        return sent

    # ── 检查并告警 ─────────────────────────────────────────────────────

    def check_and_alert(self) -> List[Dict]:
        """检查当前指标，触发需要告警的规则，返回告警列表"""
        metrics = self.get_metrics()
        rules = self.config.get("rules", {})
        triggered = []
        for metric, value in metrics.items():
            alert = self._check_rule(metric, value, rules)
            if alert:
                self.dispatch_alert(alert)
                triggered.append(alert)
        return triggered

    def check_and_dispatch(self, data: Dict) -> List[Dict]:
        """检查外部传入的指标数据，触发告警 (兼容 health_server._collect_data)"""
        rules = self.config.get("rules", {})
        triggered = []
        # 从外部数据提取指标
        metric_map = {
            "cpu_percent": ("cpu_percent", lambda d: float(d.get("cpu_percent", 0))),
            "memory_percent": ("memory_percent", lambda d: float(d.get("mem_percent", 0))),
            "disk_percent": ("disk_percent", lambda d: max((float(x.get("percent", 0)) for x in d.get("disks", []) if x.get("mount") == "/"), default=0)),
            "load_avg": ("load_avg", lambda d: float(d.get("load_avg", [0])[0]) if isinstance(d.get("load_avg"), (list, tuple)) and len(d["load_avg"]) > 0 else 0),
        }
        for metric_key, (rule_key, extractor) in metric_map.items():
            value = extractor(data)
            alert = self._check_rule(rule_key, value, rules)
            if alert:
                self.dispatch_alert(alert)
                triggered.append(alert)
        return triggered

    def trigger(self, metric: str, value: float) -> Optional[Dict]:
        """手动触发指定指标的告警"""
        rules = self.config.get("rules", {})
        rule = rules.get(metric)
        if not rule:
            print(f"❌ 未知指标: {metric}")
            return None
        level = "critical" if value >= rule.get("critical", 999) else \
                "warning" if value >= rule.get("warning", 999) else None
        if not level:
            print(f"ℹ️  {metric}={value:.1f}% 未超过阈值 (警告>{rule.get('warning',0)}%, 严重>{rule.get('critical',0)}%)")
            return None
        alert = {
            "metric": metric,
            "value": value,
            "level": level,
            "threshold": rule.get(level, 0),
            "description": rule.get("description", metric),
            "timestamp": datetime.now().isoformat(),
            "trigger": "manual",
        }
        self.dispatch_alert(alert)
        return alert


# ═══════════════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="🚨 告警管理器")
    parser.add_argument("action", choices=["config", "check", "trigger", "push"],
                        help="操作类型")
    parser.add_argument("--metric", help="指标名 (cpu_percent/memory_percent/disk_percent)")
    parser.add_argument("--value", type=float, help="指标值")
    parser.add_argument("--channel", default="desktop", help="通知通道")
    parser.add_argument("--msg", help="推送消息")
    parser.add_argument("--set", help="配置规则: cpu=90,mem=85,disk=92")
    parser.add_argument("--url", help="Webhook URL")
    parser.add_argument("--to", help="邮件地址")

    args = parser.parse_args()
    mgr = AlertManager()

    if args.action == "config":
        if args.set:
            overrides = {}
            for part in args.set.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    metric_map = {
                        "cpu": "cpu_percent", "mem": "memory_percent", "disk": "disk_percent"
                    }
                    key = metric_map.get(k.strip(), k.strip())
                    vals = {}
                    if ":" in v:
                        w, c = v.split(":")
                        vals["warning"] = float(w)
                        vals["critical"] = float(c)
                    else:
                        vals["critical"] = float(v)
                    overrides[key] = vals
            if overrides:
                mgr.set_rules(overrides)
                print(f"✅ 规则已更新")
        if args.url:
            mgr.set_channel("webhook", {"enabled": True, "url": args.url})
            print(f"✅ Webhook 已配置: {args.url}")
        if args.to:
            mgr.set_channel("email", {"enabled": True, "to": args.to})
            print(f"✅ 邮件通知已配置: {args.to}")
        cfg = mgr.get_config()
        print(json.dumps(cfg, indent=2, ensure_ascii=False))

    elif args.action == "check":
        metrics = mgr.get_metrics()
        print(f"\n📊 当前系统指标:")
        for k, v in metrics.items():
            print(f"  {k:20s} = {v:.1f}%")
        alerts = mgr.check_and_alert()
        if alerts:
            print(f"\n🚨 触发 {len(alerts)} 个告警:")
            for a in alerts:
                print(f"  [{a['level']}] {a['description']}: {a['value']:.1f}%")
        else:
            print(f"\n✅ 一切正常，未触发告警")

    elif args.action == "trigger":
        if not args.metric or args.value is None:
            print("❌ trigger 需要 --metric 和 --value")
            return
        alert = mgr.trigger(args.metric, args.value)
        if alert:
            print(f"✅ 已触发 {alert['level']} 告警: {alert['description']}={alert['value']:.1f}%")

    elif args.action == "push":
        if not args.msg:
            print("❌ push 需要 --msg")
            return
        alert = {
            "metric": "test",
            "value": 0,
            "level": "warning",
            "threshold": 0,
            "description": args.msg,
            "timestamp": datetime.now().isoformat(),
            "trigger": "manual_test",
        }
        mgr.dispatch_alert(alert)
        print(f"✅ 已推送测试通知到 {args.channel} 通道")


if __name__ == "__main__":
    main()
