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
        "sheet_names_ok": False,
        "budget_total_ok": False,
        "expense_total_ok": False,
        "summary_ok": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip():
        return result

    data = extract_json_block(response_text)
    if data is None:
        return result

    result["json_block_found"] = True
    sheet_names = data.get("sheet_names")
    budget_total = data.get("budget_total")
    expense_total = data.get("expense_total")
    summary = data.get("summary")

    result["sheet_names_ok"] = (
        isinstance(sheet_names, list)
        and len(sheet_names) >= 2
        and all(isinstance(x, str) and x.strip() for x in sheet_names)
    )
    result["budget_total_ok"] = isinstance(budget_total, (int, float)) and budget_total >= 0
    result["expense_total_ok"] = isinstance(expense_total, (int, float)) and expense_total >= 0
    result["summary_ok"] = isinstance(summary, str) and 1 <= len(summary.strip()) <= 80
    result["task_success"] = all(
        result[key]
        for key in [
            "response_present",
            "json_block_found",
            "sheet_names_ok",
            "budget_total_ok",
            "expense_total_ok",
            "summary_ok",
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
