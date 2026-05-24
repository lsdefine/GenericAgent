"""飞书交互卡片的展示层工具。

这里故意只处理呈现，不改变 agent 的决策流程。目标是让长任务更好读。
"""

from __future__ import annotations

import json
import os
import re
from typing import Iterable

CARD_OUTPUT_ENABLED = os.environ.get("GA_FEISHU_CARD_OUTPUT", "1").lower() not in {"0", "false", "no", "off"}
MAX_MARKDOWN_BLOCK_CHARS = int(os.environ.get("GA_FEISHU_CARD_BLOCK_CHARS", "5200") or "5200")
MAX_WORKSPACE_DETAIL_CHARS = int(os.environ.get("GA_FEISHU_WORKSPACE_DETAIL_CHARS", "5200") or "5200")


def markdown(content: str) -> dict[str, str]:
    return {"tag": "markdown", "content": str(content or "")}


def hr() -> dict[str, str]:
    return {"tag": "hr"}


def collapsible_panel(title: str, content: str, *, expanded: bool = False) -> dict:
    title = _clean_summary(title, limit=120)
    content = str(content or "_(无输出)_").strip() or "_(无输出)_"
    if len(content) > MAX_WORKSPACE_DETAIL_CHARS:
        content = content[:MAX_WORKSPACE_DETAIL_CHARS].rstrip() + f"\n\n...(已截断, 共 {len(content)} 字符)"
    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "header": {"title": {"tag": "plain_text", "content": title}},
        "elements": [markdown(content)],
    }


def card_raw(elements: list[dict], *, title: str = "", template: str = "blue") -> str:
    card: dict = {
        "schema": "2.0",
        "config": {"streaming_mode": False, "width_mode": "fill"},
        "body": {"elements": elements},
    }
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if title:
        card["header"] = {
            "template": template,
            "title": {"tag": "plain_text", "content": title[:80]},
        }
    return json.dumps(card, ensure_ascii=False)


def split_markdown_blocks(text: str, *, limit: int = MAX_MARKDOWN_BLOCK_CHARS) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return ["_(无文本输出)_"]
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _clean_summary(summary: str, *, limit: int = 90) -> str:
    summary = re.sub(r"\s+", " ", str(summary or "")).strip()
    if len(summary) > limit:
        return summary[: limit - 3] + "..."
    return summary or "继续处理"


def _extract_task_titles(text: str, *, limit: int = 6) -> list[str]:
    titles: list[str] = []
    patterns = [
        re.compile(r"^\s*(?:#{1,4}\s*)?(?:[🚀✅🎉📌💡🛠️📄📁📊]\s*)?(任务\s*\d+\s*[:：].+?)\s*$", re.I),
        re.compile(r"^\s*(?:#{1,4}\s*)?(Task\s*\d+\s*[:：].+?)\s*$", re.I),
        re.compile(r"^\s*(\d+)[.、]\s+(?:\*\*)?([^：:\n]{4,80}?)(?:\*\*)?\s*[:：]\s*(.+?)\s*$", re.I),
    ]
    for line in str(text or "").splitlines():
        stripped = line.strip().strip("*")
        for pattern in patterns:
            match = pattern.match(stripped)
            if match:
                if len(match.groups()) >= 3 and match.group(1).isdigit():
                    title = f"任务 {match.group(1)}：{match.group(2).strip()}：{match.group(3).strip()}"
                else:
                    title = re.sub(r"\s+", " ", match.group(1)).strip()
                if title and title not in titles:
                    titles.append(title)
                break
        if len(titles) >= limit:
            break
    return titles


def _task_title_from_summary(idx: int, summary: str) -> str:
    summary = _clean_summary(summary, limit=70)
    summary = re.sub(r"^任务\s*\d+\s*[:：]\s*", "", summary)
    summary = re.sub(r"^Turn\s*\d+\s*[:：·-]\s*", "", summary, flags=re.I)
    return f"任务 {idx}：{summary}"


def _workflow_markdown(step_summaries: Iterable[tuple[int, str]] | None, final_text: str) -> str:
    lines: list[str] = []
    task_titles = _extract_task_titles(final_text)
    if task_titles:
        lines.append("### 完成清单")
        lines.extend(f"{idx}. {title}" for idx, title in enumerate(task_titles, 1))
    elif step_summaries:
        lines.append("### 最近进展")
        for order, (_turn, summary) in enumerate(list(step_summaries)[-6:], 1):
            lines.append(f"{order}. {_task_title_from_summary(order, summary)}")
    return "\n".join(lines).strip()


def _has_output_heading(text: str) -> bool:
    return bool(re.search(r"(?mi)^\s*#{1,6}\s*(?:Outputs?|结论|最终结论|已完成)\s*[:：]?\s*$", str(text or "")))


def build_status_card(status: str, *, elapsed: int = 0, turn_count: int = 0, step_summaries=None) -> str:
    lines = [f"**{status or '工作中'}**", f"耗时: {elapsed}s"]
    if turn_count:
        lines.append(f"轮次: {turn_count}")
    if step_summaries:
        lines.append("")
        lines.append("最近进展:")
        for idx, summary in list(step_summaries):
            lines.append(f"- 第 {idx} 轮：{_clean_summary(summary)}")
    template = "green" if "完成" in str(status) else "blue"
    return card_raw([markdown("\n".join(lines))], title=str(status or "工作中").replace("...", ""), template=template)


def build_progress_card(turn: int, summary: str, detail: str = "", *, compact: bool = False) -> str:
    summary = _clean_summary(summary, limit=120)
    body = [f"**{summary}**"]
    detail = str(detail or "").strip()
    if detail:
        body.append(detail)
    title = f"进展 · 第 {turn} 轮"
    return card_raw([markdown("\n\n".join(body))], title=title, template="blue")


def build_task_workspace_card(
    *,
    status: str,
    steps: Iterable[tuple[int, str, str]] | None = None,
    final_text: str = "",
    elapsed: int = 0,
    turn_count: int = 0,
    max_steps: int = 8,
    title: str = "任务工作台",
) -> str:
    """生成一张持续更新的任务工作台卡片，每轮进展默认折叠。"""
    steps = list(steps or [])
    visible_steps = steps[-max_steps:] if max_steps > 0 else steps
    hidden = max(0, len(steps) - len(visible_steps))
    status_lines = ["### 状态", f"- 当前：**{status or '工作中'}**"]
    if elapsed:
        status_lines.append(f"- 耗时：{elapsed}s")
    if turn_count:
        status_lines.append(f"- 轮次：{turn_count}")
    if hidden:
        status_lines.append(f"- 早期进展：已折叠，保留最近 {len(visible_steps)} 轮")

    elements: list[dict] = [markdown("\n".join(status_lines))]
    workflow_source = steps if _extract_task_titles(final_text) else visible_steps
    workflow = _workflow_markdown([(idx, summary) for idx, summary, _detail in workflow_source], final_text)
    if workflow:
        elements.append(markdown(workflow))
    if final_text:
        elements.append(markdown("### 最终输出"))
        elements.extend(markdown(chunk) for chunk in split_markdown_blocks(final_text))
    if visible_steps:
        elements.append(hr())
        elements.append(markdown("### 过程记录"))
    for idx, summary, detail in visible_steps:
        elements.append(collapsible_panel(f"第 {idx} 轮 · {summary}", detail))
    template = "green" if "完成" in str(status) else ("red" if "失败" in str(status) or "错误" in str(status) else "blue")
    return card_raw(elements, title=title, template=template)


def build_final_card(
    text: str,
    *,
    title: str = "已完成",
    template: str = "green",
    step_summaries: Iterable[tuple[int, str]] | None = None,
) -> str:
    elements: list[dict] = []
    workflow = _workflow_markdown(step_summaries, text)
    if workflow:
        elements.append(markdown(workflow))
        elements.append(hr())
    if step_summaries and not _has_output_heading(text):
        elements.append(markdown("### 最终输出"))
    elements.extend(markdown(chunk) for chunk in split_markdown_blocks(text))
    return card_raw(elements, title=title, template=template)
