# Task — SHORT_VOL_RADAR_ESTABLISHMENT

**Status:** ACTIVE

**Implemented runtime capability:** `NONE`

**Production Short Vol Radar:** `NOT_ESTABLISHED`

**Task kind:** `IMPLEMENTATION`

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED only after the exact named Smoke or Soak gate opens

**Construction gate:** `OPENED_BY_EXPLICIT_HUMAN_COMMAND_2026_07_25`

**Current construction subgate:** `SHORT_VOL_RADAR_FACT_SEMANTICS_CLOSURE`
`OPENED_BY_EXPLICIT_HUMAN_COMMAND_2026_07_27`

**Current subgate base HEAD:** `c66f987f7fd7513626e69c37f7f2552991ebf9e4`

**REACHABILITY_SMOKE gate:** `CLOSED_AFTER_PRIOR_SINGLE_RUN_AUTHORIZATION`

**OPERATIONAL_SOAK gate:** `CLOSED_AFTER_ATTEMPT_001_NOT_MET`

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `0154e946c6959c351f6ab2504b9f7780a14fe9ad`

**Target branch/PR:** `codex/short-vol-radar-establishment`; Draft PR to `main`

## Human execution gates

The design DRAFT did not authorize construction. The explicit human command naming
`SHORT_VOL_RADAR_ESTABLISHMENT` on 2026-07-25 opened the original construction gate. The explicit
2026-07-27 command naming `SHORT_VOL_RADAR_FACT_SEMANTICS_CLOSURE`, base
`c66f987f7fd7513626e69c37f7f2552991ebf9e4`, and input identity
`TICKER_SNAPSHOT_CURRENTNESS_REPAIR` separately authorizes only the bounded ticker fact-semantics,
three-ledger, same-current-scope witness, diagnostic/evidence contract repair, direct tests,
authority/artifact inspection, commit, and push.

The prior `OPERATIONAL_SOAK` attempt at
`/Users/logan/Optimatrix-soak/evidence/operational-soak-attempt-001` is sealed
`NOT_MET`. It is historical evidence only and may not be changed, replayed, recomputed, migrated,
or retroactively accepted.

The execution gates are independent:

1. **Original construction gate:** authorizes implementation of the active task contract and no
   production-public connection.
2. **`REACHABILITY_SMOKE` gate:** one explicit command authorizes only the one named Smoke run
   against its exact code, Policy, evidence directory, and stop boundary. A completed or accepted
   Smoke does not authorize Soak.
3. **`OPERATIONAL_SOAK_PRECONDITIONS` construction subgate:** completed at
   `c66f987f7fd7513626e69c37f7f2552991ebf9e4`; it granted no continuing live authority.
4. **Prior `OPERATIONAL_SOAK` gate:** consumed by `attempt-001`, whose acceptance is permanently
   `NOT_MET`.
5. **`SHORT_VOL_RADAR_FACT_SEMANTICS_CLOSURE` construction subgate:** the current command
   authorizes only the exact bounded construction work above. It does not authorize any live
   command.
6. **Heartbeat wire probe gate:** closed until a separate explicit human command.
7. **Next `OPERATIONAL_SOAK` gate:** closed until the heartbeat probe is separately authorized,
   new global-continuity and local-availability thresholds are human-frozen, and a later command
   independently names exact accepted code, Policy path/digest, new empty evidence directory, and
   stop condition.

Production-public connection, live artifact collection, private API, order, trade, merge,
business acceptance, task archival, stage advancement, and any later research or execution
authority remain unauthorized. Policy files and `CURRENT_STAGE` remain unchanged.

## Business closure

**Given:** Deribit production-public data can establish a continuous current state for the actual
BTC-USDC linear-option universe with `0 < TTE <= 72 hours`.

**When:** one process loads one exact content-identified Radar Policy, maintains the current
public market state in memory, and applies the Policy only to causally known changed facts.

**Then:** for each applicable option instrument and each active short-leg episode, it continuously
reports two independent facts:

1. `detector_state[instrument_name] = UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE`, plus the
   completeness-aware aggregate state;
2. independently for each active short-leg episode,
   `public_atomic_quote_state = NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO |
   NO_TARGET_SIZE_CREDIT_QUOTE | PUBLIC_ATOMIC_QUOTE_AVAILABLE`.

The process writes one minimal `SHORT_VOL_ANOMALY_EVENT` when an anomaly episode activates. If an
official same-expiry 1:1 vertical combo later has target-size depth in the required combo order
direction and positive normalized gross entry credit during that episode, it separately writes
`PUBLIC_ATOMIC_QUOTE_EVENT`. A missing, unavailable, or empty combo book never changes an already
known anomaly into `UNKNOWN`.

**Independent verification:** direct deterministic tests of the consumed formulas, state
transitions, source continuity, result separation, and artifact projection, plus separately
authorized `REACHABILITY_SMOKE` and human-approved `OPERATIONAL_SOAK` evidence. This task does not
implement replay, a second calculator, hit-only recomputation, or provenance verification.

**Valid zero/no-hit/UNKNOWN result:**

- a covered production interval with usable detector evaluations and zero anomaly is a valid
  runtime-establishment result; it proves neither natural anomaly reachability nor Policy quality;
- no active anomaly produces `public_atomic_quote_state = NOT_EVALUATED`;
- an anomaly with no official combo is a known anomaly plus
  `public_atomic_quote_state = NO_ACTIVE_COMBO` or `NO_TARGET_SIZE_CREDIT_QUOTE`;
- unavailable/invalid detector inputs or numerically unresolved classification make only
  `detector_state = UNKNOWN`;
- unavailable combo inputs make only `public_atomic_quote_state = UNKNOWN`;
- a complete continuous book with an empty required side or insufficient target-size depth is
  known unavailable liquidity, not missing data;
- rates with a zero or unknown denominator are `null`, never `0`.

Negative claims require complete scope: `NO_ANOMALY` requires every potentially eligible option
to be usable or known liquidity-ineligible; `NO_ACTIVE_COMBO` requires complete option/combo
catalog and lifecycle coverage, complete relevant option-leg metadata, and a known protective-leg
universe; and `NO_TARGET_SIZE_CREDIT_QUOTE` requires every matching active combo book to be usable
or known insufficient. Missing protective-leg metadata or an incomplete option catalog is
`UNKNOWN`. One complete active short leg can prove `ANOMALY_ACTIVE` with degraded
coverage, and one known atomic credit quote can prove positive availability. Neither positive
witness claims a complete triggered set, best quote, or ranked full market.

Within one runtime, the exact aggregate key is
`Policy identity × expiry_timestamp × option_type`. It exists only when the reconciled catalog has
at least one real instrument in that expiry/type and a detector band whose `option_rules` contains
that option type. OTM, Delta, minimum-amount, or depth failure is a known per-instrument
evaluation; it must not erase the instrument from the denominator. An empty set is reported as
`aggregate_applicability = NO_APPLICABLE_SCOPE`; no Layer 1 aggregate detector state is evaluated,
it adds no complete aggregate evaluation, and its rate is `null`.

**Upstream prerequisite:** none. This is the smallest current product prerequisite.

## Change declarations

**Market/Decision input contract change:** `APPROVED` — establish the
`DERIBIT_BTC_USDC_0_3DTE_MARKET_MONITOR` from public Deribit time, index, option and combo
catalogs, lifecycle events, ticker facts, and continuous books. Normal option-chain changes,
no-anomaly evaluations, and theoretical structures remain transient.

**Decision Policy change:** `APPROVED` — implement one narrow configurable
`POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE` family. Exact numeric values live in a Policy file
rather than code, and Layer 2 matches only existing official same-expiry, same-option-type, 1:1
protective credit verticals. This structure family is an availability classification, not a
decision to trade. One process binds one exact Policy identity from start to stop. Detector truth,
official atomic-quote availability, and future order/fill state remain separate.

**Outcome/evaluation contract change:** `NONE` — no future realized-volatility label, settlement
result, Candidate, Shadow admission, Position action, Outcome, PnL, edge, comparator,
qualification, or promotion. Current results can describe coverage, signal frequency and public
combo availability only; they cannot prove that one Policy predicts better or earns more.

**Stage/authorization change:** `APPROVED` — conditional public Radar capability only. Permission
remains `PUBLIC_SHADOW`. Private APIs, RFQ, combo creation, maker orders, fills, account facts,
capital, training, automatic Policy evolution, and execution remain unauthorized.

### `OPERATIONAL_SOAK_PRECONDITIONS` subgate change declarations

**Market/Decision input contract change:** `APPROVED` — classify initial index bootstrap as
`INDEX_WARMUP`, not a real `INDEX_CONTINUITY_GAP`, and preserve the operational witness across
normal `TIME_BOUNDARY_PENDING`/`WATERMARK_PENDING` minute rollover. Real continuity gaps and other
non-pending coverage loss continue to clear the witness.

**Decision Policy change:** `NONE` — the candidate Soak successor preserves every business and
operational numeric parameter from the exact predecessor Smoke Policy. Its sole Policy-field
delta is the non-behavioral band identity label required to create a new content identity; no
threshold, scope, formula, source, quantity, persistence, or deadline changes.

**Outcome/evaluation contract change:** `NONE` — no new future fact, denominator, label, replay,
recomputation, Candidate, Position, Outcome, or performance claim.

**Stage/authorization change:** `NONE` — `PUBLIC_SHADOW`, implemented capability `NONE`, and
production Radar `NOT_ESTABLISHED` remain unchanged. This subgate does not authorize
production-public connection, Smoke, Soak, private API, order, trade, or stage advancement.

### `SHORT_VOL_RADAR_FACT_SEMANTICS_CLOSURE` subgate change declarations

**Market/Decision input contract change:** `APPROVED` —
`TICKER_SNAPSHOT_CURRENTNESS_REPAIR`. An option ticker is one complete snapshot without sequence
continuity. Shape, candidate/accepted-fact currentness, and application disposition are separate.
`ingress_seq` orders applications; a lower source timestamp is `LATE_IGNORED` and cannot overwrite
newer truth, resubscribe, end an episode, change coverage, or reset a witness. Only a currently
accepted ticker crossing its Policy TTL makes that option's forward unavailable.
Candidates from that latched failed generation are separately `STALE_GENERATION_IGNORED`, never
misreported as timestamp regressions.
A candidate received without a trusted-time interval is `TRUSTED_TIME_UNKNOWN`, not falsely
current; applying it in ingress order cannot recover clock-dependent detector truth.

**Decision Policy change:** `NONE` — formula, target quantity, scope, TTE bands, Delta, baseline,
activation/clear thresholds, persistence, and every Policy/runtime-limit field remain unchanged.
No Policy file is created or edited.

**Outcome/evaluation contract change:** `NONE` — no replay, offline recomputation, historical
relabelling, future label, Candidate, Position, Outcome, PnL, comparator, or qualification.

**Stage/authorization change:** `NONE` — permission remains `PUBLIC_SHADOW`, implemented
capability remains `NONE`, and production Radar remains `NOT_ESTABLISHED`. This construction
authorizes no production-public connection, heartbeat wire probe, Smoke, Soak, private API, order,
trade, or stage advancement.

### Fact-semantics business closure

**Given:** a ticker channel delivers shape-valid complete snapshots in one reduced
`session_epoch/ingress_seq` order, and an already accepted newer ticker may be followed by an older
source timestamp without implying a missing message.

**When:** the reducer parses, classifies currentness, and applies or ignores that candidate.

**Then:** an older snapshot is recorded as `LATE_IGNORED`; the existing newer accepted ticker,
current detector/episode/Layer 2 state, current coverage, and global witness remain unchanged, and
no option resubscription is emitted. A genuinely stale accepted ticker remains option-local
`UNKNOWN` and recovers only through the existing fresh-generation rule.

**Independent verification:** direct reducer/state/writer/validator tests plus `make check`,
strict validation of the sealed version-2 `attempt-001`, authority-link inspection, and artifact
inspection. Production-public evidence is prohibited for this construction.

**Valid zero/no-hit/UNKNOWN result:** zero late snapshots is a valid diagnostic count. A malformed
or ahead candidate is rejected without replacing a still-current accepted ticker. No accepted
ticker or an accepted ticker beyond TTL remains truthful option-local `UNKNOWN`; it does not
restart global continuity. A global continuity break clears the current-epoch witness and
requires a new one.

**Upstream prerequisite:** exact base
`c66f987f7fd7513626e69c37f7f2552991ebf9e4` and the sealed `attempt-001` operational evidence
showing ticker shape/application conflation and fragmented current coverage.

#### Three independent ledgers

1. `global_continuity_epoch` starts at `1` and restarts only for session retirement,
   ingress gap/duplicate or overflow, trusted-clock gap, or real index
   `WINDOW_GAP | SOURCE_STALE | CONTINUITY_GAP`.
2. `current_market_truth_coverage` retains the four-state millisecond partition. Version-3
   segments add the entry reason, sorted affected scope labels, and continuity epoch.
3. `option_local_availability` records bounded ticker-local reason, affected instrument/
   generation, start/end and recovery duration. Local availability may change current coverage
   and end the affected episode under existing TTL rules, but never resets global continuity.

#### Same-current-scope joint witness

One settled full current `Policy identity × expiry_timestamp × option_type` snapshot owns both
`detector_coverage` and `has_current_full_formula`. Unchanged current results may be reused, but
the reducer may not combine full-scope coverage with only the affected subset's
`full_formula_evaluation` or with historical counters. `EvidenceWriter` remains an edge sink and
has no input to current-truth decisions.

#### Bounded evidence and compatibility

New summaries use `operational_diagnostics_schema_version = 3`, at most 256 late-regression rows,
at most 256 option-local availability intervals, and attributed coverage rows. They persist no
prices, Greeks, books, full ticker payloads, or reconstructable chain. The strict reader still
validates version-2 summaries under their original schema; version 2 is not eligible for the new
acceptance semantics and no migration/replay path exists.

## First-principles scope

This task answers only:

1. Can the system continuously maintain the relevant public market state without confusing
   missing data with a quiet market?
2. Can it apply one explicit, inspectable Short Vol baseline to that state?
3. Can it preserve a known anomaly independently from whether Deribit happens to have an official
   combo book?
4. If an official combo exists, can it truthfully report visible target-size atomic credit
   availability?

It does not answer whether the anomaly should be traded. Fees, delivery fees, account tiers,
margin, liquidation, future exit liquidity, expected payoff, maximum total loss after all future
costs, and maker execution belong to later Underwriting/Execution work.

## Policy lifecycle and calibration

### Configuration, not hard-coded trading truth

The runtime implements one bounded formula family. A Policy file supplies exact values for:

- target base quantity in BTC;
- one exact `runtime_limits` object containing heartbeat interval, session-liveness, RPC,
  clock-refresh, clock-stale, index-source-stale, ticker-source-stale, notification-queue-lag, and
  time-boundary-poll deadlines;
- one or more exact TTE bands, each with trailing-variance lookbacks, non-negative weights, and a
  strictly positive annualized variance floor;
- in every band, a non-empty `option_rules` map keyed only by `call` and/or `put`;
- in every band/option rule, absolute-Delta bounds, activation/clear IV-richness ratios,
  activation/clear observation counts, and minimum trusted-market-time separation.

A call or put omitted from a band is explicitly out of detector scope in that band. Calls and puts
inside one band may use different detector boundaries but must share that band's one BTC
underlying return baseline.

The external file has exactly `policy_schema_version = 3`. Policy loading rejects an empty
TTE-band set or empty/unsupported per-band `option_rules`;
empty/duplicate/non-positive lookbacks; missing or misaligned weights;
non-finite/negative weights or a sum other than exactly one after canonical decimal parsing;
overlapping or out-of-range TTE bands outside `(30 minutes, 72 hours]`; invalid
`0 <= abs_delta_min < abs_delta_max <= 1`; non-positive/non-finite target quantity or variance
floor; anything other than `activation_ratio > 1` and
`0 < clear_ratio < activation_ratio`; non-positive counts; or negative separation. A deliberate
TTE-band gap is explicit `OUT_OF_BASELINE_SCOPE`, not `UNKNOWN`.
Unknown or misspelled Policy keys are rejected at every object level; unlike external exchange
payloads, repository-owned Policy objects do not tolerate `additionalProperties`.
Official BTC amount units, `contract_size = 1`, and minimum amount are source-contract
requirements. The exact derived option/combo order amount must be at least the minimum. When the
optional official `qty_tick_size` is present, it must be positive and the amount must be its
integer multiple. A known undersized or published-grid-misaligned Policy target is target-size
liquidity ineligibility; it is never rounded. Absence of that optional field is not `UNKNOWN` and
does not authorize an inferred grid from any undocumented field. Missing/invalid required amount
metadata, or an invalid present step, is `UNKNOWN` unless another independent gate is already
known to fail.

Every runtime limit is a positive integer;
`time_boundary_poll_interval_ms <= 1000`,
`time_boundary_poll_interval_ms <= ticker_source_stale_deadline_ms`,
`rpc_deadline_ms >= time_boundary_poll_interval_ms`,
`session_liveness_deadline_ms > heartbeat_interval_seconds × 1000`, and
`clock_stale_deadline_ms > clock_refresh_interval_ms`. The implementation has no operational
deadline defaults. These values are versioned operating calibration, not scientifically optimal
trading parameters.

Reconnect backoff uses `time_boundary_poll_interval_ms` as its initial bound and
`rpc_deadline_ms` as its maximum bound; it has no separate implementation cadence.
WebSocket open and close use that same `rpc_deadline_ms`; no connection deadline is hard-coded.

The construction tests use at least two different Policy fixtures so a fixed implementation
constant cannot masquerade as configuration.

Construction establishes the schema, loader, and non-production fixtures; it does not select a
permanent or secretly preferred live parameter set. The later production observation command must
name and approve the exact external Policy path and content digest to observe.

The Policy is UTF-8 JSON without BOM: one top-level object, duplicate keys and non-finite numbers
rejected, numeric tokens parsed directly to `Decimal`. Before any subscription, startup reads its
exact bytes once, computes `sha256:<hex>` over those bytes, and compares it with the required
human-approved expected digest from the command. Missing/mismatch fails closed. The runtime then
uses only the immutable parsed in-memory Policy; later file mutation cannot alter the run.

### Frozen during one run, replaceable between runs

The Policy's verified exact-byte content digest is bound before a process starts and recorded in
every event and run summary. The process rejects hot reload and cannot mutate, approve, promote,
or replace its own Policy.

After an observation interval, a human may approve a successor inside the already authorized
Policy schema. It may change target quantity, TTE bands/gaps and call/put inclusion,
lookbacks/weights/floor, Delta boundaries, activation/clear ratios and counts, or separation. The
successor receives a new content identity, a new runtime instance, and a new forward observation
interval. Earlier events keep their original meaning and are never relabeled or backfilled.

A change to the baseline formula, source family, structure family, or evaluation claim is not a
parameter adjustment; it requires a new task and owning-contract change. Automatic training,
automatic selection, and automatic deployment are out of scope.

Because this task has no future realized-volatility or trade Outcome labels, a successor based
only on these results may improve operability, coverage, frequency, or flicker behavior. It may
not be called a better forecast or a better trading strategy.

The first human-approved observation Policy may deliberately use broad bands and low persistence
to learn whether the public pipeline produces enough usable evaluations, provided every schema
invariant still holds—especially `activation_ratio > 1`. That is operational calibration, not a
profitable-threshold recommendation. After each frozen forward interval, a human may loosen or
tighten a successor for coverage/frequency/flicker and observe it prospectively. Evolving the
volatility estimator itself, or claiming improved prediction, waits for a later task that first
declares a strictly future horizon-matched realized-volatility/settlement label and comparator;
this Radar neither collects nor backtests that label.

## Product and source contract

### Product

- Deribit production public data only;
- active `BTC_USDC` linear options discovered in the `USDC` currency namespace and then filtered
  by official `base_currency = BTC`, settlement/quote currency, instrument kind, and price index;
- Monitor universe: trusted `0 < TTE <= 72 hours`;
- Policy TTE bands use explicit non-overlapping `(lower, upper]` boundaries with separate
  evaluation denominators;
- initial detector scope excludes any expiry whose official 30-minute delivery-price window has
  begun;
- same-expiry, same-option-type, 1:1 protective verticals only for the atomic-quote layer.

`TTE <= 30 minutes` has `detector_applicability = OUT_OF_BASELINE_SCOPE`, a known model limitation
rather than `UNKNOWN`. The Monitor still observes it, but no Layer 1 `detector_state` is evaluated
for it and it is excluded from the detector denominator. A future detector may cover that
interval only after explicitly modeling the partially formed delivery TWAP/estimated delivery
price.

### Exact public source route

- bootstrap active options with `public/get_instruments` using the official `USDC` currency
  namespace, then filter to BTC-USDC linear options;
- follow `instrument.state.option.USDC`;
- bootstrap active combos with `public/get_combos` for `USDC`, then filter official legs to
  BTC-USDC and fetch each admitted combo's official instrument metadata before using its amount
  constraints or book;
- follow `instrument.state.option_combo.USDC`;
- acknowledge and buffer public `platform_state` and
  `platform_state.public_methods_state`, call `public/status` to bootstrap current BTC/index lock
  state and prove public-method access, then reconcile buffered platform notifications;
- bootstrap and refresh public Deribit time with `public/get_time`;
- use only `deribit_price_index.btc_usdc` for the baseline;
- use only `ticker.<instrument_name>.100ms` for each option's official
  `underlying_price`/`underlying_index` forward facts;
- use only `book.<instrument_name>.100ms` snapshots and changes for option and active-combo depth;
- subscribe to matching combo books only while a relevant anomaly is active.

Subscriptions are dynamic, sent in bounded batches within the exchange limit, and accepted only
after their acknowledgements are checked. New lifecycle members are not inferred from names; their
official metadata must be fetched before use.

Every index/ticker channel must deliver its own initial usable notification and every book its own
snapshot; reconnect invalidates all of them. Apart from status/time/catalog/new-member metadata
bootstrap, no REST polling or alternate index/ticker interval may feed a detector observation.

One option ticker notification is a complete snapshot, not a sequenced change. Its consumed shape,
candidate currentness, and application disposition are recorded independently. A shape-valid
snapshot older than the accepted current fact is `LATE_IGNORED`; equal timestamps use
`ingress_seq` order. A malformed or ahead candidate is rejected without overwriting a
still-current accepted fact. None of those rejected candidates requests resubscription, ends an
episode, changes coverage, or resets global continuity.

An accepted ticker remains current exactly while
`ticker.source_timestamp_ms <= trusted_time.upper_ms <= ticker.source_timestamp_ms +
ticker_source_stale_deadline_ms`; equality at either boundary is current. Only crossing the upper
TTL cutoff latches the accepted ticker generation stale. Clock narrowing cannot revive it; only a
newly acknowledged generation with a strictly later applied ticker may recover the option.
Recovery with the same numeric forward updates current truth but is not itself countable.
When evaluation reaches a truly unavailable forward gate, the affected option becomes `UNKNOWN`,
an active episode ends `UNKNOWN_AT_GAP`, and Layer 2 stops. This local loss is recorded separately
from global continuity. A known amount/off-grid failure or insufficient target bid depth before
that gate remains `KNOWN_INELIGIBLE`.

Option and combo catalog bootstrap is race-free: acknowledge and buffer the lifecycle stream,
fetch the catalog snapshot, then reconcile buffered events in causal order before declaring the
catalog complete. Negative aggregate or no-combo claims stay `UNKNOWN` until reconciliation
finishes.

Platform startup never defaults an unseen `maintenance = false`. Platform-dependent state stays
unusable until the buffered platform subscriptions are acknowledged; `public/status` proves no
all-currency or consumed-BTC-index lock; later time/catalog/subscription requests succeed; and
fresh index coverage is established. This is the global platform boundary, not a global
all-option barrier: each option's initial ticker and book snapshot gates only that detector.
A public-method denial, relevant lock, or maintenance/break notification invalidates dependent
state immediately. Recovery notifications alone do not restore it; the same bootstrap conditions
must be rebuilt.

Reducer-owned platform state keeps six independent facts: lock snapshot, maintenance guard,
public-method guard, post-status probe, fresh-index coverage, and bootstrap epoch. `usable` is a
pure derived predicate over those facts. A negative maintenance or public-method guard is latched
for its epoch and no later success of an unrelated probe in that same epoch may overwrite it.

The WebSocket acknowledges `public/set_heartbeat` at the Policy's frozen
`heartbeat_interval_seconds` before market state becomes usable. The exact consumed response
shapes are `public/set_heartbeat -> "ok"` and
`public/test -> {"version": <non-empty string>, ...}`. The client answers every `test_request` with
`public/test`. Crossing the frozen `session_liveness_deadline_ms`, a failed heartbeat/test
response, or a connection close makes all dependent state `UNKNOWN` and ends affected episodes
`UNKNOWN_AT_GAP`; reconnect rebuilds subscriptions, snapshots, catalogs, and baseline coverage.
Heartbeat traffic proves connection liveness only: it neither refreshes an economic quote nor
creates a detector observation.

The socket reader only decodes and stamps every notification, success/error/late RPC response, and
heartbeat response with one `session_epoch`, `ingress_seq`, and local
`received_monotonic_ms`. Every frame enters one bounded queue. One synchronous reducer owns all
economic, subscription, catalog, platform, episode, coverage, and Layer 2 state; its complete call
tree does not await network I/O. It returns finite `PendingRpc` commands whose responses re-enter
the same queue. Heartbeat `test_request` control may enqueue guarded `public/test` work while
catalog RPC work is blocked, but neither it nor its response recursively mutates economic state.
Bootstrap and steady state share the same Policy
`notification_queue_lag_deadline_ms` and maximum-lag diagnostic. Queue overflow is a session gap.
Reconnect retires the old session epoch, pending requests, and channel generations exactly once.

Each `PendingRpc` freezes request purpose, method/params, session epoch, scope, channel generation
where applicable, origin `FactBoundary`, Policy-derived absolute deadline, and failure scope.
Reducer-owned channel state is exactly
`UNSUBSCRIBED | SUBSCRIBE_PENDING | ACKNOWLEDGED | UNSUBSCRIBE_PENDING | RETIRED`. Pre-ACK frames
cannot change market truth and reconcile exactly once after successful ACK; retired epoch or
generation frames have zero business side effects.

Raw external payloads tolerate additional unknown fields. Missing, invalid, or changed fields
that this task actually consumes fail closed at their smallest consumer. The implementation may
not reject the whole feed merely because Deribit adds an unrelated field.

No private, account, RFQ, combo-creation, order, fill, maker, or test-environment method is
permitted. The only allowed `public/test` call is the required response to a `test_request` on the
already established production-public heartbeat; it cannot be initiated as a market/business
probe.

## Market-state semantics

### Known-at order

Every accepted fact receives a local monotonic `causal_seq`. Cross-instrument channels do not have
one exchange-global sequence. “Strict as-of” therefore means the latest individually continuous
facts known to this process at one `causal_seq`; it does not claim a matching-engine-wide
simultaneous snapshot.

One fact that affects multiple instruments is evaluated as one transaction for each exact
`Policy identity × expiry_timestamp × option_type` scope: all affected instruments are calculated
before the aggregate is settled once. Iteration order may not expose transient partial truth.

### Order-book validity

The first accepted subscription notification must be a complete snapshot. Later changes require
exact `prev_change_id -> change_id` continuity. A gap, reconnect, invalid/crossed book, lifecycle
loss, or explicit platform/connection failure invalidates only affected consumers until a new
snapshot is accepted.

The book timestamp is the time of its last mutation. A quiet but continuously maintained book
does not become stale merely because no level changed for several seconds, and the runtime must
not resubscribe just to make an unchanged quote look newer. Quote mutation age is recorded as a
diagnostic only. Connection health, subscription acknowledgement, snapshot establishment,
sequence continuity, and instrument state establish whether the current public book is usable.

An empty bid side or cumulative bid depth below the Policy target is known
option liquidity ineligibility and per-instrument `NO_ANOMALY`, not `UNKNOWN`. It short-circuits
before ticker/forward/IV inputs are required; once target-size bid depth exists, missing pricing
facts are `UNKNOWN`.

### Clock and boundaries

The Monitor uses Deribit server time advanced by local monotonic elapsed time and carries an
explicit uncertainty bound. A detector TTE band is usable only when the full trusted-time
uncertainty interval lies within the band and outside the settlement window. Crossing a TTE,
settlement, freshness, or lifecycle boundary may trigger reevaluation, but an arbitrary timer may
not reuse an unproved or gapped quote to create an episode.

Detector, aggregate, coverage, and membership share one pure time classification:
`IN_BAND | ADJACENT_BAND_BOUNDARY | POLICY_GAP | FINAL_WINDOW | MONITOR_BOUNDARY |
OUT_OF_MONITOR_SCOPE`. Adjacent/monitor boundaries are unresolved; known Policy gaps/final
windows are known absent scope. Membership changes split coverage at one causal/monotonic
boundary before subscription awaits.

For every `public/get_time` request, local monotonic send/receive instants bound time at receipt as
`base = [returned_server_ms, returned_server_ms + 1 ms + round_trip_ms]`. With monotonic elapsed
`e_ms`, expand this by the fixed 1000 ppm operational drift budget:
`[base.lower + e_ms × (1 - 0.001), base.upper + e_ms × (1 + 0.001)]`. Clock math is
integer/rational milliseconds with lower rounded down and upper rounded up, never binary-float
inward rounding. Refresh and stale deadlines come from the Policy's `runtime_limits`; advance the
prior interval to the new receive instant and intersect it with the new interval as the next base.
An empty intersection or crossing `clock_stale_deadline_ms` is a clock gap: dependent state becomes
`UNKNOWN`, an active episode ends `UNKNOWN_AT_GAP`, and a fresh clock bootstrap is required. The
fixed drift budget and frozen operational limits are recorded in the run summary and are not
trading calibration parameters.

### Index-minute coverage

Validate the official index notification field `data.timestamp` as integer milliseconds, map it
to internal `source_timestamp_ms`, and assign `deribit_price_index.btc_usdc` ticks by
`floor(source_timestamp_ms / 60_000)`. Require non-decreasing source timestamps and order ties by
`causal_seq`. Seal a minute only after continuous subscription coverage for its full half-open
interval, at least one assigned tick, trusted-time lower bound at/after minute end, and index
timestamp watermark at/after minute end. The close is the last causal tick in that minute; no
near-boundary tick is required. A timestamp regression or late tick for a sealed minute is a gap:
never rewrite the close, invalidate rolling returns, and restart warm-up.

The baseline API is a per-band structured `IndexTailStatus` query with exactly
`AVAILABLE | WARMUP | TIME_BOUNDARY_PENDING | WATERMARK_PENDING | WINDOW_GAP | SOURCE_STALE |
CONTINUITY_GAP`. It proves both internal continuity for the requested lookback and exact alignment
to the minute immediately before the one trusted current minute. A trusted interval spanning a
minute boundary is `TIME_BOUNDARY_PENDING`; a trusted single current minute whose source watermark
has not crossed the expected tail end is `WATERMARK_PENDING`. Normal rollover never clears
history. Sixty returns require 61 consecutive covered closes.

`WINDOW_GAP` is isolated by requested band: an older missing minute can invalidate a longer
lookback while a shorter consecutive tail remains `AVAILABLE`, and it never resubscribes the index.
`SOURCE_STALE` and `CONTINUITY_GAP` invalidate all index consumers and require affected index
resubscription. Pending statuses preserve episode identity in `INDEX_TAIL_PENDING`, pause known
duration, stop Layer 2, reset incomplete persistence, and are never countable observations.
`WARMUP` ends an active episode `UNKNOWN_DETECTOR`; gap statuses end it `UNKNOWN_AT_GAP`. The
normative truth table is the one in `SHORT_VOL_RADAR`; implementation and direct tests may not
override it with string-priority conditions.

## Configured trailing-variance baseline

For one Policy baseline entry keyed by TTE band:

1. parse source and Policy numbers directly to canonical `Decimal` and use one repository-owned
   `decimal.Context(prec=50, rounding=ROUND_HALF_EVEN)` pure function;
2. construct returns in chronological order as
   `context.ln(close_t) - context.ln(close_t_minus_1)`;
3. for each configured lookback `h`, calculate the mean of the last `h` squared returns;
4. in ascending `h` order calculate the weighted sum; weights are finite, non-negative, and
   sum to one;
5. apply the configured strictly positive annualized variance floor after exact division by
   `365 × 24 × 60`;
6. derive remaining-life minutes as
   `[(expiry - trusted_time_upper), (expiry - trusted_time_lower)] / 60_000`, multiply the
   variance rate by both bounds for baseline total-variance interval, and calculate annualized
   baseline volatility directly as `sqrt(rate × 365 × 24 × 60)`;
7. independently inspect official amount minimum/grid, target bid depth, and forward/fixed OTM;
   any available known failure is enough for `NO_ANOMALY`, while a missing fact is `UNKNOWN` only
   when no independent gate is already known to fail;
8. after all three pass, walk visible bids through target BTC and invert that executable sell price
   with the declared official linear-option Black formula to total-volatility interval
   `x = σ × sqrt(T)`;
9. calculate Delta from `x`, apply configured absolute-Delta eligibility, and after it passes
   calculate implied-total-variance interval `x²`;
10. derive
    `IV_interval = [x_low / sqrt(T_high), x_high / sqrt(T_low)]` and compare its richness interval
    with the configured option-type/TTE-band boundaries; classification is known only when the
    entire interval has one truth value.

The same Decimal function supplies runtime and fixed-vector tests. Any final richness interval
that spans an activation/clear boundary is
`UNKNOWN/NUMERICAL_BOUNDARY_UNRESOLVED`.

The trailing-index-variance baseline is shared by calls and puts in the same TTE band. Option type may
change eligibility or detector boundaries, but it cannot create a different realized history of
the same BTC underlying.

OTM is exact at the executable-IV forward: call requires `K > F`, put requires `K < F`.
Absolute-Delta eligibility is inclusive:
`abs_delta_min <= abs(delta) <= abs_delta_max`.

For an IV-richness ratio `r`, the IV premium is `(r - 1) × 100%` and the equivalent total-variance
ratio is `r²`. These percentages are never interchanged.

Warm-up requires `largest_configured_lookback + 1` consecutive covered minute closes to form the
required number of returns; it is derived from Policy rather than a fixed close count.
Price/quantity/fee-free credit arithmetic uses `Decimal`; model values must be finite. IV inversion
uses the owning contract's one canonical total-volatility oracle: finite-domain validation,
`x = σ × sqrt(T)`, the declared binary64 `math.erf/log/sqrt` formula, a bracket from
`x_high = 1` with at most 32 doublings, and at most 64 bisection updates with one exact tie rule.
A positive price outside the finite formula domain or an unbracketed price is `UNKNOWN`. The final
bracket is the decision total-volatility interval; if Delta eligibility or an activation/clear comparison
changes truth over its conservative bound (including any analytic Delta stationary point), the
dependent result is
`UNKNOWN/NUMERICAL_BOUNDARY_UNRESOLVED`. The same repository-owned pure function serves runtime
and fixed-vector tests; half-a-tick residual is not an alternate decision rule. The owning
contract fixes `F`, `T`, call/put price, Delta, and fixed OTM formulas; they are not Policy choices.

This is a transparent causal trailing-index-variance baseline, not a delivery-TWAP distribution
forecast, validated physical forecast, model-free variance risk premium, tail model, or edge
claim. Calls and puts have separate episode denominators.
Evaluation counts are separated by configured TTE band; an episode is attributed only to its
activation band. A single OTM IV contains skew, jump, and tail pricing that the baseline does not
explain.

## Detector state and episodes

Each `Policy identity × instrument_name` scope has an activation/clear tracker. Episode identity
is `runtime identity × Policy identity × instrument_name × activation_causal_seq`; TTE band is an
activation attribute, not identity:

```text
UNKNOWN
          a required detector fact is missing/invalid, or derived classification is numerically unresolved
ARMED     this instrument is usable and no episode is active
ACTIVE    this instrument passed activation
CLEARING  this instrument's clear persistence is pending
BAND_SUSPENDED
          trusted time straddles a Policy boundary while market-source continuity stays known
INDEX_TAIL_PENDING
          normal minute rollover is unresolved while index continuity and stored history stay known
```

Activation observations use
`iv_richness_ratio >= activation_ratio`, clear observations use
`iv_richness_ratio <= clear_ratio`, and values between the two boundaries preserve the current
instrument state. Counts and minimum separation come from the Policy.
One observation can follow a counted observation only when
`later.time_lower_bound - prior_counted.time_upper_bound >= minimum_separation`; equality counts.
A qualifying observation with overlapping intervals or a smaller guaranteed gap neither
increments nor resets.
While non-active, any known observation below activation resets the activation count; while
active/clearing, any known observation above clear resets the clear count and restores `ACTIVE`.
A qualifying observation inside the minimum separation neither increments nor resets, but any
intervening known non-qualifying observation resets immediately. Equality is inclusive.
Every committed fact explicitly names all affected scopes and creates one short-lived,
non-durable `FactBoundary`. For every affected scope the reducer first computes a pure
`CurrentEvaluation`, then constructs one `ScopeSnapshot`, then settles current results, trackers,
aggregate, coverage, and Layer 2 exactly once in that boundary. Hard `UNKNOWN`, known
ineligibility, membership loss, and scope exit apply unconditionally. Only richness
activation/clear calls persistence observation, and only when
`observation_eligibility.countable = true`.

Clock revision participates in current classification but is not itself a countable persistence
observation. Observation identity contains only target-quantity bid levels, forward, current
baseline, and discrete TTE/currentness classification. Ask-only changes, depth beyond the target,
repeated messages, heartbeats, metadata-only changes, and unchanged reduced state do not activate,
clear, or reset persistence.

While trusted time straddles a boundary whose adjacent band has a rule for this instrument's
option type, detector output is temporarily `UNKNOWN/TIME_BAND_BOUNDARY`; an active episode becomes
`BAND_SUSPENDED`, its known-active clock pauses, Layer 2 becomes `NOT_EVALUATED`, and incomplete
confirmation counts reset. Once the full interval lies in that adjacent same-option-type band,
continuous sources let the same episode resume `ACTIVE` under new parameters without a second
event. A non-active tracker resumes `ARMED`.

If the time interval stops lying wholly inside the current band and the other side is a deliberate
Policy gap, a band without this option-type rule, or the final 30 minutes, an active episode ends
immediately `OUT_OF_BASELINE_SCOPE` at the last trusted active boundary. Layer 2 stops; it does not
wait for the interval to resolve wholly outside, and later applicability requires fresh
activation.

A gap invalidates only the affected instrument and its quotes and cancels pending observations. If
its episode was active, that observed episode ends with `UNKNOWN_AT_GAP` at the last trusted
boundary. A different known active instrument keeps aggregate state `ANOMALY_ACTIVE` with degraded
coverage; with none active and some unresolved, aggregate state is `UNKNOWN`.

After complete resync, fresh activation persistence creates a new episode identity. It may
reference the pre-gap episode as an uncertain predecessor, but never claims continuity across the
gap.

Session, clock/index, one-option channel, option catalog, combo Layer 2,
transient/rate-limit request, and fatal consumed-protocol incompatibility are separate failure
domains. Combo subscribe/unsubscribe/resnapshot failure makes only Layer 2 `UNKNOWN`. One root
failure records one canonical `UNKNOWN` reason. Reconnect retains runtime identity, ends the old
episode `UNKNOWN_AT_GAP`, and requires fresh activation for a new episode identity.

Known target-depth/minimum-amount, OTM, or Delta ineligibility produces `NO_ANOMALY` and ends an
active episode immediately as `KNOWN_INELIGIBLE` with detail. Expiry, deactivation, or catalog
removal ends `MEMBERSHIP_LOSS`. Any detector `UNKNOWN` except the time-band suspension or a
separately classified source-continuity gap ends `UNKNOWN_DETECTOR` with a
missing/invalid/numerical detail. Operator stop ends
`CENSORED_AT_STOP`; only richness clearing uses clear persistence and ends `CLEAR`. Every end makes
Layer 2 `NOT_EVALUATED`. Recovery/readmission requires fresh activation; only the adjacent
same-option-type band suspension above preserves episode identity.

One instrument's `ARMED -> ACTIVE` transition creates one short-leg anomaly episode and one
`SHORT_VOL_ANOMALY_EVENT`. The event is not rewritten as quotes change.

## Three separate layers

### Layer 1 — Short Vol anomaly

`detector_state` depends only on option/index/clock/Policy facts. It never depends on combo
catalog or combo books.

### Layer 2 — public official atomic availability

Only while one short-leg episode is active, inspect active official two-leg combos whose signed
legs can form the required same-expiry 1:1 protective call or put credit vertical for that exact
short instrument. Derive whether the desired signed legs require buying or selling the official
combo; do not assume every credit orientation consumes the bid.

The target vectors are fixed: call credit sells the lower-strike call and buys the higher-strike
call; put credit sells the higher-strike put and buys the lower-strike put. Official metadata
defines `legs[].amount`, the signed leg vector for buying the combo. Find the signed combo order
amount that maps that vector exactly to the desired legs. With official BTC-USDC
`contract_size = 1` and amount in BTC, the only authorized results are `+target_btc` for `BUY`
(consume asks) or `-target_btc` for `SELL` (consume bids); any other vector is not a match.
The official minimum trade amount must permit the exact target; when optional official
`qty_tick_size` is published, the target must also align exactly. No rounding is allowed.
Preserve the signed depth-weighted combo price and calculate:

```text
gross_entry_credit_usdc =
    -signed_order_amount_btc × required_side_vwap_usdc_per_btc
```

Never take the absolute value; availability requires `gross_entry_credit_usdc > 0`.

`public_atomic_quote_state` is:

- `NOT_EVALUATED`: no anomaly is active, so no combo claim was attempted;
- `UNKNOWN`: required combo catalog, metadata, lifecycle, or book continuity is unavailable;
- `NO_ACTIVE_COMBO`: the complete official catalog has no matching active combo;
- `NO_TARGET_SIZE_CREDIT_QUOTE`: matching combos are known but none has enough depth on the bid or
  ask implied by the desired legs with positive normalized gross entry credit;
- `PUBLIC_ATOMIC_QUOTE_AVAILABLE`: at least one matching official combo does.

The two negative combo states require the completeness conditions above. Positive availability is
existential and does not wait for unrelated combo books, but its event makes no best-price or
complete-selection claim.

Protective-leg discovery is independently
`KNOWN_PRESENT | KNOWN_ABSENT | UNRESOLVED`. `KNOWN_ABSENT` after complete option catalog,
relevant leg metadata, lifecycle, and combo catalog reconciliation is a known
`NO_ACTIVE_COMBO`; `UNRESOLVED` is `UNKNOWN`. A lifecycle burst during one combo authoritative
refresh marks it dirty and produces at most one trailing authoritative refresh; it never lets an
older snapshot overwrite newer lifecycle truth.

The component-leg bid/ask is not implemented in this closure and may never substitute for this
state. No Greek sign gate, arbitrary wing-width percentage, future delivery-fee estimate,
account-fee estimate, or total-loss qualification belongs to this availability fact.

An official atomic public quote is still a quote, not a fill or a guarantee it remains available.
If optional public quantity-step metadata is absent, it also does not prove that a later private
order at that amount will be accepted.

### Layer 3 — future execution

Creating a combo, requesting a quote, placing a post-only combo maker order, canceling/repricing,
and proving `ORDER_WORKING | FILLED` require private trade and account authority. They are not
implemented, represented, or simulated in this task. Two separately placed leg orders are not an
atomic substitute.

## Durable evidence

Only these small runtime evidence object kinds are permitted:

1. `SHORT_VOL_ANOMALY_EVENT`, once per activated episode;
2. `PUBLIC_ATOMIC_QUOTE_EVENT`, once per `(episode_id, combo_id)` first observed available;
3. one `RADAR_RUN_SUMMARY` when the process stops.

An anomaly event records only:

- Policy/code/runtime/episode identity and causal time;
- one short-leg instrument, expiry, option type, activation TTE band, and aggregate coverage
  state;
- configured target BTC quantity and detector boundaries;
- baseline feature summary and output, trusted-time interval, and remaining-life `T` interval;
- that short leg's consumed bid levels, forward, sell price, total-volatility, IV, Delta, implied
  total-variance, and richness lower/upper intervals plus the final classification;
- explicit `NOT_A_DELIVERY_TWAP_DISTRIBUTION_FORECAST` and `NOT_VALIDATED_FORECAST`
  non-claims.

An atomic event directly references its short-leg anomaly episode and records only official combo
identity, signed legs, that episode's current active detector causal binding, required combo order
direction, target BTC quantity, consumed combo bid or ask levels, positive normalized gross entry
credit, source times, and public-quote non-claims.

Quote changes and `AVAILABLE -> unavailable -> AVAILABLE` within that pair do not rewrite the
event; a second combo or new episode may write independently. The emitted pair is registered only
after a successful exclusive write. Evidence conflicts remain hard errors and are never
overwritten or caught-and-continued.

The run summary records coverage time, usable detector evaluations, anomaly activations, episode
ends by
`CLEAR | KNOWN_INELIGIBLE | OUT_OF_BASELINE_SCOPE | MEMBERSHIP_LOSS | UNKNOWN_DETECTOR |
UNKNOWN_AT_GAP | CENSORED_AT_STOP`, known-active duration by end reason, band-suspended duration,
atomic-state transitions, detector `UNKNOWN` transitions by reason, and Policy identity. These are
reduced business-state transitions, never message counts. It contains no full market chain.

It also requires strict `operational_diagnostics_schema_version = 3` with the exact
`SHORT_VOL_RADAR` schema:

- all nine frozen `runtime_limits`;
- ingress received/reduced/gap-or-duplicate counts, queue high-water, maximum receive-to-reduce
  lag, and overflow;
- per-method request/success/error/late/rate-limit counts and latency count/sum/max;
- received/processed counts and observation-duration-derived nullable rates for every fixed
  channel class;
- current/peak subscribed instrument and channel counts;
- heartbeat request/result and latency diagnostics;
- reconnect, session/index gap, index resubscribe, option resync, clock refresh,
  option-catalog refresh, and combo authoritative-refresh diagnostics;
- core source shape rows containing only source, counts, final validation, and sorted consumed
  key/type pairs;
- separate ticker application/currentness counts and bounded late-regression rows;
- global continuity epoch/restart counts and bounded option-local unavailable/recovery intervals;
- nullable first same-current-scope joint-witness time and continuous global-continuity duration
  after that witness.

These transport facts are counted once per reduced envelope and never enter business denominators.

Coverage partitions the exact half-open interval
`[runtime_started_monotonic_ms, clean_stop_monotonic_ms)` into one global state at every
millisecond across current Policy-applicable aggregate scopes:

- `NO_APPLICABLE_SCOPE`: reconciled catalog and trusted time are known and prove no non-empty
  expiry/type scope currently has that option-type rule;
- `KNOWN_COMPLETE`: all current scopes/instruments have known detector state;
- `KNOWN_DEGRADED`: a known active witness exists while another current instrument/scope is
  unresolved;
- `UNKNOWN`: scope existence itself or a required prerequisite is unresolved, or a scope exists
  but warm-up, band suspension, or unresolved facts prevent the two known coverage states.

Dynamic catalog/band changes split at their accepted causal boundary. Band-suspended duration is a
diagnostic subset, not a fifth partition. The validator requires non-negative, non-overlapping,
gap-free durations and
`coverage_partition_error_ms = observation_interval_ms - (known_complete_ms +
known_degraded_ms + unknown_ms + no_applicable_scope_ms) = 0`.
Each version-3 segment also records its entry reason, sorted bounded affected scopes, and
`global_continuity_epoch`; same-state activity does not create diagnostic market persistence.

`radar_runtime` is the only writer. The current readers are the strict repository-owned schema
validator and operator delivery report; no downstream business module consumes them in this
closure. Required fields cannot be silently null, unknown repository-owned fields fail
validation, and only explicitly unavailable diagnostics may be nullable. One evidence directory
binds one Policy and runtime identity; mixed identities fail closed. Cross-Policy compatibility
is `NOT_COMPARABLE` for forecast or trading claims, although named operational counts may be
displayed side by side without causal inference.

The Policy schema remains version 3 and unchanged. New strict run summaries require diagnostics
schema version 3. The reader continues validating schema version 2 under its original exact shape
only so sealed `attempt-001` remains immutable truthful evidence; version 2 is
`MIGRATION_REQUIRED` for new global-continuity/local-availability acceptance and cannot be
rewritten or upgraded. This task adds no migration or replay path.

Each object has a simple strict repository-owned schema and Policy content identity. No separate
source-document manifest, Git-object provenance graph, hit-only recomputation command, full-feed
archive, or replay object is created.

The production observation command runs only from a clean Git worktree at one exact `HEAD`.
Startup rejects staged, tracked, or untracked changes and every object records that commit as
`code_identity`. This is a minimal identity guard, not a provenance graph or correctness claim.

## Product operating behavior

One continuously running `radar_runtime` process:

1. loads and validates one exact Policy;
2. establishes time, catalogs, lifecycle subscriptions, index, tickers, and option books;
3. maintains bounded current state and the largest configured rolling return window;
4. evaluates only causally affected detector scopes, once per exact aggregate transaction;
5. writes one anomaly event on activation;
6. while active, evaluates matching official combo availability independently and writes atomic
   events only when availability first becomes known for a combo;
7. keeps ordinary no-anomaly states and market updates transient;
8. writes one run summary on clean operator stop;
9. stops only on operator signal or process failure, not because a fixed business duration
   elapsed.

A restart creates a new runtime identity and empty detector memory. No warm-state persistence or
cross-process episode de-duplication is implemented.

## Validation harness

The smallest proportional harness is:

1. direct pure/state-sequence tests;
2. integration tests with public source fixtures;
3. one separately authorized `REACHABILITY_SMOKE` using one exact Policy;
4. one separately approved `OPERATIONAL_SOAK` after its diagnostic contract and stop condition are
   accepted by a human;
5. ordinary schema validation of any event actually emitted.

No replay, second calculation path, independent recomputation, provenance CLI, market archive,
Outcome collector, or qualification run is required.

## Evidence boundary

**Proves:** a versioned public Radar can continuously produce honest detector state and keep
official atomic-quote availability separate, under real production-public connectivity.

**Does not prove:** forecast accuracy, natural anomaly frequency outside the observed interval,
edge, Candidate quality, a fill, maker feasibility, exact fees, margin, liquidation safety,
future exit liquidity, Outcome, PnL, qualification, promotion, or execution permission.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Implementation scope

**In:**

- `packages/market_monitor/src/market_monitor/`;
- `packages/options_domain/src/options_domain/`;
- `packages/short_vol_radar/src/short_vol_radar/`;
- `apps/radar_runtime/src/radar_runtime/`;
- direct tests under `tests/`;
- the Policy schema/loader and non-production test fixtures;
- minimal events and one run summary.

**Out:**

- replay, recomputation or provenance commands;
- databases, queues, schedulers, services, generic dependency engines, feature stores, model
  registries, hot reload, or automatic tuning;
- private/account APIs, test-environment market sources, combo creation, RFQ, maker/order/fill
  handling, credentials, margin, capital, settlement, or money; the sole exception is
  heartbeat-required production `public/test`;
- legged-price diagnostics, Greeks as structure gates, account or delivery fees, total economic
  maximum loss, Candidate, Shadow, Position, Outcome, research, qualification, or promotion;
- compatibility with removed legacy artifacts and unrelated refactors.

## Acceptance

### Direct behavior

1. TTE tests cover `0`, just above `0`, the settlement-window boundary, just outside it, every
   configured TTE band boundary, exactly `72 hours`, and above `72 hours`, including clock
   uncertainty.
2. Adapter tests prove the `USDC` namespace and BTC-USDC filters, bounded acknowledged
   subscriptions, subscribe-buffer-snapshot lifecycle reconciliation without a catalog race,
   initially locked/maintenance platform cases, `public/status` bootstrap/reconciliation,
   `public/get_time` RTT/discontinuity and conservative outward rounding/intersection, exact
   index/ticker/book channel allowlist and initial notifications, official heartbeat/test result
   shapes, non-blocking notification overflow, receive-time queue lag, normal socket close, stale
   subscription generations, late RPC responses, additions/removals, tolerant extra source
   fields, fail-closed consumed fields, snapshot/change continuity, gap/reconnect recovery,
   affected-only invalidation, exact official
   `data.timestamp` mapping and index-minute sealing, timestamp regression, and a late tick for a
   sealed minute.
3. Quiet-book tests prove that no-change time does not invalidate or artificially refresh a book.
   Empty and
   insufficient books remain known liquidity states rather than `UNKNOWN`.
4. Baseline tests cover configured lookbacks/weights/floor, derived warm-up, missing minutes,
   partial startup minutes, all load-time validation relationships, explicit Policy band gaps,
   exact remaining-life scaling, no future input, target-size bid walking, canonical
   total-volatility Black inversion, fixed OTM/configured Delta eligibility,
   numerical-boundary fail-closed behavior, finite values, locked Decimal/model fixed vectors, and
   at least two different Policy fixtures. Policy-loader tests also reject unknown keys,
   duplicate keys, BOM/non-finite values, and a missing/mismatched exact-byte digest before any
   subscription, and prove later file mutation cannot change the immutable in-memory Policy.
5. Episode tests cover activation, interval-bounded separation including equality/overlap,
   interrupted/too-soon persistence, maintenance, clear/re-arm, every exact end reason,
   `UNKNOWN_AT_GAP` termination followed by fresh new-episode activation,
   duplicate/heartbeat/unchanged suppression, adjacent-band suspend/resume without a mechanical
   second episode, scope-gap exit, separate call/put counts, activation-band attribution, one
   event per short-leg episode, and the aggregate truth table for positive witness, complete
   no-anomaly, incomplete `UNKNOWN`, and empty-scope non-evaluation.
6. Atomic tests cover official signed directions for call/put credits, wrong expiry/type/ratio,
   required combo buy/sell direction, bid-versus-ask selection, complete no-combo, known
   no-credit-depth, positive and negative signed combo prices, no absolute-value normalization,
   option/combo amount-minimum failure, optional quantity-step absence, published-grid
   alignment/failure without rounding, combo `UNKNOWN`, positive normalized target-size atomic
   credit, and proof that no combo state changes detector truth. They also prove that negative
   states require complete relevant scope while one positive witness makes no best-market claim.
7. Artifact tests cover minimal schemas, Policy identity, unit-bearing decimals, null rates,
   event de-duplication, dirty-worktree rejection, exact clean-`HEAD` code identity, and absence of
   normal full-chain/no-anomaly persistence; injected coverage overlap/gaps fail validation.
8. Integration tests prove one public-only process and the absence of replay, recomputation,
   private, maker, Candidate, Shadow, Position, and Outcome paths.
9. Root-cause orchestration tests prove every notification, success/error/late RPC response, and
   heartbeat response receives consecutive ingress identity and reduces exactly once; sustained
   market traffic cannot starve a successful metadata response; pre-ACK frames have zero market
   effect and reconcile exactly once after ACK; retired session/generation frames have zero
   business side effects; and a maintenance/public-method negative guard cannot be overwritten in
   the same epoch.
10. Causal-interleaving tests prove response receive-time ordering cannot regress coverage;
    `open -> close -> metadata response`, snapshot-pending close, lifecycle during catalog
    bootstrap reconciliation, and lifecycle during combo refresh all preserve newer lifecycle
    truth; blocked subscribe/unsubscribe work still permits timely heartbeat control; and a combo
    lifecycle burst produces exactly one trailing authoritative refresh.
11. Currentness tests prove initial bootstrap warm-up is not a real index gap, normal minute
    rollover enters pending without clearing history, a trusted interval spanning a minute cannot
    select an old tail, a real global gap increments the continuity epoch and recovery establishes
    a new same-scope witness with exact duration, window gaps are isolated by per-band lookback,
    and `amount UNKNOWN -> VALID` yields known current and `ARMED` with zero persistence count.
12. Ticker snapshot tests prove shape/currentness/application separation; equal-timestamp ingress
    ordering; older `LATE_IGNORED` preserving the accepted ticker, episode, coverage, commands, and
    witness; true TTL stale/recovery behavior; exact bounded diagnostic fields/counts; and no
    application disposition contaminating source-shape validity.
13. Scope tests prove `detector_coverage` and `has_current_full_formula` come from the same full
    current aggregate snapshot, including an affected subset that has no formula while an
    unchanged current member does, and reject historical/subset cross-combination.
14. Evidence tests prove version-3 reason/scope/epoch coverage, global continuity, bounded
    option-local availability, writer-edge independence, and continued strict validation of
    sealed version-2 `attempt-001`.
15. Deterministic tests run the same interleaving sequence repeatedly and require identical
    current results, episode states, coverage, emitted commands, and durable edges. Evidence
    storage `OSError` is fatal with zero reconnect.

### Required commands after the construction gate

- checkout the bounded branch, then `make sync`;
- focused tests for the four owning modules;
- `make check`;
- after the separate production observation gate:
  `.venv/bin/python -m radar_runtime observe --policy <exact-policy-path> --expected-policy-digest <sha256:hex> --evidence-dir <new-empty-evidence-dir>`.

The live command rejects a missing/invalid/mismatched Policy digest, dirty Git worktree, or
non-empty evidence directory. Evidence stays outside the Git worktree. There is no recomputation
or provenance command.

### REACHABILITY_SMOKE

The process runs until:

- warm-up completes and at least one real
  `Policy identity × expiry_timestamp × option_type` aggregate detector scope contains one or
  more reconciled catalog instruments, produces at least one full-formula known per-instrument
  evaluation inside that same settled full current-scope snapshot, and with
  `detector_coverage = COMPLETE` produces `NO_ANOMALY` or `ANOMALY_ACTIVE`, after which a human may
  stop it; or
- a human stops it earlier.

A pre-warm-up or all-`UNKNOWN` stop is truthful but does not complete live validation. A degraded
positive witness is truthful evidence but does not by itself establish the full Radar. A complete
usable `NO_ANOMALY` result does complete runtime validation. Natural anomaly and public atomic
availability are separately reported as `OBSERVED | NOT_OBSERVED`; neither is forced by elapsed
time and neither may trigger in-place Policy tuning.

`known_full_detector_formula_evaluation_count` counts only an instrument that passes
minimum-amount, target-depth, OTM, and Delta gates and reaches known baseline volatility,
executable IV interval, and richness classification. Short-circuit known ineligibility is still
truthful `NO_ANOMALY`, but cannot alone establish the formula path.
`complete_aggregate_with_full_formula_evaluation_count` counts only the joint witness where the
same Policy/scope settled full current snapshot is complete and contains that full-formula
evaluation. Still-current unchanged-member results may be reused; stale/historical results, only
the affected subset, and different scopes cannot be combined.

The accepted ledger contains only:

```text
coverage_partition_error_ms = 0
applicable_instrument_count >= 1
known_per_instrument_detector_evaluation_count >= 1
known_full_detector_formula_evaluation_count >= 1
complete_aggregate_detector_evaluation_count >= 1
complete_aggregate_with_full_formula_evaluation_count >= 1
known_full_formula_rate_given_known_per_instrument
complete_aggregate_with_full_formula_rate_given_complete_aggregate
detector_unknown_transition_count_by_reason
distinct_anomaly_episode_count
anomaly_activation_transition_count
anomaly_end_count_by_reason
known_active_duration_ms_sum_by_end_reason
public_atomic_quote_state_transition_count
```

Counts are grouped by Policy identity, option type, and TTE band. Rates with zero/unknown
denominators are `null`. Evaluation and atomic-state transitions use their current band; episode,
activation, clear, and duration metrics stay attributed to the episode's activation band.
Integration spies and artifact inspection—not new production counters—prove zero private API
calls, zero forbidden downstream artifacts, and zero persisted normal market/no-anomaly rows.

This witness proves only that the full formula and complete aggregate are reachable through the
real public wiring. It is not a sustained-operation acceptance and cannot by itself establish the
production Radar.

### OPERATIONAL_SOAK — contract approval required before any production run

Production establishment additionally requires a human-approved continuous-operation acceptance
plan. The prior separately authorized `operational-soak-attempt-001` completed with
`acceptance = NOT_MET`; its version-2 evidence is sealed and remains the authoritative result.
This fact-semantics construction does not infer new live authority and does not run a heartbeat
probe or another Soak. A future plan must name exact code, Policy path/digest, a new empty evidence
directory, and human-frozen global-continuity plus local-availability/current-coverage thresholds.

The implemented strict diagnostic schema records, without persisting full market payloads:

- actual request count, response count, latency, error and rate-limit outcomes by consumed RPC
  method, plus received/processed counts and observation-duration-derived rates by channel class;
- subscribed instrument/channel counts, queue high-water mark, maximum receive-to-process lag,
  and every overflow;
- heartbeat `test_request`/`public/test` round-trip results;
- reconnect, session/index/channel gap, resync, and clock-refresh success/failure;
- option/combo catalog refresh and recovery attempts/results;
- whether every core RPC/channel actually appeared and passed the consumed-field shape check,
  retaining only keys, types, and validation result;
- the uninterrupted covered interval after the first
  `complete_aggregate_with_full_formula_evaluation` witness.

The human-approved stop condition determines the required post-witness stable interval. Any
session/index gap restarts warm-up, requires a new joint witness, and restarts that interval.
These operational diagnostics never enter anomaly, episode, aggregate, atomic-availability, or
future trading denominators. This task requires direct schema/writer tests, but it does not approve
the Policy, stop condition, production connection, or soak, and it does not open the production
observation gate.

### Historical attempt-001 Policy and acceptance checklist

The `OPERATIONAL_SOAK_PRECONDITIONS` construction subgate prepared this historical Policy before
the separately authorized attempt:

```text
predecessor Policy digest =
  sha256:faeff9740a43df6de5c85268571592a5d47d90f9c146b2ba8b812d4e3525e50d

candidate successor Policy path =
  /Users/logan/Optimatrix-soak/policies/operational-soak-successor.json
candidate successor Policy digest =
  sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4

sealed evidence directory =
  /Users/logan/Optimatrix-soak/evidence/operational-soak-attempt-001
```

That Policy kept the predecessor's exact formula family, `0.1 BTC` target,
`(30, 4320]` minute scope, one-minute lookback with weight `1`, `0.01` annualized variance floor,
call/put Delta range `[0, 1]`, activation/clear ratios `1.2/0.9`, activation/clear counts `2/2`,
`1000 ms` separation, and all nine runtime limits. The only parsed field delta is
`band_id: reachability-smoke-30m-to-72h -> operational-soak-30m-to-72h`; this changes content
identity without tuning business behavior. Both exact files must load through the production
Policy loader, and their parsed JSON must be identical after normalizing only that band label.

The historical attempt-001 stop condition was:

```text
SUCCESS:
  after the most recent real session/index continuity gap,
  a new complete-aggregate full-formula joint witness exists
  AND continuous_covered_after_witness_ms >= 3_600_000,
  then a human performs clean stop.

EARLY STOP OR PROCESS FAILURE:
  write or preserve every truthful artifact available,
  but acceptance = NOT_MET.
```

Normal `TIME_BOUNDARY_PENDING`/`WATERMARK_PENDING` minute rollover does not restart the interval.
A real session/index continuity gap clears the witness, restarts warm-up, requires a new joint
witness, and restarts the full `3_600_000 ms` interval. The duration is an explicit proposed
validation-harness stop boundary, not a product cadence, detector holding rule, or authorization
to connect.

Before attempt-001 was started, its historical pre-run checklist required:

- the exact committed code `HEAD` is reviewed, clean, and equal to its pushed remote branch;
- the Policy exists at the exact path, its SHA-256 equals the exact digest above, and
  the production loader accepts that path/digest pair;
- semantic comparison to the predecessor Smoke Policy proves that only `band_id` changed;
- the now-sealed evidence directory is empty immediately before startup;
- the human command repeats the exact code `HEAD`, Policy path/digest, evidence directory,
  and `3_600_000 ms` post-witness stop condition;
- no private credential, private API, RFQ, combo creation, order, trade, or stage change is
  included or implied.

The resulting clean-stop summary would have met the historical Soak acceptance only if every item
below passed:

- summary code and Policy identities equal the authorized exact `HEAD` and digest;
- strict summary validation passes and `coverage_partition_error_ms = 0`;
- ingress received and reduced counts are equal, with
  `ingress_gap_or_duplicate_count = 0`, `overflow_count = 0`, and maximum lag at or below the
  frozen `5000 ms` deadline;
- every observed core source has `invalid_count = 0`; every source required for the joint formula
  witness is observed and `VALID`; conditional anomaly/combo sources may truthfully remain
  `NOT_OBSERVED`;
- every consumed RPC row has zero error, late-response, and rate-limit counts; heartbeat has at
  least one successful round trip and zero error; clock refresh has at least one success;
- at least one real scope has all five reachability counts greater than or equal to one:
  applicable instrument, known per-instrument, known full formula, complete aggregate, and
  complete aggregate with full formula;
- `first_joint_witness_monotonic_ms` is non-null and
  `continuous_covered_after_witness_ms >= 3_600_000`;
- reconnect/gap/resync/recovery counts and every `UNKNOWN` reason are reported exactly; historical
  recoveries do not fail acceptance by themselves, but the final witness interval must have
  restarted after the most recent reset-worthy gap;
- anomaly and public atomic quote occurrence are separately reported
  `OBSERVED | NOT_OBSERVED`; neither is required for Soak acceptance;
- artifact inspection proves zero private calls, zero order/trade/downstream artifacts, and zero
  persisted normal-market/no-anomaly rows.

Green precondition tests, a prepared Policy, an empty directory, or prior Smoke evidence do not
open a new Soak gate. Attempt-001 did not pass this checklist.

Attempt-001 is permanently `NOT_MET`: it cannot be reused, modified, migrated, recomputed,
replayed, or accepted under version-3 semantics. Before a new Soak authorization request, focused
tests, `make check`, and old-evidence validation must pass; a heartbeat wire probe must receive its
own explicit authorization; and a human must freeze new global-continuity duration and explicit
local availability/current coverage thresholds. The historical `3_600_000 ms` value is not
silently carried into that future gate.

## Trader-readable acceptance gates

1. **行情真的看得全。** 生产公共连接完成 warm-up，至少一个真实 aggregate 范围在目录与
   所有潜在期权覆盖完整时算出已知 detector 状态，而且同一次完整 aggregate 计算里
   至少真有一只合约走完 `baseline → IV → Delta → richness` 全公式链；只靠深度、OTM
   或 Delta 失格短路不能过关。空集合不能“全都看完”式过关。局部异常会记录，但不能
   拿局部可见冒充全 Radar 建立。断线、缺字段和数据 gap 不会被说成市场平静。
2. **安静挂单不会被误杀。** 订单簿只因明确断线、gap、失效状态或坏数据变成
   `UNKNOWN`，不会因为五秒没变化就反复洗新；同时官方 heartbeat 会识别半开连接，
   但 heartbeat 本身绝不把旧盘口“续命”为新报价。
3. **末日最后半小时不装懂。** 交割 TWAP 开始后明确标记
   `OUT_OF_BASELINE_SCOPE`，不拿普通到期模型硬算。
4. **参考波动是可审计的简基线，不是假装知道未来。** call/put 分开计数，但同一期限桶
   共享同一个 BTC 标的基线：把只使用过去数据的 1 分钟指数收益平方做配置化加权，再按
   精确剩余分钟缩放。它只是 trailing-index-variance Radar 参照，不是交割 TWAP
   分布预测，也不叫已验证预测、VRP 或 edge。
5. **参数能校准，但历史不会被改写。** 数量、Delta、期限桶、回看、触发和清除来自
   Policy 文件；第一版可为了观察覆盖率、频率和抖动而定得宽松，但触发比仍必须大于
   1。一次运行内固定，下一套参数使用新身份和新观察区间；没有未来标签前只叫运营校准，
   不能自称预测变准。
6. **异常什么时候结束说清楚。** 波动回落、深度/Delta/OTM 失格、离开模型范围、合约
   退市、输入缺失或无效、数值边界解不开、断线和人工停止各有不同结束原因；任何结束都
   立即停止 combo 检查。相邻期限桶边界只在时钟不确定期间暂停，行情连续时才允许恢复
   同一个 episode。
7. **异常与 combo 分开。** 没有 combo、combo 没深度或 combo 数据未知，都不会抹掉已知
   异常；按官方腿方向决定买卖 combo 并换算正信用，两腿拼价不会冒充 atomic quote。
8. **“没有”必须真的看全。** 少看一只潜在期权或一个相关 combo 只能报 `UNKNOWN`；看到
   一个可用原子报价可以报存在，但不能自称全市场最优。
9. **没有等市场赐予稀有事件才算代码完成。** 同一完整范围内走完全公式链后得到的已知
   `NO_ANOMALY` 可以证明实时链路能工作；由深度、OTM 或 Delta 已知失格短路得到的
   `NO_ANOMALY` 仍然真实，但不能单独验收全公式链。自然异常和原子报价另报
   `NOT_OBSERVED`，不为了验收调松阈值。
10. **没有提前造后半场。** 本闭环没有 replay、离线重算、provenance、maker、账户、
   Candidate、Outcome、数据库或自动调参。

## Artifacts and delivery report

Record the exact Policy path/digest, base/head, code commit, live command, observation interval,
coverage partition, detector and atomic counts, `UNKNOWN` reasons, any anomaly/atomic event paths,
and Git/remote state.

Report every zero, unavailable scope and non-claim. Do not infer forecast quality, complete-market
selection, fill, edge, profitability, qualification, future closeability, execution permission,
or stage advancement.

## Definition of done

The implementation is ready only when direct tests and `make check` pass. `REACHABILITY_SMOKE`
requires every accepted smoke invariant, including
`complete_aggregate_with_full_formula_evaluation_count >= 1` and a balanced coverage partition; a
covered zero-anomaly result is valid only when the joint full-formula witness also exists.
Production establishment additionally requires the separately approved and implemented
`OPERATIONAL_SOAK` contract above.

Business acceptance still requires an explicit human decision. Until then this task remains
incomplete, production Radar remains `NOT_ESTABLISHED`, no later closure is authorized, and the
prepared candidate successor Policy grants no live command or Soak authority.
