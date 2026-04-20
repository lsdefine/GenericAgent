#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path


EXPECTED_CHART_HEADER = [
    "variant",
    "segment",
    "conversion_rate",
    "payer_rate",
    "arpu",
    "net_revenue",
]

EXPECTED_SUMMARY_KEYS = [
    "overall_winner",
    "overall_conversion_lift",
    "largest_negative_segment",
    "ship_recommendation",
]


def grade(workspace_path: str) -> dict:
    root = Path(workspace_path)
    report_path = root / "analysis_report.md"
    chart_path = root / "chart_data.csv"
    summary_path = root / "summary.json"
    fig1_path = root / "figure_1.png"
    fig2_path = root / "figure_2.png"

    scores: dict[str, object] = {}
    scores["report_created"] = report_path.exists()
    scores["chart_data_created"] = chart_path.exists()
    scores["summary_created"] = summary_path.exists()
    scores["figure_1_created"] = fig1_path.exists()
    scores["figure_2_created"] = fig2_path.exists()

    if report_path.exists():
        text = report_path.read_text(encoding="utf-8", errors="ignore")
        char_count = len(re.sub(r"\s+", "", text))
        scores["report_length_ok"] = 600 <= char_count <= 1200
        required_headers = ["# 实验背景", "# 核心指标", "# 关键分群发现", "# 风险与建议"]
        scores["report_headers_ok"] = all(h in text for h in required_headers)
        report_content_ok = all(x in text for x in ["总体", "净收入", "建议"]) and any(
            x in text for x in ["负向分群", "分群退化", "largest_negative_segment"]
        )
        scores["report_content_ok"] = report_content_ok
    else:
        scores["report_length_ok"] = False
        scores["report_headers_ok"] = False
        scores["report_content_ok"] = False

    if chart_path.exists():
        try:
            with chart_path.open("r", encoding="utf-8", newline="") as f:
                reader = list(csv.reader(f))
            header = reader[0] if reader else []
            rows = reader[1:] if len(reader) > 1 else []
            scores["chart_header_ok"] = header == EXPECTED_CHART_HEADER
            scores["chart_row_count_ok"] = len(rows) >= 4
        except Exception:
            scores["chart_header_ok"] = False
            scores["chart_row_count_ok"] = False
    else:
        scores["chart_header_ok"] = False
        scores["chart_row_count_ok"] = False

    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            scores["summary_keys_ok"] = all(k in data for k in EXPECTED_SUMMARY_KEYS)
        except Exception:
            scores["summary_keys_ok"] = False
    else:
        scores["summary_keys_ok"] = False

    completion_keys = [
        "report_created",
        "report_length_ok",
        "report_headers_ok",
        "chart_data_created",
        "chart_header_ok",
        "chart_row_count_ok",
        "summary_created",
        "summary_keys_ok",
        "figures_present",
    ]
    scores["figures_present"] = fig1_path.exists() and fig2_path.exists()
    scores["final_outputs_present"] = all(
        [
            bool(scores["report_created"]),
            bool(scores["chart_data_created"]),
            bool(scores["summary_created"]),
            bool(scores["figure_1_created"]),
            bool(scores["figure_2_created"]),
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
