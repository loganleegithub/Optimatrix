# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`

## Purpose

Maintain the current Deribit BTC-USDC 0–72 hour option market in memory and tell the trader whether
target-size executable sell-side implied volatility is unusually rich relative to one exact causal
same-remaining-life baseline. While a short-leg anomaly is active, independently report whether an
existing official Deribit combo exposes the authorized target-size 1:1 protective credit vertical.

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
4. compute the frozen weighted causal trailing-index variance rate and annualized volatility;
5. classify the IV-richness interval against the Policy activation/clear boundaries.

The calculation is a pointwise hypothesis, not a delivery-TWAP forecast, physical probability,
model-free VRP estimate, or proven edge. Numeric thresholds live only in the content-identified
Radar Policy.

## Episode semantics

One episode identity is namespaced by runtime, Radar Policy, short-leg instrument, and activation
causal sequence. Activation and clear persistence use only countable changed economic observations.
Repeated bytes, heartbeat, arbitrary polling, display publication, and unchanged recomputation do
not advance persistence.

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

A trader-facing row should state the instrument, TTE, executable sell price, IV/baseline/richness,
episode state, atomic state, blocker reason, and what change would upgrade or invalidate it.

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

Counters are current operational product diagnostics. They are not research evidence, acceptance
receipts, Cohort denominators, or full-market reconstruction.

## Required verification

Direct tests own formula boundaries, missingness, continuity, episode transitions, exact combo
orientation, target depth, signed credit, and one-reducer ordering. A separately authorized bounded
public smoke may prove connectivity and at least one known formula evaluation. It does not require
a natural anomaly or Shadow admission and creates no durable Radar evidence.
