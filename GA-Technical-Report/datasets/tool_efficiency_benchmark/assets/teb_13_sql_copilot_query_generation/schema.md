# Analytics Warehouse Schema

## Overview
This SQLite database models a subscription commerce business that acquires users through multiple marketing channels. The main analysis topic is acquisition quality: which channels bring in first-order users with strong 30-day net revenue and low refund rates.

## Table: customers
Purpose: user dimension table.
Primary key: `customer_id`.

Fields:
- `customer_id` INTEGER: unique user id.
- `signup_date` TEXT: user signup date in `YYYY-MM-DD` format.
- `country` TEXT: signup country.
- `device_type` TEXT: primary signup device, such as `ios`, `android`, or `web`.
- `acquisition_channel_hint` TEXT: noisy channel hint captured at signup; not guaranteed to match final attributed first order.
- `is_enterprise` INTEGER: `1` for enterprise customers, `0` otherwise.

## Table: channels
Purpose: acquisition channel dimension table.
Primary key: `channel_id`.

Fields:
- `channel_id` INTEGER: unique channel id.
- `channel_name` TEXT: human-readable channel name.
- `channel_type` TEXT: category such as `paid_search`, `social`, `affiliate`, `content`, `community`, or `partner`.
- `region` TEXT: dominant operating region.
- `is_paid` INTEGER: `1` if channel is paid, `0` otherwise.

## Table: campaign_attribution
Purpose: first-order attribution table. This is the authoritative source for channel attribution in the task.
Primary key: `attribution_id`.

Fields:
- `attribution_id` INTEGER: unique attribution row id.
- `customer_id` INTEGER: references `customers.customer_id`.
- `first_order_id` INTEGER: references `orders.order_id` for the customer's first order.
- `channel_id` INTEGER: references `channels.channel_id`.
- `campaign_name` TEXT: campaign label attached to the attributed first order.
- `attribution_date` TEXT: attribution date in `YYYY-MM-DD` format.

Important note:
- Use this table, not `customers.acquisition_channel_hint`, when a task requires official acquisition channel attribution for first orders.

## Table: orders
Purpose: order fact table.
Primary key: `order_id`.

Fields:
- `order_id` INTEGER: unique order id.
- `customer_id` INTEGER: references `customers.customer_id`.
- `order_date` TEXT: order date in `YYYY-MM-DD` format.
- `gross_amount` REAL: pre-discount order amount.
- `discount_amount` REAL: discount applied at purchase time.
- `net_paid_amount` REAL: amount actually paid after discount.
- `currency` TEXT: order currency. This dataset uses only `USD`.
- `order_status` TEXT: order state such as `paid`, `partially_refunded`, `refunded`, or `cancelled`.
- `is_first_order` INTEGER: `1` if this row is the user's first completed order, `0` otherwise.

Important note:
- The task should rely on `is_first_order = 1` to identify first orders rather than recomputing from scratch unless explicitly asked otherwise.

## Table: order_items
Purpose: item-level order breakdown.
Primary key: `order_item_id`.

Fields:
- `order_item_id` INTEGER: unique item row id.
- `order_id` INTEGER: references `orders.order_id`.
- `product_family` TEXT: product family such as `starter`, `pro`, `team`, or `addon`.
- `billing_period` TEXT: billing period such as `monthly`, `annual`, or `one_time`.
- `quantity` INTEGER: purchased quantity.
- `item_net_amount` REAL: item-level net amount.

Important note:
- This table is included to make the warehouse realistic, but the core acquisition-quality task can be solved without joining it.

## Table: refunds
Purpose: refund fact table.
Primary key: `refund_id`.

Fields:
- `refund_id` INTEGER: unique refund row id.
- `order_id` INTEGER: references `orders.order_id`.
- `refund_date` TEXT: refund date in `YYYY-MM-DD` format.
- `refund_amount` REAL: refunded amount.
- `refund_reason` TEXT: refund category such as `fraud`, `duplicate`, `billing_issue`, `customer_request`, or `service_issue`.
- `refund_status` TEXT: refund state such as `pending`, `successful`, or `rejected`.

Important note:
- A single order may have multiple refund rows.
- For business calculations, successful refunds are the authoritative refund events.

## Table: customer_events
Purpose: user event stream used to add realistic warehouse noise and optional behavioral analysis.
Primary key: `event_id`.

Fields:
- `event_id` INTEGER: unique event id.
- `customer_id` INTEGER: references `customers.customer_id`.
- `event_time` TEXT: event timestamp in `YYYY-MM-DD HH:MM:SS` format.
- `event_type` TEXT: event type such as `landing`, `signup`, `trial_start`, `checkout`, `login`, or `cancel`.
- `session_source` TEXT: captured session source label.

Important note:
- The core task does not require this table, but it is intentionally present so the database resembles a real analytics warehouse rather than a textbook join exercise.

## Relationship Summary
- `orders.customer_id -> customers.customer_id`
- `order_items.order_id -> orders.order_id`
- `refunds.order_id -> orders.order_id`
- `campaign_attribution.customer_id -> customers.customer_id`
- `campaign_attribution.first_order_id -> orders.order_id`
- `campaign_attribution.channel_id -> channels.channel_id`
- `customer_events.customer_id -> customers.customer_id`

## Business Semantics for the Task
- Official acquisition channel for first-order analysis comes from `campaign_attribution`.
- First-order users are identified by `orders.is_first_order = 1`.
- Refund calculations should use rows with `refund_status = 'successful'`.
- Net revenue should be interpreted as paid order revenue minus successful refund amounts over the specified task window.
