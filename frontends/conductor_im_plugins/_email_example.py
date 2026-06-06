"""邮件：存在未读邮件 → 有新东西。"""

INTERVAL = 7200

PROMPT = """\
你是邮件采集subagent。先读记忆中用户画像，再用 ezgmail 检查未读邮件，过滤后汇报值得关注项并补全上下文（发件人身份/线程/附件摘要）。
过滤营销和自动通知，不确定的标"低优先级观察"。不回复不执行外部动作；无值得关注的就一句话说明。"""


def check() -> bool:
    try:
        import ezgmail
        return bool(ezgmail.unread())
    except Exception:
        return False
