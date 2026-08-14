# Optimatrix Current Stage

**Status:** B3 STRESS RISK RESERVATION — CLOSED

**Current maturity:** `B3_ATOMIC_PUBLIC_SHADOW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

## Current permissions

Stage is the permission ceiling; a future active task may only narrow it.

**Offline checks and simulation:** authorized only in caller-supplied ignored roots

**Public market calls:** `NONE_AUTHORIZED`

**Stable ObservationLedger root:** `NONE_AUTHORIZED`

**Disposable offline ObservationLedger:** authorized only under caller-supplied ignored roots

**Stable CaseJournal root:** `NONE_AUTHORIZED`

**Frozen prior evidence:** `/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1`
is retained without migration or mutation and remains ineligible for the current Policy.

**Continuous runtime:** `NONE`

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current implementation truth

- Entry reunderwriting requires later environment, exact frozen structure, economics, allocation,
  and route evidence to pass before a Shadow Position exists, and its complete Decision-to-Entry
  result remains recoverable.
- Policy schema 7 gives new Decisions, allocations, and Cases identities distinct from schema-6 and
  frozen v1 evidence.
- `ShadowRiskAllocation` records nominal contractual payoff, boundary-valued exit-cost stress,
  every inverse-delivery stress, their maximum delivery loss, and one conservative stress reserve.
  The reserve is exactly the maximum of nominal payoff, exit stress, and maximum delivery stress.
- The same reserve and metric own Decision admission, Session aggregation, the frozen allocation
  record, Case validation, restart reconstruction, and terminal release. Missing, malformed,
  identity-incoherent, or retired-metric allocation records fail closed rather than contributing an
  invented zero.
- The adversarial deterministic Candidate has `200 USD` nominal payoff and `402 USD` exit stress.
  With `300 USD` already reserved against the unchanged `600 USD` Session budget, it is rejected;
  the former nominal-only permissive branch is therefore absent.
- The complete repository gate passes: `193` tests and `8` deterministic business scenarios. This
  is offline implementation evidence, not current market, execution, or profitability evidence.
- Live runtime, stable-root writes, market calls, private facts, orders, and capital remain disabled.

**Primary blocker:** `ROUTE_EVIDENCE_NOT_TYPED` — Public Shadow Entry still represents its route as
a pricing-basis label plus blocker strings instead of one identity-bearing evidence record with an
explicit route kind, full-ratio amount, causal source cut, and evaluability result.

## Maturity ladder

- `A0_AUTHORITY_CORRECTION` — one owner per concept, explicit truth layers, and no cross-layer
  inference.
- `B1_WINDOW_OBSERVATION` — causal all-Window ObservationLedger and measured reachability.
- `B2_STRUCTURE_PRICING` — route-independent whole-four-leg discovery and inverse-unit economics.
- `B3_ATOMIC_PUBLIC_SHADOW` — complete whole-product Shadow Case, monitoring, terminality, and
  explanatory Outcome without fill claims.
- `C1_PRIVATE_READ_ONLY` — authenticated account truth with no order permission.
- `C2_AUTHORIZED_COMBO_EXECUTION` — separately authorized bounded Combo execution.
- `D1_OFFLINE_AI_CHALLENGER` — forward Outcomes support human-governed Challenger evaluation.

**Next closure:** a bounded `B3_ROUTE_EVIDENCE` task must replace the loose route label and blockers
with one typed, identity-bearing Shadow route-evidence record for the exact frozen four-leg ratios
and full target amount. It may not claim Combo executability or fills, change Entry underwriting or
risk numerics, enable live calls, or authorize private facts, orders, capital, or Policy promotion.
