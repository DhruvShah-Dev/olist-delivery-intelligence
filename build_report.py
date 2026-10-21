"""Create the canonical, source-backed portable report manifest."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
data = json.loads((OUT / "findings.json").read_text(encoding="utf-8"))
q, o = data["quality"], data["overall"]
now = datetime.now(timezone.utc).isoformat()


def pct(x, digits=1):
    return f"{100*x:.{digits}f}%"


def md(id, body, sourced=False):
    block = {"id": id, "type": "markdown", "body": body}
    if sourced:
        block["sourceId"] = "source_overall"
    return block


monthly = sorted(data["monthly"], key=lambda x: x["month"])
slack = data["slack"]
state_adj = pd.read_csv(OUT / "state_adjusted.csv").to_dict("records")
state_adj = sorted(state_adj, key=lambda x: x["observed_expected_ratio"], reverse=True)
promise = data["promise"]
reviews = [
    {"comparison": "Low reviews", "on_time": o["low_review_standardized_on_time"], "late": o["low_review_standardized_late"]},
]

pd.DataFrame([{**o, "feb_mar_late_share": o["feb_mar_late_orders"] / o["late_orders"]}]).to_csv(OUT / "overall.csv", index=False)
pd.DataFrame(reviews).to_csv(OUT / "reviews.csv", index=False)

query_files = {
    "overall": "overall.csv", "monthly": "monthly.csv", "slack": "slack.csv",
    "state_adjusted": "state_adjusted.csv", "promise": "promise.csv", "reviews": "reviews.csv",
}
queries = {key: f"SELECT * FROM read_csv_auto('outputs/{filename}')" for key, filename in query_files.items()}
queries["monthly"] = "SELECT *, 'All months' AS phase FROM read_csv_auto('outputs/monthly.csv') WHERE month < '2018-08' UNION ALL SELECT *, 'Feb–Mar 2018' AS phase FROM read_csv_auto('outputs/monthly.csv') WHERE month IN ('2018-02', '2018-03') ORDER BY month, phase"
queries["slack"] = f"SELECT *, {o['late_rate']} AS \"Cohort average\", late_rate AS \"Handoff window\" FROM read_csv_auto('outputs/slack.csv')"
queries["state_adjusted"] = "SELECT *, 1.0 - observed_expected_ratio AS performance_gap FROM read_csv_auto('outputs/state_adjusted.csv') ORDER BY observed_expected_ratio DESC"
queries["reviews"] = "SELECT comparison, on_time AS \"On time\", late AS \"Late\" FROM read_csv_auto('outputs/reviews.csv')"
conn = duckdb.connect()
datasets = {key: conn.execute(sql).df().where(lambda frame: pd.notna(frame), None).to_dict("records") for key, sql in queries.items()}

sources = [{
    "id": f"source_{key}",
    "label": f"Olist delivery analysis — {key.replace('_', ' ')}",
    "path": f"outputs/{filename}",
    "description": "Historical Olist orders transformed at order grain by analyze.py; purchase cohort January 2017–August 18, 2018.",
    "query": {"engine": "duckdb", "language": "sql", "sql": queries[key],
        "description": f"Loads the reviewed {key.replace('_', ' ')} extract.",
        "tables_used": [f"outputs/{filename}"],
        "filters": ["Purchases January 2017–August 18, 2018", "Delivered orders with actual and promised delivery dates"] + (["Monthly chart excludes partial August 2018"] if key == "monthly" else []),
        "metric_definitions": {"late_rate": "Delivered orders arriving after the estimated calendar date / eligible delivered orders.", "observed_expected_ratio": "Observed state late orders / expected state late orders from pooled month × promise-band rates.", "low_review_rate": "Orders with mean review score at most 2 / reviewed orders; standardized over comparable state × month strata."},
        "executed_at": now},
} for key, filename in query_files.items()]

cards = [
    {"id": "late_rate", "description": "Delivered orders that arrived after the promised calendar date.", "dataset": "overall", "sourceId": "source_overall", "metrics": [{"label": "Late deliveries", "field": "late_rate", "format": "percent"}]},
    {"id": "late_count", "description": "Eligible delivered orders arriving after the promised date.", "dataset": "overall", "sourceId": "source_overall", "metrics": [{"label": "Late orders", "field": "late_orders", "format": "number"}]},
    {"id": "feb_mar", "description": "Share of all late orders purchased in February and March 2018.", "dataset": "overall", "sourceId": "source_overall", "metrics": [{"label": "Late orders in Feb–Mar 2018", "field": "feb_mar_late_share", "format": "percent"}]},
]

charts = [
    {"id": "monthly", "title": "Monthly late-delivery rate", "subtitle": "Purchase month, January 2017–August 2018; August is a partial month", "type": "line", "dataset": "monthly", "sourceId": "source_monthly", "valueFormat": "percent", "encodings": {"x": {"field": "month", "type": "ordinal", "label": "Purchase month"}, "y": {"field": "late_rate", "type": "quantitative", "label": "Late rate"}, "tooltip": [{"field": "orders", "type": "quantitative", "label": "Delivered orders"}, {"field": "late_orders", "type": "quantitative", "label": "Late orders"}]}},
    {"id": "slack", "title": "Late rate by time left at carrier handoff", "subtitle": "Valid delivery stages; the time bands are measured against each order’s promise", "type": "bar", "dataset": "slack", "sourceId": "source_slack", "valueFormat": "percent", "encodings": {"x": {"field": "handoff_slack_band", "type": "ordinal", "label": "Time left at carrier handoff"}, "y": {"field": "late_rate", "type": "quantitative", "label": "Late rate"}, "tooltip": [{"field": "orders", "type": "quantitative", "label": "Orders"}]}},
    {"id": "state", "title": "Late deliveries versus expected by customer state", "subtitle": "Observed / expected after adjusting for purchase month and promise band; states with ≥1,000 orders", "type": "bar", "dataset": "state_adjusted", "sourceId": "source_state_adjusted", "valueFormat": "number", "encodings": {"x": {"field": "customer_state", "type": "nominal", "label": "Customer state"}, "y": {"field": "observed_expected_ratio", "type": "quantitative", "label": "Observed / expected"}, "tooltip": [{"field": "orders", "type": "quantitative", "label": "Orders"}, {"field": "observed", "type": "quantitative", "label": "Late orders"}, {"field": "expected", "type": "quantitative", "label": "Expected late orders"}]}},
    {"id": "reviews", "title": "Low review rate by delivery outcome", "subtitle": "State × month standardized; reviewed orders in comparable strata", "type": "bar", "dataset": "reviews", "sourceId": "source_reviews", "valueFormat": "percent", "encodings": {"x": {"field": "group", "type": "nominal", "label": "Delivery outcome"}, "y": {"field": "low_review_rate", "type": "quantitative", "label": "Low review rate"}}},
]

# Color is tied to the analytical role: amber marks late risk, blue is the
# on-time comparator, and the signed state gap uses semantic good/bad colors.
chart_by_id = {chart["id"]: chart for chart in charts}
chart_by_id["monthly"].update({
    "subtitle": "Complete purchase months, January 2017–July 2018; partial August excluded",
    "palette": {"kind": "categorical"},
    "referenceLines": [{"axis": "y", "value": o["late_rate"], "label": "Overall 6.9%", "color": "neutral", "lineStyle": "dashed"}],
})
chart_by_id["monthly"]["encodings"]["color"] = {"field": "phase", "type": "nominal", "label": "Period"}
chart_by_id["slack"].update({
    "type": "bar",
    "title": "Late risk by time left at carrier handoff",
    "subtitle": "Late rate compared with the 6.9% cohort average; valid delivery stages",
    "palette": {"kind": "categorical"},
    "settings": {"groupMode": "grouped", "sort": "none"},
})
chart_by_id["slack"]["encodings"]["y"] = {"fields": ["Cohort average", "Handoff window"], "type": "quantitative", "label": "Late rate"}
chart_by_id["state"].update({
    "title": "Late-delivery gap versus expected by customer state",
    "subtitle": "Positive means fewer late deliveries than expected; negative means more, after month and promise adjustment",
    "valueFormat": "percent",
    "palette": {"kind": "semantic"},
    "referenceLines": [{"axis": "y", "value": 0, "label": "Expected", "color": "neutral", "lineStyle": "dashed"}],
    "settings": {"sort": "none"},
})
chart_by_id["state"]["encodings"]["y"] = {"field": "performance_gap", "type": "quantitative", "label": "Fewer / more late than expected"}
chart_by_id["reviews"].update({
    "palette": {"kind": "categorical"},
    "labels": {"values": "all"},
    "settings": {"groupMode": "grouped"},
})
chart_by_id["reviews"]["encodings"] = {
    "x": {"field": "comparison", "type": "nominal", "label": "Reviewed orders"},
    "y": {"fields": ["On time", "Late"], "type": "quantitative", "label": "Low review rate"},
}

tables = [
    {"id": "promise", "title": "Promise-length cohorts", "subtitle": "Delivered orders by days promised from purchase", "dataset": "promise", "sourceId": "source_promise", "defaultSort": {"field": "orders", "direction": "desc"}, "columns": [{"field": "promise_band", "label": "Promised days", "type": "text"}, {"field": "orders", "label": "Orders", "format": "number"}, {"field": "late_rate", "label": "Late rate", "format": "percent"}, {"field": "median_actual_days", "label": "Median actual days", "format": "number"}]},
    {"id": "state_table", "title": "Geographic risk adjustment", "subtitle": "Customer states with at least 1,000 eligible deliveries", "dataset": "state_adjusted", "sourceId": "source_state_adjusted", "defaultSort": {"field": "observed_expected_ratio", "direction": "desc"}, "columns": [{"field": "customer_state", "label": "State", "type": "text"}, {"field": "orders", "label": "Orders", "format": "number"}, {"field": "observed", "label": "Late", "format": "number"}, {"field": "expected", "label": "Expected", "format": "number"}, {"field": "observed_expected_ratio", "label": "Observed / expected", "format": "number"}]},
]

blocks = [
    md("title", "# The promise clock: where Olist deliveries break", False),
    md("summary", f"## Executive Summary\n\n- **A short period drove a disproportionate share of failures.** February–March 2018 contributed {o['feb_mar_late_orders']:,} late deliveries, {pct(o['feb_mar_late_orders']/o['late_orders'])} of all late orders from {pct(o['feb_mar_orders']/o['orders'])} of eligible volume. The late rate outside those months was {pct(o['other_months_late_rate'])}.\n- **A short-buffer handoff alert is useful but cannot solve most delays.** Orders with three or fewer calendar days left at handoff had a {pct(o['short_slack_late_rate'])} late rate, yet accounted for only {pct(o['short_slack_late_capture'])} of late orders with valid stages. {pct(o['long_slack_late_share'])} of late orders still had more than 14 days left at handoff.\n- **Risk differs by destination even after a simple mix adjustment.** Rio de Janeiro observed 1.80 times the late orders expected for its purchase-month and promise-length mix; Bahia was also about 1.80 times expected. This points to routes and local conditions worth investigating, not proof of a carrier cause.\n- **Customer experience is strongly associated with lateness.** Within comparable state × month groups, {pct(o['low_review_standardized_late'])} of late orders had a low review versus {pct(o['low_review_standardized_on_time'])} of on-time orders. This is an association, not a causal estimate."),
    md("problem", "## The decision this project supports\n\n**Problem statement.** A headline on-time rate hides when a promised delivery becomes hard to meet. A fulfillment leader needs to know whether to change seller handoff practices, carrier routing, promise design, or customer communication, and where each action should be tested.\n\nThe primary outcome is arrival after the published **calendar date**. The analysis uses delivered purchases from January 2017 through August 18, 2018, with a 60-day observation buffer before the last recorded delivery. It covers 94,702 eligible delivered orders. This is historical diagnosis, not a live operations feed.\n\n**Decision rule.** Prioritize an intervention only if it addresses a measured concentration of failures, has an owner, and can be evaluated against both late delivery and customer experience."),
    {"id": "metrics", "type": "metric-strip", "cardIds": ["late_rate", "late_count", "feb_mar"]},
    md("shock", "## A two-month shock dominates the failure count\n\nThe February–March 2018 cohort had 2,254 late orders across 13,558 eligible deliveries. March alone reached an 18.96% late rate, while the full cohort rate was 6.87%. The monthly pattern argues for a surge or incident review before treating the full-period average as a steady operating baseline. The data does not record weather, strikes, capacity, or carrier identity, so it cannot identify the external cause."),
    {"id": "monthly_chart", "type": "chart", "chartId": "monthly"},
    md("stage", f"## A short-buffer alert catches only one in ten late orders\n\nOf {o['late_stage_eligible']:,} late orders with valid stage dates, only {o['late_already_past_promise_at_handoff']:,} had already missed the promised calendar date at carrier handoff. An alert for three or fewer days remaining would flag {o['short_slack_orders']:,} orders, of which {o['short_slack_late_orders']:,} were late: {pct(o['short_slack_late_rate'])} precision, but only {pct(o['short_slack_late_capture'])} of all late orders captured.\n\nThe other side is easy to miss: {pct(o['long_slack_late_share'])} of late orders had **more than 14 days** left at handoff. A handoff alert is a focused recovery tool. The larger problem requires route and transit-tail investigation with carrier and scan data. These observations do not assign delay to a particular party."),
    {"id": "slack_chart", "type": "chart", "chartId": "slack"},
    md("geography", "## Geographic gaps survive a basic promise and season adjustment\n\nRio de Janeiro recorded 1,493 late deliveries versus 832 expected from its purchase-month and promise-length mix. Bahia recorded 395 versus 219. São Paulo recorded 1,794 versus 2,660 expected. These are large descriptive gaps; product mix, seller origin, carriers, and local route characteristics remain unobserved. Start route-level investigation in the elevated states, but avoid ranking carriers or sellers from customer state alone."),
    {"id": "state_chart", "type": "chart", "chartId": "state"},
    {"id": "state_table_block", "type": "table", "tableId": "state_table"},
    md("promises", "## Short promises are a distinct risk, but longer promises can conceal slow service\n\nThe 900 orders promised in seven days or less had a 21.0% late rate. Orders promised more than 30 days had a 5.0% late rate, yet their median actual delivery was about 15 days. A lower late rate can therefore reflect more generous promises as well as faster execution. The metric must be paired with actual delivery time and customer expectations; this table is not evidence that promises should simply be extended."),
    {"id": "promise_table", "type": "table", "tableId": "promise"},
    md("seller", f"## Seller deadline compliance is a warning signal, not a blame score\n\nFor {o['single_seller_orders']:,} single-seller delivered orders, {o['single_seller_after_shipping_limit']:,} were handed to the carrier after the latest item shipping-limit date. Their late-delivery rate was {pct(o['single_seller_after_limit_late_rate'])}, versus {pct(o['single_seller_within_limit_late_rate'])} when within that limit. The dates are tightly related to the same operational timeline; the gap does not measure the effect of seller behavior. Multi-seller baskets are excluded because one order-level carrier timestamp cannot reliably assign responsibility to each seller."),
    md("reviews", "## Late arrival and poor reviews travel together\n\nA low review means an order-level average score of 1 or 2. The simple late versus on-time comparison is 62.5% versus 9.2%; after weighting comparable state × purchase-month groups, it is 58.1% versus 9.4%. Standardization still cannot isolate delivery from product quality, service recovery, or who chooses to review. Use review impact as a guardrail in an intervention test, not as a revenue or causal loss estimate."),
    {"id": "review_chart", "type": "chart", "chartId": "reviews"},
    md("actions", "## Recommended operating tests\n\n1. **Pilot a focused handoff alert.** Flag orders with three or fewer calendar days left, then track its late-order capture and false alarms. It addresses a small, high-risk subset.\n2. **Investigate the long-slack transit tail.** Add carrier, seller origin, pickup, hub, and delivery-attempt scans. Compare lanes within destination and promise cohorts; prioritize the paths behind most late orders.\n3. **Review the February–March 2018 spike as an incident.** Compare capacity, holidays, weather, and route events from operational logs before assigning a cause. Monitor surge volume and late rate together.\n4. **Pilot route-specific recovery in RJ and BA.** Test rerouting or proactive communication on comparable orders with a holdout, tracking actual delivery time, late rate, and low reviews.\n5. **Review promise policy on short-window orders.** Compare conversion, actual speed, late rate, and reviews. Extending dates alone would improve the SLA number without proving better service."),
    md("questions", "## Further questions that could change the decision\n\n- **What is the economic loss?** Freight value is a customer charge, not carrier cost, refund expense, or contribution margin. Those records are needed to size savings.\n- **Where exactly is the bottleneck?** Add seller origin, carrier, pickup scan, hub events, and delivery attempts. The current order-level handoff and arrival dates do not identify a failed lane or facility.\n- **What happened to orders never marked delivered?** The mature purchase cohort includes 1,092 shipped, 601 unavailable, 554 canceled, and other unresolved statuses. A delivered-only on-time rate cannot describe all customer outcomes.\n- **Does an intervention work?** The findings are observational. Measure changes with a randomized or carefully matched pilot, tracking both delivery speed and customer outcomes."),
    md("caveats", f"## Caveats and assumptions\n\nThe source is an anonymized 2016–2018 public e-commerce dataset, so the project demonstrates an analytical method, not current Olist performance. Delivery is judged by calendar date; timestamp-based lateness would answer a different question. The 60-day buffer reduces recent-order censoring but does not resolve the {q['cohort_orders']-q['delivered_eligible']:,} non-eligible orders in the purchase cohort. Stage analysis excludes {q['delivered_missing_carrier']} missing carrier timestamp and {q['invalid_stage_order']} chronologically invalid stage records. Reviews cover {pct(q['review_coverage'])} of eligible delivered orders. Geographic adjustment controls only purchase month and promise band. No inventory, carrier cost, or route-event data are available."),
]
for block in blocks:
    source_id = {
        "problem": "source_overall", "shock": "source_overall",
        "geography": "source_state_adjusted", "promises": "source_promise",
        "seller": "source_overall", "reviews": "source_overall",
    }.get(block["id"])
    if source_id:
        block["sourceId"] = source_id

artifact = {
    "surface": "report",
    "manifest": {"version": 1, "surface": "report", "title": "The promise clock: where Olist deliveries break", "description": "A decision-ready supply chain case study using historical Olist orders.", "generatedAt": now, "filters": [], "cards": cards, "charts": charts, "tables": tables, "sources": [{"id": s["id"], "label": s["label"], "path": s["path"]} for s in sources], "blocks": blocks},
    "snapshot": {"version": 1, "generatedAt": now, "status": "ready", "datasets": datasets},
    "sources": sources,
}

(HERE / "artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
print(HERE / "artifact.json")
