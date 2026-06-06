#!/usr/bin/env python3
"""
agentmail_bridge.py — AgentMail 程序化桥接模块

为 GA 各模块提供干净的 AgentMail API 封装：
  - send_alert()     — 发送告警消息（供 auto_repair 等调用）
  - send_report()    — 发送格式化报告（供 health_server/scheduler 调用）
  - list_inboxes()   — 列出所有 inbox
  - read_messages()  — 读取收件箱消息
  - daily_summary()  — 生成并发送执行摘要

Usage:
    from scripts.agentmail_bridge import AgentMailBridge
    bridge = AgentMailBridge()
    bridge.send_alert("disk_usage", "磁盘使用率 85%")
"""

import os, sys, json, logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agentmail_bridge")

# 本地文件交换 fallback (v110#1)
_HAVE_LOCAL = False
try:
    from scripts.agentmail_local import LocalMailBox, send_alert as local_alert, send_report as local_report
    _HAVE_LOCAL = True
except ImportError:
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from scripts.agentmail_local import LocalMailBox, send_alert as local_alert, send_report as local_report
        _HAVE_LOCAL = True
    except Exception:
        log.debug("agentmail_local 未安装，禁用本地 fallback")


class AgentMailBridge:
    """AgentMail 程序化桥接"""

    DEFAULT_INBOX = "genericagent@agentmail.to"

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        """懒加载 AgentMail client"""
        if self._client is not None:
            return self._client

        api_key = self._api_key
        if not api_key:
            api_key = os.environ.get("AGENTMAIL_API_KEY")
        if not api_key:
            try:
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "memory"))
                from keychain import keys
                if "AGENTMAIL_API_KEY" in keys.ls():
                    api_key = keys.AGENTMAIL_API_KEY.use()
            except Exception as e:
                log.warning(f"keychain access failed: {e}")

        if not api_key:
            raise RuntimeError(
                "AGENTMAIL_API_KEY 未设置。请: export AGENTMAIL_API_KEY=xxx\n"
                "或通过 keychain 存储"
            )

        from agentmail import AgentMail
        self._client = AgentMail(api_key=api_key)
        return self._client

    # ─── 核心功能 ───────────────────────────────────────────────

    def send_alert(self, alert_type: str, message: str, severity: str = "warning",
                    to: Optional[str] = None) -> Dict[str, Any]:
        """发送告警消息（供 auto_repair 调用）. AgentMail 失败时自动 fallback 到本地文件交换"""
        to_addr = to or self.DEFAULT_INBOX
        subject = f"[GA-{severity.upper()}] {alert_type}"
        text = (
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"⚠️ 类型: {alert_type}\n"
            f"📊 严重度: {severity}\n"
            f"📝 详情: {message}\n"
        )

        # Try AgentMail API first
        try:
            client = self._get_client()
            log.info(f"Sending alert via AgentMail: {subject} → {to_addr}")
            resp = client.inboxes.messages.send(
                inbox_id=self.DEFAULT_INBOX,
                to=[to_addr],
                subject=subject,
                text=text,
            )
            return {"ok": True, "message_id": getattr(resp, "message_id", None), "to": to_addr, "via": "agentmail"}
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'RateLimit' in err_str or 'rate' in err_str.lower():
                log.warning(f"⚠️ AgentMail RateLimit, fallback to local: {e}")
                if _HAVE_LOCAL:
                    result = local_alert(alert_type, message, severity, to_addr.replace('@agentmail.to', ''))
                    result["via"] = "local"
                    return result
            log.error(f"❌ AgentMail send failed (no fallback): {e}")
            raise

    def send_report(self, title: str, body: str, to: Optional[str] = None,
                    tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """发送格式化报告. AgentMail 失败时自动 fallback 到本地文件交换"""
        to_addr = to or self.DEFAULT_INBOX
        subject = f"[GA-Report] {title}"
        text = f"📋 {title}\n{'=' * 40}\n\n{body}\n\n---\nGA AgentMail Bridge | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        try:
            client = self._get_client()
            log.info(f"Sending report via AgentMail: {subject} → {to_addr}")
            resp = client.inboxes.messages.send(
                inbox_id=self.DEFAULT_INBOX,
                to=[to_addr],
                subject=subject,
                text=text,
            )
            return {"ok": True, "message_id": getattr(resp, "message_id", None), "to": to_addr, "via": "agentmail"}
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'RateLimit' in err_str or 'rate' in err_str.lower():
                log.warning(f"⚠️ AgentMail RateLimit, fallback to local: {e}")
                if _HAVE_LOCAL:
                    result = local_report(title, body, to_addr.replace('@agentmail.to', ''))
                    result["via"] = "local"
                    return result
            log.error(f"❌ AgentMail send failed (no fallback): {e}")
            raise

    def list_inboxes(self) -> List[Dict[str, str]]:
        """列出所有 inbox"""
        client = self._get_client()
        resp = client.inboxes.list()
        return [
            {"id": ib.inbox_id, "email": ib.email, "name": ib.display_name}
            for ib in resp.inboxes
        ]

    def read_messages(self, inbox_id: Optional[str] = None, limit: int = 5) -> List[Dict]:
        """读取收件箱消息"""
        client = self._get_client()
        if not inbox_id:
            inboxes = self.list_inboxes()
            if not inboxes:
                return []
            inbox_id = inboxes[0]["id"]
        resp = client.inboxes.messages.list(inbox_id=inbox_id, limit=limit)
        messages = []
        for msg in getattr(resp, "messages", []) or []:
            messages.append({
                "id": getattr(msg, "message_id", None),
                "from": getattr(msg, "from", None),
                "subject": getattr(msg, "subject", None),
                "timestamp": str(getattr(msg, "timestamp", "")),
                "body_preview": (getattr(msg, "text", "") or "")[:200],
            })
        return messages

    # ─── 高级功能 ───────────────────────────────────────────────

    def daily_summary(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """生成并发送每日执行摘要"""
        lines = []
        lines.append(f"📅 日期: {datetime.now().strftime('%Y-%m-%d')}")
        lines.append(f"🕐 时间: {datetime.now().strftime('%H:%M:%S')}")
        lines.append("")
        lines.append("📊 系统指标:")
        for k, v in metrics.get("system", {}).items():
            lines.append(f"  {k}: {v}")
        lines.append("")
        lines.append("✅ 调度任务:")
        for t in metrics.get("tasks", []):
            status_icon = "✅" if t.get("status") == "ok" else "❌"
            lines.append(f"  {status_icon} {t.get('name', '?')}: {t.get('result', '?')}")
        lines.append("")
        lines.append("⚠️ 告警:")
        for a in metrics.get("alerts", []):
            lines.append(f"  ⚠️ [{a.get('severity','?')}] {a.get('type','?')}: {a.get('msg','?')}")

        body = "\n".join(lines)
        return self.send_report("每日执行摘要", body)


# ─── CLI 入口 ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AgentMail Bridge CLI")
    parser.add_argument("action", choices=["inboxes", "read", "alert", "report", "summary"])
    parser.add_argument("--to", default=None, help="目标 inbox")
    parser.add_argument("--subject", default=None, help="主题")
    parser.add_argument("--body", default=None, help="内容")
    parser.add_argument("--type", dest="alert_type", default="generic", help="告警类型")
    parser.add_argument("--severity", default="warning", help="告警严重度")
    parser.add_argument("--limit", type=int, default=5, help="消息数量")
    args = parser.parse_args()

    bridge = AgentMailBridge()

    if args.action == "inboxes":
        for ib in bridge.list_inboxes():
            print(f"  📬 {ib['name']} <{ib['email']}>")
    elif args.action == "read":
        msgs = bridge.read_messages(inbox_id=args.to, limit=args.limit)
        for m in msgs:
            print(f"  [{m['timestamp']}] {m['subject']}")
            print(f"    {m['body_preview'][:100]}...")
    elif args.action == "alert":
        r = bridge.send_alert(args.alert_type, args.body or "(no message)", args.severity, args.to)
        print(f"  ✅ Alert sent: {r}")
    elif args.action == "report":
        r = bridge.send_report(args.subject or "Report", args.body or "(empty)", args.to)
        print(f"  ✅ Report sent: {r}")
    elif args.action == "summary":
        import json
        metrics = json.loads(args.body) if args.body else {}
        r = bridge.daily_summary(metrics)
        print(f"  ✅ Summary sent: {r}")
