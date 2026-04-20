#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def extract_json_block(text: str) -> dict | None:
    patterns = [
        r"```json\s*(\{[\s\S]*?\})\s*```",
        r"```\s*(\{[\s\S]*?\})\s*```",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            return json.loads(m.group(1))
        except Exception:
            continue
    return None


def grade_response(response_text: str) -> dict:
    result = {
        "response_present": bool(response_text.strip()),
        "json_block_found": False,
        "row_count_ok": False,
        "columns_ok": False,
        "numeric_summary_ok": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip():
        return result

    data = extract_json_block(response_text)
    if data is None:
        return result

    result["json_block_found"] = True
    row_count = data.get("row_count")
    columns = data.get("columns")
    numeric_summary = data.get("numeric_summary")

    result["row_count_ok"] = isinstance(row_count, int) and row_count > 0
    result["columns_ok"] = (
        isinstance(columns, list)
        and len(columns) >= 2
        and all(isinstance(x, str) and x.strip() for x in columns)
    )
    result["numeric_summary_ok"] = (
        isinstance(numeric_summary, dict)
        and all(key in numeric_summary for key in ["min", "max", "mean"])
    )
    result["task_success"] = all(
        result[key]
        for key in [
            "response_present",
            "json_block_found",
            "row_count_ok",
            "columns_ok",
            "numeric_summary_ok",
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
