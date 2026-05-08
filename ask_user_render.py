import ast
import json


DEFAULT_ASK_USER_QUESTION = "请提供下一步信息："
DEFAULT_ASK_USER_INTRO = "🙋 需要你来决定下一步"
DEFAULT_ASK_USER_FOOTER = "请直接回复你的选择，或补充新的说明。"


def _truncate(text, max_len):
    text = str(text or "").strip()
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _normalize_candidates(raw_candidates):
    if not isinstance(raw_candidates, (list, tuple)):
        return []
    candidates = []
    for candidate in raw_candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            candidates.append(text)
    return candidates


def coerce_ask_user_data(data):
    if not isinstance(data, dict):
        return None
    question = str(data.get("question") or DEFAULT_ASK_USER_QUESTION).strip() or DEFAULT_ASK_USER_QUESTION
    return {"question": question, "candidates": _normalize_candidates(data.get("candidates") or [])}


def extract_ask_user_event(exit_reason):
    payload = exit_reason
    if isinstance(exit_reason, dict) and "result" in exit_reason and "data" in exit_reason:
        if exit_reason.get("result") != "EXITED":
            return None
        payload = exit_reason.get("data")
    if not isinstance(payload, dict):
        return None
    if payload.get("status") != "INTERRUPT" or payload.get("intent") != "HUMAN_INTERVENTION":
        return None
    return coerce_ask_user_data(payload.get("data"))


def extract_ask_user_event_from_text(raw_text):
    text = str(raw_text or "").strip()
    if not text:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except Exception:
            continue
        event = extract_ask_user_event(parsed)
        if event:
            return event
    return None


def summarize_ask_user_event(event, max_len=120):
    if not event:
        return ""
    question = str(event.get("question") or DEFAULT_ASK_USER_QUESTION).strip() or DEFAULT_ASK_USER_QUESTION
    candidates = _normalize_candidates(event.get("candidates") or [])
    summary = f"等待用户回复：{question}"
    if candidates:
        preview = " / ".join(candidates[:3])
        if len(candidates) > 3:
            preview += " / ..."
        summary += f"（选项：{preview}）"
    return _truncate(summary, max_len)


def format_ask_user_message(event, intro=DEFAULT_ASK_USER_INTRO, footer=DEFAULT_ASK_USER_FOOTER):
    normalized = coerce_ask_user_data(event)
    if not normalized:
        normalized = {"question": DEFAULT_ASK_USER_QUESTION, "candidates": []}
    lines = [intro, "", normalized["question"]]
    if normalized["candidates"]:
        lines.extend(["", "可选项："])
        for idx, candidate in enumerate(normalized["candidates"], start=1):
            lines.append(f"{idx}. {candidate}")
    if footer:
        lines.extend(["", footer])
    return "\n".join(lines).strip()


def summarize_tool_args(name, args, max_len=120):
    clean_args = {k: v for k, v in (args or {}).items() if not str(k).startswith("_")}
    if name == "ask_user":
        event = coerce_ask_user_data(clean_args)
        return summarize_ask_user_event(event, max_len=max_len)
    try:
        rendered = json.dumps(clean_args, ensure_ascii=False)
    except TypeError:
        rendered = str(clean_args)
    return _truncate(rendered, max_len)