#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path


RNG_SEED = 20260408
BASE_DATE = datetime(2026, 4, 1, 12, 0, 0)

COUNTRY_TIERS = ["core_market", "emerging_market"]
REGIONS = ["NA", "EU", "APAC", "LATAM"]
DEVICES = ["ios", "android", "web"]
CHANNELS = ["paid_search", "organic_search", "creator", "partner", "community", "email"]
USER_TIERS = ["new_user", "repeat_like", "team_buyer"]


def ts(days_ago: int, hour: int | None = None) -> str:
    dt = BASE_DATE - timedelta(days=days_ago, hours=0 if hour is None else (12 - hour))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def date_str(days_ago: int) -> str:
    return (BASE_DATE - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_metric_definition(path: Path) -> None:
    text = """# Metric Definition

本次实验分析对象为 `new_onboarding_v2`，目标是评估新版 onboarding 流程是否值得继续推进。

必须回答的问题：
1. treatment 在总体转化率上是否优于 control？
2. treatment 在收入和净收入上是否优于 control？
3. 是否存在一个不能忽略的负向分群？
4. 是否建议继续推进实验？

口径要求：
1. 样本集合以 `experiment_assignments.csv` 中 `experiment_name = new_onboarding_v2` 的用户为准。
2. `overall_conversion_rate` 定义为：分组内 `purchase_within_7d = 1` 的用户数 / 分组总用户数。
3. `payer_rate` 定义为：分组内有成功支付记录 (`payment_status = successful`) 的用户数 / 分组总用户数。
4. `arpu` 定义为：分组内成功支付金额总和 / 分组总用户数。
5. `net_revenue` 定义为：分组内成功支付金额总和减去成功退款金额总和。
6. 分群分析至少覆盖：`device_type` 和 `country_tier`；如需要，可结合 `acquisition_channel`。
7. 如果总体 uplift 为正，但存在样本量不小且明显退化的关键分群，报告中必须明确指出，不能只写总体结论。
8. 如果 treatment 的总体转化率提升但 `net_revenue` 未改善或下降，报告中必须明确指出该矛盾。

输出建议：
- `analysis_report.md` 应包含：实验背景、核心指标、关键分群发现、风险与建议。
- `chart_data.csv` 应是整理后的图表数据，不应直接复制原始表。
- `summary.json` 应包含：总体优胜组、总体转化 uplift、关键负向分群、是否建议继续推进。
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=".", help="Output directory for generated assets.")
    args = parser.parse_args()

    rng = random.Random(RNG_SEED)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    assignments: list[tuple] = []
    sessions: list[tuple] = []
    payments: list[tuple] = []
    segments: list[tuple] = []

    user_count = 10000
    session_id = 1
    payment_id = 1

    for user_id in range(1, user_count + 1):
        variant = "control" if user_id % 2 == 0 else "treatment"
        device = rng.choices(DEVICES, weights=[0.34, 0.46, 0.20])[0]
        country_tier = rng.choices(COUNTRY_TIERS, weights=[0.62, 0.38])[0]
        region = rng.choices(REGIONS, weights=[0.30, 0.24, 0.28, 0.18])[0]
        channel = rng.choices(CHANNELS, weights=[0.25, 0.18, 0.14, 0.12, 0.16, 0.15])[0]
        user_tier = rng.choices(USER_TIERS, weights=[0.72, 0.20, 0.08])[0]
        assign_days_ago = rng.randint(10, 45)

        assignments.append(
            (
                user_id,
                "new_onboarding_v2",
                variant,
                ts(assign_days_ago, rng.randint(8, 22)),
                region,
            )
        )
        segments.append((user_id, country_tier, device, channel, user_tier))

        base_completion = {
            "ios": 0.61,
            "android": 0.56,
            "web": 0.48,
        }[device]
        if variant == "treatment":
            if device == "android" and country_tier == "emerging_market":
                completion = base_completion - 0.06
            elif device == "web":
                completion = base_completion + 0.04
            else:
                completion = base_completion + 0.025
        else:
            completion = base_completion

        checkout_base = 0.62 if country_tier == "core_market" else 0.54
        purchase_base = 0.26 if channel in {"paid_search", "partner"} else 0.21
        if variant == "treatment":
            purchase_boost = 0.018
            if device == "android" and country_tier == "emerging_market":
                purchase_boost = -0.035
            elif device == "web":
                purchase_boost = 0.03
        else:
            purchase_boost = 0.0

        completed = 1 if rng.random() < completion else 0
        started_checkout = 1 if completed and rng.random() < checkout_base else 0
        purchased = 1 if started_checkout and rng.random() < (purchase_base + purchase_boost) else 0

        session_count = rng.randint(1, 4)
        for s_idx in range(session_count):
            viewed = 1
            session_completed = completed if s_idx == session_count - 1 else (1 if rng.random() < completion * 0.6 else 0)
            session_checkout = started_checkout if s_idx == session_count - 1 else (1 if session_completed and rng.random() < checkout_base * 0.5 else 0)
            session_purchase = purchased if s_idx == session_count - 1 else 0
            sessions.append(
                (
                    session_id,
                    user_id,
                    ts(assign_days_ago - rng.randint(0, 6), rng.randint(7, 23)),
                    device,
                    region,
                    viewed,
                    session_completed,
                    session_checkout,
                    session_purchase,
                )
            )
            session_id += 1

        if purchased:
            if variant == "treatment":
                amount = rng.uniform(18, 76)
                if device == "web":
                    amount += 6
                if device == "android" and country_tier == "emerging_market":
                    amount -= 7
            else:
                amount = rng.uniform(22, 82)

            amount = round(max(amount, 8.0), 2)
            refund_prob = 0.05
            if variant == "treatment":
                refund_prob = 0.075
                if device == "android" and country_tier == "emerging_market":
                    refund_prob = 0.16

            refund_status = "successful" if rng.random() < refund_prob else "none"
            refund_amount = 0.0
            if refund_status == "successful":
                refund_amount = round(amount * rng.uniform(0.35, 1.0), 2)

            payments.append(
                (
                    payment_id,
                    user_id,
                    ts(assign_days_ago - rng.randint(0, 7), rng.randint(8, 22)),
                    amount,
                    "successful",
                    refund_status,
                    refund_amount,
                )
            )
            payment_id += 1

            if rng.random() < 0.12:
                follow_amount = round(amount * rng.uniform(0.35, 0.8), 2)
                payments.append(
                    (
                        payment_id,
                        user_id,
                        ts(assign_days_ago - rng.randint(0, 25), rng.randint(8, 22)),
                        follow_amount,
                        "successful",
                        "none",
                        0.0,
                    )
                )
                payment_id += 1

    write_csv(
        output_dir / "experiment_assignments.csv",
        ["user_id", "experiment_name", "variant", "assignment_time", "assignment_region"],
        assignments,
    )
    write_csv(
        output_dir / "user_sessions.csv",
        [
            "session_id",
            "user_id",
            "session_start",
            "device_type",
            "region",
            "viewed_onboarding",
            "completed_onboarding",
            "started_checkout",
            "purchase_within_7d",
        ],
        sessions,
    )
    write_csv(
        output_dir / "payments.csv",
        [
            "payment_id",
            "user_id",
            "payment_time",
            "amount_usd",
            "payment_status",
            "refund_status",
            "refund_amount_usd",
        ],
        payments,
    )
    write_csv(
        output_dir / "segment_reference.csv",
        ["user_id", "country_tier", "device_type", "acquisition_channel", "user_tier"],
        segments,
    )
    write_metric_definition(output_dir / "metric_definition.md")

    print(f"Generated experiment assets at {output_dir}")
    print(f"experiment_assignments rows: {len(assignments)}")
    print(f"user_sessions rows: {len(sessions)}")
    print(f"payments rows: {len(payments)}")
    print(f"segment_reference rows: {len(segments)}")


if __name__ == "__main__":
    main()
