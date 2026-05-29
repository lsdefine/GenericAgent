"""Shared /todo command — persistent user TODO list.

Data file: temp/user_todo.json  (list of str, creation time tracked for display)
API:  load(), save(), add(text), remove(idx), list_all()
"""

from __future__ import annotations
import json, os, time

_TODO_PATH = os.path.join(os.path.dirname(__file__), "..", "temp", "user_todo.json")


def _path() -> str:
    return os.path.abspath(_TODO_PATH)


def load() -> list[dict]:
    """Return [{id, text, created}, …] or empty list."""
    p = _path()
    if not os.path.isfile(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save(items: list[dict]) -> None:
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add(text: str) -> int:
    """Append a new TODO item. Returns its 1-based index."""
    items = load()
    item = {
        "id": int(time.time() * 1000) % 1000000,
        "text": text.strip(),
        "created": time.strftime("%m-%d %H:%M"),
    }
    items.append(item)
    save(items)
    return len(items)


def remove(idx: int) -> str | None:
    """Remove by 0-based index. Returns removed text or None."""
    items = load()
    if not (0 <= idx < len(items)):
        return None
    removed = items.pop(idx)
    save(items)
    return removed["text"]


def list_all() -> list[dict]:
    """Return items with 'text' and 'created'."""
    return load()


def format_list(items: list[dict]) -> list[str]:
    """Format items for terminal display, one str per item, 1-based."""
    if not items:
        return ["(empty)"]
    return [f"{i+1}. {it['text']}  ({it['created']})" for i, it in enumerate(items)]
