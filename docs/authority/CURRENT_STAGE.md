# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_SCHEMA7_8675_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8675_FROM_MAIN_6236F14`

**Live commands:** `MERGE_PRESTOP_CLEAN_RESTART_SMOKE_AUTHORIZED`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_QUEUE_LAG_ROOT_CAUSE`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_QUEUE_LAG_ROOT_CAUSE.md)

## Active queue-lag repair authority

The trader reports a current Workbench frame near the fixed queue deadline: processing queue lag
approximately `5.0 s` and latest market-event age approximately `5.2 s`. A fresh Chronicle frame at
`2026-08-10 22:44 +08:00` independently showed processing lag `4.4 s` and market-event age `4.7 s`
while the service remained visibly running. The accepted prior locality repair removed one measured
single-book hotspot, but its direct profile did not include the global one-second time boundary or
Workbench business projection. It therefore did not establish the complete live bottleneck.

The one authorized `25.020 s` loopback sample is consumed. Across `92` observations, accepted
ingress advanced by `3,366` frames, approximately `134.6 frames/s`, while queue lag remained between
`4,106 ms` and `5,041 ms` with `4,600 ms` median. Thirteen observations crossed the fixed currentness
deadline and changed `RADAR_KNOWN` coverage from `128/128` to `0/128`. Loopback HTTP latency remained
about `20 ms` median. This directly establishes a processing backlog rather than a slow Workbench
request; it does not independently identify upstream wire latency because the displayed wire age is
settled reducer state.

The attributed blocker is `TICKER_CROSS_SECTIONAL_CORE_RECOMPUTATION`. A production-shaped offline
profile used `128` varied-strike instruments and `135` facts per modeled market second. Before the
repair, one modeled second consumed `1.268 s` and invoked the full option core calculator `3,907`
times. The ticker path was recomputing Black inversion and baseline economics for every same-expiry
and immediately shorter-expiry score peer even though only S/T surface inputs changed. Workbench
publication measured approximately `26 ms` per one-second publication and is not the primary
blocker.

The bounded repair keeps the complete cross-sectional dependency and countability semantics, but
reuses each unchanged peer's current core calculation and recomputes only its S/T score. The
identical profile consumed `0.675 s` per modeled second and invoked the core calculator `262` times,
the exact required `67 ticker + 67 book + 128 global` calculations. A causal regression proves that
one ticker change performs one core calculation while still refreshing an immediately shorter
expiry's term score. Focused tests and the full repository gate pass, including `732` tests.

The user explicitly authorized merge, cleanup, and restart with the new code. PR `#43` may be made
ready and merged only while its required checks remain green. Before stopping, one current
Workbench snapshot and one official schema-v5 report may inventory the stable root
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The exact `8675` listener may then
receive one clean termination signal. The replacement must start from clean synchronized `main`,
reuse that same stable repository under its single-instance lease, and bind the unchanged product
and three-Policy identities. Compatible non-terminal admitted Entries are restored into GAPPED
Segments; Cases are neither copied nor rewritten.

One bounded post-start smoke of at most `120 s` may verify the new code/runtime/Policy identities,
loopback health/readiness, `128/128` current coverage after warmup, and queue/current market latency.
The task-created active task file and local/remote topic branch must be removed after acceptance.
Only code made unused by this repair may be deleted; no unrelated historical research root or Case
may be removed. No repeated start, Policy/threshold/universe/schema change, private input, host
resource gate, log inspection, or alternate state root is authorized.

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
