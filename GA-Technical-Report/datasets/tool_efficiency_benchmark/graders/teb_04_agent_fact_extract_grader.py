#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_FACT_MARKERS = [
    "7 atomic tools",
    "1-2 steps",
    "subagent",
]


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
        "used_agent_ok": False,
        "facts_shape_ok": False,
        "facts_content_ok": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip():
        return result
    data = extract_json_block(response_text)
    if data is None:
        return result
    result["json_block_found"] = True
    used_agent = data.get("used_agent")
    facts = data.get("facts")
    result["used_agent_ok"] = used_agent is True
    result["facts_shape_ok"] = (
        isinstance(facts, list)
        and len(facts) == 3
        and all(isinstance(x, str) and x.strip() for x in facts)
    )
    joined = " ".join(facts).lower() if isinstance(facts, list) else ""
    result["facts_content_ok"] = all(marker.lower() in joined for marker in REQUIRED_FACT_MARKERS)
    result["task_success"] = all(result[k] for k in ["response_present", "json_block_found", "used_agent_ok", "facts_shape_ok", "facts_content_ok"])
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
