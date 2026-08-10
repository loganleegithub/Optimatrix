# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_QUEUE_BACKLOG_REPAIR_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8675_FROM_MAIN_D5D4C88`

**Live commands:** `NONE_CONSUMED`

**Sole authorized closure:** `NONE`

## Current online boundary

The sole Online Runtime is serving `127.0.0.1:8675` from clean synchronized `main` at code
identity `d5d4c880ef28218bf2cde56be123074da5adba66`. Its runtime identity is
`sha256:4dd2b9887bdd1fc9c9b0ad3cb3bfe4374d5430b07c8f8632e9550cb000ac254a`.
It holds the single-instance lease for the stable Case repository
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`; no Case root was copied, migrated,
replaced, or deleted during the cutover.

The clean-stop inventory found zero schema-v5 Case, Control, Shadow Entry, Position, or Outcome
records. The one authorized post-start smoke completed `31/31` ready samples over more than
`60 s`. Every sample reported health, readiness, `RUNNING`, `CURRENT`, `KNOWN_COMPLETE`, inactive
queue backlog, and `128/128` current Radar coverage, with zero reconnects and zero protocol gaps.

Observed processing-queue lag was `0 ms` minimum, `99 ms` median, `650 ms` p95, and `693 ms`
maximum. Latest market-event age was `310 ms` minimum, `815 ms` median, `1,129 ms` p95, and
`1,340 ms` maximum. These measurements verify the accepted runtime transition and removal of the
previously reproduced backlog during the bounded smoke; they do not guarantee future uptime or
latency.

The accepted repair preserves the full cross-sectional surface and term dependencies while
reusing unchanged peers' current core calculations and recomputing only their dependent scores.
It adds no process, queue, worker, cache, retry, controller, dependency, schema, threshold, score
formula, market-universe change, or private input. The replaced all-peer core-recalculation path
has no remaining production implementation or compatibility branch.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. Its channel is
`INVERSE_BTC_SHORT_VOL_V2`, Workbench document schema is `7`, and durable Shadow Case family is
schema v5. It consumes Deribit production public BTC options and `btc_usd`, uses BTC-native
premium/fees/settlement/PnL, and labels current valuation as `USD_EQUIVALENT`.

There is no product selector, fallback product, compatibility profile, alternate online schema, or
in-process Policy switch. The repository contains only the three fixed V2 Inverse Policy
artifacts:

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
settlement action, actual exposure, or private execution. The accepted smoke and green repository
checks do not establish future uptime, source freshness, fillability, qualification, Edge, or
profitability.

All repair sampling, stop/start, Case reading, and live commands are consumed. A future live probe,
restart, state-root operation, Policy change, or roadmap-channel implementation requires a new
explicit task and permission update under the Delivery Contract.
