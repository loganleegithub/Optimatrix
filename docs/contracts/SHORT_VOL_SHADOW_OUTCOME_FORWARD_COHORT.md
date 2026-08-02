# Short Vol Shadow Outcome and Forward Cohort Contract

**Status:** ACTIVE IMPLEMENTATION/EVALUATION CONTRACT

**Owning semantic identity:** `SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT`

**Current implementation state:** `OFFLINE_RUNTIME_IMPLEMENTED`

## Purpose

This contract freezes the last semantic prerequisite before a fixed-contract, fixed-Policy
production-public Shadow runtime and forward cohort may be implemented. It owns:

- one strictly-future observation for every accepted `SHADOW_ENTRY`;
- causal-order first eligible counterfactual exit selection without hindsight;
- terminal Shadow Outcome maturity and censoring;
- at most one bounded rejected-counterfactual unit per `UnderwritingPositionSlotKeyIdentity`;
- cohort-aligned `NO_TRADE` alternatives;
- exact public-quote economics and `null` behavior; and
- current downstream business-object identity, writing, and reading.

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

OutcomeContractContentDigest =
    "sha256:" + lowercase_sha256_of_exact_accepted_contract_bytes

OutcomeContractIdentity =
    CanonicalIdentity(
        "OUTCOME_CONTRACT",
        outcome_contract_semantic_identity,
        OutcomeContractContentDigest,
        exact_code_identity,
        Radar_Policy_identity,
        Underwriting_Policy_identity,
        Position_Policy_identity
    )
```

The contract-byte digest is a content identity, not an ordinal version. A changed contract receives
a new digest and applies only to a new forward interval. Runtime cannot hot-reload, select, train,
approve, or replace any identity.

Every new identity equation in this contract uses one exact typed encoding. A `CanonicalValue` is
exactly one native JSON value from this closed recursive domain:

- a canonical UTF-8 string, including every identity, enum, semantic label, and canonical Decimal;
- a JSON integer;
- JSON `true`, `false`, or `null`;
- an array of `CanonicalValue` members in declared order; or
- an object whose exact keys, value types, and key order are declared by this contract.

No object or array is first serialized into a JSON string. No JSON number other than an integer
enters an identity preimage; every exact non-integer Decimal is its canonical string lexeme.

```text
CanonicalIdentity(label, ordered_members...) =
    "sha256:"
    + lowercase_sha256(
        UTF8(
            JSON_array(
                [label, ordered_members...],
                ensure_ascii = false,
                separators = [",", ":"],
                no_BOM = true,
                no_trailing_LF = true
            )
        )
    )
```

`label` is a canonical UTF-8 string and every ordered member is embedded as its native
`CanonicalValue`. A `FactBoundary` is the native compact JSON object with keys in the exact order
declared below. Vectors and leg arrays are native JSON arrays in their declared order. A post-CLOSE
request-params member is exactly the native object
`{"instrument_name": Identity, "depth": 10000}` in that key order; for a not-requestable attempt,
request params is native JSON `null`, and the request-id member is the exact declared marker string
rather than an integer. There is no implicit separator, pre-stringification, string interpolation,
Unicode normalization, map iteration, or platform-dependent serialization. For every symbolic equation
`FooIdentity = member_1 × member_2`, the exact encoding is
`CanonicalIdentity("FooIdentity", member_1, member_2)`; the left-hand identity kind is therefore
always in the preimage. The symbolic `×` below means those ordered arguments, never raw
concatenation.

The accepted upstream slot's symbolic members receive one exact string identity here:

```text
UnderwritingPositionSlotKeyIdentity =
    CanonicalIdentity(
        "UnderwritingPositionSlotKeyIdentity",
        runtime_identity,
        Radar_Policy_identity,
        active_episode_identity,
        short_leg_identity,
        canonical_q_Decimal
    )
```

`canonical_q_Decimal` is the slot's exact positive target-quantity Decimal string. No native tuple,
array, object, or alternative slot-key hash is accepted.

The normative fixed vectors are:

```text
["FooIdentity","member_1","member_2"]
→ sha256:961665d18281a3f4d46b0e72f1d05c494d73d11a9f829def2f4509e09e76bf3a

["CompositeIdentity",{"code_identity":"code","runtime_identity":"runtime","session_epoch":1,"ingress_seq":2,"received_monotonic_ms":3,"causal_seq":4},["TRUE","UNKNOWN"],{"instrument_name":"combo","depth":10000},7,null]
→ sha256:2a6013410106bda9c407cb910982744c77f406384beb93f17b917464639e05ff

["UnderwritingPositionSlotKeyIdentity","runtime","radar-policy","episode","short-leg","0.1"]
→ sha256:3d9a604d72459c3f0353f0a623c7f1f014ec0a24ff38a79975dd272f73e0a8dc
```

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

The following value members are always JSON `null` under `PUBLIC_SHADOW`; the matching
`ActualAvailability` member for each is always `"UNKNOWN"`:

```text
actual_entry_fee_usdc: null
actual_close_fee_usdc: null
actual_total_fee_usdc: null
actual_pnl_usdc: null
actual_exposure_quantity_btc: null
actual_exposure_duration_ms: null
actual_all_in_loss_usdc: null
actual_all_in_max_loss_usdc: null
actual_fill_identity: null
actual_settlement_cashflow_usdc: null
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
PENDING → MATURE_KNOWN
PENDING → MATURE_UNKNOWN
PENDING → CENSORED_AT_STOP
PENDING → CENSORED_AT_FAILURE
```

These are four alternative branches, never a serial chain. Every terminal state is immutable.
Every terminal transition emits exactly one `SHADOW_OUTCOME`:

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

The observation's attempt terminal identity is:

```text
PostCloseAttemptTerminalIdentity =
    ScheduledPostCloseQuoteAttemptIdentity
    × exact_attempt_terminal_status
    × terminal_owner_ORDINARY_or_STOP_or_FAILURE
    × attempt_terminal_FactBoundary
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

## Same-boundary total order and unknown maturity

This contract consumes no delivery or settlement-price source and never computes settlement payoff.
At every settled boundary `B`, the reducer applies this exact terminal total order:

1. settle all source and control effects accepted at `B`, including Position action, the matched
   post-CLOSE attempt terminal, close-opportunity evaluation, and both instrument lifecycle facts;
2. if the observation was already `PENDING` before `B`, select its causal-order first eligible exit
   accepted through `B`; if one exists, emit `MATURE_KNOWN` and stop terminal evaluation;
3. only when no exit was selected, evaluate the natural-terminal predicate below; if it is true,
   emit `MATURE_UNKNOWN`; and
4. only when neither prior terminal applies and `B` is the committed clean-stop or process-failure
   boundary, emit `CENSORED_AT_STOP` or `CENSORED_AT_FAILURE` respectively; otherwise leave the
   observation `PENDING`.

The natural-terminal predicate at `B` is true only when all of the following hold:

1. no `ShadowCounterfactualExitIdentity` has been selected;
2. the observation's own first Position `CLOSE` is already latched at a boundary whose
   `causal_seq < B.causal_seq`;
3. the observation's exact `ScheduledPostCloseQuoteAttemptIdentity` is terminal through its
   ordinary request, response, deadline, error, or explicit not-requestable state at a boundary
   whose `causal_seq <= B.causal_seq`; a stop-owned or failure-owned censor terminal does not
   satisfy this condition;
4. both canonical option instrument records are current, identity-matched, and each has known
   lifecycle state `delivered` or `archivized` at `B`;
5. `B` is strictly later than Entry and the observation is still `PENDING`; and
6. every identity belongs to the same runtime, code, contract, and three-Policy set.

Therefore an ordinary attempt may become terminal at the same boundary as the two natural
lifecycle witnesses. A first CLOSE created at that boundary is not already latched and cannot
mature there. If an eligible exit and the natural-terminal predicate are both visible at the same
settled boundary, exit selection wins and the Outcome is `MATURE_KNOWN`.

The required boundary traces are:

```text
first_CLOSE < B; eligible_exit = B; ordinary_attempt_terminal <= B;
natural_lifecycle_ready = B
    → MATURE_KNOWN

first_CLOSE < B; no_eligible_exit; ordinary_attempt_terminal = B;
natural_lifecycle_ready = B
    → MATURE_UNKNOWN

first_CLOSE < B; no_eligible_exit; attempt_terminal_owner = STOP | FAILURE;
natural_lifecycle_ready = B
    → CENSORED_AT_STOP | CENSORED_AT_FAILURE

first_CLOSE < ordinary_attempt_terminal < B; no_eligible_exit;
natural_lifecycle_not_ready = B; terminal_source = STOP | FAILURE
    → CENSORED_AT_STOP | CENSORED_AT_FAILURE; retain ORDINARY attempt terminal
```

Independently, `first_CLOSE = B` never satisfies the natural-terminal predicate at `B`; at an
ordinary boundary with no exit it remains `PENDING`, while a stop/failure boundary still applies
the censor branch.

`settlement`, `inactive`, `locked`, `halted`, missing lifecycle, one delivered leg, or an unresolved
second leg is insufficient. The Outcome records the two lifecycle witnesses, CLOSE/attempt
identities, and maturity boundary, but all exit, fee, PnL, loss, settlement cashflow, and actual
fields are `null / UNKNOWN`.

A stop/failure-owned attempt terminal cannot manufacture `MATURE_UNKNOWN`. A later quote cannot
upgrade `MATURE_UNKNOWN`; terminal means terminal.

## Rejected-counterfactual anchor

A rejected unit is an independently labeled causal unit. It is not a Candidate, admission,
`SHADOW_ENTRY`, Shadow Position, `SHADOW_OUTCOME`, actual exposure, or actual trade.

For each exact `UnderwritingPositionSlotKeyIdentity`, select at most one anchor:

```text
RejectedCounterfactualAnchorIdentity =
    OutcomeContractIdentity
    × UnderwritingPositionSlotKeyIdentity
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
    × REJECTED_COUNTERFACTUAL_OBSERVATION
```

The observation is created at the rejected anchor boundary. Like an admitted observation, it may
consume only facts with a strictly greater same-runtime `causal_seq`; the anchor fact cannot double
as Position, exit, maturity, or Outcome evidence. It uses only distinct semantic identities:

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

The rejected identity family is exact:

```text
RejectedCounterfactualPositionEvaluationIdentity =
    RejectedCounterfactualObservationIdentity
    × Position_Policy_identity
    × consumed_position_fact_fingerprint
    × evaluation_FactBoundary

RejectedCounterfactualPositionActionIdentity =
    RejectedCounterfactualPositionEvaluationIdentity
    × serialized_action
    × ordered_predicate_truth_vector
    × ordered_latched_close_reason_vector

RejectedScheduledPostCloseQuoteAttemptIdentity =
    RejectedCounterfactualObservationIdentity
    × first_latched_rejected_CLOSE_action_identity
    × unique_request_id_or_NOT_REQUESTABLE_KNOWN_or_NOT_REQUESTABLE_UNKNOWN
    × method_public_get_order_book
    × exact_request_params_including_depth_10000_or_null
    × first_latched_rejected_CLOSE_FactBoundary

RejectedPostCloseAttemptTerminalIdentity =
    RejectedScheduledPostCloseQuoteAttemptIdentity
    × exact_attempt_terminal_status
    × terminal_owner_ORDINARY_or_STOP_or_FAILURE
    × attempt_terminal_FactBoundary

RejectedCounterfactualCloseQuoteEvaluationIdentity =
    RejectedCounterfactualObservationIdentity
    × Position_Policy_identity
    × official_combo_and_canonical_leg_identity
    × exact_reverse_direction
    × full_remaining_q
    × consumed_rule_scoped_quote_fingerprint
    × close_quote_state
    × close_conditioning_PRE_CLOSE_or_first_latched_rejected_CLOSE_action_identity
    × close_quote_evaluation_FactBoundary

RejectedCounterfactualCloseOpportunityEvaluationIdentity =
    RejectedCounterfactualObservationIdentity
    × first_latched_rejected_CLOSE_action_identity
    × post_CLOSE_rejected_CloseQuoteEvaluationIdentity_or_attempt_terminal_identity
    × opportunity_economics_business_fingerprint
    × opportunity_eligibility_ELIGIBLE_or_INELIGIBLE_or_UNKNOWN
    × opportunity_evaluation_FactBoundary

RejectedCounterfactualExitIdentity =
    RejectedCounterfactualObservationIdentity
    × first_latched_rejected_CLOSE_action_identity
    × causal_order_first_ELIGIBLE_RejectedCounterfactualCloseOpportunityEvaluationIdentity

RejectedCounterfactualOutcomeIdentity =
    RejectedCounterfactualObservationIdentity
    × exact_terminal_state
    × terminal_FactBoundary
```

Without semantic alteration, the rejected path reuses:

- the exact compatible Position Policy identity;
- the same first strictly-future Position evaluation requirement;
- `HOLD | CLOSE | UNKNOWN` truth and permanent first-CLOSE latch;
- the same nine predicate meanings and total order;
- the exact close-quote first-match classifier and full-`q` requirement;
- the deterministic single post-CLOSE snapshot attempt and subscription-versus-RPC race; and
- the first causal-order `ELIGIBLE` full-`q` strictly-post-CLOSE exit rule.

An early rejected close-quote or opportunity evaluation whose state is `UNKNOWN` or `INELIGIBLE`
does not consume the observation and is not an exit. The first later `ELIGIBLE` identity still wins
exactly once; best, worst, last, or equal-value later quotes cannot replace it. Every identity is
formed by replacing the admitted Entry anchor with
`RejectedCounterfactualObservationIdentity`, retaining the exact upstream identity members, and
using the distinct rejected object kind. The rejected anchor's entry index, short-leg mark implied
volatility, canonical combo/legs/direction, `q`, gross entry credit, fee reserve, net entry credit,
and Entry loss measures become the rejected trade's frozen entry facts.

The rejected observation has the same lifecycle:

```text
PENDING → MATURE_KNOWN
PENDING → MATURE_UNKNOWN
PENDING → CENSORED_AT_STOP
PENDING → CENSORED_AT_FAILURE
```

Known and unknown maturity rules, including the same-boundary total order, are identical after
identity substitution.

Each slot can contribute at most one rejected observation, regardless of quote flicker or later
actions. A later Candidate or `SHADOW_ENTRY` in the same slot coexists with the rejected
observation: neither identity cancels, merges, replaces, or consumes the other. Known
rejected-trade economics use the same exact four equations; unknown/censored fields are
`null / UNKNOWN`.

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
from economic-advantage, PnL, win, and loss denominators. Terminal unknown/censored pairs remain in
the separate aligned comparison-availability-rate denominator. A known zero `NO_TRADE` arm cannot
make an unknown trade arm comparable.

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
8. durably write the resulting terminal business objects.

The stop boundary cannot reuse the last quote, mark, mid, component-leg reference, or cached
projection to invent an exit. Terminal objects remain immutable.

A valid `AuthorizedEmergencyStopControl` runs this same drain sequence at its committed control
boundary, records `AUTHORIZED_EMERGENCY_STOP`, and owns `CENSORED_AT_STOP`; it does not fabricate or
reuse the pre-bound final-stop boundary.

### Process failure

A fatal runtime failure rejects new outbound work, stops producers, and drains every application
fact and pre-failure control already accepted under the owning failure barrier. Any qualifying first
exit already accepted before the terminal failure is applied in causal order. The runtime then
commits one terminal failure `FactBoundary`, terminalizes remaining attempts, and transitions every
still-`PENDING` admitted/rejected observation and aligned pair to `CENSORED_AT_FAILURE`.

A writer failure cannot be relabelled as a successful terminal publication. Objects written before
the failure remain immutable; no missing terminal object or success claim is fabricated.

Ordinary source `UNKNOWN`, reconnect, recoverable gap, or Position `UNKNOWN` is not process failure
and does not censor or mature an observation.

## Forward cohort enrollment

Product behavior remains continuous and event-driven. There is no planned holding period, fixed
Outcome horizon, periodic batch, saved-data scan, replay, or in-application acceptance supervisor.

`cohort_enrolled` is fixed when an admitted or rejected observation is created. An explicit
offline/runtime owner may open or close enrollment at a settled boundary; units outside that
interval remain valid product facts with `cohort_enrolled = false`. Already enrolled observations
continue to mature or censor through ordinary causal facts. Clean stop and process failure use their
own committed terminal boundary; no future boundary, manifest, rate, or acceptance result is
fabricated.

## Exact durable object schemas

The object kinds below are the only new kinds in this Outcome/cohort family. This restriction does
not prevent the same future owner from writing the separate upstream Underwriting, admission,
Entry, Position, or close-opportunity kinds accepted by their owning contract.

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
```

### Canonical types and shared envelope

`Identity` is either an exact accepted upstream semantic identity or the lowercase
`sha256:`-prefixed 64-hex output of `CanonicalIdentity`. `Decimal` is a finite canonical base-10
string matching `0|-?(?:[1-9][0-9]*(?:\.[0-9]*[1-9])?|0\.[0-9]*[1-9])`. Thus zero has only the
lexeme `"0"`; negative zero, trailing fractional zeroes, exponent notation, `NaN`, and infinity
are forbidden. `NonNegativeInteger` is a JSON integer `>= 0`; `Boolean` is a JSON boolean.
Every nullable member is written explicitly as `type | null`.

Every `FactBoundary` is an object with exactly these keys and types:

```text
code_identity: Identity
runtime_identity: Identity
session_epoch: NonNegativeInteger
ingress_seq: NonNegativeInteger
received_monotonic_ms: NonNegativeInteger
causal_seq: NonNegativeInteger
```

Every consumed atomic level is:

```text
price_usdc_per_btc: Decimal
amount_btc: positive Decimal
```

Every non-empty `consumed_levels` or `entry_consumed_levels` array preserves the accepted upstream
required-side consumption order from best to worse price. It contains no unconsumed level, every
amount is positive, the exact sum of `amount_btc` equals the object's `full_quantity_btc`, and only
the final member may be truncated to the exact remaining quantity. Reordering equal-price levels,
retaining depth after full quantity, aggregating levels, or serializing zero consumption is
invalid. These rules apply identically to admitted and rejected entry/exit payloads.

Every exact two-element `canonical_leg_identities` array is ordered
`[short_leg_identity, long_leg_identity]`. It is never sorted lexically.

Every natural lifecycle witness is:

```text
canonical_leg_role: "SHORT" | "LONG"
instrument_identity: Identity
lifecycle_state: "delivered" | "archivized"
source_identity: Identity
witness_fact_boundary: FactBoundary
```

The two-element witness array is ordered `[SHORT, LONG]`.

Every external direct source reference is an object with exactly:

```text
DirectSourceRef = {
source_identity: Identity
receipt_fact_boundary: FactBoundary
}
```

Every leg commission source reference is an object with exactly:

```text
LegCommissionSourceRef = {
canonical_leg_role: "SHORT" | "LONG"
source_identity: Identity
receipt_fact_boundary: FactBoundary
}
```

A two-member leg commission array is ordered `[SHORT, LONG]`; a partial array preserves that
relative order and cannot contain the same role twice. Each reference names the exact accepted
public fact whose normalized value is copied into the owning payload. Its boundary is the fact's
settled acceptance boundary, not the later evaluation or serialization boundary.

`ActualAvailability` is an object with exactly these keys, each fixed to `"UNKNOWN"`:

```text
actual_entry_fee_usdc: "UNKNOWN"
actual_close_fee_usdc: "UNKNOWN"
actual_total_fee_usdc: "UNKNOWN"
actual_pnl_usdc: "UNKNOWN"
actual_exposure_quantity_btc: "UNKNOWN"
actual_exposure_duration_ms: "UNKNOWN"
actual_all_in_loss_usdc: "UNKNOWN"
actual_all_in_max_loss_usdc: "UNKNOWN"
actual_fill_identity: "UNKNOWN"
actual_settlement_cashflow_usdc: "UNKNOWN"
```

Every `source_provenance` member is an object with exactly:

```text
source_role: "ANCHOR" | "POSITION_EVALUATION" | "POSITION_ACTION" |
             "CLOSE_QUOTE_EVALUATION" | "CLOSE_OPPORTUNITY_EVALUATION" |
             "SELECTED_EXIT" | "TERMINAL_OUTCOME" | "POSITION_FACT" |
             "COMBO_QUOTE" | "COMMISSION" | "INDEX" |
             "INSTRUMENT_LIFECYCLE" | "ATTEMPT_CONTROL" | "SUPERVISOR_CONTROL"
source_identity: Identity
receipt_fact_boundary: FactBoundary
```

All three keys are required. Raw timestamp, subscription generation, request id, and official
`change_id` remain inside their accepted upstream `source_identity`; they are not duplicated into
this envelope. Policy identity binds the fee formula and compatibility threshold, but every
actually consumed short- or long-leg commission fraction still requires its current public
option-instrument source identity and receipt boundary under role `COMMISSION`.

The owner includes only direct facts actually consumed by the object. The array is sorted by
bytewise-ascending UTF-8 (source_role, source_identity) and contains no duplicate pair. The
writer and reader validate member shape, identity format, boundary identity, causal order, sorting,
and uniqueness; they do not resolve local objects or reconstruct a second relationship graph.
Provenance never enters a normalized business fingerprint or kind-specific object identity.
Direct owner tests verify the role assigned to each consumed source.

Every object has exactly this top-level envelope:

```text
object_kind: one exact kind above
content_schema_identity: Identity
object_identity: Identity
outcome_contract_identity: OutcomeContractIdentity
code_identity: Identity
runtime_identity: Identity
radar_policy_identity: Identity
underwriting_policy_identity: Identity
position_policy_identity: Identity
fact_boundary: FactBoundary
source_provenance: array[source provenance member]
payload: exact kind-specific object below
non_claims: exact six-element array below
```

The required non-claim array, in this order, is:

```text
PUBLIC_QUOTE_NOT_FILL
NO_ACTUAL_EXPOSURE
NO_ACTUAL_PNL
NO_ACTUAL_ACCOUNT_FEE
NO_SETTLEMENT_PAYOFF
NO_ACTUAL_ALL_IN_LOSS_OR_MAX_LOSS
```

For each kind:

```text
content_schema_identity =
    CanonicalIdentity(
        "OUTCOME_CONTENT_SCHEMA",
        OutcomeContractContentDigest,
        object_kind
    )
```

The contract content digest binds every declared key, type, enum, condition, and null matrix without
a non-executable placeholder. Code/runtime/Policy identities remain envelope data and do not create
a different schema.

The envelope `object_identity` equals the kind-specific identity field in `payload`.
`fact_boundary` equals the payload's creation, evaluation, selection, or terminal boundary
and every duplicated code/runtime/Policy member must be byte-identical. Unknown top-level or
payload keys, missing keys, duplicate keys, invalid array cardinality/order, or a conditionally
forbidden non-null value fail validation.

### Exact payload key sets

`SHADOW_OUTCOME_OBSERVATION`:

```text
shadow_observation_identity: ShadowObservationIdentity
shadow_entry_identity: ShadowEntryIdentity
start_fact_boundary: FactBoundary
aligned_pair_identity: AlignedPolicyNoTradePairIdentity
cohort_enrolled: Boolean
lifecycle_state: "PENDING"
```

`SHADOW_COUNTERFACTUAL_EXIT`:

```text
shadow_counterfactual_exit_identity: ShadowCounterfactualExitIdentity
shadow_observation_identity: ShadowObservationIdentity
first_latched_close_action_identity: PositionActionIdentity
close_opportunity_evaluation_identity: CloseOpportunityEvaluationIdentity
shadow_close_opportunity_identity: ShadowCloseOpportunityIdentity
selection_fact_boundary: FactBoundary
first_latched_close_action_fact_boundary: FactBoundary
close_opportunity_evaluation_fact_boundary: FactBoundary
combo_quote_source_ref: DirectSourceRef
commission_source_refs: exact two-element array[LegCommissionSourceRef]
index_source_ref: DirectSourceRef
canonical_combo_identity: Identity
canonical_leg_identities: exact two-element array[Identity]
close_direction: "BUY" | "SELL"
full_quantity_btc: Decimal
consumed_levels: non-empty array[atomic level]
short_leg_taker_commission_fraction: Decimal
long_leg_taker_commission_fraction: Decimal
close_index_usdc_per_btc: Decimal
gross_close_cashflow_usdc: Decimal
close_fee_reserve_usdc: Decimal
net_close_cashflow_usdc: Decimal
net_close_debit_usdc: Decimal
projected_shadow_net_pnl_usdc: Decimal
projected_net_loss_usdc: Decimal
```

The action and opportunity boundaries are their accepted upstream object boundaries and must be
strictly after Entry in the order required above. `combo_quote_source_ref` is the accepted official
atomic quote consumed by that opportunity. The two commission refs are `[SHORT, LONG]`, match the
two serialized commission fractions, and `index_source_ref` matches
`close_index_usdc_per_btc`. Their projected `source_provenance` members are therefore independently
reconstructed from payload bytes rather than accepted as envelope-only claims.

`SHADOW_OUTCOME`:

```text
shadow_outcome_identity: ShadowOutcomeIdentity
shadow_observation_identity: ShadowObservationIdentity
shadow_entry_identity: ShadowEntryIdentity
terminal_state: "MATURE_KNOWN" | "MATURE_UNKNOWN" | "CENSORED_AT_STOP" |
                "CENSORED_AT_FAILURE"
terminal_fact_boundary: FactBoundary
selected_exit_identity: ShadowCounterfactualExitIdentity | null
first_latched_close_action_identity: PositionActionIdentity | null
first_latched_close_action_fact_boundary: FactBoundary | null
scheduled_post_close_attempt_identity: ScheduledPostCloseQuoteAttemptIdentity | null
scheduled_post_close_attempt_fact_boundary: FactBoundary | null
post_close_attempt_terminal_identity: PostCloseAttemptTerminalIdentity | null
post_close_attempt_terminal_status: "SUCCESS" | "ERROR" | "DEADLINE_LATE" | "RETIRED" |
                                    "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE" |
                                    "NOT_REQUESTABLE_UNKNOWN" | "CENSORED" | null
post_close_attempt_terminal_owner: "ORDINARY" | "STOP" | "FAILURE" | null
post_close_attempt_terminal_fact_boundary: FactBoundary | null
natural_terminal_lifecycle_witnesses:
    exact zero- or two-element array[natural lifecycle witness]
censor_mask: exact array[] | ["STOP"] | ["FAILURE"]
terminal_supervisor_source_identity: Identity | null
gross_entry_credit_usdc: Decimal
entry_fee_reserve_usdc: Decimal
net_entry_credit_usdc: Decimal
contractual_payoff_max_loss_ex_fees_usdc: Decimal
entry_fee_reserved_payoff_loss_usdc: Decimal
underwriting_reserved_loss_usdc: Decimal
gross_close_cashflow_usdc: Decimal | null
close_fee_reserve_usdc: Decimal | null
net_close_cashflow_usdc: Decimal | null
gross_pnl_usdc: Decimal | null
total_public_fee_reserve_usdc: Decimal | null
net_pnl_after_public_standard_fee_reserve_usdc: Decimal | null
net_loss_usdc: Decimal | null
economic_availability: "KNOWN" | "UNKNOWN"
actual_entry_fee_usdc: null
actual_close_fee_usdc: null
actual_total_fee_usdc: null
actual_pnl_usdc: null
actual_exposure_quantity_btc: null
actual_exposure_duration_ms: null
actual_all_in_loss_usdc: null
actual_all_in_max_loss_usdc: null
actual_fill_identity: null
actual_settlement_cashflow_usdc: null
actual_availability: ActualAvailability
```

For both admitted and rejected Outcome payloads, a non-null first-CLOSE identity has a non-null
matching action boundary; its scheduled-attempt identity and boundary are also non-null and the
scheduled boundary equals that first-CLOSE boundary. All four members are null together before
CLOSE. A present attempt-terminal identity has its exact terminal boundary in the existing
attempt-terminal field. The terminal supervisor source is null for `MATURE_KNOWN` and
`MATURE_UNKNOWN`; for either censored state it is non-null, recomputes from the summary's native
`terminal_source`, equals the summary's `terminal_source_identity`, and uses the Outcome terminal
boundary. Thus a censor object cannot name a different stop/failure control than the directory
summary.

`REJECTED_COUNTERFACTUAL_ANCHOR`:

```text
rejected_anchor_identity: RejectedCounterfactualAnchorIdentity
underwriting_position_slot_key: UnderwritingPositionSlotKeyIdentity
underwriting_action_identity: UnderwritingActionIdentity
underwriting_action: "WATCH" | "ABSTAIN"
anchor_fact_boundary: FactBoundary
canonical_combo_identity: Identity
canonical_leg_identities: exact two-element array[Identity]
entry_direction: "BUY" | "SELL"
full_quantity_btc: Decimal
entry_consumed_levels: non-empty array[atomic level]
entry_combo_quote_source_ref: DirectSourceRef
entry_commission_source_refs: exact two-element array[LegCommissionSourceRef]
entry_index_usdc_per_btc: Decimal
entry_index_source_identity: Identity
entry_index_fact_boundary: FactBoundary
entry_short_leg_mark_iv_fraction: Decimal
entry_short_leg_mark_iv_source_identity: Identity
entry_short_leg_mark_iv_fact_boundary: FactBoundary
gross_entry_credit_usdc: Decimal
entry_fee_reserve_usdc: Decimal
net_entry_credit_usdc: Decimal
contractual_payoff_max_loss_ex_fees_usdc: Decimal
entry_fee_reserved_payoff_loss_usdc: Decimal
underwriting_reserved_loss_usdc: Decimal
```

The entry combo reference is the one official full-quantity atomic quote consumed by the rejected
Underwriting action. The two entry commission refs are ordered `[SHORT, LONG]`, match the exact
accepted commission facts used in `entry_fee_reserve_usdc`, and share the anchor's settled
known-at scope. The already explicit index and IV source identity/boundary pairs are the other two
external roots. An anchor with a missing, duplicated, role-swapped, or value-incompatible direct
source reference is invalid.

`REJECTED_COUNTERFACTUAL_OBSERVATION`:

```text
rejected_observation_identity: RejectedCounterfactualObservationIdentity
rejected_anchor_identity: RejectedCounterfactualAnchorIdentity
start_fact_boundary: FactBoundary
aligned_pair_identity: AlignedPolicyNoTradePairIdentity
cohort_enrolled: Boolean
lifecycle_state: "PENDING"
```

`REJECTED_COUNTERFACTUAL_POSITION_EVALUATION`:

```text
rejected_position_evaluation_identity: RejectedCounterfactualPositionEvaluationIdentity
rejected_observation_identity: RejectedCounterfactualObservationIdentity
consumed_position_fact_fingerprint: Identity
evaluation_fact_boundary: FactBoundary
ordered_predicate_truth_vector: exact nine-element array["TRUE" | "FALSE" | "UNKNOWN"]
entry_index_usdc_per_btc: Decimal
entry_index_source_identity: Identity
entry_index_fact_boundary: FactBoundary
entry_short_leg_mark_iv_fraction: Decimal
entry_short_leg_mark_iv_source_identity: Identity
entry_short_leg_mark_iv_fact_boundary: FactBoundary
prior_evaluation_index_usdc_per_btc: Decimal
prior_evaluation_index_source_identity: Identity
prior_evaluation_index_fact_boundary: FactBoundary
current_index_usdc_per_btc: Decimal | null
current_index_source_identity: Identity | null
current_index_fact_boundary: FactBoundary | null
current_index_availability: "KNOWN" | "UNKNOWN"
next_evaluation_index_usdc_per_btc: Decimal
```

If current index availability is `KNOWN`, all three current-index members are non-null, the decimal
is finite and positive, and `next_evaluation_index_usdc_per_btc = current_index_usdc_per_btc`.
If it is `UNKNOWN`, all three current-index value/source/boundary members are `null` and
`next_evaluation_index_usdc_per_btc = prior_evaluation_index_usdc_per_btc`.

`REJECTED_COUNTERFACTUAL_POSITION_ACTION`:

```text
rejected_position_action_identity: RejectedCounterfactualPositionActionIdentity
rejected_position_evaluation_identity: RejectedCounterfactualPositionEvaluationIdentity
serialized_action: "HOLD" | "CLOSE" | "UNKNOWN"
ordered_predicate_truth_vector: exact nine-element array["TRUE" | "FALSE" | "UNKNOWN"]
ordered_latched_close_reason_vector: array[exact accepted close-reason enum in total order]
first_latched_close_action_identity: RejectedCounterfactualPositionActionIdentity | null
scheduled_post_close_attempt_identity: RejectedScheduledPostCloseQuoteAttemptIdentity | null
action_fact_boundary: FactBoundary
```

`first_latched_close_action_identity` is `null` iff no rejected CLOSE has latched; then the scheduled
attempt is also `null`. Once CLOSE latches, both fields are non-null, immutable across later
rejected action objects, and the one attempt is created in that same reducer transaction. On the
first CLOSE action, the first-latched identity equals
`rejected_position_action_identity`.

`REJECTED_COUNTERFACTUAL_CLOSE_QUOTE_EVALUATION`:

```text
rejected_close_quote_evaluation_identity: RejectedCounterfactualCloseQuoteEvaluationIdentity
rejected_observation_identity: RejectedCounterfactualObservationIdentity
first_latched_close_action_identity: RejectedCounterfactualPositionActionIdentity | null
canonical_combo_identity: Identity
canonical_leg_identities: exact two-element array[Identity]
close_direction: "BUY" | "SELL"
full_quantity_btc: Decimal
consumed_rule_scoped_quote_fingerprint: Identity
close_quote_state: "ATOMIC_COMBO_CLOSE_QUOTE" | "LEGGED_CLOSE_REFERENCE" |
                   "UNEXECUTABLE" | "UNKNOWN"
close_conditioning: "PRE_CLOSE" | RejectedCounterfactualPositionActionIdentity
consumed_levels: array[atomic level]
gross_close_cashflow_usdc: Decimal | null
evaluation_fact_boundary: FactBoundary
```

`close_conditioning = "PRE_CLOSE"` iff `first_latched_close_action_identity` is `null`.
Post-CLOSE conditioning equals the exact non-null first-latched identity. A first-CLOSE-boundary
evaluation remains `PRE_CLOSE`; only a strictly later accepted source fact changes conditioning.
`consumed_levels` is non-empty and gross cashflow is `Decimal` exactly for
`ATOMIC_COMBO_CLOSE_QUOTE`; for every other close-quote state the array is empty and gross cashflow
is `null`.

`REJECTED_COUNTERFACTUAL_CLOSE_OPPORTUNITY_EVALUATION`:

```text
rejected_close_opportunity_evaluation_identity:
    RejectedCounterfactualCloseOpportunityEvaluationIdentity
rejected_observation_identity: RejectedCounterfactualObservationIdentity
first_latched_close_action_identity: RejectedCounterfactualPositionActionIdentity
close_quote_evaluation_identity: RejectedCounterfactualCloseQuoteEvaluationIdentity | null
attempt_terminal_identity: RejectedPostCloseAttemptTerminalIdentity | null
attempt_terminal_fact_boundary: FactBoundary | null
opportunity_economics_business_fingerprint: Identity
eligibility: "ELIGIBLE" | "INELIGIBLE" | "UNKNOWN"
eligibility_reason: "KNOWN_ATOMIC_UNAVAILABLE" | "QUOTE_OR_ATTEMPT_UNKNOWN" |
                    "COMMISSION_UNKNOWN" | "COMMISSION_ABOVE_POLICY" |
                    "INDEX_UNKNOWN" | "ELIGIBLE_COMPLETE"
evaluation_fact_boundary: FactBoundary
gross_close_cashflow_usdc: Decimal | null
gross_cashflow_availability: "KNOWN" | "UNKNOWN" | "NOT_APPLICABLE"
short_leg_taker_commission_fraction: Decimal | null
long_leg_taker_commission_fraction: Decimal | null
commission_source_refs: zero-to-two-element array[LegCommissionSourceRef]
close_index_usdc_per_btc: Decimal | null
index_source_ref: DirectSourceRef | null
close_fee_reserve_usdc: Decimal | null
net_close_cashflow_usdc: Decimal | null
net_close_debit_usdc: Decimal | null
projected_shadow_net_pnl_usdc: Decimal | null
projected_net_loss_usdc: Decimal | null
derived_economics_availability: "KNOWN" | "UNKNOWN" | "NOT_APPLICABLE"
```

Exactly one of `close_quote_evaluation_identity` and `attempt_terminal_identity` is non-null.
The exact first-match value/null matrix is:

| Eligibility reason | eligibility | gross cashflow | commission values | close index | fee/net/debit/projected fields |
|---|---|---|---|---|---|
| `KNOWN_ATOMIC_UNAVAILABLE` | `INELIGIBLE` | `null / NOT_APPLICABLE` | both `null` | `null` | all `null / NOT_APPLICABLE` |
| `QUOTE_OR_ATTEMPT_UNKNOWN` | `UNKNOWN` | `null / UNKNOWN` | both `null` | `null` | all `null / UNKNOWN` |
| `COMMISSION_UNKNOWN` | `UNKNOWN` | `Decimal / KNOWN` | both `null` | `null` | all `null / UNKNOWN` |
| `COMMISSION_ABOVE_POLICY` | `INELIGIBLE` | `Decimal / KNOWN` | both `Decimal` | `null` | all `null / UNKNOWN` |
| `INDEX_UNKNOWN` | `UNKNOWN` | `Decimal / KNOWN` | both `Decimal` | `null` | all `null / UNKNOWN` |
| `ELIGIBLE_COMPLETE` | `ELIGIBLE` | `Decimal / KNOWN` | both `Decimal` | positive `Decimal` | all `Decimal / KNOWN` |

The last column's availability is `derived_economics_availability`. The gross field remains known
when an atomic quote is known even if commission or index prevents fee/net economics. Every
`ELIGIBLE_COMPLETE` row satisfies the accepted upstream equations; no other row invents a fee,
net cashflow, projected PnL, or projected loss.

`attempt_terminal_fact_boundary` is non-null exactly when `attempt_terminal_identity` is non-null;
otherwise it is null and the referenced local close-quote evaluation supplies its own boundary.
`commission_source_refs` and `index_source_ref` follow the provenance rule table exactly. Every
present commission ref's normalized value equals the matching short/long commission fact consumed
by the first-match classifier. A present index ref names the exact accepted current, stale, or
invalid index fact actually consumed; `ELIGIBLE_COMPLETE` requires it to match the positive
`close_index_usdc_per_btc`. A numeric source field with no required ref, or a ref that the
eligibility row forbids, fails validation.

`REJECTED_COUNTERFACTUAL_EXIT`:

```text
rejected_exit_identity: RejectedCounterfactualExitIdentity
rejected_observation_identity: RejectedCounterfactualObservationIdentity
first_latched_close_action_identity: RejectedCounterfactualPositionActionIdentity
close_quote_evaluation_identity: RejectedCounterfactualCloseQuoteEvaluationIdentity
close_opportunity_evaluation_identity:
    RejectedCounterfactualCloseOpportunityEvaluationIdentity
selection_fact_boundary: FactBoundary
first_latched_close_action_fact_boundary: FactBoundary
close_quote_evaluation_fact_boundary: FactBoundary
close_opportunity_evaluation_fact_boundary: FactBoundary
consumed_rule_scoped_quote_fingerprint: Identity
commission_source_refs: exact two-element array[LegCommissionSourceRef]
index_source_ref: DirectSourceRef
canonical_combo_identity: Identity
canonical_leg_identities: exact two-element array[Identity]
close_direction: "BUY" | "SELL"
full_quantity_btc: Decimal
consumed_levels: non-empty array[atomic level]
short_leg_taker_commission_fraction: Decimal
long_leg_taker_commission_fraction: Decimal
close_index_usdc_per_btc: Decimal
gross_close_cashflow_usdc: Decimal
close_fee_reserve_usdc: Decimal
net_close_cashflow_usdc: Decimal
net_close_debit_usdc: Decimal
projected_shadow_net_pnl_usdc: Decimal
projected_net_loss_usdc: Decimal
```

The selected local opportunity must be the causal-order first `ELIGIBLE_COMPLETE` opportunity named
by `rejected_exit_identity`; its local close-quote evaluation, first-CLOSE action, and all three
boundaries must resolve to the exact identity/boundary fields above. The opaque quote fingerprint
must equal the resolved quote evaluation's fingerprint. Both ordered commission refs and the index
ref must equal the resolved opportunity's direct-source refs. Every rejected-exit economic field is
byte-identical to the corresponding selected-opportunity or resolved-quote field, including combo,
legs, direction, full quantity, levels, both commissions, index, gross/fee/net/debit, projected PnL,
and projected loss. Any mismatch invalidates the exit and directory; a reader never obtains these
roots by expanding another object's `source_provenance`.

`REJECTED_COUNTERFACTUAL_OUTCOME`:

```text
rejected_outcome_identity: RejectedCounterfactualOutcomeIdentity
rejected_observation_identity: RejectedCounterfactualObservationIdentity
rejected_anchor_identity: RejectedCounterfactualAnchorIdentity
terminal_state: "MATURE_KNOWN" | "MATURE_UNKNOWN" | "CENSORED_AT_STOP" |
                "CENSORED_AT_FAILURE"
terminal_fact_boundary: FactBoundary
selected_exit_identity: RejectedCounterfactualExitIdentity | null
first_latched_close_action_identity: RejectedCounterfactualPositionActionIdentity | null
first_latched_close_action_fact_boundary: FactBoundary | null
scheduled_post_close_attempt_identity: RejectedScheduledPostCloseQuoteAttemptIdentity | null
scheduled_post_close_attempt_fact_boundary: FactBoundary | null
post_close_attempt_terminal_identity: RejectedPostCloseAttemptTerminalIdentity | null
post_close_attempt_terminal_status: "SUCCESS" | "ERROR" | "DEADLINE_LATE" | "RETIRED" |
                                    "NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE" |
                                    "NOT_REQUESTABLE_UNKNOWN" | "CENSORED" | null
post_close_attempt_terminal_owner: "ORDINARY" | "STOP" | "FAILURE" | null
post_close_attempt_terminal_fact_boundary: FactBoundary | null
natural_terminal_lifecycle_witnesses:
    exact zero- or two-element array[natural lifecycle witness]
censor_mask: exact array[] | ["STOP"] | ["FAILURE"]
terminal_supervisor_source_identity: Identity | null
gross_entry_credit_usdc: Decimal
entry_fee_reserve_usdc: Decimal
net_entry_credit_usdc: Decimal
contractual_payoff_max_loss_ex_fees_usdc: Decimal
entry_fee_reserved_payoff_loss_usdc: Decimal
underwriting_reserved_loss_usdc: Decimal
gross_close_cashflow_usdc: Decimal | null
close_fee_reserve_usdc: Decimal | null
net_close_cashflow_usdc: Decimal | null
gross_pnl_usdc: Decimal | null
total_public_fee_reserve_usdc: Decimal | null
net_pnl_after_public_standard_fee_reserve_usdc: Decimal | null
net_loss_usdc: Decimal | null
economic_availability: "KNOWN" | "UNKNOWN"
actual_entry_fee_usdc: null
actual_close_fee_usdc: null
actual_total_fee_usdc: null
actual_pnl_usdc: null
actual_exposure_quantity_btc: null
actual_exposure_duration_ms: null
actual_all_in_loss_usdc: null
actual_all_in_max_loss_usdc: null
actual_fill_identity: null
actual_settlement_cashflow_usdc: null
actual_availability: ActualAvailability
```

`ALIGNED_POLICY_NO_TRADE_PAIR`:

```text
aligned_pair_identity: AlignedPolicyNoTradePairIdentity
pair_family: "ADMITTED" | "REJECTED"
cohort_enrolled: Boolean
pair_anchor_identity: ShadowEntryIdentity | RejectedCounterfactualAnchorIdentity
policy_arm: "SHADOW_TRADE" | "NO_TRADE"
alternative_arm: "NO_TRADE" | "REJECTED_COUNTERFACTUAL_TRADE"
trade_observation_identity:
    ShadowObservationIdentity | RejectedCounterfactualObservationIdentity
trade_outcome_identity: ShadowOutcomeIdentity | RejectedCounterfactualOutcomeIdentity
terminal_state: "MATURE_KNOWN" | "MATURE_UNKNOWN" | "CENSORED_AT_STOP" |
                "CENSORED_AT_FAILURE"
terminal_fact_boundary: FactBoundary
censor_mask: exact array[] | ["STOP"] | ["FAILURE"]
no_trade_cashflow_usdc: Decimal exactly "0"
trade_net_pnl_after_public_standard_fee_reserve_usdc: Decimal | null
policy_advantage_usdc: Decimal | null
comparison_availability: "KNOWN" | "UNKNOWN"
```

The only legal family/arm combinations are exactly
`ADMITTED × SHADOW_TRADE × NO_TRADE` and
`REJECTED × NO_TRADE × REJECTED_COUNTERFACTUAL_TRADE`. The anchor, observation, and Outcome
identity types must match that family. `cohort_enrolled` equals the immutable enrollment bit on the
owning observation; it cannot be inferred from terminal state.

### Exact terminal null matrix

The matrix applies independently to admitted and rejected terminal Outcomes:

| Terminal state | selected exit | first CLOSE / scheduled attempt / terminal witness | natural lifecycle witnesses | censor mask | entry audit fields | close and four Outcome economics | economic availability | actual fields and availability |
|---|---|---|---|---|---|---|---|---|
| `MATURE_KNOWN` | required identity | all required; terminal owner `ORDINARY` | exact empty array | `[]` | all six `Decimal` | all seven `Decimal` | `KNOWN` | all ten `null`; all ten availability values `UNKNOWN` |
| `MATURE_UNKNOWN` | `null` | all required; terminal owner `ORDINARY` | exact `[SHORT, LONG]` witnesses | `[]` | all six `Decimal` | all seven `null` | `UNKNOWN` | all ten `null`; all ten availability values `UNKNOWN` |
| `CENSORED_AT_STOP` | `null` | either all eight close/attempt identity/boundary members `null`, or all eight required; retain an earlier `ORDINARY` non-`CENSORED` terminal, otherwise terminal status `CENSORED`, owner `STOP`, and boundary equal to Outcome terminal | exact empty array | `["STOP"]` | all six `Decimal` | all seven `null` | `UNKNOWN` | all ten `null`; all ten availability values `UNKNOWN` |
| `CENSORED_AT_FAILURE` | `null` | either all eight close/attempt identity/boundary members `null`, or all eight required; retain an earlier `ORDINARY` non-`CENSORED` terminal, otherwise terminal status `CENSORED`, owner `FAILURE`, and boundary equal to Outcome terminal | exact empty array | `["FAILURE"]` | all six `Decimal` | all seven `null` | `UNKNOWN` | all ten `null`; all ten availability values `UNKNOWN` |

The seven close/Outcome economics are
`gross_close_cashflow_usdc`, `close_fee_reserve_usdc`, `net_close_cashflow_usdc`,
`gross_pnl_usdc`, `total_public_fee_reserve_usdc`,
`net_pnl_after_public_standard_fee_reserve_usdc`, and `net_loss_usdc`. The six Entry audit fields
never become Outcome availability and never turn an unknown exit into known economics.
For every state, `first_latched_close_action_identity` and its boundary are `null` iff the scheduled
attempt identity, its boundary, and all attempt-terminal members are `null`. A non-null first CLOSE
requires the one deterministic scheduled attempt. Terminal Outcomes require that attempt's
ordinary or barrier-owned terminal identity, status, owner, and boundary; the members are never
independently nullable.
`ORDINARY` requires a non-`CENSORED` terminal status. An immutable ordinary terminal that predates a
later censor boundary is retained unchanged; stop/failure never rewrites it. Only an attempt still
pending when the barrier opens receives status `CENSORED`, owner `STOP | FAILURE` matching the
Outcome censor state/mask, and an attempt terminal boundary equal to the Outcome terminal boundary.
`terminal_supervisor_source_identity` is null for both mature rows and is required for both censor
rows under the exact terminal-source binding.

For aligned pairs, `no_trade_cashflow_usdc` is always exact known `"0"`. The trade net PnL and
policy advantage are both `Decimal` with comparison availability `KNOWN` only for
`MATURE_KNOWN`; for the other three terminal states both are `null` and availability is `UNKNOWN`.

## Writer, reader, validation, and compatibility

`short_vol_underwriting` is the only downstream business-object owner. It consumes immutable public
DTOs and never imports `radar_runtime`; the runtime remains the sole composer.

The writer validates exact envelope and payload keys, primary boundary, object identity, source
shape/order, and code/runtime/contract/Policy bindings before exclusive immutable publication. An
identical duplicate is an idempotent no-op; a conflicting duplicate is a hard error. The current
reader repeats the same per-object checks; it does not recompute owner arithmetic or reconstruct a
second relationship graph. The typed owner is the sole calculator and its arithmetic and state
matrices are covered by direct behavior tests. There is no manifest, terminal summary,
complete-directory proof, compatibility reader, replay, backfill, or migration path.

## Direct verification and evidence boundary

Direct contract tests must prove:

- typed canonical identity fixed vectors, semantic identity, exact three-Policy binding, and
  absence of another Policy;
- strictly-future observation and immutable five-state lifecycle;
- causal-order first eligible exit and no hindsight replacement;
- exact four economics equations, signs, full `q`, and actual-field non-claims;
- exact `MATURE_UNKNOWN` predicates without settlement payoff;
- one rejected anchor per slot, excluded inputs, and separate rejected identities;
- aligned `NO_TRADE`, terminal/censor-mask alignment, and comparison exclusion;
- clean-stop/failure ordering and immutable censor ownership;
- durable object fields, full-quantity consumed-level order, owner-produced provenance,
  writer/readers, and strict duplicate/mixed-identity behavior;
- natural zero, `null`, and `UNKNOWN` without a fabricated cohort rate; and
- compatibility with unchanged Radar and Underwriting/Position contracts.

This authority-only closure requires no production-public command, live market fact, capture,
replay, recomputation, or external artifact. It proves no runtime reachability, Candidate quality,
closeability, forecast skill, edge, profitability, actual fee, actual PnL, actual exposure,
qualification, promotion, deployment, fill, or execution permission.

## Explicitly prohibited scope

- changing Radar Policy, Underwriting Policy, Position Policy, upstream contracts, or business events;
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
