#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_KEYS = [
    "base_model",
    "hardware_env",
    "critical_libs",
    "is_feasible_on_8xa100_80gb",
    "reason",
]


def grade(workspace_path: str) -> dict:
    root = Path(workspace_path)
    report_path = root / "report_08.json"

    scores: dict[str, object] = {}
    scores["report_created"] = report_path.exists()

    if report_path.exists():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            scores["json_keys_ok"] = all(k in data for k in REQUIRED_KEYS)
            scores["base_model_ok"] = isinstance(data.get("base_model"), str) and bool(data.get("base_model", "").strip())
            scores["hardware_env_ok"] = isinstance(data.get("hardware_env"), str) and bool(data.get("hardware_env", "").strip())
            libs = data.get("critical_libs")
            scores["critical_libs_ok"] = (
                isinstance(libs, list)
                and len(libs) >= 1
                and all(isinstance(x, str) and x.strip() for x in libs)
            )
            scores["feasibility_bool_ok"] = isinstance(data.get("is_feasible_on_8xa100_80gb"), bool)
            scores["reason_ok"] = isinstance(data.get("reason"), str) and bool(data.get("reason", "").strip())
        except Exception:
            scores["json_keys_ok"] = False
            scores["base_model_ok"] = False
            scores["hardware_env_ok"] = False
            scores["critical_libs_ok"] = False
            scores["feasibility_bool_ok"] = False
            scores["reason_ok"] = False
    else:
        scores["json_keys_ok"] = False
        scores["base_model_ok"] = False
        scores["hardware_env_ok"] = False
        scores["critical_libs_ok"] = False
        scores["feasibility_bool_ok"] = False
        scores["reason_ok"] = False

    completion_items = [
        bool(scores["report_created"]),
        bool(scores["json_keys_ok"]),
        bool(scores["base_model_ok"]),
        bool(scores["hardware_env_ok"]),
        bool(scores["critical_libs_ok"]),
        bool(scores["feasibility_bool_ok"]),
        bool(scores["reason_ok"]),
    ]

    scores["final_outputs_present"] = bool(scores["report_created"])
    scores["task_success"] = all(completion_items)
    scores["task_completion_score"] = round(sum(1.0 if x else 0.0 for x in completion_items) / len(completion_items), 4)
    return scores


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    print(json.dumps(grade(args.workspace), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
