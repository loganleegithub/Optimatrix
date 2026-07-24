# Short Vol Radar

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Product authority:**
[`../authority/PRODUCT_CONSTITUTION.md`](../authority/PRODUCT_CONSTITUTION.md)

**Permission authority:** [`../authority/CURRENT_STAGE.md`](../authority/CURRENT_STAGE.md)

**Structural authority:**
[`../authority/SYSTEM_ARCHITECTURE.md`](../authority/SYSTEM_ARCHITECTURE.md)

**Delivery authority:**
[`../authority/DELIVERY_CONTRACT.md`](../authority/DELIVERY_CONTRACT.md)

This contract specifies stable Short Vol business semantics and the behavior authorized by the
current stage. [`CURRENT_STAGE.md`](../authority/CURRENT_STAGE.md) is the authority for what is
implemented versus merely authorized next. Historical bounded acceptance behavior is labeled
below and must not be mistaken for the Online Runtime lifecycle. Code and tests do not silently
amend this contract.

## Pipeline

```text
one continuously captured canonical public fact stream
→ rolling strict-as-of market and risk state
→ repeated authorized-universe scan cycles
→ legal 1:1 vertical pairs and per-structure quote/executability readiness
→ finite-horizon insurance assessments for 30m / 1h / 2h / 4h
→ availability plus RESEARCH_CANDIDATE | WATCH | ABSTAIN when evaluable
→ separate immutable Shadow admission
→ asynchronous strictly future actual and labeled counterfactual evaluation
```

`RESEARCH_CANDIDATE` is the current public-Shadow schema name for a candidate-class research
decision. It grants no trading authority.

## Operating semantics

**Implementation status:** the operating, observation, Policy-boundary, and scan-accounting
semantics before the historical appendix are the authorized `RADAR_ESTABLISHMENT` target and are
**not yet implemented**. Their prospective identities are
`DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT`,
`OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY`, and
`SHORT_VOL_RADAR_SCAN_SUMMARY`. They must not be persisted under the existing input, Policy, or
DecisionReceipt identities. The currently implemented bounded behavior remains the compatibility
contract in the explicitly non-active historical appendix below.

1. Market facts flow through one shared collector and tape used by scans and later Outcomes. A
   structure, Decision, or Entry does not start a new collector. This is not a network
   exactly-once guarantee; duplicates and conflicts remain canonical evidence.
2. Sixty minutes is a rolling feature lookback, not a run duration or a delay between scans.
   Warm-up is needed only when required history is genuinely unavailable.
3. Reconnect does not erase history already proved complete. The disconnected interval is
   `UNKNOWN` until sequence continuity or a separately authorized backfill positively covers it.
   Backfill may restore only future scan readiness and never rewrite an earlier Decision.
4. Market-global risk readiness, universe coverage, per-structure quote/executability readiness,
   Policy action, and Shadow admission are separate states. One may not erase the others.
5. Missing or stale price/depth facts for one instrument make dependent structures unavailable,
   not every otherwise complete structure. An explicitly declared market-global Policy feature
   may still depend on aggregate facts; coverage loss remains explicit.
6. `UNKNOWN` availability is not economic `ABSTAIN`. Zero Candidate is a numeric observation only
   over a nonzero Policy-evaluable-assessment denominator.
7. Bounded captures, fixed cutoffs, long evidence runs, and replay bundles are validation
   harnesses or historical artifacts, not the product's processing lifecycle.
8. Actual Shadow Outcomes and rejected-opportunity counterfactual evaluation are distinct; neither
   public quotes nor counterfactuals are fills.

## Observation semantics

Every window separately records collector-elapsed feed coverage and Deribit market-time price
coverage. Coverage may be restored from persisted canonical facts. A reconnect does not delete
prior complete history, but its disconnected interval is incomplete unless continuity or
authorized backfill positively proves the required facts.

Canonical observation uses four distinct domains:

- `capture_seq` is the sole known-at and causal order for DecisionFrame inputs;
- `collector_received_at_ms` preserves the raw local wall-clock receive time and may regress;
- `collector_elapsed_ms` is persisted monotonic session time for warm-up, quote freshness,
  subscription coverage, gaps, and reconnects;
- Deribit source timestamps define the reference market watermark, price/trade sample windows,
  option TTE, and surface as-of calculations.

No known-at, warm-up, or freshness decision compares a Deribit timestamp numerically with the
collector wall clock. A source timestamp later than its raw local receive timestamp is retained as
clock-skew evidence, not rejected or clamped.

Cross-channel known-at order is always `capture_seq`. An option fact already captured is not
discarded merely because its Deribit source timestamp is later than the latest reference-channel
watermark; each fact retains its own source time and age, and any alignment anomaly remains
explicit.

The reference path is exactly `BTC_USDC-PERPETUAL` ticker `index_price`. Ticker `last_price`,
perpetual `mark_price`, and trade prices never substitute into that path: mark remains descriptive
basis input and trades remain flow input. The accepted bounded Market/Decision input contract is
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`; its content digest is separate from the accepted
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY` identity and digest. The target semantics belong only to
`DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT`.

- Price elapsed coverage is necessary but not sufficient. A complete price path requires an
  accepted reference-price anchor at or before the requested Deribit market start, an endpoint at
  the current reference market watermark, the full requested source-time span, and watermark
  progress observed within the existing reference freshness limit. Otherwise the path is
  `UNKNOWN`; fully covered unchanged prices remain observed zero.
- Platform tradability is scoped to the current WebSocket connection generation. `OPEN` requires
  the current generation's accepted `platform_state` subscription-start fact followed by a later
  canonical `public/status` fact. Before that barrier the state is `UNKNOWN`; an observed positive
  maintenance or BTC-USDC index lock is immediately `LOCKED`. An absent maintenance notification
  remains unobserved metadata and is never fabricated as `false`. This is a Policy/admission fact,
  not a prerequisite for computing market-path risk.
- Complete flat prices produce observed zero return, range, and variation.
- Complete trade coverage with no trades produces observed zero flow.
- An incomplete window has no path or flow value.
- Only windows actually consumed by the immutable deployed Policy are hard readiness
  dependencies. Under the present observed-path formula these are 1m and 60m price observations
  and 1m flow. Additional 5m / 15m / 30m price or longer flow windows are diagnostics unless a new
  Policy identity explicitly consumes them.
- A visible option price without its corresponding amount has unknown depth, never numerical zero.

The accepted bounded Policy contains a scheduled-block predicate, but the current production
adapter has no authorized `SCHEDULED_BLOCK_STATE` producer. Its absence remains `UNKNOWN` under
that historical identity and is never fabricated as `CLEAR`. The target
`OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY` adds no source and removes this unavailable fact
from economic Candidate eligibility. A future Shadow-admission contract may add a sourced
scheduled-event veto only through a separate authority change.

The runtime refreshes the same Deribit public option/future catalog every 300 seconds and requires
the latest complete snapshot to be no more than 360 seconds old at scan time. Each snapshot
includes the 0–72h Decision range plus only the 360-second expiry-transition buffer; the projector
still scans exactly 0–72h. A complete snapshot binds reference membership, every member's
same-generation instrument source sequence, and the canonical metadata-set digest. A failed
refresh publishes no new generation.

Catalog completeness and quote readiness are different. A missing/stale catalog generation makes
complete-universe coverage `UNKNOWN`. Inside a known generation, a missing, stale, or
depth-unknown quote makes only structures using that instrument unavailable. It is reported in
coverage and unavailable-reason counts and does not suppress completed assessments for unrelated
structures. The Radar establishment closure uses the already implemented leg-quote execution path;
it does not authorize new combo acquisition. A later task may activate visible combo economics
under an explicit input-contract change.

## Risk method

The deployed method is `OBSERVED_PATH_STRESS_FIXED_PRIOR`. It is a transparent, deterministic
research prior, not a calibrated probability model. It scales complete observed range/variation
into a candidate horizon and adds explicit multipliers for:

- short/long-window acceleration;
- directional efficiency;
- maximum observed jump;
- quote-age dispersion;
- side-aligned aggressor/liquidation flow;
- a current breakout.

Any missing required path or flow coverage returns incomplete risk and fails closed.

The present formula and its quote-age treatment remain uncalibrated Policy behavior. In
particular, current whole-universe quote-age dispersion is an explicitly market-global dependency;
localizing price/depth availability does not silently localize that multiplier.
`RADAR_ESTABLISHMENT` may separate readiness and health diagnostics but may not tune these
multipliers or reinterpret them as demonstrated edge.

## Insurance reserve

For each candidate vertical and horizon, the deployed assessment freezes:

- visible entry credit and immediate close debit;
- entry and close fee upper bounds;
- maximum loss;
- short-strike distance;
- stress intrinsic payout;
- residual time-value floor;
- liquidity and method-uncertainty reserves.

`ResidualTimeValueFloor` is:

```text
entry-frame immediate close notional
× sqrt(max(TTE - horizon, 0) / TTE)
```

The claim reserve is the larger of that floor and stress intrinsic payout. This is a fixed,
falsifiable prior; future Shadow outcomes must determine whether it is conservative enough.

## Deployed bounded Policy predicates

The accepted bounded Policy identity currently requires all predicates below for a
candidate-class action. This list records deployed compatibility; it does not collapse the Radar
funnel back into one global readiness flag. In particular, platform and scheduled-block facts are
currently folded into candidate eligibility. Its broad `complete current frame` and four-sided-leg
requirements are legacy predicates, not statements that the target input contract is already
implemented.

A research candidate requires all of:

- complete current frame and complete risk;
- TTE greater than horizon plus settlement buffer;
- visible four-sided quantity and immediate close;
- credit/friction ratio at least 2.5;
- short-strike distance at least 1.25 times adverse stress;
- minimum premium/max-loss ratio;
- no same-side breakout or directional-flow veto;
- a current-generation platform barrier establishing `OPEN`, and no scheduled block;
- positive conservative insurance margin.

The target `OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY` preserves the horizons, economic
formulas, thresholds, reserves, platform predicate, non-schedule vetoes, ranking, and legacy WATCH
mapping above. Its only Policy delta is removing the scheduled-block predicate. Legacy WATCH means
the best-ranked completed assessment when none passes; it does not mean near-threshold,
actionable, or likely to become a future Candidate.

The preserved universe and sizing parameters are exact: OTM-only 1:1 same-expiry same-side
verticals, TTE from 1,800 through 259,200 seconds, quantity `0.04`, configured horizons
`(1,800, 3,600, 7,200, 14,400)` seconds, and a 1,800-second settlement buffer. Every legal
structure is paired with all four configured horizons. `TTE_BUFFER` remains a Policy predicate and
may not be moved into denominator filtering.

## Scan availability and denominator accounting

Each due scan reports linked ledgers without mixing units:

- cycle counts: due, executed, globally risk-ready, and action cycles;
- `legal_structure_count`: authorized active same-expiry, same-side verticals with valid
  short/long strike order, compatible contract size, OTM-only legs, and TTE from 1,800 through
  259,200 seconds;
- `quote_observable_structure_count`: legal structures with observations needed by the current
  leg-quote execution path;
- `round_trip_executable_structure_count`: observable structures with valid entry and
  immediate-close sides, sufficient depth for quantity `0.04`, and positive visible entry credit;
- `assessment_opportunity_count`: legal structure × all four configured horizons, before any
  horizon-specific Policy predicate is applied;
- `completed_assessment_count`: structure/horizon opportunities with all required market-risk,
  cost, liquidity, and reserve inputs;
- `policy_evaluable_assessment_count`: completed assessments for which every target Policy
  predicate fact is available;
- `passing_assessment_count`: Policy-evaluable assessments that pass every target candidate
  predicate.

Each item has one terminal funnel stage and zero or more diagnostic reasons; multiple simultaneous
causes are not discarded to manufacture one primary reason. Candidate observations, candidate
scan cycles, distinct deduplicated opportunity episodes, admitted Entries, and mature Outcomes
remain separate measures.

Availability is independent from action:

```text
evaluation_status = COMPLETE | PARTIAL | UNKNOWN
policy_action = RESEARCH_CANDIDATE | WATCH | ABSTAIN | null
```

Only a Policy-evaluable assessment can contribute to an economic action. The target
`policy_action` is `null` for unavailable evaluation. A legacy safety `ABSTAIN` compatibility
output remains separately labeled and is excluded from Policy action rates.

A denominator is numeric only when its upstream scope is known. Unknown catalog or universe scope
makes legal-structure and dependent counts/rates `null/UNKNOWN`, never zero. Zero is valid only
after the relevant scope and readiness boundary were completely observed. With
`policy_evaluable_assessment_count > 0`, zero Candidate describes only the evaluated window or,
under partial coverage, the evaluated subset; it does not prove Policy value or complete-universe
absence.

## Target Radar scan summary

Every due cycle emits one prospective `SHORT_VOL_RADAR_SCAN_SUMMARY` with:

```text
cycle_status = EXECUTED | SKIPPED | UNAVAILABLE
```

The due time/trigger identity and target input/Policy identities are always present.
`SKIPPED` and `UNAVAILABLE` require a non-empty exact reason; frame, as-of sequence, assessment,
Policy action, and any downstream denominator whose scope was not known are `null`. `EXECUTED`
means the scanner actually projected and evaluated the available as-of state; its
`action_cycle_count` is one exactly when `policy_action` is non-null, otherwise zero.

For an executed cycle, the summary freezes as available:

- current frame identity and source lineage;
- audit Git commit, authoritative scoped runtime-source digest, and immutable deployed Policy
  identity/digest;
- legal-universe identity and every funnel denominator above;
- global risk-input readiness, universe coverage, and structure-readiness summaries;
- unavailable and predicate-failure reason summaries;
- selected assessment, predicates, and ranking result;
- the exact action and reason.

It refers to sealed segment identity plus the exact as-of `capture_seq` when present,
frame/lineage digest, ledger counts and reasons, assessment-set digest, selected assessment when
present, exact availability/action, and its own content digest. It does not change or impersonate
the existing `SHORT_VOL_DECISION_RECEIPT` schema and need not duplicate reconstructable rolling
lineage.

The Git commit is audit provenance. Every legal structure/configured-horizon pair is an assessment
opportunity; quote or executability filters may not erase it before denominator accounting.
Predicate failures remain separate from availability diagnostics over incomplete assessments.

## Queued forward-cohort semantics

The following Outcome and rejected-opportunity behavior is product direction for the later
Fixed-Policy forward cohort. `RADAR_ESTABLISHMENT` does not implement or invoke it.

Every Shadow entry must freeze its Decision, structure, entry economics, assessment, horizon, and
Policy identity. Observed Outcome contains only facts strictly after entry and no later than actual
exit. Any continued full-horizon path is a separately labeled counterfactual.

When a later stage authorizes a forward cohort, a pre-registered sample of complete rejected
assessments may be evaluated from facts strictly after its Decision to measure false negatives and
reserve conservatism. This `POLICY_REJECTION_COUNTERFACTUAL` is not a Shadow Entry, actual
exposure, fill, or observed Policy PnL and does not require an online fact seal per rejected
structure.

When a task marks replay `REQUIRED`, equality reconstructs only identities derivable from the
minimal sealed input. It is determinism evidence, not qualification.

## NON-ACTIVE HISTORICAL APPENDIX — bounded Outcome Truth

No current task inherits this appendix's 3,600-second duration, fixed cutoff, retry, connection
ceremony, CLI, bundle, or replay requirements unless `CURRENT_STAGE.md` and that task's evidence
matrix explicitly name the historical `PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH` contract.

This section preserves the accepted `OUTCOME_TRUTH` artifact meaning for deterministic
compatibility. Its one cutoff, one admission, connection proof, CLI, and bundle behavior describe
that historical bounded acceptance harness. They do not define the continuous Radar lifecycle,
the current next closure, or a requirement to wait for every Outcome before scanning again.

The Outcome/evaluation contract is `PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH`. It adds only the
bounded Outcome behavior and artifacts below:

- the Market/Decision input contract remains `DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`, including
  the accepted `SHORT_VOL_DECISION_RECEIPT` schema and meaning;
- the Decision Policy remains `OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY`, with no change to its
  horizons, structures, formulas, thresholds, reserves, vetoes, ranking, or candidate predicates;
- the Outcome/evaluation axis adds `SHORT_VOL_SHADOW_ENTRY_RECEIPT`,
  `SHORT_VOL_OUTCOME_FACT_SEAL`, and `SHORT_VOL_OUTCOME_RECEIPT` under the new Outcome contract;
- the permission boundary remains bounded `PUBLIC_SHADOW`. This contract does not authorize a
  cadence, retrying scan, Run receipt, qualification, private/account data, or execution.

Existing non-durable `ShadowPosition`, `OutcomePath`, and `MaturedOutcome` values remain synthetic
regression inputs only. They are not durable Outcome Truth artifacts or historically comparable
qualification Outcomes. Their package-root `OutcomeStatus` and `OPEN` value remain unchanged for
legacy compatibility; the new exact durable enum is public as `shadow_engine.truth.OutcomeStatus`
with only `CLOSED`, `UNEXITABLE`, and `UNKNOWN`.

### Historical cutoff and admission

One run fixes exactly one Decision cutoff before inspecting any Outcome suffix: the first canonical
event after the initial required subscriptions have accumulated 3,600 seconds of
collector-elapsed time. Missingness, contamination, or reconnect may make that cutoff Decision
incomplete, but may not move the cutoff, select a later Decision, or trigger a retry.

The one admission result is fail-closed:

- `UNKNOWN`: the cutoff Decision or its binding evidence is incomplete; Entry and Outcome receipt
  counts are both zero;
- `NO_ENTRY`: the cutoff Decision is complete and its action is `WATCH` or `ABSTAIN`; Entry and
  Outcome receipt counts are both zero;
- `ADMITTED`: and only a complete `RESEARCH_CANDIDATE` whose receipt, frame, selected assessment,
  Policy, sequence, entry prices, amounts, and depth all bind exactly may create one Entry receipt.

Admission never changes thresholds to manufacture activity. Receipt, frame, assessment, Policy,
or sequence drift is an error, not another chance to scan. If an admitted entry later lacks
complete future evidence, it still produces one `UNKNOWN` Outcome with null observed executable
PnL.

This “no later cutoff” rule prevents result selection inside that historical artifact. It does not
forbid the continuous runtime from performing later scheduled scans, recovering after a recorded
failure, or starting a new predeclared session while retaining the failed attempt and gap.

### Immutable artifacts and identities

`SHORT_VOL_SHADOW_ENTRY_RECEIPT` binds the exact accepted Decision receipt and digest, Decision
frame and selected assessment, deployed Policy identity/digest, frozen structure and quantity,
entry credit, executable depth, fees, maximum loss, entry causal sequence, entry-generation
platform-control anchors, and Outcome contract/runtime identities.

`SHORT_VOL_OUTCOME_FACT_SEAL` binds the original sealed full-capture identity, the fixed cutoff,
the Decision prefix and strictly post-entry suffix boundaries, every retained future market and
platform-control fact, their causal lineage, and its own content digest. It is closure-specific;
it is not a generic capture or storage format.

`SHORT_VOL_OUTCOME_RECEIPT` binds the Entry receipt and fact-seal digests, Outcome
contract/runtime identities, actual-exposure and optional counterfactual path digests, selected
exit or bounded failure status, executable close assessment, observed result, complete lineage,
and its own content digest. A fresh process must reproduce all derivable fields and digests from
the sealed inputs; a mismatch or tamper fails verification. The receipt JSON is not a standalone
trust anchor: acceptance requires byte-verified fact-seal reconstruction and fresh replay. Merely
rehashing modified receipt content never validates it against the sealed tape.

### Strictly future facts and control lineage

Every market or platform-control fact used for reference price, tradability, close economics,
touch, excursion, or exit has `capture_seq` strictly greater than the Entry sequence. Entry facts
and the Entry connection's platform anchors remain frozen in the Entry receipt but cannot be
reused as future evidence.

An executable future close requires a connection-scoped platform barrier in the future suffix: an
accepted `platform_state` subscription-start fact for that connection generation followed by a
later canonical `public/status` fact. Entry-only `OPEN` is insufficient. Reconnect invalidates the
prior barrier and requires a new future subscription/status pair before a close can be executable.
The bounded Outcome collector waits until the fixed Decision cutoff has actually been selected,
then obtains an acknowledged platform-only subscription refresh and a later `public/status` on
the active connection. Those facts are Outcome-only suffix evidence: they cannot change the
already frozen Decision prefix or its receipt.

That same-connection refresh is a compatibility rule for this bounded artifact, not a general
requirement to resubscribe after every future Entry. A future Outcome-contract change may use
lifecycle-valid platform state until reconnect or an observed state change, but this authority
task does not alter the accepted receipt meaning.
Missing or stale reference, quote side, amount, platform proof, or causal lineage is `UNKNOWN`;
known platform lock, reference closure, or complete visible depth below the frozen quantity is
`UNEXITABLE`. A stale future reference keeps its concrete source sequence in the point-level
lineage even though its reference value is unusable.

Each future close observation is classified independently as `EXECUTABLE`, `UNEXITABLE`, or
`UNKNOWN`. `EXECUTABLE` means all visible close economics, frozen-quantity depth, future platform
proof, and lineage are complete. `UNEXITABLE` means the required facts are complete and establish
a known inability to close. `UNKNOWN` means the observation is missing or invalid and cannot be
used to infer either execution or known inability. The evaluator independently checks the frozen
input-contract identity and a non-boolean integer quote age within the frozen limit; truthy
non-booleans cannot impersonate `fresh` or `valid`. A blank combo identity is invalid. Duplicate
latest combo facts or duplicate leg facts are conflicting evidence and remain `UNKNOWN` when no
other independently complete close path is executable. An observed stale, invalid, or conflicting
combo cannot disappear into a leg-depth `UNEXITABLE` classification.

### Actual exposure, exit, and counterfactual

Actual exposure starts at Entry and examines future points once in increasing `capture_seq` order.
The first executable exit condition wins. If multiple conditions hold at the same point, priority
is `PROFIT_TARGET`, then `FIRST_TOUCH`, then `HORIZON`. No later fact may change the selected exit,
touch, excursion, or observed PnL.

Reaching the horizon arms the `HORIZON` exit condition; it does not by itself end exposure.
An `UNKNOWN` or `UNEXITABLE` close observation at or after the horizon is non-terminal, and the
actual path continues until the first later executable close or data end. If no executable close
appears, the last observation at or after the horizon supplies the bounded failure status and
evaluation sequence. Earlier temporary missingness or inability is not sticky.

The actual path ends at the selected exit, inclusive. Any retained point after that exit belongs
only to a separately labeled, unscored counterfactual path. It cannot contribute to actual touch,
excursion, max-loss-region, holding time, close, or PnL fields.

Excursion uses Entry as an explicit zero baseline once at least one valid strictly future reference
fact exists. Actual maximum-up and maximum-down excursion therefore include zero and use only the
actual path through exit. With no valid future reference fact, excursion and touch remain
`UNKNOWN`; Entry alone is not evidence of an observed zero path.

### Outcome status and observed PnL

- `CLOSED` requires a visible executable close with complete price sides and amounts, depth at least
  the frozen quantity, complete future platform proof, and complete lineage. It alone records an
  executable exit sequence, close debit and fee, and observed PnL. PnL is frozen gross entry credit
  less executable close debit times frozen quantity and contract size, entry fee, and close fee.
- `UNEXITABLE` records a known inability to close, such as an explicit platform/reference closure
  or complete visible depth below frozen quantity. Close debit, observed PnL, and executable exit
  sequence are null. Frozen maximum loss may remain risk context but is never substituted for
  observed PnL.
- `UNKNOWN` records missing, stale, incomplete, contaminated, or invalid future evidence. Close
  debit, observed PnL, and executable exit sequence are null; absence is never represented as zero
  or `UNEXITABLE`.

### Evidence and non-claims

Outcome Truth requires two distinct evidence layers. Deterministic synthetic evidence must exercise
an admitted nonzero Entry/Outcome path and boundary failures. A fresh production-public bounded
capture may honestly produce zero admission or an admitted `UNKNOWN`; it proves only the facts it
contains. Fresh-process replay must verify the full-capture identity, fixed prefix/suffix boundary,
Decision, admission, Entry, fact seal, Outcome, lineage, and zero drift for each layer.

Historical CLI names, bundle layout, invocation witness, checksums, report rendering, and archived
replay procedure remain versioned implementation evidence for the accepted bounded contract. They
are not active trading semantics and are required by a later task only when its evidence matrix
names them. Process witness verifies the named process evidence, not third-party network
attestation.

Synthetic success is not production Outcome evidence. A public zero result is not failure or
profitability evidence. Visible public quotes are not fills. Matching receipts and replay digests
prove deterministic reconstruction only; they do not prove Policy quality, qualification,
continuous Shadow operation, promotion, account access, execution, or capital authority.

## Non-goals

The current contract does not claim calibrated touch probability, dealer positioning, causal
market classification, optimal thresholds, strategy qualification, or automatic self-evolution.
