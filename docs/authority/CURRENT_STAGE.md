# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_SCHEMA7_8675_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_CURRENT_8675_STABLE_SCHEMA_V5`

**Live commands:** `ONE_QUEUE_REPAIR_8675_CLEAN_CUTOVER_AUTHORIZED`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_QUEUE_THROUGHPUT_REPAIR`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_QUEUE_THROUGHPUT_REPAIR.md)

## Active queue-throughput repair authority

The trader reports that schema v7 currently shows both market-event age and queue-processing lag
elevated. The accepted pre-task facts already prove that `QUEUE_LAG_CURRENTNESS` can intermittently
drop `RADAR_KNOWN` from `128 / 128` to `0 / 128` without a reconnect or session gap. The largest
current blocker is therefore `QUEUE_PROCESSING_THROUGHPUT_INTERMITTENT`, not the removed schema-v6
label ambiguity.

The one at-most-60-second loopback sample is consumed. Its client collected the frames but failed
while serializing tuple-keyed state counts, so no sample aggregate survived and no retry is
authorized. Static inspection plus a deterministic 128-instrument profile independently isolated
the hot path: 200 single-book transactions averaged `10.698 ms` each, while rebuilding all score
feature contexts consumed `1.798 s` of their `2.137 s` cumulative transaction time. The local
repair keeps all cross-sectional ticker points but builds contexts only for the transaction's
existing `recalculation_names`; the identical profile then averaged `1.724 ms` per transaction, a
bounded `83.9%` reduction with unchanged Decision inputs and formulas.

Static code inspection, focused tests, and the repository gate remain permitted. The task may
repair only this measured synchronous reducer hot path; it may not change a Policy, threshold,
market universe, score, Case schema, or public/private boundary.

The pre-stop inventory is consumed. Its same-frame Workbench snapshot was
`RUNNING / CURRENT / ready`, `KNOWN_COMPLETE 128 / 128`, with market-event age `5,147 ms`, wire age
`3,784 ms`, queue-processing lag `4,129 ms` against the `5,000 ms` deadline, and zero reconnects or
session gaps. It reported no Shadow Entry, Position, Outcome, Decision Control, or canonical
`SHADOW_CASE_OPENED`. The official schema-v5 report found zero Case rows in every view for the
already-bound stable root `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`.

Durable cutover effect is exactly `NONE`: there is no admitted Entry Segment to close or recover,
and no Case will be migrated, copied, deleted, or rewritten. The active task may mark PR #41 ready,
merge it to `main`, delete its local and remote topic branch, clean-stop only the currently owned
8675 runtime session, verify the six declared routes refuse connection, and start exactly one
replacement from clean synchronized `main` using the same stable root and port.

One bounded post-start smoke may inspect all six GET/HEAD routes, schema/code/runtime/Policy
identities, and at most 60 seconds of the three schema-v7 latency values plus
service/readiness/coverage and FactBoundary progress, followed by one official Case report. No
retry, second root/process, Policy change, Case migration, PID/log/resource inspection, or
additional restart is authorized.

## Completed latency-attribution result

Schema v6 mislabeled newest accepted exchange-event age as generic market delay. The consumed
pre-stop frame also proved a separate intermittent reducer backlog by reporting
`QUEUE_LAG_CURRENTNESS` with `0 / 128` known instruments while reconnect and session-gap counts
remained zero. Schema v7 now exposes exchange-event age, local wire silence, and receive-to-reducer
processing lag as separate values. It does not claim that the measured reducer backlog is fixed.

PR #39 merged this non-durable attribution change without modifying the product or any of the three
Policy artifacts. Its topic branch was deleted locally and remotely. The clean cutover reused the
already-bound stable root after the official pre-stop reader found `0` Case rows, so there was no
Segment to close or recover and no Case was migrated, copied, deleted, or rewritten.

The one stop, one start, and bounded post-start smoke are consumed. No further live command,
restart, second process, state-root operation, external public-source probe, PID/log/resource
inspection, Policy change, or Case write is authorized.

## Current online boundary

The sole `INVERSE_BTC_SHORT_VOL_V2` Online Runtime is deployed at
`http://127.0.0.1:8675`. The consumed post-start same-frame smoke reported:

```text
channel:                      INVERSE_BTC_SHORT_VOL_V2
Workbench schema:             7
code identity:                982c5be3db1bdc077cd398e6ea572c0855ccd09b
runtime identity:             sha256:0ddf1b13e1039c98588b8457dd44277c698628f1238ae16c965563dc43e3cec3
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d
Underwriting Policy identity: sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d
Position Policy identity:     sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe
observed service state:       RUNNING / CURRENT / health / ready
declared GET routes:          6 / 6 HTTP 200
declared HEAD routes:         6 / 6 HTTP 200
coverage state:               KNOWN_COMPLETE, 128 / 128 instruments
current Radar rows:           128
latest market-event age:      4,331 ms
last wire-message age:        3,926 ms
last queue-processing lag:    3,925 ms
queue-lag deadline/active:    5,000 ms / false
Shadow Entry rows:            0
Position rows:                0
Outcome rows:                 0
Decision Control rows:        0
```

The replacement reused the stable root
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The official schema-v5 report
validated the exact product/Policy chain and again reported zero opened, pending, mature, censored,
or incomplete Case rows.

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

The accepted post-start frame was `RUNNING / CURRENT / ready`, with `KNOWN_COMPLETE 128 / 128`,
`0` reconnects, `0` session gaps, and `128` current Radar rows. It contained no Shadow Entry,
Position, Outcome, or Decision Control. The earlier pre-stop `QUEUE_LAG_CURRENTNESS` frame remains
evidence of an intermittent reducer-backlog blocker; one current post-start frame does not prove
that blocker absent or fixed. These are current runtime diagnostics, not an opportunity-frequency
or Policy-quality estimate.

The permission remains `PUBLIC_SHADOW`: no credential, account, balance, margin, order, fill,
capital, settlement action, actual exposure, or private execution. Current health and coverage do
not establish future uptime, fillability, qualification, Edge, or profitability. Beyond the exact
active-task sample, a future service operation, Policy change, or new roadmap channel requires an
explicit permission update under the Delivery Contract.
