# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_SCHEMA7_8675_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8675_FROM_MAIN_6236F14`

**Live commands:** `NONE_CONSUMED`

**Sole authorized closure:** `NONE`

## Current online boundary

PR [#41](https://github.com/loganleegithub/Optimatrix/pull/41) merged the bounded V2 queue-
throughput repair to `main`; its topic branch was deleted. The sole replacement runtime was then
started from clean synchronized code identity
`6236f143a5a62cba30b95bcb723c50287725aba2` on `127.0.0.1:8675`, using the already-bound stable
root `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The owned execution session
remained active at the final non-invasive session poll.

The consumed post-start smoke completed its collection, but the tool response containing its
schema-v7 latency distribution and exact runtime identity was truncated before a retained result
could be recovered. No retry is authorized. Consequently, this Authority does not claim a measured
post-start latency distribution, an exact current runtime identity, or future absence of queue
backlog from that smoke.

The one authorized post-start official schema-v5 report completed successfully against the stable
root. It validated the exact Inverse product/Policy chain and reported zero opened, pending, mature,
censored, or incomplete Case rows across every enrollment kind and score band. The cutover therefore
created no Case, Control, Shadow Entry, Position, or Outcome and performed no Case migration, copy,
deletion, rewrite, Segment close, or recovery.

## Accepted throughput repair

Direct deterministic profiling of 200 single-option-book transactions over a 128-instrument
universe isolated the synchronous hotspot. Before the repair, transactions averaged `10.698 ms`;
`build_score_feature_contexts` consumed `1.798 s` because each local book fact constructed contexts
for all 128 instruments. The repair retains the complete cross-sectional ticker point set but builds
contexts only for the transaction's existing `recalculation_names`. The identical profile then
averaged `1.724 ms` per transaction, a bounded `83.9%` reduction and approximately `6.2x`
throughput improvement.

This is a locality repair, not a Policy or data-source change. It adds no process, queue, worker,
cache, retry, controller, dependency, schema, threshold, score formula, market-universe change, or
private input. Focused verification passed `246` tests; the full repository gate passed format,
Ruff, mypy, and `731` tests. These deterministic results establish removal of the measured local
hotspot, not future live latency or uptime.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. Its channel is
`INVERSE_BTC_SHORT_VOL_V2`, Workbench document schema is `7`, and durable Shadow Case family is
schema v5. It consumes Deribit production public BTC options and `btc_usd`, uses BTC-native
premium/fees/settlement/PnL, and labels current valuation as `USD_EQUIVALENT`.

There is no product selector, fallback product, compatibility profile, alternate online schema, or
in-process Policy switch. The repository contains only the three fixed V2 Inverse Policy artifacts:

```text
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d
Underwriting Policy identity: sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d
Position Policy identity:     sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe
```

The V2 score is an expert ordinal opportunity-ranking hypothesis, not a probability, oracle,
expected return, Edge, or profitability claim. The component-book lifecycle is a public-book
counterfactual, not an order, fill, atomic quote, liquidity reservation, or actual position.

## Permission and non-claims

Permission remains `PUBLIC_SHADOW`: no credential, account, balance, margin, order, fill, capital,
settlement action, actual exposure, or private execution. The observed session liveness, zero Case
report, deterministic profile, and green tests do not establish future uptime, source freshness,
fillability, qualification, Edge, or profitability.

All repair sampling, stop/start, Case reading, and live commands are consumed. A future live probe,
restart, state-root operation, Policy change, or roadmap-channel implementation requires a new
explicit task and permission update under the Delivery Contract.
