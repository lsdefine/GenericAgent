#!/usr/bin/env python3
"""
agentmail_local.py — 本地文件消息交换系统

替代 AgentMail API 在 RateLimit 时的 agent 间通信。
所有消息存储在 temp/agentmail_local/ 目录下，通过 JSON 文件交换。

用法:
    from scripts.agentmail_local import LocalMailBox
    mailbox = LocalMailBox("genericagent")
    mailbox.send("其他agent", subject="你好", text="消息内容")
    msgs = mailbox.list_inbox(limit=5)
"""

import os, json, uuid, time, glob, logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

MAIL_DIR = os.path.join(os.path.dirname(__file__), "..", "temp", "agentmail_local")
log = logging.getLogger("agentmail_local")

# 确保目录存在
os.makedirs(os.path.join(MAIL_DIR, "inbox"), exist_ok=True)
os.makedirs(os.path.join(MAIL_DIR, "archive"), exist_ok=True)


class LocalMailBox:
    """本地消息邮箱"""

    def __init__(self, agent_id: str = "genericagent"):
        self.agent_id = agent_id
        self._inbox_path = os.path.join(MAIL_DIR, "inbox")

    def send(self, to: str, subject: str, text: str,
             msg_type: str = "message") -> Dict[str, Any]:
        """发送消息到指定 agent（写入接收者的 inbox 目录）"""
        msg_id = f"{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        msg = {
            "message_id": msg_id,
            "from": self.agent_id,
            "to": [to],
            "subject": subject,
            "text": text,
            "msg_type": msg_type,
            "created_at": now.isoformat(),
            "read": False,
        }

        # 写入接收方的 inbox（支持 "all" 广播）
        if to == "all":
            targets = [d for d in os.listdir(self._inbox_path) if os.path.isdir(os.path.join(self._inbox_path, d))]
        else:
            targets = [to]

        written = []
        for t in targets:
            target_dir = os.path.join(self._inbox_path, t)
            os.makedirs(target_dir, exist_ok=True)
            filepath = os.path.join(target_dir, f"{msg_id}.json")
            with open(filepath, "w") as f:
                json.dump(msg, f, indent=2, ensure_ascii=False)
            written.append(t)

        log.info(f"📬 [{msg_id}] {self.agent_id} → {', '.join(written)}: {subject}")
        return {"ok": True, "message_id": msg_id, "to": written}

    def list_inbox(self, limit: int = 10) -> List[Dict]:
        """列出本 agent 收件箱中的消息"""
        agent_dir = os.path.join(self._inbox_path, self.agent_id)
        if not os.path.isdir(agent_dir):
            return []

        files = sorted(
            glob.glob(os.path.join(agent_dir, "*.json")),
            key=os.path.getmtime, reverse=True
        )

        msgs = []
        for fp in files[:limit]:
            try:
                with open(fp) as f:
                    msg = json.load(f)
                msgs.append({
                    "id": msg.get("message_id"),
                    "from": msg.get("from"),
                    "subject": msg.get("subject"),
                    "preview": (msg.get("text") or "")[:200],
                    "timestamp": msg.get("created_at"),
                    "read": msg.get("read", False),
                    "_file": fp,
                })
            except Exception as e:
                log.warning(f"读取消息 {fp} 失败: {e}")

        return msgs

    def read_message(self, message_id: str) -> Optional[Dict]:
        """读取并标记已读"""
        agent_dir = os.path.join(self._inbox_path, self.agent_id)
        fp = os.path.join(agent_dir, f"{message_id}.json")
        if not os.path.isfile(fp):
            # 可能在 archive 中
            fp = os.path.join(MAIL_DIR, "archive", f"{self.agent_id}_{message_id}.json")
            if not os.path.isfile(fp):
                return None

        with open(fp) as f:
            msg = json.load(f)

        # 标记已读
        if not msg.get("read"):
            msg["read"] = True
            msg["read_at"] = datetime.now(timezone.utc).isoformat()
            with open(fp, "w") as f:
                json.dump(msg, f, indent=2, ensure_ascii=False)

        return msg

    def archive_message(self, message_id: str) -> bool:
        """归档消息（移到 archive 目录）"""
        agent_dir = os.path.join(self._inbox_path, self.agent_id)
        src = os.path.join(agent_dir, f"{message_id}.json")
        if not os.path.isfile(src):
            return False

        dst = os.path.join(MAIL_DIR, "archive", f"{self.agent_id}_{message_id}.json")
        os.rename(src, dst)
        return True

    def delete_message(self, message_id: str) -> bool:
        """删除消息"""
        agent_dir = os.path.join(self._inbox_path, self.agent_id)
        fp = os.path.join(agent_dir, f"{message_id}.json")
        if os.path.isfile(fp):
            os.remove(fp)
            return True
        return False

    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        agent_dir = os.path.join(self._inbox_path, self.agent_id)
        inbox_count = len(glob.glob(os.path.join(agent_dir, "*.json"))) if os.path.isdir(agent_dir) else 0
        archive_count = len(glob.glob(os.path.join(MAIL_DIR, "archive", f"{self.agent_id}_*.json")))
        return {"inbox": inbox_count, "archive": archive_count}

    def health_check(self) -> bool:
        """检查本地邮箱系统是否正常"""
        return os.path.isdir(self._inbox_path) and os.path.isdir(os.path.join(MAIL_DIR, "archive"))


# ─── 便捷函数（兼容 AgentMail 桥接） ──────────────────────────

def send_alert(alert_type: str, message: str, severity: str = "warning",
               to: str = "genericagent") -> Dict[str, Any]:
    """发送告警消息（兼容 AgentMailBridge.send_alert）"""
    mailbox = LocalMailBox()
    subject = f"[GA-{severity.upper()}] {alert_type}"
    text = (
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"⚠️ 类型: {alert_type}\n"
        f"📊 严重度: {severity}\n"
        f"📝 详情: {message}\n"
    )
    return mailbox.send(to, subject, text, msg_type="alert")


def send_report(title: str, body: str, to: str = "genericagent") -> Dict[str, Any]:
    """发送报告（兼容 AgentMailBridge.send_report）"""
    mailbox = LocalMailBox()
    subject = f"[GA-Report] {title}"
    text = f"📋 {title}\n{'=' * 40}\n\n{body}\n\n---\nGA Local Mail | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return mailbox.send(to, subject, text, msg_type="report")


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="本地消息交换系统")
    parser.add_argument("action", choices=["send", "list", "read", "stats", "archive", "delete", "health"])
    parser.add_argument("--to", default="genericagent", help="接收者 agent ID")
    parser.add_argument("--subject", default="(无主题)", help="消息主题")
    parser.add_argument("--body", default="", help="消息正文")
    parser.add_argument("--msg-id", help="消息 ID")
    parser.add_argument("--limit", type=int, default=10, help="列表数量")
    args = parser.parse_args()

    mailbox = LocalMailBox()

    if args.action == "send":
        r = mailbox.send(args.to, args.subject, args.body)
        print(f"✅ Sent: {r}")

    elif args.action == "list":
        msgs = mailbox.list_inbox(limit=args.limit)
        print(f"📨 Inbox ({len(msgs)}):")
        for m in msgs:
            read_icon = "📖" if m["read"] else "📩"
            print(f"  {read_icon} [{m['timestamp'][:19]}] {m['from']} → {m['subject']}")
            print(f"    ├─ id: ...{m['id'][-12:]}")
            print(f"    └─ {m['preview'][:80]}...")

    elif args.action == "read":
        if not args.msg_id:
            print("❌ 需要 --msg-id")
        else:
            msg = mailbox.read_message(args.msg_id)
            if msg:
                print(f"📩 From: {msg.get('from')}")
                print(f"   Subject: {msg.get('subject')}")
                print(f"   Date: {msg.get('created_at')}")
                print(f"   Text:\n{msg.get('text', '')}")
            else:
                print(f"❌ 消息 {args.msg_id} 未找到")

    elif args.action == "stats":
        s = mailbox.get_stats()
        print(f"📊 Inbox: {s['inbox']} | Archive: {s['archive']}")

    elif args.action == "archive":
        if args.msg_id:
            r = mailbox.archive_message(args.msg_id)
            print(f"{'✅' if r else '❌'} Archived: {args.msg_id}")
        else:
            # 归档所有已读消息
            msgs = mailbox.list_inbox(limit=999)
            archived = 0
            for m in msgs:
                if m["read"]:
                    mailbox.archive_message(m["id"])
                    archived += 1
            print(f"📦 归档 {archived} 条已读消息")

    elif args.action == "delete":
        if args.msg_id:
            r = mailbox.delete_message(args.msg_id)
            print(f"{'✅' if r else '❌'} Deleted: {args.msg_id}")

    elif args.action == "health":
        ok = mailbox.health_check()
        print(f"{'✅' if ok else '❌'} Local mail health: {'OK' if ok else 'FAIL'}")
