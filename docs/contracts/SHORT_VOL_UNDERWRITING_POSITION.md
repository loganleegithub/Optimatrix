# Short Vol Underwriting and Shadow Position Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning product boundary:** `SHORT_VOL_UNDERWRITING_SHADOW_POSITION`

**Current implementation state:** `CONTRACT_FROZEN_RUNTIME_NOT_IMPLEMENTED`

## Purpose

This contract owns the first downstream business boundary after
[`SHORT_VOL_RADAR`](SHORT_VOL_RADAR.md). It freezes:

- production-public Underwriting availability and economic action;
- immutable Underwriting and Position Policy identities;
- Candidate identity, validity, invalidation, and one-shot admission;
- public-only entry and close economics, fee reserves, and defined-risk loss measures;
- post-entry Position action and a total hard-close order;
- close-quote classification and strictly later `SHADOW_CLOSE_OPPORTUNITY`; and
- exact business denominators, zero, `null`, and `UNKNOWN` meaning.

It is implementation-ready authority. It is not evidence that a runtime exists or that a
Candidate, `SHADOW_ENTRY`, Position action, close opportunity, Outcome, order, fill, exposure,
edge, or profit has occurred.

## Authority and current permission

[`PRODUCT_CONSTITUTION`](../authority/PRODUCT_CONSTITUTION.md) owns product meaning,
[`CURRENT_STAGE`](../authority/CURRENT_STAGE.md) owns permission,
[`SYSTEM_ARCHITECTURE`](../authority/SYSTEM_ARCHITECTURE.md) owns dependency direction, and
[`DELIVERY_CONTRACT`](../authority/DELIVERY_CONTRACT.md) owns evidence and delivery.

This contract does not change the accepted Radar runtime, its Policy, its events, its evidence, or
its `ESTABLISHED` record. It grants no runtime implementation or live command by itself.
`PUBLIC_SHADOW` still forbids private/account APIs, credentials, balances, margin, orders, fills,
settlement acts, capital, and money.

## Upstream compatibility and boundary

The upstream Radar remains the sole owner of:

- `detector_state = UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE`;
- anomaly episode identity and active/paused/ended state;
- official 1:1 protective vertical matching;
- `public_atomic_quote_state`; and
- `SHORT_VOL_ANOMALY_EVENT`, `PUBLIC_ATOMIC_QUOTE_EVENT`, and `RADAR_RUN_SUMMARY`.

`PUBLIC_ATOMIC_QUOTE_EVENT` is a historical first-observed fact. It cannot prove a current
Candidate or refresh an admission. Existing Radar objects and sealed readers remain compatible and
are never migrated, replayed, recalculated, or relabelled.

The downstream lifecycle is:

```text
current active Radar episode + current full-quantity official atomic quote
→ Underwriting availability
→ CANDIDATE | WATCH | ABSTAIN, only when evaluable
→ still-valid Candidate + post-Candidate official atomic refresh
→ SHADOW_ENTRY
→ strictly later public facts
→ HOLD | CLOSE | UNKNOWN
→ latched CLOSE + strictly later full-remaining-quantity official atomic quote
→ SHADOW_CLOSE_OPPORTUNITY
```

An anomaly is not a Candidate. A public quote is not a fill. `SHADOW_ENTRY` creates no exposure.
A close opportunity does not close a Shadow position or create PnL or Outcome.

## Exact units and arithmetic

All numeric inputs must be finite. Decimal market and Policy values are parsed as exact decimal
values, not binary floating-point approximations.

| Name | Unit and meaning |
|---|---|
| `q` | positive target and remaining base quantity in BTC |
| `signed_order_amount_btc` | `+q` for combo `BUY`, `-q` for combo `SELL` |
| strike, index, option price, combo price | USDC per BTC |
| `contract_size` | exactly `1` for this contract |
| fee, reserve, credit, debit, loss, PnL | USDC |
| timestamps | Unix milliseconds |
| Delta | dimensionless signed ratio |
| implied volatility and returns | dimensionless fractions |

The entry leg vector remains the Radar contract's exact same-expiry 1:1 protective credit
vertical. `q` must align with every applicable official amount minimum and step. No rounding is
permitted. A component leg, mark, mid, theoretical price, RFQ, or imagined maker price can never
create entry or close economics.

Decision arithmetic uses arbitrary-precision base-10 decimals. Addition and multiplication are
exact and no decision input or intermediate is quantized or rounded. A consumed order-book side
uses exact per-level `price × consumed_amount` products, with the final level consumed only up to
the exact remaining `q`. Decision predicates never divide:

- minimum-credit ratio compares
  `net_entry_credit_usdc < minimum_fraction × payoff_cap_usdc`;
- path/jump compares
  `abs(current_index - anchor_index) >= return_limit × anchor_index`; and
- remaining-premium compares
  `net_close_debit_usdc <= maximum_fraction × net_entry_credit_usdc`.

All denominators above must already be strictly positive. A display ratio or VWAP is
non-authoritative and, if serialized, carries its exact numerator and denominator; presentation
rounding cannot affect a state or identity.

## Known-at and causal order

### `FactBoundary`

Every downstream evaluation binds one immutable:

```text
FactBoundary =
    code_identity
    × runtime_identity
    × session_epoch
    × ingress_seq
    × received_monotonic_ms
    × causal_seq
```

Within one runtime, business order is the strict order of `causal_seq`. Source timestamps describe
the exchange fact but do not replace local known-at order. An object from another runtime cannot
continue the Candidate, entry, or Position lifecycle. A later boundary means a strictly greater
`causal_seq` in the same runtime.

The reducer first settles all effects of one accepted ingress event and then exposes one immutable
snapshot. Underwriting, admission, Position, and quote evaluation consume only such settled
snapshots. Heartbeats, arbitrary polling ticks, repeated bytes, schema checks, and unchanged
recomputation do not create a new economic identity.

A precomputed admission-cutoff, latest-exit, or expiry wakeup is not an arbitrary timer. At the
first local monotonic instant when extrapolating the accepted trusted-market-time interval changes
one declared discrete classification, the runtime commits exactly one time-boundary fact and
settles the affected Candidate or Position. The interval advances with the Radar contract's exact
monotonic drift and outward-rounding rules. If its source age is inside
`clock_currentness_budget_ms`, the changed cutoff predicate is known; otherwise the fact changes
clock currentness to `UNKNOWN`. Repeated wakeups in the same classification create no identity.
Thus a quiet market still invalidates a Candidate at admission cutoff and evaluates latest-exit
and expiry hard close; wall-clock time and heartbeat time never substitute for trusted market
time.

### Currentness and completeness

Every Policy contains exact positive request/send/receipt or source-age budgets for the source
families that have those semantics. Underwriting availability, Candidate, and admission use only
the Underwriting Policy budgets; every strictly post-entry Position, close-quote, and opportunity
evaluation uses only the Position Policy budgets. The two Policy values may differ and are never
silently minimized, maximized, or substituted.

Currentness comparisons are inclusive and exact:

- trusted clock is current iff
  `0 <= boundary.received_monotonic_ms - last_time_response_received_monotonic_ms <=
  clock_currentness_budget_ms`; its interval advances under the Radar drift rule before testing;
- platform/connection state is current iff its current session is explicitly operational and
  `0 <= boundary.received_monotonic_ms -
  last_platform_continuity_received_monotonic_ms <= platform_currentness_budget_ms`;
- an already shape-valid index fact is current iff
  `index.source_timestamp_ms <= trusted_time.upper_ms <=
  index.source_timestamp_ms + index_currentness_budget_ms`; and
- an already shape-valid short-leg ticker is current iff
  `ticker.source_timestamp_ms <= trusted_time.upper_ms <=
  ticker.source_timestamp_ms + option_ticker_currentness_budget_ms`.

An index/ticker candidate ahead of `trusted_time.upper_ms` is `AHEAD_IGNORED` and cannot overwrite
the current accepted fact. Crossing above a right-hand deadline makes that fact stale; equality
remains current. Catalog state instead must belong to the current accepted authoritative
generation and has no mutation-age TTL.

Streaming option and combo books are different: an acknowledged generation, accepted snapshot,
unbroken `prev_change_id → change_id` chain, usable connection, and operational platform keep a
quiet unchanged book current. Last-mutation age is diagnostic only and never expires the book.
`combo_snapshot_send_budget_ms` bounds the downstream RPC from `SCHEDULED` to successful `SENT`;
`combo_snapshot_response_budget_ms` bounds it from `SENT` through local response receipt. The
inclusive inequalities are
`request_SENT_monotonic_ms - request_scheduled_monotonic_ms <=
combo_snapshot_send_budget_ms` and
`response_received_monotonic_ms - request_SENT_monotonic_ms <=
combo_snapshot_response_budget_ms`. These budgets apply only to the downstream admission or
post-CLOSE `public/get_order_book` request; they do not amend Radar bootstrap, initial
subscription, or resync authority and are not quote-mutation TTLs. Quiet currentness alone is not
an admission refresh.

For clock/index/ticker freshness, the runtime precomputes the first conservative local-monotonic
crossing under the trusted-time drift rule; platform receipt-age uses its direct monotonic
deadline. RPC deadlines are direct
`scheduled_monotonic_ms + combo_snapshot_send_budget_ms` and
`SENT_monotonic_ms + combo_snapshot_response_budget_ms`, independent of trusted-clock
availability. Each one-time deadline control re-enters the unified application queue and commits
one changed-fact `FactBoundary`; no arbitrary poll creates identity. A late `SENT`/response is
ignored after the terminal deadline disposition.

Completeness means every required member, catalog relationship, subscription generation, snapshot
and change chain, amount rule, and target-side level needed by the evaluation is known and valid.
Missing, stale, gapped, malformed, contradictory, out-of-generation, or contaminated input is
`UNKNOWN`; it never defaults to zero or calm.

## Required production-public facts

The exact source, unit, known-at rule, completeness rule, nullability, and invalidation effect are
frozen below.

| Fact | Official public source and unit | Known-at and currentness | Complete/nullable | Invalidation |
|---|---|---|---|---|
| trusted market-time interval | Deribit server time reconciled with local monotonic receipt; Unix ms lower/upper | settled boundary; Policy clock budget | both integer bounds and `lower_ms <= upper_ms` required; otherwise `UNKNOWN` | invalidates Candidate; makes time predicates `UNKNOWN` unless another known close predicate is true |
| platform and connection state | public status, heartbeat controls, connection and sequence controls | settled reducer state for the current session epoch | operational/degraded/gapped/stopped is explicit; missing is `UNKNOWN` | pause/end/gap invalidates Candidate; a known post-entry discontinuity is a close predicate |
| Radar episode | current `ANOMALY_ACTIVE` episode, Radar Policy identity, short leg, target `q` | same settled boundary as Underwriting | active and complete required; paused/ended is not active | any pause, end, identity or scope change invalidates Candidate; entry remains independent afterward |
| option instrument metadata | `public/get_instrument` for both legs: `state`, `is_active`, kind, currency, settlement currency, strike, expiry, option type, `contract_size`, amount minimum/step, and dimensionless nonnegative `taker_commission` as an index-price fraction | current accepted catalog generation; a quiet current generation has no age TTL | both legs must have `state = open`, `is_active = true`, be BTC-USDC linear options with same expiry/type and exact 1:1 protective orientation; a known structural/lifecycle mismatch is known ineligible, while missing/malformed metadata or missing/above-reserve public commission is `UNKNOWN` | any change/unknown invalidates Candidate; after entry it feeds lifecycle, fee compatibility, and close predicates |
| authoritative active-combo catalog | the current Radar/source-owner DTO from race-free `public/get_combos` USDC bootstrap plus `instrument.state.option_combo.USDC` dirty/reconcile; exact combo id and signed official legs | current complete accepted catalog generation; a quiet current generation has no age TTL | exact canonical-leg match present means an active combo; complete absence proves known no active combo; a single-id details error/absence proves nothing; missing, malformed, dirty, or unreconciled catalog is `UNKNOWN` | known absence prevents evaluation; change/end/unknown invalidates Candidate; runtime composition keeps the same owner alive after entry for close classification |
| combo instrument metadata | `public/get_instrument` for a combo present in the active catalog: `kind`, seven-state lifecycle `state`, `is_active`, instrument identity, amount minimum/step | current accepted instrument generation; a quiet current generation has no age TTL | exact matched `kind = option_combo`, `state = open`, `is_active = true`, and `q` aligned to amount rules are required; a recognized non-`open` state, known false, or known off-grid `q` is known unavailable; missing, malformed, or unrecognized data is `UNKNOWN` | known unavailability prevents evaluation; change/end/unknown invalidates Candidate; after entry it feeds close-quote/liquidity state |
| combo order book | `book.<combo>.100ms` snapshot/change fields `type`, timestamp, instrument, `change_id`, optional `prev_change_id`, bids, and asks; or the one bounded public snapshot response, whose separate REST `state` is required | stream: acknowledged generation and unbroken snapshot/change chain; REST: attempt/frontier rules below; last-mutation age is diagnostic only | streaming messages never invent a lifecycle `state`; combo instrument metadata owns lifecycle. A REST response must have `state = open` consistent with current combo metadata. Complete stream depth may prove full `q` or known insufficiency; bounded REST proves only positive full-`q`, while insufficient/possibly truncated is `UNKNOWN` | Candidate invalidates on unknown or known loss of full entry quote; after entry it changes close-quote/liquidity state |
| BTC-USDC index | official public index/ticker; USDC/BTC | accepted source identity at the same settled snapshot | finite positive value required for each fee reserve | unknown invalidates Candidate; after entry makes quote-dependent fee and economic predicates `UNKNOWN` |
| short-leg ticker risk facts | official public ticker for the short leg; signed Delta and mark implied volatility normalized from percent to fraction | accepted source identity and Policy ticker budget | both finite and instrument-bound fields are required; signed Delta must be within `[-1, 1]` and mark implied volatility must be nonnegative; out-of-domain data is `UNKNOWN`, not a threshold breach; mark is risk-only | unknown invalidates Candidate; after entry makes the relevant risk predicate `UNKNOWN` |
| component option books | `book.<option>.100ms` for the two legs; price in USDC/BTC and amount in BTC; lifecycle comes from option instrument metadata, not book deltas | each has its own acknowledged generation and unbroken snapshot/change chain; quiet books do not age out | optional for atomic state; both option instruments must remain open/active and both exact reverse sides must be continuous, amount-rule aligned, and full-`q` to classify `LEGGED_CLOSE_REFERENCE` | never creates economics; missingness cannot override a known atomic quote or known atomic insufficiency |
| entry and prior Position facts | accepted `SHADOW_ENTRY` and last changed Position snapshot; stated units | durable identity plus current settled boundary | exact identities required after entry | mismatch fails closed; no cross-runtime continuation |

The future implementation must schedule the one deterministic public snapshot attempt defined
under admission and races its response against a later public subscription snapshot/change. It
may consume only the winning post-Candidate official refresh and may not call
`private/get_leg_prices` or any account endpoint.

## Public-source basis and inference limits

The public contract is based on:

- [Deribit fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees), including the
  USDC option fee cap and option-combo buy-versus-sell discount;
- [linear USDC options](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options),
  including the current two-step expiry mechanics and final 30-minute delivery-price window;
- [combo books](https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books);
- [`public/get_combos`](https://docs.deribit.com/api-reference/combo-books/public-get_combos),
  whose complete currency catalog supplies active combo identities and signed legs;
- [streaming order-book schema](https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval),
  whose full snapshot/change chain does not carry lifecycle `state`;
- [public order-book fields](https://docs.deribit.com/api-reference/market-data/public-get_order_book);
  and
- [public instrument fields](https://docs.deribit.com/api-reference/market-data/public-get_instrument).

Deribit exposes the allocation of an aggregate combo price to individual legs through
[a private endpoint](https://docs.deribit.com/api-reference/combo-books/private-get_leg_prices).
That endpoint is cited only to establish the public inference limit and is forbidden here.

The official pages define venue mechanics. They do not prove account fee tier, maker status,
future index, future close price, settlement cost, actual fill, margin, or a finite all-in account
loss. A production Policy freezes the retrieved source URL, retrieval timestamp, effective
schedule label, fee role, and numeric reserve rate in its content identity. A changed official
label or retrieval requires a new Policy identity even when the frozen formula and rate are
unchanged. A change to the formula, combo discount, or `0.0003` reserve rate requires an explicit
contract amendment before a new Policy can be accepted. Runtime code may not silently follow a
webpage.

## Policy artifacts and content identities

Underwriting and Position are two separate immutable Policy artifacts. There is no third admission
Policy. Admission is the deterministic gate in this contract; every configurable pre-entry field
belongs to the Underwriting Policy.

Each Policy is one UTF-8 JSON file with no byte-order mark, duplicate member, non-finite number,
unknown member, or missing required member. Its identity is:

```text
Policy identity = "sha256:" + lowercase_sha256_of_exact_file_bytes
```

The exact bytes are validated before process start, frozen for the process lifetime, and recorded
on every downstream durable object. Hot reload, fallback defaults, environment overrides, and
in-process tuning are forbidden. Numeric fields are JSON numbers interpreted as exact decimals.
JSON booleans never satisfy integer or decimal fields.

Common scalar validation is exact:

- every `*_policy_identity` is a string matching `sha256:[0-9a-f]{64}`;
- `fee_schedule_source_url` is the exact non-empty HTTPS URL used for review;
- `fee_schedule_retrieved_at_utc` is a valid UTC timestamp in
  `YYYY-MM-DDTHH:MM:SSZ` form;
- `fee_schedule_effective_label` is a non-empty UTF-8 string of at most 128 Unicode scalar values;
- every `*_ms` is a JSON integer from `1` through `9223372036854775807`, inclusive;
- every `*_level_count` is a JSON integer from `1` through `10000`, inclusive;
- every other numeric Policy member is a JSON number satisfying its stated exact-decimal range;
  and
- neither Policy contains a derived member, nested object, or array.

### Required Underwriting Policy fields

The Underwriting Policy has exactly these semantic members:

- `policy_semantic_name = "SHORT_VOL_PUBLIC_SHADOW_UNDERWRITING_POLICY"`;
- `radar_policy_identity`, equal to the one accepted Radar Policy identity;
- positive `target_base_quantity_btc`;
- positive integer `clock_currentness_budget_ms`, `platform_currentness_budget_ms`,
  `combo_snapshot_send_budget_ms`, `combo_snapshot_response_budget_ms`,
  `index_currentness_budget_ms`, and `option_ticker_currentness_budget_ms`;
- `fee_role = "TAKER"`;
- non-empty `fee_schedule_source_url`, `fee_schedule_retrieved_at_utc`, and
  `fee_schedule_effective_label`, plus
  `fee_rate_index_fraction = 0.0003`;
- nonnegative `path_risk_reserve_usdc`, `jump_risk_reserve_usdc`,
  `tail_risk_reserve_usdc`, `liquidity_cost_reserve_usdc`,
  `uncertainty_reserve_usdc`, and `settlement_cost_reserve_usdc`;
- positive `maximum_underwriting_reserved_loss_usdc`;
- positive `minimum_net_entry_credit_usdc`;
- a `minimum_net_credit_to_payoff_cap_fraction` strictly between zero and one; and
- positive integer `maximum_entry_consumed_level_count`.

The six named reserves sum exactly to `future_cost_reserve_usdc`; this derived value is recorded,
not a Policy member. The exact top-level key set is:

```text
policy_semantic_name
radar_policy_identity
target_base_quantity_btc
clock_currentness_budget_ms
platform_currentness_budget_ms
combo_snapshot_send_budget_ms
combo_snapshot_response_budget_ms
index_currentness_budget_ms
option_ticker_currentness_budget_ms
fee_role
fee_schedule_source_url
fee_schedule_retrieved_at_utc
fee_schedule_effective_label
fee_rate_index_fraction
path_risk_reserve_usdc
jump_risk_reserve_usdc
tail_risk_reserve_usdc
liquidity_cost_reserve_usdc
uncertainty_reserve_usdc
settlement_cost_reserve_usdc
maximum_underwriting_reserved_loss_usdc
minimum_net_entry_credit_usdc
minimum_net_credit_to_payoff_cap_fraction
maximum_entry_consumed_level_count
```

The two fixed string values, identity format, common scalar rules, and per-field ranges above are
the complete type contract. The Underwriting target quantity must equal the target quantity in
the exact accepted Radar Policy identified by `radar_policy_identity`. A missing, extra, negative,
out-of-range, or inconsistent field, including that quantity mismatch, rejects the Policy before
runtime.

### Required Position Policy fields

The Position Policy has exactly these semantic members:

- `policy_semantic_name = "SHORT_VOL_PUBLIC_SHADOW_POSITION_POLICY"`;
- `underwriting_policy_identity`, equal to the one compatible Underwriting Policy identity;
- the same positive `target_base_quantity_btc`;
- positive integer `clock_currentness_budget_ms`, `platform_currentness_budget_ms`,
  `combo_snapshot_send_budget_ms`, `combo_snapshot_response_budget_ms`,
  `index_currentness_budget_ms`, and `option_ticker_currentness_budget_ms`;
- `fee_role = "TAKER"`, the same frozen `fee_schedule_source_url`,
  `fee_schedule_retrieved_at_utc`, and `fee_schedule_effective_label`, and
  `fee_rate_index_fraction = 0.0003`;
- `latest_exit_lead_ms = 1800000`;
- positive `maximum_projected_net_loss_usdc`;
- `maximum_absolute_short_delta` strictly between zero and one;
- positive `maximum_absolute_index_return_since_entry_fraction`;
- positive `maximum_absolute_index_return_since_prior_evaluation_fraction`;
- positive `maximum_short_mark_iv_increase_fraction`;
- positive integer `maximum_close_consumed_level_count`;
- nonnegative `minimum_take_profit_usdc`; and
- `maximum_remaining_premium_fraction` greater than or equal to zero and less than or equal to one.

No field chooses a holding duration. An incompatible Policy identity or target quantity fails
closed. The exact top-level key set is:

```text
policy_semantic_name
underwriting_policy_identity
target_base_quantity_btc
clock_currentness_budget_ms
platform_currentness_budget_ms
combo_snapshot_send_budget_ms
combo_snapshot_response_budget_ms
index_currentness_budget_ms
option_ticker_currentness_budget_ms
fee_role
fee_schedule_source_url
fee_schedule_retrieved_at_utc
fee_schedule_effective_label
fee_rate_index_fraction
latest_exit_lead_ms
maximum_projected_net_loss_usdc
maximum_absolute_short_delta
maximum_absolute_index_return_since_entry_fraction
maximum_absolute_index_return_since_prior_evaluation_fraction
maximum_short_mark_iv_increase_fraction
maximum_close_consumed_level_count
minimum_take_profit_usdc
maximum_remaining_premium_fraction
```

The two fixed string values, identity format, common scalar rules, and per-field ranges above are
the complete type contract. The Position target quantity must equal the target quantity in the
exact compatible Underwriting Policy. A missing, extra, negative, out-of-range, or inconsistent
field, including that quantity mismatch, rejects the Policy before runtime.

## Entry economics and fee reserve

For required-side full-quantity official atomic depth:

```text
direction_sign = +1 for BUY, -1 for SELL

required_side_total_quote_usdc =
    sum(level_price_usdc_per_btc × consumed_level_amount_btc)

gross_entry_credit_usdc =
    -direction_sign × required_side_total_quote_usdc

equivalently =
    -signed_order_amount_btc × exact_required_side_vwap_usdc_per_btc

require gross_entry_credit_usdc > 0
```

The consumed amounts sum exactly to `q`; no absolute value is taken. The summed form is normative
and performs no division. Public depth is evaluated as taker economics. Both option instrument
records must publish finite nonnegative `taker_commission <= 0.0003`. Before entry, any other
commission value makes fee compatibility `UNKNOWN`, leaves the Underwriting economic action
absent, and invalidates any Candidate.

After entry, commission incompatibility does not erase the Position or alter the independent
close-quote classification. A missing/malformed commission makes fee-dependent
`MAXIMUM_NET_LOSS_BOUNDARY_REACHED` and `ECONOMIC_EXIT_BOUNDARY_REACHED` `UNKNOWN`; a known
commission above the frozen rate additionally makes
`PLATFORM_OR_SOURCE_DISCONTINUITY = TRUE`. Any other known hard/risk/liquidity predicate and an
already latched CLOSE remain authoritative. An atomic gross close quote may still be classified,
but fee reserve, net close economics, and projected PnL/loss are `null / UNKNOWN`, and no
fee-complete `SHADOW_CLOSE_OPPORTUNITY` is eligible until compatible current instrument facts
return.

The frozen public standard single-leg option mechanic is:

```text
single_leg_fee_usdc =
    min(
        0.0003 × btc_usdc_index_usdc_per_btc,
        0.125 × abs(option_leg_price_usdc_per_btc)
    ) × q
```

For the authorized one-buy/one-sell combo, the venue waives the lower of total buy-side and
sell-side option fees. For this exact 1:1 structure:

```text
buy_leg_standard_fee_usdc <= 0.0003 × index × q
sell_leg_standard_fee_usdc <= 0.0003 × index × q

combo_standard_base_fee_usdc =
    max(buy_leg_standard_fee_usdc, sell_leg_standard_fee_usdc)
    <= 0.0003 × index × q
```

Public combo depth does not expose the exact leg-price allocation needed to apply the per-leg cap.
Therefore this contract never claims an actual account fee. It freezes only the conservative
public standard base-trading-fee upper bound:

```text
public_standard_entry_trading_fee_upper_bound_usdc =
    0.0003 × entry_btc_usdc_index_usdc_per_btc × q

entry_fee_reserve_usdc =
    public_standard_entry_trading_fee_upper_bound_usdc

net_entry_credit_usdc =
    gross_entry_credit_usdc - entry_fee_reserve_usdc
```

The field name is always `fee_reserve` or `fee_upper_bound`, never `actual_fee`. SMA/broker fees,
account adjustments, account tier, fee-balance use, maker rebates, delivery, liquidation, and
private leg allocation are excluded from this public standard bound and remain unknown.

## Defined-risk loss measures

Let the protective vertical width be:

```text
width_usdc_per_btc = abs(long_strike_usdc_per_btc - short_strike_usdc_per_btc)
payoff_cap_usdc = width_usdc_per_btc × q
```

The exact decision measures are:

```text
contractual_payoff_max_loss_ex_fees_usdc =
    max(0, payoff_cap_usdc - gross_entry_credit_usdc)

entry_fee_reserved_payoff_loss_usdc =
    max(0, payoff_cap_usdc - net_entry_credit_usdc)

future_cost_reserve_usdc =
    path_risk_reserve_usdc
    + jump_risk_reserve_usdc
    + tail_risk_reserve_usdc
    + liquidity_cost_reserve_usdc
    + uncertainty_reserve_usdc
    + settlement_cost_reserve_usdc

underwriting_reserved_loss_usdc =
    max(
        0,
        payoff_cap_usdc
        - net_entry_credit_usdc
        + future_cost_reserve_usdc
    )
```

`contractual_payoff_max_loss_ex_fees_usdc` is a payoff bound before costs.
`underwriting_reserved_loss_usdc` is a Policy decision measure, not a guarantee.
`actual_all_in_max_loss_usdc` is always `null` with availability `UNKNOWN` under
`PUBLIC_SHADOW`: future index, exact leg fees, account tier, future quote, and settlement costs do
not have a public finite bound. In particular, no Policy reserve may be relabelled as actual loss.

## Underwriting availability and action

Both Policy files must pass exact-key, identity, compatibility, target-quantity, and value
validation before the downstream process starts. Missing or invalid Policy bytes are a preflight
failure and create no runtime availability denominator. A later in-memory Policy identity or
Radar episode target-quantity mismatch is an integrity failure and fatal stop, not an availability
state or `ABSTAIN`; the mismatching boundary creates no downstream evaluation.

For valid preloaded Policies, availability and economic action are orthogonal and evaluated in this
exclusive order:

| Current opportunity state | Availability | Economic action |
|---|---|---|
| no active Radar episode; the episode/short-leg slot is already consumed by Entry; complete current scope proves `NO_ACTIVE_COMBO` / `NO_TARGET_SIZE_CREDIT_QUOTE`; or trusted-time upper bound reaches the admission cutoff | `NOT_EVALUATED` | absent |
| an active episode exists and a required public `taker_commission` is missing, malformed, negative, or greater than the frozen `0.0003` reserve rate | `UNKNOWN` | absent |
| an active episode exists but atomic availability is `UNKNOWN`, or any required public fact is missing, stale, incomplete, malformed, gapped, contradictory, or contaminated | `UNKNOWN` | absent |
| active episode, `PUBLIC_ATOMIC_QUOTE_AVAILABLE`, valid exact structure/`q`, positive payoff cap and gross credit, and every required public fact complete/current | `EVALUABLE` | exactly one of `CANDIDATE | WATCH | ABSTAIN` |

For one `EVALUABLE` identity:

1. `ABSTAIN` if net entry credit is not positive, net entry credit is at or below
   `future_cost_reserve_usdc`, or `underwriting_reserved_loss_usdc` exceeds the Policy maximum.
2. Otherwise `WATCH` if net entry credit is below the Policy minimum,
   `net_entry_credit_usdc < minimum_net_credit_to_payoff_cap_fraction × payoff_cap_usdc`, or
   consumed entry levels exceed the Policy maximum.
3. Otherwise `CANDIDATE`.

The order is total and exclusive. `UNKNOWN` is not `ABSTAIN`; no action is emitted when availability
is not `EVALUABLE`. A known valid unsupported structure or known full-book depth below `q` is
`NOT_EVALUATED`; a malformed structure or incomplete/truncated book is `UNKNOWN`; neither reaches
`ABSTAIN`.

## Underwriting and Candidate identity

```text
UnderwritingAvailabilityEvaluationIdentity =
    runtime_identity
    × Radar_Policy_identity
    × Underwriting_Policy_identity
    × Position_Policy_identity
    × Radar_scope_or_short_leg_identity
    × consumed_availability_fact_fingerprint
    × resulting_availability
    × availability_evaluation_FactBoundary

UnderwritingPositionSlotKey =
    runtime_identity
    × Radar_Policy_identity
    × active_episode_identity
    × short_leg_identity
    × q

UnderwritingOpportunityKey =
    UnderwritingPositionSlotKey
    × official_combo_and_canonical_leg_identity

UnderwritingEvaluationIdentity =
    UnderwritingOpportunityKey
    × Underwriting_Policy_identity
    × Position_Policy_identity
    × consumed_economic_fact_fingerprint
    × evaluation_FactBoundary

UnderwritingActionIdentity =
    UnderwritingEvaluationIdentity
    × economic_action_CANDIDATE_or_WATCH_or_ABSTAIN

CandidateIdentity =
    UnderwritingActionIdentity_where_action_is_CANDIDATE
    × candidate_activation_FactBoundary
```

Each slot begins `AVAILABLE` and transitions once to `CONSUMED_BY_SHADOW_ENTRY`. The slot excludes
combo identity deliberately: at most one Shadow Entry and open Position may arise for one
runtime/Radar-Policy/episode/short-leg/quantity scope, even if several compatible combos or later
quotes exist. Before Entry, sequential replacement Candidates remain allowed under their distinct
consumed facts; after Entry, the terminal slot makes later opportunity availability
`NOT_EVALUATED` and forbids another Candidate or Entry until a distinct Radar episode creates a
new slot.

The availability fingerprint includes only normalized decision-relevant business facts: settled
Radar/atomic/slot state; required-fact availability, currentness, completeness, validity, and
classification; exact normalized values actually compared by the availability rules; and the
discrete trusted-time cutoff/currentness classes those rules consume. Raw source identity, source
timestamp, receipt identity, request id, subscription generation, and official `change_id` are
immutable provenance only. They never enter an availability business fingerprint. An availability
identity is created only when that normalized fingerprint or resulting availability changes. With
no episode it binds the available Radar scope/state facts without inventing missing opportunity
facts, so it can represent no episode or a known-negative state. An
`UnderwritingOpportunityKey`, `UnderwritingEvaluationIdentity`, and `UnderwritingActionIdentity`
exist only for `EVALUABLE`. Candidate activation uses the same known-at `FactBoundary` as its
Candidate action and inherits every opportunity, Policy, consumed-fact, and action binding.
The consumed economic fingerprint includes only the normalized business facts actually used:
catalog/structure/lifecycle/currentness/completeness classifications, exact `q`-relevant quote
levels, exact index and ticker risk values, Policy values, fee/reserve/loss values and derived
economics, and discrete trusted-time decision classes. Raw source or transport identities remain
attached as provenance but are excluded. A source update that preserves every normalized business
fact neither creates another evaluation or Candidate nor invalidates the existing Candidate.

Candidate lifecycle is:

```text
ABSENT → VALID → ADMITTED
               ↘ INVALIDATED
```

`ADMITTED` and `INVALIDATED` are terminal. A Candidate has no arbitrary TTL and never revives.
Recovery may create a new Candidate only from a new complete normalized business fingerprint.

### Complete Candidate invalidation order

At each later settled boundary, the first applicable reason in this order becomes the primary
reason; all applicable reasons are recorded in this same order:

1. `RUNTIME_OR_CODE_IDENTITY_CHANGED`;
2. `RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED`;
3. `UNDERWRITING_OR_POSITION_POLICY_IDENTITY_CHANGED`;
4. `POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY`;
5. `STRUCTURE_LEG_LIFECYCLE_OR_TARGET_QUANTITY_CHANGED`;
6. `SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN`;
7. `LATEST_ADMISSION_BOUNDARY_REACHED`;
8. `CONSUMED_NON_ADMISSION_BUSINESS_FINGERPRINT_CHANGED`;
9. `REUNDERWRITING_NO_LONGER_CANDIDATE`;
10. `FAILED_ADMISSION_EVALUATION_CONSUMED`.

For `LATEST_ADMISSION_BOUNDARY_REACHED`, Candidate remains valid only while
`trusted_time.upper_ms < expiry_ms - 1800000`. Any overlap with or passage beyond the boundary
invalidates it. Relevant normalized business-fact change triggers re-Underwriting; it does not
extend the old Candidate. Heartbeat, timer, repeated message, and component-leg price do not
preserve or refresh Candidate identity.

A qualifying post-Candidate official combo refresh is handled only by the admission transaction
below. It may carry economically identical levels and a new raw source identity without changing
the Candidate business identity; that later official source identity is recorded as admission
provenance. Any other changed normalized consumed business fingerprint terminally invalidates the
old Candidate. If its complete re-Underwriting result is again `CANDIDATE`, that boundary may
activate one new Candidate with a new consumed fingerprint; it may not mutate the old identity. A
successful admission ends the Candidate as `ADMITTED`.

At a boundary containing a qualifying combo refresh, reasons 1 through 7 are checked first, then
the admission transaction recomputes all contemporaneously changed clock, index, ticker, catalog,
and quote facts as one settled snapshot. Reason 8 does not preempt that transaction. At a boundary
without a qualifying combo refresh, reason 8 applies before ordinary re-Underwriting.

## Deterministic Shadow admission

Admission has no configurable Policy of its own. In the same non-blocking reducer transaction that
commits a Candidate, the reducer deterministically returns exactly one Candidate-scoped
`PendingRpc` in `SCHEDULED`; it never performs network I/O. The immutable scheduled identity is:

```text
ScheduledAdmissionAttemptIdentity =
    CandidateIdentity
    × unique_request_id
    × method_public_get_order_book
    × exact_request_params_including_depth_10000
    × Candidate_origin_FactBoundary
```

The send deadline is
`Candidate_origin_FactBoundary.received_monotonic_ms +
Underwriting_Policy.combo_snapshot_send_budget_ms`. Only a later send-completion control from the
unified application queue creates immutable `SENT`; its boundary must satisfy the send-budget
inequality and its `causal_seq` must be greater than Candidate activation. `SENT` starts the
separate Underwriting response deadline. The first deadline crossing enqueues exactly one
`DEADLINE_LATE` control; it is not an arbitrary timer.

No second admission request is permitted. The first locally accepted qualifying subscription
refresh or matched RPC response in `causal_seq` order wins; the other source is cancelled or
ignored for that terminal Candidate. An unknown/wrong/already-terminal request id is only
`ORPHAN_LATE_WIRE` and cannot consume the Candidate's own pending attempt. For that matched
attempt, `ERROR`, `DEADLINE_LATE`, transport/error response, payload combo/instrument mismatch,
malformed/truncated response, stale/ahead frontier, or complete evaluation without Entry
terminally applies `FAILED_ADMISSION_EVALUATION_CONSUMED`, after any higher-priority invalidation
already true at that boundary. A subscription refresh may win while the RPC is still
`SCHEDULED` or `SENT`; its pending command is then cancelled and a later wire response is
`ORPHAN_LATE_WIRE`. Equal-receive-time races use `ingress_seq`/`causal_seq`, never source
timestamp. The transaction order is fixed:

1. prove the Candidate was `VALID` before the refresh transaction;
2. accept one of the two same-runtime refresh identities below at a local `FactBoundary` whose
   `causal_seq` is strictly greater than Candidate activation;
3. reduce that fact into a complete settled snapshot;
4. prove the same combo, canonical legs, direction, and full `q`;
5. prove all catalogs, currentness, continuity, trusted time, index, and risk facts current;
6. recompute entry fee reserve, net credit, all loss measures, and Underwriting under the exact same
   two downstream Policy identities; and
7. atomically emit `SHADOW_ENTRY`, mark its `UnderwritingPositionSlotKey`
   `CONSUMED_BY_SHADOW_ENTRY`, and invalidate every other valid Candidate in that slot only if the
   recomputed result is still `CANDIDATE` and
   `trusted_time.upper_ms < expiry_ms - 1800000`; otherwise terminally invalidate Candidate.

A qualifying refresh is either:

- an accepted official combo-book snapshot/change in the same unbroken subscription generation,
  with a new `change_id` and local boundary later than the Candidate's consumed quote; or
- an official public combo-book snapshot response matched to the Candidate-origin request, whose
  successful `SENT` boundary is strictly after Candidate activation, whose response receipt is
  strictly after `SENT`, and which satisfies both
  `request_SENT_monotonic_ms - Candidate_origin_received_monotonic_ms <=
  combo_snapshot_send_budget_ms` and
  `response_received_monotonic_ms - request_SENT_monotonic_ms <=
  combo_snapshot_response_budget_ms`.

The exact refresh identities are:

```text
SubscriptionAdmissionRefreshSourceIdentity =
    runtime_identity
    × session_epoch
    × subscription_generation
    × official_combo_identity
    × snapshot_or_change_kind
    × prev_change_id_or_null_for_snapshot
    × change_id
    × source_timestamp_ms
    × accepted_FactBoundary

RpcAdmissionRefreshSourceIdentity =
    runtime_identity
    × unique_request_id
    × method_public_get_order_book
    × official_combo_identity
    × exact_request_params_including_depth_10000
    × Candidate_origin_FactBoundary
    × request_SENT_FactBoundary
    × matched_response_change_id
    × matched_response_timestamp_ms
    × response_received_FactBoundary
```

Every listed source value is required and validated. The subscription chain must link exactly.
The one RPC uses exact params `{instrument_name: official_combo_identity, depth: 10000}`; another
depth is invalid, and the response must match the one request id and combo. At response receipt,
its `change_id` must
equal the current accepted same-session combo-book market frontier and every returned lifecycle
field and level through the requested depth must match that accepted projection exactly. A lower
`change_id` is `LATE_IGNORED`; a higher one is `RECONCILIATION_REQUIRED` and cannot seed a delta
book or qualify admission. Either disposition consumes the one RPC attempt. Equality permits one
fresh public verification of a quiet unchanged book; inconsistent bytes at equal id are
contaminated and consume the attempt.

No exchange timestamp is compared with a local Candidate timestamp; all before/after claims use
same-runtime `FactBoundary.causal_seq`, while official `change_id` separately prevents market-state
regression. A bounded RPC result that covers full `q` is a positive witness. A result that does
not cover `q` is incomplete/possibly truncated and makes admission `UNKNOWN`, never known
unexecutable.

The refreshed book may have economically identical levels. Its official response/update and local
known-at identities must still be new. Candidate-time projection, mere elapsed time, heartbeat,
currentness recheck, component legs, mark, or mid cannot refresh admission. This makes a quiet but
continuous book refreshable without pretending that old bytes are a new market fact.

```text
ShadowEntryIdentity =
    CandidateIdentity
    × admission_FactBoundary
```

`SHADOW_ENTRY` freezes the refresh source identity and levels, exact gross/net entry economics,
fee reserve, all loss measures, both downstream Policy identities, Radar Policy/episode identity,
canonical structure, `q`, trusted-time interval, entry BTC-USDC index, entry short-leg mark
implied-volatility fraction, their source identities/boundaries, and all non-claims. It is neither
an order nor a fill and creates no actual exposure.

## Post-entry ownership and remaining quantity

After `SHADOW_ENTRY`, the Shadow Position lifecycle is independent of whether the Radar anomaly
remains active. The future runtime must maintain the required official public instrument and
active-combo catalog, ticker, index, platform, and active-combo book lifecycle for every open
Shadow Position. Component books are optional diagnostic observations: their absence or gap is
never a required-source discontinuity. When no active combo is known, no combo-book subscription
is required; that known atomic unavailability feeds the liquidity predicate. Radar Layer 2
stopping cannot stop Position observation.

Because this contract contains no order or fill:

```text
remaining_shadow_quantity_btc = entry_target_quantity_btc = q
```

Every quote evaluation uses full `q`. A public opportunity never reduces quantity. This contract
does not create settlement completion, flatness, Position termination, PnL Outcome, or elapsed
holding-period acceptance.

## Position action state machine

The first Position evaluation must consume a changed fact at a boundary strictly later than
`SHADOW_ENTRY`. Entry-boundary facts cannot double as future Position evidence.

```text
ENTRY_BOUNDARY
→ PENDING_STRICTLY_FUTURE_FACT
→ HOLD | UNKNOWN | CLOSE_LATCHED

HOLD ↔ UNKNOWN
HOLD | UNKNOWN → CLOSE_LATCHED
CLOSE_LATCHED → CLOSE_LATCHED
```

The serialized economic action is `HOLD | CLOSE | UNKNOWN`; `CLOSE_LATCHED` is the lifecycle state
that permanently serializes action `CLOSE`. Once a known close predicate is true, later recovery,
price change, or quote loss cannot return the Position to `HOLD` or `UNKNOWN`.

Every close predicate is exactly `TRUE | FALSE | UNKNOWN`. Evaluation is:

1. evaluate every predicate independently, including after CLOSE is latched so later true reasons
   can be added;
2. if lifecycle is already `CLOSE_LATCHED`, serialized action remains `CLOSE` regardless of the
   current predicate vector;
3. otherwise, if any predicate is known `TRUE`, latch lifecycle and serialize action `CLOSE`;
4. otherwise, if any predicate is `UNKNOWN`, action is `UNKNOWN`;
5. otherwise action is `HOLD`.

An unknown higher-priority predicate cannot erase a lower-priority known true predicate.

### Position evaluation and action identities

```text
PositionEvaluationIdentity =
    ShadowEntryIdentity
    × Position_Policy_identity
    × consumed_position_fact_fingerprint
    × evaluation_FactBoundary

PositionActionIdentity =
    PositionEvaluationIdentity
    × serialized_action
    × ordered_predicate_truth_vector
    × ordered_latched_close_reason_vector
```

The consumed fingerprint includes trusted time, official lifecycle states, platform/continuity,
current index, short-leg ticker risk facts, and only the atomic quote facts actually consumed by
the loss, liquidity, or economic predicates, plus fee reserve and exact derived arithmetic.
Component-book identities never enter a Position fingerprint because they are diagnostic and
cannot change a Position predicate. A `PositionEvaluationIdentity` exists once for every changed
consumed fingerprint at a strictly post-entry settled boundary.
Every such evaluation has exactly one `PositionActionIdentity`, including repeated `HOLD`,
`UNKNOWN`, or latched `CLOSE`; only an identical evaluation is de-duplicated.

`first_latched_CLOSE_action_identity` is the earliest `PositionActionIdentity` in causal order whose
serialized action is `CLOSE`. Every close reason that is known true is added permanently to the
Position's latched reason set. Primary reason is always the highest-priority latched reason and
secondary reasons are the remaining latched reasons in total order. Later unknown/false values
cannot remove a latched action or reason.

The entry index is the initial `prior_evaluation_index`. For each distinct Position evaluation:

1. compute both path predicates against the frozen entry index and the last committed finite
   positive prior-evaluation index;
2. commit the evaluation and action; then
3. if the evaluation consumed a finite positive current index, advance
   `prior_evaluation_index` to that exact current index for the next evaluation.

An evaluation with index `UNKNOWN` does not advance the anchor. Recovery compares with the last
finite committed anchor, or the entry index if none exists. The Entry boundary itself never
advances the anchor. Each Position evaluation persists current index, prior anchor, next anchor,
entry index, entry short-leg mark implied volatility, exact units, and their source boundaries, so
no replay is required.

## Hard-close and close-reason total order

The one total order, from highest to lowest primary reason, is:

1. `SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED`;
2. `LATEST_EXIT_BOUNDARY_REACHED`;
3. `PLATFORM_OR_SOURCE_DISCONTINUITY`;
4. `MAXIMUM_NET_LOSS_BOUNDARY_REACHED`;
5. `SHORT_LEG_RISK_BOUNDARY_REACHED`;
6. `PATH_OR_JUMP_RISK_BOUNDARY_REACHED`;
7. `VOLATILITY_STATE_BOUNDARY_REACHED`;
8. `LIQUIDITY_EXIT_BOUNDARY_REACHED`;
9. `ECONOMIC_EXIT_BOUNDARY_REACHED`.

When several predicates are true, the first is `primary_close_reason`; every other true reason is
recorded as `secondary_close_reasons` in this same order.

The seven-state lifecycle below is applied to each of the two canonical option instrument
metadata records:

| Official option instrument `state` | Settlement/expiry predicate | Platform/source predicate |
|---|---|---|
| `open` | trusted-time rule below | false when every other required source is continuous |
| `settlement` | `TRUE` | false unless another discontinuity exists |
| `delivered` | `TRUE` | false unless another discontinuity exists |
| `archivized` | `TRUE` | false unless another discontinuity exists |
| `inactive` | trusted-time rule below | `TRUE` |
| `locked` | trusted-time rule below | `TRUE` |
| `halted` | trusted-time rule below | `TRUE` |
| missing, malformed, or any unrecognized value | trusted-time rule if decisive, otherwise `UNKNOWN` | `UNKNOWN` unless another discontinuity is known true |

The active-combo catalog is present/absent, not a single-details `active | inactive` record. Combo
instrument metadata has the same seven-state field and `is_active`; any recognized non-`open` or
false value proves atomic-combo unavailability and feeds liquidity, while `locked | halted` also
independently triggers source/platform discontinuity. No combo state proves that the canonical
option Position settled. Streaming book messages have no lifecycle state. Only a matched REST
snapshot's separate `state` must be `open`; a recognized non-`open` REST state also proves atomic
unavailability.

Before entry, both option instruments and the matched combo instrument must be `open` and
`is_active = true`, the exact combo must be present in the complete active-combo catalog, and
stream continuity or a matched REST response must be usable. A recognized non-`open`/false value
or complete catalog absence is `NOT_EVALUATED`; missing, malformed, unreconciled, or unrecognized
facts are `UNKNOWN`.

The predicate truth rules are exact:

- `SETTLEMENT_OR_EXPIRY_BOUNDARY_REACHED` is true when either canonical option instrument has
  official state `settlement`, `delivered`, or `archivized`, or when
  `trusted_time.lower_ms >= expiry_ms`; false for recognized leg states only when both are outside
  that set and
  `trusted_time.upper_ms < expiry_ms`; otherwise unknown.
- `LATEST_EXIT_BOUNDARY_REACHED` is true when
  `trusted_time.upper_ms >= expiry_ms - 1800000`; false when the upper bound is strictly earlier;
  missing trusted time is unknown. Treating interval overlap as reached is the frozen conservative
  product rule, not an exchange mandate.
- `PLATFORM_OR_SOURCE_DISCONTINUITY` is true for a known connection/session gap, stopped epoch,
  non-operational platform, known failed/gapped required metadata generation, lost required
  index/ticker subscription, loss/gap of the required combo-book stream while complete current
  catalog/instrument facts still prove that combo active/open, either canonical option with known
  `state = open` plus `is_active = false` or with state `inactive | locked | halted`, a matched combo instrument in
  `locked | halted`, a known canonical-leg identity/structure/`contract_size` change, or a known
  fee incompatibility with the frozen Policy. Active-combo catalog absence, combo
  `inactive | settlement | delivered | archivized`, combo `is_active = false`/off-grid state, and
  all component-book state are excluded and owned by atomic availability/liquidity. A merely dirty
  in-progress authoritative catalog reconcile is `UNKNOWN`, not a known platform failure. The
  predicate is false only when every required core source for the current atomic-availability
  state is explicitly continuous, active, compatible, and operational; otherwise unknown.
  Canonical option `settlement | delivered | archivized` with the corresponding
  `is_active = false` contributes only the higher settlement/expiry reason, not a false secondary
  source-discontinuity reason.
- `MAXIMUM_NET_LOSS_BOUNDARY_REACHED` is true when a current full-`q` atomic close quote proves
  projected net loss at or above the Policy maximum; false when it proves loss below the maximum;
  otherwise unknown.
- `SHORT_LEG_RISK_BOUNDARY_REACHED` is true when the current absolute short Delta is at or above
  the Policy maximum or the current index is at/through the short strike in the short option's loss
  direction: `index >= short_strike` for a short call and `index <= short_strike` for a short put.
  It is false when both facts are known below/outside their boundaries; otherwise unknown.
- `PATH_OR_JUMP_RISK_BOUNDARY_REACHED` is true when absolute index return since entry or since the
  preceding changed Position evaluation is at or above its corresponding Policy maximum; false
  when both are known below; otherwise unknown. The exact no-division comparisons are
  `abs(current_index - entry_index) >= entry_return_limit × entry_index` and
  `abs(current_index - prior_evaluation_index) >= jump_return_limit ×
  prior_evaluation_index`; equality triggers `TRUE`.
- `VOLATILITY_STATE_BOUNDARY_REACHED` is true when the current short-leg mark implied-volatility
  fraction minus its entry fraction is at or above the Policy maximum increase; false when known
  below; otherwise unknown. Mark is risk-only, never quote economics.
- `LIQUIDITY_EXIT_BOUNDARY_REACHED` is true when complete official scope proves
  `UNEXECUTABLE` or `LEGGED_CLOSE_REFERENCE`, or when a full-`q` atomic close quote consumes more
  levels than the Policy maximum; false when a full-`q` atomic quote is known within the limit;
  otherwise unknown. An active-combo stream gap leaves quote/liquidity `UNKNOWN` and separately
  makes the higher source-discontinuity predicate true.
  `LEGGED_CLOSE_REFERENCE` is true here because its classifier rule independently proves no
  authorized active atomic combo; component prices remain diagnostic and are not the reason.
- `ECONOMIC_EXIT_BOUNDARY_REACHED` is true when a full-`q` atomic close quote proves projected net
  PnL at or above `minimum_take_profit_usdc`, or
  `net_close_debit_usdc <= maximum_remaining_premium_fraction × net_entry_credit_usdc`; false when
  both are known outside their boundaries; otherwise unknown. Equality triggers `TRUE`.

The first three are unconditional hard-close predicates. The remaining known risk/economic
predicates are Policy close predicates. Any known true predicate outranks missing soft facts and
any `UNKNOWN | UNEXECUTABLE` close quote.

## Close-quote state and economics

Position action and quote state are separate. The classifier applies this first-match total order:

1. A known non-`open`/inactive canonical option, changed canonical identity/structure/
   `contract_size`, or `q` violating either option's current amount rule produces `UNEXECUTABLE`;
   stale component depth cannot turn an untradeable leg into a legged reference.
2. With both options known open/active/structurally compatible and amount-aligned, complete current
   scope proving no authorized atomic combo—complete catalog absence, combo instrument
   non-open/inactive/off-grid, or matched REST state non-open and consistent with current combo
   metadata—plus both component references defined below produces `LEGGED_CLOSE_REFERENCE`.
3. The same complete known atomic unavailability without both component references produces
   `UNEXECUTABLE`.
4. Otherwise, any missing, malformed, dirty, gapped, generation-unknown, unrecognized, or
   contradictory required option/catalog/combo-instrument/book fact produces `UNKNOWN`. A bounded
   REST response that does not cover `q` is also `UNKNOWN` because it may be truncated.
5. Both options open/active/aligned, exact combo present, combo instrument open/active/aligned,
   complete continuous streaming depth or a matched open/equal-frontier REST witness covering
   full remaining `q` produces `ATOMIC_COMBO_CLOSE_QUOTE`.
6. Under the same active/open/aligned scope, a complete continuous full streaming book known not
   to cover `q` produces `UNEXECUTABLE`.

The component reference closes the Entry's long option by selling full `q` against that option's
bid side and closes the Entry's short option by buying full `q` against that option's ask side.
Each side must independently be continuous, complete, amount-rule aligned, and cover `q`; the
prices are never added, netted, or turned into economics. `LEGGED_CLOSE_REFERENCE` cannot prove an
atomic quote absent or create an opportunity; rules 2 and 3 already require the independent
known-atomic-unavailability fact.

```text
CloseQuoteEvaluationIdentity =
    ShadowEntryIdentity
    × Position_Policy_identity
    × official_combo_and_canonical_leg_identity
    × exact_reverse_direction
    × full_remaining_q
    × consumed_rule_scoped_quote_fingerprint
    × close_quote_state
    × close_conditioning_PRE_CLOSE_or_first_latched_CLOSE_action_identity
    × close_quote_evaluation_FactBoundary
```

The consumed quote fingerprint includes only normalized business facts consumed through the first
matching classifier rule: canonical option/structure identity; lifecycle, active, amount,
currentness, completeness, atomic-availability, and continuity classifications; the exact
`q`-relevant atomic levels and terminal depth state when that rule consumes them; and normalized
unknown reasons. Component raw identities/levels remain provenance only; the business fingerprint
includes just the derived
`FULL_Q_LEGGED_REFERENCE_AVAILABLE | NOT_AVAILABLE | UNKNOWN` state when rules 2 or 3 consume it.
Raw component changes that preserve that state create no business identity.

For business de-duplication, an atomic market-book fingerprint binds the normalized lifecycle,
availability, continuity, currentness, and completeness states plus only the exact
decision-relevant full-`q` levels or known-insufficiency terminal state consumed by the matching
rule. Session, acknowledged generation, official `change_id`, source timestamp, RPC request id,
and schedule/SENT/receipt boundaries remain durable provenance and never enter that fingerprint.
Every quote evaluation on the first-CLOSE boundary still uses `PRE_CLOSE`. `close_conditioning`
changes to the exact first latched CLOSE identity only when the first official subscription
observation or matched RPC response is accepted at a strictly later `FactBoundary`. That one
conditioning transition permits verification of a quiet book even when the normalized business
fingerprint is unchanged. It is recorded once; later source identities with the same fingerprint
cannot repeat it. One identity exists for each changed rule-scoped fingerprint and conditioning
value.

Close direction is the exact reverse of entry:

The fee/net equations below are available only when both current option instrument commission
facts are compatible with the frozen Policy and the close index is known. Otherwise the gross
atomic cashflow remains known, while fee reserve, net close cashflow, projected PnL, and projected
loss are `null / UNKNOWN`.

```text
close_signed_order_amount_btc = -entry_signed_order_amount_btc

close_direction_sign = +1 for close BUY, -1 for close SELL

required_close_side_total_quote_usdc =
    sum(level_price_usdc_per_btc × consumed_level_amount_btc)

gross_close_cashflow_usdc =
    -close_direction_sign × required_close_side_total_quote_usdc

equivalently =
    -close_signed_order_amount_btc × exact_required_close_side_vwap_usdc_per_btc

public_standard_close_trading_fee_upper_bound_usdc =
    0.0003 × close_btc_usdc_index_usdc_per_btc × q

close_fee_reserve_usdc =
    public_standard_close_trading_fee_upper_bound_usdc

net_close_cashflow_usdc =
    gross_close_cashflow_usdc - close_fee_reserve_usdc

net_close_debit_usdc =
    max(0, -net_close_cashflow_usdc)

projected_shadow_net_pnl_usdc =
    net_entry_credit_usdc + net_close_cashflow_usdc

projected_net_loss_usdc =
    max(0, -projected_shadow_net_pnl_usdc)
```

Signs are preserved. A closing credit is not converted into a debit. These are public
opportunity economics, not fills or actual PnL.

## Post-CLOSE observation and opportunity identity

In the reducer transaction that first latches CLOSE, a current exact combo identity with valid
public request params produces one non-blocking Position-scoped `PendingRpc` in `SCHEDULED`;
complete current facts proving that no such combo is requestable record
`NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE`; missing/malformed/unknown facts that prevent a safe
request record `NOT_REQUESTABLE_UNKNOWN`. The latter creates an `UNKNOWN` opportunity evaluation,
not known zero. The reducer never waits for network I/O and never schedules a second quiet-book
request for that first CLOSE:

```text
ScheduledPostCloseQuoteAttemptIdentity =
    ShadowEntryIdentity
    × first_latched_CLOSE_action_identity
    × unique_request_id_or_NOT_REQUESTABLE_KNOWN_or_NOT_REQUESTABLE_UNKNOWN
    × method_public_get_order_book
    × exact_request_params_including_depth_10000_or_null
    × first_latched_CLOSE_FactBoundary
```

For a scheduled request, Position Policy owns the absolute send deadline and subsequent response
deadline. `SENT`, error, cancellation, and deadline controls return through the unified
application queue exactly as for admission. The first qualifying strictly post-CLOSE subscription
observation or matched RPC response wins in causal order; a subscription winner cancels or retires the
request, and a later response is orphan-late. An unknown/wrong/already-terminal request id has zero
business effect; only the matched attempt's send/error/timeout, payload combo mismatch,
stale/ahead, or contaminated outcome is recorded `UNKNOWN` for close-opportunity evaluation.
Nothing unlatches CLOSE or authorizes a retry. Later natural subscription observations remain
eligible for ordinary evaluation only when they change a normalized rule-consumed business fact;
new `change_id` provenance alone has zero business effect.

The one RPC uses the same exact depth, source members, same/equal-frontier reconciliation, and
de-duplication rules as admission, replacing Candidate with first latched CLOSE. Its `SENT`
boundary must be strictly later than first CLOSE and satisfy
`request_SENT_monotonic_ms - first_latched_CLOSE_received_monotonic_ms <=
Position_Policy.combo_snapshot_send_budget_ms`; its matched response must be later than `SENT` and
satisfy
`response_received_monotonic_ms - request_SENT_monotonic_ms <=
Position_Policy.combo_snapshot_response_budget_ms`.

Quote classification and opportunity economics have separate identities:

```text
CloseOpportunityEvaluationIdentity =
    ShadowEntryIdentity
    × first_latched_CLOSE_action_identity
    × post_CLOSE_CloseQuoteEvaluationIdentity_or_attempt_terminal_identity
    × opportunity_economics_business_fingerprint
    × opportunity_eligibility_ELIGIBLE_or_INELIGIBLE_or_UNKNOWN
    × opportunity_evaluation_FactBoundary

ShadowCloseOpportunityIdentity =
    CloseOpportunityEvaluationIdentity_where_eligibility_is_ELIGIBLE
```

The opportunity fingerprint consumes only facts through the first matched eligibility rule below.
It binds the normalized close-quote or attempt-terminal state first and appends commission, index,
and derived economics only when the ordered rule reaches those facts. Raw session/generation/
`change_id`, request id, source timestamp, receipt identity, and an equal-value repeated tick are
durable provenance only. A fact ignored by the first matched rule cannot change the business
identity or create another opportunity evaluation.

Eligibility is a first-match total order:

1. Known `UNEXECUTABLE | LEGGED_CLOSE_REFERENCE`, or
   `NOT_REQUESTABLE_KNOWN_ATOMIC_UNAVAILABLE`, is `INELIGIBLE`. Its fingerprint consumes only the
   normalized quote/attempt state; commission and index are ignored.
2. Quote `UNKNOWN`, `NOT_REQUESTABLE_UNKNOWN`, or matched RPC send/error/deadline/payload/frontier
   failure is `UNKNOWN`. Its fingerprint consumes only the normalized quote/attempt state;
   commission and index are ignored.
3. For `ATOMIC_COMBO_CLOSE_QUOTE`, a required commission fact that is missing, stale, malformed,
   negative, or otherwise not comparable is `UNKNOWN`. Its fingerprint additionally consumes only
   the normalized commission availability/currentness/classification; index is ignored.
4. For `ATOMIC_COMBO_CLOSE_QUOTE`, a known current commission above the frozen rate is
   `INELIGIBLE`. Its fingerprint additionally consumes the exact commission values and
   compatibility class; index is ignored and fee/net economics remain `null / UNKNOWN`.
5. For an atomic quote with known current compatible commissions, a missing, stale, malformed, or
   nonpositive index is `UNKNOWN`. Its fingerprint additionally consumes only the normalized index
   availability/currentness/classification.
6. Only `ATOMIC_COMBO_CLOSE_QUOTE` covering full `q`, bound to an official market-book source
   accepted strictly after first CLOSE, with current compatible option/catalog/index facts and
   matching Entry/Policy/structure/direction/quantity identities, is `ELIGIBLE`. This rule consumes
   the exact quote levels, commission and index values, gross/fee/net cashflows, projected PnL/loss,
   and every derived economic value.

Every `ELIGIBLE` evaluation atomically emits exactly one `SHADOW_CLOSE_OPPORTUNITY` carrying its
complete gross/fee/net/PnL/loss economics. Every quote evaluation on the first-CLOSE boundary
remains `PRE_CLOSE` and is not eligible. The same business fingerprint emits at most once. A later
change in `q`-relevant levels, normalized quote/classifier state, or facts actually consumed by the
first matched eligibility rule may create another evaluation while CLOSE remains latched. A new
official `change_id`, generation, request id, receipt, or equal-value repeated tick alone cannot.
Absence of an opportunity neither erases CLOSE nor proves a failed order, flatness, or Position
end.

## Durable future object minimum fields

Any later writer must strictly validate and persist:

- object semantic kind and content schema identity;
- code/runtime and every Policy identity;
- complete `FactBoundary` and consumed source identities;
- Radar episode, Candidate, entry, Position-action, and prior-object identities as applicable;
- canonical instruments, combo, signed directions, `q`, and full consumed levels;
- availability, action, reason, quote-state, and invalidation enums;
- all input units, gross/net economics, fee reserve, loss measures, and `null` availabilities;
- primary and ordered secondary reasons;
- source-currentness and completeness summary; and
- explicit public-quote-not-fill, no-exposure, no-Outcome, no-account-fee, and no-actual-all-in-loss
  non-claims.

Unknown member, missing required member, identity mismatch, non-finite number, unit mismatch,
non-full quantity, invalid enum, or arithmetic mismatch fails closed. Writers never overwrite a
conflicting identity.

## Denominators, zero, `null`, and `UNKNOWN`

Counts are distinct changed business identities after settled-state de-duplication, never market
messages, timer ticks, component legs, repeated calculations, or elapsed seconds.

Every Candidate has exactly one terminal admission-attempt outcome:
`ENTRY_EMITTED | KNOWN_COMPLETE_NO_ENTRY | KNOWN_INVALIDATED_BEFORE_REFRESH |
UNKNOWN_CONSUMED`. The first two consumed a complete refresh and contemporaneous complete
re-Underwriting; the third records a known ordered invalidation before such an evaluation; the
fourth includes send failure, timeout, transport/error, malformed/truncated response,
missing/unknown facts, or stale/ahead/contaminated frontier. Their counts sum exactly to distinct
Candidate identities. Failure and unknown outcomes are never dropped from that denominator.
Its immutable identity is `ScheduledAdmissionAttemptIdentity × terminal_outcome ×
terminal_FactBoundary`; the scheduled identity never mutates when `SENT` or terminal facts arrive.

| Metric | Numerator | Denominator, scope, and conditioning | Unit and `null` rule |
|---|---|---|---|
| Underwriting availability | three state counts; known-availability numerator = `NOT_EVALUATED + EVALUABLE`; evaluable numerator = `EVALUABLE` | all changed `UnderwritingAvailabilityEvaluationIdentity` values in one runtime/Policy/Radar scope | counts plus the two named fractions; either rate `null` if denominator zero/unknown |
| Underwriting action rate | each of `CANDIDATE | WATCH | ABSTAIN` | `EVALUABLE` Underwriting identities only | fraction; `UNKNOWN` excluded; `null` if denominator zero/unknown |
| Candidate activation rate | distinct Candidate identities | `EVALUABLE` Underwriting identities | fraction; `null` if denominator zero/unknown |
| admission-evaluable rate | `ENTRY_EMITTED + KNOWN_COMPLETE_NO_ENTRY` admission outcomes | every distinct Candidate / `ScheduledAdmissionAttemptIdentity` | fraction; the two non-evaluable outcome counts are reported separately; `null` if Candidate denominator zero/unknown |
| Shadow Entry rate | distinct `SHADOW_ENTRY` / `ENTRY_EMITTED` identities | `ENTRY_EMITTED + KNOWN_COMPLETE_NO_ENTRY` admission outcomes | fraction; `null` if denominator zero/unknown |
| Position known-action rate | every `PositionActionIdentity` whose action is `HOLD` or `CLOSE` | every distinct post-entry `PositionEvaluationIdentity` | fraction; action `UNKNOWN` excluded from numerator and counted separately; `null` if denominator zero/unknown |
| close-quote known-state rate | `CloseQuoteEvaluationIdentity` values classified atomic + legged + unexecutable | every distinct close-quote evaluation while a Shadow Position is open | fraction; quote `UNKNOWN` excluded from numerator and counted separately; `null` if denominator zero/unknown |
| close-opportunity rate while closing | distinct `ShadowCloseOpportunityIdentity` / `ELIGIBLE` evaluations | `CloseOpportunityEvaluationIdentity` values with eligibility `ELIGIBLE + INELIGIBLE` while CLOSE is latched | fraction; eligibility `UNKNOWN` excluded from numerator and denominator and counted separately; `null` if known-eligibility denominator zero/unknown |

For each reported rate, the artifact also names runtime, Policy identities, wall-clock interval,
conditioning event, numerator, denominator, unit, and unknown count.

`NOT_EVALUATED + UNKNOWN + EVALUABLE` equals all availability identities.
`CANDIDATE + WATCH + ABSTAIN` equals the `EVALUABLE` count. The four admission outcomes equal all
Candidate/attempt identities. A numeric claim of zero Candidates requires a known nonzero
`EVALUABLE` denominator. A numeric claim of zero Entries requires a known nonzero
admission-evaluable denominator. A numeric claim of zero close opportunities requires a known
nonzero `ELIGIBLE + INELIGIBLE` CloseOpportunityEvaluation denominator conditioned on
`CLOSE_LATCHED`; all-`UNKNOWN` economics therefore serialize `null`, never zero. A zero or unknown
denominator serializes rate `null`, never `0`.

No `SHADOW_ENTRY` means no Position, close opportunity, or Outcome object; it does not create an
`UNKNOWN` Outcome. Underwriting `UNKNOWN` has no economic action; Position `UNKNOWN` is a
serialized decision-availability result but never a `HOLD` or `CLOSE` instruction.

## Architecture and dependency rule

The future pure downstream owner consumes immutable public DTOs from `market_monitor`,
`options_domain`, and `short_vol_radar`. It never imports the runtime app and never causes a lower
layer to own economic Policy. Runtime composition may keep official public combo observation alive
for an open Shadow Position after the Radar episode ends. That lifecycle is bounded current state,
not a database, replay system, workflow engine, or service split.

No current package implements this boundary. A separate task must name and introduce the owning
module, strict Policy artifacts, runtime composition, writers/readers, and tests before any public
observation.

## Direct acceptance and non-claims

Direct contract verification must prove:

- both separate content identities and the absence of an admission Policy;
- exact required facts, source/currentness/completeness rules, and causal order;
- fee reserve versus actual-fee distinction and every arithmetic equation;
- all three loss measures plus `actual_all_in_max_loss_usdc = null / UNKNOWN`;
- total Underwriting action classification;
- Candidate terminal state and complete invalidation order;
- post-Candidate official refresh with a new source identity;
- strictly future Position evaluation, close latch, and all nine ordered predicates;
- action/quote orthogonality and full-quantity close-opportunity eligibility;
- denominator, natural-zero, `null`, and `UNKNOWN` rules; and
- compatibility with the unchanged accepted Radar boundary.

This contract requires no live market command, capture, replay, recomputation, or external
artifact. It does not prove implementation reachability, Candidate quality, closeability,
forecast skill, edge, profitability, account economics, all-in loss, Outcome, qualification,
promotion, deployment, or execution.

## Explicitly prohibited scope

- changing Radar Policy, detector truth, events, summaries, sealed evidence, or accepted hashes;
- adding runtime code, package scaffolding, CLI, writer/reader, Policy instance, or evidence schema
  without a separately active task;
- treating mark, mid, component legs, or a historical atomic event as executable economics;
- using private/account data to repair a public inference gap;
- defaulting fees, reserves, loss, missing facts, or denominators to zero;
- fixed holding duration, saved-data scan, replay, synthetic Candidate, synthetic Entry, or
  synthetic close opportunity;
- defining Shadow Outcome, forward cohort, counterfactual, `NO_TRADE`, PnL acceptance,
  qualification, Challenger, promotion, or execution here; and
- persistent deployment, credentials, margin, orders, fills, settlement action, capital, or money.
