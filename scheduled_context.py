"""Scheduled task output journal: records what the reflect runner just sent.
Frontends read recent entries and inject them into the next user-prompt so the
agent can answer follow-up questions about its own scheduled output.
"""
import json, os, re, time

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _compact(text, limit=1800):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def _field(text, name):
    m = re.search(rf"^\[{re.escape(name)}\]\s*(.+)$", text or "", re.M)
    return m.group(1).strip() if m else ""


def _read_report(path):
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def record_scheduled_output(task, result, root=_ROOT, keep=20):
    """Append one entry to the journal after a reflect-mode task finishes."""
    task_name = _field(task, "定时任务")
    if not task_name:
        return
    report_path = _field(result, "报告路径") or _field(task, "报告路径")
    body = _read_report(report_path) if report_path else result
    entry = {
        "ts": time.time(),
        "task": task_name,
        "report": report_path,
        "text": _compact(body),
    }
    path = os.path.join(root, "temp", "scheduled_context.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            rows = [line for line in f if line.strip()][-keep + 1:]
    rows.append(json.dumps(entry, ensure_ascii=False) + "\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(rows)
    os.replace(tmp, path)


def recent_scheduled_context(root=_ROOT, max_age=6 * 3600, limit=3):
    """Return formatted context string from recent scheduled outputs, or ''."""
    path = os.path.join(root, "temp", "scheduled_context.jsonl")
    if not os.path.exists(path):
        return ""
    now = time.time()
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                item = json.loads(line)
                item["ts"] = float(item.get("ts", 0))
            except Exception:
                continue
            if now - item["ts"] <= max_age:
                entries.append(item)
    if not entries:
        return ""
    parts = ["### Recent scheduled task outputs"]
    for item in entries[-limit:]:
        when = time.strftime("%m-%d %H:%M", time.localtime(item["ts"]))
        report = f"\nReport: {item['report']}" if item.get("report") else ""
        parts.append(f"[{when}] {item.get('task', 'scheduled task')}{report}\n{item.get('text', '')}")
    return "\n\n".join(parts)
