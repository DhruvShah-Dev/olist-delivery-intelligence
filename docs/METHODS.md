# Methods, uncertainty, and proposed tests

## Population and definitions

- **Fixed purchase window:** January 1, 2017 through August 18, 2018 13:22:46. The observation end is October 17, 2018 13:22:46.
- **Headline denominator:** 94,702 completed deliveries with actual and promised delivery dates. The purchase cohort contains 97,559 orders; other statuses are reported separately.
- **Promise-maturity sensitivity:** Requiring the promised date to fall before the observation end retains 94,700 completed deliveries. Adding a 30-day grace retains 94,539. The main completed-delivery rate uses the fixed purchase window and does not present this as a per-order 60-day rule.
- **Late delivery:** Actual delivery calendar date after the estimated delivery calendar date. Same-day delivery counts as on time.
- **Order grain:** One row per order. Items are aggregated before joining. Multiple review rows are averaged to an order-level score.
- **Stage eligibility:** Nonnegative purchase-to-handoff, handoff-to-delivery, and purchase-to-promise intervals. One delivery lacks a carrier timestamp and 174 have invalid chronology. Of 6,503 late deliveries, 6,500 have valid stage data.
- **Handoff states:** `past promise` means the promised date was already breached at handoff. The actionable warning population is strictly **0–3 calendar days remaining**. The groups are mutually exclusive.
- **Seller deadline:** Exact carrier-handoff timestamp compared with the latest item shipping-limit timestamp for single-seller orders. Same-day but after-time handoffs count as after deadline.
- **State adjustment:** Expected late orders use pooled late rates within purchase-month × promise-window cells. Excess late orders equal observed minus expected. Displayed states have at least 1,000 eligible deliveries.
- **Low review:** Mean order review score of 1 or 2. Standardized rates use state × purchase-month strata with at least 10 late and 10 on-time reviewed orders.

## Decision evidence

| Question | Supported answer | Limit |
| --- | --- | --- |
| How large is the problem? | 6,503 of 94,702 eligible completed deliveries were late: 6.87%. | This is not an all-order fulfillment KPI; unresolved statuses are separate. |
| When did failures concentrate? | February–March 2018 contributed 2,254 late deliveries, 34.7% of all late deliveries from 14.3% of volume. November 2017 was another spike. | Weather, labor, capacity, and carrier events are unavailable. |
| Was intervention possible? | The 0–3 day warning flags 840 orders; 358 were late: 42.6% precision and 5.5% recall. Another 322 late orders were already breached at handoff. | Retrospective classification does not prove an intervention can recover an order. |
| Where should investigation begin? | RJ had about 661 excess late deliveries and BA about 176 after basic adjustment. | Origin, destination lane, carrier, and route events are missing. |
| Can promise policy conceal slow service? | More-than-30-day promises had a 5.0% late rate but a median actual delivery time near 15 days. | Conversion and customer expectation measures are unavailable. |
| Why does it matter? | Standardized low-review rates were 58.1% late versus 9.4% on time. | Common support retains 68,416 orders; delivery and review are associated, not causally isolated. |

## Uncertainty

State excess and review differences use 1,000 deterministic stratified order-bootstrap replicates. Within each state × month × promise cell—or review common-support cell—resampling binary outcomes is equivalent to a binomial draw with the observed cell rate.

Intervals describe sampling variation around the historical adjusted comparison. They do not correct omitted carriers, routes, products, service recovery, or other unmeasured factors.

## Validation coverage

`validate.py` independently checks:

1. headline orders, late deliveries, and February–March late deliveries directly from source orders;
2. stage eligibility, breached orders, the mutually exclusive 0–3 day warning, precision, recall, and long-slack share;
3. exact-timestamp seller deadline populations and rates;
4. review common-support counts and standardized rates using independent DuckDB SQL;
5. aggregate reconciliation across monthly, promise, handoff, state, review, and interval outputs.

## Three proposed tests

### 1. Pre-breach warning

- Randomize eligible 0–3 day orders to intervention or holdout.
- Track actual delivery time, late rate, recovered deliveries, false alarms, cost, and customer outcomes.
- Scale only when the interval excludes zero and cost per recovered order is acceptable.

### 2. RJ and BA route pilot

- Add carrier, seller origin, pickup, hub, lane, and delivery-attempt events.
- Compare comparable lanes using randomized or carefully matched holdouts.
- Stop if the apparent improvement comes only from extending promised dates.

### 3. Promise and communication test

- Test clearer promise setting and proactive updates independently where possible.
- Measure conversion, actual speed, late rate, low reviews, contacts, and refunds.
- Do not scale if the SLA improves while actual delivery speed does not.

Historical evidence identifies where to test—not what is already proven.
