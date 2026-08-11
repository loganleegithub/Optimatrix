# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_CONFIRMING_MAP_LIVE_8765`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_MAIN_CCD773B_WITH_34_RECOVERED_ADMITTED_ENTRIES`

**Live commands:** `NONE_CONSUMED`

**Sole authorized closure:** `NONE`

## Current online boundary

The sole Online Runtime serves `127.0.0.1:8765` from the clean non-temporary checkout
`/Users/logan/Optimatrix-runtime` at code identity
`ccd773b4d94fa964d0215b8ba617c2d83110d6b0`. Its runtime identity is
`sha256:88eab249d5deeddca03fd101804ba2b2575caef4468be779e3c2fd03a037b6ed`.
The former endpoint `127.0.0.1:8675` does not serve, and no second Runtime owns the stable
repository at `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`.

All six declared GET and HEAD routes return HTTP 200. The service reports `RUNNING`, `CURRENT`,
`health=true`, and `ready=true`; the schema-v7 snapshot has `128/128` Radar rows and the unchanged
product/Policy identities. The served `/app.js` bytes exactly match the accepted checkout at SHA-256
`c2ffb0e87dbf8475787187cbc942dbdd8f2a3c2d96c7f38c6d0c6ef6f1badc59`.

The bounded trader-visible observation showed `9 current visible / 9 strong signals / 128 scanned
contracts`. All nine were server-owned clue-eligible HIGH leaders in `CONFIRMING 1/3`, with the
correctly absent pre-activation Episode identity. The map placed them at their exact expiry and
strike, exposed the selected server Score/coverage/evidence, and logged no browser warning or error.
`ACTIVE` rows still require a valid Episode identity. Zero remains truthful only when no current row
satisfies the exact `HIGH + leader + clue eligible + CONFIRMING|ACTIVE` subset.

Immediately before the clean stop, the official policy-aware reader validated 49 schema-v5 Cases:
34 non-terminal admitted Shadow Entries, 4 selected Underwriting Controls, and 11 Radar-score
Controls. All 34 admitted latest Segments were `OPEN` under the predecessor runtime. The clean stop
closed every one as `CENSORED_AT_STOP` and created zero admitted Outcome files. The new runtime then
restored all 34 Entry identities exactly once. Their latest Segments are `OPEN` and bind the current
code/runtime; Workbench publishes 34 Shadow Entry rows, 34 Position rows, and 34 `PENDING` Outcome
projections with actual availability `UNKNOWN` and no actual PnL. All 34 are `ACTIVE/GAPPED`; gap
counts are 2 at one, 28 at two, 2 at three, and 2 at four.

The 15 Controls remain historical Case truth and are not restored as Entries. Thirteen have Outcome
files: 12 `CENSORED_AT_FAILURE` and one `MATURE_KNOWN`; the other two remain pending Controls. The
mature Control is not an admitted Shadow Outcome and does not establish Policy Edge or
profitability. No Case, Entry, Control, or Outcome was copied, migrated, rewritten, deleted, or
relabeled. Both exact-checkout `make check` runs and main CI passed with 750 tests.

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
34 restored Entries, or current strong-signal counts do not establish future uptime, source
freshness, fillability, qualification, Edge, or profitability.

All cutover probes and live commands are consumed. A future probe, restart, state-root operation,
Policy change, or roadmap-channel implementation requires a new explicit task and permission update
under the Delivery Contract.
