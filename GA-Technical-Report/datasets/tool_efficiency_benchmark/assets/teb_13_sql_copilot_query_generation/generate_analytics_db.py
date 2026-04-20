#!/usr/bin/env python3
import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


RNG_SEED = 20260408


CHANNELS = [
    (1, "Google Search", "paid_search", "global", 1),
    (2, "YouTube Creators", "content", "global", 1),
    (3, "Reddit Community", "community", "global", 0),
    (4, "LinkedIn Ads", "paid_search", "global", 1),
    (5, "X Performance", "social", "global", 1),
    (6, "Product Hunt", "community", "global", 0),
    (7, "Developer Newsletter", "content", "us", 1),
    (8, "Affiliate Partners", "affiliate", "global", 1),
    (9, "Open Source Docs", "content", "global", 0),
    (10, "APAC Resellers", "partner", "apac", 1),
    (11, "Startup Events", "partner", "us", 1),
    (12, "SEO Blog", "content", "global", 0),
]

COUNTRIES = ["US", "CA", "GB", "DE", "FR", "JP", "SG", "IN", "AU", "BR"]
DEVICE_TYPES = ["ios", "android", "web"]
PRODUCT_FAMILIES = ["starter", "pro", "team", "addon"]
BILLING_PERIODS = ["monthly", "annual", "one_time"]
REFUND_REASONS = ["fraud", "duplicate", "billing_issue", "customer_request", "service_issue"]
EVENT_TYPES = ["landing", "signup", "trial_start", "checkout", "login", "cancel"]


def d(days_ago: int) -> str:
    base = datetime(2026, 4, 1)
    return (base - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def dt(days_ago: int, hour: int) -> str:
    base = datetime(2026, 4, 1, hour, 0, 0)
    return (base - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS customers;
        DROP TABLE IF EXISTS channels;
        DROP TABLE IF EXISTS campaign_attribution;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS order_items;
        DROP TABLE IF EXISTS refunds;
        DROP TABLE IF EXISTS customer_events;

        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            signup_date TEXT NOT NULL,
            country TEXT NOT NULL,
            device_type TEXT NOT NULL,
            acquisition_channel_hint TEXT NOT NULL,
            is_enterprise INTEGER NOT NULL
        );

        CREATE TABLE channels (
            channel_id INTEGER PRIMARY KEY,
            channel_name TEXT NOT NULL,
            channel_type TEXT NOT NULL,
            region TEXT NOT NULL,
            is_paid INTEGER NOT NULL
        );

        CREATE TABLE campaign_attribution (
            attribution_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            first_order_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            campaign_name TEXT NOT NULL,
            attribution_date TEXT NOT NULL
        );

        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            gross_amount REAL NOT NULL,
            discount_amount REAL NOT NULL,
            net_paid_amount REAL NOT NULL,
            currency TEXT NOT NULL,
            order_status TEXT NOT NULL,
            is_first_order INTEGER NOT NULL
        );

        CREATE TABLE order_items (
            order_item_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_family TEXT NOT NULL,
            billing_period TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            item_net_amount REAL NOT NULL
        );

        CREATE TABLE refunds (
            refund_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            refund_date TEXT NOT NULL,
            refund_amount REAL NOT NULL,
            refund_reason TEXT NOT NULL,
            refund_status TEXT NOT NULL
        );

        CREATE TABLE customer_events (
            event_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            event_time TEXT NOT NULL,
            event_type TEXT NOT NULL,
            session_source TEXT NOT NULL
        );
        """
    )


def generate_dataset(conn: sqlite3.Connection) -> None:
    rng = random.Random(RNG_SEED)
    cur = conn.cursor()

    cur.executemany("INSERT INTO channels VALUES (?, ?, ?, ?, ?)", CHANNELS)

    customers = []
    orders = []
    order_items = []
    refunds = []
    attributions = []
    events = []

    order_id = 1
    order_item_id = 1
    refund_id = 1
    attribution_id = 1
    event_id = 1

    for customer_id in range(1, 4001):
        signup_days_ago = rng.randint(0, 180)
        channel = rng.choice(CHANNELS)
        customers.append(
            (
                customer_id,
                d(signup_days_ago),
                rng.choice(COUNTRIES),
                rng.choice(DEVICE_TYPES),
                channel[1],
                1 if rng.random() < 0.08 else 0,
            )
        )

        for ev in ["landing", "signup", "trial_start", "checkout"]:
            events.append((event_id, customer_id, dt(signup_days_ago, rng.randint(8, 20)), ev, channel[1]))
            event_id += 1

        num_orders = rng.choices([1, 2, 3, 4, 5], weights=[0.45, 0.25, 0.17, 0.09, 0.04])[0]
        first_order_for_customer = None
        first_channel_id = None

        for idx in range(num_orders):
            days_offset = max(0, signup_days_ago - rng.randint(0, 45) - idx * rng.randint(5, 22))
            gross = round(rng.uniform(39, 499), 2)
            discount = round(gross * rng.choice([0, 0.05, 0.1, 0.15]), 2)
            net = round(gross - discount, 2)
            is_first = 1 if idx == 0 else 0
            status = "paid"

            if is_first:
                first_order_for_customer = order_id
                first_channel_id = channel[0]

            orders.append(
                (
                    order_id,
                    customer_id,
                    d(days_offset),
                    gross,
                    discount,
                    net,
                    "USD",
                    status,
                    is_first,
                )
            )

            remaining = net
            num_items = rng.choices([1, 2, 3], weights=[0.55, 0.35, 0.10])[0]
            for item_idx in range(num_items):
                if item_idx == num_items - 1:
                    item_amount = round(remaining, 2)
                else:
                    item_amount = round(rng.uniform(0.2, 0.7) * remaining, 2)
                    remaining = round(remaining - item_amount, 2)
                order_items.append(
                    (
                        order_item_id,
                        order_id,
                        rng.choice(PRODUCT_FAMILIES),
                        rng.choice(BILLING_PERIODS),
                        rng.randint(1, 4),
                        max(item_amount, 1.0),
                    )
                )
                order_item_id += 1

            refund_probability = 0.07 if is_first else 0.04
            if rng.random() < refund_probability:
                refund_parts = 1 if rng.random() < 0.82 else 2
                refunded_total = round(net * rng.uniform(0.2, 1.0), 2)
                refunded_remaining = refunded_total
                for part_idx in range(refund_parts):
                    if part_idx == refund_parts - 1:
                        amount = round(refunded_remaining, 2)
                    else:
                        amount = round(refunded_total * rng.uniform(0.35, 0.65), 2)
                        refunded_remaining = round(refunded_remaining - amount, 2)
                    status = "successful" if rng.random() < 0.92 else "pending"
                    refunds.append(
                        (
                            refund_id,
                            order_id,
                            d(max(0, days_offset - rng.randint(0, 12))),
                            max(amount, 1.0),
                            rng.choice(REFUND_REASONS),
                            status,
                        )
                    )
                    refund_id += 1

            for _ in range(rng.randint(1, 4)):
                events.append(
                    (
                        event_id,
                        customer_id,
                        dt(max(0, days_offset - rng.randint(0, 12)), rng.randint(7, 23)),
                        rng.choice(EVENT_TYPES),
                        channel[1],
                    )
                )
                event_id += 1

            order_id += 1

        attributions.append(
            (
                attribution_id,
                customer_id,
                first_order_for_customer,
                first_channel_id,
                f"{channel[1]} Q{rng.randint(1,4)} campaign",
                d(signup_days_ago),
            )
        )
        attribution_id += 1

    cur.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?)", customers)
    cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", orders)
    cur.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)", order_items)
    cur.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)", refunds)
    cur.executemany("INSERT INTO campaign_attribution VALUES (?, ?, ?, ?, ?, ?)", attributions)
    cur.executemany("INSERT INTO customer_events VALUES (?, ?, ?, ?, ?)", events)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="analytics.db", help="Path to output SQLite database.")
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(output_path)
    try:
        init_db(conn)
        generate_dataset(conn)
    finally:
        conn.close()

    print(f"Generated analytics database at {output_path}")


if __name__ == "__main__":
    main()
