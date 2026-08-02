# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Current implementation state:** `ESTABLISHED` — exact bounded production-public runtime
capability accepted

**Owning implemented capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`

## Purpose

Establish the smallest honest production-public Radar for Deribit BTC-USDC options with
`0 < TTE <= 72 hours`.

This contract asks whether target-size executable sell-side IV is unusually rich under one exact
causal baseline. While that anomaly is active, it separately asks whether an existing official
atomic combo book exposes the target same-expiry 1:1 protective credit vertical.

It does not decide whether to trade, estimate account economics, place a maker order, prove a
fill, collect future Outcome, or validate forecast quality.

## Business terms

- **Market Monitor:** continuously maintained public current state plus the bounded causal index
  history used by the active Policy.
- **Detector evaluation:** one calculation from usable facts after a consumed economic fact or
  declared time boundary changes.
- **Anomaly episode:** one short-leg activation, optionally paused only at an adjacent
  same-option-type Policy-band boundary, and ending at any explicit end reason defined below.
- **Public atomic availability:** the current official combo-book fact for an active anomaly.
- **Future maker/order state:** private-account behavior not represented by this closure.
- **Candidate:** a later Underwriting action, not a Radar output.
- **Shadow or executed Entry:** a later admission/fill fact, not a public quote.
- **Position `CLOSE`:** a later Policy action, not proof that an exit happened.
- **Shadow close opportunity:** a later strictly future executable public quote while action is
  `CLOSE`.
- **Actual exposure duration:** a future fill-to-flat interval.

The Radar never returns `CANDIDATE`, `WATCH`, `ABSTAIN`, `HOLD`, or `CLOSE`.

## Three-layer truth model

### Layer 1 — detector

For each applicable option instrument, `detector_state[instrument_name]` is exactly:

- `UNKNOWN`: a required detector fact is unavailable/invalid or a derived classification is
  numerically unresolved;
- `NO_ANOMALY`: detector facts are usable and the activation rule has not passed;
- `ANOMALY_ACTIVE`: activation persistence passed and clear has not completed.

The aggregate Radar state is derived without erasing per-instrument truth:

- any known active instrument makes aggregate state `ANOMALY_ACTIVE`;
- with no active instrument, complete catalog and complete known instrument states make it
  `NO_ANOMALY`;
- with no active instrument and any unresolved potentially eligible instrument, it is `UNKNOWN`.

An aggregate `NO_ANOMALY` is therefore a negative completeness claim. One active instrument is a
positive witness even if unrelated instruments are unavailable; aggregate coverage is then
`DEGRADED`, with explicit unknown-instrument reasons and no complete-universe claim.

Within one runtime, the exact aggregate scope key is
`Policy identity × expiry_timestamp × option_type`. A scope exists only when the reconciled
current catalog contains at least one real instrument in that expiry/type and the expiry is in a
detector band whose `option_rules` contains that option type. OTM, Delta, minimum amount, and
target bid depth are per-instrument evaluations, not reasons to erase an instrument from the
aggregate. An empty catalog set is
reported as `aggregate_applicability = NO_APPLICABLE_SCOPE`; no Layer 1 aggregate detector state
is evaluated, it does not produce a vacuous complete aggregate evaluation, and its rate
denominator is `null`.

### Layer 2 — existing official atomic quote

For each short-leg episode, when Layer 1 is not active,
`public_atomic_quote_state` is `NOT_EVALUATED`.

While Layer 1 is active, the state is exactly:

- `UNKNOWN`: required combo catalog, metadata, lifecycle, subscription, or book continuity is
  unavailable;
- `NO_ACTIVE_COMBO`: the complete known official catalog has no matching active combo;
- `NO_TARGET_SIZE_CREDIT_QUOTE`: matching combos are known but none exposes enough depth in the
  required order direction with positive normalized gross entry credit;
- `PUBLIC_ATOMIC_QUOTE_AVAILABLE`: at least one matching official combo does.

No Layer 2 result changes Layer 1. An anomaly with no combo is still a known anomaly. An empty or
insufficient continuous combo book is known unavailability, not `UNKNOWN`.

`NO_ACTIVE_COMBO` requires complete official combo-catalog and lifecycle coverage, complete
relevant option-leg metadata, and a known protective-leg universe. Missing protective-leg
metadata or an incomplete option catalog is `UNKNOWN`, never `NO_ACTIVE_COMBO`.
`NO_TARGET_SIZE_CREDIT_QUOTE` additionally requires every matching active combo book to be usable
or known insufficient. One `PUBLIC_ATOMIC_QUOTE_AVAILABLE` witness is enough for a positive
availability claim, but it does not claim the best quote or complete-market selection.

Protective-wing applicability is exactly:

```text
KNOWN_PRESENT
KNOWN_ABSENT
UNRESOLVED
```

`KNOWN_PRESENT` means complete relevant option catalog/lifecycle/metadata proves at least one
farther-OTM same-expiry/same-type long wing. `KNOWN_ABSENT` means the same complete scope proves
none exists and is a known negative `NO_ACTIVE_COMBO` result. `UNRESOLVED` means any required
catalog, lifecycle, or leg metadata is incomplete and forces Layer 2 `UNKNOWN`.

### Layer 3 — future execution

Combo creation, RFQ, post-only maker placement, cancel/reprice, order acknowledgement, partial
fill, full fill, fees, margin, and account state require private authority. No current enum,
placeholder service, simulation, or artifact represents them.

Two component-leg orders are not an atomic substitute at any layer.

## Exact product and public sources

### Universe

- Deribit production public data only;
- active BTC-USDC linear options discovered through official metadata;
- trusted `0 < TTE <= 72 hours`;
- calls and puts remain separate;
- Policy TTE bands use explicit non-overlapping `(lower, upper]` boundaries and have separate
  evaluation denominators.

Instrument display labels do not define membership. Actual expiry timestamps and trusted Deribit
time do.

### Source namespace

- bootstrap options with `public/get_instruments` in currency namespace `USDC`, then require
  official BTC base, linear USDC option, and BTC-USDC index/product metadata;
- follow `instrument.state.option.USDC` and fetch metadata before admitting a new instrument;
- bootstrap combos with `public/get_combos` for `USDC`, then accept only official legs that map to
  the in-scope BTC-USDC options; fetch each admitted combo's official instrument metadata before
  using its amount constraints or book;
- follow `instrument.state.option_combo.USDC`;
- acknowledge and buffer public `platform_state` and
  `platform_state.public_methods_state`, call `public/status` to bootstrap current BTC/index lock
  state and prove that a public method succeeds, then reconcile the buffered notifications before
  treating platform state as usable;
- bootstrap and periodically refresh public Deribit time with `public/get_time`;
- consume index ticks only from `deribit_price_index.btc_usdc`;
- consume option forward facts only from `ticker.<instrument_name>.100ms`, and option/active-combo
  depth only from `book.<instrument_name>.100ms`;
- send dynamic subscriptions in bounded batches within the exchange limit and validate every
  acknowledgement.

Catalog establishment uses one race-free sequence for options and combos: acknowledge the
lifecycle subscription, buffer its events, fetch the bootstrap catalog, then reconcile buffered
events in causal order before declaring catalog completeness. Until reconciliation finishes,
negative aggregate or no-combo claims are `UNKNOWN`.

Every `instrument.state.option.USDC` notification first passes the shared protocol-shape check for
a non-empty `instrument_name` and `state`. The reducer then proves that the target identity starts
with `BTC_USDC-` before any catalog, membership, current-result, coverage, witness, or RPC side
effect. Shape-valid ETH, XRP, and other USDC option lifecycle facts remain counted protocol facts
only; they never schedule metadata or enter the BTC-USDC business catalog.

Combo lifecycle notifications only mark the current combo-catalog generation dirty. While one
authoritative `public/get_combos` refresh is pending, any burst is coalesced. Its response commits
only if its epoch/generation/origin boundary is current; if dirty, the reducer emits exactly one
trailing authoritative refresh for the latest generation. The burst never produces one refresh
per notification.

Platform state is reducer-owned as six independent facts:

```text
lock_snapshot
maintenance_guard
public_method_guard
post_status_probe
fresh_index_coverage
bootstrap_epoch
```

`usable` is a pure derived predicate and is never assigned. Platform startup does not default an
unobserved `maintenance = false`. It remains unusable until:

1. buffered platform subscriptions are acknowledged;
2. `public/status` succeeds and its official lock fields prove that neither all currencies nor the
   consumed BTC index are locked;
3. the time/catalog requests and subscriptions succeed after that status boundary; and
4. fresh index coverage is established.

That is the global platform boundary, not a global all-option barrier. Each current option's own
initial ticker and book snapshot gates only that detector. A missing or invalid per-instrument
fact required by the evaluation gate actually reached makes that instrument `UNKNOWN`; it does
not overwrite an earlier terminal known-ineligibility result or suppress a causally known active
witness in another instrument, which is reported through the completeness-aware aggregate state.

An option ticker notification is a complete snapshot. It has no `change_id`, `prev_change_id`, or
other sequence-continuity contract. The reducer validates its consumed shape, classifies the
candidate's currentness, and then records one application disposition as three separate facts:

```text
shape = VALID | INVALID
candidate currentness =
  CURRENT | SOURCE_STALE | TIMESTAMP_AHEAD | TRUSTED_TIME_UNKNOWN
application disposition =
  APPLIED | LATE_IGNORED | AHEAD_IGNORED | STALE_GENERATION_IGNORED | SHAPE_REJECTED
```

`ingress_seq`, not source timestamp, orders applications inside one session epoch. A shape-valid
snapshot with source timestamp lower than the currently accepted ticker is `LATE_IGNORED`. It
does not overwrite the newer accepted fact, request resubscription, end or clear an episode,
or restart `global_continuity_epoch` by virtue of the rejected candidate. Its receive boundary
still enters the sole reducer transaction and settles the already accepted ticker's currentness;
if that independent fact crosses TTL at the same boundary, detector/coverage/Layer 2 truth changes
under a concurrent `TICKER_SOURCE_STALE` effect while the received trigger remains
`LATE_IGNORED`. Equal timestamps are ordered by `ingress_seq` and the later ingress may apply. A
malformed snapshot is `SHAPE_REJECTED`; an ahead-of-trusted-time candidate is `AHEAD_IGNORED`.
Neither overwrites a still-current accepted ticker or manufactures a continuity gap.

When no trusted-time interval exists at receipt, candidate currentness is
`TRUSTED_TIME_UNKNOWN`, never `CURRENT`. The complete snapshot may still be applied in ingress
order, but it cannot make detector truth current; the accepted fact is classified against trusted
time when that dependency recovers.

After accepted-ticker TTL loss has latched one failed subscription generation, a candidate from
that same generation is `STALE_GENERATION_IGNORED` even if its timestamp is later. It cannot
recover or overwrite the latched fact; it is not counted as timestamp regression.

The currently accepted option ticker is usable exactly while
`ticker.source_timestamp_ms <= trusted_time.upper_ms <= ticker.source_timestamp_ms +
ticker_source_stale_deadline_ms`; equality at either boundary remains current. Only the accepted
fact crossing that upper TTL cutoff latches its ticker generation `SOURCE_STALE`, makes the
smallest dependent option truth unavailable, and requests exactly one resubscription for that
failed generation. A later clock refresh or narrower trusted-time interval cannot resurrect that
generation. Recovery requires a newly acknowledged ticker generation and an applied ticker whose
source timestamp is strictly later than the latched accepted fact.

At the forward gate, a missing accepted ticker or genuinely stale accepted ticker makes that
option `UNKNOWN`; an active episode ends `UNKNOWN_AT_GAP` and Layer 2 stops. This is
option-local availability loss, not global continuity loss. A known amount/off-grid failure or
insufficient target bid depth that terminates evaluation before the forward gate retains its
earlier `KNOWN_INELIGIBLE` result. Heartbeat, book, index, metadata, a rejected candidate, and
unchanged elapsed-time facts cannot refresh the accepted ticker. A recovered ticker with the same
numeric forward and only a newer source timestamp restores current truth but is not a countable
activation/clear observation. A change only between valid `underlying_index` labels with the same
numeric forward is likewise not countable.

`platform_state.public_methods_state.allow_unauthenticated_public_requests = false`, a relevant
lock, or a maintenance/break notification latches the corresponding guard negative for that
bootstrap epoch and invalidates dependent state immediately. A later `true`, unlock, or
maintenance-end notification cannot overwrite that negative guard in the same epoch. Only a new
bootstrap epoch with a fresh status snapshot, post-status probe, subscriptions, catalogs, clock,
and index coverage can restore derived usability.

No private, account, RFQ, combo-creation, order, trade, fill, maker, or test-environment method is
permitted. The only allowed `public/test` call is the protocol-required response to a
`test_request` on the already established production-public heartbeat; it cannot be initiated as
a market/business probe.

External responses may add unrelated fields. Only missing, invalid, or semantically changed fields
actually consumed by this contract fail closed at their smallest consumer.

The WebSocket enables `public/set_heartbeat` at the exact interval supplied by the frozen
versioned external Policy and acknowledges it before market state can become usable. This is
transport safety, not a trading threshold or an optimality claim. The consumed official result
shapes are
`public/set_heartbeat -> "ok"` and `public/test -> {"version": <non-empty string>, ...}`. Every
`test_request` is answered with `public/test`. Exceeding the Policy's session-liveness deadline, a
failed heartbeat/test response, or a connection close invalidates every
connection-dependent consumer and ends affected active episodes as `UNKNOWN_AT_GAP`. Reconnect
requires fresh subscriptions, snapshots, catalog reconciliation, and baseline coverage.
Heartbeat traffic proves only transport liveness: it never refreshes a book's economic timestamp,
creates a detector observation, or bridges a market-data sequence gap.

The transport owns one application-sequence allocator per session epoch. Every decoded inbound
frame—notification, RPC success/error/acknowledgement, heartbeat response, or late response—and
every immutable `SEND_COMPLETED`, `SEND_FAILED`, or connection-failure control consumes one unique
consecutive application identity. That identity is persisted as `session_epoch + ingress_seq`;
`received_monotonic_ms` freezes its local boundary. Allocation advances only after the bounded
inbound queue accepts the event. The reducer accepts exactly `last + 1` for every event kind and
advances its frontier once; a duplicate or gap fails the epoch closed. FIFO position without this
identity is not a fact lifecycle.

The socket reader never resolves a response future that applies economic state, never owns active
subscription generation, and never has a second notification queue. The sender likewise never
mutates the reducer or owns session termination: expected send completion, failure, and
cancellation are facts that must return through the same application queue. Only decoded socket
frames update the wire-liveness timestamp. Local send or connection controls never refresh
session liveness, economic currentness, a book timestamp, or a detector observation.

One synchronous reducer exclusively owns session, channel, platform, catalog, market, detector,
episode, coverage, and Layer 2 state. No function reachable from that reducer waits for network
I/O. It returns a finite tuple of `PendingRpc`; the orchestrator sends those commands and feeds
their success/error/acknowledgement envelopes back through the same queue. Heartbeat
`test_request` may enqueue a guarded `public/test` command while catalog work is pending, but
neither it nor its response mutates economic truth.

Each `PendingRpc` freezes:

- request id and one finite request purpose;
- method and exact consumed params;
- session epoch;
- scope kind/id and channel generation when applicable;
- origin `FactBoundary`;
- absolute monotonic send deadline derived from the scheduling boundary and frozen external
  Policy; a separate response deadline exists only after `SENT`;
- one failure scope from
  `SESSION | CLOCK_INDEX | OPTION | OPTION_CATALOG | COMBO_LAYER | FATAL_PROTOCOL`.

A response with the wrong epoch, unknown/retired request id, retired generation, or expired
deadline is a reduced late response with zero business side effects. The exact RPC transitions
are:

```text
SCHEDULED -> SENT | ERROR | DEADLINE_LATE | RETIRED | CENSORED
SENT      -> SUCCESS | ERROR | DEADLINE_LATE | RETIRED | CENSORED
```

Only completed transport send creates the immutable `SENT` boundary. It starts the response
deadline and latency clock. A terminal transition is idempotent and cannot be rewritten by a
later control, deadline, cancellation, or response. A response received before its send receipt
is retained until the reducer settles that receipt; if no legal `SENT` transition follows, it is
retained as `ORPHAN_LATE_WIRE`.

Reconnect first retires every pending request and channel generation in that session epoch
exactly once. The failure barrier then stops producers and reduces every event already accepted by
the transport or held in the runtime buffer as a retired/orphan application fact before failure
propagation.

Clean stop has a distinct barrier: reject further outbound work, stop producers, settle in-flight
cancellation controls, drain every accepted application event, then censor remaining
`SCHEDULED` and `SENT` requests and project the summary. No queued request may begin transport
send after this barrier opens. A cancellation settled after its send deadline remains
`DEADLINE_LATE`; clean stop cannot rewrite an earlier terminal fact.

Reducer-owned channel state is exactly:

```text
UNSUBSCRIBED
SUBSCRIBE_PENDING
ACKNOWLEDGED
UNSUBSCRIBE_PENDING
RETIRED
```

Frames received before a successful subscribe acknowledgement are buffered only for that exact
epoch/generation and cannot alter market truth. A successful acknowledgement reconciles them once
in ingress order. Frames for `UNSUBSCRIBE_PENDING` or `RETIRED` generations have zero business
side effects. Membership/coverage changes occur at the originating fact boundary before the
unsubscribe command is emitted.

Bootstrap and steady state use the same Policy-supplied receive-lag deadline and update the same
queue diagnostics. A unique, consecutive application event whose receive-to-reduce lag exceeds
that deadline is an ordered queue-currentness incident, not evidence of ingress loss or socket
loss. The event is still reduced exactly once in order. Entry is one reducer edge: that delayed
event's immutable receive boundary rebuilds every current detector scope once, makes detector,
aggregate, atomic, witness eligibility, and coverage fail closed, records
`blocking_reason = QUEUE_LAG_CURRENTNESS`, and counts no observation. While lag remains above the
deadline, each later consecutive event settles only its frozen causally affected scope against
the already committed incident truth; it remains non-countable and may not repeat a full-market
rebuild. The first later consecutive within-deadline application boundary is the recovery edge;
after every earlier accepted event has been reduced, it rebuilds every current scope exactly once
before observation can resume. The incident does not retire the session, reconnect, increment
`global_continuity_epoch`, erase the existing witness, or rewrite that witness as if it occurred
after local recovery. Queue overflow, an application-sequence gap/duplicate, or real
socket/session loss remains a session gap. No operational deadline or cadence has an
implementation default.

## Time and settlement boundary

The Monitor advances last accepted Deribit server time with local monotonic elapsed time and
carries an explicit uncertainty interval. A TTE band is usable only when that entire interval
falls inside the same band. One pure classification is shared by detector, aggregate, coverage,
and membership: `IN_BAND | ADJACENT_BAND_BOUNDARY | POLICY_GAP | FINAL_WINDOW |
MONITOR_BOUNDARY | OUT_OF_MONITOR_SCOPE`. `ADJACENT_BAND_BOUNDARY` and `MONITOR_BOUNDARY`
remain unresolved for coverage; a known Policy gap or final window is known absent scope.
Membership changes split coverage at one causal/monotonic boundary before any subscribe or
unsubscribe await.

Every accepted market-fact transaction obtains trusted time and seals every index minute ready at
that same boundary before reading any index tail or classifying current detector truth. This order
also applies when the trusted-time watermark crosses a minute on a ticker, book, lifecycle,
catalog, combo, or other non-index fact. A ready-but-unsealed minute is pending work in the same
transaction, never evidence of `WINDOW_GAP`, and cannot restart global continuity.

For each `public/get_time` request, record local monotonic send/receive instants and the returned
integer server millisecond. At receipt, its 1 ms quantization and request round trip establish
`base = [returned_ms, returned_ms + 1 ms + round_trip_ms]`. With local monotonic elapsed `e_ms`,
the current interval is
`[base.lower + e_ms × (1 - 1000/1_000_000),
base.upper + e_ms × (1 + 1000/1_000_000)]`; 1000 ppm is a fixed conservative operational drift
budget, not Policy. All clock math uses integer/rational milliseconds: round the lower bound toward
negative infinity and the upper bound toward positive infinity; binary float may not narrow the
interval. Refresh and stale deadlines come only from `runtime_limits`. If
two successive intervals are available, first advance the prior interval to the new receive
instant. Their non-empty intersection becomes the new base interval; an empty intersection is a
clock gap. This prevents the trusted lower bound from moving backward and forbids choosing
replace versus union ad hoc. A clock gap makes dependent consumers `UNKNOWN` and ends active
episodes `UNKNOWN_AT_GAP`. Heartbeat timestamps, wall-clock time, and option display names cannot
substitute for this clock.

Every required subscription is acknowledged and must deliver its own initial usable
notification/snapshot. A reconnect invalidates all of them. Except for status, time, catalog, and
new-member metadata bootstrap, the runtime does not REST-poll market facts or substitute another
index/ticker interval.

Deribit BTC-USDC linear-option delivery price is formed during the final 30 minutes before
delivery. The initial baseline therefore sets
`detector_applicability = OUT_OF_BASELINE_SCOPE` once that window begins. This is a known detector
limitation, not `UNKNOWN`; the Monitor still observes the instrument, but does not evaluate a
Layer 1 `detector_state` for it or include it in the detector denominator.

A future final-window detector must explicitly model the partially formed delivery TWAP and
estimated delivery price. Ordinary remaining-life variance scaling cannot silently cover it.

## Order-book and known-at semantics

Each accepted fact receives a local monotonic `causal_seq`. Different channels do not share one
exchange-global sequence. “Strict as-of” means the latest individually continuous facts known to
this process at one `causal_seq`; it does not claim a simultaneous exchange snapshot.

When one fact affects multiple instruments in the same
`Policy identity × expiry_timestamp × option_type` scope, the runtime evaluates every affected
instrument first and then settles one full current-scope snapshot exactly once from that causal
pass. Unaffected members contribute only their still-current settled results; the reducer may not
replace the full current scope with the affected subset or publish transient partial truth
produced by iteration order.

An order book becomes usable only after:

1. its subscription is acknowledged;
2. a complete snapshot is accepted;
3. every later change satisfies exact `prev_change_id -> change_id` continuity;
4. connection, platform, and instrument state remain usable;
5. its levels remain valid and uncrossed.

A continuously maintained book does not become stale merely because no level changed. The last
mutation timestamp is a diagnostic, not a freshness timeout, and the runtime does not resubscribe
to manufacture a newer timestamp.

A gap, reconnect, missing snapshot, lifecycle loss, or invalid book makes only dependent consumers
`UNKNOWN` until resnapshot. A complete book with an empty required side or inadequate cumulative
depth is a known liquidity-ineligible `NO_ANOMALY` for that instrument; it short-circuits before
ticker/forward/IV inputs are required. If target-size bid depth exists, missing downstream pricing
facts are `UNKNOWN`.

## Policy contract

### Formula family

The only initially authorized detector family is
`POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE`.

One exact content-identified Policy file has `policy_schema_version = 3` and supplies:

- `target_base_quantity_btc`;
- one exact `runtime_limits` object containing:
  - `heartbeat_interval_seconds`;
  - `session_liveness_deadline_ms`;
  - `rpc_deadline_ms`;
  - `clock_refresh_interval_ms`;
  - `clock_stale_deadline_ms`;
  - `index_source_stale_deadline_ms`;
  - `ticker_source_stale_deadline_ms`;
  - `notification_queue_lag_deadline_ms`;
  - `time_boundary_poll_interval_ms`;
- one non-empty list of exact TTE bands, where each band owns:
  - trailing one-minute return lookbacks and non-negative weights;
  - a positive annualized-variance floor, converted to the reducer's per-minute unit before use;
  - a non-empty `option_rules` map keyed only by `call` and/or `put`;
- for each band/option rule:
  - absolute-Delta boundaries;
  - activation and clear IV-richness ratios;
  - activation and clear observation counts;
  - minimum trusted-market-time separation.

A call or put omitted from a band is explicitly out of detector scope in that band. Calls and puts
present in the same band may have different detector rules, but consume exactly the same
underlying return baseline for that band.

Load-time validation requires:

- exact repository-owned object keys at every nesting level (`additionalProperties = false`);
- exactly `policy_schema_version = 3`;
- every runtime-limit field to be a positive integer, with
  `time_boundary_poll_interval_ms <= 1000`,
  `time_boundary_poll_interval_ms <= ticker_source_stale_deadline_ms`,
  `rpc_deadline_ms >= time_boundary_poll_interval_ms`,
  `session_liveness_deadline_ms > heartbeat_interval_seconds × 1000`, and
  `clock_stale_deadline_ms > clock_refresh_interval_ms`;
- at least one TTE band and a non-empty supported `option_rules` map in every band;
- at least one unique positive-integer lookback and one aligned finite non-negative weight per
  lookback, with weights summing exactly to one after canonical decimal parsing;
- non-overlapping TTE bands contained in `(30 minutes, 72 hours]`; any deliberate gap is explicit
  `OUT_OF_BASELINE_SCOPE`;
- `0 <= abs_delta_min < abs_delta_max <= 1`;
- finite `target_base_quantity_btc > 0`;

Reconnect backoff uses `time_boundary_poll_interval_ms` as its initial bound and
`rpc_deadline_ms` as its maximum bound; it has no separate implementation cadence.
WebSocket open and close also use `rpc_deadline_ms`; the transport has no hidden connection
deadline.
- finite annualized variance floor `> 0`;
- finite `activation_ratio > 1` and `0 < clear_ratio < activation_ratio`;
- positive-integer activation/clear counts and finite minimum separation `>= 0`.

Quantity is expressed in BTC underlying units. The adapter validates official contract size,
minimum trade amount, and the API's declared `amount` unit before mapping that quantity to an
option or combo order-book amount. This closure does not consume a separate `quantity` field and
does not infer any relationship from it. This BTC-USDC contract requires official
`contract_size = 1` and option/combo `amount` in BTC; a source-contract change fails closed rather
than activating a generic multiplier framework. The exact derived order amount must be at least
`min_trade_amount`. When the optional official `qty_tick_size` field is present, it must be
positive and the amount must be its integer multiple. A known undersized or published-grid
misaligned target is target-size liquidity ineligibility; it is never rounded. Absence of the
optional field is not `UNKNOWN` and does not authorize inferring a grid from an undocumented
field. Missing or invalid required amount metadata, or an invalid present `qty_tick_size`, is
`UNKNOWN` unless another independent gate is already known to fail.

Numeric values, including operational deadlines, are configuration, not universal trading truth.
Operational limits are safety/calibration candidates, not scientifically optimal values. The
implementation has no fallback constants and tests at least two materially different Policy
fixtures so code constants cannot masquerade as Policy.
Construction establishes the schema and loader, not a preferred live parameter set. A later human
production-observation command, or an active bounded terminal-goal delegation, names and
pre-binds the exact external Policy path and digest.

The Policy format is UTF-8 JSON without a BOM, with one top-level object, duplicate keys rejected,
and non-finite numbers rejected. Before any network subscription, startup reads its exact bytes
once, computes `sha256:<hex>` over those bytes, and requires equality with the human-approved or
terminal-goal-pre-bound expected digest supplied to the command. JSON numeric tokens parse
directly to `Decimal`. It then
uses only the immutable parsed in-memory object; a missing/mismatched digest or a later file
mutation cannot change the running Policy.

### One run, one immutable identity

The process binds the verified exact-byte Policy digest before subscribing. Every event and run
summary records that identity. Hot reload, in-run mutation, automatic training, automatic
selection, and automatic deployment are rejected.

After reviewing a forward interval, a human or an active terminal-goal delegate may pre-bind a
successor inside this same Policy schema when the delegation expressly permits Policy
calibration. It may change target quantity, TTE bands/gaps and call/put inclusion,
lookbacks/weights/floor, Delta boundaries, activation/clear ratios and counts, or separation. It
receives a new identity, process, and forward interval. Earlier events keep their original meaning
and are never backfilled or relabeled.

Changing the formula, source family, structure family, or claimed evaluation target requires a new
task and owning-contract amendment.

### What current calibration can and cannot do

This closure may compare across Policy intervals:

- covered and `UNKNOWN` time;
- usable evaluation frequency;
- anomaly frequency by call/put and TTE band;
- activation/clear flicker and episode duration;
- official combo availability conditional on active anomaly.

It has no strictly future realized-volatility label, settlement Outcome, executable trade Outcome,
or cohort comparator. It therefore cannot call one Policy a better forecast, edge, or strategy.
Those claims require a later authorized forward evaluation contract.

The first explicitly registered production-observation Policy may be intentionally broad for
operational coverage/frequency/flicker discovery, while still satisfying every load invariant,
including `activation_ratio > 1`. Each later Policy successor is reviewed and observed only on a
new forward interval. Improving the estimator itself requires a later contract that first declares
an exact horizon-matched future volatility or settlement label and comparator; it is not smuggled
into Radar construction as automatic tuning or backtest infrastructure.

## Causal trailing-index-variance baseline

### Index-minute reducer

The source adapter validates official notification field `data.timestamp` as integer milliseconds
and maps it to internal `source_timestamp_ms`. Assign each accepted
`deribit_price_index.btc_usdc` tick to `floor(source_timestamp_ms / 60_000)`. Timestamps must be
non-decreasing on the continuous subscription; equal timestamps are ordered by local
`causal_seq`. A UTC minute is fully covered only when the subscription was healthy for its
complete half-open interval, it contains at least one accepted tick, trusted-time lower bound is
at or beyond minute end, and the accepted index timestamp watermark is also at or beyond minute
end. Its close is the last causal tick assigned to that minute. This does not require a tick
within an arbitrary number of milliseconds of the boundary.

A timestamp regression or a tick assigned to an already sealed minute is an index continuity gap:
sealed closes are never rewritten, rolling returns are invalidated, and warm-up restarts from new
continuous coverage.

Index baseline truth has two orthogonal axes. Per-return-count availability is exactly:

```text
AVAILABLE
WARMUP
WINDOW_GAP
SOURCE_STALE
CONTINUITY_GAP
```

Generation-global publication phase is exactly:

```text
CURRENT
TIME_BOUNDARY_PENDING
WATERMARK_PENDING
```

A newly started generation with no proven history is bootstrap `WARMUP`, not `CONTINUITY_GAP`.

`IndexTailStatus` and `IndexBaselineState.status` remain current production Python projections.
When a requested baseline is unavailable, `status` projects its per-return-count availability;
when it is available, `status` projects `AVAILABLE | TIME_BOUNDARY_PENDING |
WATERMARK_PENDING` from the independent publication phase. This compatibility projection does not
make publication pending a coverage blocker or collapse the two normative axes.

By contrast, `INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility name. It is
not serialized and the current reader does not consume it. Current coverage rejects
`INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING` as blockers; publication pending lives
only in `index_baseline_publication`. The current contract does not require a Python tracker,
disposition, or other runtime state named `INDEX_TAIL_PENDING`. For one accepted index generation
and global continuity epoch, the
publication tracker is inactive until trusted clock, accepted watermark, and at least one
immutable published close exist. Thereafter it observes only the immediate successor:
`published = tail.last_start`, `target = published + 60_000`, and
`target_end = target + 60_000`.

```text
proven_end_ms = floor(min(trusted_time.lower_ms, accepted_watermark_ms) / 60_000) * 60_000
expected_latest_close_start_ms = proven_end_ms - 60_000
```

Expected time is not an actual close. Actual publication changes only after one exact continuous
suffix ending at `expected_latest_close_start_ms` passes generation, global-continuity epoch,
coverage-start, 60-second alignment, and terminal-minute checks. The frozen published object owns
its generation, epoch, complete immutable `MinuteClose` tuple, published end and last start, first
publish `FactBoundary`, and proof lower/watermark audit values. Proof audit values do not change
later and do not enter economic observation identity.

Each band independently projects an exact `N + 1` close tuple from the same sealed generation
history for `N` returns. The tuple must end at the actual published last minute, exclude every
close after the proven cutoff, and be 60-second consecutive. `coverage_start > earliest_required`
is `WARMUP`; once proof and coverage require a minute, any missing, misaligned, or nonconsecutive
close is `WINDOW_GAP`. A shorter band may be `AVAILABLE` while a longer band is `WARMUP` or
`WINDOW_GAP`.

Publication phase is relative to the immediate successor:

- `CURRENT`: no pending row;
- `TIME_BOUNDARY_PENDING`: `trusted.lower < target_end <= trusted.upper`;
- `WATERMARK_PENDING`: `trusted.lower >= target_end` and accepted watermark `< target_end`;
- phase is a same-tail/same-target latch after it starts. A later clock refresh may tighten
  `trusted.upper` back below `target_end`, but it cannot erase the already observed
  `TIME_BOUNDARY_PENDING` interval; that phase remains until the successor is jointly proven,
  changes to `WATERMARK_PENDING`, currentness is lost, or the run stops;
- if trusted lower and watermark both prove the successor in one boundary, publish immediately
  without a zero-duration pending row;
- `PHASE_CHANGED` is only same-tail/same-target/same-epoch
  `TIME_BOUNDARY_PENDING -> WATERMARK_PENDING`;
- if a different full `FactBoundary` in the same integer monotonic millisecond immediately
  publishes, invalidates, or clean-stops the zero-duration watermark phase, the ledger atomically
  folds that terminal disposition into the preceding positive-duration time row, cancels the
  watermark start, and cancels the intermediate `PHASE_CHANGED` end. It never emits a zero-duration
  row or leaves an orphan phase chain;
- a successor seal ends a pending row as `PUBLISHED`; if the newly published tail's next successor
  is already pending in the same boundary, close the old row first and open the new row;
- trusted lower never moves backward, so one target cannot move from watermark pending to time
  pending. A later target may begin a new time-pending row.

Normal publication pending keeps the previously published exact tuple available. It does not
resubscribe, restart continuity, make detector truth unknown, pause or end an episode, stop Layer
2, pause known-active duration, increment persistence, or reset persistence. Phase, timers,
watermark target, and proof audit metadata are excluded from detector observation identity. A
published tuple identity may change once when the immutable consumed closes change. Generation
and global-continuity epoch own and prove the tuple but are publication provenance, not economic
de-duplication identity. The new tuple identity is observed at most once only when the owning
boundary was already countable; a clock/time-only publish is current truth only, and a later
unchanged fact cannot backfill an observation. Multiple simultaneously proven minutes publish only
the latest exact window and do not replay intermediate observations.

Availability behavior is normative:

| Availability | Detector / episode / Layer 2 / coverage | Resubscribe and continuity |
|---|---|---|
| `AVAILABLE` | calculate from the exact `N + 1` published tuple; normal pending leaves all current truth unchanged | no |
| `WARMUP` | affected detector `UNKNOWN/INDEX_WARMUP`; an active episode ends `UNKNOWN_DETECTOR`; Layer 2 stops; only that query is unavailable | no resubscribe and no gap count |
| `WINDOW_GAP` | only bands whose exact requested window contains the gap become `UNKNOWN/INDEX_WINDOW_GAP`; affected active episodes end `UNKNOWN_AT_GAP` | restart `global_continuity_epoch`; do not resubscribe; publication rows cannot cross the epoch and are rebound only from proven sealed history |
| `SOURCE_STALE` | every index consumer becomes `UNKNOWN/INDEX_SOURCE_STALE`; active episodes end `UNKNOWN_AT_GAP`; reusable publication is lost | restart owning continuity if no incident is active; always resubscribe the index channel |
| `CONTINUITY_GAP` | every index consumer becomes `UNKNOWN/INDEX_CONTINUITY_GAP`; clear sealed history and restart warm-up | restart owning continuity if no incident is active; always resubscribe the index channel |

Timestamp regression, a late tick targeting a sealed minute, or explicit index-channel continuity
failure is `CONTINUITY_GAP`. A retired epoch/generation establishes continuity loss at retirement;
subsequent retired frames have zero business effect. `WINDOW_GAP` is only a proven missing or
nonconsecutive requested minute and never resubscribes. Publication invalidation is independent
from continuity-incident de-duplication: every session/clock/index invalidating fact closes an
active pending row exactly once and invalidates the published tuple, even when an earlier
`WINDOW_GAP` already owns the sole epoch restart. That later fact changes the current blocker but
does not fabricate a second restart before recovery.

### Baseline projection

For one Policy baseline entry keyed by TTE band, define one-minute log returns `r`. The index
variance baseline is shared by calls and puts in the same TTE band; option type may change
eligibility or detector boundaries, but it cannot create a different history of the underlying.
For each configured lookback `h`:

```text
window_variance(h, t) = mean(r² over the last h covered returns)
baseline_variance_rate(t) =
    max(converted_per_minute_floor, Σ weight(h) × window_variance(h, t))
remaining_life_minutes_interval =
    [(expiry_ms - trusted_time_upper_ms) / 60_000,
     (expiry_ms - trusted_time_lower_ms) / 60_000]
baseline_total_variance_interval =
    baseline_variance_rate(t) × remaining_life_minutes_interval
baseline_volatility =
    sqrt(baseline_variance_rate(t) × 365 × 24 × 60)
```

The baseline has one numerical oracle. Parse consumed numeric tokens and Policy numbers directly
to canonical `Decimal`; never through binary float. Use one repository-owned pure function with
`decimal.Context(prec=50, rounding=ROUND_HALF_EVEN)` and finite/overflow traps. In chronological
order calculate
`r_t = context.ln(close_t) - context.ln(close_t_minus_1)`, then square, sum, and divide by
`Decimal(h)`. Calculate windows and the weighted sum in ascending `h` order, convert annual
variance to per-minute variance by exact division by `365 × 24 × 60`, multiply by exact
remaining-life-minute interval bounds, and use the same context's square root/division for
baseline volatility and IV-richness bounds. Runtime and fixed-vector tests call this same
function. If the final
richness interval contains values on both sides of an activation/clear boundary, classification
is `UNKNOWN/NUMERICAL_BOUNDARY_UNRESOLVED`.

Weights are finite, non-negative, and sum to one. Every window is backward-looking and ends at or
before its bound `causal_seq`. Annualized and per-minute units use the same declared 365-day year
as the option time fraction.

This deliberately small estimator adapts recent realized variance to the exact remaining-life
horizon. It is an inspectable operational baseline—not a delivery-TWAP distribution forecast,
validated physical forecast, event-risk model, jump model, volatility-surface model, or
model-free variance risk premium.

### Executable sell-side IV

The live calculation fixes the official linear formula rather than making it a Policy choice:

```text
F = option ticker underlying_price
x = σ × sqrt(T)
d1 = (ln(F / K) + 0.5 × x²) / x
d2 = d1 - x
call_price = F × N(d1) - K × N(d2)
put_price  = K × N(-d2) - F × N(-d1)
call_delta = N(d1)
put_delta  = N(d1) - 1
```

`underlying_index` must identify the official forward basis expected for that option. `N` is the
standard normal CDF. Trusted time gives
`T_interval = [(expiry - time_upper), (expiry - time_lower)] / milliseconds_per_365_day_year`.
Required values are finite with `F > 0`, `K > 0`, `T_interval.lower > 0`, and `x > 0`.

For each in-scope catalog option, amount minimum/grid, target bid depth, and forward/OTM are
independent gates. Any available known failure is sufficient for per-instrument `NO_ANOMALY` even
if an unrelated gate is unavailable. Only when no gate is known to fail does a missing required
fact produce `UNKNOWN`. The full path is:

1. validate official amount metadata, including exact alignment when optional `qty_tick_size` is
   published, and inspect the complete bid book for target depth;
2. validate the option ticker's official forward `underlying_price` and apply fixed OTM before IV
   inversion (`K > F` for a call, `K < F` for a put);
3. only after minimum amount, target depth, and OTM all pass, walk visible bids through
   `target_base_quantity_btc` and calculate executable sell price in official units;
4. use the declared Deribit linear-option Black formula, strike, and forward to invert that price
   to a finite total-volatility `x` interval;
5. calculate Delta from `x` and apply the Policy's absolute-Delta boundaries; a known
   Delta failure is `NO_ANOMALY` without requiring a baseline;
6. calculate `implied_total_variance_interval = x_interval²`;
7. combine `x_interval` and `T_interval` conservatively:
   `executable_bid_IV_interval =
   [x_low / sqrt(T_high), x_high / sqrt(T_low)]`;
8. calculate `iv_richness_interval = executable_bid_IV_interval / baseline_volatility`.

An IV-richness ratio `r` means IV is `(r - 1) × 100%` above baseline volatility; its equivalent
total-variance ratio is `r²`. The implementation must never treat those percentages as
interchangeable.

If the bid cannot support the target quantity, the option is known liquidity-ineligible; it is
not a fake mid/mark observation. IV inversion has one canonical numerical oracle:

1. solve total volatility `x = σ × sqrt(T)`, not annualized `σ`, so tiny remaining life does not
   make the search coordinate ill-conditioned;
2. require the target price strictly inside the formula's finite domain (`0 < call_price < F` or
   `0 < put_price < K`); an out-of-domain positive quote is `UNKNOWN` with an explicit numerical
   reason;
3. use the locked Python binary64 primitives
   `N(z) = 0.5 × (1 + math.erf(z / math.sqrt(2)))`, `math.log`, and `math.sqrt`;
4. start with `x_low = 0` and `x_high = 1`, double `x_high` at most 32 times until the target is
   bracketed, otherwise return `UNKNOWN`;
5. perform at most 64 bisection updates; `model_price(mid) >= target_price` moves the upper bound,
   otherwise it moves the lower bound, and an unrepresentable midpoint stops with the two adjacent
   bounds;
6. retain the lower/midpoint/upper `x` values, convert each through its canonical round-trip
   decimal string, and combine the bounds with the trusted `T_interval` as specified above before
   any `Decimal` threshold comparison.

The one repository-owned pure function implements this algorithm and is used directly by the
runtime and its fixed-vector tests; no alternate solver may make detector decisions. Consumed
official prices and ticks remain recorded, but half-a-tick price residual is not a second decision
oracle. The final bracket defines the decision total-volatility interval. Delta eligibility and
activation/clear classification must have the same truth over the whole resulting interval.
Delta depends on `x`, not the choice of a point inside `T_interval`; its range evaluates both
`x` endpoints and the analytic `d1` stationary point when it lies inside. Richness uses the
conservative IV interval above. If either resulting interval contains values on both sides of a decision
boundary, the smallest dependent result is `UNKNOWN` with
`NUMERICAL_BOUNDARY_UNRESOLVED`. Tests pin solver vectors and the exact inclusive side of Delta,
activation, and clear boundaries. This deterministic mathematical inversion does not claim that
the market quote itself is more precise than its official tick.

All prices, amounts, and exact threshold comparisons use unit-bearing `Decimal` values. Model
functions require finite inputs and explicit time units.

OTM is exact at the executable-IV forward: call requires `K > F`, put requires `K < F`.
Absolute-Delta eligibility is inclusive:
`abs_delta_min <= abs(delta) <= abs_delta_max`.

One OTM point contains skew, jump, tail, supply/demand, and liquidity premium that this estimator
does not explain. The ratio is a detector input, not an edge estimate.

## Activation, clear, and gaps

Each `Policy identity × instrument_name` scope has one small activation/clear tracker.
An observed episode identity is
`runtime identity × Policy identity × instrument_name × activation_causal_seq`; TTE band is an
activation attribute, not identity. The current tracker states are:

```text
UNKNOWN
          a required detector fact is missing/invalid, or derived classification is numerically unresolved
ARMED     this instrument is usable and no episode is active
ACTIVE    this instrument has passed activation
CLEARING  this instrument's clear persistence is pending
BAND_SUSPENDED
          trusted time straddles a Policy boundary while market-source continuity remains known
```

The removed `INDEX_TAIL_PENDING` enum/disposition was Python-only compatibility surface, not a
serialized tracker field. The current reader does not recognize it. The current runtime never
enters an `INDEX_TAIL_PENDING` tracker state, and generation-global publication pending is
diagnostic only.

```text
activation observation: iv_richness_ratio >= activation_ratio
clear observation:      iv_richness_ratio <= clear_ratio
between the boundaries: preserve the instrument's current active/non-active state
```

Activation occurs only after the configured activation count, with consecutive trusted
observations separated by at least the configured market-time interval. An active episode clears
only after the configured clear count. The Policy requires `activation_ratio > 1` and
`0 < clear_ratio < activation_ratio`.

Separation uses the clock intervals, never a midpoint:

```text
later_observation.time_lower_bound
- prior_counted_observation.time_upper_bound
>= minimum_separation
```

Equality counts. A qualifying observation whose intervals overlap or leave a smaller guaranteed
gap neither increments nor resets the count.

“Consecutive” is exact: while non-active, any known observation below the activation boundary
resets pending activation; while active/clearing, any known observation above the clear boundary
resets pending clear and returns the tracker to `ACTIVE`. A qualifying observation that arrives
before the minimum separation neither increments nor resets the count, but any intervening known
non-qualifying observation resets it immediately. Equality uses the inclusive comparisons shown
above.

Every committed economic fact creates one non-durable `FactBoundary` with epoch/ingress/causal
identity and receive monotonic time, and explicitly supplies a finite set of affected
`Policy × expiry × option_type` scopes to settlement. The reducer first commits the fact, then builds one
short-lived `ScopeSnapshot` per affected scope, calculates every instrument's
`CurrentEvaluation`, applies all unconditional state effects, settles the aggregate/coverage/
Layer 2 once, and only then exposes that boundary's truth. Iteration order cannot expose a partial
aggregate.

`CurrentEvaluation` is separate from `observation_eligibility/reason`. Trusted-time revision can
change TTE/current classification, but it is not a countable persistence observation. Hard
`UNKNOWN`, known ineligibility, membership loss, and scope exit apply even when `countable =
false`. Normal index publication pending is not a suspension or detector state. Only a richness
evaluation with `countable = true` and a new consumed-fact identity calls the persistence
observation transition.

Observation identity contains only facts the formula consumes: target-quantity bid levels,
forward, the exact immutable published `MinuteClose` tuple used by the band, and discrete TTE
classification. Publication phase, timer, target successor, trusted-lower proof audit, and
watermark proof audit are excluded. Index generation and global-continuity epoch own and prove the
published tuple but are provenance, not detector de-duplication facts; the baseline component of
identity is only the exact selected immutable `MinuteClose` tuple. Identity change alone never
resets persistence. Duplicates, ask-only changes, depth beyond the target, heartbeats,
metadata-only changes, and unchanged reduced economic state do not activate, clear, or reset
persistence and do not create observations or episodes.

A trusted-time interval that straddles a boundary cannot select either parameter set. If the next
adjacent band also has an `option_rules` entry for this instrument's option type, detector output
is temporarily `UNKNOWN` with reason `TIME_BAND_BOUNDARY`; an already active episode becomes
`BAND_SUSPENDED`, its known-active duration pauses, Layer 2 becomes `NOT_EVALUATED`, and all
incomplete activation/clear counts reset. Once the full trusted-time interval lies inside that
adjacent same-option-type band, continuous market sources permit the same episode identity to
resume `ACTIVE` under the new band's parameters; this does not write a second anomaly event. A
non-active tracker resumes `ARMED`.

If the uncertainty interval stops lying wholly inside the current band and the other side is a
deliberate Policy gap, a band with no rule for this option type, or the final 30-minute window, an
active episode ends immediately at its last trusted active boundary with
`end_reason = OUT_OF_BASELINE_SCOPE`; Layer 2 becomes `NOT_EVALUATED`. It does not wait for the
clock interval to lie wholly outside and cannot resume that identity. Later entry into an enabled
same-option-type band requires fresh activation. A distinct episode is attributed to the band in
which it activated; per-band evaluation counts use the band active at each known evaluation. No
suspended interval is counted as known-active time.

Current normal index publication pending never enters the removed Python-only
`INDEX_TAIL_PENDING` compatibility state and never resets activation or clear counts. The
current reader rejects `INDEX_TIME_BOUNDARY_PENDING` and `INDEX_WATERMARK_PENDING` as coverage
blockers; publication timing is represented only by `index_baseline_publication`.
`WARMUP`, `WINDOW_GAP`, `SOURCE_STALE`, and `CONTINUITY_GAP` remain fail-closed exactly as the
availability table specifies.

A detector-dependent gap changes only the affected instrument to `UNKNOWN`, invalidates its
option/combo quotes, cancels pending observations, and never infers what happened inside the gap.
If an observed episode was active, it ends with `end_reason = UNKNOWN_AT_GAP`; its known-active
duration stops at the last trusted boundary.

An older complete ticker snapshot is not itself a detector-dependent gap. `LATE_IGNORED` has no
candidate-derived tracker, aggregate, coverage, Layer 2, resubscription, or witness effect, but
the same receive boundary must settle independent source TTL before any of those current results.
A rejected malformed or ahead candidate likewise cannot overwrite a still-current accepted
ticker. Only actual option-local unavailability—no accepted current ticker or the accepted ticker
crossing its TTL—can make the forward dependency unavailable.

After complete resync, the instrument must pass fresh activation persistence and receives a new
episode identity. It may reference the pre-gap episode as an uncertain predecessor, but neither
object claims continuity across the gap. Unaffected instruments retain their own states, so one
can keep the aggregate Radar active.

Failure domains are explicit: session; clock/index; one option channel; option catalog; combo
Layer 2; transient/rate-limit request; and fatal protocol incompatibility. Session gaps invalidate
the session; clock/index gaps rebuild their dependent baseline; one-option failures stay local;
option-catalog incompleteness blocks complete Layer 1 negatives; combo request/subscription/
resnapshot failures make only Layer 2 `UNKNOWN`; fatal consumed-shape incompatibility stops.
One root failure records one canonical `UNKNOWN` reason. Reconnect preserves runtime identity,
ends pre-gap episodes as `UNKNOWN_AT_GAP`, and fresh activation receives a new episode identity.

Other exits are explicit and immediate:

- target bid depth or official amount minimum/published grid becoming known ineligible, or a known
  OTM/Delta failure, produces per-instrument `NO_ANOMALY` and ends an active episode with
  `KNOWN_INELIGIBLE` plus a detail reason;
- expiry, deactivation, or reconciled catalog removal ends it with `MEMBERSHIP_LOSS`;
- any detector `UNKNOWN` other than the `TIME_BAND_BOUNDARY` suspension or a separately classified
  source-continuity gap ends it with `UNKNOWN_DETECTOR` plus a detail such as missing/invalid
  input, out-of-domain price, unbracketed IV, or `NUMERICAL_BOUNDARY_UNRESOLVED`;
- clean operator stop ends it with `CENSORED_AT_STOP`;
- ordinary ratio clearing is the only exit that uses clear persistence and ends with `CLEAR`.

Every end makes Layer 2 `NOT_EVALUATED` immediately. Resolved ineligibility, membership
readmission, or input recovery starts from `ARMED` and requires fresh activation; only the
adjacent-band suspension rule above preserves an episode identity.

One instrument's `ARMED -> ACTIVE` transition writes one `SHORT_VOL_ANOMALY_EVENT` for that short
leg. It is not rewritten as quotes change.

### Global continuity, current coverage, and option-local availability

The runtime keeps three ledgers whose units and reset rules are not interchangeable:

1. `global_continuity_epoch` is a positive integer starting at `1`. It increments exactly once
   for each retired session, ingress gap/duplicate or queue overflow, trusted-clock gap, or real
   index continuity loss (`WINDOW_GAP | SOURCE_STALE | CONTINUITY_GAP`). Bootstrap
   `WARMUP`, normal `TIME_BOUNDARY_PENDING | WATERMARK_PENDING`, option ticker/book/catalog
   unavailability, ordered queue lag, aggregate coverage changes, and episode transitions never
   increment it. One
   root `ContinuityIncident` can increment it at most once before an explicit recovery edge;
   cause, failure domain, and affected scopes use the exact repository allowlist.
2. `current_market_truth_coverage` remains the exact global time partition
   `NO_APPLICABLE_SCOPE | KNOWN_COMPLETE | KNOWN_DEGRADED | UNKNOWN`. Every segment records the
   reason that caused its state to begin, the bounded affected scope
   (`GLOBAL`, one exact aggregate scope, or one option-local scope), and the active
   `global_continuity_epoch`. A local loss remains visible here even though it does not erase
   global continuity.
3. `option_local_availability` records ticker-local unavailable intervals by instrument,
   subscription generation, reason, start, end/recovery disposition, recovery time when known,
   duration, and continuity epoch. It is diagnostic and cannot change detector truth by itself;
   detector truth continues to consume the same accepted current facts.

The joint operational witness is one property of one settled full current
`Policy identity × expiry_timestamp × option_type` scope snapshot. That exact snapshot contains
every current member and derives both:

```text
detector_coverage = COMPLETE
has_current_full_formula = true
```

The reducer may reuse an unchanged member's current result, but it cannot combine complete
coverage calculated over the full scope with `full_formula_evaluation` taken only from the
boundary's affected subset or from historical counters. `EvidenceWriter` receives only a settled
episode edge or clean-stop projection; write success, file presence, and historical event content
never decide current scope truth.

An accepted BTC lifecycle boundary freezes its pre-mutation expiry/type scope, applies membership,
and recomputes only that affected immutable scope plus any independently time-changed scope.
Unrelated immutable current results are reused rather than rebuilt. A same-boundary expiry burst,
including the Deribit 08:00 UTC concentration, therefore scales with affected scopes without
changing unrelated detector, aggregate, coverage, witness, or atomic truth.

The first joint witness in the current `global_continuity_epoch` starts
`continuous_global_continuity_after_witness_ms`. Current coverage and option-local availability
continue to be reported independently and do not reset that clock. An epoch restart clears the
witness and requires a new same-snapshot joint witness. Human acceptance must separately freeze
both the required global-continuity duration and the permitted local-availability/coverage
thresholds before a later Soak. A terminal-goal delegation may instead freeze them in its durable
run manifest when the active task already defines their exact derivation. Elapsed global
continuity alone cannot silently waive poor local availability.

## Official atomic credit availability

Only an active official two-leg combo qualifies. Its metadata must prove:

- exactly two option legs;
- same expiry and option type;
- absolute leg ratio 1:1;
- the active episode's short leg;
- a farther OTM protective long leg;
- exact target leg signs for a defined-risk call or put credit vertical;
- official BTC amount units and minimum trade amount that permit the exact target quantity without
  rounding, plus `qty_tick_size` alignment when that optional official field is published.

The target leg vector is fixed:

```text
call credit: sell lower-strike call, buy higher-strike call
put credit:  sell higher-strike put, buy lower-strike put
```

Official `legs[].amount` defines the signed leg vector produced by buying the combo. Find the one
signed combo order amount whose multiplication by that vector equals the desired leg amounts
exactly. For target short-leg BTC quantity `q`, the only authorized results are
`signed_order_amount_btc = +q` or `-q`:

- positive means `BUY` and consumes asks;
- negative means `SELL` and consumes bids;
- no exact match means reject the combo.

Preserve the sign of the required-side depth-weighted combo price:

```text
gross_entry_credit_usdc =
    -signed_order_amount_btc × required_side_vwap_usdc_per_btc
require gross_entry_credit_usdc > 0
```

The calculation never takes the absolute value of combo price. This prevents a debit orientation
from being called a credit merely because one side of the book has depth.

No component-leg synthetic price, mark, mid, theoretical price, RFQ, or imagined maker price can
create `PUBLIC_ATOMIC_QUOTE_AVAILABLE`.

Layer 2 intentionally stops at gross public availability. Account fee tier, maker/taker status,
delivery fee, margin, liquidation, strike-width risk, maximum loss after costs, and future exit
liquidity belong to later Underwriting/Execution.

When optional public quantity-step metadata is absent, Layer 2 still reports only visible depth
subject to published required amount metadata; it never claims that a later private order will be
accepted.

## Durable objects

Only three runtime evidence object kinds are permitted:

### `SHORT_VOL_ANOMALY_EVENT`

Written once per activated episode. It contains only:

- Policy/code/runtime/episode identity and causal time;
- one short-leg instrument, expiry, option type, activation TTE band, aggregate coverage state,
  and target BTC quantity;
- detector boundaries, compact baseline summary, trusted-time interval, and remaining-life `T`
  interval;
- that short leg's consumed bid levels and pricing inputs, plus total-volatility, IV, Delta,
  implied-total-variance, and richness lower/upper intervals and the final classification;
- explicit `NOT_A_DELIVERY_TWAP_DISTRIBUTION_FORECAST` and `NOT_VALIDATED_FORECAST`
  non-claims.

### `PUBLIC_ATOMIC_QUOTE_EVENT`

Written once per `(episode_id, combo_id)` first observed available inside one short-leg anomaly
episode. Quote changes or `AVAILABLE -> unavailable -> AVAILABLE` do not rewrite it. Another combo
in the same episode and the same combo in a new episode may each write once. The emitted identity
is registered only after the exclusive write succeeds; a conflicting existing file remains a
hard error and is never overwritten or caught-and-continued. It references that episode directly
and contains only:

- official combo identity and signed legs;
- the short-leg episode's current active detector causal binding;
- required combo order direction;
- target BTC quantity and consumed bid or ask levels;
- normalized positive gross entry credit;
- source times, causal sequence, and public-quote non-claims.

### `RADAR_RUN_SUMMARY`

Written on clean operator stop. It records coverage, usable detector evaluations, anomaly
activations, episode ends by
`CLEAR | KNOWN_INELIGIBLE | OUT_OF_BASELINE_SCOPE | MEMBERSHIP_LOSS | UNKNOWN_DETECTOR |
UNKNOWN_AT_GAP | CENSORED_AT_STOP`, known-active duration by end reason, band-suspended duration,
Layer 2 state transitions, detector `UNKNOWN` transitions by reason, and Policy identity. Counts
are business-state transitions after reduced-state de-duplication, never message counts. Rates
with a zero or unknown denominator are `null`.

`operational_diagnostics` is a required strict object with
`operational_diagnostics_schema_version = 6`. It is operational evidence only and has exactly
these members:

- `runtime_limits`: the exact nine frozen Policy `runtime_limits`;
- `ingress`: `received_envelope_count`, `reduced_envelope_count`,
  `ingress_gap_or_duplicate_count`, `queue_high_water_frames`,
  `max_receive_to_reduce_lag_ms`, `overflow_count`, `send_control_event_count`, and
  `connection_error_event_count`;
- `rpc_by_method`: one row per exact-allowlisted consumed method, sorted by method, with `method`,
  `scheduled_count`, `sent_count`, mutually exclusive `success_count`, `error_count`,
  `deadline_late_count`, `retired_count`, `censored_count`, the provenance fields
  `pre_send_error_count`, `pre_send_deadline_late_count`, `pre_send_retired_count`,
  `pre_send_censored_count`, `post_send_success_count`, `post_send_error_count`,
  `post_send_deadline_late_count`, `post_send_retired_count`, and
  `post_send_censored_count`, followed by `rate_limit_count`, `latency_observation_count`,
  `latency_ms_sum`, and `latency_ms_max`; unmatched or already terminal wire responses are
  excluded from method outcomes and counted only in top-level `rpc_orphan_late_wire_count`;
- `transport_terminal_attribution`: sorted unique rows containing exactly `close_code`,
  `close_disposition`, `exception_class`, and positive `count`. Close code is bounded to
  `1000 | 1001 | 1002 | 1003 | 1006 | 1007 | 1008 | 1009 | 1010 | 1011 | 1012 | 1013 |
  1014 | 1015 | NOT_AVAILABLE | OTHER`; disposition is `CLEAN` only for `1000 | 1001` and
  otherwise `ABNORMAL`; exception class is bounded to
  `NONE | PublicProtocolIncompatibility | PublicProtocolError | ConnectionClosedOK |
  ConnectionClosedError | OSError | SSLError | TimeoutError | EOFError |
  WebSocketException | OTHER`. No exception message, URL, payload, or other unbounded transport
  detail is persisted. Every reduced current or already-retired `connection_error` commits its
  count and one bounded attribution row atomically before the retired-epoch business-effect
  barrier; row counts sum exactly to `ingress.connection_error_event_count`;
- `channel_by_class`: exactly one sorted row for each
  `PLATFORM | OPTION_LIFECYCLE | COMBO_LIFECYCLE | INDEX | OPTION_TICKER | OPTION_BOOK |
  COMBO_BOOK | HEARTBEAT | CONNECTION_CONTROL | INVALID`, with `received_count`,
  `processed_count`, `received_rate_per_second`, and `processed_rate_per_second`;
- `subscriptions`: `current_subscribed_instrument_count`,
  `peak_subscribed_instrument_count`, `current_subscribed_channel_count`, and
  `peak_subscribed_channel_count`;
- `heartbeat`: `test_request_count`, `public_test_success_count`, `public_test_error_count`,
  `latency_observation_count`, `latency_ms_sum`, and `latency_ms_max`;
- `recovery`: counts for reconnect, session gap, index gap, index resubscribe, option-channel
  resync, and attempt/success/failure for clock refresh, option-catalog refresh, and combo
  authoritative refresh;
- `source_shapes`: one sorted row per core RPC/channel source with `source`, `observed_count`,
  `valid_count`, `invalid_count`, `validation = NOT_OBSERVED | VALID | INVALID`, and a sorted list
  of consumed `{key, type}` pairs governed by the exact shared field specification below; an
  unobserved source has no consumed fields, and any undeclared key or impossible JSON type fails;
  this ledger reports parse/consumed-shape validity only, so a shape-valid `LATE_IGNORED` ticker
  increments `valid_count`, never `invalid_count`;
- `global_continuity`: positive `current_epoch`, total `restart_count`,
  `restart_count_by_reason`, exact `restart_edges`, explicit `recovery_edges`, and
  `current_epoch_joint_evaluation_count_by_scope`; each current-epoch row has exactly
  `policy_identity`, `expiration_timestamp_ms`, `option_type`, `tte_band_id`,
  `formula_instrument_name`, positive `count`, and nullable
  `first_joint_evaluation_boundary`. Every current version-6 restart edge has exactly `incident_id`,
  `from_epoch`, `to_epoch`, root `trigger_cause`, restart-effect `reason`, `failure_domain`,
  `affected_scopes`, and `boundary`;
- `ticker_application`: `disposition_count` has exact counts for
  `APPLIED | LATE_IGNORED | AHEAD_IGNORED | STALE_GENERATION_IGNORED | SHAPE_REJECTED`, a fixed
  `late_ignored_diagnostic_limit = 256`, `omitted_late_ignored_diagnostic_count`, and at most 256
  strict-regression `late_ignored_diagnostics` rows containing only `instrument_name`, channel
  `generation`, `ingress_seq`, `previous_source_timestamp_ms`,
  `candidate_source_timestamp_ms`, signed `timestamp_delta_ms`, `received_monotonic_ms`, and
  `disposition = LATE_IGNORED`;
- `ticker_currentness`: `candidate_count_by_classification` has exact counts for
  `CURRENT | SOURCE_STALE | TIMESTAMP_AHEAD | TRUSTED_TIME_UNKNOWN`, separately from de-duplicated
  `accepted_transition_count_by_state` for `MISSING | CURRENT | SOURCE_STALE`;
- `index_baseline_publication`: exact `start_count_by_phase`, `end_count_by_disposition`,
  `acceptance_window_ms = 3_600_000`, `retained_interval_limit = 10_000`,
  `outside_window_interval_count`, nullable `outside_window_latest_end_monotonic_ms`, exact fixed
  `outside_window_interval_count_by_phase_and_disposition`, `omitted_interval_count`, exact fixed
  `omitted_interval_count_by_phase_and_disposition`, and bounded `intervals`. Each retained row has
  exactly `phase`, `published_tail_last_minute_start_ms`,
  `target_successor_minute_start_ms`, `start_monotonic_ms`, `end_monotonic_ms`, `duration_ms`,
  `end_disposition`, `global_continuity_epoch`, and nullable `currentness_loss`. Minute identities
  are 60-second aligned, target equals published plus 60 seconds, and rows are positive half-open
  sorted nonoverlapping intervals. Only `CURRENTNESS_LOST` has non-null
  `{reason, boundary}` with one allowlisted session/clock/index invalidating reason, a full exact
  `FactBoundary`, and `boundary.received_monotonic_ms = end_monotonic_ms`; every other disposition
  requires null. The row is the owning publication-currentness transition. If one exact full
  boundary also owns a restart edge, its reason and `from_epoch` must agree; a different fact in
  the same integer monotonic millisecond is not cross-bound. `PHASE_CHANGED` is only
  time-to-watermark for the same identity, `PUBLISHED` owns a successor seal, and
  `CENSORED_AT_STOP` ends exactly at clean stop. Rows ending at or before the final-hour start are
  compressed before the independent 10,000-row detail cap; only true final-hour overflow is
  omitted, and any omission makes Soak `NOT_MET`;
- `option_local_availability`: `unavailable_count_by_reason`, `recovery_count_by_reason`, fixed
  `end_count_by_disposition`, fixed `acceptance_window_ms = 3_600_000`, fixed
  `retained_interval_limit = 10_000`, exact `outside_window_interval_count`,
  nullable `outside_window_latest_end_monotonic_ms`,
  `outside_window_interval_count_by_reason`, `omitted_interval_count`,
  `omitted_interval_count_by_reason`, and at most 10,000 `intervals` containing only
  `instrument_name`, ticker `generation`, `reason`, `start_monotonic_ms`,
  `end_monotonic_ms`, `duration_ms`,
  `end_disposition = RECOVERED | REASON_CHANGED | CENSORED_AT_STOP`, and
  `global_continuity_epoch`. At clean stop, every interval ending after
  `clean_stop_monotonic_ms - 3_600_000` is retained unless the fixed row bound was genuinely
  exceeded; only intervals ending at or before that boundary enter the exact outside-window
  conservation totals. `outside_window_latest_end_monotonic_ms` is null exactly when that count
  is zero and otherwise cannot enter the final acceptance window. `omitted_interval_count` is
  reserved for genuine retention overflow and never means ordinary historical compaction. Every
  retained `CENSORED_AT_STOP.end_monotonic_ms` equals the clean stop boundary exactly;
- `witness`: current `global_continuity_epoch`, nullable
  `first_joint_witness_monotonic_ms`, and nullable
  `continuous_global_continuity_after_witness_ms`, plus its exact scope, fact boundary, and formula
  instrument identity. A known witness must lie inside a current-epoch `KNOWN_COMPLETE` segment,
  follow strict recovery of the latest incident, bind exactly one `counts_by_scope` row whose
  `complete_aggregate_with_full_formula_evaluation_count > 0`, and match one current-epoch joint
  row on every Policy/expiry/option-type/band/formula-instrument field and its first eligible
  boundary.

For `rpc_by_method`, the validator proves both equations for every row:

```text
scheduled_count =
    sent_count
  + pre_send_error_count
  + pre_send_deadline_late_count
  + pre_send_retired_count
  + pre_send_censored_count

sent_count =
    post_send_success_count
  + post_send_error_count
  + post_send_deadline_late_count
  + post_send_retired_count
  + post_send_censored_count
```

Each aggregate terminal total equals the sum of its pre-/post-send provenance; success is
post-send only. Rate limits are a subset of post-send errors. Latency observations are a subset
of post-send response terminals and start at the real immutable `SENT` boundary.

The shared `source_shapes` field specification uses JSON types `S = string`, `B = boolean`,
`I = integer`, `N = integer | number | string`, and `A = array`:

```text
combo_book, option_book:
  type:S timestamp:I instrument_name:S change_id:I
  prev_change_id:I|null bids:A asks:A
combo_lifecycle, option_lifecycle:
  instrument_name:S state:S
heartbeat:
  type:S
index:
  timestamp:I index_name:S price:N
option_ticker:
  instrument_name:S timestamp:I underlying_price:N underlying_index:S
platform_state:
  maintenance:B price_index:S locked:B
platform_state.public_methods_state:
  allow_unauthenticated_public_requests:B
public/get_combos:
  id:S state:S legs:A
public/get_instrument, public/get_instruments:
  instrument_name:S kind:S base_currency:S quote_currency:S settlement_currency:S
  counter_currency:S price_index:S instrument_type:S is_active:B state:S option_type:S
  expiration_timestamp:I strike:N contract_size:N min_trade_amount:N qty_tick_size:N
public/status:
  locked:B|S locked_indices:A
public/test:
  version:S
public/get_time, public/set_heartbeat, public/subscribe, public/unsubscribe:
  no object-key fields
```

The two channel rates use the run observation interval in seconds; either rate is `null` when that
denominator is zero or unknown. Ingress, channel classes, send/connection controls, transport
terminal attribution, RPC response latency, orphan wire responses, heartbeat/public-test facts,
and source shapes cross-conserve exactly. Atomic evidence is directory-valid only when its
code/runtime/Policy/episode identity,
target, short leg, detector causal identity, and later quote causal order cross-bind to the owning
anomaly event and that anomaly's Policy/option-type/activation-band scope has a positive
`PUBLIC_ATOMIC_QUOTE_AVAILABLE` transition in `counts_by_scope`. Only a
`global_continuity_epoch` restart clears the witness start. Current coverage or option-local
availability loss remains explicit in its own ledger and does not reset global continuity.
Diagnostics count source/application/currentness facts in their declared ledgers and never enter
detector, episode, aggregate, atomic availability, or any trading denominator.

The final-window option-local ledger is bounded by time and by a fixed row cap independently of
total run duration. Post-stop acceptance inspects the exact half-open hour
`[clean_stop_monotonic_ms - 3_600_000, clean_stop_monotonic_ms)` and requires
`omitted_interval_count = 0`; outside-window aggregate counts preserve full-run conservation but
do not masquerade as retained interval detail. This one-hour horizon is an operational evidence
contract, not a Policy value, detector cadence, market-currentness deadline, or automatic stop
condition.

Session continuity restart causes are finite and boundary-owned. In addition to existing
platform, queue-overflow, application-sequence, clock, and index causes, the session-global
allowlist distinguishes
`REMOTE_CONNECTION_CLOSED`, `TRANSPORT_READ_FAILURE`, `SESSION_LIVENESS_DEADLINE`,
`SESSION_RPC_FAILURE`, `RUNTIME_SESSION_FAILURE`, and `PROTOCOL_INCOMPATIBILITY`. The first
retirement of an epoch freezes that cause; a later reconnect notice is idempotent and cannot
replace it with generic `SESSION_GAP`.

Coverage is one exact half-open runtime interval
`[runtime_started_monotonic_ms, clean_stop_monotonic_ms)`. At every monotonic millisecond it has
exactly one mutually exclusive global state across all current Policy-applicable aggregate scopes:

- `NO_APPLICABLE_SCOPE`: reconciled catalog and trusted time are known and prove that no non-empty
  expiry/type scope currently has a Policy rule;
- `KNOWN_COMPLETE`: every current scope and instrument has known detector state;
- `KNOWN_DEGRADED`: at least one known active witness exists, but another current instrument/scope
  is unresolved;
- `UNKNOWN`: scope existence itself or any required prerequisite is unresolved, or at least one
  scope exists but warm-up, band suspension, or unresolved facts prevent either complete coverage
  or a degraded positive witness.

Out-of-scope instruments create no scope; dynamic catalog/band transitions split the interval at
their accepted causal boundary. `band_suspended_duration_ms` is a diagnostic subset of
`UNKNOWN`/`KNOWN_DEGRADED`, not a fifth partition state. The summary validator enforces:

```text
observation_interval_ms =
    known_complete_ms
  + known_degraded_ms
  + unknown_ms
  + no_applicable_scope_ms
coverage_partition_error_ms =
    observation_interval_ms - sum(the four partition durations)
```

Any overlap, gap, negative duration, or nonzero error fails validation.

Every current version-6 `coverage_segments` row has exactly
`start_monotonic_ms`, `end_monotonic_ms`, `state`, `trigger_cause`, `blocking_reason`,
`affected_scopes`, `global_continuity_epoch`, and `blocking_groups`. `blocking_groups` is a sorted
array of 0–256 strict objects containing exactly `blocking_reason` and `affected_scopes`; group
reasons are unique. `KNOWN_COMPLETE` requires an empty array and scalar
`blocking_reason = NONE`. Every incomplete state requires one or more non-`NONE` groups, and
`NO_APPLICABLE_SCOPE` requires one matching group. `NONE`, `LEGACY_UNATTRIBUTED`, and
`ACTIVE_POSITIVE_SCOPE_INCOMPLETE` are forbidden as group reasons. `trigger_cause` is the reduced
fact whose transaction caused entry into that state. Each group records one bounded prerequisite
and the scopes where it actually prevents completeness; a concurrent source-currentness effect
therefore need not equal `trigger_cause`. The scalar `blocking_reason` equals the sole group reason,
or `CURRENT_SCOPE_INCOMPLETE` when multiple heterogeneous groups exist. The scalar
`affected_scopes` is the exact bounded summary of all group scopes.
`affected_scopes` is a sorted array of 1–256 labels whose bounded labels are exactly `GLOBAL`,
`OPTION_LOCAL`, `SCOPE:<expiry_timestamp_ms>:<call|put>:<band_id>`, or
`OPTION:<instrument_name>`. `OPTION_LOCAL` is the aggregate representation when a proper
option-local subset would otherwise require more than 256 instrument labels; it does not mean
global continuity was lost. Incomplete coverage derives all blocker groups from the complete
committed current truth, never only from the newest causal effect. Segment identity is exactly
`state + blocking_groups + global_continuity_epoch`: a change in any member splits at that
boundary; a fact that leaves all three unchanged does not split merely to log activity. Every
version-6 epoch edge additionally cross-binds the coverage `trigger_cause` to the restart root and
one exact group to the restart effect and scopes. Before that incident recovers, later same-epoch
segments may replace or combine its blocker with another real session/clock/index currentness
blocker without a second epoch edge. No such global blocker may appear in epoch 1 or extend beyond
the owning incident's recorded recovery. An epoch restart always splits at its exact boundary even
when the coverage state is unchanged. The sole exception is one final, unrecovered restart whose
exact boundary equals clean stop: it is a real terminal point event but owns no positive-duration
coverage segment, so the final partition legitimately remains in its `from_epoch`; no zero-length
segment is fabricated.

### Writer, reader, and compatibility

`radar_runtime` is the only writer. The current readers are the strict repository-owned schema
validator and the operator delivery report; no later business module is a current consumer.
Required fields may not be silently null, and only explicitly declared unavailable diagnostics
may be nullable. Unknown fields in these repository-owned objects fail validation.

Every object binds exactly one Policy identity. Mixed Policy or runtime identities inside one
evidence directory fail closed. Comparison compatibility across different Policy identities is
`NOT_COMPARABLE` for forecast/trading claims; only the explicitly named operational counts may be
reported side by side, with no causal or quality inference. A schema or reader change requires an
explicit task.

The Policy schema remains exactly version 3 and is unchanged by this repair. Summaries use
integer `operational_diagnostics_schema_version = 6` and the grouped coverage-segment shape above.
The writer and reader accept only version 6. Current accounting treats publication `P` as
diagnostic, keeps `K` independent, defines `G` from real currentness incidents, `E = W \ G`, and
intersects option-local `U` with `E`. Versions 2–5 and unversioned objects are unsupported and
`NOT_COMPARABLE`; there is no migration or compatibility reader. `SHORT_VOL_ANOMALY_EVENT` and
`PUBLIC_ATOMIC_QUOTE_EVENT` semantics remain compatible and unchanged.

Ordinary market facts, `NO_ANOMALY`, theoretical structures, unmatched combos, and full chain
state are transient. The objects do not contain the full option chain and cannot reconstruct the
configured lookback preceding an event.

This closure does not create replay, a second calculation path, a provenance command, or a
source-document graph. Direct tests validate the live formulas, state sequences, continuity, and
exact repository-owned object projections.

Production observation runs only from a clean Git worktree at one exact `HEAD`; startup rejects
tracked, staged, or untracked worktree changes and records that commit as `code_identity` in every
object. This small identity precondition does not create a provenance graph or claim that a commit
proves correctness.

## Product operating behavior

One `radar_runtime` process:

1. loads and validates one Policy;
2. establishes time, catalogs, lifecycle streams, index state, required pricing facts, and option
   books;
3. maintains bounded current state and only the largest configured rolling return window;
4. evaluates causally affected detector scopes as one aggregate transaction per exact scope;
5. writes one anomaly event on activation;
6. subscribes to matching active official combo books only while relevant anomalies are active;
7. reports Layer 2 independently and writes an atomic event when availability first appears;
8. leaves normal market/no-anomaly state transient;
9. writes one run summary when an operator or pre-registered external goal supervisor stops it;
10. otherwise runs until operator stop or process failure, not a fixed business duration.

A restart creates a new runtime identity and empty detector memory. Warm-state persistence and
cross-process episode de-duplication are not implemented.

## Establishment acceptance

### Direct behavior

Tests must cover:

- USDC source namespace, BTC-USDC filtering, lifecycle changes, acknowledged bounded
  subscriptions, initially locked/maintenance platform cases, `public/status`
  bootstrap/reconciliation, `public/get_time` RTT/discontinuity and conservative outward
  rounding/intersection, exact index/ticker/book channel allowlist and initial notifications,
  official heartbeat/test result shapes, non-blocking notification overflow, receive-time queue
  lag, normal socket close, stale subscription generations, late RPC responses, and tolerant
  unrelated source fields;
- TTE and trusted-clock interval boundaries, including final delivery-price window exclusion;
- snapshot/change continuity, quiet unchanged books, empty/insufficient depth, gap/resnapshot,
  affected-only invalidation, exact `data.timestamp` mapping and index-minute sealing, index
  timestamp regression, and a late index tick for a sealed minute; ticker tests separately prove
  complete-snapshot semantics, equal-timestamp ingress ordering, older
  `LATE_IGNORED` without resync/episode/witness side effects, malformed/ahead candidate rejection
  without overwriting a current accepted fact, and true accepted-ticker TTL expiry/recovery;
- configured lookbacks, weights, floor, warm-up, missing minutes, exact remaining-life scaling,
  target-size bid walking, canonical total-volatility Black inversion, fixed OTM and configurable
  Delta eligibility, numerical-boundary fail-closed behavior, finite values, locked Decimal/model
  fixed vectors, and at least two different Policy fixtures;
- strict Policy parsing at every nesting level, duplicate/BOM/non-finite rejection, exact-byte
  digest mismatch failure before subscription, and proof that later file mutation cannot change
  the immutable in-memory Policy;
- required amount-metadata failure, optional `qty_tick_size` absence, valid published-grid
  alignment, invalid published step, and known off-grid rejection without rounding;
- activation, interval-bounded separation including equality/overlap, interrupted/too-soon
  persistence, clear/re-arm, every explicit episode end reason, unchanged-state suppression, gap
  termination followed by fresh new-episode activation, adjacent-band suspend/resume, scope-gap
  exit, and the non-vacuous completeness-aware aggregate truth table;
- independent detector and public atomic states;
- official call/put combo leg signs, target combo buy/sell direction, bid-versus-ask selection,
  positive normalized credit, wrong expiry/type/ratio, no combo, no depth, and combo `UNKNOWN`;
- minimal schema projection, Policy identity, unit-bearing decimals, null denominators, and absence
  of normal full-chain/no-anomaly persistence, plus dirty-worktree rejection and exact clean
  `HEAD` code identity; coverage fixtures inject interval overlap/gaps and must fail;
- initial bootstrap warm-up distinct from a real `INDEX_CONTINUITY_GAP`, normal cross-minute
  pending that preserves history, real global-gap epoch restart, post-gap recovery with a new
  same-current-scope joint witness, exact global-continuity duration, independent local
  availability intervals, and attributed coverage segments;
- current writer/validator tests for separate ticker
  shape/currentness/application/publication ledgers, bounded regression diagnostics, and grouped
  coverage reason-to-scope attribution, including rejection of missing, non-integer, and
  non-current diagnostics versions;
- absence of replay, offline recomputation, private, maker, Candidate, Shadow, Position, and
  Outcome paths.

### REACHABILITY_SMOKE

`REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` are independent production-public evidence gates.
Authorization, evidence, or acceptance for either one never accepts the other. A named bounded
terminal-goal delegation may conditionally authorize both gates as one product closure, but each
must still pre-bind and independently satisfy its own exact run manifest.

After Smoke authorization or terminal-goal pre-binding, run one exact Policy until either:

- warm-up completes and at least one real
  `Policy identity × expiry_timestamp × option_type` aggregate scope contains at least one current
  catalog instrument, at least one full-formula known per-instrument evaluation occurs inside that
  same settled full current-scope snapshot, and that snapshot's complete scope evaluates to known
  `NO_ANOMALY` or `ANOMALY_ACTIVE`, after which the pre-registered external supervisor may stop
  according to its result-independent predicate; or
- a human emergency stop or the pre-registered predicate stops it earlier.

A pre-warm-up or all-`UNKNOWN` stop is truthful but does not establish runtime capability. A
degraded positive witness is truthful evidence but does not by itself complete establishment.
A complete usable `NO_ANOMALY` result does. Natural anomaly and public atomic quote are
independently reported `OBSERVED | NOT_OBSERVED`; neither is required and neither may be forced
through in-place tuning.

`known_full_detector_formula_evaluation_count` increments only when one real instrument passes
minimum-amount, target-depth, OTM, and Delta gates and produces known baseline volatility,
executable IV interval, and richness classification. Minimum/depth/OTM/Delta short-circuit
`NO_ANOMALY` remains truthful but cannot by itself establish the full Radar formula path.
`complete_aggregate_with_full_formula_evaluation_count` increments only when that full-formula
instrument is inside the same Policy/scope settled full current snapshot that is complete.
Still-current results for unchanged members may be reused, but stale/historical results, a
different scope, and only the current boundary's affected subset cannot be combined into the
establishment witness.

Accepted summary invariants are:

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

Counts are grouped by Policy identity, option type, and TTE band. Zero or unknown denominators
serialize as `null`. Evaluation and atomic-state transitions use their current band; episode,
activation, clear, and duration metrics stay attributed to the episode's activation band. Direct
integration spies and artifact inspection—not new runtime counters—prove zero private API calls,
zero forbidden downstream artifacts, and zero persisted normal market/no-anomaly rows.

This joint witness proves only real-wiring reachability. It is not a sustained-operation
acceptance and cannot by itself establish the production Radar.

### OPERATIONAL_SOAK — separately pre-bound before production

Production establishment also requires a continuous-operation manifest naming the exact pushed
code `HEAD`, exact Policy path/digest, a new empty evidence directory, and its deterministic
result-independent stop condition. A human or active terminal-goal delegate may explicitly
rebind a previously approved Policy identity or bind an expressly permitted successor; omission
never carries an identity forward. No run duration is fixed by this contract or inferred from a
smoke witness.

The Soak run manifest must independently name the exact accepted code `HEAD`, verified equal
remote `HEAD`, Policy path/digest, evidence directory, and stop condition. A prior Smoke command
or witness supplies none of these bindings.

The construction implementation must record:

- actual request/response count, latency, errors and rate-limit outcomes by consumed RPC method,
  and received/processed counts plus observation-duration-derived rates by channel class;
- subscribed instrument/channel counts, queue high-water, maximum receive-to-process lag, and
  overflow;
- conditionally observed heartbeat request/response round trips, without inventing a
  `test_request` when the server emitted none;
- reconnect, gap, resync, and clock-refresh success/failure;
- option/combo catalog refresh and recovery outcomes;
- core RPC/channel appearance and consumed-field shape validation, retaining only keys, types,
  and validation result rather than full market payloads;
- separate ticker shape/currentness/application dispositions and bounded late-snapshot rows;
- global continuity epochs, current coverage reason/scope/epoch, and bounded option-local
  unavailable/recovery intervals;
- the uninterrupted global-continuity interval after a same-current-scope joint full-formula
  complete-aggregate witness.

Before any later Soak, the order is:

1. direct focused tests and `make check`;
2. any heartbeat wire probe required by the active task, separately pre-bound under the current
   authority;
3. pre-freezing of the new global-continuity duration and explicit option-local and
   current-coverage thresholds in the run manifest; publication pending has no acceptance budget;
4. a new independently bound Soak using the previously approved business Policy or one expressly
   permitted successor and a new empty evidence directory.

Post-stop acceptance keeps independent integrity, publication, coverage, and currentness
results. `P` is the wall-clock union of version-6 index publication pending rows in the exact final
hour. It is diagnostic only, may overlap `KNOWN_COMPLETE` or an unrelated local blocker, has no
budget, and is not subtracted from `K` or `E`. Current coverage is still calculated over the full
hour and must satisfy the frozen 99% threshold. Real global/session/clock/index incident union is
`G`; effective option-local denominator is `E = W \ G`.

A global epoch restart requires a new same-snapshot witness after global recovery. Queue-lag and
option-local incidents instead prove their recovery in their own coverage/availability ledgers;
they neither require a new global witness nor relabel the earlier witness as post-recovery.
Heartbeat wire evidence is conditional: an absent server heartbeat/test request is
`NOT_OBSERVED`, while every observed request, shape, RPC terminal, and latency must
cross-conserve. The pre-bound run manifest owns all frozen thresholds. A deterministic stop by the
registered external supervisor is valid; elapsed time alone is never acceptance. Process failure,
an incomplete directory, or a directory that was not empty at startup is `NOT_MET`. The current
version-6 strict directory reader accepts only regular non-symlink `.json` entries and requires
exactly one canonical `radar-run-summary.json`. Unsupported historical objects are never
retroactively authorized.

## Evidence boundary

**Proves:** one content-identified public Radar can maintain honest current state, produce usable
detector evaluations, and preserve official atomic quote availability as a separate fact under
real production-public connectivity.

**Does not prove:** forecast accuracy, natural event frequency outside the observed interval,
edge, Candidate quality, maker feasibility, fee economics, maximum loss, a fill, margin,
closeability, Outcome, PnL, qualification, promotion, or execution permission.

This closure stops at `SHORT_VOL_ANOMALY_EVENT` plus optional
`PUBLIC_ATOMIC_QUOTE_EVENT`. Neither entry kind has a planned holding duration. Later Position
logic must keep `CLOSE` separate from quote availability, never let a missing quote override a
known hard-close condition, emit `SHADOW_CLOSE_OPPORTUNITY` only when action is `CLOSE` and a
strictly future full-quantity atomic quote exists, and keep `LEGGED_CLOSE_REFERENCE` diagnostic.

## Public-source basis and inference limits

The implementation and Policy must pin the exact official API/schema facts they consume. Current
design basis:

- [Deribit order-book subscription semantics](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval)
- [Deribit market-data collection practices](https://docs.deribit.com/articles/market-data-collection-best-practices)
- [Deribit index subscription](https://docs.deribit.com/subscriptions/market-data/deribit_price_indexindex_name)
- [Deribit ticker subscription](https://docs.deribit.com/subscriptions/market-data/tickerinstrument_nameinterval)
- [Deribit linear USDC options and delivery-price mechanics](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options)
- [Deribit settlement Delta decay](https://support.deribit.com/hc/en-us/articles/25944751433757-Delta-decay-during-settlement)
- [Deribit instrument lifecycle subscription](https://docs.deribit.com/subscriptions/market-data/instrumentstatekindcurrency)
- [Deribit public platform-state subscription](https://docs.deribit.com/subscriptions/platform/platform_state)
- [Deribit public-method-state subscription](https://docs.deribit.com/subscriptions/platform/platform_statepublic_methods_state)
- [Deribit public status bootstrap](https://docs.deribit.com/api-reference/supporting/public-status)
- [Deribit server time](https://docs.deribit.com/api-reference/supporting/public-get_time)
- [Deribit instrument metadata and quantity step](https://docs.deribit.com/api-reference/market-data/public-get_instrument)
- [Deribit WebSocket heartbeat](https://docs.deribit.com/api-reference/session-management/public-set_heartbeat)
- [Deribit heartbeat test response](https://docs.deribit.com/api-reference/supporting/public-test)
- [Deribit official combo books and leg conventions](https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books)

These sources define mechanics, not a universal target quantity, Delta band, return lookback,
trigger, clear rule, or profitable Short Vol strategy.
