"""Independent SQL spot checks against source CSVs and analysis outputs."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
from verify_source import verify_sources

ROOT = Path(__file__).resolve().parent
verify_sources()
HERE = Path(__file__).resolve().parent
findings = json.loads((HERE / "outputs" / "findings.json").read_text(encoding="utf-8"))
q = findings["quality"]
o = findings["overall"]

con = duckdb.connect()
rows = con.execute("""
    SELECT COUNT(*) AS orders,
           SUM(CASE WHEN CAST(order_delivered_customer_date AS DATE) > CAST(order_estimated_delivery_date AS DATE) THEN 1 ELSE 0 END) AS late_orders,
           SUM(CASE WHEN strftime(CAST(order_purchase_timestamp AS TIMESTAMP), '%Y-%m') IN ('2018-02', '2018-03')
                         AND CAST(order_delivered_customer_date AS DATE) > CAST(order_estimated_delivery_date AS DATE)
                    THEN 1 ELSE 0 END) AS feb_mar_late_orders
    FROM read_csv_auto('data/raw/olist_orders_dataset.csv')
    WHERE order_purchase_timestamp >= '2017-01-01'
      AND order_purchase_timestamp <= ?
      AND order_status = 'delivered'
      AND order_delivered_customer_date IS NOT NULL
      AND order_estimated_delivery_date IS NOT NULL
""", [q["purchase_cutoff"]]).fetchone()
assert rows == (o["orders"], o["late_orders"], o["feb_mar_late_orders"]), (rows, o)
assert sum(x["orders"] for x in findings["monthly"]) == o["orders"]
assert sum(x["late_orders"] for x in findings["monthly"]) == o["late_orders"]
assert sum(x["orders"] for x in findings["promise"]) == o["orders"]
assert o["late_already_past_promise_at_handoff"] <= o["late_stage_eligible"] <= o["late_orders"]
print("Independent SQL and aggregate reconciliation passed:", rows)
