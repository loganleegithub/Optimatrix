# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`

## Purpose

Maintain the current Deribit BTC-USDC 0–72 hour option market in memory and tell the trader whether
target-size executable sell-side implied volatility remains unusually rich relative to an exact
causal, conservative multi-horizon BTC realized-volatility baseline. A positive state is a
reviewable Radar candidate, not merely a point-in-time anomaly. While a short-leg candidate is
active, independently report whether an existing official Deribit combo exposes the authorized
target-size 1:1 protective credit vertical.

The Radar is a current decision component. It does not persist anomaly, quote, no-anomaly, coverage,
or run-summary objects. It does not decide whether to enter a Shadow Case, place an order, prove a
fill, estimate actual account risk, or qualify a Policy.

## Authorized source and universe

- production endpoint `wss://www.deribit.com/ws/api/v2`;
- public methods only;
- active BTC-USDC linear options selected by actual expiry timestamp;
- `0 < TTE <= 72 hours` under trusted Deribit time;
- calls and puts evaluated separately;
- official option and combo metadata, option ticker, option/combo order books, BTC-USDC index,
  platform status, heartbeat, and public time;
- one exact target quantity and TTE-band Policy for the full run.

No private/account, RFQ, combo-creation, order, trade, fill, balance, margin, settlement act, or test
environment method is authorized. Component-leg prices cannot create official atomic availability.

## Current-state model

The transport stamps each accepted wire or send-control event with one consecutive
`session_epoch + ingress_seq` and `received_monotonic_ms`, then places it on one bounded queue. One
synchronous reducer owns all mutable market and Radar state. It never waits for network I/O.

Catalog, clock, platform, index, ticker, order-book, subscription generation, RPC lifecycle,
detector, episode, aggregate, and atomic state are current in-memory facts. A reconnect retires the
old epoch; recovery requires fresh current facts. Normal market updates and full books are never
written as product records.

## Detector truth

For each applicable option:

```text
UNKNOWN
NO_ANOMALY
ANOMALY_ACTIVE
```

`UNKNOWN` means a required fact is missing, stale, discontinuous, malformed, contradictory, or a
numerical interval spans a decision boundary. `NO_ANOMALY` requires usable inputs. An aggregate
`NO_ANOMALY` additionally requires complete relevant scope. One active instrument is a positive
witness even when unrelated instruments are unknown; aggregate coverage is then degraded rather
than erased.

An empty applicable universe is `NO_APPLICABLE_SCOPE`, not a vacuous `NO_ANOMALY`.

## Detector calculation

For one short-leg option at one causal boundary:

1. prove time-band applicability, option lifecycle, target quantity, target bid depth, forward,
   Delta eligibility, trusted causal index close history, and numerical domain;
2. solve Black total volatility from the consumed target-size executable bid;
3. convert total volatility to an IV interval over the trusted remaining-life interval;
4. form non-overlapping five-minute log returns from the same causal minute-close owner;
5. compute realized-variance rates over the trailing 30-minute, 120-minute, and 360-minute windows;
6. use the highest window variance rate or the annualized variance floor, whichever is more
   conservative for a short-vol screen;
7. classify the IV-richness interval against the Policy activation/clear boundaries.

The calculation is a causal candidate screen, not a delivery-TWAP forecast, event/calendar model,
surface-relative mispricing test, physical probability, model-free VRP estimate, or proven edge.
It uses no SPX-transferred parameter, fitted coefficient, or future observation. Numeric thresholds
live only in the content-identified Radar Policy.

The five-minute sampling choice follows BTC-specific evidence that five-minute realized variance
can outperform alternative realized measures. The multiple horizons follow the long-memory idea
behind HAR-RV, but A2 deliberately takes the maximum rather than importing or fitting a forecasting
regression. Bitcoin evidence also shows regime-dependent variance premia and asymmetric tail risk,
so this Policy does not turn historical VRP into a profitability claim. Deribit's 24/7 expiry and
weekend structure is not treated as SPX market hours or as an automatic weekend edge.

Design references:

- Takahiro Hattori, [Does 5-Minute RV Outperform Other Realized Measures in the Cryptocurrency
  Market?](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3416106);
- Fulvio Corsi, [A Simple Long Memory Model of Realized Volatility](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365738);
- Gkillas et al., [Forecasting realised volatility of Bitcoin](https://repository.up.ac.za/bitstream/handle/2263/84189/Gkillas_Forecasting_2021.pdf);
- [Bitcoin Options: Finding Edge in Four Years of Volatility Regimes](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/);
- [Selling Weekend Vol Revisited](https://insights.deribit.com/education/option-backtest-selling-weekend-vol-revisited/);
- Deribit [Contract Introduction Policy](https://support.deribit.com/hc/en-us/articles/25944688876957-Contract-Introduction-Policy).

## Episode semantics

One episode identity is namespaced by runtime, Radar Policy, short-leg instrument, and activation
causal sequence. Activation requires three qualifying countable observations separated by at least
five minutes, so the first-to-third span is at least ten minutes. Clear requires two qualifying
observations separated by at least five minutes. Repeated bytes, heartbeat, arbitrary polling,
display publication, unchanged recomputation, and multiple changes inside one separation interval
do not advance persistence.

An episode ends on clear, known ineligibility, scope/membership loss, required detector fact loss,
continuity loss, or run stop. A source gap ends it as unknown; a later resync requires fresh
activation. An explicitly declared adjacent-band boundary may suspend and resume the same episode
without treating normal index-publication timing as market blindness.

## Official atomic availability

While no episode is active, atomic state is `NOT_EVALUATED`. While active it is exactly:

```text
UNKNOWN
NO_ACTIVE_COMBO
NO_TARGET_SIZE_CREDIT_QUOTE
PUBLIC_ATOMIC_QUOTE_AVAILABLE
```

An official match requires:

- one active two-leg Deribit combo;
- same expiry and option type;
- exact 1:1 protective vertical orientation;
- exact target quantity permitted by published amount rules;
- current continuous combo book;
- full target quantity on the required bid or ask side;
- positive signed gross credit without taking an absolute value.

A positive available witness does not claim best price or complete-market optimality. Negative
absence states require complete relevant catalog, metadata, and book knowledge. Missing evidence is
`UNKNOWN`, not no-combo or no-credit.

## Trader handoff

After each settled transaction the Radar exposes current typed state to:

- the in-process Underwriting adapter;
- the read-only Workbench;
- bounded in-memory funnel diagnostics.

A trader-facing row should state the instrument, TTE, executable sell price, five-minute return
sampling, selected conservative horizon or floor, IV/baseline/richness, candidate episode state,
atomic state, blocker reason, and what change would upgrade or invalidate it.

Neither an anomaly nor an atomic quote is a durable record. Only a later admitted
`SHADOW_CASE_OPENED` may freeze the exact Radar and quote facts it consumed.

## Funnel diagnostics

The runtime may maintain non-durable counters for:

```text
APPLICABLE_MARKET_SCOPE
RADAR_KNOWN
ANOMALY_ACTIVE
STRUCTURE_REVIEWABLE
PUBLIC_ATOMIC_QUOTE_AVAILABLE
```

For knownness, one countable applicable instrument evaluation is partitioned exactly once:

- `startup_warmup`: the current Policy-band index tail is `WARMUP`, or that band has not yet
  produced an `AVAILABLE` tail in the runtime;
- `post_warmup`: the current tail is `AVAILABLE`, or the band was previously available and the
  current non-warmup state is `SOURCE_STALE`, `WINDOW_GAP`, or `CONTINUITY_GAP`.

A later `WARMUP` recovery interval returns to `startup_warmup`; it does not become a steady-state
loss. `INDEX_WARMUP` therefore remains visible in the startup/recovery projection but cannot be the
post-warmup primary blocker. The availability transition itself is post-warmup.

Canonical `APPLICABLE_MARKET_SCOPE` and `RADAR_KNOWN` counts use only post-warmup evaluations. The
projection outputs the exact numerator, denominator, ratio, and blocker counts for both partitions.
Every Radar UNKNOWN contributes exactly one bounded aggregate reason; exact instrument detail
remains in the current Radar rows. A post-warmup source-stale, window-gap, or continuity-gap loss is
not hidden as startup.

Counters are current operational product diagnostics. They are not research evidence, acceptance
receipts, Cohort denominators, or full-market reconstruction.

Candidate diagnostics keep two units distinct: instrument Episodes count every activated contract;
an activation batch collapses all same-option-type/same-band activations at one causal boundary.
The latter is the trader-readable count of temporally distinct volatility clues for this screen, but
it is not a claim of statistical independence across batches, directions, expiries, or regimes.

## Required verification

Direct tests own five-minute sampling, multi-horizon maximum and floor selection, causal warmup,
formula boundaries, missingness, continuity, episode persistence, exact combo orientation, target
depth, signed credit, one-reducer ordering, warmup partitioning, and finite UNKNOWN reasons. The
single separately authorized 43,200-second public observation may establish connectivity, a
positive post-warmup applicable denominator, the naturally observed known proportion, candidate
Episode count/duration/end reasons, and the naturally reached next funnel loss. It does not require
a natural candidate or Shadow admission, does not prove future frequency or edge, and creates no
durable Radar evidence. When no Shadow Case opens, durable Shadow Case files must remain zero.
