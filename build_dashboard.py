"""Build the compact operational dashboard from the reviewed report data."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
report = json.loads((HERE / "artifact.json").read_text(encoding="utf-8"))
dashboard = json.loads(json.dumps(report))
dashboard["surface"] = "dashboard"
manifest = dashboard["manifest"]
manifest["surface"] = "dashboard"
manifest["title"] = "Olist delivery risk monitor"
manifest["description"] = "Historical delivery risk snapshot: status, time pattern, handoff buffer, and destination mix."
manifest["blocks"] = [
    {"id": "heading", "type": "markdown", "body": "# Olist delivery risk monitor\n\nHistorical snapshot of eligible delivered orders purchased January 2017–August 18, 2018. Late means arrival after the promised calendar date."},
    {"id": "headline", "type": "metric-strip", "cardIds": ["late_rate", "late_count", "feb_mar"]},
    {"id": "monthly_view", "type": "chart", "chartId": "monthly"},
    {"id": "handoff_view", "type": "chart", "chartId": "slack"},
    {"id": "state_view", "type": "chart", "chartId": "state"},
    {"id": "state_detail", "type": "table", "tableId": "state_table"},
    {"id": "promise_view", "type": "table", "tableId": "promise"},
    {"id": "review_view", "type": "chart", "chartId": "reviews"},
    {"id": "dashboard_limit", "type": "markdown", "body": "This is a historical public-data snapshot. Regional ratios control only purchase month and promise band. Carrier cost, inventory, route events, and intervention effects are not observable. Read the companion report for decisions and caveats."},
]
(HERE / "dashboard-artifact.json").write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
print(HERE / "dashboard-artifact.json")
