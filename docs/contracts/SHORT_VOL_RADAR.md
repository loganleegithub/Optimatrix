# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`

## Purpose

Maintain the current 0–72 hour Deribit `INVERSE_BTC_V1` option market in memory and rank
target-size executable sell-side volatility opportunities with the sole
`INVERSE_BTC_SHORT_VOL_V2` ordinal score. The score combines premium evidence with observable
path/liquidity quality. It is a conditional-quality-lift hypothesis, not an oracle, calibrated probability,
expected return, downstream Underwriting `CANDIDATE`, trade, or profitability claim.

The Radar separately supplies a ranked protective-vertical review and reports official
atomic-combo availability as a diagnostic. Review context cannot create detector truth. One frozen
protective-leg identity may feed the separate component-book Underwriting calculator; it still does
not create admission or execution permission by itself.

## Authorized sources and universe

- production endpoint `wss://www.deribit.com/ws/api/v2` and public methods only;
- active Inverse BTC options selected by actual expiry timestamp and exact product metadata;
- trusted-time scope `0 < TTE <= 72 hours`, with the final 30 minutes excluded;
- Calls and Puts evaluated separately;
- official option/combo metadata, aggregated `agg2` option ticker and option order books, combo order
  books, the fixed product's streaming `btc_usd` index and matching index-chart history, platform
  status, heartbeat, and public time;
- one exact target quantity, product identity, and matching content-identified Policy chain for the
  full run.

No private/account, RFQ, combo-creation, order, trade, fill, balance, margin, settlement act, or test
environment method is authorized. Component-leg prices cannot create official atomic availability,
but may create the explicitly non-atomic Shadow counterfactual defined by the Underwriting contract.

## Source contract

`IndexHistoryReducer` is the sole validator and bounded in-memory owner of
`public/get_index_chart_data(index_name=btc_usd, range=2d)`. It accepts only a bounded
chronological array of positive finite `[timestamp, average_index_price]` pairs for that one index.
It exposes:

- response point count and interval histogram;
- modal timestamp interval;
- newest response timestamp and age;
- whether the newest response point falls outside the configured completion cutoff;
- latest confirmed point and age;
- exact consecutive source-confirmed UTC-epoch-aligned five-minute suffix points and minutes;
- completed-overlap revision count, pending state, and revised timestamps.

The owner never interpolates, backfills, persists, or synthesizes a missing point. A completed-point
revision makes the history `REVISION/UNKNOWN` until one subsequent response confirms the replacement
values. `WARMUP`, `SOURCE_STALE`, `WINDOW_GAP`, and `REVISION` are local history facts; none triggers
a streaming-index reconnect. The streaming index remains the separate owner of current price and
currentness.

## Product and unit boundary

The fixed `INVERSE_BTC_V1` product specification is immutable and binds market family, exact source
metadata, native option-price and settlement currency, strike currency, price index,
economic-semantics version, model-normalization rule, valuation-conversion rule, fee rule, payoff
convention, and Case schema. The Radar Policy must bind the same product identity; any mismatch or
foreign-product leg is rejected before it can create Radar or downstream truth.

Depth walking and adverse tick stress always occur first in the exchange-native BTC premium unit.
The product-owned model conversion multiplies native premium by the declared expiry forward before
Black inversion. The forward is a model input, not the current cash-valuation index. BTC-native
cashflows are separately valued at the causal `btc_usd` index and labeled `USD_EQUIVALENT`; they are
not USDC cashflows or account-margin facts.

## Detector truth

For each applicable option:

```text
UNKNOWN
NO_ANOMALY
ANOMALY_ACTIVE
```

`UNKNOWN` means a required hard-screen fact is missing, stale, discontinuous, malformed,
contradictory, revised, or numerically unresolved. `NO_ANOMALY` requires usable hard-screen facts
but may include a known review-only TTE or Delta row. `ANOMALY_ACTIVE` is a known positive witness.
An unrelated unknown instrument does not erase that witness; aggregate negative absence still
requires complete relevant scope.

## Hard-screen calculation

For one short-leg option at one causal boundary:

1. prove the fixed product identity, trusted TTE applicability, lifecycle, target amount rules,
   current forward, and OTM status;
2. consume full target quantity from both bid and ask; reject an absent side, locked/crossed target
   VWAP, or invalid amount grid;
3. consume official native `tick_size` and `tick_size_steps` metadata;
4. move every consumed bid level down by one native legal tick, respecting tick-regime boundaries;
   a non-positive stressed price is known ineligible;
   target-spread distance is integrated across every crossed tick regime rather than divided by the
   tick size at only the first bid level;
5. convert raw bid, stressed bid, and ask native VWAPs through the fixed product's model rule,
   then invert Black total volatility from those model-domain prices;
6. derive the short-leg Delta interval and classify its explicit review bucket;
7. consume the exact source-confirmed UTC-epoch-aligned five-minute `average_price` suffix and
   compute the
   Policy band's realized-variance rates;
8. form the reference rate as the larger of the variance floor and
   `0.5 × maximum window rate + 0.5 × mean window rate`;
9. map **one-tick-stressed executable bid IV / reference RV** into premium anchor `A`;
10. derive required path quality `D` and target-book liquidity quality `E`, plus optional signed
    surface `S` and adjacent-term `T` adjustments when their exact causal neighbours exist;
11. compute the V2 score interval and apply content-identified activation/clear hysteresis.

The clue-eligible Policy buckets are:

```text
TTE:   45m–6h | 6h–24h | 24h–72h
Delta: 0.05 <= |Delta| <= 0.40
```

`30m–45m` is review-only because the ten-minute activation span and 30-minute admission cutoff leave
insufficient conversion slack. Delta `<0.05` and `>0.40` remain visible review-only rows rather than
being mislabeled as comparable wing clues. A numerical Delta interval crossing an eligibility
boundary remains `UNKNOWN`.

The five-minute horizons and persistence are:

| TTE band | horizons (minutes) | activation observations / separation | clear |
| --- | --- | --- | --- |
| 30m–45m review only | 30 / 120 / 360 | no clue | no clue |
| 45m–6h | 30 / 120 / 360 | 3 / 60 s | 2 / 60 s |
| 6h–24h | 120 / 360 / 720 | 3 / 150 s | 2 / 150 s |
| 24h–72h | 360 / 720 / 1440 | 3 / 300 s | 2 / 300 s |

Activation requires `score.lower >= 65`; clear requires `score.upper <= 50`. A numerical interval
that overlaps either threshold is known `REVIEW/HOLD`, not source `UNKNOWN`. These are frozen expert
priors, not qualified Edge estimates.

## V2 score contract

All weights, knots, saturation points, and thresholds below are exact Radar Policy members:

```text
A = piecewise richness: ratio <= 1 -> 0; 1.20 -> 0.80; ratio >= 1.30 -> 1
S = clip((stressed bid-IV midpoint - local mark IV) / 0.10, -1, 1)
T = clip((current ATM mark IV - immediate next-longer-expiry ATM mark IV) / 0.10, -1, 1)
D = clip(1 - 0.5 * adverse semivariance share - 0.5 * jump share, 0, 1)
E = 0.7 * spread_quality + 0.3 * depth_quality
PremiumEvidence = clip(A + 0.10*S + 0.05*T, 0, 1)
RiskQuality = 0.60*D + 0.40*E
Score = 100 * PremiumEvidence * (0.40 + 0.60*RiskQuality)
```

`spread_quality` declines linearly from one at one target-spread tick to zero at ten ticks.
`depth_quality` declines linearly from one at two total consumed bid-plus-ask levels to zero at ten.
S/T missingness contributes zero adjustment but remains an explicit `UNKNOWN` feature with a reason;
it is never stored as an observed zero or neutral 50%. D/E are required for a known score. The
server exposes the numerical score interval, LOW `[0,50)`, MID `[50,65)`, or HIGH `[65,100]`,
premium/risk decomposition, coverage, missing mask, raw inputs, and normalized contributions.

Every score-packet Decimal is serialized from its full coefficient in fixed-point form, with only
non-significant trailing fractional zeros removed. Serialization must not invoke an ambient
precision context or round a raw input. The one policy-aware packet validator restores those raw
values and reproduces the exact A/S/T/D/E factors, aggregates, score interval, band, coverage, and
diagnostics before the packet may enter a durable Case.

S/T are optional cross-sectional observations, not independent clocks. `S` freezes the maximum
source-timestamp skew across the target ticker and the same-type lower/upper interpolation
neighbours. `T` freezes the skew between the current-expiry and immediate-next-longer-expiry ATM
proxies. Each adjustment is usable only when all contributors carry source time and the skew is at
most `6000 ms`; otherwise that factor is explicitly missing while A/D/E may still produce a
`PARTIAL` score. This local rule does not replace the separate `300000 ms` ticker source-staleness
deadline or make every current ticker mutually synchronous.

## Regime diagnostics

The baseline calculator also derives, for every declared horizon:

- positive and negative realized semivariance and shares;
- bipower variation;
- non-negative `RV - BV` jump variation and jump share;
- maximum absolute five-minute return;
- net log return.

The maximum-RV horizon supplies the row's regime context. Call clues label positive
semivariance as adverse; Put clues label negative semivariance as adverse. These finite-sample
statistics supply the bounded path-quality input but do not forecast delivery-period variance or
turn historical VRP into an Edge claim.

## Surface-lite diagnostics

For current, active, open same-expiry options with usable ticker Delta and mark IV, the review layer
may show:

- nearest ATM mark-IV proxy across Calls and Puts and its actual Delta, only within five Delta
  points of absolute `0.50`;
- nearest 25-Delta Call and Put only when each lies within five Delta points;
- 25-Delta risk reversal when both proxies are usable;
- local same-type mark-IV interpolation around the clue's Delta;
- executable bid-IV midpoint minus that local mark-IV context;
- immediate next-longer-expiry ATM mark-IV difference; if no longer expiry is current, `T` is
  explicitly `UNKNOWN` rather than reversing the comparison against a shorter expiry.

Mark IV is not executable. The local and next-longer-expiry residuals may provide only their bounded
optional score adjustments. Missing neighbours remain explicit and contribute no adjustment; they
never erase a known executable-bid witness. No fitted SVI, SABR, Heston, calendar forecast, or
surface-mispricing claim is part of this slice.

## Unsigned OI/gamma diagnostic

When current public ticker `open_interest` and absolute option gamma are both usable, the Radar may
show `open_interest × abs(gamma)` and that instrument's share of the matching expiry/bucket total.
It preserves raw inputs, source currentness, and missing reason. It never converts the value into a
signed dealer inventory, dollar GEX, support/resistance, pin target, or score contribution;
`dealer_gamma_sign` is always `UNKNOWN` under public-only data.

## Protective-vertical structure review

The review layer may enumerate at most three same-expiry, same-type 1:1 protective legs from the
same product. It uses target-size short bid and long ask, stresses the short bid down and long ask up
by one native legal tick, and applies each public standard option fee in the product's native
settlement currency including the premium cap. It shows native credit and fees plus an explicitly
labeled causal valuation projection, USD-defined width/payoff cap, max loss after fee reserve, and
credit/payoff-cap ratio. Inverse BTC liability at settlement depends on settlement price; actual
account margin remains `UNKNOWN`. Ordering uses the declared valuation unit: descending
credit/payoff-cap ratio, descending stressed net credit, narrower width, then instrument name.

These three rows are a trader display and attention aid only. They do not select or freeze the
formal protective leg. The downstream Underwriting composition separately enumerates every legal
target-size component quote, invokes the sole component-book calculator, and hands its economics to
the Underwriting-owned selector. The review object itself cannot create a Candidate or Case.

This state is exactly `LEGGED_REFERENCE_NOT_ATOMIC`. It carries explicit non-claims:

```text
NOT_AN_ORDER
NOT_A_FILL
NOT_AN_ATOMIC_QUOTE
NO_LIQUIDITY_RESERVATION
CANDIDATE_REQUIRES_STRICTLY_LATER_PAIRED_REFRESH
```

## Bucket leader and attention order

The decision bucket is `(TTE band, expiry, option type, Delta bucket)`. Each bucket has at most one
leader. An already-active frozen leader remains first; otherwise ordering is score lower bound,
raw-richness lower bound, tighter target spread, fewer total consumed levels, strike, then
instrument name. An unknown competitor degrades bucket coverage but does not erase a known leader.
Leader change resets pre-activation confirmation; after HIGH or research-review confirmation the
leader is frozen until that Episode ends. Only the leader advances persistence or enrollment.
Rows whose TTE band or Delta bucket is review-only never enter `CONFIRMING`, never accumulate a
confirmation observation, and never form a HIGH or LOW/MID Episode. Workbench may display their
server-settled score band, but must label the exact TTE/Delta review constraint instead of rendering
`0/N` as confirmation progress.

The default Workbench view is bounded Top-N with `ALL` available. It displays the server-owned V2
score and leader truth and never recomputes either in the browser.

## Episode semantics

One HIGH Episode or LOW/MID research-review Episode identity is namespaced by runtime, fixed
product, Radar Policy, bucket, leader, score band, and confirmation causal sequence. Repeated bytes,
heartbeat, polling, display publication, unchanged recomputation, and multiple changes inside one
separation interval do not advance persistence.

The Episode freezes its canonical activation score packet. Composition must use that packet at the
activation causal boundary even if a mutable current-packet projection is absent; a later packet
cannot be substituted for the activation witness.

An Episode ends on clear/band exit, known ineligibility, transition into a review-only TTE bucket,
leader change before freeze, membership or scope loss, required core-score fact loss, history
revision/gap/staleness, continuity loss, or run stop. After any source loss, fresh observations are
required. A confirmed LOW/MID research-review Episode can be designated at most once and cannot
repeat until it has ended and a later Episode completes fresh persistence.

Ordered queue-lag currentness is a global decision pause, not a source observation. While it is
active, current evaluations and bucket coverage are `UNKNOWN`, no persistence observation is
counted, and no Episode, Candidate, or Case can open. A bucket with no active Episode retains only
its already-accepted pre-activation leader, band, and count through that pause. Catch-up recomputes
current truth: the same leader and band may continue from the retained count, while leader, band,
scope, or persistent core change applies the normal reset. An already-active Episode remains
fail-closed and ends on required core loss; queue lag never extends active decision authority.

A ticker application is a distinct persistence observation only when forward, signed Delta, or
mark IV changes. OI/gamma-only changes refresh the unsigned diagnostic but do not advance score
confirmation. Because S/T may select either option type and the adjacent expiry, a ticker change
recomputes both Call and Put peers on the affected expiry and the immediately shorter expiry whose
`T` uses it as the next-longer term. Unchanged polling and timestamp-only updates remain
non-countable.

## Official atomic diagnostic

While no Episode is active, atomic state is `NOT_EVALUATED`. While active it is exactly:

```text
UNKNOWN
NO_ACTIVE_COMBO
NO_TARGET_SIZE_CREDIT_QUOTE
PUBLIC_ATOMIC_QUOTE_AVAILABLE
```

An official match requires one active two-leg Deribit combo, same expiry/type, exact protective
orientation and ratio, valid target quantity, current continuous combo book, full target depth on
the required side, and positive signed gross credit. This state does not create or veto the
component-book Shadow funnel. In particular, `NO_ACTIVE_COMBO` is not evidence of absent single-leg
liquidity or absent strategy economics.

## Funnel diagnostics

Canonical `APPLICABLE_MARKET_SCOPE` and `RADAR_KNOWN` counts use post-warmup evaluations. Startup
and recovery remain separately visible, so `INDEX_WARMUP` remains visible without becoming a
steady-state blocker. After first availability, history stale/gap/revision and live-index continuity
loss remain post-warmup UNKNOWN. Every Radar UNKNOWN contributes exactly one bounded aggregate reason; counters are current diagnostics, not research evidence or qualification denominators.
When a bucket loses a nonzero but not-yet-confirmed observation count, the reducer increments one
fixed reset reason: leader change, score-band change, core UNKNOWN, scope loss, clue ineligibility,
or run stop. The counter is runtime-local, non-durable, and is neither an Episode count nor a market
frequency estimate; zero-observation state alignment does not increment it. A transient ordered
queue-lag pause that preserves the count is not a loss and therefore increments no reset reason.

## Trader handoff and persistence

After each settled transaction the Radar exposes typed current state to the in-process Underwriting
adapter, read-only Workbench, and bounded funnel diagnostics. A row states source contract,
TTE/Delta bucket, target bid/ask, tick stress, raw and stressed IV/richness, mixed reference
baseline, five score inputs and interval, coverage/missing reasons, bucket leader, optional unsigned
OI/gamma diagnostic, protective structure, official atomic diagnostic, blocker, and invalidation
condition.

No market fact, score, clue, diagnostic, rank, atomic quote, funnel counter, probe result, or
Workbench snapshot is a durable product record. Only a later `SHADOW_CASE_OPENED` may freeze the
same minimal V2 score-packet shape at selection and strictly later entry refresh together with the
consumed structure, component-book, and atomic-diagnostic facts.

## Required verification

Direct tests own source shape/cadence/revision state, `2d` request shape, tick regimes, two-sided
target depth, one-tick stress, Black inversion, TTE/Delta review buckets, band-specific five-minute
mixed baseline, every score normalization/interval/missing rule, leader determinism, HIGH and
LOW/MID persistence/end reasons, unsigned OI limitations, fee-cap arithmetic, protective-leg
display ranking, Underwriting-selector separation, official combo semantics, reducer ordering, and
bounded UNKNOWN reasons.

Only an explicit `CURRENT_STAGE` may authorize production-public read-only observation. A bounded
currentness/product-isolation gate may establish only the facts it actually observes before the
same process continues waiting for a natural Outcome. A rejected or consumed gate grants no retry.
Neither a gate nor continued observation may tune Policy, require a clue by a deadline, or prove
frequency, fillability, Edge, profitability, qualification, deployment, or execution permission.

## Design references

- Takahiro Hattori, [Does 5-Minute RV Outperform Other Realized Measures in the Cryptocurrency
  Market?](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3416106)
- Fulvio Corsi, [A Simple Long Memory Model of Realized Volatility](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365738)
- Deribit [`public/get_index_chart_data`](https://docs.deribit.com/api-reference/market-data/public-get_index_chart_data)
- Deribit [`public/get_instrument`](https://docs.deribit.com/api-reference/market-data/public-get_instrument)
- Deribit [Fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees)
- Deribit, [Bitcoin Options: Finding Edge in Four Years of Volatility Regimes](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/)
