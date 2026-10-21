# Methods, hard questions, and proposed tests

## Population and definitions

- **Source and time:** Historical Olist orders. Purchases from 2017-01-01 through 2018-08-18 13:22:46, a 60-day maturity buffer before the last observed customer delivery on 2018-10-17.
- **Headline denominator:** 94,702 orders marked delivered with actual customer delivery and estimated delivery dates. There were 97,559 orders of all statuses in the purchase cohort. The gap is excluded, not assumed on time or lost.
- **Late order:** Actual delivery **date** after the estimated delivery **date**. Same-day delivery counts on time regardless of hour.
- **Order grain:** One row per order. Order items are grouped before joining; reviews are averaged to one order score before joining. Payment rows are not used.
- **Stage eligibility:** Nonnegative purchase-to-handoff, handoff-to-delivery, and purchase-to-promise intervals. One delivered order lacks a carrier timestamp and 174 have invalid stage chronology; stage metrics exclude those records. Of 6,503 late orders, 6,500 have eligible stage data.
- **Handoff slack:** Estimated delivery calendar date minus carrier handoff calendar date. A short-buffer alert means at most three days remain. Alert counts and precision are retrospective measures.
- **State adjustment:** Expected late orders sum pooled late rates in purchase-month × promise-length cells over each state's orders. Observed / expected above 1 signals more late orders than this simple mix predicts. Displayed states have at least 1,000 eligible deliveries.
- **Review comparison:** A low review is a mean order score of at most 2. Standardized late and on-time rates use comparable customer-state × purchase-month strata. Review coverage is 99.3% of the headline delivered cohort; response selection remains possible.

## Questions a headline SLA overlooks

| Question | Answer supported by this dataset | Remaining uncertainty |
| --- | --- | --- |
| Was the promise already impossible at carrier handoff? | 322 of 6,500 stage-eligible late orders were already past the promise at handoff. | Handoff time does not expose pickup attempts, warehouse holds, or scans. |
| Can a handoff alert catch most late deliveries? | At ≤3 days, precision is 680/1,162 = 58.5%; recall is 680/6,500 = 10.5%. | The useful threshold depends on capacity, costs, and lead time. |
| Is risk temporary or broad? | February–March 2018 accounts for 34.7% of late orders but 14.3% of deliveries. | No incident, weather, labor, or capacity records explain the spike. |
| Are regions comparable? | State ratios adjust only purchase month and promise length. RJ and BA are about 1.8. | Origin-destination lanes and carrier mix may explain the residual. |
| Could a better SLA be cosmetic? | Longer promises can lower the measured late rate without faster delivery. The report displays actual time alongside promise cohorts. | Conversion and expectation data are needed to judge promise-policy changes. |
| Did seller delay cause transit misses? | Single-seller orders handed off after their shipping limit have higher late rates. | Seller mix, products, destinations, and carrier schedules may confound this. |
| What is the financial return? | It cannot be calculated. Freight value is charged to the buyer, not actual freight expense. | Need carrier invoices, refunds, support contacts, margin, and intervention costs. |
| What about orders never delivered? | They are outside the delivered-order late-rate denominator and reported separately by status. | A full fulfillment KPI needs mature, resolved orders and cancellation reasons. |

## A decision-ready pilot

1. **Instrument the journey:** Collect seller ready time, carrier pickup, hub scans, delivery attempts, carrier, origin-destination lane, promised date, and costs at order grain.
2. **Pilot the handoff alert:** Apply the ≤3-day trigger to a randomized subset of eligible orders. Record interventions, false alarms, recovered deliveries, cost, and customer outcomes. Keep a holdout.
3. **Investigate long-slack misses:** Segment the 69.4% of stage-eligible late orders that had >14 days at handoff by comparable lane and promise cohort. Prioritize lanes by absolute late volume, then test a route-specific change.
4. **Measure customer outcomes:** Track actual delivery time, late rate, low reviews, support contacts, and refunds. A later promised date alone is not evidence of improved service.
5. **Report uncertainty:** Compare pilot and holdout on the same eligibility rule and period. Publish counts, effects with uncertainty intervals, and costs before scaling.

The project provides a prioritization framework and hypotheses. It does not establish that a specific carrier, seller, or route caused the observed misses.
