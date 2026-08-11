# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_CONFIRMING_MAP_REPAIR`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_FROM_MAIN_54E3B58_WITH_32_RECOVERED_ADMITTED_ENTRIES`

**Live commands:** `ONE_CLEAN_STOP_AND_ONE_CLEAN_START_8765`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_CONFIRMING_MAP_REPAIR`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_CONFIRMING_MAP_REPAIR.md)

## Current bounded implementation authority

The live schema-v7 snapshot contains 128 Radar rows, including nine clue-eligible `HIGH` bucket
leaders in server-owned `CONFIRMING 1/3`, while the Workbench renders zero strong signals. The
browser incorrectly requires an Episode identity for both `CONFIRMING` and `ACTIVE`; the Radar owner
creates that identity only when confirmation completes and the bucket becomes `ACTIVE`.

The user explicitly authorizes this bounded repair directly on `main` without a feature branch.
Starting from clean synchronized `main@7f55972028073570be7774b25f40184f8cba25e1`, the task may change
only the browser strong-signal predicate, its direct tests, and this task/Authority closure. It may
then perform one clean stop of the current 8765 Runtime, synchronize the clean non-temporary runtime
checkout to the exact accepted main commit, and perform one clean start on `127.0.0.1:8765` using
the unchanged stable Case repository and three-Policy chain.

The stop closes each active admitted Entry's current Observation Segment without creating a mature
Entry Outcome. The new runtime must restore every compatible non-terminal admitted Entry exactly
once and open a truthful `GAPPED` Segment after fresh facts settle. No Case, Entry, Control, or
Outcome may be copied, migrated, rewritten, deleted, or relabeled. One bounded post-start route,
snapshot, strong-signal, and official Case-reader verification is authorized. A consumed or failed
start grants no retry. Policy, Workbench schema, Case schema, stable-root, roadmap-channel, private
execution, host inspection, commissioning, and supervision changes remain forbidden.

## Current online boundary

The sole Online Runtime serves `127.0.0.1:8765` from the clean non-temporary checkout
`/Users/logan/Optimatrix-runtime` at merged `main` code identity
`54e3b589ba5ffd7eff7f7acf018fbc0530492614`. Its runtime identity is
`sha256:3d548ef832ac917c11575650de682af3f6adf359d75648b02a9c6e4a0baaee26`.
The former endpoint `127.0.0.1:8675` no longer serves.

The bounded post-start matrix returned HTTP `200` for GET and HEAD on `/`, `/app.js`,
`/styles.css`, `/api/workbench/current`, `/healthz`, and `/readyz`. The settled schema-v7 snapshot
reported `RUNNING`, `CURRENT`, ready and healthy service, `KNOWN_COMPLETE` Radar coverage, and
`128/128` current instruments. The deployed browser assets contain the strong-signal map; zero
current strong signals is a valid settled state when no row satisfies the server-owned eligible
`HIGH` bucket-leader predicate in `CONFIRMING | ACTIVE`.

The runtime holds the single-instance lease for the unchanged stable Case repository
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. Before start, the official reader
validated 47 schema-v5 Cases: 32 non-terminal admitted Shadow Entries, 4 selected Underwriting
Controls, and 11 Radar-score Controls, with zero mature Outcome. The new runtime restored all 32
admitted Entry identities exactly once and publishes 32 Shadow Entry rows, 32 Position rows, and 32
pending Outcome projections. The official policy-aware reader validates every latest admitted
Segment as `OPEN` under the current code/runtime identities. Every restored Entry is truthfully
`GAPPED` and qualification-ineligible because the preceding process ended without closing its
latest Segment. Controls remain historical Case truth and are not restored. No Case, Entry,
Control, or Outcome was copied, migrated, rewritten, deleted, or relabeled.

PR #48 is merged as `main@d237aaf4579ab041441edebae93a4c56f32031c4`; its source-grid,
confirmation-continuity, Decimal, Candidate-retirement, heartbeat, and typed activation-packet
repairs remain in the deployed code. PR #47 is merged as
`main@54e3b589ba5ffd7eff7f7acf018fbc0530492614`; its strong-signal map is the deployed Workbench
surface. The completed implementation task is removed from the final tree; Git and the merged PRs
retain its engineering history.

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
settlement action, actual exposure, or private execution. Green checks, a responsive Workbench,
32 restored Entries, or current strong-signal counts do not establish future uptime, source
freshness, fillability, qualification, Edge, or profitability.

All cutover probes and live commands are consumed. A future probe, restart, state-root operation,
Policy change, or roadmap-channel implementation requires a new explicit task and permission update
under the Delivery Contract.
