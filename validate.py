"""Independent checks for every shareholder-story metric family."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from verify_source import verify_sources


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
verify_sources()
findings = json.loads((OUT / "findings.json").read_text(encoding="utf-8"))
q, o = findings["quality"], findings["overall"]

con = duckdb.connect()
con.execute("""
CREATE OR REPLACE TEMP VIEW cohort_orders AS
SELECT *,
       CAST(order_delivered_customer_date AS DATE) > CAST(order_estimated_delivery_date AS DATE) AS late,
       date_diff('day', CAST(order_delivered_carrier_date AS DATE), CAST(order_estimated_delivery_date AS DATE)) AS slack_days
FROM read_csv_auto('data/raw/olist_orders_dataset.csv')
WHERE order_purchase_timestamp >= '2017-01-01'
  AND order_purchase_timestamp <= '2018-08-18 13:22:46';
""")

headline = con.execute("""
SELECT COUNT(*) AS orders,
       SUM(late::INTEGER) AS late_orders,
       SUM(CASE WHEN strftime(CAST(order_purchase_timestamp AS TIMESTAMP), '%Y-%m') IN ('2018-02','2018-03')
                AND late THEN 1 ELSE 0 END) AS feb_mar_late
FROM cohort_orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL
""").fetchone()
assert headline == (o["orders"], o["late_orders"], o["feb_mar_late_orders"]), headline

stage = con.execute("""
SELECT SUM(late::INTEGER) AS late_stage,
       SUM(CASE WHEN slack_days < 0 AND late THEN 1 ELSE 0 END) AS breached_late,
       SUM(CASE WHEN slack_days BETWEEN 0 AND 3 THEN 1 ELSE 0 END) AS warning_orders,
       SUM(CASE WHEN slack_days BETWEEN 0 AND 3 AND late THEN 1 ELSE 0 END) AS warning_late,
       SUM(CASE WHEN slack_days > 14 AND late THEN 1 ELSE 0 END) AS long_slack_late
FROM cohort_orders
WHERE order_status = 'delivered'
  AND order_delivered_customer_date IS NOT NULL
  AND order_estimated_delivery_date IS NOT NULL
  AND order_delivered_carrier_date IS NOT NULL
  AND CAST(order_delivered_carrier_date AS TIMESTAMP) >= CAST(order_purchase_timestamp AS TIMESTAMP)
  AND CAST(order_delivered_customer_date AS TIMESTAMP) >= CAST(order_delivered_carrier_date AS TIMESTAMP)
  AND CAST(order_estimated_delivery_date AS TIMESTAMP) >= CAST(order_purchase_timestamp AS TIMESTAMP)
""").fetchone()
assert stage[:4] == (
    o["late_stage_eligible"], o["late_already_past_promise_at_handoff"],
    o["prebreach_alert_orders"], o["prebreach_alert_late_orders"],
), stage
assert abs(stage[3] / stage[2] - o["prebreach_alert_precision"]) < 1e-12
assert abs(stage[3] / stage[0] - o["prebreach_alert_capture"]) < 1e-12
assert abs(stage[4] / stage[0] - o["long_slack_late_share"]) < 1e-12
assert not (
    con.execute("""
      SELECT COUNT(*) FROM cohort_orders
      WHERE slack_days < 0 AND slack_days BETWEEN 0 AND 3
    """).fetchone()[0]
), "Breached and warning populations must be mutually exclusive"

seller = con.execute("""
WITH item_rollup AS (
  SELECT order_id, COUNT(DISTINCT seller_id) AS seller_count,
         MAX(CAST(shipping_limit_date AS TIMESTAMP)) AS last_shipping_limit
  FROM read_csv_auto('data/raw/olist_order_items_dataset.csv') GROUP BY order_id
), eligible AS (
  SELECT o.late, COALESCE(CAST(o.order_delivered_carrier_date AS TIMESTAMP) > i.last_shipping_limit, FALSE) AS after_limit
  FROM cohort_orders o JOIN item_rollup i USING(order_id)
  WHERE o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL
    AND o.order_estimated_delivery_date IS NOT NULL AND i.seller_count=1
)
SELECT COUNT(*), SUM(after_limit::INTEGER),
       AVG(CASE WHEN after_limit THEN late::INTEGER END),
       AVG(CASE WHEN NOT after_limit THEN late::INTEGER END)
FROM eligible
""").fetchone()
assert seller[0] == o["single_seller_orders"]
assert seller[1] == o["single_seller_after_shipping_limit"]
assert abs(seller[2] - o["single_seller_after_limit_late_rate"]) < 1e-12
assert abs(seller[3] - o["single_seller_within_limit_late_rate"]) < 1e-12

review = con.execute("""
WITH review_rollup AS (
  SELECT order_id, AVG(review_score) AS review_score
  FROM read_csv_auto('data/raw/olist_order_reviews_dataset.csv') GROUP BY order_id
), eligible AS (
  SELECT o.order_id, c.customer_state,
         strftime(CAST(o.order_purchase_timestamp AS TIMESTAMP), '%Y-%m') AS month,
         o.late, r.review_score <= 2 AS low_review
  FROM cohort_orders o
  JOIN read_csv_auto('data/raw/olist_customers_dataset.csv') c USING(customer_id)
  JOIN review_rollup r USING(order_id)
  WHERE o.order_status='delivered' AND o.order_delivered_customer_date IS NOT NULL
    AND o.order_estimated_delivery_date IS NOT NULL
), strata AS (
  SELECT customer_state, month, late, COUNT(*) AS n, SUM(low_review::INTEGER) AS low_count
  FROM eligible GROUP BY customer_state, month, late
), support AS (
  SELECT a.customer_state, a.month, a.n AS on_n, a.low_count AS on_low,
         b.n AS late_n, b.low_count AS late_low, a.n+b.n AS weight
  FROM strata a JOIN strata b USING(customer_state, month)
  WHERE a.late=FALSE AND b.late=TRUE AND a.n>=10 AND b.n>=10
)
SELECT SUM(on_n)+SUM(late_n) AS support_n,
       SUM(weight * on_low/on_n) / SUM(weight) AS on_rate,
       SUM(weight * late_low/late_n) / SUM(weight) AS late_rate,
       COUNT(*) AS strata
FROM support
""").fetchone()
assert review[0] == o["review_standardization_orders"]
assert abs(review[1] - o["low_review_standardized_on_time"]) < 1e-12
assert abs(review[2] - o["low_review_standardized_late"]) < 1e-12
assert review[3] == o["review_standardization_strata"]

monthly = pd.read_csv(OUT / "monthly.csv")
promise = pd.read_csv(OUT / "promise.csv")
slack = pd.read_csv(OUT / "slack.csv")
states = pd.read_csv(OUT / "state_adjusted.csv")
reviews = pd.read_csv(OUT / "reviews.csv")
assert monthly.orders.sum() == o["orders"] and monthly.late_orders.sum() == o["late_orders"]
assert promise.orders.sum() == o["orders"]
assert slack.orders.sum() == o["orders"] - q["delivered_missing_carrier"] - q["invalid_stage_order"]
assert slack.late_orders.sum() == o["late_stage_eligible"]
assert promise.promise_band.tolist() == ["≤7", "8–14", "15–21", "22–30", ">30"]
assert (states.excess_ci_low <= states.excess_late_orders).all()
assert (states.excess_ci_high >= states.excess_late_orders).all()
assert reviews.n_common_support.sum() == o["review_standardization_orders"]
assert o["low_review_difference_ci_low"] <= o["low_review_difference"] <= o["low_review_difference_ci_high"]

print("Validated headline, stage, seller, review, uncertainty, and output reconciliations.")
