# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Current implementation state:** IMPLEMENTED — AWAITING REVIEW AND SEPARATE PRODUCTION OBSERVATION

**Owning closure:** `SHORT_VOL_RADAR_ESTABLISHMENT`

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

Platform startup does not default an unobserved `maintenance = false`. It remains unusable until:

1. buffered platform subscriptions are acknowledged;
2. `public/status` succeeds and its official lock fields prove that neither all currencies nor the
   consumed BTC index are locked;
3. the time/catalog requests and subscriptions succeed after that status boundary; and
4. fresh index coverage is established.

That is the global platform boundary, not a global all-option barrier. Each current option's own
initial ticker and book snapshot gates only that detector. A missing or invalid per-instrument
fact makes that instrument `UNKNOWN`; it does not suppress a causally known active witness in
another instrument, which is reported through the completeness-aware aggregate state.

`platform_state.public_methods_state.allow_unauthenticated_public_requests = false`, a relevant
lock, or a maintenance/break notification invalidates dependent state immediately. A later
`true`, unlock, or maintenance-end notification is not sufficient by itself: the four bootstrap
conditions above must be re-established. Thus the maintenance stream is a fail-closed transition
guard, while successful post-status public bootstrap plus fresh data is the startup usability
oracle.

No private, account, RFQ, combo-creation, order, trade, fill, maker, or test-environment method is
permitted. The only allowed `public/test` call is the protocol-required response to a
`test_request` on the already established production-public heartbeat; it cannot be initiated as
a market/business probe.

External responses may add unrelated fields. Only missing, invalid, or semantically changed fields
actually consumed by this contract fail closed at their smallest consumer.

The WebSocket enables `public/set_heartbeat` at a fixed operational interval of 30 seconds and
acknowledges it before market state can become usable. This is transport safety, not a trading
Policy parameter, and the run summary freezes it. The consumed official result shapes are
`public/set_heartbeat -> "ok"` and `public/test -> {"version": <non-empty string>, ...}`. Every
`test_request` is answered with `public/test`. No inbound session activity for 60 seconds, a
failed heartbeat/test response, or a connection close invalidates every
connection-dependent consumer and ends affected active episodes as `UNKNOWN_AT_GAP`. Reconnect
requires fresh subscriptions, snapshots, catalog reconciliation, and baseline coverage.
Heartbeat traffic proves only transport liveness: it never refreshes a book's economic timestamp,
creates a detector observation, or bridges a market-data sequence gap.

The socket reader assigns every inbound frame—notification or RPC response—one increasing
`ingress_seq` and local `received_monotonic_ms` immediately after decode. Economic facts enter one
ordered reducer by that sequence. Heartbeat `test_request` control may call `public/test` without
waiting for catalog work, but neither the control message nor its response may apply an economic
fact out of order. Bootstrap and steady state use the same receive-lag gate and update the same
maximum queue-lag diagnostic. The queue is bounded and must never block the sole RPC-response
reader: overflow is a session gap. Processing more than 1000 ms after receive is also a session
gap, not a late market observation.

## Time and settlement boundary

The Monitor advances last accepted Deribit server time with local monotonic elapsed time and
carries an explicit uncertainty interval. A TTE band is usable only when that entire interval
falls inside the same band. One pure classification is shared by detector, aggregate, coverage,
and membership: `IN_BAND | ADJACENT_BAND_BOUNDARY | POLICY_GAP | FINAL_WINDOW |
MONITOR_BOUNDARY | OUT_OF_MONITOR_SCOPE`. `ADJACENT_BAND_BOUNDARY` and `MONITOR_BOUNDARY`
remain unresolved for coverage; a known Policy gap or final window is known absent scope.
Membership changes split coverage at one causal/monotonic boundary before any subscribe or
unsubscribe await.

For each `public/get_time` request, record local monotonic send/receive instants and the returned
integer server millisecond. At receipt, its 1 ms quantization and request round trip establish
`base = [returned_ms, returned_ms + 1 ms + round_trip_ms]`. With local monotonic elapsed `e_ms`,
the current interval is
`[base.lower + e_ms × (1 - 1000/1_000_000),
base.upper + e_ms × (1 + 1000/1_000_000)]`; 1000 ppm is a fixed conservative operational drift
budget, not Policy. All clock math uses integer/rational milliseconds: round the lower bound toward
negative infinity and the upper bound toward positive infinity; binary float may not narrow the
interval. Refresh every 30 seconds and fail closed at 60 seconds without a refresh. If
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
instrument first and settles that aggregate exactly once from that same causal pass. It may not
publish transient partial truth produced by iteration order.

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

One exact content-identified Policy file supplies:

- `target_base_quantity_btc`;
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
- at least one TTE band and a non-empty supported `option_rules` map in every band;
- at least one unique positive-integer lookback and one aligned finite non-negative weight per
  lookback, with weights summing exactly to one after canonical decimal parsing;
- non-overlapping TTE bands contained in `(30 minutes, 72 hours]`; any deliberate gap is explicit
  `OUT_OF_BASELINE_SCOPE`;
- `0 <= abs_delta_min < abs_delta_max <= 1`;
- finite `target_base_quantity_btc > 0`;
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

Numeric values are configuration, not universal trading truth. The implementation tests at least
two materially different Policy fixtures so code constants cannot masquerade as Policy.
Construction establishes the schema and loader, not a preferred live parameter set. A later human
production-observation command names and approves the exact external Policy path and digest.

The Policy format is UTF-8 JSON without a BOM, with one top-level object, duplicate keys rejected,
and non-finite numbers rejected. Before any network subscription, startup reads its exact bytes
once, computes `sha256:<hex>` over those bytes, and requires equality with the human-approved
expected digest supplied to the command. JSON numeric tokens parse directly to `Decimal`. It then
uses only the immutable parsed in-memory object; a missing/mismatched digest or a later file
mutation cannot change the running Policy.

### One run, one immutable identity

The process binds the verified exact-byte Policy digest before subscribing. Every event and run
summary records that identity. Hot reload, in-run mutation, automatic training, automatic
selection, and automatic deployment are rejected.

After reviewing a forward interval, a human may approve a successor inside this same Policy
schema. It may change target quantity, TTE bands/gaps and call/put inclusion,
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

The first human-approved production-observation Policy may be intentionally broad for operational
coverage/frequency/flicker discovery, while still satisfying every load invariant, including
`activation_ratio > 1`. Each later Policy successor is reviewed and observed only on a new
forward interval. Improving the estimator itself requires a later contract that first declares an
exact horizon-matched future volatility or settlement label and comparator; it is not smuggled
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

A baseline window is current only when its closes are internally consecutive and its tail is the
minute immediately before the trusted clock's current minute. A 60-return maximum therefore needs
61 consecutive covered closes. An older internally consecutive window is
`INDEX_BASELINE_STALE/UNKNOWN`; stale or gap invalidates the window and known evaluation cannot
resume until a fresh complete window is rebuilt.

Missing or gapped minutes make only consumers whose configured window includes them `UNKNOWN`.
Warm-up requires `largest_configured_lookback + 1` consecutive covered minute closes to form the
required number of returns; it is derived from Policy rather than a hard-coded close count.

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
activation attribute, not identity:

```text
UNKNOWN
          a required detector fact is missing/invalid, or derived classification is numerically unresolved
ARMED     this instrument is usable and no episode is active
ACTIVE    this instrument has passed activation
CLEARING  this instrument's clear persistence is pending
BAND_SUSPENDED
          trusted time straddles a Policy boundary while market-source continuity remains known
```

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

At each accepted causal boundary the runtime may build one short-lived, non-durable
`ScopeSnapshot`. It reports the recomputed current result separately from
`observation_eligibility/reason`. Trusted-time revision can change TTE/current classification,
but it is not a countable persistence observation. Observation identity contains only facts the
formula consumes: target-quantity bid levels, forward, current baseline, and discrete
TTE/currentness classification. Duplicates, ask-only changes, depth beyond the target,
heartbeats, metadata-only changes, and unchanged reduced economic state do not activate, clear,
or reset persistence and do not create observations or episodes.

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

A detector-dependent gap changes only the affected instrument to `UNKNOWN`, invalidates its
option/combo quotes, cancels pending observations, and never infers what happened inside the gap.
If an observed episode was active, it ends with `end_reason = UNKNOWN_AT_GAP`; its known-active
duration stops at the last trusted boundary.

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
with a zero or unknown denominator are `null`. Operational diagnostics include the frozen
notification queue-lag limit and the maximum observed queue lag.

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
9. writes one run summary when an operator stops it;
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
  affected-only invalidation, exact `data.timestamp` mapping and index-minute sealing, timestamp
  regression, and a late tick for a sealed minute;
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
- absence of replay, offline recomputation, private, maker, Candidate, Shadow, Position, and
  Outcome paths.

### Production-public smoke

After separate human authorization, run one exact Policy until either:

- warm-up completes and at least one real
  `Policy identity × expiry_timestamp × option_type` aggregate scope contains at least one current
  catalog instrument, at least one full-formula known per-instrument evaluation occurs inside that
  same causal aggregate evaluation, and the complete scope evaluates to known `NO_ANOMALY` or
  `ANOMALY_ACTIVE`, after which a human may stop it; or
- a human stops it earlier.

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
instrument is inside the same Policy/scope/causal evaluation that is complete; separate observations
cannot be combined into the establishment witness.

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
