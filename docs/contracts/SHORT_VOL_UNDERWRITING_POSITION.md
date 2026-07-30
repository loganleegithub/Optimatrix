# Short Vol Underwriting, Shadow Admission, and Position Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Current implementation state:** `CONTRACT_FROZEN — NOT_IMPLEMENTED`

**Owning future boundary:** `SHORT_VOL_UNDERWRITING_SHADOW_POSITION`

**Upstream contract:** [`SHORT_VOL_RADAR`](SHORT_VOL_RADAR.md)

## Purpose

Freeze the complete production-public Shadow contract that follows an established Short Vol Radar
opportunity. The contract decides whether one visible official atomic credit vertical pays for its
declared risk, admits a counterfactual Shadow Entry only after a later current quote proof, and
continuously decides `HOLD | CLOSE | UNKNOWN` without a planned holding duration.

This contract is implementation authority, not implementation presence. The current repository
contains no Underwriting, Candidate, Shadow Entry, Position action, close-opportunity, or Outcome
runtime path. Permission remains governed by
[`CURRENT_STAGE`](../authority/CURRENT_STAGE.md).

## Product boundary

The exact product slice remains:

```yaml
market: Deribit production public
underlying: BTC
product: BTC_USDC_LINEAR_OPTIONS
time_to_expiry: greater_than_0_and_at_most_72_hours
structure: 1x1_same_expiry_same_option_type_protective_vertical_credit_spread
environment: PUBLIC_SHADOW
```

The contract permits only an existing official option-combo instrument. Component-leg prices,
marks, mids, theoretical prices, RFQs, imagined maker prices, and private account facts cannot
create entry or close economics.

The future lifecycle is:

```text
current ANOMALY_ACTIVE short-leg episode
+ current official full-target atomic credit quote
→ Underwriting availability
→ CANDIDATE | WATCH | ABSTAIN only when EVALUABLE
→ still-valid Candidate
+ strictly later refreshed official full-target atomic quote proof
→ SHADOW_ENTRY
→ current Position evaluation
→ HOLD | CLOSE | UNKNOWN
→ CLOSE
+ strictly later official full-remaining-quantity atomic close quote
→ SHADOW_CLOSE_OPPORTUNITY
```

A public quote, Candidate, Shadow Entry, Position action, or Shadow close opportunity is never an
order, fill, actual position, actual exposure, or realized PnL.

## Exact identities and causal order

### `FactBoundary`

Every future object consumes one fully settled reducer boundary:

```text
FactBoundary =
    session_epoch
    × ingress_seq
    × received_monotonic_ms
    × causal_seq
```

Within one runtime, `causal_seq` is the strict committed business order. `session_epoch` and
`ingress_seq` cross-check source application order, and receive monotonic time may not move
backward. Admission additionally requires the same session and continuity epoch; a Position may
observe a later recovered session only after the known continuity-loss hard-close transition has
already been committed. Every object records the latest boundary it consumed.

### Structure identity

```text
structure_id =
    BTC_USDC_LINEAR_OPTIONS
    × canonical ordered signed option legs
    × combo_instrument_name
    × required entry combo direction
    × expiration_timestamp_ms
    × option_type
    × target_base_quantity_btc
```

The short leg is the active Radar episode's leg. A call credit spread sells the lower-strike call
and buys the higher-strike call. A put credit spread sells the higher-strike put and buys the
lower-strike put. The absolute leg ratio is exactly `1:1`; both legs have the same expiry and
option type; the long leg is farther OTM. Quote state never changes `structure_id`.

### Policy identities

Underwriting and Position are separate immutable artifacts:

```text
underwriting_policy_identity = sha256:<64 lowercase hexadecimal characters>
position_policy_identity     = sha256:<64 lowercase hexadecimal characters>
```

Each Policy is one exact UTF-8 JSON object without a BOM. Duplicate keys, non-finite numbers,
unknown keys, missing keys, invalid units, and invalid relationships fail before any consumer can
become available. Numbers parse directly to exact decimal values. The process reads each file once,
verifies the expected digest, and uses only the immutable in-memory object.

One runtime binds one exact Policy pair. Hot reload, implicit defaults, automatic selection,
training, approval, promotion, or replacement are forbidden. A successor has a new digest and a
new forward interval; earlier objects retain their original identities.

A Candidate binds the Radar Policy, Underwriting Policy, and complete Position Policy identities.
No Candidate exists when either downstream Policy is missing.

The Policy pair is valid only when its fee-schedule objects are exactly equal after strict canonical parsing
and its downstream currentness deadlines are equal to each other. Each downstream index, ticker,
and queue-lag deadline must be less than or equal to the corresponding frozen Radar Policy
runtime limit. A downstream Policy may fail closed earlier but may never resurrect a fact that the
upstream public runtime already made unavailable.

## Underwriting Policy contract

The top-level object has exactly these members:

```yaml
policy_schema: SHORT_VOL_UNDERWRITING_POLICY
policy_family: PUBLIC_ATOMIC_DEFINED_RISK_VERTICAL
fee_schedule: exact object below
currentness: exact object below
path_risk: exact object below
reserves: exact object below
action_thresholds: exact object below
```

### Fee schedule object

```yaml
source: DERIBIT_PUBLIC_FEE_SCHEDULE
source_uri: https://support.deribit.com/hc/en-us/articles/25944746248989-Fees
source_observed_at_ms: non_negative_integer
valid_from_ms: non_negative_integer
valid_through_ms: integer_strictly_greater_than_valid_from_ms
account_assumption: DIRECT_STANDARD_ACCOUNT
execution_assumption: VISIBLE_ATOMIC_TAKER
option_trading_fee_rate_of_index: finite_positive_decimal
option_fee_cap_fraction_of_leg_premium: finite_positive_decimal_at_most_one
option_combo_discount: WAIVE_LOWER_DIRECTION_FEE_TOTAL
delivery_fee_rate_of_index: finite_non_negative_decimal
delivery_fee_cap_fraction_of_intrinsic: finite_non_negative_decimal_at_most_one
fee_discount_assumed: false
fee_balance_assumed: false
broker_or_sma_fee_assumed: false
expiry_future_offset_assumed: false
```

For the official standard USDC-linear-option schedule verified for this contract, the concrete
Policy values are:

```text
option_trading_fee_rate_of_index = 0.0003
option_fee_cap_fraction_of_leg_premium = 0.125
delivery_fee_rate_of_index = 0.00015
delivery_fee_cap_fraction_of_intrinsic = 0.125
```

`source_uri` is the literal official URL shown above. `source_observed_at_ms` must be no later
than the consuming Decision boundary and strictly earlier than `valid_through_ms`; it may follow
the schedule's effective start. `valid_from_ms` is the effective start of the selected official
schedule. `valid_through_ms` may not pass an already published successor-schedule boundary unless
every consumed standard-account option and delivery value remains identical across that boundary.

A future official schedule change requires a human-approved successor Policy identity with a new
validity interval. Runtime does not scrape or mutate the schedule. The trusted-time interval must
lie wholly inside the half-open interval `[valid_from_ms, valid_through_ms)`; otherwise Underwriting
is `UNKNOWN` and an already admitted Position has hard-close reason `FEE_SCHEDULE_INVALID`. No
pre-existing expiry
future, account fee discount, fee balance, affiliate discount, broker charge, or liquidation state
is assumed; those private/account effects may lower or alter actual charges but cannot lower this
public-only reserve.

### Currentness object

```yaml
index_source_stale_deadline_ms: positive_integer
ticker_source_stale_deadline_ms: positive_integer
notification_queue_lag_deadline_ms: positive_integer
```

Book currentness has no elapsed-mutation timeout. It is proved by acknowledged generation,
accepted snapshot, exact change continuity, current session/platform/lifecycle, and an uncrossed
valid book. Equality at every deadline remains current. The exact downstream currentness
predicates are:

```text
accepted_ticker_source_timestamp_ms
    <= trusted_time_upper_ms
    <= accepted_ticker_source_timestamp_ms + ticker_source_stale_deadline_ms

trusted_time_lower_ms - accepted_index_source_timestamp_ms
    <= index_source_stale_deadline_ms

processed_monotonic_ms - received_monotonic_ms
    <= notification_queue_lag_deadline_ms
```

A negative receive-to-process difference is invalid. An active queue-lag incident, upstream
currentness failure, retired generation, or source timestamp ahead of trusted time makes every
dependent downstream consumer `UNKNOWN`; a downstream deadline can fail earlier but cannot extend
or resurrect upstream usability.

### Path-risk object

```yaml
lookbacks_minutes: non_empty_unique_positive_integer_array
maximum_adverse_log_return: finite_positive_decimal
maximum_abs_short_delta: finite_decimal_in_open_closed_interval_0_1
maximum_short_gamma_per_usdc: finite_positive_decimal
maximum_short_mark_iv_percentage_points: finite_positive_decimal
minimum_vertical_mark_iv_spread_percentage_points: finite_decimal
path_reserve_multiplier: finite_non_negative_decimal
gamma_stress_move_fraction: finite_positive_decimal_at_most_one
```

The required index history is bounded to the largest declared lookback and is continuous known-at
history ending at or before the decision boundary. It is not a persisted market archive.

### Reserve object

Every floor is a finite non-negative USDC amount. Every width fraction is finite and non-negative.

```yaml
entry_friction_floor_usdc
entry_friction_fraction_of_width
close_friction_floor_usdc
close_friction_fraction_of_width
liquidity_floor_usdc
liquidity_fraction_of_width
path_jump_floor_usdc
path_jump_fraction_of_width
short_leg_tail_floor_usdc
short_leg_tail_fraction_of_width
model_uncertainty_floor_usdc
model_uncertainty_fraction_of_width
settlement_index_stress_ceiling_usdc_per_btc: finite_positive_decimal
```

The stress ceiling must be at least the current accepted BTC-USDC index price and both strikes.
Otherwise the evaluation is `UNKNOWN/SETTLEMENT_STRESS_BOUND_INSUFFICIENT`.

### Action-threshold object

```yaml
watch_minimum_margin_usdc: finite_decimal
candidate_minimum_margin_usdc: finite_decimal_not_less_than_watch_minimum_margin_usdc
candidate_minimum_net_credit_to_loss_ratio: finite_positive_decimal
maximum_policy_bounded_conservative_loss_usdc: finite_positive_decimal
```

No implementation constant may replace any numeric Policy member.

## Position Policy contract

The top-level object has exactly these members:

```yaml
policy_schema: SHORT_VOL_POSITION_POLICY
policy_family: PUBLIC_SHADOW_DEFINED_RISK_VERTICAL
fee_schedule: exact fee schedule object
currentness: exact currentness object
boundaries: exact object below
hard_risk_limits: exact object below
soft_close: exact object below
reserves: exact Position-reserve object below
```

The Position fee schedule must be semantically identical to the Underwriting fee schedule at
Candidate creation and Shadow admission. A mismatch is unavailable, not a selectable cheaper rate.

### Boundary object

```yaml
settlement_window_before_expiry_ms: 1800000
latest_exit_before_expiry_ms: integer_strictly_between_1800000_and_259200000
```

`latest_exit_before_expiry_ms` is a hard risk boundary. It is not an intended holding duration.

### Hard-risk object

```yaml
lookbacks_minutes: non_empty_unique_positive_integer_array
maximum_abs_short_delta: finite_decimal_in_open_closed_interval_0_1
maximum_short_gamma_per_usdc: finite_positive_decimal
maximum_short_mark_iv_percentage_points: finite_positive_decimal
maximum_adverse_mark_iv_change_percentage_points: finite_non_negative_decimal
minimum_vertical_mark_iv_spread_percentage_points: finite_decimal
maximum_adverse_log_return: finite_positive_decimal
gamma_stress_move_fraction: finite_positive_decimal_at_most_one
loss_close_fraction_of_policy_bounded_loss: finite_decimal_in_open_closed_interval_0_1
maximum_net_close_debit_usdc: finite_positive_decimal
```

### Soft-close object

```yaml
profit_capture_fraction_of_net_entry_credit: finite_decimal_in_open_closed_interval_0_1
minimum_position_hold_margin_usdc: finite_decimal
```

### Position-reserve object

```yaml
close_friction_floor_usdc: finite_non_negative_decimal
close_friction_fraction_of_width: finite_non_negative_decimal
liquidity_floor_usdc: finite_non_negative_decimal
liquidity_fraction_of_width: finite_non_negative_decimal
path_jump_floor_usdc: finite_non_negative_decimal
path_jump_fraction_of_width: finite_non_negative_decimal
path_reserve_multiplier: finite_non_negative_decimal
short_leg_tail_floor_usdc: finite_non_negative_decimal
short_leg_tail_fraction_of_width: finite_non_negative_decimal
model_uncertainty_floor_usdc: finite_non_negative_decimal
model_uncertainty_fraction_of_width: finite_non_negative_decimal
settlement_index_stress_ceiling_usdc_per_btc: finite_positive_decimal
```

The Position stress ceiling may exceed the Underwriting ceiling but may not be lower. No Position
Policy contains a fixed holding-period field. The Position Policy owns every threshold and reserve
used by `HOLD | CLOSE | UNKNOWN`; it does not silently reuse an Underwriting number merely because
the field has a similar name.

## Required public facts

Every required fact has a non-null state for an evaluable consumer. A value field may be null
only after complete current scope proves a declared known-negative short circuit, such as an
unexecutable full-quantity close; that branch produces the exact known action and does not enter
dependent arithmetic. Optional diagnostics are explicitly labeled and never affect an action.

Every fact consumed by a Decision, admission, or Position evaluation must have been committed at
or before that object's `FactBoundary`. Source timestamps describe exchange facts; reducer order
and receive time establish what the process knew. A later object may reuse an unchanged immutable
value only after the later boundary independently re-proves every owning continuity and
currentness predicate.

BTC-USDC linear options are European, quoted and settled in USDC. BTC contract size is one, so one
BTC option contract represents one BTC of underlying and a target `q` BTC is also `q` contracts.
Expiry is 08:00 UTC. The delivery price is the 30-minute BTC-USDC index TWAP leading into expiry;
only intrinsic value is settled. ITM options first settle into the expiry future at strike and that
future immediately settles into USDC, producing the same net cash result as direct cash settlement.
This contract treats the final 1,800,000 milliseconds as settlement-ineligible for a new Shadow
position and never calls a settlement fact a market fill.

| Fact | Exact public source | Unit | Current and complete when | Missing or invalid effect |
|---|---|---|---|---|
| active short-leg episode | current Radar reducer state under `SHORT_VOL_RADAR` | identities and enum | same runtime and Radar Policy; episode is `ANOMALY_ACTIVE`, not suspended or ended | Underwriting `NOT_EVALUATED`; Candidate invalid; after Entry a known terminal episode reason is evaluated by Position |
| trusted time | `public/get_time` plus monotonic advancement | integer millisecond interval | current clock generation, no gap, not stale | `UNKNOWN`; admitted Position hard-closes on known clock/source loss |
| BTC-USDC index | `deribit_price_index.btc_usdc` | USDC per BTC, integer source ms | acknowledged continuous generation and Policy deadline | `UNKNOWN`; Candidate invalid |
| option catalog and lifecycle | `public/get_instruments`, `public/get_instrument`, `instrument.state.option.USDC` | metadata; strike USDC/BTC; expiry ms; amount BTC | reconciled complete catalog; both legs active/open; contract size exactly one; quantity minimum/grid valid | incomplete is `UNKNOWN`; known ineligibility is `NOT_EVALUATED` or `ABSTAIN` as specified |
| combo catalog and lifecycle | `public/get_combos`, `public/get_instrument`, `instrument.state.option_combo.USDC` | signed leg ratios and BTC amount metadata | reconciled complete catalog; exact official combo active/open | incomplete is `UNKNOWN`; known absence is `NOT_EVALUATED` |
| entry combo book | `book.<combo>.100ms` | price USDC per BTC strategy unit; amount BTC | acknowledged snapshot/change continuity, current platform/session/lifecycle, full `q` on required side | incomplete is `UNKNOWN`; complete insufficient depth means no current opportunity |
| opposite-side close combo book | `book.<combo>.100ms` | price USDC per BTC strategy unit; amount BTC | same proof, opposite signed direction, full `q` | incomplete is `UNKNOWN`; complete insufficient depth is known `UNEXECUTABLE` and Underwriting `ABSTAIN` |
| component option books, diagnostic only | `book.<short>.100ms`, `book.<long>.100ms` | price USDC per BTC; amount BTC | both books independently continuous with full remaining quantity on buy-short ask and sell-long bid | absence does not change a known atomic state; it only prevents `LEGGED_CLOSE_REFERENCE` |
| short and long option tickers | `ticker.<instrument>.100ms` | forward and mark price USDC/BTC; mark IV percentage points; delta dimensionless; gamma inverse USDC; source ms | complete ticker snapshot, accepted generation, source timestamp inside Policy deadline | `UNKNOWN`; Candidate invalid |
| bounded path history | continuous BTC-USDC index closes | USDC/BTC and dimensionless log returns | every declared lookback is covered without a gap and known at the boundary | `UNKNOWN`; Candidate invalid |
| platform and public-method state | `platform_state`, `platform_state.public_methods_state`, `public/status`, heartbeat | enums and booleans | current bootstrap epoch proves no relevant lock/maintenance/public-method denial and live session | `UNKNOWN`; admitted Position hard-closes on known loss |
| fee schedule | exact downstream Policy bytes | rates and validity ms | Policy pair agrees and trusted time lies wholly inside validity interval | `UNKNOWN`; admitted Position hard-closes when invalid |

Ticker mark, IV, and Greeks are risk facts, not executable prices. A component option book may
create only a `LEGGED_CLOSE_REFERENCE`; it is not a substitute for an official combo. An old
`SHORT_VOL_ANOMALY_EVENT`, `PUBLIC_ATOMIC_QUOTE_EVENT`, run summary, or sealed evidence directory
proves only its historical boundary and cannot establish current Underwriting or admission.

A quiet combo book remains current when every continuity and lifecycle predicate remains true.
Heartbeats, elapsed time, or repeated serialization do not refresh its economic levels.

## Exact structure and entry economics

For target quantity `q` in BTC and short/long strikes in USDC per BTC:

```text
width_usdc = abs(short_strike_usdc_per_btc - long_strike_usdc_per_btc) × q
```

Require `q > 0`, `width_usdc > 0`, exact amount-grid eligibility, and contract size one.

Let `a_entry` be the signed official combo order amount that produces the target legs and
`p_entry` the required-side full-quantity VWAP:

```text
a_entry ∈ {+q, -q}
gross_entry_credit_usdc = -a_entry × p_entry
require 0 < gross_entry_credit_usdc < width_usdc
```

No absolute value is taken. Failure of the economic domain is
`UNKNOWN/ENTRY_QUOTE_OUTSIDE_DEFINED_RISK_DOMAIN`.

The opposite full-quantity closing order is:

```text
a_close = -a_entry
gross_close_debit_usdc = a_close × p_close
gross_close_debit_usdc must be finite
```

The field is a signed cash cost: a positive value is a debit and a negative value is a close
credit. An official full-quantity quote remains visible even when its signed cost lies outside the
vertical payoff width; Underwriting and Position risk limits decide whether to use it. A missing,
non-finite, or arithmetically unresolved value is
`UNKNOWN/CLOSE_QUOTE_OUTSIDE_NUMERIC_DOMAIN`, never a zero debit.

## Fee and reserve economics

### Public-only trading-fee reserve

Deribit calculates each USDC-linear-option leg fee from index price and leg option price, then
waives the lower total fee direction for a mixed buy/sell option combo. Public combo price does not
provide the private individual leg-price allocation required to apply each premium cap exactly.

Therefore public Shadow uses this explicit conservative upper bound for a one-buy/one-sell 1:1
combo under the frozen standard schedule:

```text
trading_fee_reserve_usdc(S, q) =
    option_trading_fee_rate_of_index × S × q

entry_trading_fee_reserve_usdc =
    trading_fee_reserve_usdc(current_index_usdc_per_btc, q)

close_trading_fee_reserve_usdc =
    trading_fee_reserve_usdc(current_index_usdc_per_btc, remaining_q)
```

The reserve deliberately does not claim an account's actual fee, discount, fee balance, broker
charge, maker status, or fill fee. Fee is never zero by default.

### Delivery-fee reserve

For hypothetical delivery index `S`, strike `K`, quantity `q`, and one option leg:

```text
call_intrinsic_usdc_per_btc = max(S - K, 0)
put_intrinsic_usdc_per_btc  = max(K - S, 0)

delivery_fee_leg_usdc =
    min(
        delivery_fee_rate_of_index × S,
        delivery_fee_cap_fraction_of_intrinsic × intrinsic_usdc_per_btc
    ) × q
```

The vertical reserve is the maximum sum of both leg fees over
`S ∈ [0, settlement_index_stress_ceiling_usdc_per_btc]`. The exact finite maximization evaluates
the interval endpoints, both strikes, and each in-range fee-cap switch:

```text
call switch = cap_fraction × K / (cap_fraction - delivery_rate)
put switch  = cap_fraction × K / (cap_fraction + delivery_rate)
```

The call switch is used only when `cap_fraction > delivery_rate`. Values outside the stress
interval are omitted. All arithmetic uses exact decimals.

Because call delivery fees can grow with an unbounded settlement index, this reserve is explicitly
`POLICY_BOUNDED`, not a global all-price fee bound.

### Friction and risk reserves

Risk projections use these exact current public definitions:

```text
abs_short_delta = abs(short_leg_ticker.delta)
short_gamma_per_usdc = abs(short_leg_ticker.gamma)
short_mark_iv_percentage_points = short_leg_ticker.mark_iv
vertical_mark_iv_spread_percentage_points =
    short_leg_ticker.mark_iv - long_leg_ticker.mark_iv
adverse_mark_iv_change_percentage_points =
    max(current_short_mark_iv - entry_short_mark_iv, 0)
```

Missing, non-finite, or source-stale ticker values are `UNKNOWN`; mark, IV, Delta, and gamma remain
risk references and never become executable prices.

For any pair `(floor_usdc, fraction_of_width)`:

```text
base_reserve = max(floor_usdc, fraction_of_width × width_usdc)
```

Define the adverse path return over the Policy lookbacks:

```text
call adverse return = max(ln(current_index / historical_index), 0)
put adverse return  = max(ln(historical_index / current_index), 0)
observed_maximum_adverse_log_return = maximum across declared lookbacks
```

Then:

```text
entry_friction_reserve =
    base_reserve(entry_friction_floor, entry_friction_fraction)

close_friction_reserve =
    base_reserve(close_friction_floor, close_friction_fraction)

gross_round_trip_friction =
    max(gross_close_debit_usdc - gross_entry_credit_usdc, 0)

liquidity_closeability_reserve =
    max(
        base_reserve(liquidity_floor, liquidity_fraction),
        gross_round_trip_friction
    )

path_jump_reserve =
    max(
        base_reserve(path_jump_floor, path_jump_fraction),
        width_usdc × path_reserve_multiplier × observed_maximum_adverse_log_return
    )

gamma_stress_move_usdc =
    current_index_usdc_per_btc × gamma_stress_move_fraction

short_leg_gamma_stress_loss =
    0.5 × short_gamma_per_usdc × gamma_stress_move_usdc² × q

short_leg_tail_reserve =
    max(
        base_reserve(short_leg_tail_floor, short_leg_tail_fraction),
        short_leg_gamma_stress_loss
    )

model_uncertainty_reserve =
    base_reserve(model_uncertainty_floor, model_uncertainty_fraction)

future_exit_cost_reserve =
    max(
        close_trading_fee_reserve_usdc + close_friction_reserve,
        settlement_delivery_fee_reserve_usdc
    )
```

The Position Policy applies the same formulas with its own current facts and its own reserve
members, yielding `position_liquidity_reserve`, `position_path_jump_reserve`,
`position_short_leg_tail_reserve`, `position_model_uncertainty_reserve`, and
`position_future_exit_cost_reserve`.

### Net reward and loss boundaries

```text
net_entry_credit_usdc =
    gross_entry_credit_usdc
    - entry_trading_fee_reserve_usdc
    - entry_friction_reserve

payoff_maximum_loss_usdc =
    width_usdc - gross_entry_credit_usdc

policy_bounded_conservative_maximum_loss_usdc =
    payoff_maximum_loss_usdc
    + entry_trading_fee_reserve_usdc
    + entry_friction_reserve
    + future_exit_cost_reserve

required_compensation_usdc =
    liquidity_closeability_reserve
    + path_jump_reserve
    + short_leg_tail_reserve
    + model_uncertainty_reserve
    + future_exit_cost_reserve

underwriting_margin_usdc =
    net_entry_credit_usdc - required_compensation_usdc

net_credit_to_loss_ratio =
    net_entry_credit_usdc / policy_bounded_conservative_maximum_loss_usdc
```

The ratio is defined only when the denominator is positive. Non-finite arithmetic, an insufficient
stress bound, missing risk facts, or an interval spanning a threshold is `UNKNOWN`, never an
economic action.

## Underwriting truth model

```text
underwriting_availability =
    NOT_EVALUATED | UNKNOWN | EVALUABLE

underwriting_action =
    null | CANDIDATE | WATCH | ABSTAIN
```

| Availability | Exact condition | Action |
|---|---|---|
| `NOT_EVALUATED` | no current active episode; or no current positive official full-target atomic entry quote; or complete current facts prove no matching active combo | `null` |
| `UNKNOWN` | an anomaly is active and opportunity existence or economics cannot be resolved because any required fact, identity, currentness, completeness, fee validity, numerical classification, or economic domain is unresolved | `null` |
| `EVALUABLE` | every required fact and both Policy identities are complete, current, valid, and known | exactly one economic action |

Known complete absence of a full-quantity atomic close quote is an evaluable closeability veto and
produces `ABSTAIN`. Incomplete or discontinuous close-quote evidence is `UNKNOWN`.

For an `EVALUABLE` opportunity, apply this total action order:

1. `ABSTAIN` if any known strategy veto holds:
   - latest-exit boundary is already reached;
   - current `close_quote_state` is `LEGGED_CLOSE_REFERENCE | UNEXECUTABLE`;
   - `observed_maximum_adverse_log_return > path_risk.maximum_adverse_log_return`;
   - `abs_short_delta > path_risk.maximum_abs_short_delta`;
   - `short_gamma_per_usdc > path_risk.maximum_short_gamma_per_usdc`;
   - short mark IV exceeds `path_risk.maximum_short_mark_iv_percentage_points`;
   - vertical mark-IV spread is below
     `path_risk.minimum_vertical_mark_iv_spread_percentage_points`;
   - `policy_bounded_conservative_maximum_loss_usdc` exceeds the Policy maximum;
   - `net_entry_credit_usdc <= 0`.
2. Otherwise `CANDIDATE` when:
   - `underwriting_margin_usdc >= candidate_minimum_margin_usdc`; and
   - `net_credit_to_loss_ratio >= candidate_minimum_net_credit_to_loss_ratio`.
3. Otherwise `WATCH` when
   `underwriting_margin_usdc >= watch_minimum_margin_usdc`.
4. Otherwise `ABSTAIN`.

`WATCH` is a known evaluated intermediate result. `ABSTAIN` is a known economic rejection.
Neither may absorb `UNKNOWN`.

## Underwriting Decision and Candidate identity

A `SHORT_VOL_UNDERWRITING_DECISION` is created only for a current positive official entry-quote
opportunity and only when its settled consumed-fact identity changes. Such a Decision may be
`UNKNOWN` when later required risk, closeability, fee, or numerical facts are unresolved. When the
positive entry opportunity itself is not proven, `NOT_EVALUATED | UNKNOWN` remains query-only
availability with no Decision or economic denominator. Messages, duplicate snapshots, unconsumed
depth, heartbeats, and unchanged reduced state do not create another Decision.

```text
decision_id =
    runtime_identity
    × radar_policy_identity
    × underwriting_policy_identity
    × position_policy_identity
    × episode_id
    × structure_id
    × decision_fact_boundary
    × canonical consumed-fact identity
```

When `underwriting_action = CANDIDATE`, `candidate_id = decision_id`. Candidate additionally freezes:

- every Policy and runtime identity;
- the active episode and its current detector causal binding;
- canonical combo, legs, direction, expiry, option type, and target quantity;
- trusted-time interval for audit and discrete TTE/latest-exit/fee-validity classifications for causal validity;
- entry and opposite-close consumed levels and book generations;
- index, path, ticker, Delta, gamma, mark-IV, and fee-schedule facts;
- every calculated fee, reserve, reward, loss, margin, and threshold result.

### Candidate validity

Candidate validity has no arbitrary elapsed-time limit. It remains valid only while all of these
facts continue to hold:

1. same runtime, session epoch, continuity epoch, and Policy identities;
2. same active, unsuspended Radar episode and short-leg causal binding;
3. same complete option/combo identities, lifecycle, metadata, amount grid, and target quantity;
4. same current entry and close consumed economic levels for the target quantity;
5. same required index, path, ticker, Greek, surface, and fee-schedule consumed-fact identity, plus the same discrete TTE/latest-exit/fee-validity classifications;
6. platform, public methods, clock, catalogs, subscriptions, and books remain usable;
7. trusted time remains strictly before the Position latest-exit boundary;
8. a full re-evaluation under the same Policy pair still returns `CANDIDATE`.

Any changed consumed economic or risk fact ends the original Candidate as
`SUPERSEDED_BY_REUNDERWRITING`; a complete new evaluation may create a new Candidate. A missing,
stale, discontinuous, invalid, or contaminated required fact ends it as `INVALIDATED_UNKNOWN`.
Episode end, identity/lifecycle/quantity loss, latest-exit crossing, fee-schedule invalidity, or a
known non-Candidate result ends it with its exact reason.

Unrelated messages, duplicate reduced state, ask/depth changes beyond consumed target levels, and
continuous clock movement wholly inside the same discrete TTE/latest-exit/fee-validity classes do
not invalidate Candidate. The recorded trusted-time interval remains audit evidence, not a lease.
No historical event or wall-clock timer can keep Candidate valid.

## Shadow admission

Shadow admission is a deterministic gate, not a third Policy. It has no configurable threshold,
maker choice, quote-age duration, or legging behavior. A future maker, RFQ, legged, or configurable
admission method requires a separate authorized Policy and task.

`SHADOW_ENTRY` requires:

1. a still-valid Candidate;
2. an admission `FactBoundary` strictly later than the Candidate boundary in the same session and
   continuity epoch;
3. a fresh settlement of every Candidate-validity predicate at that later boundary;
4. a new full-quantity walk of the same official combo, same required entry direction, and same
   target quantity from the current book state;
5. the same non-time consumed economic and risk-fact identity frozen by Candidate, with the same
   discrete TTE/latest-exit/fee-validity classifications.

An admission boundary must be a reducer-owned currentness/economic transaction caused by an
accepted public market fact or an accepted `public/get_time` response that settles every admission
consumer. A heartbeat, local timer tick, duplicate with no settled currentness effect, report
write, or repeated serialization cannot be the admission boundary.

The admission proof may consume an unchanged economic revision when the official book has remained
quiet but continuously usable. The later boundary re-proves acknowledgement, snapshot/change
continuity, platform, lifecycle, catalog completeness, amount eligibility, Candidate guards, and
full-quantity depth. It may not copy the pre-Candidate `PUBLIC_ATOMIC_QUOTE_EVENT` or Decision
projection.

If any consumed fact changed, the original Candidate is invalid and must be fully re-underwritten.
If any proof is unavailable, admission is `UNKNOWN` and no Entry exists. Complete known failure is
`REJECTED`. Neither result is an order or fill.

`SHADOW_ENTRY` freezes the Candidate, admission boundary, exact current quote levels, gross credit,
fee reserve, net credit, structure, quantity, and three Policy identities. It starts strictly
future public observation and creates no actual exposure.

## Position state

### Remaining quantity

For public Shadow:

```text
shadow_remaining_quantity_btc = entry_target_quantity_btc
```

It remains constant for this contract. A public quote or close opportunity never decrements it,
ends Shadow duration, or proves settlement. Actual partial quantities require future fill authority.

### Current close economics

At a current full-remaining-quantity atomic close quote:

```text
current_net_close_debit_usdc =
    gross_close_debit_usdc
    + close_trading_fee_reserve_usdc
    + close_friction_reserve

remaining_net_premium_usdc = current_net_close_debit_usdc

counterfactual_close_margin_usdc =
    shadow_entry_net_credit_usdc - current_net_close_debit_usdc

counterfactual_loss_usdc =
    max(current_net_close_debit_usdc - shadow_entry_net_credit_usdc, 0)

position_required_compensation_usdc =
    position_liquidity_reserve
    + position_path_jump_reserve
    + position_short_leg_tail_reserve
    + position_model_uncertainty_reserve
    + position_future_exit_cost_reserve

position_hold_margin_usdc =
    remaining_net_premium_usdc - position_required_compensation_usdc
```

These are current counterfactual economics, not Outcome or realized PnL. They are evaluated only
from complete current facts; an unavailable atomic close quote cannot be silently assigned a zero
remaining premium.

### Close quote state

```text
close_quote_state =
    ATOMIC_COMBO_CLOSE_QUOTE
    | LEGGED_CLOSE_REFERENCE
    | UNEXECUTABLE
    | UNKNOWN
```

Classification order is exact:

1. `ATOMIC_COMBO_CLOSE_QUOTE` when a current official same-combo opposite-direction quote covers
   the full Shadow remaining quantity.
2. `UNKNOWN` when any atomic catalog, lifecycle, platform, subscription, book, quantity, or
   currentness prerequisite is missing, invalid, stale, or discontinuous. A legged reference may
   not overwrite atomic uncertainty.
3. `LEGGED_CLOSE_REFERENCE` when atomic prerequisites are complete and prove no full-quantity
   atomic quote, while both component books independently support the full remaining quantity.
4. `UNEXECUTABLE` when atomic prerequisites are complete and prove no full-quantity atomic quote
   and no complete legged reference, or settlement lifecycle makes trading unavailable.

For a legged diagnostic, buy back the short leg from asks and sell the long leg into bids:

```text
gross_legged_close_reference_usdc =
    short_leg_full_quantity_ask_vwap_usdc_per_btc × remaining_q
    - long_leg_full_quantity_bid_vwap_usdc_per_btc × remaining_q
```

This non-simultaneous value has no authorized net-close calculation, fee claim, close opportunity,
or PnL meaning. Atomic takes precedence over a legged reference. A legged reference never creates
a close opportunity.

## Position action and hard-close total order

```text
position_action = HOLD | CLOSE | UNKNOWN
```

At every new position-consumed fact identity, evaluate all known hard-close predicates. Record every
matching reason in the exact order below and use the first as `primary_close_reason`:

1. `EXPIRY_OR_FINAL_SETTLEMENT_WINDOW`
2. `LATEST_EXIT_BOUNDARY`
3. `PLATFORM_NOT_USABLE`
4. `SOURCE_CONTINUITY_LOST`
5. `STRUCTURE_OR_REMAINING_QUANTITY_INVALID`
6. `RADAR_THESIS_ENDED`
7. `SETTLEMENT_STRESS_BOUND_INSUFFICIENT`
8. `FEE_SCHEDULE_INVALID`
9. `SHORT_STRIKE_BREACH`
10. `POLICY_BOUNDED_LOSS_LIMIT`
11. `PATH_JUMP_LIMIT`
12. `SHORT_LEG_DELTA_OR_GAMMA_LIMIT`
13. `VOLATILITY_SURFACE_LIMIT`
14. `ATOMIC_CLOSE_NOT_EXECUTABLE`

Exact predicates:

- final settlement: `expiry_ms - trusted_time_upper_ms <= 1_800_000`, or lifecycle is
  `settlement | delivered | inactive | archivized`;
- latest exit:
  `expiry_ms - trusted_time_upper_ms <= latest_exit_before_expiry_ms`;
- platform not usable: maintenance, relevant lock, public-method denial, dead/retired session, or
  unresolved bootstrap;
- source continuity lost: clock, index, ticker, catalog, ingress, or relevant book continuity loss;
- structure/quantity invalid: identity, leg, expiry/type, lifecycle, amount minimum/grid, or
  remaining-quantity invariant fails;
- Radar thesis ended: the owning episode ends by `CLEAR | KNOWN_INELIGIBLE |
  OUT_OF_BASELINE_SCOPE | MEMBERSHIP_LOSS`; a suspended episode without a terminal reason instead
  makes the dependent soft thesis fact unavailable, while `UNKNOWN_AT_GAP | UNKNOWN_DETECTOR` is
  owned by the applicable source/required-fact unavailable rule;
- settlement stress bound insufficient: current index or either strike exceeds the Position
  Policy settlement-index stress ceiling, or the required finite maximization cannot be proven;
- fee schedule invalid: Policy pair differs or trusted time is outside the frozen validity interval;
- short-strike breach: a call has current index at or above the short strike, or a put has current
  index at or below the short strike;
- bounded loss:
  `counterfactual_loss_usdc >=
   loss_close_fraction_of_policy_bounded_loss
   × entry_policy_bounded_conservative_maximum_loss_usdc`,
  or current net close debit exceeds its absolute Policy limit;
- path jump: observed maximum adverse log return exceeds
  `hard_risk_limits.maximum_adverse_log_return`;
- Delta/gamma: absolute short Delta or short gamma exceeds its respective hard-risk maximum;
- surface: short mark IV or adverse mark-IV change exceeds its respective Position maximum, or
  vertical mark-IV spread is below
  `hard_risk_limits.minimum_vertical_mark_iv_spread_percentage_points`;
- atomic close not executable: complete current truth gives `close_quote_state =
  LEGGED_CLOSE_REFERENCE | UNEXECUTABLE`; component legs remain diagnostic only.

Truth table:

| Hard close known? | Required soft facts complete? | Soft close predicate? | Action |
|---|---|---|---|
| yes | either | either | `CLOSE` |
| no | no | unavailable | `UNKNOWN` |
| no | yes | yes | `CLOSE` |
| no | yes | no | `HOLD` |

A known hard close has priority over missing soft-risk facts and
`close_quote_state = UNKNOWN | UNEXECUTABLE`. Missing quote evidence cannot erase an obligation to
close. `CLOSE` is an instruction, not a closing fact.

When no hard close exists, soft close is known when either:

```text
counterfactual_close_margin_usdc / shadow_entry_net_credit_usdc
    >= profit_capture_fraction_of_net_entry_credit
```

or `position_hold_margin_usdc` is below `minimum_position_hold_margin_usdc`. Division requires
positive entry net credit. Otherwise complete known facts yield `HOLD`.

There is no planned holding time, elapsed-time close, or fixed-horizon Outcome.

## Shadow close opportunity

A `SHADOW_CLOSE_OPPORTUNITY` exists only when:

1. a durable Position action is `CLOSE`;
2. the quote boundary is strictly later than both `SHADOW_ENTRY` and the owning `CLOSE` action;
3. `close_quote_state = ATOMIC_COMBO_CLOSE_QUOTE`;
4. the same official combo in the opposite direction covers the complete unchanged Shadow
   remaining quantity;
5. current platform, lifecycle, metadata, quantity, fee, and continuity proofs are usable.

The object freezes the Entry and Position-action identities, quote boundary, official combo,
direction, full quantity, consumed levels, gross close debit, fee reserve, friction reserve, and
current net close debit. A quiet continuous combo book may retain unchanged economic levels, but
the strictly later quote boundary must independently re-prove every atomic currentness predicate;
a heartbeat, local timer, or repeated projection is not that proof.

At most one object is emitted for
`(shadow_entry_id, position_close_action_id, combo_instrument_name)`. Quote flicker or repeated
unchanged levels do not multiply it. A later materially different close action may have its own
opportunity.

A close opportunity is not a fill, does not reduce remaining quantity, does not end Shadow
observation, and does not create PnL or Outcome.

## Future durable object meanings

This contract freezes semantics but creates no current writer.

### `SHORT_VOL_UNDERWRITING_DECISION`

Required identity and facts:

- code/runtime and all three Policy identities;
- episode, structure, Decision boundary, and canonical consumed-fact identity;
- availability and nullable action with exact reasons;
- all required source identities, units, currentness, and completeness;
- entry/close quote facts and every economic calculation;
- explicit `PUBLIC_QUOTES_NOT_FILLS` and `NO_EDGE_OR_PROFITABILITY_CLAIM`.

### Candidate

Candidate is the Decision whose action is `CANDIDATE`; `candidate_id = decision_id`. Its validity
transitions are separate from the economic action.

### `SHORT_VOL_CANDIDATE_LIFECYCLE_EVENT`

Written once for each terminal Candidate transition. It freezes Candidate identity, terminal
boundary, and exactly one reason from `SUPERSEDED_BY_REUNDERWRITING | INVALIDATED_UNKNOWN |
EPISODE_ENDED | IDENTITY_OR_LIFECYCLE_LOSS | LATEST_EXIT_REACHED | FEE_SCHEDULE_INVALID |
KNOWN_NON_CANDIDATE`. It is not another Underwriting action.

### `SHORT_VOL_SHADOW_ADMISSION_DECISION`

Written for each distinct still-valid Candidate and later admission-proof identity. It freezes the
Candidate, later boundary, re-proved currentness and full-quantity walk, and exactly one result:
`ADMITTED | REJECTED | UNKNOWN`. Only `ADMITTED` creates `SHADOW_ENTRY`; the public quote remains
not a fill.

### `SHADOW_ENTRY`

Required identity and facts:

- Candidate identity and admission boundary;
- structure and three Policy identities;
- refreshed official quote, full quantity, consumed levels, gross/net entry economics;
- `COUNTERFACTUAL_NOT_ORDER_OR_FILL` and `NO_ACTUAL_EXPOSURE`.

### `SHORT_VOL_POSITION_ACTION`

Required identity and facts:

- Shadow Entry and Position Policy identity;
- current boundary and unchanged remaining quantity;
- `HOLD | CLOSE | UNKNOWN`, every ordered reason, and nullable primary reason;
- independent close quote state and current counterfactual economics;
- no actual exposure or fill claim.

### `SHADOW_CLOSE_OPPORTUNITY`

Required identity and facts are defined above. It never represents a fill.

A missing admission creates no Position or Outcome object. It is not an `UNKNOWN Outcome`.

## Business denominators

Every count uses reduced business identities, never messages, files, elapsed time, repeated quotes,
legs, theoretical structures, or schema checks.

| Metric | Numerator | Denominator and conditioning | Unit/scope | Zero or unknown |
|---|---|---|---|---|
| Underwriting opportunity count | distinct current `episode_id × structure_id` opportunities | active episode plus positive official entry quote | opportunity, grouped by Policy pair/option type/TTE band | known zero requires complete relevant atomic scope |
| Underwriting evaluation count | new Decision consumed-fact identities | opportunities whose relevant state changed | Decision | duplicates excluded |
| Underwriting evaluable count | Decisions with `EVALUABLE` | all Decision evaluations | Decision | missing facts remain separate `UNKNOWN` Decision count |
| Underwriting unknown Decision count | Decisions with `UNKNOWN` | all Decision evaluations | Decision | query-only pre-opportunity `UNKNOWN` is reported separately and has no economic denominator |
| Candidate/Watch/Abstain count | evaluable Decisions by exact action | `underwriting_evaluable_count` | Decision | action rate is `null` when denominator is zero or unknown |
| Candidate count | Decisions with `CANDIDATE` | `underwriting_evaluable_count` | Candidate | numeric zero requires a positive complete evaluable denominator |
| Admission evaluation count | distinct `SHORT_VOL_SHADOW_ADMISSION_DECISION` identities | still-valid Candidates considered at a later qualifying boundary | admission evaluation | `UNKNOWN` separate |
| Shadow Entry count | admission Decisions with `ADMITTED` | admission Decisions with `ADMITTED | REJECTED`; `UNKNOWN` excluded | Entry | rate `null` when denominator is zero or unknown |
| Position evaluation count | new Entry plus Position consumed-fact identities | active Shadow Entries | Position evaluation | duplicates excluded |
| Hold/Close count | known Position actions | Position evaluations with action `HOLD` or `CLOSE` | action | `UNKNOWN` excluded from economic action denominator |
| Position unknown count | Position action `UNKNOWN` | all Position evaluations | action | never contributes zero to Hold/Close |
| Close quote-state count | evaluations by exact quote state | Position evaluations, reported separately from action | quote-state transition | no fill inference |
| Close-opportunity count | distinct allowed close-opportunity identity | known `CLOSE` actions with a strictly later quote evaluation | opportunity | known zero requires complete later quote scope |

Every rate serializes `null` when its denominator is zero or unknown. `UNKNOWN` never becomes
`ABSTAIN`, zero, calm, or an economic contribution.

## Compatibility and evidence boundary

Existing `SHORT_VOL_ANOMALY_EVENT`, `PUBLIC_ATOMIC_QUOTE_EVENT`, `RADAR_RUN_SUMMARY`, current
writer/reader, and sealed readers remain `COMPATIBLE` as unchanged upstream evidence. They do not
become downstream Decisions or Entries. No migration, replay, recomputation, relabeling, full-market
archive, or historical backfill is authorized.

Direct tests are sufficient to implement and falsify formulas, state transitions, Policy
validation, Candidate invalidation, admission order, hard-close priority, quote-state separation,
and denominator/null behavior. Production-public occurrence, Shadow forward Outcome,
qualification, and execution evidence are not required to freeze this contract.

This contract proves no edge, Candidate quality, maker feasibility, account fee, margin,
closeability in an unobserved market, Outcome, PnL, qualification, promotion, fill, or execution
permission.

## Implementation boundary

A later separately activated task may introduce the smallest deterministic pure-domain
implementation and direct tests. It must not combine that first implementation with a forward
cohort, persistent deployment, private/account methods, orders, fills, capital, qualification, or
execution.

No current package, CLI, schema writer, service, or live command is created by this contract.

## Official public-source basis

The mechanics frozen here are based on:

- [Deribit fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees)
- [Deribit combo books](https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books)
- [Deribit option combo orders](https://support.deribit.com/hc/en-us/articles/25944794271261-Option-Combo-Order)
- [Deribit linear USDC options](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options)
- [Deribit option ticker](https://docs.deribit.com/subscriptions/market-data/tickerinstrument_nameinterval)
- [Deribit order-book subscription](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval)
- [Deribit instrument metadata](https://docs.deribit.com/api-reference/market-data/public-get_instrument)
- [Deribit private leg-price allocation](https://docs.deribit.com/api-reference/combo-books/private-get_leg_prices)

The private `private/get_leg_prices` method is cited only to establish why exact per-leg
premium-cap allocation is not a public-only fact. This contract does not authorize calling it.
