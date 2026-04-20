#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def extract_json_block(text: str) -> dict | None:
    for pattern in [r"```json\s*(\{[\s\S]*?\})\s*```", r"```\s*(\{[\s\S]*?\})\s*```"]:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            return json.loads(m.group(1))
        except Exception:
            continue
    return None


def count_nonempty_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def grade_response(response_text: str, workspace: Path | None) -> dict:
    result = {
        "response_present": bool(response_text.strip()),
        "json_block_found": False,
        "audio_file_field_ok": False,
        "line_count_ok": False,
        "audio_file_exists": False,
        "audio_file_nonempty": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip():
        return result
    data = extract_json_block(response_text)
    if data is None:
        return result
    result["json_block_found"] = True
    script_path = (workspace / "script.txt") if workspace else None
    audio_path = (workspace / "speech.wav") if workspace else None
    expected_lines = count_nonempty_lines(script_path) if script_path and script_path.exists() else 0
    result["audio_file_field_ok"] = data.get("audio_file") == "speech.wav"
    result["line_count_ok"] = data.get("line_count") == expected_lines
    result["audio_file_exists"] = bool(audio_path and audio_path.exists())
    result["audio_file_nonempty"] = bool(audio_path and audio_path.exists() and audio_path.stat().st_size > 0)
    result["task_success"] = all(result[k] for k in ["response_present", "json_block_found", "audio_file_field_ok", "line_count_ok", "audio_file_exists", "audio_file_nonempty"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace")
    parser.add_argument("--response-file")
    args = parser.parse_args()
    response_text = ""
    if args.response_file:
        response_text = Path(args.response_file).read_text(encoding="utf-8", errors="replace")
    workspace = Path(args.workspace) if args.workspace else None
    if not response_text and workspace:
        fallback = workspace / "final_response.txt"
        if fallback.exists():
            response_text = fallback.read_text(encoding="utf-8", errors="replace")
    print(json.dumps(grade_response(response_text, workspace), ensure_ascii=False))


if __name__ == "__main__":
    main()
