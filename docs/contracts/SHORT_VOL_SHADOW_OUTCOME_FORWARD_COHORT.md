# Short Vol Shadow Outcome and Forward Cohort Contract

**Status:** ACTIVE IMPLEMENTATION/EVALUATION CONTRACT

**Owning semantic identity:** `SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT`

**Current implementation state:** `RUNTIME_NOT_IMPLEMENTED`

## Purpose

This contract freezes the last semantic prerequisite before a fixed-contract, fixed-Policy
production-public Shadow runtime and forward cohort may be implemented. It owns:

- one strictly-future observation for every accepted `SHADOW_ENTRY`;
- causal-order first eligible counterfactual exit selection without hindsight;
- terminal Shadow Outcome maturity and censoring;
- at most one bounded rejected-counterfactual unit per `UnderwritingPositionSlotKey`;
- cohort-aligned `NO_TRADE` alternatives;
- exact public-quote economics, conservation, denominators, and `null` behavior; and
- strict downstream evidence identity, writing, reading, and compatibility.

It does not implement a runtime, create a Candidate, admit an Entry, place an order, prove a fill,
create exposure, settle an option, qualify a Policy, or authorize execution.

## Authority and upstream boundary

[`PRODUCT_CONSTITUTION`](../authority/PRODUCT_CONSTITUTION.md) owns product meaning,
[`CURRENT_STAGE`](../authority/CURRENT_STAGE.md) owns permission,
[`SYSTEM_ARCHITECTURE`](../authority/SYSTEM_ARCHITECTURE.md) owns dependency direction, and
[`DELIVERY_CONTRACT`](../authority/DELIVERY_CONTRACT.md) owns evidence and delivery.

The accepted upstream contracts remain unchanged:

- [`SHORT_VOL_RADAR`](SHORT_VOL_RADAR.md) owns detector truth, anomaly episodes, official atomic
  availability, and the sealed Radar objects;
- [`SHORT_VOL_UNDERWRITING_POSITION`](SHORT_VOL_UNDERWRITING_POSITION.md) owns Underwriting,
  Candidate/admission semantics, `SHADOW_ENTRY`, Position actions, close-quote classification,
  `CloseOpportunityEvaluationIdentity`, and `SHADOW_CLOSE_OPPORTUNITY`.

This contract begins only after those upstream identities exist. It does not reinterpret a public
quote as a fill or make a close opportunity terminate a Position. It adds no delivery price,
settlement price, mark-to-settlement, private/account, order, fill, balance, margin, or capital
source.

## Contract identity and absence of another Policy

There is no Outcome Policy and no Cohort Policy. No fourth strategy Policy exists.

Every object and cohort binds:

```text
outcome_contract_semantic_identity =
    SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT

OutcomeContractIdentity =
    outcome_contract_semantic_identity
    × sha256_of_exact_accepted_contract_bytes
    × exact_code_identity
    × Radar_Policy_identity
    × Underwriting_Policy_identity
    × Position_Policy_identity
```

The contract-byte digest is a content identity, not an ordinal version. A changed contract receives
a new digest and applies only to a new forward interval. Runtime cannot hot-reload, select, train,
approve, or replace any identity.

Source timestamp, subscription generation, request id, official `change_id`, transport receipt,
file path, and message count are immutable provenance only. They never create an Outcome,
counterfactual unit, cohort unit, or denominator when normalized business facts and terminal state
are unchanged.

## Exact units, arithmetic, and non-claims

All numeric market, Policy, and object values are finite exact base-10 decimals. No decision or
Outcome equation uses binary floating point, implicit quantization, presentation rounding, or
integer truncation.

| Name | Unit and meaning |
|---|---|
| `q` | positive full target and remaining quantity in BTC |
| combo and option prices | USDC per BTC |
| gross cashflow, fee reserve, PnL, loss | USDC |
| `FactBoundary` time fields | integer milliseconds and causal sequence |
| Policy and contract identity | exact content digest or declared semantic string |

Every selected entry and exit uses exactly the same full `q`. Partial public depth cannot be scaled,
rounded, or treated as a partial exit.

The following fields are always `null` with availability `UNKNOWN` under `PUBLIC_SHADOW`:

```text
actual_entry_fee_usdc
actual_close_fee_usdc
actual_total_fee_usdc
actual_pnl_usdc
actual_exposure_quantity_btc
actual_exposure_duration_ms
actual_all_in_loss_usdc
actual_all_in_max_loss_usdc
actual_fill_identity
actual_settlement_cashflow_usdc
```

`contractual_payoff_max_loss_ex_fees_usdc`, `entry_fee_reserved_payoff_loss_usdc`, and
`underwriting_reserved_loss_usdc` remain frozen Entry-time decision measures. They are copied for
audit and never cap, floor, replace, or clamp Outcome PnL or loss.

## Known-at and strictly future order

All causal order uses the accepted upstream `FactBoundary` and same-runtime `causal_seq`. Exchange
timestamps do not replace local known-at order.

For any anchor boundary `A`:

```text
strictly_future(B, A) =
    B.runtime_identity = A.runtime_identity
    and B.causal_seq > A.causal_seq
```

An object from another runtime cannot continue an observation. A changed code or Policy identity
cannot continue an old cohort unit. The reducer settles all effects of one accepted application
event before any Outcome or cohort transition consumes that boundary.

Heartbeat, elapsed wall time, repeated serialization, unchanged recomputation, schema validation,
file creation, and a source identity that preserves every normalized business fact do not create a
new observation identity.

## Admitted Shadow observation

Every accepted `SHADOW_ENTRY` creates exactly one observation:

```text
ShadowObservationIdentity =
    OutcomeContractIdentity
    × ShadowEntryIdentity
```

The observation starts at the Entry boundary and may consume only strictly later facts. Entry facts
cannot double as Position, exit, maturity, or Outcome facts.

The initial lifecycle is `PENDING`. Its state machine is exactly:

```text
PENDING
  → MATURE_KNOWN
  → MATURE_UNKNOWN
  → CENSORED_AT_STOP
  → CENSORED_AT_FAILURE
```

The arrows are alternatives from `PENDING`; every terminal state is immutable. Every terminal
transition emits exactly one `SHADOW_OUTCOME`:

```text
ShadowOutcomeIdentity =
    ShadowObservationIdentity
    × exact_terminal_state
    × terminal_FactBoundary
```

A terminal object cannot be rewritten, upgraded, downgraded, or supplemented by a later quote.
Ordinary Position `UNKNOWN`, quote `UNKNOWN`, a market-data gap, reconnect, elapsed time,
latest-exit crossing, expiry crossing, or absence of a quote does not itself mature an observation.

## Deterministic Shadow counterfactual exit

The only eligible exit source is an upstream `CloseOpportunityEvaluationIdentity` whose eligibility
is `ELIGIBLE` and whose emitted `SHADOW_CLOSE_OPPORTUNITY`:

1. belongs to the same `ShadowEntryIdentity`;
2. binds the observation's exact code and three Policy identities;
3. binds the Entry's canonical combo, legs, reverse direction, and full `q`;
4. is conditioned on the observation's own `first_latched_CLOSE_action_identity`;
5. is accepted at a `FactBoundary` strictly later than both Entry and first CLOSE; and
6. contains complete gross, public-standard fee-reserve, and net close economics.

Selection is exactly once and causal:

```text
ShadowCounterfactualExitIdentity =
    ShadowObservationIdentity
    × first_latched_CLOSE_action_identity
    × causal_order_first_ELIGIBLE_CloseOpportunityEvaluationIdentity
```

The first qualifying identity in reducer causal order wins atomically. Later eligible quotes,
better prices, worse prices, lower fees, lower loss, or hindsight cannot replace it. Raw request,
generation, source timestamp, and `change_id` are provenance and cannot reorder causal selection.
The selected object is `SHADOW_COUNTERFACTUAL_EXIT`. It is not an order, fill, exposure change,
flatness fact, settlement action, or proof that the market would have filled the visible quote.

At the same settled boundary that selects the exit, the still-`PENDING` observation transitions to
`MATURE_KNOWN` and emits exactly one `SHADOW_OUTCOME`.

## Known Shadow Outcome economics

For the selected full-`q` exit, preserve the upstream signs and exact values. These field names and
equations are normative:

```text
gross_pnl_usdc =
    gross_entry_credit_usdc
    + gross_close_cashflow_usdc

total_public_fee_reserve_usdc =
    entry_fee_reserve_usdc
    + close_fee_reserve_usdc

net_pnl_after_public_standard_fee_reserve_usdc =
    gross_pnl_usdc
    - total_public_fee_reserve_usdc

net_loss_usdc =
    max(0, -net_pnl_after_public_standard_fee_reserve_usdc)
```

The equations use no division and no rounding. A close credit remains a signed credit. These are
counterfactual public-quote economics, not actual PnL or actual fees.

A `MATURE_KNOWN` Outcome freezes all four values. `MATURE_UNKNOWN`, `CENSORED_AT_STOP`, and
`CENSORED_AT_FAILURE` require all four Outcome economic fields to be `null` with availability
`UNKNOWN`; Entry-time decision measures remain present only as audit fields.

## Unknown maturity without settlement-price economics

This contract consumes no delivery or settlement-price source and never computes settlement payoff.
A `PENDING` admitted observation becomes `MATURE_UNKNOWN` only when one settled boundary proves all
of the following:

1. no `ShadowCounterfactualExitIdentity` has been selected;
2. the observation's own first Position `CLOSE` is already latched;
3. the observation's exact `ScheduledPostCloseQuoteAttemptIdentity` is already terminal through its
   ordinary request, response, deadline, error, or explicit not-requestable state; a stop-owned or
   failure-owned censor terminal does not satisfy this condition;
4. both canonical option instrument records are current, identity-matched, and each has known
   lifecycle state `delivered` or `archivized`;
5. the maturity boundary is strictly later than Entry, first CLOSE, and the post-CLOSE attempt's
   terminal boundary; and
6. the observation is still `PENDING`.

`settlement`, `inactive`, `locked`, `halted`, missing lifecycle, one delivered leg, or an unresolved
second leg is insufficient. The Outcome records the two lifecycle witnesses, CLOSE/attempt
identities, and maturity boundary, but all exit, fee, PnL, loss, settlement cashflow, and actual
fields are `null / UNKNOWN`.

A stop/failure-owned attempt terminal cannot manufacture `MATURE_UNKNOWN`. A later quote cannot
upgrade `MATURE_UNKNOWN`; terminal means terminal.

## Rejected-counterfactual anchor

A rejected unit is an independently labeled causal unit. It is not a Candidate, admission,
`SHADOW_ENTRY`, Shadow Position, `SHADOW_OUTCOME`, actual exposure, or actual trade.

For each exact `UnderwritingPositionSlotKey`, select at most one anchor:

```text
RejectedCounterfactualAnchorIdentity =
    OutcomeContractIdentity
    × UnderwritingPositionSlotKey
    × causal_order_first_complete_EVALUABLE_WATCH_or_ABSTAIN_UnderwritingActionIdentity
```

The selected action must:

- have complete `EVALUABLE` Underwriting availability;
- be exactly `WATCH` or `ABSTAIN`;
- freeze a current official full-`q` atomic entry quote;
- freeze complete gross/net entry economics, public fee reserve, all three Entry loss measures,
  canonical structure, exact code, and all three Policy identities.

Anchor selection is product behavior and is not conditioned on cohort enrollment. If two eligible
actions share one `FactBoundary`, the bytewise-ascending canonical `UnderwritingActionIdentity` is
the identity-only tie-break; it does not inspect price, severity, future path, or Outcome.

`NOT_EVALUATED`, availability `UNKNOWN`, `CANDIDATE`, Candidate invalidation, admission send or
response failure, deadline, transport failure, malformed/truncated refresh, and unknown admission
outcome never create a rejected anchor.

Once selected, the slot's rejected anchor is immutable. A later rejection cannot replace it. A
later Candidate or `SHADOW_ENTRY` in the same slot remains a distinct admitted causal unit and does
not erase or merge the rejected unit.

## Rejected-counterfactual observation

Each selected rejected anchor creates exactly one:

```text
RejectedCounterfactualObservationIdentity =
    RejectedCounterfactualAnchorIdentity
```

It starts strictly after the rejected action boundary and uses only distinct semantic identities:

```text
REJECTED_COUNTERFACTUAL_POSITION_EVALUATION
REJECTED_COUNTERFACTUAL_POSITION_ACTION
REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION
REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION
REJECTED_COUNTERFACTUAL_EXIT
REJECTED_COUNTERFACTUAL_OUTCOME
```

None may serialize Candidate, `SHADOW_ENTRY`, `SHORT_VOL_POSITION_ACTION`,
`SHADOW_CLOSE_OPPORTUNITY`, or `SHADOW_OUTCOME` as its object kind.

Without alteration, the rejected path reuses:

- the exact compatible Position Policy identity;
- the same first strictly-future Position evaluation requirement;
- `HOLD | CLOSE | UNKNOWN` truth and permanent first-CLOSE latch;
- the same nine predicate meanings and total order;
- the exact close-quote first-match classifier and full-`q` requirement;
- the deterministic single post-CLOSE snapshot attempt and subscription-versus-RPC race; and
- the first causal-order `ELIGIBLE` full-`q` strictly-post-CLOSE exit rule.

Every upstream identity is transformed only by replacing the admitted Entry anchor with
`RejectedCounterfactualAnchorIdentity` and using the distinct rejected object kind. The rejected
anchor's entry index, short-leg mark implied volatility, canonical combo/legs/direction, `q`, gross
entry credit, fee reserve, net entry credit, and Entry loss measures become the rejected trade's
frozen entry facts.

The rejected observation has the same lifecycle:

```text
PENDING
  → MATURE_KNOWN
  → MATURE_UNKNOWN
  → CENSORED_AT_STOP
  → CENSORED_AT_FAILURE
```

Known and unknown maturity rules are identical after identity substitution. Its terminal identity
is:

```text
RejectedCounterfactualOutcomeIdentity =
    RejectedCounterfactualObservationIdentity
    × exact_terminal_state
    × terminal_FactBoundary
```

Each slot can contribute at most one rejected observation, regardless of quote flicker or later
actions. Known rejected-trade economics use the same exact four equations; unknown/censored fields
are `null / UNKNOWN`.

## Cohort-aligned NO_TRADE pairs

Every admitted or rejected observation creates exactly one logical aligned pair. Non-enrolled pairs
remain product facts but never enter cohort denominators.

For an admitted unit:

```text
policy_arm = SHADOW_TRADE
alternative_arm = NO_TRADE
pair_anchor = ShadowEntryIdentity
```

For a rejected unit:

```text
policy_arm = NO_TRADE
alternative_arm = REJECTED_COUNTERFACTUAL_TRADE
pair_anchor = RejectedCounterfactualAnchorIdentity
```

The identity is:

```text
AlignedPolicyNoTradePairIdentity =
    OutcomeContractIdentity
    × pair_anchor
    × exact_policy_arm
    × exact_alternative_arm
```

Both arms bind the same anchor, code, contract, three Policy identities, observation terminal state,
terminal boundary, and censor mask. A unit can never switch pair type. The logical pair begins
`PENDING`; one durable `ALIGNED_POLICY_NO_TRADE_PAIR` is written exactly once when the trade
observation becomes terminal.

`NO_TRADE` cashflow is exactly zero USDC because zero is the definition of the no-action arm. It is
not a quote, fill, realized return, capital statement, or missing-data replacement.

Economic comparison is available only when the trade arm is `MATURE_KNOWN`. Then:

```text
admitted_policy_advantage_usdc =
    shadow_trade_net_pnl_after_public_standard_fee_reserve_usdc - 0

rejected_policy_advantage_usdc =
    0 - rejected_counterfactual_trade_net_pnl_after_public_standard_fee_reserve_usdc
```

If the trade arm is `PENDING`, `MATURE_UNKNOWN`, `CENSORED_AT_STOP`, or
`CENSORED_AT_FAILURE`, both-arm comparison fields are `null / UNKNOWN`, and the pair is excluded
from the aligned economic-comparison denominator. A known zero `NO_TRADE` arm cannot make an
unknown trade arm comparable.

## Lifecycle censoring and failure

### Clean stop

A later evidence runtime must apply this exact order:

1. open the clean-stop barrier, reject all new outbound work, and prevent another enrollment;
2. stop producers;
3. settle every application event already accepted by transport or orchestration;
4. settle every pre-stop accepted send completion, failure, cancellation, response, and deadline;
5. apply any qualifying first exit or maturity transition owned by those accepted facts;
6. commit one immutable clean-stop `FactBoundary`;
7. terminalize every remaining attempt under the stop boundary and transition every still-`PENDING`
   admitted/rejected observation and aligned pair to `CENSORED_AT_STOP`; and
8. durably write all terminal objects and the conservation summary.

The stop boundary cannot reuse the last quote, mark, mid, component-leg reference, or cached
projection to invent an exit. Terminal objects remain immutable.

### Process failure

A fatal runtime failure rejects new outbound work, stops producers, and drains every application
fact and pre-failure control already accepted under the owning failure barrier. Any qualifying first
exit already accepted before the terminal failure is applied in causal order. The runtime then
commits one terminal failure `FactBoundary`, terminalizes remaining attempts, and transitions every
still-`PENDING` admitted/rejected observation and aligned pair to `CENSORED_AT_FAILURE`.

An evidence-integrity failure counts as a valid `CENSORED_AT_FAILURE` terminal only when the
terminal boundary, every required censor object, and a conservation-valid summary are durably
published. If the writer or directory failure prevents that publication, the evidence directory is
incomplete/invalid and no terminal-state or conservation success is inferred.

Ordinary source `UNKNOWN`, reconnect, recoverable gap, or Position `UNKNOWN` is not process failure
and does not censor or mature an observation.

## Forward cohort enrollment and manifest

Product behavior remains continuous and event-driven. There is no planned holding period, fixed
Outcome horizon, periodic batch, saved-data scan, or replay.

A later production-public evidence task must pre-bind one immutable manifest before process start.
It contains exactly:

- exact candidate commit/tree and intended/verified bounded remote ref;
- `OutcomeContractIdentity` and exact accepted contract path;
- exact Radar, Underwriting, and Position Policy paths/digests;
- one new empty absolute downstream evidence directory, separate from every Radar evidence
  directory;
- exact process argv/cwd and required pre-run checks;
- `runtime_start_boundary`, `enrollment_cutoff_boundary`, and `final_stop_boundary`, with strict
  ordering `start < cutoff < stop`;
- half-open enrollment interval `[start, cutoff)` and strictly-future follow-up interval
  `[cutoff, stop)`;
- one deterministic clean-stop predicate and emergency-stop authority; and
- explicit forbidden capabilities and non-claims.

Enrollment applies only to admitted Entry boundaries and rejected-anchor action boundaries inside
`[start, cutoff)`. Units created before start or at/after cutoff remain product facts but are not
cohort-enrolled. Already enrolled units continue observation through the follow-up interval.

The stop predicate cannot depend on anomaly, Candidate, Entry, rejection, Outcome, maturity,
knownness, PnL, win/loss, close opportunity, denominator, or likelihood of passing. Empty/zero
natural activity is truthful evidence but does not by itself establish a usable qualification
cohort.

## Durable object kinds and minimum fields

All downstream semantic object names are ordinal-free. The future owner may write only these kinds:

```text
SHADOW_OUTCOME_OBSERVATION
SHADOW_COUNTERFACTUAL_EXIT
SHADOW_OUTCOME
REJECTED_COUNTERFACTUAL_ANCHOR
REJECTED_COUNTERFACTUAL_OBSERVATION
REJECTED_COUNTERFACTUAL_POSITION_EVALUATION
REJECTED_COUNTERFACTUAL_POSITION_ACTION
REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION
REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION
REJECTED_COUNTERFACTUAL_EXIT
REJECTED_COUNTERFACTUAL_OUTCOME
ALIGNED_POLICY_NO_TRADE_PAIR
SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY
```

Every object strictly requires, as applicable:

- object semantic kind and content schema identity;
- `OutcomeContractIdentity`, code identity, runtime identity, and all three Policy identities;
- complete anchor and prior-object identities;
- complete accepted `FactBoundary` values;
- canonical option/combo identities, direction, exact full `q`, and consumed levels;
- lifecycle/terminal state, availability, censor mask, and ordered reasons;
- all units and exact gross/fee-reserve/net/PnL/loss fields;
- explicit nullability and availability for every unavailable field;
- source provenance separated from the normalized business fingerprint; and
- `PUBLIC_QUOTE_NOT_FILL`, `NO_ACTUAL_EXPOSURE`, `NO_ACTUAL_PNL`,
  `NO_ACTUAL_ACCOUNT_FEE`, `NO_SETTLEMENT_PAYOFF`, and
  `NO_ACTUAL_ALL_IN_LOSS_OR_MAX_LOSS` non-claims.

A `PENDING` observation object contains the anchor and start boundary but no terminal boundary,
exit, or Outcome economics. A terminal Outcome requires one terminal state and terminal boundary.
`MATURE_KNOWN` requires a selected exit and all four exact economics; every other terminal state
requires no selected exit and `null / UNKNOWN` economics, except that audit-only Entry decision
measures remain present.

## Writer, readers, validation, and compatibility

The only future pure downstream owner is `short_vol_underwriting`. It owns Underwriting,
admission, Position, rejected-counterfactual, Outcome, aligned-pair, and downstream evidence
semantics. It consumes immutable public DTOs from `market_monitor`, `options_domain`, and
`short_vol_radar`; it never imports `radar_runtime`. The Online Runtime remains the sole composer.

One downstream evidence directory binds exactly one code identity, runtime identity,
`OutcomeContractIdentity`, and exact three-Policy identity set. It is separate from Radar evidence.
The writer uses canonical UTF-8 JSON, sorted keys, finite exact decimal strings, newline termination,
exclusive creation, file flush, and directory flush.

For every semantic identity:

- an identical duplicate is an idempotent no-op;
- a conflicting duplicate is a hard error;
- unknown or missing members fail validation;
- invalid enums, units, quantities, arithmetic, nullability, or causal order fail validation;
- mixed code/contract/Policy/runtime identities fail closed; and
- writers never overwrite an existing object.

Repository-owned current readers validate only the exact current downstream schema. Any explicitly
sealed future reader remains immutable under its owning schema. A different contract digest,
Policy identity, code identity, source family, maturity rule, exit rule, cohort rule, or arithmetic
is `NOT_COMPARABLE` for economic/qualification claims unless a later authorized compatibility
contract proves otherwise.

Existing `SHORT_VOL_ANOMALY_EVENT`, `PUBLIC_ATOMIC_QUOTE_EVENT`, `RADAR_RUN_SUMMARY`, current Radar
writer/readers, and sealed Radar readers remain unchanged. No migration, replay, recomputation,
backfill, relabeling, or full-market archive is authorized.

## Conservation and denominators

Counts use distinct normalized business identities after settled-state de-duplication, never market
messages, timer ticks, requests, source generations, `change_id` values, files, repeated
calculations, or elapsed seconds.

For every complete evidence directory:

```text
ShadowEntry_count =
    shadow_pending_count
    + shadow_mature_known_count
    + shadow_mature_unknown_count
    + shadow_censored_stop_count
    + shadow_censored_failure_count

RejectedCounterfactualAnchor_count =
    rejected_pending_count
    + rejected_mature_known_count
    + rejected_mature_unknown_count
    + rejected_censored_stop_count
    + rejected_censored_failure_count

logical_aligned_pair_count =
    ShadowEntry_count
    + RejectedCounterfactualAnchor_count

enrolled_aligned_pair_count =
    enrolled_admitted_pair_count
    + enrolled_rejected_pair_count

enrolled_aligned_pair_count =
    enrolled_pair_pending_count
    + enrolled_pair_mature_known_count
    + enrolled_pair_mature_unknown_count
    + enrolled_pair_censored_stop_count
    + enrolled_pair_censored_failure_count
```

Every terminal Outcome count cross-binds exactly one observation and terminal aligned pair. Every
selected exit cross-binds exactly one `MATURE_KNOWN` Outcome. Every `MATURE_KNOWN` Outcome has
exactly one selected exit. `MATURE_UNKNOWN` and censored units have none.

| Metric | Numerator | Denominator and conditioning | `null` rule |
|---|---|---|---|
| admitted terminal-availability rate | `shadow_mature_known + shadow_mature_unknown` | admitted units that are terminal mature or censored | `null` if denominator zero/unknown |
| rejected terminal-availability rate | `rejected_mature_known + rejected_mature_unknown` | rejected units that are terminal mature or censored | `null` if denominator zero/unknown |
| maturity known share | mature-known | `mature_known + mature_unknown` only | `null` if denominator zero/unknown |
| PnL/win/loss statistics | mature-known units with exact economics | mature-known units only | `null` if denominator zero/unknown |
| aligned economic-comparison rate | comparable enrolled pairs | enrolled pairs whose trade arm is `MATURE_KNOWN`; unknown/censored trade arms excluded and counted separately | `null` if denominator zero/unknown |

A win is exact net PnL `> 0`, a loss is `< 0`, and exact zero is neither win nor loss and is reported
separately. No `MATURE_UNKNOWN`, pending, or censored unit enters PnL, win, loss, or aligned economic
comparison.

A numeric zero Entry claim requires the known nonzero upstream admission-evaluable denominator. A
numeric zero rejected-anchor claim requires a known nonzero complete `EVALUABLE WATCH | ABSTAIN`
slot denominator. A numeric zero mature Outcome or exit claim requires a known nonzero admitted or
rejected observation denominator with complete conservation. A zero or unknown denominator
serializes every rate as `null`, never `0`.

## Direct verification and evidence boundary

Direct contract tests must prove:

- semantic identity, exact three-Policy binding, and absence of another Policy;
- strictly-future observation and immutable five-state lifecycle;
- causal-order first eligible exit and no hindsight replacement;
- exact four economics equations, signs, full `q`, and actual-field non-claims;
- exact `MATURE_UNKNOWN` predicates without settlement payoff;
- one rejected anchor per slot, excluded inputs, and separate rejected identities;
- aligned `NO_TRADE`, terminal/censor-mask alignment, and comparison exclusion;
- manifest result-independence and clean-stop/failure ordering;
- durable object fields, writer/readers, strict duplicate/mixed-identity behavior;
- conservation, denominators, natural zero, `null`, and `UNKNOWN`; and
- compatibility with unchanged Radar and Underwriting/Position contracts.

This authority-only closure requires no production-public command, live market fact, capture,
replay, recomputation, or external artifact. It proves no runtime reachability, Candidate quality,
closeability, forecast skill, edge, profitability, actual fee, actual PnL, actual exposure,
qualification, promotion, deployment, fill, or execution permission.

## Explicitly prohibited scope

- changing Radar Policy, Underwriting Policy, Position Policy, upstream contracts, events,
  summaries, sealed evidence, or accepted hashes;
- adding runtime code, package scaffolding, CLI, writer/reader implementation, Policy instance, or
  evidence schema without a separately active task;
- adding a delivery/settlement-price source or treating mark, mid, component legs, last quote, or
  historical atomic event as an exit;
- using private/account data to repair a public inference gap;
- defaulting fee, PnL, loss, maturity, missing facts, or denominators to zero;
- selecting best/worst/last/hindsight quotes or rewriting a terminal exit/Outcome;
- fixed holding duration, fixed Outcome horizon, saved-data scan, replay, synthetic Entry, or
  synthetic exit;
- defining qualification, Challenger, promotion, or execution here; and
- persistent deployment, credentials, margin, orders, fills, settlement action, capital, or money.
