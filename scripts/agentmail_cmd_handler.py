#!/usr/bin/env python3
"""
agentmail_cmd_handler.py — AgentMail 指令处理器

轮询收件箱，解析指令邮件并自动回复。

支持指令:
  /status         — 系统状态概览
  /exec <cmd>     — 执行 shell 命令 (受限)
  /help           — 指令帮助
  /ping           — 连通性测试

Usage:
    python scripts/agentmail_cmd_handler.py          # 单次轮询
    python scripts/agentmail_cmd_handler.py --watch  # 持续监控模式
    python scripts/agentmail_cmd_handler.py --once   # 单次执行, 无输出仅exit code

配置:
    AGENTMAIL_API_KEY 通过 keychain 或环境变量设置
    inbox: genericagent@agentmail.to
"""

import os
import re
import sys
import json
import time
import subprocess
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("agentmail_cmd")

# ─── 配置 ─────────────────────────────────────────────────────
INBOX = "genericagent@agentmail.to"
STATE_FILE = Path(__file__).parent / ".agentmail_cmd_state.json"
ALLOWED_COMMANDS = ["status", "help", "ping", "exec", "benchmark"]


# ─── 工具函数 ─────────────────────────────────────────────────

def _get_client():
    """获取已认证的 AgentMail client"""
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
            "AGENTMAIL_API_KEY 未设置。\n"
            "请: export AGENTMAIL_API_KEY=xxx\n"
            "或通过 keychain 存储"
        )

    from agentmail import AgentMail
    return AgentMail(api_key=api_key)


def _load_state() -> dict:
    """加载已处理消息ID记录"""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"processed_ids": [], "last_check": None}


def _save_state(state: dict):
    """保存已处理消息ID记录"""
    state["last_check"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    log.debug(f"State saved: {len(state['processed_ids'])} processed IDs")


def _execute_command(cmd: str) -> str:
    """执行受限的 shell 命令"""
    # 安全检查: 只允许特定命令
    forbidden = ["rm -rf", "mkfs", "dd if=", "> /dev", ":(){ :|:& };:"]
    for pattern in forbidden:
        if pattern in cmd.lower():
            return f"❌ 命令被拒绝: 包含危险模式 '{pattern}'"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout.strip()
        error = result.stderr.strip()
        ret = result.returncode

        msg_parts = []
        if output:
            # 限制输出长度
            if len(output) > 2000:
                output = output[:2000] + "\n... (truncated)"
            msg_parts.append(f"📤 STDOUT:\n{output}")
        if error:
            if len(error) > 1000:
                error = error[:1000] + "\n... (truncated)"
            msg_parts.append(f"📥 STDERR:\n{error}")

        status = f"✅ Exit: {ret}" if ret == 0 else f"❌ Exit: {ret}"
        msg_parts.insert(0, status)
        return "\n\n".join(msg_parts)

    except subprocess.TimeoutExpired:
        return "❌ 命令执行超时 (30s)"
    except Exception as e:
        return f"❌ 执行失败: {e}"


# ─── 指令处理 ─────────────────────────────────────────────────

def _parse_command(body: str) -> tuple:
    """从邮件正文解析指令, 返回 (cmd, args)"""
    body = body.strip()
    # 支持 /command args 或 /command(args) 格式
    m = re.match(r"^/(\w+)(?:\s+(.+))?$", body, re.DOTALL)
    if m:
        return m.group(1).lower(), (m.group(2) or "").strip()
    return None, None


def _get_system_status() -> str:
    """收集系统状态"""
    lines = []
    lines.append(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"📦 Hostname: {os.uname().nodename}")

    # Disk
    try:
        df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        parts = df.stdout.strip().split("\n")[-1].split()
        lines.append(f"💾 Disk: {parts[2]} / {parts[1]} ({parts[4]} used)")
    except Exception:
        pass

    # Memory
    try:
        mem = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        mem_line = mem.stdout.strip().split("\n")[1].split()
        lines.append(f"🧠 Mem: {mem_line[2]} / {mem_line[1]}")
    except Exception:
        pass

    # Uptime
    try:
        uptime = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
        lines.append(f"⏱ Uptime: {uptime.stdout.strip()}")
    except Exception:
        pass

    # Agent version
    lines.append(f"🤖 GA: v107 (R340)")
    return "\n".join(lines)


def _get_benchmark_summary() -> str:
    """读取 benchmark_trend.json 返回最新benchmark摘要"""
    trend_path = Path(__file__).parent.parent / "temp" / "autonomous_reports" / "benchmark_trend.json"
    if not trend_path.exists():
        return "❌ benchmark 趋势数据不存在（尚未运行过benchmark）"

    try:
        data = json.loads(trend_path.read_text())
        runs = data.get("runs", [])
        if not runs:
            return "❌ benchmark 趋势数据为空"

        last = runs[-1]
        ts = last.get("timestamp", "?")[:19]
        results = last.get("results", {})
        summary = last.get("summary_stats", {})

        lines = [f"📊 **Hermes Benchmark 最新报告**"]
        lines.append(f"⏱ {ts}")
        lines.append(f"📈 总运行次数: {len(runs)}")
        lines.append(f"✅ 最新成功率: {summary.get('overall_success_rate', '?')}%")
        lines.append(f"⚡ 平均响应: {summary.get('avg_response_time', '?')}s")
        lines.append("")

        # Per command
        for cmd, res in sorted(results.items()):
            rate = res.get("success_rate", 0)
            avg = res.get("avg_duration_s", 0)
            icon = "✅" if rate == 100 else ("⚠️" if rate >= 50 else "❌")
            lines.append(f"  {icon} **{cmd}**: {avg:.2f}s ({rate:.0f}%)")

        # Check if there are failed runs
        failed = [r for r in runs if r.get("summary_stats", {}).get("overall_success_rate", 100) < 100]
        if failed:
            lines.append("")
            lines.append(f"⚠️ 历史中有 {len(failed)} 次运行部分失败")
            for r in failed[-3:]:
                lines.append(f"   · {r['timestamp'][:16]}: {r['summary_stats']['overall_success_rate']}%")

        lines.append("")
        lines.append("_(数据由 GA v107 daily cron 自动采集)_")
        return "\n".join(lines)

    except Exception as e:
        log.error(f"Benchmark summary error: {e}")
        return f"❌ 读取 benchmark 数据失败: {e}"


def handle_command(client, inbox_id: str, message_id: str, body: str) -> str:
    """处理单条指令, 返回回复内容"""
    cmd, args = _parse_command(body)

    if not cmd:
        return (
            "🤖 无法识别的指令。支持:\n"
            "  /status    — 系统状态\n"
            "  /exec <s>  — 执行命令\n"
            "  /ping      — 连通测试\n"
            "  /help      — 此帮助"
        )

    log.info(f"Handling command: /{cmd} {args or ''}")

    if cmd == "help" or cmd == "h":
        return (
            "📋 **可用指令:**\n\n"
            "  `/status` — 系统状态概览\n"
            "  `/exec <shell_command>` — 执行 Shell 命令\n"
            "  `/ping` — 连通性测试\n"
            "  `/benchmark` — 查询最新 Hermes Benchmark 报告\n"
            "  `/help` — 显示此帮助\n\n"
            "⚠️ 注意: /exec 有安全限制和30秒超时"
        )

    elif cmd == "ping":
        return f"🏓 Pong! ({datetime.now().strftime('%H:%M:%S')})"

    elif cmd == "status":
        return _get_system_status()

    elif cmd == "exec":
        if not args:
            return "❌ 用法: /exec <command>"
        log.warning(f"Exec command: {args}")
        return _execute_command(args)

    elif cmd == "benchmark" or cmd == "bm":
        return _get_benchmark_summary()

    else:
        return f"❌ 未知指令: /{cmd}。使用 /help 查看可用指令。"


# ─── 主流程 ───────────────────────────────────────────────────

def poll_once() -> int:
    """单次轮询: 读取新消息, 处理指令, 回复"""
    try:
        client = _get_client()
    except RuntimeError as e:
        log.error(str(e))
        return 1
    except ImportError:
        log.error("agentmail SDK not installed. Run: pip install agentmail")
        return 1

    state = _load_state()
    processed = set(state.get("processed_ids", []))

    try:
        resp = client.inboxes.messages.list(inbox_id=INBOX, limit=20)
        # ListMessagesResponse -> .messages is list of MessageItem
        msg_list = resp.messages if hasattr(resp, 'messages') else (resp if isinstance(resp, list) else [])

        if not msg_list:
            log.info("No new messages")
            return 0

        new_count = 0
        for msg in msg_list:
            msg_id = msg.message_id if hasattr(msg, 'message_id') else getattr(msg, 'id', None)
            if not msg_id or msg_id in processed:
                continue

            # Get subject + body (preview may be truncated, use subject)
            subject = msg.subject if hasattr(msg, 'subject') else ''
            # Use preview as body text (it's the plain text snippet)
            body = msg.preview if hasattr(msg, 'preview') else ''
            body_text = f"{subject}\n{body}" if subject else body
            if not body_text.strip():
                continue

            # Check if this looks like a command
            if not body_text.strip().startswith("/"):
                log.debug(f"Skipping non-command message {msg_id}")
                processed.add(msg_id)
                continue

            log.info(f"Processing command message: {msg_id} [{subject}]")
            reply = handle_command(client, INBOX, msg_id, body_text.strip())

            # Send reply
            try:
                client.inboxes.messages.send(
                    inbox_id=INBOX,
                    to=[INBOX],
                    subject=f"Re: {subject[:50]}" if subject else f"Re: command",
                    text=reply,
                )
                log.info(f"✅ Replied to message {msg_id}")
            except Exception as e:
                log.error(f"Failed to send reply: {e}")

            processed.add(msg_id)
            new_count += 1

        # Update state
        state["processed_ids"] = list(processed)
        _save_state(state)
        log.info(f"Processed {new_count} new command(s)")
        return 0

    except Exception as e:
        log.error(f"Poll error: {e}")
        return 1


def watch_mode(interval: int = 60):
    """持续监控模式"""
    log.info(f"Starting watch mode (interval={interval}s)")
    while True:
        try:
            poll_once()
        except KeyboardInterrupt:
            log.info("Watch mode stopped by user")
            break
        except Exception as e:
            log.error(f"Watch error: {e}")
        time.sleep(interval)


def main():
    if "--watch" in sys.argv:
        watch_mode()
    elif "--once" in sys.argv:
        return poll_once()
    else:
        return poll_once()


if __name__ == "__main__":
    sys.exit(main())
