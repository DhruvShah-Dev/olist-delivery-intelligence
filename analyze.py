"""Rebuild the corrected Olist shareholder delivery analysis."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from verify_source import verify_sources


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

PURCHASE_START = pd.Timestamp("2017-01-01 00:00:00")
PURCHASE_CUTOFF = pd.Timestamp("2018-08-18 13:22:46")
OBSERVATION_END = pd.Timestamp("2018-10-17 13:22:46")
BOOTSTRAP_REPS = 1_000
RNG_SEED = 20261105

verify_sources()


def read(name: str, dates: list[str] | None = None) -> pd.DataFrame:
    return pd.read_csv(RAW / name, parse_dates=dates or [])


def summarize(group: pd.DataFrame) -> dict:
    return {
        "orders": int(len(group)),
        "late_orders": int(group.late.sum()),
        "late_rate": float(group.late.mean()) if len(group) else None,
        "median_promise_days": float(group.promise_days.median()) if len(group) else None,
        "median_actual_days": float(group.actual_days.median()) if len(group) else None,
        "p90_actual_days": float(group.actual_days.quantile(0.9)) if len(group) else None,
        "mean_review": float(group.review_score.mean()) if len(group) else None,
    }


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
    item_count=("order_item_id", "size"), seller_count=("seller_id", "nunique"),
    seller_id=("seller_id", "first"), item_value=("price", "sum"),
    freight_value=("freight_value", "sum"), last_shipping_limit=("shipping_limit_date", "max"),
).reset_index()
review_agg = reviews.groupby("order_id").agg(
    review_score=("review_score", "mean"), review_count=("review_score", "size")
).reset_index()

df = (orders.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left", validate="many_to_one")
      .merge(item_agg, on="order_id", how="left", validate="one_to_one")
      .merge(review_agg, on="order_id", how="left", validate="one_to_one"))
assert len(df) == len(orders)

# The headline is a completed-delivery rate in a fixed purchase window. Promise
# maturity sensitivity is reported separately so it is not misdescribed as a
# per-order 60-day observation rule.
cohort = df.loc[df.order_purchase_timestamp.between(PURCHASE_START, PURCHASE_CUTOFF)].copy()
delivered = cohort.loc[
    cohort.order_status.eq("delivered")
    & cohort.order_delivered_customer_date.notna()
    & cohort.order_estimated_delivery_date.notna()
].copy()

for name, end, start in [
    ("promise_days", "order_estimated_delivery_date", "order_purchase_timestamp"),
    ("actual_days", "order_delivered_customer_date", "order_purchase_timestamp"),
    ("handoff_days", "order_delivered_carrier_date", "order_purchase_timestamp"),
    ("transit_days", "order_delivered_customer_date", "order_delivered_carrier_date"),
]:
    delivered[name] = (delivered[end] - delivered[start]).dt.total_seconds() / 86400

delivered["late"] = (delivered.order_delivered_customer_date.dt.normalize()
                     > delivered.order_estimated_delivery_date.dt.normalize())
delivered["late_days"] = (delivered.order_delivered_customer_date.dt.normalize()
                          - delivered.order_estimated_delivery_date.dt.normalize()).dt.days.clip(lower=0)
delivered["month"] = delivered.order_purchase_timestamp.dt.to_period("M").astype(str)
delivered["handoff_slack_calendar_days"] = (
    delivered.order_estimated_delivery_date.dt.normalize()
    - delivered.order_delivered_carrier_date.dt.normalize()).dt.days
delivered["handoff_slack_band"] = np.select([
    delivered.handoff_slack_calendar_days.lt(0),
    delivered.handoff_slack_calendar_days.between(0, 3),
    delivered.handoff_slack_calendar_days.between(4, 7),
    delivered.handoff_slack_calendar_days.between(8, 14),
], ["past promise", "0–3 days", "4–7 days", "8–14 days"], default=">14 days")
delivered["promise_band"] = pd.cut(
    delivered.promise_days, [-np.inf, 7, 14, 21, 30, np.inf],
    labels=["≤7", "8–14", "15–21", "22–30", ">30"],
)

valid_stages = delivered.loc[
    delivered.handoff_days.ge(0) & delivered.transit_days.ge(0)
    & delivered.promise_days.ge(0) & delivered.order_delivered_carrier_date.notna()
].copy()
late_stages = valid_stages.loc[valid_stages.late].copy()

monthly = []
for month, group in delivered.groupby("month", observed=True):
    row = {"month": str(month), **summarize(group)}
    row["incident_label"] = (
        "November 2017 spike" if month == "2017-11" else
        "February–March 2018 concentration" if month in {"2018-02", "2018-03"} else ""
    )
    monthly.append(row)
monthly.sort(key=lambda row: row["month"])

state = [{"customer_state": str(key), **summarize(group)}
         for key, group in delivered.groupby("customer_state", observed=True) if len(group) >= 100]
state.sort(key=lambda row: row["orders"], reverse=True)

promise_order = ["≤7", "8–14", "15–21", "22–30", ">30"]
promise = [{"promise_band": str(key), **summarize(group)}
           for key, group in delivered.groupby("promise_band", observed=True)]
promise.sort(key=lambda row: promise_order.index(row["promise_band"]))

slack_order = ["past promise", "0–3 days", "4–7 days", "8–14 days", ">14 days"]
slack, cumulative_late = [], 0
for band in slack_order:
    group = valid_stages.loc[valid_stages.handoff_slack_band.eq(band)]
    row = {"handoff_slack_band": band, **summarize(group)}
    row["share_of_all_late"] = float(row["late_orders"] / len(late_stages))
    cumulative_late += row["late_orders"]
    row["cumulative_capture"] = float(cumulative_late / len(late_stages))
    row["eligibility_state"] = "breached" if band == "past promise" else "pre-breach"
    slack.append(row)

# State adjustment and stratified order bootstrap.
pool = delivered.groupby(["month", "promise_band"], observed=True).late.agg(["size", "sum"]).reset_index()
pool["rate"] = pool["sum"] / pool["size"]
state_strata = delivered.groupby(
    ["customer_state", "month", "promise_band"], observed=True
).late.agg(["size", "sum"]).reset_index()
state_strata = state_strata.merge(pool[["month", "promise_band", "rate"]],
                                  on=["month", "promise_band"], how="left")
state_strata["expected"] = state_strata["size"] * state_strata["rate"]
state_adj = state_strata.groupby("customer_state").agg(
    orders=("size", "sum"), observed=("sum", "sum"), expected=("expected", "sum")
).reset_index()
state_adj = state_adj.loc[state_adj.orders.ge(1_000)].copy()
state_adj["observed_expected_ratio"] = state_adj.observed / state_adj.expected
state_adj["excess_late_orders"] = state_adj.observed - state_adj.expected

rng = np.random.default_rng(RNG_SEED)
state_codes, state_labels = pd.factorize(state_strata.customer_state, sort=True)
pool_codes, _ = pd.factorize(state_strata.month.astype(str) + "|" + state_strata.promise_band.astype(str), sort=True)
cell_n = state_strata["size"].to_numpy(dtype=int)
cell_p = (state_strata["sum"] / state_strata["size"]).to_numpy(dtype=float)
pool_n = np.bincount(pool_codes, weights=cell_n)
boot_excess = np.empty((BOOTSTRAP_REPS, len(state_labels)))
boot_ratio = np.empty_like(boot_excess)
for rep in range(BOOTSTRAP_REPS):
    late_draw = rng.binomial(cell_n, cell_p)
    observed_draw = np.bincount(state_codes, weights=late_draw, minlength=len(state_labels))
    pool_late = np.bincount(pool_codes, weights=late_draw, minlength=len(pool_n))
    pool_rate = np.divide(pool_late, pool_n, out=np.zeros_like(pool_late), where=pool_n > 0)
    expected_draw = np.bincount(state_codes, weights=cell_n * pool_rate[pool_codes], minlength=len(state_labels))
    boot_excess[rep] = observed_draw - expected_draw
    boot_ratio[rep] = np.divide(observed_draw, expected_draw,
                                out=np.full_like(observed_draw, np.nan), where=expected_draw > 0)
positions = {value: idx for idx, value in enumerate(state_labels)}
for target, source in [("excess_ci_low", boot_excess), ("ratio_ci_low", boot_ratio)]:
    high = target.replace("_low", "_high")
    state_adj[target] = state_adj.customer_state.map(
        lambda value: float(np.nanquantile(source[:, positions[value]], 0.025)))
    state_adj[high] = state_adj.customer_state.map(
        lambda value: float(np.nanquantile(source[:, positions[value]], 0.975)))
state_adj.sort_values("excess_late_orders", ascending=False, inplace=True)

# Exact timestamp comparison fixes same-calendar-day deadline misclassification.
seller_orders = delivered.loc[delivered.seller_count.eq(1)].copy()
seller_orders["after_shipping_limit"] = (
    seller_orders.order_delivered_carrier_date > seller_orders.last_shipping_limit)
seller = seller_orders.groupby("seller_id").agg(
    orders=("order_id", "size"), late_orders=("late", "sum"),
    late_rate=("late", "mean"), median_handoff_days=("handoff_days", "median")
).reset_index()
seller = seller.loc[seller.orders.ge(100)].sort_values(["late_orders", "orders"], ascending=False)

# Keep category output for the diagnostic appendix.
item_category = items[["order_id", "product_id"]].merge(
    products[["product_id", "product_category_name"]], on="product_id", how="left", validate="many_to_one")
one_category_ids = item_category.groupby("order_id").product_category_name.nunique(dropna=True).loc[lambda s: s.eq(1)].index
category_lookup = item_category.loc[item_category.order_id.isin(one_category_ids)].drop_duplicates("order_id")[["order_id", "product_category_name"]]
category_orders = delivered.merge(category_lookup, on="order_id", how="inner", validate="one_to_one")
category = category_orders.groupby("product_category_name").agg(
    orders=("order_id", "size"), late_orders=("late", "sum"), late_rate=("late", "mean")
).reset_index().query("orders >= 200").sort_values("late_orders", ascending=False)

# Review standardization with explicit common-support coverage and uncertainty.
reviewed = delivered.loc[delivered.review_score.notna() & delivered.customer_state.notna()].copy()
reviewed["low_review"] = reviewed.review_score.le(2)
review_strata = reviewed.groupby(["customer_state", "month", "late"]).agg(
    n=("order_id", "size"), low_count=("low_review", "sum")).reset_index()
review_pivot = review_strata.pivot(index=["customer_state", "month"], columns="late",
                                   values=["n", "low_count"]).dropna()
review_pivot = review_pivot.loc[
    review_pivot[("n", False)].ge(10) & review_pivot[("n", True)].ge(10)]
review_weights = review_pivot[("n", False)] + review_pivot[("n", True)]
on_rate = review_pivot[("low_count", False)] / review_pivot[("n", False)]
late_rate = review_pivot[("low_count", True)] / review_pivot[("n", True)]
std_on = float(np.average(on_rate, weights=review_weights))
std_late = float(np.average(late_rate, weights=review_weights))
on_n, late_n = review_pivot[("n", False)].to_numpy(int), review_pivot[("n", True)].to_numpy(int)
on_p, late_p = on_rate.to_numpy(float), late_rate.to_numpy(float)
weights_array = review_weights.to_numpy(float)
boot_on, boot_late = np.empty(BOOTSTRAP_REPS), np.empty(BOOTSTRAP_REPS)
for rep in range(BOOTSTRAP_REPS):
    boot_on[rep] = np.average(rng.binomial(on_n, on_p) / on_n, weights=weights_array)
    boot_late[rep] = np.average(rng.binomial(late_n, late_p) / late_n, weights=weights_array)
reviewed_total = reviewed.groupby("late").size()
delivered_total = delivered.groupby("late").size()
common_support = {False: int(on_n.sum()), True: int(late_n.sum())}
review_rows = []
for outcome, label, rate, draws in [
    (False, "On time", std_on, boot_on), (True, "Late", std_late, boot_late)]:
    review_rows.append({
        "group": label, "low_review_rate": rate,
        "ci_low": float(np.quantile(draws, 0.025)),
        "ci_high": float(np.quantile(draws, 0.975)),
        "n_common_support": common_support[outcome],
        "n_reviewed_total": int(reviewed_total[outcome]),
        "review_coverage": float(reviewed_total[outcome] / delivered_total[outcome]),
        "common_support_share": float(common_support[outcome] / reviewed_total[outcome]),
    })

maturity_sensitivity = {
    f"promise_plus_{grace}_days": int(
        (delivered.order_estimated_delivery_date + pd.Timedelta(days=grace) <= OBSERVATION_END).sum())
    for grace in [0, 7, 14, 30, 60]
}
quality = {
    "source_orders": len(orders), "source_items": len(items), "source_reviews": len(reviews),
    "cohort_orders": len(cohort), "delivered_eligible": len(delivered),
    "delivered_missing_carrier": int(delivered.order_delivered_carrier_date.isna().sum()),
    "invalid_stage_order": int((delivered.handoff_days.lt(0) | delivered.transit_days.lt(0)).sum()),
    "multiple_seller_orders": int(delivered.seller_count.gt(1).sum()),
    "review_coverage": float(delivered.review_score.notna().mean()),
    "observation_end": OBSERVATION_END.isoformat(), "purchase_start": PURCHASE_START.isoformat(),
    "purchase_cutoff": PURCHASE_CUTOFF.isoformat(), "maturity_sensitivity": maturity_sensitivity,
    "cohort_statuses": {str(k): int(v) for k, v in cohort.order_status.value_counts().items()},
    "delivered_missing_promise": int((cohort.order_status.eq("delivered") & cohort.order_estimated_delivery_date.isna()).sum()),
    "delivered_missing_customer_date": int((cohort.order_status.eq("delivered") & cohort.order_delivered_customer_date.isna()).sum()),
}

overall = summarize(delivered)
prebreach = valid_stages.handoff_slack_calendar_days.between(0, 3)
breached = valid_stages.handoff_slack_calendar_days.lt(0)
overall.update({
    "median_handoff_days": float(valid_stages.handoff_days.median()),
    "median_transit_days": float(valid_stages.transit_days.median()),
    "late_stage_eligible": len(late_stages),
    "late_already_past_promise_at_handoff": int(valid_stages.loc[breached, "late"].sum()),
    "late_already_past_promise_share": float(valid_stages.loc[breached, "late"].sum() / len(late_stages)),
    "prebreach_alert_orders": int(prebreach.sum()),
    "prebreach_alert_late_orders": int(valid_stages.loc[prebreach, "late"].sum()),
    "prebreach_alert_precision": float(valid_stages.loc[prebreach, "late"].mean()),
    "prebreach_alert_capture": float(valid_stages.loc[prebreach, "late"].sum() / len(late_stages)),
    "long_slack_late_share": float(valid_stages.loc[valid_stages.handoff_slack_calendar_days.gt(14), "late"].sum() / len(late_stages)),
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
    "low_review_difference": std_late - std_on,
    "low_review_difference_ci_low": float(np.quantile(boot_late - boot_on, 0.025)),
    "low_review_difference_ci_high": float(np.quantile(boot_late - boot_on, 0.975)),
    "review_standardization_strata": len(review_pivot),
    "review_standardization_orders": int(review_weights.sum()),
    "review_common_support_share": float(review_weights.sum() / len(reviewed)),
})
# Compatibility fields now use the corrected pre-breach population.
overall.update({
    "short_slack_orders": overall["prebreach_alert_orders"],
    "short_slack_late_orders": overall["prebreach_alert_late_orders"],
    "short_slack_late_rate": overall["prebreach_alert_precision"],
    "short_slack_late_capture": overall["prebreach_alert_capture"],
})

status_context = cohort.order_status.value_counts().rename_axis("status").reset_index(name="orders")
status_context["share_of_cohort"] = status_context.orders / len(cohort)
for name, rows in [("monthly", monthly), ("state", state), ("promise", promise), ("slack", slack)]:
    pd.DataFrame(rows).to_csv(OUT / f"{name}.csv", index=False)
state_adj.to_csv(OUT / "state_adjusted.csv", index=False)
pd.DataFrame(review_rows).to_csv(OUT / "reviews.csv", index=False)
status_context.to_csv(OUT / "status_context.csv", index=False)
seller.to_csv(OUT / "seller.csv", index=False)
category.to_csv(OUT / "category.csv", index=False)
delivered[[
    "order_id", "month", "customer_state", "seller_count", "promise_days", "actual_days",
    "handoff_days", "transit_days", "handoff_slack_calendar_days", "handoff_slack_band",
    "late", "late_days", "review_score",
]].to_csv(OUT / "delivery_orders.csv", index=False)

source_manifest = json.loads((ROOT / "data" / "source_manifest.json").read_text(encoding="utf-8"))
analysis_version = "shareholder-story-v2"
run_id = hashlib.sha256(json.dumps({
    "analysis_version": analysis_version, "source_manifest": source_manifest,
}, sort_keys=True).encode("utf-8")).hexdigest()[:16]
build_metadata = {
    "analysis_version": analysis_version, "build_id": run_id,
    "source_manifest": "data/source_manifest.json",
    "purchase_window": [PURCHASE_START.isoformat(), PURCHASE_CUTOFF.isoformat()],
    "observation_end": OBSERVATION_END.isoformat(),
    "bootstrap_replicates": BOOTSTRAP_REPS, "bootstrap_seed": RNG_SEED,
}
(OUT / "build_metadata.json").write_text(json.dumps(build_metadata, indent=2), encoding="utf-8")
(OUT / "findings.json").write_text(json.dumps({
    "build": build_metadata, "quality": quality, "overall": overall,
    "monthly": monthly, "state": state, "promise": promise, "slack": slack,
    "state_adjusted": state_adj.to_dict("records"), "reviews": review_rows,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"build": build_metadata, "quality": quality, "overall": overall}, indent=2))
