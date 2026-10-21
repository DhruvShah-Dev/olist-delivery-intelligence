"""Rebuild the Olist delivery case study from the source CSVs.

Run from the repository root: python analyze.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)


def read(name: str, dates: list[str] | None = None) -> pd.DataFrame:
    return pd.read_csv(RAW / name, parse_dates=dates or [])


orders = read("olist_orders_dataset.csv", [
    "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
    "order_delivered_customer_date", "order_estimated_delivery_date",
])
items = read("olist_order_items_dataset.csv", ["shipping_limit_date"])
customers = read("olist_customers_dataset.csv")
reviews = read("olist_order_reviews_dataset.csv")
products = read("olist_products_dataset.csv")

assert orders.order_id.is_unique
assert customers.customer_id.is_unique
assert not items.duplicated(["order_id", "order_item_id"]).any()

item_agg = items.groupby("order_id").agg(
    item_count=("order_item_id", "size"),
    seller_count=("seller_id", "nunique"),
    seller_id=("seller_id", "first"),
    item_value=("price", "sum"),
    freight_value=("freight_value", "sum"),
    last_shipping_limit=("shipping_limit_date", "max"),
).reset_index()
rev_agg = reviews.groupby("order_id").agg(review_score=("review_score", "mean"), review_count=("review_score", "size")).reset_index()

df = (orders.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left", validate="many_to_one")
      .merge(item_agg, on="order_id", how="left", validate="one_to_one")
      .merge(rev_agg, on="order_id", how="left", validate="one_to_one"))
assert len(df) == len(orders)

# Mature purchase cohort: each promise had at least 60 days to resolve by the
# last observed customer delivery. This avoids counting still-open recent orders
# as if they were on time or lost. It is an observational cohort, not a live SLA.
last_delivery = df.order_delivered_customer_date.max()
cutoff = min(pd.Timestamp("2018-08-31 23:59:59"), last_delivery - pd.Timedelta(days=60))
cohort = df.loc[(df.order_purchase_timestamp >= "2017-01-01") & (df.order_purchase_timestamp <= cutoff)].copy()
delivered = cohort.loc[cohort.order_status.eq("delivered") & cohort.order_delivered_customer_date.notna() & cohort.order_estimated_delivery_date.notna()].copy()

for name, end, start in [
    ("promise_days", "order_estimated_delivery_date", "order_purchase_timestamp"),
    ("actual_days", "order_delivered_customer_date", "order_purchase_timestamp"),
    ("handoff_days", "order_delivered_carrier_date", "order_purchase_timestamp"),
    ("transit_days", "order_delivered_customer_date", "order_delivered_carrier_date"),
    ("remaining_at_handoff_days", "order_estimated_delivery_date", "order_delivered_carrier_date"),
]:
    delivered[name] = (delivered[end] - delivered[start]).dt.total_seconds() / 86400

# Published promise is a calendar date. Same-day arrivals count as on time.
delivered["late"] = delivered.order_delivered_customer_date.dt.normalize() > delivered.order_estimated_delivery_date.dt.normalize()
delivered["late_days"] = (delivered.order_delivered_customer_date.dt.normalize() - delivered.order_estimated_delivery_date.dt.normalize()).dt.days.clip(lower=0)
delivered["handoff_after_promise"] = delivered.order_delivered_carrier_date.dt.normalize() > delivered.order_estimated_delivery_date.dt.normalize()
delivered["month"] = delivered.order_purchase_timestamp.dt.to_period("M").astype(str)
delivered["promise_band"] = pd.cut(delivered.promise_days, [-np.inf, 7, 14, 21, 30, np.inf], labels=["≤7", "8–14", "15–21", "22–30", ">30"])

valid_stages = delivered.loc[delivered.handoff_days.ge(0) & delivered.transit_days.ge(0) & delivered.promise_days.ge(0)].copy()
late_stages = valid_stages.loc[valid_stages.late].copy()
late_stages["handoff_share"] = late_stages.handoff_days / late_stages.actual_days
valid_stages["handoff_slack_calendar_days"] = (valid_stages.order_estimated_delivery_date.dt.normalize() - valid_stages.order_delivered_carrier_date.dt.normalize()).dt.days
valid_stages["handoff_slack_band"] = pd.cut(valid_stages.handoff_slack_calendar_days, [-np.inf, -0.1, 3, 7, 14, np.inf], labels=["past promise", "0–3 days", "4–7 days", "8–14 days", ">14 days"])

def summary(g: pd.DataFrame) -> dict:
    return {
        "orders": int(len(g)),
        "late_orders": int(g.late.sum()),
        "late_rate": float(g.late.mean()) if len(g) else None,
        "median_promise_days": float(g.promise_days.median()) if len(g) else None,
        "median_actual_days": float(g.actual_days.median()) if len(g) else None,
        "p90_actual_days": float(g.actual_days.quantile(.9)) if len(g) else None,
        "mean_review": float(g.review_score.mean()) if len(g) else None,
    }

def grouped(key: str, min_n=0):
    rows = [{key: str(k), **summary(g)} for k, g in delivered.groupby(key, observed=True) if len(g) >= min_n]
    return sorted(rows, key=lambda x: x["orders"], reverse=True)

monthly = grouped("month")
state = grouped("customer_state", 100)
promise = grouped("promise_band")
slack = [{"handoff_slack_band": str(k), **summary(g)} for k, g in valid_stages.groupby("handoff_slack_band", observed=True)]

# Geographic comparison standardized to a common month × promise-band mix.
# Compare each state's observed late count to its expected count at the pooled
# rate in those same strata. This is descriptive risk adjustment, not causal.
pool = delivered.groupby(["month", "promise_band"], observed=True).late.agg(["size", "sum"]).reset_index()
pool["rate"] = pool["sum"] / pool["size"]
state_strata = delivered.groupby(["customer_state", "month", "promise_band"], observed=True).late.agg(["size", "sum"]).reset_index()
state_strata = state_strata.merge(pool[["month", "promise_band", "rate"]], on=["month", "promise_band"], how="left")
state_strata["expected"] = state_strata["size"] * state_strata["rate"]
state_adj = state_strata.groupby("customer_state").agg(orders=("size", "sum"), observed=("sum", "sum"), expected=("expected", "sum")).reset_index()
state_adj = state_adj.loc[state_adj.orders >= 1000].copy()
state_adj["observed_expected_ratio"] = state_adj.observed / state_adj.expected
state_adj = state_adj.sort_values("observed", ascending=False)

# Seller accountability is restricted to one-seller orders. These rankings are
# descriptive, not causal: route and product mix may differ among sellers.
seller_orders = delivered.loc[delivered.seller_count.eq(1)].copy()
seller_orders["after_shipping_limit"] = seller_orders.order_delivered_carrier_date.dt.normalize() > seller_orders.last_shipping_limit.dt.normalize()
seller = seller_orders.groupby("seller_id").agg(orders=("order_id", "size"), late_orders=("late", "sum"), late_rate=("late", "mean"), median_handoff_days=("handoff_days", "median")).reset_index()
seller = seller.loc[seller.orders >= 100].sort_values(["late_orders", "orders"], ascending=False)

# Item category is not an order-level property for mixed-category baskets;
# use only orders whose items share one product category.
item_category = items[["order_id", "product_id"]].merge(products[["product_id", "product_category_name"]], on="product_id", how="left", validate="many_to_one")
category_counts = item_category.groupby("order_id").product_category_name.nunique(dropna=True)
one_cat_ids = category_counts.loc[category_counts.eq(1)].index
cat = item_category.loc[item_category.order_id.isin(one_cat_ids)].drop_duplicates("order_id")[["order_id", "product_category_name"]]
category_orders = delivered.merge(cat, on="order_id", how="inner", validate="one_to_one")
category = (category_orders.groupby("product_category_name")
            .agg(orders=("order_id", "size"), late_orders=("late", "sum"), late_rate=("late", "mean"))
            .reset_index().query("orders >= 200").sort_values("late_orders", ascending=False))

# Review comparison standardized over customer-state × purchase-month strata.
# This reduces obvious geography/season mix imbalance but cannot remove all
# confounding (product, service, and unmeasured expectations remain).
reviewed = delivered.loc[delivered.review_score.notna() & delivered.customer_state.notna()].copy()
reviewed["low_review"] = reviewed.review_score.le(2)
strata = reviewed.groupby(["customer_state", "month", "late"]).agg(n=("order_id", "size"), low=("low_review", "mean")).reset_index()
pivot = strata.pivot(index=["customer_state", "month"], columns="late", values=["n", "low"]).dropna()
pivot = pivot.loc[(pivot[("n", False)] >= 10) & (pivot[("n", True)] >= 10)]
weights = pivot[("n", False)] + pivot[("n", True)]
std_on = float(np.average(pivot[("low", False)], weights=weights))
std_late = float(np.average(pivot[("low", True)], weights=weights))

quality = {
    "source_orders": len(orders), "source_items": len(items), "source_reviews": len(reviews),
    "cohort_orders": len(cohort), "delivered_eligible": len(delivered),
    "delivered_missing_carrier": int(delivered.order_delivered_carrier_date.isna().sum()),
    "invalid_stage_order": int((delivered.handoff_days.lt(0) | delivered.transit_days.lt(0)).sum()),
    "multiple_seller_orders": int(delivered.seller_count.gt(1).sum()),
    "review_coverage": float(delivered.review_score.notna().mean()),
    "last_observed_delivery": str(last_delivery), "purchase_cutoff": str(cutoff),
    "cohort_statuses": {str(k): int(v) for k, v in cohort.order_status.value_counts().items()},
    "delivered_missing_promise": int((cohort.order_status.eq("delivered") & cohort.order_estimated_delivery_date.isna()).sum()),
    "delivered_missing_customer_date": int((cohort.order_status.eq("delivered") & cohort.order_delivered_customer_date.isna()).sum()),
}
overall = summary(delivered)
overall.update({
    "median_handoff_days": float(valid_stages.handoff_days.median()),
    "median_transit_days": float(valid_stages.transit_days.median()),
    "late_stage_eligible": len(late_stages),
    "late_already_past_promise_at_handoff": int(late_stages.handoff_after_promise.sum()),
    "late_already_past_promise_share": float(late_stages.handoff_after_promise.mean()),
    "late_median_handoff_share_of_actual": float(late_stages.handoff_share.median()),
    "late_over_7_days_share": float(late_stages.late_days.gt(7).mean()),
    "short_slack_orders": int(valid_stages.handoff_slack_calendar_days.le(3).sum()),
    "short_slack_late_orders": int(valid_stages.loc[valid_stages.handoff_slack_calendar_days.le(3), "late"].sum()),
    "short_slack_late_rate": float(valid_stages.loc[valid_stages.handoff_slack_calendar_days.le(3), "late"].mean()),
    "short_slack_late_capture": float(valid_stages.loc[valid_stages.handoff_slack_calendar_days.le(3), "late"].sum() / late_stages.shape[0]),
    "long_slack_late_share": float(valid_stages.loc[valid_stages.handoff_slack_calendar_days.gt(14), "late"].sum() / late_stages.shape[0]),
    "feb_mar_orders": int(delivered.month.isin(["2018-02", "2018-03"]).sum()),
    "feb_mar_late_orders": int(delivered.loc[delivered.month.isin(["2018-02", "2018-03"]), "late"].sum()),
    "other_months_late_rate": float(delivered.loc[~delivered.month.isin(["2018-02", "2018-03"]), "late"].mean()),
    "single_seller_orders": len(seller_orders),
    "single_seller_after_shipping_limit": int(seller_orders.after_shipping_limit.sum()),
    "single_seller_after_limit_late_rate": float(seller_orders.loc[seller_orders.after_shipping_limit, "late"].mean()),
    "single_seller_within_limit_late_rate": float(seller_orders.loc[~seller_orders.after_shipping_limit, "late"].mean()),
    "reviewed_orders": len(reviewed),
    "low_review_on_time": float(reviewed.loc[~reviewed.late, "low_review"].mean()),
    "low_review_late": float(reviewed.loc[reviewed.late, "low_review"].mean()),
    "low_review_standardized_on_time": std_on,
    "low_review_standardized_late": std_late,
    "review_standardization_strata": len(pivot),
    "review_standardization_orders": int(weights.sum()),
})

for name, rows in [("monthly", monthly), ("state", state), ("promise", promise), ("slack", slack)]:
    pd.DataFrame(rows).to_csv(OUT / f"{name}.csv", index=False)
state_adj.to_csv(OUT / "state_adjusted.csv", index=False)
seller.to_csv(OUT / "seller.csv", index=False)
category.to_csv(OUT / "category.csv", index=False)
delivered[["order_id", "month", "customer_state", "seller_count", "promise_days", "actual_days", "handoff_days", "transit_days", "late", "late_days", "review_score"]].to_csv(OUT / "delivery_orders.csv", index=False)
(OUT / "findings.json").write_text(json.dumps({"quality": quality, "overall": overall, "monthly": monthly, "state": state, "promise": promise, "slack": slack}, indent=2), encoding="utf-8")
print(json.dumps({"quality": quality, "overall": overall}, indent=2))
