# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Implemented runtime capability:** `NONE` — implementation under review; no accepted observation

**Production Short Vol Radar:** `NOT_ESTABLISHED`

**Sole authorized next product-capability closure:** `SHORT_VOL_RADAR_ESTABLISHMENT`

## Authority

This document grants permission under
[`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md). It does not own product definitions,
architecture, detector parameters, or evidence mechanics. Code presence, green tests, old
receipts, run duration, or roadmap order grant no stage.

The current boundary authorizes one implementation task inside the existing modular monolith:
establish the production-public Short Vol Radar defined by
[`SHORT_VOL_RADAR.md`](../contracts/SHORT_VOL_RADAR.md). Candidate, Shadow admission, executed
entry, Position runtime, Outcome cohort, private/account data, orders, fills, capital,
qualification, Challenger automation, promotion, and execution remain unauthorized.

Runtime construction and each production-public observation require their own explicit human
command. `REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` are independent per-run gates: authorization
or evidence for either one never opens the other. The
`OPERATIONAL_SOAK_PRECONDITIONS` construction gate is open for the active task; both
production-public gates remain closed.

## Reset baseline and current construction truth

The legacy bounded collector, replay path, fixed-horizon Decision logic, elapsed-time Shadow and
Outcome logic, receipts, and bundles have been physically removed. No compatibility layer remains.
The current construction branch adds only the guarded production-public Radar path; code presence
does not establish a runtime capability or open the production-observation gate.

Known-at inputs, explicit missingness and continuity, strictly future facts, and visible-quote
economics remain product invariants in authority. They are not claims of an implemented runtime
capability.

## Root blocker

The product has not yet established this continuous production-public path:

```text
live BTC-USDC 0–3DTE state
→ exact content-identified Short Vol detector
→ independent anomaly state
→ independent official atomic-combo quote state while anomalous
```

This blocker is runtime reachability, not proof that a rare natural anomaly or combo happens
during one observation. Until the path can produce at least one usable detector evaluation,
Candidate and Outcome work has no established Radar input.

## Authorized closure

`SHORT_VOL_RADAR_ESTABLISHMENT` may implement only:

- one continuous public WebSocket-fed, bounded in-memory BTC-USDC option-chain monitor;
- actual timestamp-based `0 < TTE <= 72 hours` membership, trusted Deribit time, and an explicit
  initial exclusion of the final 30-minute delivery-price window from the detector baseline;
- acknowledged subscription, snapshot/change continuity, known empty or insufficient depth
  versus `UNKNOWN`, and affected-scope recovery; a quiet continuous book does not expire merely
  because no price level changed, while acknowledged heartbeat/test-request handling prevents a
  half-open connection from preserving old state;
- one narrow `POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE` formula family whose exact target
  BTC quantity, Delta/TTE ranges, lookbacks, variance floor, trigger/clear ratios, persistence,
  and separation live in one content-identified Policy file;
- one Policy identity frozen from process start to stop, with no hot reload or in-process
  tuning;
- per-instrument `detector_state = UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE` plus a
  completeness-aware aggregate;
- independent per-short-leg-episode
  `public_atomic_quote_state = NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO |
  NO_TARGET_SIZE_CREDIT_QUOTE | PUBLIC_ATOMIC_QUOTE_AVAILABLE` for official same-expiry,
  same-option-type, 1:1 protective credit verticals;
- one minimal anomaly event on activation, a separate minimal atomic-quote event when available,
  and one bounded run summary.

The atomic layer reports only official public combo availability. It does not estimate fees,
maximum loss, Greeks-based structure quality, margin, future closeability, or maker feasibility.
Component-leg prices cannot substitute for an official combo quote. No Candidate, Shadow Entry,
Position action, or Outcome is emitted.

## Policy calibration boundary

The implementation must make the declared detector scope and numeric parameters configurable
rather than embed one claimed trading truth in code. Each production observation names one exact
Policy file and identity.

After a completed observation, a human may approve a successor inside the same authorized Policy
schema. It may change target quantity, TTE bands/gaps and call/put inclusion,
lookbacks/weights/floor, Delta boundaries, or activation/clear persistence. The successor receives
a new identity, process, and forward interval. Earlier events keep their original Policy meaning.
The runtime cannot train, select, approve, promote, or deploy a successor.

The current closure can compare operational coverage, `UNKNOWN` reasons, anomaly frequency,
clear/re-arm flicker, and official combo availability across forward intervals. Because it has no
strictly future realized-volatility or trade Outcome label, it cannot claim that a successor is a
better volatility forecast or trading strategy. Formula, source-family, structure-family, or
evaluation-claim changes require a separately authorized task.

## Acceptance boundary

Implementation readiness requires:

1. direct deterministic tests covering source namespaces and filters, continuity, quiet books,
   causal feature windows, configurable boundaries, detector episodes, gap termination/resync, the
   detector/combo separation, official combo direction and target depth, and minimal artifacts;
2. focused tests and `make check`;
3. inspection confirming that no replay, second calculator, full-market persistence, private
   path, maker path, or later-stage object was added.

Runtime establishment additionally requires two independently authorized and accepted
production-public observations. `REACHABILITY_SMOKE` must complete warm-up and produce at least
one known per-instrument evaluation inside one non-empty real
`Policy identity × expiry_timestamp × option_type` aggregate, then produce a complete aggregate
`NO_ANOMALY` or `ANOMALY_ACTIVE` result. At least one instrument must also pass all preliminary
eligibility gates and reach a known baseline/IV/Delta/richness calculation; short-circuit
ineligibility alone cannot establish the Radar. Empty scope cannot pass vacuously. A covered
`NO_ANOMALY` interval is valid reachability evidence. A degraded positive witness is truthful but
does not alone establish the full Radar. Natural anomaly occurrence and official atomic-quote
availability are separately reported `OBSERVED | NOT_OBSERVED`; neither is required for code
acceptance and neither may be forced through in-place tuning.

`OPERATIONAL_SOAK` must then satisfy its separately approved exact Policy, evidence-directory,
and stop-condition checklist. A Smoke authorization, run, or accepted witness proves no sustained
operation and grants no Soak authority. A Soak authorization likewise cannot retroactively supply
or relabel the Smoke reachability witness.

An all-`UNKNOWN` or pre-warm-up stop is truthful but does not establish runtime capability. Rates
with a zero or unknown denominator remain `null`.

This closure requires no replay, independent offline recomputation, provenance command,
full-market archive, Candidate, Shadow Entry, Position action, mature Outcome, profitability, or
fill evidence.

## Queued sequence — not authorized

After Radar establishment is explicitly accepted and this document is advanced:

1. **Underwriting, Shadow admission, and Position contract:** freeze
   `CANDIDATE | WATCH | ABSTAIN`, `HOLD | CLOSE | UNKNOWN`, hard-close priority, atomic
   entry/close economics, fee and maximum-loss handling, and any exact maker-versus-taker Policy.
2. **Fixed-Policy forward cohort:** record complete anomaly/quote opportunity, Decision, Shadow
   Entry, Shadow close, Shadow Outcome, rejected-counterfactual, and cohort-aligned `NO_TRADE`
   denominators.
3. **Challenger research and qualification:** authorize only after a usable frozen-Policy cohort
   and pre-registered qualification contract.
4. **Promotion and execution:** authorize separately after independent qualification. Account,
   capital, order, and fill authority remain distinct.

A queued closure is not active. Exactly one may be activated only by an explicitly approved
change after its prerequisite is accepted.

## Forbidden under the current boundary

- changing a Policy inside its observation interval or relabeling earlier events;
- calling operational calibration forecast validation, model-free VRP, or proven edge;
- attaching an atomic structure to an anomaly whose short leg is outside the triggered scope;
- treating component-leg quotes as an atomic structure or any public quote as a fill;
- full-market persistence, per-update no-anomaly receipts, replay, or offline recomputation as a
  prerequisite for this Radar;
- Candidate, Shadow admission, executed entry, Position runtime, or Outcome cohort behavior;
- automatic training, Policy selection, qualification, promotion, or evolution;
- generic databases, feature stores, registries, workflow engines, services, markets, or
  strategies;
- private/account APIs, test-environment market sources, credentials, balances, margin, positions,
  orders, fills, settlement, execution gateways, maker behavior, or money; production
  `public/test` is allowed only as the protocol-required response to an established heartbeat
  `test_request`.

Update this document in the same accepted change that changes permission, implemented capability,
blockers, or the sole authorized next closure.
