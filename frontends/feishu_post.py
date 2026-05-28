from __future__ import annotations

import json
import os
import re
from typing import Any


AUTO_POST_MIN_CHARS = int(os.environ.get("GA_FEISHU_POST_MIN_CHARS", "420") or "420")
AUTO_POST_MIN_LINES = int(os.environ.get("GA_FEISHU_POST_MIN_LINES", "7") or "7")
MAX_POST_ROWS = int(os.environ.get("GA_FEISHU_POST_MAX_ROWS", "120") or "120")
MAX_ROW_CHARS = int(os.environ.get("GA_FEISHU_POST_MAX_ROW_CHARS", "1200") or "1200")

_BOLD_RE = re.compile(r"\*\*([^*\n][^*\n]*?)\*\*")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_STRUCTURED_RE = re.compile(
    r"(^|\n)\s*(#{1,6}\s+\S|[-*]\s+\S|\d+[.)]\s+\S|"
    r"正式准入[:：]|跳过[:：]|证据记录[:：]|反馈记录[:：]|说明[:：]|"
    r"Dream\s*认知精炼报告|```|\|.+\|)",
    re.IGNORECASE,
)
_OPERATIONAL_CARD_ENABLED = os.environ.get("GA_FEISHU_OPERATIONAL_CARD", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
_OPERATIONAL_RE = re.compile(
    r"(PID|进程|Gateway|gateway|重启|已启动|已重启|连接已恢复|飞书连接|"
    r"Feishu|Weixin|微信|平台|connected|运行正常|系统运行|状态稳定|"
    r"验证|测试|pytest|passed|score\s*\d+|findings|push\s*成功|"
    r"已同步|origin/main|HEAD|commit|提交|工作区干净|报错|失败)",
    re.IGNORECASE,
)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", str(text or "")).strip()
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def derive_post_title(text: str, fallback: str = "GA 回复") -> str:
    for line in str(text or "").splitlines():
        title = _strip_markdown(line)
        if not title:
            continue
        if len(title) > 80:
            return fallback
        return title
    return fallback


def should_send_post(text: str, *, force: bool = False) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    if force:
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) >= AUTO_POST_MIN_LINES:
        return True
    if _STRUCTURED_RE.search(text):
        return True
    return len(text) >= AUTO_POST_MIN_CHARS and len(lines) >= 3


def should_send_operational_card(text: str) -> bool:
    if not _OPERATIONAL_CARD_ENABLED:
        return False
    text = str(text or "").strip()
    if not text:
        return False
    return bool(_OPERATIONAL_RE.search(text))


def derive_operational_card_title(text: str, fallback: str = "状态汇报") -> str:
    text = str(text or "")
    if re.search(r"重启|已启动|连接已恢复", text, re.IGNORECASE):
        return "重启汇报"
    if re.search(r"验证|测试|pytest|passed|score\s*\d+|findings", text, re.IGNORECASE):
        return "验证结果"
    if re.search(r"push|已同步|origin/main|HEAD|commit|提交|工作区干净", text, re.IGNORECASE):
        return "同步汇报"
    if re.search(r"报错|失败", text, re.IGNORECASE):
        return "异常汇报"
    return fallback


def _text_node(text: str, *, bold: bool = False) -> dict[str, Any]:
    node: dict[str, Any] = {"tag": "text", "text": text}
    if bold:
        node["style"] = ["bold"]
    return node


def _inline_nodes(line: str, *, bold_line: bool = False) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    pos = 0
    for match in _BOLD_RE.finditer(line):
        if match.start() > pos:
            nodes.append(_text_node(line[pos:match.start()], bold=bold_line))
        nodes.append(_text_node(match.group(1), bold=True))
        pos = match.end()
    if pos < len(line):
        nodes.append(_text_node(line[pos:], bold=bold_line))
    return nodes or [_text_node(line or " ")]


def _line_nodes(line: str, *, in_code: bool = False) -> list[dict[str, Any]]:
    line = str(line or "")
    if len(line) > MAX_ROW_CHARS:
        line = line[:MAX_ROW_CHARS].rstrip() + "..."
    if in_code:
        return [_text_node(line or " ")]
    heading = _HEADING_RE.match(line)
    if heading:
        return _inline_nodes(_strip_markdown(heading.group(1)), bold_line=True)
    return _inline_nodes(line)


def _content_rows(text: str) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    in_code = False
    blank_pending = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not line.strip():
            blank_pending = bool(rows)
            continue
        if blank_pending and len(rows) < MAX_POST_ROWS - 1:
            rows.append([_text_node(" ")])
            blank_pending = False
        rows.append(_line_nodes(line, in_code=in_code))
        if len(rows) >= MAX_POST_ROWS:
            rows.append([_text_node("...(内容较长，已截断)")])
            break
    return rows or [[_text_node("(无内容)")]]


def build_post_payload(text: str, *, title: str | None = None) -> str:
    text = str(text or "").strip()
    post_title = title or derive_post_title(text)
    lines = text.splitlines()
    if lines and _strip_markdown(lines[0]) == post_title:
        text = "\n".join(lines[1:]).strip()
    payload = {
        "zh_cn": {
            "title": post_title,
            "content": _content_rows(text),
        }
    }
    return json.dumps(payload, ensure_ascii=False)
