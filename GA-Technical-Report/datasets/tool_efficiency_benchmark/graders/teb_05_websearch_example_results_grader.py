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


def grade_response(response_text: str) -> dict:
    result = {
        "response_present": bool(response_text.strip()),
        "json_block_found": False,
        "query_ok": False,
        "results_shape_ok": False,
        "has_example_domain_result": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip():
        return result
    data = extract_json_block(response_text)
    if data is None:
        return result
    result["json_block_found"] = True
    query = data.get("query")
    items = data.get("results")
    result["query_ok"] = query == "Example Domain official site"
    result["results_shape_ok"] = (
        isinstance(items, list)
        and len(items) == 3
        and all(isinstance(x, dict) and isinstance(x.get("title"), str) and isinstance(x.get("url"), str) for x in items)
    )
    result["has_example_domain_result"] = bool(
        isinstance(items, list) and any("example.com" in str(x.get("url", "")) for x in items)
    )
    result["task_success"] = all(result[k] for k in ["response_present", "json_block_found", "query_ok", "results_shape_ok", "has_example_domain_result"])
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
