#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


EXPECTED_HEADER = [
    "provider",
    "model",
    "input_cost_per_1m",
    "output_cost_per_1m",
    "estimated_monthly_cost_usd",
    "meets_budget",
]

EXPECTED_JSON_KEYS = [
    "primary_option",
    "primary_option_feasible",
    "fallback_triggered",
    "recommended_plan",
    "recommended_models",
    "estimated_monthly_cost_usd",
    "reason",
]

VALID_PLANS = {"single_model", "dual_model", "infeasible"}


def grade(workspace_path: str) -> dict:
    root = Path(workspace_path)
    csv_path = root / "cost_comparison.csv"
    json_path = root / "decision_04.json"

    scores: dict[str, object] = {}
    scores["cost_csv_created"] = csv_path.exists()
    scores["decision_json_created"] = json_path.exists()

    if csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            header = rows[0] if rows else []
            body = rows[1:] if len(rows) > 1 else []
            scores["csv_header_ok"] = header == EXPECTED_HEADER
            scores["csv_has_rows"] = len(body) >= 1
        except Exception:
            scores["csv_header_ok"] = False
            scores["csv_has_rows"] = False
    else:
        scores["csv_header_ok"] = False
        scores["csv_has_rows"] = False

    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            scores["json_keys_ok"] = all(k in data for k in EXPECTED_JSON_KEYS)

            recommended_plan = data.get("recommended_plan")
            scores["recommended_plan_ok"] = recommended_plan in VALID_PLANS

            models = data.get("recommended_models")
            models_ok = isinstance(models, list)
            if recommended_plan == "single_model":
                models_ok = models_ok and len(models) == 1
            elif recommended_plan == "dual_model":
                models_ok = models_ok and len(models) == 2
            elif recommended_plan == "infeasible":
                models_ok = models_ok and len(models) in {0, 1}
            scores["recommended_models_ok"] = models_ok

            try:
                scores["estimated_cost_ok"] = float(data.get("estimated_monthly_cost_usd")) >= 0
            except Exception:
                scores["estimated_cost_ok"] = False
        except Exception:
            scores["json_keys_ok"] = False
            scores["recommended_plan_ok"] = False
            scores["recommended_models_ok"] = False
            scores["estimated_cost_ok"] = False
    else:
        scores["json_keys_ok"] = False
        scores["recommended_plan_ok"] = False
        scores["recommended_models_ok"] = False
        scores["estimated_cost_ok"] = False

    completion_keys = [
        "cost_csv_created",
        "csv_header_ok",
        "csv_has_rows",
        "decision_json_created",
        "json_keys_ok",
        "recommended_plan_ok",
        "recommended_models_ok",
        "estimated_cost_ok",
    ]
    scores["final_outputs_present"] = all(
        [bool(scores["cost_csv_created"]), bool(scores["decision_json_created"])]
    )
    scores["task_success"] = all(bool(scores[key]) for key in completion_keys)
    scores["task_completion_score"] = round(
        sum(1.0 if bool(scores[key]) else 0.0 for key in completion_keys) / len(completion_keys),
        4,
    )
    return scores


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    result = grade(args.workspace)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
