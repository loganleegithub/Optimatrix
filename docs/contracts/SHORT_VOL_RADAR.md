# Short Vol Radar

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Product authority:**
[`../authority/PRODUCT_CONSTITUTION.md`](../authority/PRODUCT_CONSTITUTION.md)

**Permission authority:** [`../authority/CURRENT_STAGE.md`](../authority/CURRENT_STAGE.md)

**Structural authority:**
[`../authority/SYSTEM_ARCHITECTURE.md`](../authority/SYSTEM_ARCHITECTURE.md)

**Delivery authority:**
[`../authority/DELIVERY_CONTRACT.md`](../authority/DELIVERY_CONTRACT.md)

This contract specifies the deployed Short Vol behavior. Code and tests do not silently weaken it.
Changes must use the input, Policy, Outcome, and authorization declarations defined by the
Delivery Contract.

## Pipeline

```text
Canonical public facts
→ strict DecisionFrame
→ complete 1m / 5m / 15m / 30m / 60m observations
→ finite-horizon observed-path stress
→ executable 1:1 vertical inventory
→ insurance assessment for 30m / 1h / 2h / 4h
→ RESEARCH_CANDIDATE | WATCH | ABSTAIN
→ one fixed-cutoff Shadow admission
→ zero entry or SHORT_VOL_SHADOW_ENTRY_RECEIPT
→ strictly future SHORT_VOL_OUTCOME_FACT_SEAL
→ SHORT_VOL_OUTCOME_RECEIPT
```

`RESEARCH_CANDIDATE` is the current public-Shadow schema name for a candidate-class research
decision. It grants no trading authority.

## Observation semantics

Every window separately records collector-elapsed subscription coverage and Deribit market-time
price coverage. Elapsed subscription coverage is complete only after the relevant subscription
has remained observed for the full requested duration, with no contaminating gap or reconnect.

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

The reference path is exactly `BTC_USDC-PERPETUAL` ticker `index_price`. Ticker `last_price`,
perpetual `mark_price`, and trade prices never substitute into that path: mark remains descriptive
basis input and trades remain flow input. The immutable Market/Decision input contract is
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`; its content digest is separate from the immutable
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY` identity and digest.

- Price elapsed coverage is necessary but not sufficient. A complete price path requires an
  accepted reference-price anchor at or before the requested Deribit market start, an endpoint at
  the current reference market watermark, the full requested source-time span, and watermark
  progress observed within the existing reference freshness limit. Otherwise the path is
  `UNKNOWN`; fully covered unchanged prices remain observed zero.
- Platform tradability is scoped to the current WebSocket connection generation. `OPEN` requires
  the current generation's accepted `platform_state` subscription-start fact followed by a later
  canonical `public/status` fact. Before that barrier the state is `UNKNOWN`; an observed positive
  maintenance or BTC-USDC index lock is immediately `LOCKED`. An absent maintenance notification
  remains unobserved metadata and is never fabricated as `false`.
- Complete flat prices produce observed zero return, range, and variation.
- Complete trade coverage with no trades produces observed zero flow.
- An incomplete window has no path or flow value.
- Every configured 1m / 5m / 15m / 30m / 60m price and flow window is required. One incomplete
  window makes finite-horizon path risk `UNKNOWN`.
- A visible option price without its corresponding amount has unknown depth, never numerical zero.
- Scheduled-block state is observed only through an explicit canonical fact with a non-empty source
  identity and an inclusive `valid_from_ms` / `valid_until_ms` market-time interval. Its absence,
  invalid source/interval, or a Decision `market_as_of` outside that interval is `UNKNOWN`, not
  confirmation that no block exists. A stale `CLEAR` never passes the no-block predicate; a
  reconnect does not renew a fact's validity.

The bounded runtime refreshes the same Deribit public option/future catalog every 300 seconds and
requires the latest complete snapshot to be no more than 360 seconds old at Decision time. Each
snapshot includes the 0–72h Decision range plus only the 360-second expiry-transition buffer; the
projector still scans exactly 0–72h. A complete snapshot binds reference membership, every member's
same-generation instrument source sequence, and the canonical metadata-set digest. Names and
metadata membership must match exactly and every member must be active; a failed refresh publishes
no new generation. The generation identity, names/metadata digests, counts, age, and causal
sequences are Decision lineage. A missing/stale/incomplete generation or missing member quote fails
closed; this is not a generic catalog service.

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

## Entry predicates

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

## Decision and Outcome evidence

Every candidate/watch/abstain Decision receipt must freeze:

- current frame identity and source lineage;
- audit Git commit, authoritative scoped runtime-source digest, and immutable deployed Policy
  identity/digest;
- complete scanned-universe and assessment-set identity;
- frame completeness and required-window/catalog/schedule/quote readiness summaries;
- assessment opportunity, unavailable and assessed counts, with unavailable and predicate-failure
  reason summaries;
- selected assessment, predicates, and ranking result;
- the exact action and reason.

`SHORT_VOL_DECISION_RECEIPT` is the sole durable Decision artifact for this closure. It binds the
sealed capture and manifest, final frame/readiness and complete lineage, audit Git commit,
authoritative runtime-source digest, input-contract and Policy identities/digests, option quote
set, complete executable-structure and assessment-opportunity sets, unavailable and predicate
failure summaries, deterministic assessment set, full selected assessment when present, exact
decision, and its own content digest. Zero structures, assessments, or candidate-class actions
remain valid explicit counts.

The Git commit is audit provenance. `runtime_source_digest` is the authoritative reconstruction
identity over the declared Decision runtime source scope. Replay may use a different commit only
when that digest is identical; a changed digest or dirty file inside the identity scope fails.
Every executable structure/configured-horizon pair is one assessment opportunity. The receipt
partitions all opportunities into assessed or unavailable and aggregates deterministic unavailable
reasons; predicate failures remain a separate summary over completed assessments.

Every Shadow entry must freeze its Decision, structure, entry economics, assessment, horizon, and
Policy identity. Observed Outcome contains only facts strictly after entry and no later than actual
exit. Any continued full-horizon path is a separately labeled counterfactual.

Live/replay equality must independently reconstruct every identity that can be derived from sealed
input. Equality is determinism evidence, not qualification.

## Bounded Outcome Truth contract

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

### Cutoff and admission

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
Missing or stale reference, quote side, amount, platform proof, or causal lineage is `UNKNOWN`;
known platform lock, reference closure, or complete visible depth below the frozen quantity is
`UNEXITABLE`.

Each future close observation is classified independently as `EXECUTABLE`, `UNEXITABLE`, or
`UNKNOWN`. `EXECUTABLE` means all visible close economics, frozen-quantity depth, future platform
proof, and lineage are complete. `UNEXITABLE` means the required facts are complete and establish
a known inability to close. `UNKNOWN` means the observation is missing or invalid and cannot be
used to infer either execution or known inability.

### Actual exposure, exit, and counterfactual

Actual exposure starts at Entry and examines future points once in increasing `capture_seq` order.
The first executable exit condition wins. If multiple conditions hold at the same point, priority
is `PROFIT_TARGET`, then `FIRST_TOUCH`, then `HORIZON`. No later fact may change the selected exit,
touch, excursion, or observed PnL.

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

The `optimatrix-outcome` CLI exposes bounded `synthetic`, `capture`, `replay`, `bundle`, and
`verify-bundle` commands. Each output path is fresh and each run uses the one fixed cutoff without
retry. The evidence bundle keeps synthetic and production-public subtrees distinct and binds both
with `BUNDLE_MANIFEST.json`, `SHA256SUMS`, and `ACCEPTANCE.zh-CN.md`. Production-public evidence
also retains a collector invocation witness binding the authorized duration, Deribit public
endpoint, monotonic invocation elapsed time, collector artifacts, capture, Git identity, and
Decision runtime identity. The witness is process evidence, not third-party network attestation.

Synthetic success is not production Outcome evidence. A public zero result is not failure or
profitability evidence. Visible public quotes are not fills. Matching receipts and replay digests
prove deterministic reconstruction only; they do not prove Policy quality, qualification,
continuous Shadow operation, promotion, account access, execution, or capital authority.

## Non-goals

The current contract does not claim calibrated touch probability, dealer positioning, causal
market classification, optimal thresholds, strategy qualification, or automatic self-evolution.
