"""Export publication-ready PNGs for the GitHub README from reviewed aggregates."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
FIG = ROOT / "assets"
FIG.mkdir(exist_ok=True)

BLUE = "#2F6FDB"
ORANGE = "#E76F2E"
RED = "#C43D3D"
GREEN = "#16815D"
INK = "#1D2939"
MUTED = "#667085"
GRID = "#E5EAF0"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 16,
    "axes.titleweight": "bold",
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.edgecolor": GRID,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def polish(ax, percent=False):
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="both", length=0, pad=8)
    ax.yaxis.grid(True, color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    if percent:
        from matplotlib.ticker import PercentFormatter
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))


def save(fig, filename):
    fig.tight_layout(pad=1.8)
    fig.savefig(FIG / filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


findings = json.loads((OUT / "findings.json").read_text(encoding="utf-8"))
overall = findings["overall"]

monthly = pd.read_csv(OUT / "monthly.csv").sort_values("month")
monthly = monthly.loc[monthly.month.lt("2018-08")].reset_index(drop=True)
fig, ax = plt.subplots(figsize=(10.5, 4.2))
x = np.arange(len(monthly))
ax.plot(x, monthly.late_rate, color=BLUE, linewidth=2.7, marker="o", markersize=3.5)
surge = monthly.month.isin(["2018-02", "2018-03"])
surge_idx = np.flatnonzero(surge)
ax.plot(surge_idx, monthly.late_rate[surge], color=ORANGE, linewidth=3.3, marker="o", markersize=5)
ax.axhline(overall["late_rate"], color=MUTED, linestyle=(0, (4, 4)), linewidth=1.2)
ax.text(len(monthly)-.3, overall["late_rate"]+.003, "Full-cohort average 6.9%", color=MUTED, ha="right", fontsize=9)
ax.annotate("March 2018  ·  19.0%", (14, monthly.loc[14, "late_rate"]), xytext=(10.7, .17), color=ORANGE, fontsize=10, fontweight="bold", arrowprops={"arrowstyle": "-", "color": ORANGE})
ax.set_xticks(x[::3], monthly.month.iloc[::3].str.replace("-", " ", regex=False))
ax.set_ylim(0, .22)
ax.set_ylabel("Late-delivery rate")
ax.set_title("A short surge dominates the late-delivery trend", loc="left", pad=16)
polish(ax, percent=True)
save(fig, "monthly-late-rate.png")

slack = pd.read_csv(OUT / "slack.csv")
fig, ax = plt.subplots(figsize=(9.5, 4.2))
x = np.arange(len(slack))
w = .34
ax.bar(x-w/2, overall["late_rate"], width=w, color=BLUE, label="Full cohort 6.9%")
bars = ax.bar(x+w/2, slack.late_rate, width=w, color=ORANGE, label="Handoff window")
for bar, rate in zip(bars, slack.late_rate):
    ax.text(bar.get_x()+bar.get_width()/2, rate+.018, f"{rate:.0%}", ha="center", color=INK, fontweight="bold", fontsize=9)
ax.set_xticks(x, slack.handoff_slack_band)
ax.set_ylim(0, 1.12)
ax.set_ylabel("Late-delivery rate")
ax.set_title("A short handoff buffer signals risk, but misses most late orders", loc="left", pad=16)
ax.legend(frameon=False, loc="upper right", ncol=2)
polish(ax, percent=True)
save(fig, "handoff-slack.png")

state = pd.read_csv(OUT / "state_adjusted.csv").sort_values("observed_expected_ratio", ascending=False)
state["gap"] = 1 - state.observed_expected_ratio
fig, ax = plt.subplots(figsize=(10, 4.3))
colors = [RED if value < 0 else GREEN for value in state.gap]
ax.bar(state.customer_state, state.gap, color=colors, width=.72)
ax.axhline(0, color=INK, linewidth=1)
ax.set_ylim(-1.2, .55)
ax.set_ylabel("Fewer / more late than expected")
ax.set_title("Regional gaps persist after month and promise adjustment", loc="left", pad=16)
polish(ax, percent=True)
save(fig, "state-risk-gap.png")

review_values = [overall["low_review_standardized_on_time"], overall["low_review_standardized_late"]]
fig, ax = plt.subplots(figsize=(7.6, 4.1))
bars = ax.bar(["On-time delivery", "Late delivery"], review_values, color=[BLUE, ORANGE], width=.52)
for bar, value in zip(bars, review_values):
    ax.text(bar.get_x()+bar.get_width()/2, value+.025, f"{value:.1%}", ha="center", fontweight="bold", fontsize=12)
ax.set_ylim(0, .7)
ax.set_ylabel("Share with low review")
ax.set_title("Late arrival is associated with far more low reviews", loc="left", pad=16)
polish(ax, percent=True)
save(fig, "review-association.png")

print("Wrote 4 figures to", FIG)
