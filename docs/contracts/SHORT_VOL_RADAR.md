# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`

## Purpose

Maintain the current 0–72 hour Deribit `INVERSE_BTC_V1` option market in memory and tell the trader
whether a target-size executable sell-side implied-volatility witness is unusually rich relative to
one exact causal, conservative multi-horizon BTC realized-volatility baseline. The product is fixed
at startup; there is no product selector or fallback. A positive detector state is a selective
`RICHNESS_CLUE`, not a downstream Underwriting `CANDIDATE`, forecast, trade, or profitability claim.

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
`public/get_index_chart_data(index_name=btc_usd, range=1d)`. It accepts only a bounded
chronological array of positive finite `[timestamp, average_index_price]` pairs for that one index.
It exposes:

- response point count and interval histogram;
- modal timestamp interval;
- newest response timestamp and age;
- whether the newest response point falls outside the configured completion cutoff;
- latest confirmed point and age;
- exact consecutive five-minute suffix points and minutes;
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
5. convert raw bid, stressed bid, and ask native VWAPs through the fixed product's model rule,
   then invert Black total volatility from those model-domain prices;
6. derive the short-leg Delta interval and classify its explicit review bucket;
7. consume the exact confirmed five-minute average-index suffix and compute 30/120/360-minute
   realized-variance rates;
8. select the highest variance rate or the fixed annualized variance floor;
9. compare **one-tick-stressed executable bid IV** with that baseline;
10. apply the content-identified activation/clear hysteresis.

The clue-eligible Policy buckets are:

```text
TTE:   45m–6h | 6h–24h | 24h–72h
Delta: 0.05 <= |Delta| <= 0.40
```

`30m–45m` is review-only because the ten-minute activation span and 30-minute admission cutoff leave
insufficient conversion slack. Delta `<0.05` and `>0.40` remain visible review-only rows rather than
being mislabeled as comparable wing clues. A numerical Delta interval crossing an eligibility
boundary remains `UNKNOWN`.

Activation retains the existing `1.20` stressed IV/RV ratio, three qualifying observations, and at
least five minutes between observations; the first-to-third span is at least ten minutes. Clear
retains `1.05`, two observations, and five-minute separation. These are frozen screen parameters,
not qualified Edge estimates.

## Regime diagnostics

The baseline calculator also derives, for every declared horizon:

- positive and negative realized semivariance and shares;
- bipower variation;
- non-negative `RV - BV` jump variation and jump share;
- maximum absolute five-minute return;
- net log return.

The selected/highest-RV horizon supplies the row's regime context. Call clues label positive
semivariance as adverse; Put clues label negative semivariance as adverse. These finite-sample
statistics are descriptive and non-gating. They do not forecast delivery-period variance or turn
historical VRP into an Edge claim.

## Surface-lite diagnostics

For current, active, open same-expiry options with usable ticker Delta and mark IV, the review layer
may show:

- nearest ATM mark-IV proxy and its actual Delta;
- nearest 25-Delta Call and Put only when each lies within five Delta points;
- 25-Delta risk reversal when both proxies are usable;
- local same-type mark-IV interpolation around the clue's Delta;
- executable bid-IV midpoint minus that local mark-IV context;
- nearest adjacent-expiry ATM mark-IV difference.

Mark IV is diagnostic, not executable. Missing neighbours produce `PARTIAL/UNKNOWN`; they never
erase a known executable-bid witness. No fitted SVI, SABR, Heston, calendar forecast, or surface
mispricing claim is part of this slice.

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

## Transparent attention rank

The Workbench assigns a deterministic lexicographic rank, not an ML score. Ordering is by:

1. active detector witness;
2. clue-eligible TTE/Delta bucket;
3. stressed richness lower bound;
4. availability and value of surface residual;
5. availability and value of the best stressed legged credit/payoff-cap ratio;
6. lower adverse semivariance share and jump share;
7. tighter target spread and fewer consumed levels;
8. deterministic expiry/type/Delta/strike/name tie-breakers.

The default view is bounded Top-N; `ALL` remains available. Every row exposes the ordered rank inputs.
Rank changes attention only and cannot change any business truth.

## Episode semantics

One Episode identity is namespaced by runtime, fixed product, Radar Policy, instrument, and
activation causal sequence. Repeated bytes, heartbeat, polling, display publication, unchanged recomputation, and
multiple changes inside one separation interval do not advance persistence.

An Episode ends on clear, known ineligibility, transition into a review-only bucket, membership or
scope loss, hard-screen fact loss, history revision/gap/staleness, continuity loss, or run stop.
After any source loss, fresh activation observations are required.

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

## Trader handoff and persistence

After each settled transaction the Radar exposes typed current state to the in-process Underwriting
adapter, read-only Workbench, and bounded funnel diagnostics. A row states source contract,
TTE/Delta bucket, target bid/ask, tick stress, raw and stressed IV/richness, selected baseline,
regime, surface, protective structure, official atomic diagnostic, rank, blocker, and invalidation
condition.

No market fact, clue, diagnostic, rank, atomic quote, funnel counter, probe result, or Workbench
snapshot is a durable product record. Only a later admitted `SHADOW_CASE_OPENED` may freeze consumed
Radar, frozen structure, component-book, and atomic-diagnostic facts.

## Required verification

Direct tests own source shape/cadence/revision state, tick regimes, two-sided target depth, one-tick
stress, Black inversion, TTE/Delta review buckets, five-minute multi-horizon baseline, regime
statistics, surface-lite limitations, fee-cap arithmetic, protective-leg display ranking,
Underwriting-selector separation, ranking
determinism, episode persistence/end reasons, official combo semantics, reducer ordering, and
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
