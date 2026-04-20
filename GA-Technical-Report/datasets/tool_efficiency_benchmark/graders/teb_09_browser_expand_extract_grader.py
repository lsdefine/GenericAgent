#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_PHRASES = [
    "Expanded findings",
    "retention improved by 18%",
]


def extract_text_block(text: str) -> str:
    patterns = [
        r"```text\s*([\s\S]*?)\s*```",
        r"```\s*([\s\S]*?)\s*```",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return ""


def grade_response(response_text: str) -> dict:
    result = {
        "response_present": bool(response_text.strip()),
        "text_block_found": False,
        "content_length_ok": False,
        "contains_required_phrases": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip():
        return result

    text = extract_text_block(response_text)
    if not text:
        return result

    result["text_block_found"] = True
    result["content_length_ok"] = len(text.strip()) >= 80
    result["contains_required_phrases"] = all(phrase in text for phrase in REQUIRED_PHRASES)
    result["task_success"] = all(
        result[key]
        for key in [
            "response_present",
            "text_block_found",
            "content_length_ok",
            "contains_required_phrases",
        ]
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace")
    parser.add_argument("--response-file")
    args = parser.parse_args()
    response_text = ""
    if args.response_file:
        response_text = Path(args.response_file).read_text(encoding="utf-8", errors="replace")
    elif args.workspace:
        fallback = Path(args.workspace) / "final_response.txt"
        if fallback.exists():
            response_text = fallback.read_text(encoding="utf-8", errors="replace")
    print(json.dumps(grade_response(response_text), ensure_ascii=False))


if __name__ == "__main__":
    main()
