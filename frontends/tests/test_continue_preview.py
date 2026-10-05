"""Preview extraction for /continue when the first user prompt sits past the head window."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "frontends"))

from continue_cmd import _preview_from_file, list_sessions  # noqa: E402


def _block(prompt_obj, response_text="ok"):
    prompt = json.dumps(prompt_obj, ensure_ascii=False)
    return (
        f"=== Prompt === extra\n{prompt}\n"
        f"=== Response === extra\n[{{'type': 'text', 'text': {response_text!r}}}]\n"
    )


def _tool_block():
    return _block(
        {"role": "user", "content": [{"type": "tool_result", "content": "x" * 400}]}
    )


def test_preview_finds_user_prompt_past_32kb_head(tmp_path, monkeypatch):
    log_dir = tmp_path / "temp" / "model_responses"
    log_dir.mkdir(parents=True)
    path = log_dir / "model_responses_4242.txt"

    user_text = "Index remaining PDFs using focr house style and skip Jira keys."
    prefix = _tool_block() * 80  # well over 32KB of tool_result rounds
    suffix = _tool_block() * 80
    middle = _block({"role": "user", "content": [{"type": "text", "text": user_text}]})
    path.write_text(prefix + middle + suffix, encoding="utf-8")
    assert path.stat().st_size > 64 * 1024

    preview = _preview_from_file(str(path))
    assert "Index remaining PDFs" in preview

    monkeypatch.setattr("continue_cmd._LOG_GLOB", str(log_dir / "model_responses_*.txt"))
    monkeypatch.setattr("continue_cmd._ROUNDS_CACHE_PATH", str(tmp_path / "continue_rounds_cache.json"))
    sessions = list_sessions()
    assert any("Index remaining PDFs" in item[2] for item in sessions)
