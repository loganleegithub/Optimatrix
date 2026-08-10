# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_REVIEW_TRUTH_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8675_FROM_MAIN_9A4CC23`

**Live commands:** `NONE_CONSUMED`

**Sole authorized closure:** `NONE`

## Current online boundary

The sole Online Runtime is serving `127.0.0.1:8675` from clean synchronized `main` at code
identity `9a4cc23cb9092a04b0a6e72eec6657a570660c73`. Its runtime identity is
`sha256:9d383a7d19027c09324d1b811caeef90184dd1065a2bcff226b6df665c1e4432`.
It holds the single-instance lease for the stable Case repository
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`; no Case root was copied, migrated,
replaced, or deleted during the cutover.

The review-truth implementation was merged by
[PR #44](https://github.com/loganleegithub/Optimatrix/pull/44); its one-stop/one-start cutover was
authorized by [PR #45](https://github.com/loganleegithub/Optimatrix/pull/45). Immediately before
stop, the old runtime had 41 research activation batches, 38 selected decisions, 38
`KNOWN_NO_CONTROL` terminals, and zero schema-v5 Case, Control, Shadow Entry, Position, or Outcome
records. The accepted cutover used the unchanged stable root and port 8675.

The authorized post-start gate completed `31/31` samples over `302.1 s`. Every sample reported
health, readiness, `RUNNING`, `CURRENT`, `KNOWN_COMPLETE`, inactive queue-lag currentness, and
`128/128` current Radar coverage. The post-gate snapshot still had zero reconnects and zero
protocol gaps.

The current option universe contained zero rows in the 30-to-45-minute review-only TTE band during
the gate, so live review-only confirmation violations were zero but the live window did not exercise
a non-empty review-only band. Direct deterministic coverage remains the acceptance evidence that an
ineligible review row stays `IDLE` with `0` confirmation. Across all current rows, the gate observed
18-to-23 `CONFIRMING` rows and zero-to-four `ACTIVE` rows.

By the final gate sample, lost nonzero pre-activation confirmation was attributed to 13
`CORE_UNKNOWN`, 36 `LEADER_CHANGE`, 9 `SCOPE_LOSS`, and 6 `SCORE_BAND_CHANGE` resets. These are
reset events, not distinct Episodes or a market-frequency estimate. One prospective research batch
selected one `ABSTAIN` decision and terminated as one `KNOWN_NO_CONTROL`; its one fixed reason was
`RADAR_EPISODE_OR_REVIEW_ENDED`, so the reason and terminal denominators conserved `1 = 1`. It
opened no Case, Control, Shadow Entry, Position, or Outcome.

Observed processing-queue lag was `0 ms` minimum, `278 ms` median, `2,303 ms` p95, and `4,560 ms`
maximum. Latest market-event age was `299 ms` minimum, `929 ms` median, `2,677 ms` p95, and
`5,057 ms` maximum. Wire-message age was `0 ms` minimum, `244 ms` median, `2,310 ms` p95, and
`4,569 ms` maximum. These measurements establish the bounded cutover result, not future uptime,
latency, market frequency, Policy quality, Edge, or profitability.

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
