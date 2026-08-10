# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_8675_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_CURRENT_8675_FRESH_SCHEMA_V5`

**Live commands:** `NONE_AUTHORIZED_8675_LATENCY_SAMPLE_CONSUMED`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_MARKET_LATENCY_ATTRIBUTION`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_MARKET_LATENCY_ATTRIBUTION.md)

## Active latency-attribution result

The trader reports that the generic Workbench market-delay value repeatedly exceeds `5,000 ms`.
The one authorized loopback-only, read-only sample of `/api/workbench/current` ran for at most 45
seconds and is consumed. All `45 / 45` observations were `RUNNING / CURRENT / ready` with
`KNOWN_COMPLETE 128 / 128`, `0` reconnects, `0` session gaps, and no
`QUEUE_LAG_CURRENTNESS` anywhere in the snapshot. Maximum generic source-event age was `4,616 ms`;
maximum last-wire age was `4,068 ms`.

Code inspection establishes that schema-v6 `data_delay_ms` subtracts the newest accepted exchange
source timestamp from trusted time. It is source-event age, not receive-to-reducer processing lag.
The active task may correct that non-durable Workbench schema and expose the already-owned queue
lag separately. The bounded observation does not prove a synchronous runtime hot path, so no
performance architecture or Decision Policy change is authorized.

This authority permits no further live command, stop, restart, second process, state-root operation,
external public-source probe, PID/log/resource inspection, Policy change, Case write, or deployment.
Any later live validation or deployment requires a subsequent explicit authority update.

## Current online boundary

The causal-coherence repair is deployed as the sole `INVERSE_BTC_SHORT_VOL_V2` Online Runtime. At
`2026-08-10T17:59:55+08:00`, the bounded same-frame smoke at
`http://127.0.0.1:8675` reported:

```text
channel:                      INVERSE_BTC_SHORT_VOL_V2
Workbench schema:             6
code identity:                a2de69894dbcc5913c414f4074506340c991c587
runtime identity:             sha256:4421619ac60b840c374c0bfee23e2cdb70abb8c21f3fabe9f621ef337ebdea38
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d
Underwriting Policy identity: sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d
Position Policy identity:     sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe
observed service state:       RUNNING / CURRENT / health / ready
declared GET routes:          6 / 6 HTTP 200
declared HEAD routes:         6 / 6 HTTP 200
coverage state:               KNOWN_COMPLETE, 128 / 128 instruments
current Radar rows:           128
Shadow Entry rows:            0
Position rows:                0
Outcome rows:                 0
Decision Control rows:        0
```

The one authorized start used the fresh stable root
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The official schema-v5 report
validated its exact product/Policy chain with `0` Case directories. The start and bounded smoke are
consumed; no restart, second root, repoint, or additional live operation is authorized.

## Superseded service and durable roots

Before the new start, all six declared routes at `127.0.0.1:8765` refused connection. The prior H2
process was therefore already absent; this cutover issued no stop command and wrote no Segment
close to its root. Its stable repository
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2` was preserved in place and the official
schema-v5 report found `0` Case directories.

The historical V1 `/private/tmp/optimatrix-inverse-btc-stable-97AYba` repository also remains
untouched. No Case was copied, migrated, rewritten, deleted, or recovered from either prior root
into the new V2-v9 epoch.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. It consumes Deribit production public BTC
options and `btc_usd`, uses BTC-native premium/fees/settlement/PnL, and labels current valuation as
`USD_EQUIVALENT`. Its accepted durable family is schema v5. There is no product selector, fallback
product, compatibility profile, alternate online schema, or in-process Policy switch. The
repository contains only the three fixed V2 Inverse Policy artifacts shown above.

The V2 score is an expert ordinal opportunity-ranking hypothesis, not a probability, oracle,
expected return, Edge, or profitability claim. The component-book lifecycle is a public-book
counterfactual, not an order, fill, atomic quote, liquidity reservation, or actual position.

## Current funnel observation and non-claims

In the accepted same-frame snapshot, post-warmup `RADAR_KNOWN` was
`107,371 / 113,251`; the earliest measured loss was `OPTION_BOOK_UNKNOWN`, with `5,880` total
blocked evaluations at that stage including `128` `POST_STATUS_BOOTSTRAP_REQUIRED`. No anomaly
Episode, Candidate, Shadow Case, or mature Outcome had formed. These are rapidly changing current
runtime diagnostics, not an opportunity-frequency or Policy-quality estimate.

The permission remains `PUBLIC_SHADOW`: no credential, account, balance, margin, order, fill,
capital, settlement action, actual exposure, or private execution. Current health and coverage do
not establish future uptime, fillability, qualification, Edge, or profitability. A future service
operation, Policy change, or new roadmap channel requires a new active task and explicit permission
update under the Delivery Contract.
