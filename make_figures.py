"""Export publication-ready README figures from corrected aggregates."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT, FIG = ROOT / "outputs", ROOT / "assets"
FIG.mkdir(exist_ok=True)
BLUE, ORANGE, INK, MUTED, GRID = "#1677C8", "#F97316", "#171717", "#667085", "#E6E9EE"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10,"axes.titlesize":16,
                     "axes.titleweight":"bold","axes.labelcolor":INK,"text.color":INK,
                     "xtick.color":MUTED,"ytick.color":MUTED,"axes.edgecolor":GRID,
                     "figure.facecolor":"white","axes.facecolor":"white","savefig.facecolor":"white"})


def polish(ax, percent=False, grid="y"):
    ax.spines[["top","right","left"]].set_visible(False)
    ax.tick_params(axis="both", length=0, pad=8)
    ax.grid(axis=grid, color=GRID, linewidth=.8)
    ax.set_axisbelow(True)
    if percent:
        from matplotlib.ticker import PercentFormatter
        ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))


def save(fig, filename):
    fig.tight_layout(pad=1.8)
    fig.savefig(FIG / filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


# 1. Monthly count and rate, with both material periods labeled.
monthly = pd.read_csv(OUT / "monthly.csv").query("month < '2018-08'").sort_values("month").reset_index(drop=True)
x = np.arange(len(monthly))
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10.5, 7), sharex=True, gridspec_kw={"height_ratios":[1,1.1]})
focus = monthly.month.isin(["2017-11","2018-02","2018-03"])
ax1.bar(x, monthly.late_orders, color=np.where(focus, ORANGE, "#C9CED6"), width=.66)
ax1.set_ylabel("Late orders")
ax1.set_title("Failures concentrated in November 2017 and February–March 2018", loc="left", pad=16)
ax1.annotate("904", (10, monthly.loc[10,"late_orders"]), xytext=(10,1000), ha="center", fontweight="bold")
ax1.annotate("2,254 across Feb–Mar", (14, monthly.loc[14,"late_orders"]), xytext=(12.6,1450), color=ORANGE, fontweight="bold")
polish(ax1)
ax2.plot(x, monthly.late_rate, color=BLUE, linewidth=2.4, marker="o", markersize=3.5)
ax2.scatter(x[focus], monthly.loc[focus,"late_rate"], color=ORANGE, s=42, zorder=4)
ax2.set_ylabel("Late rate")
ax2.set_xticks(x[::2], monthly.month.iloc[::2].str.replace("-", " ", regex=False), rotation=0)
polish(ax2, percent=True)
save(fig, "monthly-late-rate.png")

# 2. Handoff risk and late-order capture are separate questions.
slack = pd.read_csv(OUT / "slack.csv")
y = np.arange(len(slack))
colors = [BLUE if band == "past promise" else ORANGE if band == "0–3 days" else "#AEB6C2" for band in slack.handoff_slack_band]
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
ax1.barh(y, slack.late_rate, color=colors)
ax1.set_yticks(y, slack.handoff_slack_band)
ax1.invert_yaxis(); ax1.set_xlabel("Late rate"); ax1.set_title("Risk within each window", loc="left")
ax1.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1, decimals=0)); polish(ax1, grid="x")
ax2.barh(y, slack.share_of_all_late, color=colors)
ax2.set_xlabel("Share of all late orders"); ax2.set_title("Late-order capture", loc="left")
ax2.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1, decimals=0)); polish(ax2, grid="x")
fig.suptitle("A pre-breach warning is high risk but narrow reach", x=.07, ha="left", fontweight="bold", fontsize=16)
save(fig, "handoff-slack.png")

# 3. Rank operational burden, not only relative ratios.
state = pd.read_csv(OUT / "state_adjusted.csv").query("excess_late_orders > 0").sort_values("excess_late_orders")
fig, ax = plt.subplots(figsize=(9.5, 5.1))
colors = [ORANGE if code in {"RJ","BA"} else "#C4CAD2" for code in state.customer_state]
ax.barh(state.customer_state, state.excess_late_orders, color=colors)
for y_pos, (_, row) in enumerate(state.iterrows()):
    ax.text(row.excess_late_orders + 10, y_pos, f"+{row.excess_late_orders:.0f}", va="center", fontweight="bold")
ax.set_xlabel("Excess late orders (observed minus expected)")
ax.set_title("Investigation starts where excess failures are largest", loc="left", pad=16)
polish(ax, grid="x")
save(fig, "state-risk-gap.png")

# 4. Customer outcome comparison with the common-support denominator visible.
review = pd.read_csv(OUT / "reviews.csv")
fig, ax = plt.subplots(figsize=(8.5, 3.8))
values = review.low_review_rate.to_numpy()
ax.hlines(0, values[0], values[1], color=INK, linewidth=1.5)
ax.scatter(values, [0,0], s=115, color=[BLUE,ORANGE], zorder=3)
for value, label in zip(values, review.group):
    ax.text(value, .11, f"{label} · {value:.1%}", ha="center", fontweight="bold")
ax.text(values.mean(), -.16, f"+{(values[1]-values[0])*100:.1f} percentage points", ha="center", fontweight="bold")
ax.set_xlim(0,.65); ax.set_ylim(-.3,.3); ax.set_yticks([])
ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1, decimals=0))
ax.set_title("Late delivery travels with poor reviews", loc="left", pad=16)
polish(ax, grid="x")
save(fig, "review-association.png")

print("Wrote 4 corrected figures to", FIG)
