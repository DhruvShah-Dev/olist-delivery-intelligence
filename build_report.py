"""Build the self-contained shareholder story and diagnostic dashboard."""
from __future__ import annotations

import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
DATA = json.loads((OUT / "findings.json").read_text(encoding="utf-8"))
O, Q, BUILD = DATA["overall"], DATA["quality"], DATA["build"]
MONTHLY = sorted(DATA["monthly"], key=lambda row: row["month"])
SLACK = DATA["slack"]
STATES = sorted(DATA["state_adjusted"], key=lambda row: row["excess_late_orders"], reverse=True)
PROMISE = DATA["promise"]
REVIEWS = DATA["reviews"]
GENERATED_AT = datetime.now(timezone.utc).isoformat()

ORANGE = "#f97316"
BLUE = "#1677c8"
INK = "#171717"
MUTED = "#667085"
GRID = "#d0d5dd"
LIGHT = "#eef1f4"


def pct(value: float, digits: int = 1) -> str:
    return f"{100 * value:.{digits}f}%"


def compact(value: float) -> str:
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    return f"{value:,.0f}"


def safe(value: object) -> str:
    return html.escape(str(value), quote=True)


def mark_attrs(lines: list[str]) -> str:
    text = "||".join(lines)
    return f'class="mark" tabindex="0" data-tooltip="{safe(text)}"'


def line(x1, y1, x2, y2, cls="grid") -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="{cls}" />'


def monthly_svg() -> str:
    rows = [row for row in MONTHLY if row["month"] < "2018-08"]
    width, height = 960, 520
    left, right, top = 70, 24, 62
    plot_w = width - left - right
    step = plot_w / len(rows)
    max_count = max(row["late_orders"] for row in rows) * 1.12
    max_rate = max(row["late_rate"] for row in rows) * 1.12
    count_y0, count_h = 225, 150
    rate_y0, rate_h = 476, 150
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="monthly-title monthly-desc">',
             '<title id="monthly-title">Monthly late-order count and late-delivery rate</title>',
             '<desc id="monthly-desc">Two aligned panels show late-order counts and rates by purchase month. November 2017 and February to March 2018 are annotated.</desc>',
             '<text x="70" y="30" class="axis-title">Late orders</text>',
             '<text x="70" y="282" class="axis-title">Late rate</text>']
    for tick in [0, 0.5, 1.0]:
        y = count_y0 - count_h * tick
        value = max_count * tick
        parts += [line(left, y, width - right, y),
                  f'<text x="58" y="{y + 4}" class="tick" text-anchor="end">{compact(value)}</text>']
        y2 = rate_y0 - rate_h * tick
        value2 = max_rate * tick
        parts += [line(left, y2, width - right, y2),
                  f'<text x="58" y="{y2 + 4}" class="tick" text-anchor="end">{pct(value2, 0)}</text>']
    points = []
    for idx, row in enumerate(rows):
        x = left + step * idx + step / 2
        bar_h = count_h * row["late_orders"] / max_count
        y = count_y0 - bar_h
        focus = row["month"] in {"2017-11", "2018-02", "2018-03"}
        color = ORANGE if focus else "#c9ced6"
        tooltip = [
            row["month"], f"Late orders: {row['late_orders']:,}",
            f"Late rate: {pct(row['late_rate'])}", f"Eligible deliveries: {row['orders']:,}",
            "Purchase month; partial August excluded",
        ]
        parts.append(f'<g {mark_attrs(tooltip)}><rect x="{x-step*.27:.1f}" y="{y:.1f}" width="{step*.54:.1f}" height="{bar_h:.1f}" fill="{color}" /><title>{safe(" · ".join(tooltip))}</title></g>')
        rate_y = rate_y0 - rate_h * row["late_rate"] / max_rate
        points.append((x, rate_y, row, focus))
        if idx % 2 == 0 or focus:
            label = row["month"][2:].replace("-", "·")
            parts.append(f'<text x="{x:.1f}" y="505" class="tick" text-anchor="middle">{label}</text>')
    parts.append(f'<path d="{" ".join(("M" if i == 0 else "L") + f" {x:.1f} {y:.1f}" for i,(x,y,_,_) in enumerate(points))}" class="rate-line" />')
    for x, y, row, focus in points:
        tooltip = [
            row["month"], f"Late rate: {pct(row['late_rate'])}",
            f"Late orders: {row['late_orders']:,} of {row['orders']:,}",
            f"Compared with cohort: {row['late_rate']/O['late_rate']:.1f}×",
            "Purchase month; partial August excluded",
        ]
        fill = ORANGE if focus else BLUE
        parts.append(f'<g {mark_attrs(tooltip)}><circle cx="{x:.1f}" cy="{y:.1f}" r="{6 if focus else 4}" fill="{fill}" /><title>{safe(" · ".join(tooltip))}</title></g>')
    for month, text, dx, dy in [
        ("2017-11", "Nov 2017 · 904 late · 12.4%", -6, -16),
        ("2018-02", "Feb–Mar · 2,254 late", -16, -30),
        ("2018-03", "Mar · 19.0%", 8, -14),
    ]:
        idx = next(i for i, row in enumerate(rows) if row["month"] == month)
        x, y, _, _ = points[idx]
        parts.append(f'<text x="{x+dx:.1f}" y="{y+dy:.1f}" class="annotation">{text}</text>')
    parts.append('</svg>')
    return "".join(parts)


def handoff_svg() -> str:
    width, height = 960, 420
    left, mid, right = 170, 485, 925
    row_h, start_y = 58, 78
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="handoff-title handoff-desc">',
             '<title id="handoff-title">Late risk and share of all late orders by handoff window</title>',
             '<desc id="handoff-desc">The pre-breach zero to three day window has high risk but captures only 5.5 percent of stage-eligible late orders.</desc>',
             '<text x="170" y="32" class="axis-title">Late risk within window</text>',
             '<text x="585" y="32" class="axis-title">Share of all late orders</text>']
    for idx, row in enumerate(SLACK):
        y = start_y + idx * row_h
        risk_w = 260 * row["late_rate"]
        share_w = 260 * row["share_of_all_late"] / max(r["share_of_all_late"] for r in SLACK)
        focal = row["handoff_slack_band"] == "0–3 days"
        breached = row["handoff_slack_band"] == "past promise"
        color = ORANGE if focal else BLUE if breached else "#aeb6c2"
        parts.append(f'<text x="155" y="{y+5}" class="category" text-anchor="end">{safe(row["handoff_slack_band"])}</text>')
        tooltip = [
            row["handoff_slack_band"], f"Late rate: {pct(row['late_rate'])}",
            f"Late orders: {row['late_orders']:,} of {row['orders']:,}",
            f"Captures {pct(row['share_of_all_late'])} of stage-eligible late orders",
            "Breached at handoff" if breached else "Pre-breach window",
        ]
        parts.append(f'<g {mark_attrs(tooltip)}><rect x="{left}" y="{y-12}" width="{risk_w:.1f}" height="18" fill="{color}" /><text x="{left+risk_w+8:.1f}" y="{y+3}" class="value">{pct(row["late_rate"],0)}</text><title>{safe(" · ".join(tooltip))}</title></g>')
        parts.append(f'<g {mark_attrs(tooltip)}><rect x="585" y="{y-12}" width="{share_w:.1f}" height="18" fill="{color}" /><text x="{585+share_w+8:.1f}" y="{y+3}" class="value">{pct(row["share_of_all_late"],1)}</text><title>{safe(" · ".join(tooltip))}</title></g>')
    parts += [line(left, 373, mid-20, 373, "axis"), line(585, 373, right, 373, "axis"),
              '<text x="170" y="400" class="note">0–3 days: 42.6% precision, 5.5% recall</text>',
              '<text x="585" y="400" class="note">69.4% of late orders had more than 14 days left</text>', '</svg>']
    return "".join(parts)


def state_svg() -> str:
    rows = [row for row in STATES if row["excess_late_orders"] > 0]
    width, height = 960, 520
    left, right, start_y, row_h = 170, 880, 64, 50
    max_value = max(row["excess_ci_high"] for row in rows) * 1.05
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="state-title state-desc">',
             '<title id="state-title">Excess late orders by customer state</title>',
             '<desc id="state-desc">Rio de Janeiro has the largest absolute excess after adjustment, followed by Bahia. Intervals are stratified bootstrap ranges.</desc>']
    for idx, row in enumerate(rows):
        y = start_y + idx * row_h
        bar_w = (right-left) * row["excess_late_orders"] / max_value
        lo = left + (right-left) * max(row["excess_ci_low"], 0) / max_value
        hi = left + (right-left) * max(row["excess_ci_high"], 0) / max_value
        focal = row["customer_state"] in {"RJ", "BA"}
        color = ORANGE if focal else "#c4cad2"
        tooltip = [
            row["customer_state"], f"Excess late orders: {row['excess_late_orders']:+.0f}",
            f"Observed: {row['observed']:.0f}; expected: {row['expected']:.0f}",
            f"Observed / expected: {row['observed_expected_ratio']:.2f}×",
            "Adjusted only for purchase month and promise window",
        ]
        parts.append(f'<text x="150" y="{y+5}" class="category" text-anchor="end">{safe(row["customer_state"])}</text>')
        parts.append(f'<g {mark_attrs(tooltip)}><rect x="{left}" y="{y-12}" width="{bar_w:.1f}" height="20" fill="{color}" /><line x1="{lo:.1f}" x2="{hi:.1f}" y1="{y-2}" y2="{y-2}" class="interval" /><text x="{left+bar_w+10:.1f}" y="{y+4}" class="value">+{row["excess_late_orders"]:.0f}</text><title>{safe(" · ".join(tooltip))}</title></g>')
    parts += [line(left, height-35, right, height-35, "axis"),
              f'<text x="{left}" y="{height-10}" class="note">Excess late orders (observed minus expected) · intervals show bootstrap uncertainty</text>', '</svg>']
    return "".join(parts)


def promise_svg() -> str:
    width, height = 960, 400
    left, mid, right, start_y, row_h = 170, 520, 920, 76, 58
    max_rate = max(row["late_rate"] for row in PROMISE) * 1.15
    max_days = max(row["median_actual_days"] for row in PROMISE) * 1.12
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="promise-title promise-desc">',
             '<title id="promise-title">Late rate and actual delivery time by promised window</title>',
             '<desc id="promise-desc">Short promises have high late rates while long promises can have low late rates despite slower actual delivery.</desc>',
             '<text x="170" y="30" class="axis-title">Late rate</text>',
             '<text x="560" y="30" class="axis-title">Median actual delivery days</text>']
    for idx, row in enumerate(PROMISE):
        y = start_y + idx * row_h
        rate_x = left + 280 * row["late_rate"] / max_rate
        days_x = 560 + 280 * row["median_actual_days"] / max_days
        tooltip = [
            f"Promise window: {row['promise_band']} days", f"Late rate: {pct(row['late_rate'])}",
            f"Median actual delivery: {row['median_actual_days']:.1f} days", f"Eligible deliveries: {row['orders']:,}",
            "A lower late rate can reflect a longer promise",
        ]
        parts += [f'<text x="150" y="{y+5}" class="category" text-anchor="end">{safe(row["promise_band"])}</text>',
                  line(left, y, mid-30, y), line(560, y, right, y),
                  f'<g {mark_attrs(tooltip)}><circle cx="{rate_x:.1f}" cy="{y}" r="7" fill="{BLUE}" /><text x="{rate_x+12:.1f}" y="{y+5}" class="value">{pct(row["late_rate"],1)}</text><title>{safe(" · ".join(tooltip))}</title></g>',
                  f'<g {mark_attrs(tooltip)}><circle cx="{days_x:.1f}" cy="{y}" r="7" fill="{ORANGE}" /><text x="{days_x+12:.1f}" y="{y+5}" class="value">{row["median_actual_days"]:.1f}</text><title>{safe(" · ".join(tooltip))}</title></g>']
    parts += ['<text x="170" y="380" class="note">Promise windows remain ordered from shortest to longest</text>', '</svg>']
    return "".join(parts)


def review_svg() -> str:
    width, height = 960, 250
    left, right, y = 140, 880, 115
    on, late = REVIEWS[0], REVIEWS[1]
    x_on = left + (right-left) * on["low_review_rate"] / 0.65
    x_late = left + (right-left) * late["low_review_rate"] / 0.65
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-labelledby="review-title review-desc">',
             '<title id="review-title">Low-review rate for on-time and late deliveries</title>',
             '<desc id="review-desc">Late deliveries have a 58.1 percent low-review rate compared with 9.4 percent for on-time deliveries in common-support strata.</desc>',
             line(left, y, right, y, "axis")]
    for row, x, color in [(on, x_on, BLUE), (late, x_late, ORANGE)]:
        tooltip = [
            row["group"], f"Low-review rate: {pct(row['low_review_rate'])}",
            f"Common-support orders: {row['n_common_support']:,}",
            f"Review coverage: {pct(row['review_coverage'])}",
            "Comparable state × month groups; association, not causation",
        ]
        parts.append(f'<g {mark_attrs(tooltip)}><circle cx="{x:.1f}" cy="{y}" r="11" fill="{color}" /><text x="{x:.1f}" y="{y-25}" class="value" text-anchor="middle">{safe(row["group"])} · {pct(row["low_review_rate"])}</text><title>{safe(" · ".join(tooltip))}</title></g>')
    parts += [f'<path d="M {x_on:.1f} {y+34} L {x_late:.1f} {y+34}" class="difference" />',
              f'<text x="{(x_on+x_late)/2:.1f}" y="{y+66}" class="annotation" text-anchor="middle">+{100*O["low_review_difference"]:.1f} percentage points</text>',
              f'<text x="{left}" y="220" class="note">Common support: {O["review_standardization_orders"]:,} orders ({pct(O["review_common_support_share"])} of reviewed orders)</text>', '</svg>']
    return "".join(parts)


CSS = r"""
:root{--ink:#171717;--muted:#667085;--orange:#f97316;--blue:#1677c8;--grid:#d0d5dd;--light:#eef1f4;--max:1120px;--serif:Georgia,'Times New Roman',serif;--sans:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:var(--ink);font-family:var(--sans);font-size:17px;line-height:1.55}a{color:inherit}header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.96);border-bottom:1px solid var(--grid);backdrop-filter:blur(10px)}.topbar{max-width:var(--max);margin:auto;padding:14px 28px;display:flex;align-items:center;gap:24px}.brand{font-family:var(--serif);font-weight:700}.progress{height:3px;background:#e6e9ee;flex:1}.progress span{display:block;width:0;height:100%;background:var(--orange)}.topbar small{color:var(--muted)}main{overflow:hidden}.hero,.story-section,.appendix,.actions{max-width:var(--max);margin:auto;padding:88px 28px}.hero{min-height:calc(100svh - 54px);display:flex;flex-direction:column;justify-content:center}.hero h1{font:700 clamp(3.2rem,7vw,6.9rem)/.96 var(--serif);letter-spacing:-.055em;max-width:1040px;margin:0 0 56px}.hero-stat{display:grid;grid-template-columns:1.1fr 1fr;gap:42px;align-items:end;border-top:1px solid var(--ink);padding-top:28px}.hero-number{font:700 clamp(5rem,12vw,10rem)/.8 var(--serif);color:var(--orange)}.hero-copy{font:700 clamp(1.8rem,3.8vw,3.7rem)/1.04 var(--serif);max-width:580px}.hero-meta{display:flex;gap:36px;margin-top:24px;color:var(--muted);font-size:.95rem}.story-section{border-top:1px solid var(--ink);min-height:88vh}.section-number{color:var(--orange);font-weight:800;letter-spacing:.08em;font-size:.78rem;text-transform:uppercase}.story-section h2,.actions h2,.appendix h2{font:700 clamp(2.5rem,5vw,5rem)/1.02 var(--serif);letter-spacing:-.04em;max-width:900px;margin:16px 0 18px}.takeaway{font-size:clamp(1.15rem,2vw,1.45rem);max-width:820px;margin:0 0 12px}.caveat{color:var(--muted);font-size:.94rem;max-width:800px;margin:0 0 48px}.chart{margin:32px 0 0}.chart svg{width:100%;height:auto;overflow:visible}.chart .grid{stroke:var(--light);stroke-width:1}.chart .axis{stroke:#7b8491;stroke-width:1.2}.chart .interval{stroke:#5f6875;stroke-width:2}.chart .rate-line{fill:none;stroke:var(--blue);stroke-width:2.5}.chart .difference{fill:none;stroke:var(--ink);stroke-width:1.4;marker-end:url(#arrow)}.chart .tick,.chart .note{fill:var(--muted);font:13px var(--sans)}.chart .axis-title,.chart .category,.chart .value{fill:var(--ink);font:600 14px var(--sans)}.chart .annotation{fill:var(--ink);font:700 14px var(--sans)}.mark{cursor:help;outline:none}.mark:focus>rect,.mark:focus>circle,.mark:hover>rect,.mark:hover>circle{filter:brightness(.88);stroke:#111;stroke-width:2}.status-context{display:grid;grid-template-columns:4fr 1fr;margin-top:48px}.status-context .delivered{background:var(--blue);color:#fff;padding:22px}.status-context .other{background:var(--light);padding:22px}.test-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0;margin-top:60px;border-top:1px solid var(--grid);border-bottom:1px solid var(--grid)}.test{padding:32px 28px 34px 0}.test+ .test{border-left:1px solid var(--grid);padding-left:28px}.test h3{font:700 2rem/1.05 var(--serif);margin:0 0 30px}.test h4{font:700 1rem var(--sans);margin:22px 0 4px}.test p{margin:0;color:#343a40}.appendix{background:#f7f8fa;max-width:none}.appendix-inner{max-width:var(--max);margin:auto}.appendix-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:30px}.appendix details{border-top:1px solid var(--grid);padding-top:14px}.appendix summary{font-weight:750;cursor:pointer}.data-table{overflow-x:auto;margin-top:20px}.data-table table{width:100%;border-collapse:collapse;font-size:.88rem}.data-table th,.data-table td{padding:10px 12px;border-bottom:1px solid #e2e5e9;text-align:right}.data-table th:first-child,.data-table td:first-child{text-align:left}.tooltip{position:fixed;z-index:50;max-width:310px;background:#171717;color:#fff;padding:14px 16px;box-shadow:0 12px 40px rgba(0,0,0,.2);font-size:.84rem;line-height:1.45;pointer-events:none;opacity:0;transform:translateY(4px);transition:.15s}.tooltip.show{opacity:1;transform:none}.tooltip strong{display:block;color:#ffb27a;margin-bottom:5px}.tooltip span{display:block}.reveal{opacity:0;transform:translateY(24px);transition:opacity .55s ease,transform .55s ease}.reveal.visible{opacity:1;transform:none}.story-nav{position:fixed;right:22px;top:50%;transform:translateY(-50%);z-index:15;display:flex;flex-direction:column;gap:9px}.story-nav a{width:9px;height:9px;border-radius:50%;background:#d3d7de;text-indent:-999px}.story-nav a.active{background:var(--orange);transform:scale(1.35)}footer{max-width:var(--max);margin:auto;padding:40px 28px 70px;color:var(--muted);font-size:.85rem}
.mark{pointer-events:bounding-box}.mark:hover>rect,.mark:hover>circle{filter:none;stroke:none}
@media(max-width:760px){body{font-size:16px}.topbar{padding:11px 18px}.topbar small{display:none}.hero,.story-section,.actions{padding:62px 20px}.hero{min-height:auto;padding-top:78px}.hero h1{font-size:3.25rem;margin-bottom:40px}.hero-stat{grid-template-columns:1fr}.hero-copy{font-size:2.25rem}.hero-meta{display:block}.hero-meta span{display:block;margin-top:7px}.story-section{min-height:auto}.story-section h2,.actions h2{font-size:2.8rem}.chart{overflow-x:auto}.chart svg{min-width:760px}.story-nav{display:none}.status-context{grid-template-columns:1fr}.test-grid{grid-template-columns:1fr}.test{padding:28px 0}.test+.test{border-left:0;border-top:1px solid var(--grid);padding-left:0}.appendix{padding:58px 20px}.appendix-grid{grid-template-columns:1fr}.tooltip{max-width:260px}.reveal{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}.reveal{opacity:1;transform:none;transition:none}}
@media print{header,.story-nav,.tooltip{display:none}.hero,.story-section,.actions{min-height:0;padding:42px 20px;break-inside:avoid}.reveal{opacity:1;transform:none}.appendix details{display:block}.appendix details>*{display:block}}
.reveal{opacity:1;transform:none;transition:none}.reveal.visible{animation:section-rise .55s ease both}@keyframes section-rise{from{opacity:.72;transform:translateY(18px)}to{opacity:1;transform:none}}
"""

JS = r"""
const tooltip=document.querySelector('.tooltip');
const showTip=(event)=>{const el=event.currentTarget;const rows=(el.dataset.tooltip||'').split('||');tooltip.innerHTML=`<strong>${rows[0]||''}</strong>${rows.slice(1).map(x=>`<span>${x}</span>`).join('')}`;const box=el.getBoundingClientRect();const x=Math.min(window.innerWidth-330,Math.max(12,box.left+box.width/2));const y=Math.min(window.innerHeight-180,Math.max(12,box.top-10));tooltip.style.left=`${x}px`;tooltip.style.top=`${y}px`;tooltip.classList.add('show')};
const hideTip=()=>tooltip.classList.remove('show');
document.querySelectorAll('.mark').forEach(el=>{el.addEventListener('pointerenter',showTip);el.addEventListener('pointerleave',hideTip);el.addEventListener('focus',showTip);el.addEventListener('blur',hideTip);el.addEventListener('click',e=>{e.stopPropagation();showTip(e)})});
document.addEventListener('click',hideTip);document.addEventListener('keydown',e=>{if(e.key==='Escape')hideTip()});
const sections=[...document.querySelectorAll('[data-story]')];const nav=[...document.querySelectorAll('.story-nav a')];const progress=document.querySelector('.progress span');
const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('visible');const id=entry.target.id;nav.forEach(a=>a.classList.toggle('active',a.getAttribute('href')===`#${id}`))}})},{threshold:.18});sections.forEach(s=>observer.observe(s));
window.addEventListener('scroll',()=>{const h=document.documentElement.scrollHeight-window.innerHeight;progress.style.width=`${h?Math.min(100,window.scrollY/h*100):0}%`},{passive:true});
"""


def table_html(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "".join(f"<th>{safe(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = []
        for key, _ in columns:
            value = row.get(key, "")
            if isinstance(value, float):
                value = f"{value:.3f}"
            cells.append(f"<td>{safe(value)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f'<div class="data-table"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def page_shell(title: str, body: str, nav: bool = True) -> str:
    story_nav = "" if not nav else '<nav class="story-nav" aria-label="Story sections">' + "".join(
        f'<a href="#{name}" aria-label="Section {idx}">{idx}</a>' for idx, name in enumerate(
            ["scale", "time", "handoff", "states", "promise", "reviews", "tests"], 1)) + '</nav>'
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><link rel="icon" href="data:,"><title>{safe(title)}</title><style>{CSS}</style></head><body>
<header><div class="topbar"><span class="brand">Olist delivery intelligence</span><div class="progress" aria-hidden="true"><span></span></div><small>Historical shareholder case study</small></div></header>
{story_nav}<main>{body}</main><div class="tooltip" role="tooltip" aria-live="polite"></div>
<footer>Historical public-data case study · Purchase window January 2017–August 18, 2018 · Build {safe(BUILD['build_id'])}</footer><script>{JS}</script></body></html>'''


def report_body() -> str:
    top_states = [row for row in STATES if row["excess_late_orders"] > 0]
    return f'''
<section class="hero reveal visible" id="scale" data-story>
  <h1>Delivery reliability: where risk concentrates and what to test next.</h1>
  <div class="hero-stat"><div><div class="hero-number">{pct(O['late_rate'])}</div></div><div><div class="hero-copy">of eligible deliveries were late.</div><div class="hero-meta"><span><strong>{O['late_orders']:,}</strong> of {O['orders']:,}</span><span>About one in fifteen</span></div></div></div>
  <div class="status-context" aria-label="Purchase cohort status context"><div class="delivered"><strong>{Q['cohort_statuses']['delivered']:,}</strong><br>orders marked delivered</div><div class="other"><strong>{Q['cohort_orders']-Q['cohort_statuses']['delivered']:,}</strong><br>other statuses</div></div>
  <p class="caveat" style="margin-top:24px">Historical public-data case study—not current Olist performance. The headline includes completed deliveries with actual and promised dates.</p>
</section>
<section class="story-section reveal" id="time" data-story><span class="section-number">02 · When</span><h2>Failures concentrated in two months.</h2><p class="takeaway">February–March produced {pct(O['feb_mar_late_orders']/O['late_orders'])} of late deliveries from {pct(O['feb_mar_orders']/O['orders'])} of eligible volume.</p><p class="caveat">November 2017 is also labeled; the dataset cannot identify the events behind either spike.</p><div class="chart">{monthly_svg()}</div></section>
<section class="story-section reveal" id="handoff" data-story><span class="section-number">03 · Intervention</span><h2>Most late orders still had time at handoff.</h2><p class="takeaway">A 0–3 day warning was {pct(O['prebreach_alert_precision'])} precise but captured only {pct(O['prebreach_alert_capture'])} of stage-eligible late orders.</p><p class="caveat">The {O['late_already_past_promise_at_handoff']:,} already-breached orders are a separate escalation population.</p><div class="chart">{handoff_svg()}</div></section>
<section class="story-section reveal" id="states" data-story><span class="section-number">04 · Where</span><h2>Investigation starts where excess failures are largest.</h2><p class="takeaway">Rio de Janeiro had about {STATES[0]['excess_late_orders']:.0f} excess late deliveries; Bahia followed with about {STATES[1]['excess_late_orders']:.0f}.</p><p class="caveat">Customer state is a starting point, not a carrier or route diagnosis. Adjustment covers only month and promise window.</p><div class="chart">{state_svg()}</div></section>
<section class="story-section reveal" id="promise" data-story><span class="section-number">05 · Promise policy</span><h2>A lower late rate can hide slower service.</h2><p class="takeaway">Promises beyond 30 days had a {pct(PROMISE[-1]['late_rate'])} late rate, yet median delivery still took {PROMISE[-1]['median_actual_days']:.0f} days.</p><p class="caveat">Extending a promise can improve the SLA without improving actual delivery speed.</p><div class="chart">{promise_svg()}</div></section>
<section class="story-section reveal" id="reviews" data-story><span class="section-number">06 · Customer trust</span><h2>Late delivery travels with poor reviews.</h2><p class="takeaway">Low reviews were {pct(O['low_review_standardized_late'])} for late orders versus {pct(O['low_review_standardized_on_time'])} for on-time orders in comparable groups.</p><p class="caveat">Common support covers {O['review_standardization_orders']:,} orders; this is association, not causation.</p><div class="chart">{review_svg()}</div></section>
<section class="actions reveal" id="tests" data-story><span class="section-number">07 · What next</span><h2>Three controlled tests can build evidence.</h2><p class="takeaway">Targeted holdouts can show whether improvement is real, operationally meaningful, and worth scaling.</p><div class="test-grid">
<article class="test"><h3>Pre-breach warning</h3><h4>Hypothesis</h4><p>A 0–3 day warning can recover a narrow high-risk group.</p><h4>Success</h4><p>Lower late rate versus holdout without excessive false alarms.</p><h4>Stop or scale</h4><p>Scale only when the interval excludes zero and cost per recovery is acceptable.</p></article>
<article class="test"><h3>RJ and BA route pilot</h3><h4>Hypothesis</h4><p>Lane-specific intervention can reduce excess late orders.</p><h4>Success</h4><p>Faster actual delivery and fewer late orders versus holdout.</p><h4>Stop or scale</h4><p>Stop if improvement comes only from extending promises.</p></article>
<article class="test"><h3>Promise and communication</h3><h4>Hypothesis</h4><p>Clearer promises and proactive updates can protect trust.</p><h4>Success</h4><p>Actual speed, late rate, and low reviews improve together.</p><h4>Stop or scale</h4><p>Do not scale if SLA improves but actual delivery does not.</p></article></div></section>
<section class="appendix" id="appendix"><div class="appendix-inner"><h2>Technical appendix</h2><p class="takeaway">Definitions, coverage, uncertainty, and source lineage for interpretation.</p><div class="appendix-grid">
<details><summary>Definitions</summary><p>Late means delivered after the promised calendar date. The pre-breach warning is 0–3 days remaining; already-breached orders are separate.</p></details>
<details><summary>Coverage</summary><p>{O['orders']:,} eligible completed deliveries. Review standardization retains {pct(O['review_common_support_share'])} of reviewed orders across {O['review_standardization_strata']} common-support strata.</p></details>
<details><summary>Uncertainty</summary><p>State excess and review differences use {BUILD['bootstrap_replicates']:,} deterministic stratified order-bootstrap replicates.</p></details>
<details><summary>Source lineage</summary><p>Recorded Olist CSV checksums, fixed purchase window, build ID {safe(BUILD['build_id'])}. No carrier cost, route scans, or intervention outcomes are available.</p></details></div>
<details style="margin-top:38px"><summary>Monthly evidence table</summary>{table_html(MONTHLY,[('month','Month'),('orders','Eligible'),('late_orders','Late'),('late_rate','Late rate')])}</details>
<details><summary>Handoff evidence table</summary>{table_html(SLACK,[('handoff_slack_band','Window'),('orders','Orders'),('late_orders','Late'),('late_rate','Late rate'),('share_of_all_late','Late-order share')])}</details>
<details><summary>State evidence table</summary>{table_html(STATES,[('customer_state','State'),('orders','Orders'),('observed','Observed late'),('expected','Expected late'),('excess_late_orders','Excess'),('observed_expected_ratio','Ratio')])}</details>
<details><summary>Promise evidence table</summary>{table_html(PROMISE,[('promise_band','Promised days'),('orders','Orders'),('late_rate','Late rate'),('median_actual_days','Median actual days')])}</details>
<details><summary>Seller diagnostic</summary><p>Exact timestamps classify {O['single_seller_after_shipping_limit']:,} single-seller orders after the shipping limit. Their late rate was {pct(O['single_seller_after_limit_late_rate'])} versus {pct(O['single_seller_within_limit_late_rate'])} within the limit. This is descriptive, not causal.</p></details>
<details><summary>Maturity sensitivity</summary><p>The headline uses a fixed completed-delivery purchase window. Requiring promises to mature through the observation end retains {Q['maturity_sensitivity']['promise_plus_0_days']:,} orders at zero grace and {Q['maturity_sensitivity']['promise_plus_30_days']:,} at 30 days.</p></details>
<p style="font:italic 700 1.5rem var(--serif);margin-top:50px">Historical evidence identifies where to test—not what is already proven.</p></div></section>'''


def dashboard_body() -> str:
    return f'''
<section class="hero reveal visible" style="min-height:auto;padding-bottom:54px"><h1 style="font-size:clamp(3rem,6vw,6rem)">Historical delivery diagnostic.</h1><div class="hero-stat"><div class="hero-number">{pct(O['late_rate'])}</div><div><div class="hero-copy">late delivery rate</div><div class="hero-meta"><span>{O['late_orders']:,} of {O['orders']:,}</span><span>Fixed historical purchase window</span></div></div></div></section>
<section class="story-section reveal visible" style="min-height:auto"><h2>When failures concentrated</h2><div class="chart">{monthly_svg()}</div></section>
<section class="story-section reveal visible" style="min-height:auto"><h2>When intervention remained possible</h2><div class="chart">{handoff_svg()}</div></section>
<section class="story-section reveal visible" style="min-height:auto"><h2>Where excess failures were largest</h2><div class="chart">{state_svg()}</div></section>
<section class="story-section reveal visible" style="min-height:auto"><h2>Customer outcome guardrail</h2><div class="chart">{review_svg()}</div></section>
<section class="appendix"><div class="appendix-inner"><h2>Use with care</h2><p>This is a historical diagnostic, not a live monitor. Carrier, route, cost, and intervention outcomes are unavailable.</p></div></section>'''


def write_metadata(surface: str, title: str, target: Path) -> None:
    artifact = {
        "surface": surface,
        "title": title,
        "generatedAt": GENERATED_AT,
        "build": BUILD,
        "source": "data/source_manifest.json",
        "outputs": [
            "outputs/monthly.csv", "outputs/slack.csv", "outputs/state_adjusted.csv",
            "outputs/promise.csv", "outputs/reviews.csv", "outputs/findings.json",
        ],
        "storyQuestions": [
            "How large is the delivery problem?", "When did failures concentrate?",
            "When was intervention still possible?", "Where should investigation begin?",
            "Does promise policy conceal slow delivery?", "Why does it matter to customers?",
            "What should be tested next?",
        ],
    }
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")


def build_report() -> Path:
    target = ROOT / "report.html"
    target.write_text(page_shell(
        "Delivery reliability: where risk concentrates and what to test next",
        report_body(), nav=True), encoding="utf-8")
    write_metadata("report", "Delivery reliability: where risk concentrates and what to test next", ROOT / "artifact.json")
    return target


def build_dashboard() -> Path:
    target = ROOT / "dashboard.html"
    target.write_text(page_shell("Historical delivery diagnostic", dashboard_body(), nav=False), encoding="utf-8")
    write_metadata("dashboard", "Historical delivery diagnostic", ROOT / "dashboard-artifact.json")
    return target


if __name__ == "__main__":
    print(build_report())
