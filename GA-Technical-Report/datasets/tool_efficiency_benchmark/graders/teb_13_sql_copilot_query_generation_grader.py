#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path


EXPECTED_HEADER = [
    "channel_name",
    "first_order_customers",
    "refund_rate",
    "net_revenue_30d",
]


def grade(workspace_path: str) -> dict:
    root = Path(workspace_path)
    db_path = root / "analytics.db"
    query_path = root / "query.sql"
    result_path = root / "result.csv"
    analysis_path = root / "analysis.md"

    scores: dict[str, object] = {}
    scores["query_created"] = query_path.exists()
    scores["result_created"] = result_path.exists()
    scores["analysis_created"] = analysis_path.exists()

    if query_path.exists() and db_path.exists():
        query_text = query_path.read_text(encoding="utf-8", errors="ignore").strip()
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute(query_text)
            cur.fetchall()
            conn.close()
            scores["query_executable"] = True
        except Exception:
            scores["query_executable"] = False
    else:
        scores["query_executable"] = False

    if result_path.exists():
        try:
            with result_path.open("r", encoding="utf-8", newline="") as f:
                reader = list(csv.reader(f))
            header = reader[0] if reader else []
            rows = reader[1:] if len(reader) > 1 else []
            scores["result_header_ok"] = header == EXPECTED_HEADER
            scores["result_row_limit_ok"] = len(rows) <= 5

            numeric_ok = True
            refund_rate_range_ok = True
            for row in rows:
                if len(row) != 4:
                    numeric_ok = False
                    refund_rate_range_ok = False
                    break
                try:
                    float(row[1])
                    refund_rate = float(row[2])
                    float(row[3])
                    if not (0.0 <= refund_rate <= 1.0):
                        refund_rate_range_ok = False
                except Exception:
                    numeric_ok = False
                    refund_rate_range_ok = False
                    break

            scores["result_numeric_ok"] = numeric_ok
            scores["refund_rate_range_ok"] = refund_rate_range_ok
        except Exception:
            scores["result_header_ok"] = False
            scores["result_row_limit_ok"] = False
            scores["result_numeric_ok"] = False
            scores["refund_rate_range_ok"] = False
    else:
        scores["result_header_ok"] = False
        scores["result_row_limit_ok"] = False
        scores["result_numeric_ok"] = False
        scores["refund_rate_range_ok"] = False

    if analysis_path.exists():
        text = analysis_path.read_text(encoding="utf-8", errors="ignore").lower()
        has_formula = any(x in text for x in ["口径", "refund", "净收入", "30"])
        has_join = any(x in text for x in ["join", "关联", "campaign_attribution", "orders", "channels"])
        has_top_reason = any(x in text for x in ["第1", "第一", "top 1", "排名第", "入选", "原因"])
        scores["analysis_content_ok"] = all([has_formula, has_join, has_top_reason])
    else:
        scores["analysis_content_ok"] = False

    completion_keys = [
        "query_created",
        "query_executable",
        "result_created",
        "result_header_ok",
        "result_row_limit_ok",
        "result_numeric_ok",
        "refund_rate_range_ok",
        "analysis_created",
        "analysis_content_ok",
    ]
    scores["final_outputs_present"] = all(
        [
            bool(scores["query_created"]),
            bool(scores["result_created"]),
            bool(scores["analysis_created"]),
        ]
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
