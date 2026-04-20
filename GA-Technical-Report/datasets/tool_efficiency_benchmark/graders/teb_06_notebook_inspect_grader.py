#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

def notebook_expectations() -> tuple[int, dict]:
    expected_index = 4
    expected_snapshot = {
        "mean_value": 7.25,
        "tool_count": 7,
        "step_claim": "1-2",
    }
    return expected_index, expected_snapshot


def grade_response(response_text: str, workspace: Path | None) -> dict:
    result = {
        "response_present": bool(response_text.strip()),
        "new_cell_index_ok": False,
        "notebook_modified_ok": False,
        "release_snapshot_source_ok": False,
        "final_outputs_present": bool(response_text.strip()),
        "task_success": False,
    }
    if workspace is None:
        return result
    notebook_path = workspace / "analysis.ipynb"
    expected_index, expected_snapshot = notebook_expectations()

    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    cells = notebook.get("cells", [])
    result["new_cell_index_ok"] = len(cells) > expected_index
    modified_ok = len(cells) == 5
    source_ok = False
    if modified_ok:
        new_cell = cells[expected_index]
        source = new_cell.get("source") or []
        source_text = "".join(source) if isinstance(source, list) else str(source)
        outputs = new_cell.get("outputs") or []
        output_text = json.dumps(outputs, ensure_ascii=False)
        modified_ok = (
            new_cell.get("cell_type") == "code"
            and "release_snapshot" in source_text
            and "values" in source_text
            and "summary" in source_text
        )
        source_ok = (
            str(expected_snapshot["mean_value"]) in source_text or str(expected_snapshot["mean_value"]) in output_text
        ) and (
            str(expected_snapshot["tool_count"]) in source_text or str(expected_snapshot["tool_count"]) in output_text
        ) and (
            expected_snapshot["step_claim"] in source_text or expected_snapshot["step_claim"] in output_text
        )
    result["notebook_modified_ok"] = modified_ok
    result["release_snapshot_source_ok"] = source_ok
    result["task_success"] = all(
        result[k]
        for k in [
            "new_cell_index_ok",
            "notebook_modified_ok",
            "release_snapshot_source_ok",
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
    workspace = Path(args.workspace) if args.workspace else None
    if not response_text and workspace:
        fallback = workspace / "final_response.txt"
        if fallback.exists():
            response_text = fallback.read_text(encoding="utf-8", errors="replace")
    print(json.dumps(grade_response(response_text, workspace), ensure_ascii=False))


if __name__ == "__main__":
    main()
