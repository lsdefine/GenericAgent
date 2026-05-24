import json

from frontends.feishu_cards import build_final_card
from frontends.feishu_task_stream import (
    FeishuTaskStream,
    build_step_detail,
    humanize_step_summary,
    natural_group_final,
    should_send_plain_final,
)


class _Resp:
    thinking = "private chain of thought"
    content = "visible output"


def _display_text(text):
    return text or "..."


def _payload_text(payload):
    data = json.loads(payload)
    parts = []

    post = data.get("zh_cn")
    if isinstance(post, dict):
        title = post.get("title")
        if isinstance(title, str):
            parts.append(title)
        for row in post.get("content", []) or []:
            for node in row or []:
                if isinstance(node, dict) and isinstance(node.get("text"), str):
                    parts.append(node["text"])
        return "\n".join(part for part in parts if part)

    def walk(element):
        if not isinstance(element, dict):
            return
        header = element.get("header", {})
        if isinstance(header, dict):
            title = header.get("title", {})
            if isinstance(title, dict):
                parts.append(title.get("content", ""))
        for key in ("content", "text"):
            value = element.get(key)
            if isinstance(value, str):
                parts.append(value)
        for child in element.get("elements", []) or []:
            walk(child)

    header = data.get("header", {})
    title = header.get("title", {}) if isinstance(header, dict) else {}
    if isinstance(title, dict):
        parts.append(title.get("content", ""))
    for element in data.get("body", {}).get("elements", []):
        walk(element)
    return "\n".join(part for part in parts if part)


def test_step_detail_hides_raw_thinking_by_default():
    detail = build_step_detail(
        _Resp(),
        [{"tool_name": "file_read", "args": {"path": "/tmp/a.txt"}}],
        _display_text,
    )

    assert "private chain of thought" not in detail
    assert "### 小结" in detail
    assert "本轮完成：读取 `a.txt`" in detail
    assert "执行动作" in detail
    assert "读取 `a.txt`" in detail
    assert "visible output" in detail
    assert "{\"path\"" not in detail


def test_step_detail_places_summary_after_turn_outputs():
    detail = build_step_detail(
        _Resp(),
        [{"tool_name": "file_read", "args": {"path": "/tmp/a.txt"}}],
        _display_text,
        tool_results=[{"status": "success", "output": "已读取 a.txt"}],
    )

    assert detail.index("### 执行动作") < detail.index("### 产物/证据")
    assert detail.index("### 产物/证据") < detail.index("### 可见输出")
    assert detail.index("### 可见输出") < detail.index("### 小结")


def test_step_detail_summarizes_tool_results_without_raw_trace():
    detail = build_step_detail(
        _Resp(),
        [{"tool_name": "file_patch", "args": {"path": "/tmp/USER.md", "old_content": "x" * 1200}}],
        _display_text,
        tool_results=[{"status": "success", "output": "patched /tmp/USER.md\n当前持仓已写入本地记忆"}],
    )

    assert "更新 `USER.md`" in detail
    assert "当前结果" in detail
    assert "产物/证据" in detail
    assert "当前持仓已写入本地记忆" in detail
    assert "old_content" not in detail


def test_step_detail_surfaces_error_outputs():
    detail = build_step_detail(
        _Resp(),
        [{"tool_name": "code_run", "args": {"script": "python scanner.py"}}],
        _display_text,
        tool_results=[{"status": "error", "error": "KeyError: slice(None, 800, None)"}],
    )

    assert "产物/证据" in detail
    assert "KeyError" in detail
    assert "调用" not in detail


def test_humanize_raw_tool_summary():
    summary = "调用工具file_read, args: {'path': '/Users/me/memory/USER.md'}"

    assert humanize_step_summary(summary) == "读取 `USER.md`"


def test_task_stream_patches_one_workspace_card_for_progress_and_final():
    sent = []
    patched = []

    def send_raw(receive_id, payload, msg_type, rid_type):
        sent.append((receive_id, payload, msg_type, rid_type))
        return f"msg-{len(sent)}"

    def patch_card(message_id, payload):
        patched.append((message_id, payload))
        return True

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=send_raw,
        patch_card=patch_card,
        display_text=_display_text,
    )

    stream.start()
    stream.step("读取配置", "### Tool Calls\n- `file_read`({})")
    stream.step("运行验证", "### Tool Calls\n- `code_run`({})")
    stream.done("最终结论")

    assert len(sent) == 1
    assert "任务工作台" in _payload_text(sent[0][1])
    assert "第 1 轮 · 读取配置" in _payload_text(patched[0][1])
    assert "第 2 轮 · 运行验证" in _payload_text(patched[1][1])
    assert "已完成" in _payload_text(patched[-1][1])
    assert "最终输出" in _payload_text(patched[-1][1])
    assert "最终结论" in _payload_text(patched[-1][1])
    assert patched


def test_workspace_card_keeps_only_recent_steps():
    sent = []
    patched = []

    def send_raw(receive_id, payload, msg_type, rid_type):
        sent.append(payload)
        return "status-msg"

    def patch_card(message_id, payload):
        patched.append(payload)
        return True

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=send_raw,
        patch_card=patch_card,
        display_text=_display_text,
        workspace_max_steps=2,
    )
    stream.start()
    for idx in range(5):
        stream.step(f"步骤 {idx}", "detail")

    latest_status = _payload_text(patched[-1])
    assert "步骤 0" not in latest_status
    assert "步骤 1" not in latest_status
    assert "步骤 3" in latest_status
    assert "步骤 4" in latest_status


def test_workspace_structured_final_is_sent_as_post_not_embedded_in_card():
    sent = []
    patched = []

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda receive_id, payload, msg_type, rid_type: sent.append((payload, msg_type)) or f"msg-{len(sent)}",
        patch_card=lambda message_id, payload: patched.append(payload) or True,
        display_text=_display_text,
    )

    stream.start()
    stream.step("修改发送通道", "detail")
    stream.done("改造已完成，汇报结果：\n\n**做了什么：**\n1. 改为 post\n2. 重启验证")

    assert sent[0][1] == "interactive"
    assert sent[-1][1] == "post"
    assert "**做了什么：**" not in _payload_text(patched[-1])
    assert "结论已通过富文本消息发送" in _payload_text(patched[-1])
    assert "做了什么：" in _payload_text(sent[-1][0])
    assert "改为 post" in _payload_text(sent[-1][0])


def test_task_stream_can_skip_initial_status_until_second_step():
    sent = []
    patched = []

    def send_raw(receive_id, payload, msg_type, rid_type):
        sent.append((receive_id, payload, msg_type, rid_type))
        return f"msg-{len(sent)}"

    def patch_card(message_id, payload):
        patched.append((message_id, payload))
        return True

    stream = FeishuTaskStream(
        "open-1",
        "open_id",
        send_raw=send_raw,
        patch_card=patch_card,
        display_text=_display_text,
        send_initial_status=False,
    )

    stream.start()
    assert sent == []
    stream.step("读取配置", "detail")
    assert sent == []
    stream.step("运行验证", "detail")
    assert len(sent) == 1
    assert "第 1 轮 · 读取配置" in _payload_text(sent[0][1])
    assert "第 2 轮 · 运行验证" in _payload_text(sent[0][1])


def test_quiet_task_stream_sends_only_final_conclusion():
    sent = []
    patched = []

    def send_raw(receive_id, payload, msg_type, rid_type):
        sent.append((receive_id, payload, msg_type, rid_type))
        return f"msg-{len(sent)}"

    def patch_card(message_id, payload):
        patched.append((message_id, payload))
        return True

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=send_raw,
        patch_card=patch_card,
        display_text=_display_text,
        quiet=True,
    )

    stream.start()
    stream.pulse("working")
    stream.step("读取配置", "### Tool Calls\n- `file_read`({})")
    stream.done("最终结论")

    assert len(sent) == 1
    assert "Turn" not in _payload_text(sent[0][1])
    assert "读取配置" not in _payload_text(sent[0][1])
    assert "思考流" not in _payload_text(sent[0][1])
    assert "Tool Calls" not in _payload_text(sent[0][1])
    assert "最终结论" in _payload_text(sent[0][1])
    assert not patched


def test_group_compact_replies_with_progress_and_plain_final():
    sent = []
    replies = []
    patched = []

    def send_raw(receive_id, payload, msg_type, rid_type):
        sent.append((receive_id, payload, msg_type, rid_type))
        return f"msg-{len(sent)}"

    def send_reply(message_id, payload, msg_type):
        replies.append((message_id, payload, msg_type))
        return f"reply-{len(replies)}"

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=send_raw,
        patch_card=lambda message_id, payload: patched.append((message_id, payload)) or True,
        display_text=_display_text,
        group_compact=True,
        group_progress_after_sec=0,
        reply_to="om_123",
        send_reply=send_reply,
    )

    stream.start()
    stream.step("查 cron 配置", "### Tool Calls\n- `file_read`({})")
    stream.done("**结论**\n\n收到，DAG 报告不会再发群里。")

    assert sent == []
    assert replies[0][0] == "om_123"
    assert replies[0][2] == "interactive"
    assert "第 1 轮 · 查 cron 配置" in _payload_text(replies[0][1])
    assert "收到，DAG 报告不会再发群里。" in _payload_text(patched[-1][1])
    assert replies[-1][2] == "text"
    assert json.loads(replies[-1][1])["text"] == "收到，DAG 报告不会再发群里。"


def test_terminal_workspace_ignores_late_pulse_after_done():
    sent = []
    patched = []

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda receive_id, payload, msg_type, rid_type: sent.append(payload) or "msg",
        patch_card=lambda message_id, payload: patched.append(payload) or True,
        display_text=_display_text,
        group_compact=True,
        workspace_progress_after_sec=0,
    )

    stream.step("读取配置", "detail")
    stream.done("最终结论")
    final_patch_count = len(patched)
    stream.pulse("⏳ 工作中 · 999s")
    stream.step("迟到进展", "detail")

    assert len(patched) == final_patch_count
    assert "✅ 已完成" in _payload_text(patched[-1])
    assert "999s" not in _payload_text(patched[-1])


def test_group_compact_replies_structured_final_as_post():
    replies = []

    def send_reply(message_id, payload, msg_type):
        replies.append((message_id, payload, msg_type))
        return f"reply-{len(replies)}"

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda *args: "raw",
        patch_card=lambda *_: True,
        display_text=_display_text,
        group_compact=True,
        reply_to="om_123",
        send_reply=send_reply,
    )

    stream.done(
        "\n".join([
            "**结论**",
            "",
            "已完成清理:",
            "1. 保留短句普通回复",
            "2. 长报告自动改成卡片",
            "3. Dream 报告默认走卡片",
        ])
    )

    assert replies[0][2] == "post"
    payload = json.loads(replies[0][1])
    assert payload["zh_cn"]["title"] == "已完成清理:"
    flat = json.dumps(payload["zh_cn"]["content"], ensure_ascii=False)
    assert "长报告自动改成卡片" in flat


def test_group_compact_replies_operational_status_as_post():
    replies = []

    def send_reply(message_id, payload, msg_type):
        replies.append((message_id, payload, msg_type))
        return f"reply-{len(replies)}"

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda *args: "raw",
        patch_card=lambda *_: True,
        display_text=_display_text,
        group_compact=True,
        reply_to="om_123",
        send_reply=send_reply,
    )

    stream.done("状态稳定。Feishu 和 Weixin 在线，PID 97981。")

    assert replies[0][2] == "post"
    payload = json.loads(replies[0][1])
    assert payload["zh_cn"]["title"] == "状态汇报"
    assert "PID 97981" in _payload_text(replies[0][1])


def test_group_compact_keeps_casual_short_reply_as_text():
    replies = []

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda *args: "raw",
        patch_card=lambda *_: True,
        display_text=_display_text,
        group_compact=True,
        reply_to="om_123",
        send_reply=lambda message_id, payload, msg_type: replies.append((message_id, payload, msg_type)) or "reply",
    )

    stream.done("我在，直接说。")

    assert replies[0][2] == "text"
    assert json.loads(replies[0][1])["text"] == "我在，直接说。"


def test_private_casual_reply_stays_text_not_card():
    sent = []

    stream = FeishuTaskStream(
        "open-1",
        "open_id",
        send_raw=lambda receive_id, payload, msg_type, rid_type: sent.append((payload, msg_type)) or "msg",
        patch_card=lambda *_: True,
        display_text=_display_text,
    )

    stream.done("0.7 是个好数值，保持这个值挺好。")

    assert sent[0][1] == "text"
    assert json.loads(sent[0][0])["text"] == "0.7 是个好数值，保持这个值挺好。"


def test_structured_private_reply_uses_post():
    sent = []

    stream = FeishuTaskStream(
        "open-1",
        "open_id",
        send_raw=lambda receive_id, payload, msg_type, rid_type: sent.append((payload, msg_type)) or "msg",
        patch_card=lambda *_: True,
        display_text=_display_text,
    )

    stream.done("结论：已修复。\n\n1. 更新输出流\n2. 重启验证")

    assert sent[0][1] == "post"
    assert "更新输出流" in _payload_text(sent[0][0])


def test_plain_final_classifier_keeps_reports_as_cards():
    assert should_send_plain_final("我在，直接说。")
    assert not should_send_plain_final("结论：已处理")
    assert not should_send_plain_final("1. 先查日志\n2. 再重启")


def test_final_card_surfaces_task_titles_from_output():
    payload = build_final_card(
        "\n".join([
            "🎉 任务 1 & 2 全部完成!",
            "",
            "✅ 任务 1：盘中监控预警脚本",
            "已创建。",
            "",
            "✅ 任务 2：K 线图可视化",
            "已生成。",
        ]),
        title="已完成",
    )

    text = _payload_text(payload)
    assert "完成清单" in text
    assert "任务 1：盘中监控预警脚本" in text
    assert "任务 2：K 线图可视化" in text


def test_workspace_card_surfaces_task_plan_from_steps_and_outputs():
    sent = []
    patched = []

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda receive_id, payload, msg_type, rid_type: sent.append(payload) or "msg",
        patch_card=lambda message_id, payload: patched.append(payload) or True,
        display_text=_display_text,
    )

    stream.step(
        "生成盘中监控预警脚本",
        build_step_detail(
            _Resp(),
            [{"tool_name": "file_write", "args": {"path": "/tmp/scanner_ma5_monitor.py"}}],
            _display_text,
            tool_results=[{"status": "success", "output": "已写入 scanner_ma5_monitor.py"}],
        ),
    )
    stream.step(
        "绘制 K 线图",
        build_step_detail(
            _Resp(),
            [{"tool_name": "code_run", "args": {"script": "python draw_kline.py"}}],
            _display_text,
            tool_results=[{"status": "success", "output": "已生成 kline_001259.png"}],
        ),
    )
    stream.done("任务 1：盘中监控预警脚本\n任务 2：K 线图可视化\n\n全部完成。")

    text = _payload_text(patched[-1])
    assert "完成清单" in text
    assert "任务 1：盘中监控预警脚本" in text
    assert "任务 2：K 线图可视化" in text
    assert "执行动作" in text
    assert "产物/证据" in text
    assert "scanner_ma5_monitor.py" in text


def test_natural_group_final_strips_machine_heading():
    assert natural_group_final("**结论**\n\n搞定了") == "搞定了"
    assert natural_group_final("✅ 最终结论：已处理") == "已处理"


def test_group_compact_delays_workspace_until_second_step():
    replies = []

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda *args: "raw",
        patch_card=lambda *_: True,
        display_text=_display_text,
        group_compact=True,
        reply_to="om_123",
        send_reply=lambda message_id, payload, msg_type: replies.append((message_id, payload, msg_type)) or "reply",
    )

    stream.step("刚开始处理", "detail")
    assert replies == []
    stream.step("继续验证", "detail")

    assert replies
    assert "第 1 轮 · 刚开始处理" in _payload_text(replies[0][1])
    assert "第 2 轮 · 继续验证" in _payload_text(replies[0][1])


def test_group_compact_cancel_sends_plain_stop_message():
    replies = []

    stream = FeishuTaskStream(
        "chat-1",
        "chat_id",
        send_raw=lambda *args: "raw",
        patch_card=lambda *_: True,
        display_text=_display_text,
        group_compact=True,
        reply_to="om_123",
        send_reply=lambda message_id, payload, msg_type: replies.append((message_id, payload, msg_type)) or "reply",
    )

    stream.cancel("已停止当前任务")

    assert replies == [("om_123", json.dumps({"text": "已停止当前任务"}, ensure_ascii=False), "text")]
