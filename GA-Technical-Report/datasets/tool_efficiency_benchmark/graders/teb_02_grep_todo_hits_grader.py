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


def expected_hits(workspace: Path) -> list[dict]:
    hits = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(workspace))
        for idx, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if "TODO" in line:
                hits.append({"path": rel, "line": idx})
    return sorted(hits, key=lambda x: (x["path"], x["line"]))


def grade_response(response_text: str, workspace: Path | None) -> dict:
    result = {
        "response_present": bool(response_text.strip()),
        "json_block_found": False,
        "hits_field_ok": False,
        "hits_match_expected": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if not response_text.strip() or workspace is None:
        return result
    data = extract_json_block(response_text)
    if data is None:
        return result
    result["json_block_found"] = True
    hits = data.get("hits")
    result["hits_field_ok"] = (
        isinstance(hits, list)
        and all(isinstance(x, dict) and isinstance(x.get("path"), str) and isinstance(x.get("line"), int) for x in hits)
    )
    result["hits_match_expected"] = result["hits_field_ok"] and sorted(hits, key=lambda x: (x["path"], x["line"])) == expected_hits(workspace)
    result["task_success"] = all(result[k] for k in ["response_present", "json_block_found", "hits_field_ok", "hits_match_expected"])
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
