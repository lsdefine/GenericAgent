#!/usr/bin/env python3
"""
check_agentmail.py — AgentMail 每日摘要检查脚本

用途:
  读取 AgentMail 收件箱中的未读/新消息，生成本地摘要报告。
  供 scheduler 每日调用（sche_tasks/agentmail_daily_summary.json）

输出:
  写入 /home/admin/GenericAgent/temp/agentmail_daily_summary_{YYYY-MM-DD}.md

失败时:
  日志记录错误，供上层（飞书通知等）捕获

依赖:
  agentmail_bridge.py（scripts/）
  agentmail SDK
"""

import os, sys, json, logging
from datetime import datetime

# 路径设置
GA_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_DIR = os.path.join(GA_ROOT, "temp")
sys.path.insert(0, GA_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(TEMP_DIR, "agentmail_daily_check.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("check_agentmail")


def main():
    log.info("=== AgentMail 每日摘要检查 ===")

    # 1. 初始化 bridge
    try:
        from scripts.agentmail_bridge import AgentMailBridge
        bridge = AgentMailBridge()
    except Exception as e:
        log.error(f"AgentMailBridge 初始化失败: {e}")
        return False

    # 2. 读取消息
    try:
        messages = bridge.read_messages(limit=20)
        log.info(f"读取到 {len(messages)} 条消息")
    except Exception as e:
        log.error(f"读取消息失败: {e}")
        # 尝试发送飞书告警（可选）
        return False

    # 3. 生成本地摘要
    today = datetime.now().strftime("%Y-%m-%d")
    summary_path = os.path.join(TEMP_DIR, f"agentmail_daily_summary_{today}.md")

    lines = []
    lines.append(f"# AgentMail 每日摘要 — {today}")
    lines.append(f"")
    lines.append(f"**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**消息总数**: {len(messages)}")
    lines.append(f"")

    if not messages:
        lines.append("📭 收件箱为空，无新消息。")
    else:
        lines.append("## 📬 最新消息")
        lines.append(f"")
        for i, msg in enumerate(messages, 1):
            subject = msg.get("subject", "(无主题)")
            from_addr = msg.get("from", "(未知发件人)")
            timestamp = msg.get("timestamp", "")
            preview = msg.get("body_preview", "")[:120]
            lines.append(f"### {i}. {subject}")
            lines.append(f"- **发件人**: {from_addr}")
            lines.append(f"- **时间**: {timestamp}")
            lines.append(f"- **预览**: {preview}...")
            lines.append(f"")

    lines.append("---")
    lines.append("_由 check_agentmail.py 自动生成_")

    summary_text = "\n".join(lines)

    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary_text)
        log.info(f"摘要已写入: {summary_path}")
    except Exception as e:
        log.error(f"写入摘要失败: {e}")
        return False

    # 4. 打印摘要供 scheduler 日志捕获
    print(f"\n{'='*60}")
    print(f"AgentMail 每日摘要 — {today}")
    print(f"{'='*60}")
    print(f"消息总数: {len(messages)}")
    if messages:
        for msg in messages[:5]:
            print(f"  📧 [{msg.get('timestamp','')}] {msg.get('subject','(无主题)')}")
    print(f"摘要文件: {summary_path}")
    print(f"{'='*60}\n")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
