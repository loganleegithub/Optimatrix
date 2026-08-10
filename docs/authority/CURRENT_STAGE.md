# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_DECIMAL_PACKET_INTEGRITY_REPAIR_ACTIVE`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `STOPPED_8675_AFTER_SCORE_PACKET_INTEGRITY_FAILURE_6FBCF9F`

**Live commands:** `REQUIRED_BOUNDED_DECIMAL_REPAIR_CUTOVER`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_INDEX_GRID_PHASE_REPAIR`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_INDEX_GRID_PHASE_REPAIR.md)

## Active repair authorization

The source-grid repairs in Draft PR #48 removed both the rotating five-minute phase and the
trusted-time-ahead-of-source race without changing a Policy artifact. Running code identity
`17d94dafb8eb6fb0044df100de3f10b4f8fca24b` subsequently allowed eligible HIGH leaders in the
6-to-24-hour and 24-to-72-hour bands to reach confirmation `2/3` at their Policy-owned 150-second
and 300-second separations.

Live fixed-attribution then established the next blocker. Three consecutive scheduled history
refresh cycles produced processing-lag peaks of `3,045 ms`, `4,032 ms`, and `5,003 ms`. At the
threshold-crossing frame, `queue_lag_currentness_active=true`, the known HIGH leader became
`QUEUE_LAG_CURRENTNESS`, its confirmation changed `2 → 0`, and the runtime-local `CORE_UNKNOWN`
reset count increased by `13`. The session epoch remained `1`, reconnect and protocol-gap counts
remained zero, and current truth recovered about half a second later. The fixed cause is
`ORDERED_QUEUE_LAG_DESTRUCTIVE_PRECONFIRMATION_RESET`: an ordered reducer backlog correctly paused
current evaluation but incorrectly erased earlier accepted observations.

The repair keeps every lagged frame `UNKNOWN`, globally degrades leader coverage, counts no
observation, and permits no Episode, Underwriting admission, Candidate, or Shadow Case. Only an
inactive pre-confirmation tracker retains its previously accepted leader, score band, and count.
After catch-up, the current score is recomputed; a different leader, band, scope, or persistent core
loss still resets normally, and an already-active Episode remains fail-closed. No score threshold,
confirmation count, separation, TTE/Delta rule, Underwriting economics, Position rule, Case schema,
or Policy identity changes.

The now-stopped code identity `6fbcf9fbf4237d6685cbf7ae986dc4dfa4dfee76` ran that repair.
Its first three observed HIGH Episodes reached Underwriting and were known non-Candidates because
entry credit did not exceed the fixed future-cost reserve. One separately selected LOW research
Control then opened normally and exposed `OFFLINE_CASE_DIRECTORY_IDENTITY_MISPARSE`: its store-owned
directory is the bare 64-hex digest, while `report-v2-cases` duplicated the directory scan and
incorrectly required the directory name itself to be a prefixed `sha256:` identity. The durable Case
is valid; the reader boundary was wrong.

The bounded closure makes the CaseStore's directory-name-to-Case-identity conversion public and
reuses it in the offline report. It changes no online decision, Policy, Case bytes, or stable root
and requires no runtime restart. Continued observation remains production-public Shadow only and
cannot claim Edge, profitability, an order, a fill, or actual exposure. The bounded implementation
remains [Draft PR
#48](https://github.com/loganleegithub/Optimatrix/pull/48).

Continued observation then exercised the repaired currentness boundary at `5,011 ms`: the frame was
truthfully `STALE/UNKNOWN`, accepted no observation or admission, recovered `128/128` about one
second later, and added zero destructive `CORE_UNKNOWN` pre-confirmation resets. The cumulative
count then reached seven HIGH Episodes that were fully evaluable by Underwriting; all seven were
known non-Candidates at the fixed future-cost reserve.

Direct policy-aware validation of the current Workbench score-packet projection exposed
`LOSSY_DECIMAL_PACKET_SERIALIZATION`. Baseline path shares are calculated at 50-digit precision,
but score-packet `_decimal_text` called `Decimal.normalize()` under the ambient 28-digit context.
The serialized raw D input could therefore lose trailing significant digits while the stored D
result retained the pre-serialization calculation, producing a one-unit final-decimal mismatch on
reader recomputation. The online score was correct, but a future written Case could become
unreadable after JSON restoration. The repair serializes the existing Decimal coefficient in
fixed-point form without changing calculation, score, band, Policy, schema, or threshold.

The ninth HIGH Episode exercised the defect while opening a selected no-trade Control. The
CaseStore rejected the packet before publication, the runtime converted that durable-boundary
failure to `ShadowRuntimeIntegrityError`, and the process exited fail-closed. No second Case,
Candidate, admitted Entry, or Position was written. The existing Control is still readable and is
truthfully `INCOMPLETE_UNCLEAN_EXIT` while the runtime is stopped.

This authority permits one clean start on `127.0.0.1:8675` from the checked repair commit, reusing
the unchanged stable Case repository. No Case may be copied, rewritten, migrated, or deleted.

## Current online boundary

The last Online Runtime served `127.0.0.1:8675` from clean Draft PR #48 code identity
`6fbcf9fbf4237d6685cbf7ae986dc4dfa4dfee76`. Its runtime identity was
`sha256:5f1f5989c6475e1608af90e9d4b15dde553e71b270ccbaf0eaa80798957aa2f8`.
It released the single-instance lease when the integrity failure stopped the process. The stable
Case repository remains `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`; no Case
root was copied, migrated, replaced, or deleted.

The Decimal-repair discovery boundary reported health, readiness, `RUNNING`, `CURRENT`,
`KNOWN_COMPLETE`, `128/128` current Radar coverage, zero reconnects, and zero protocol gaps. Before
the failure it had nine distinct
HIGH Episodes and zero Candidate, admitted Shadow Entry, or Position. The single durable Case was a
non-admitted LOW research Control; the repaired official report now reads it under inactive-runtime
truth as `INCOMPLETE_UNCLEAN_EXIT`. These are bounded observations, not Policy-quality or
future-frequency claims.

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

Only the bounded Decimal repair start and continued public-only monitoring declared above are
authorized. Any extra restart, state-root operation, Policy change, or roadmap-channel
implementation requires a new explicit task and permission update under the Delivery Contract.
