#!/usr/bin/env python3
"""
AgentMail Tool — 封装收/发/列/格式化的便捷工具
Usage:
    python -m scripts.agentmail_tool send TO "subject" "body"
    python -m scripts.agentmail_tool list [--limit 5]
    python -m scripts.agentmail_tool inboxes
    python -m scripts.agentmail_tool read MESSAGE_ID
    python -m scripts.agentmail_tool threads [--limit 5]
"""

import os, sys, json, argparse, textwrap
from datetime import datetime

def _get_client():
    """获取 AgentMail client，优先从 keychain 获取 key，再 fallback 到 env"""
    api_key = os.environ.get('AGENTMAIL_API_KEY')
    if not api_key:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'memory'))
            from keychain import keys
            if 'AGENTMAIL_API_KEY' in keys.ls():
                api_key = keys.AGENTMAIL_API_KEY.use()
        except Exception:
            pass
    if not api_key:
        raise RuntimeError(
            "AGENTMAIL_API_KEY 未设置。请: export AGENTMAIL_API_KEY=xxx\n"
            "或通过 keychain 存储: python -c 'from keychain import keys; keys.set(\"AGENTMAIL_API_KEY\", \"your_key\")'"
        )
    from agentmail import AgentMail
    return AgentMail(api_key=api_key)


def cmd_inboxes(args):
    """列出所有 inbox"""
    client = _get_client()
    resp = client.inboxes.list()
    print(f"📬 Inboxes ({len(resp.inboxes)}):")
    for ib in resp.inboxes:
        print(f"  📧 {ib.email}")
        print(f"     ├─ display_name: {ib.display_name}")
        print(f"     ├─ inbox_id: {ib.inbox_id}")
        print(f"     └─ org_id: {ib.organization_id}")


def cmd_list(args):
    """列出 inbox 中的消息"""
    client = _get_client()
    inbox_id = args.inbox or 'genericagent@agentmail.to'
    resp = client.inboxes.messages.list(inbox_id=inbox_id, limit=args.limit)
    msgs = getattr(resp, 'messages', [])
    print(f"📨 Messages in {inbox_id} ({len(msgs)} shown / total={getattr(resp, 'total', '?')}):")
    for m in msgs:
        ts = m.created_at.strftime('%Y-%m-%d %H:%M') if hasattr(m, 'created_at') and m.created_at else '?'
        suj = (m.subject or '(no subject)')[:60]
        frm = m.from_ or '?'
        mid = m.message_id.split('@')[0][-20:] if m.message_id else '?'
        print(f"  [{ts}] {frm}")
        print(f"     ├─ {suj}")
        print(f"     └─ id: ...{mid}")


def cmd_read(args):
    """读取单条消息内容"""
    client = _get_client()
    inbox_id = args.inbox or 'genericagent@agentmail.to'
    try:
        msg = client.inboxes.messages.get(inbox_id=inbox_id, message_id=args.message_id)
    except Exception as e:
        # 也许只传了短ID？尝试搜索
        print(f"直接读取失败: {e}")
        return

    print(f"📩 Message: {msg.message_id}")
    print(f"  From:    {msg.from_}")
    print(f"  To:      {msg.to}")
    print(f"  Subject: {msg.subject}")
    print(f"  Date:    {msg.created_at}")
    print(f"  Text:\n{textwrap.indent(msg.text or '(empty)', '    ')}")
    print(f"  HTML:    {'yes' if msg.html else 'no'}")
    if msg.attachments:
        print(f"  Attachments: {len(msg.attachments)}")
        for a in msg.attachments:
            print(f"    - {a.filename} ({a.content_type}, {a.size}B)")


def cmd_send(args):
    """发送邮件"""
    client = _get_client()
    inbox_id = args.inbox or 'genericagent@agentmail.to'
    body = args.body or '(empty)'
    is_html = args.html

    resp = client.inboxes.messages.send(
        inbox_id=inbox_id,
        to=args.to,
        subject=args.subject,
        text=body if not is_html else None,
        html=body if is_html else None,
    )
    print(f"✅ Sent!")
    print(f"  message_id: {resp.message_id}")
    print(f"  thread_id:  {resp.thread_id}")


def cmd_threads(args):
    """列出线程"""
    client = _get_client()
    inbox_id = args.inbox or 'genericagent@agentmail.to'
    resp = client.inboxes.threads.list(inbox_id=inbox_id, limit=args.limit)
    threads = getattr(resp, 'threads', [])
    print(f"🧵 Threads in {inbox_id} ({len(threads)}):")
    for t in threads:
        subj = t.subject or '(no subject)'
        cnt = t.message_count if hasattr(t, 'message_count') else '?'
        preview = (t.preview or '')[:60]
        print(f"  📎 [{subj}] ({cnt} msgs)")
        print(f"     └─ {preview}")


def cmd_format(args):
    """将消息格式化为结构化文本"""
    client = _get_client()
    inbox_id = args.inbox or 'genericagent@agentmail.to'
    resp = client.inboxes.messages.list(inbox_id=inbox_id, limit=args.limit)
    msgs = getattr(resp, 'messages', [])
    output = []
    for m in msgs:
        output.append({
            'id': m.message_id,
            'from': m.from_,
            'to': m.to,
            'subject': m.subject,
            'timestamp': str(m.created_at) if hasattr(m, 'created_at') and m.created_at else None,
            'preview': m.preview[:100] if m.preview else None,
            'has_attachments': bool(m.attachments) if hasattr(m, 'attachments') else False,
        })
    print(json.dumps(output, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description='AgentMail 工具')
    parser.add_argument('--inbox', '-i', default=None, help='Inbox email (default: genericagent@agentmail.to)')
    sub = parser.add_subparsers(dest='command', required=True)

    # inboxes
    p_ib = sub.add_parser('inboxes', help='列出所有 inbox')
    p_ib.set_defaults(func=cmd_inboxes)

    # list
    p_list = sub.add_parser('list', help='列出消息')
    p_list.add_argument('--limit', type=int, default=10)
    p_list.set_defaults(func=cmd_list)

    # read
    p_read = sub.add_parser('read', help='读取消息')
    p_read.add_argument('message_id', help='消息 ID')
    p_read.set_defaults(func=cmd_read)

    # send
    p_send = sub.add_parser('send', help='发送邮件')
    p_send.add_argument('to', help='收件人')
    p_send.add_argument('subject', help='主题')
    p_send.add_argument('body', nargs='?', default='', help='正文')
    p_send.add_argument('--html', action='store_true', help='正文是 HTML')
    p_send.set_defaults(func=cmd_send)

    # threads
    p_threads = sub.add_parser('threads', help='列出线程')
    p_threads.add_argument('--limit', type=int, default=10)
    p_threads.set_defaults(func=cmd_threads)

    # format
    p_fmt = sub.add_parser('format', help='JSON 格式化输出消息')
    p_fmt.add_argument('--limit', type=int, default=10)
    p_fmt.set_defaults(func=cmd_format)

    # 特殊处理 subcommands 不需要 inbox 参数
    args = parser.parse_args()
    if args.command in ('inboxes',):
        getattr(args, 'func', lambda a: None)(args)
    else:
        args.func(args)


if __name__ == '__main__':
    main()
