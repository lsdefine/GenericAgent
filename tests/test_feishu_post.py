import json

from frontends.feishu_post import build_post_payload, derive_post_title, should_send_post


def test_short_casual_reply_stays_text():
    assert not should_send_post("可以")
    assert not should_send_post("收到，我来处理。")


def test_structured_report_uses_post():
    report = "\n".join([
        "Dream 认知精炼报告 | 2026-05-15",
        "",
        "旁路复盘: 1 条",
        "1. [L2] 飞书对话: 当天群聊应进入强记忆。",
        "",
        "证据记录: 8 条",
        "反馈记录: 2 条",
    ])

    assert should_send_post(report)


def test_build_post_payload_preserves_title_and_structure():
    payload = json.loads(build_post_payload("**结论**\n\n- 已接入 Post\n- 短句仍发 text"))

    assert payload["zh_cn"]["title"] == "结论"
    rows = payload["zh_cn"]["content"]
    flat = json.dumps(rows, ensure_ascii=False)
    assert "已接入 Post" in flat
    assert "短句仍发 text" in flat
    assert rows[0][0]["text"].startswith("- 已接入")


def test_derive_post_title_falls_back_for_long_first_line():
    long_line = "这是一段很长很长的普通回复" * 8

    assert derive_post_title(long_line, fallback="GA 结论") == "GA 结论"
