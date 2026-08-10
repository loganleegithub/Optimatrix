# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `VALIDATION_ONLY`

**Current implementation status:** `INVERSE_ONLY_REPOSITORY_ACCEPTED`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_V1_ONLY_REPOSITORY`

**Persistent service:** `STABLE_CASE_REPOSITORY_RECOVERY_ACCEPTED`

**Live commands:** `ONE_CANONICAL_PUBLIC_SHADOW_RESTART_REQUIRED`

**Sole authorized closure:** `RESTORE_INVERSE_BTC_WORKBENCH_8765`

**Active task:**
[`SHORT_VOL_8765_OUTAGE_RECOVERY`](../../tasks/SHORT_VOL_8765_OUTAGE_RECOVERY.md)

## Active outage-recovery authority

At `2026-08-10T11:22+08:00`, all six declared loopback Workbench routes returned connection
refused. The official Case reader validated all `51` Cases in
`/private/tmp/optimatrix-inverse-btc-stable-97AYba`, found `14` compatible non-terminal admitted
Entries, and classified every latest Observation Segment from runtime
`sha256:33dedd47cff3f6cb10bb5b2844f58b79218f40c931bf02221440a1894a785bf4` as
`INCOMPLETE_UNCLEAN_EXIT`. The stable repository lease was available. Focused service/Workbench
tests and the repository gate passed on base `7093c9e4630da041ea8b68e650bdce3406606c90`.

This task authorizes one external long-lived start from its clean commit, using only:

```text
product:        INVERSE_BTC_V1
state root:     /private/tmp/optimatrix-inverse-btc-stable-97AYba
Workbench:      http://127.0.0.1:8765
Policy chain:   the exact identities below
```

The start must restore every compatible admitted Entry and may append the contract-required new
`GAPPED` Observation Segment after the first settled public boundary. It may not migrate, copy,
delete, rewrite, or selectively recover a Case. It may not restore selected no-trade Controls. One
bounded read-only route/currentness check is authorized after the start. No second start, retry,
alternate root, Policy change, private input, host inspection, process supervisor, or automatic
restart implementation is authorized by this task.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. It uses active Deribit BTC options, the
`btc_usd` index, BTC-native premium/fees/settlement/PnL, and explicitly labeled
`USD_EQUIVALENT` valuation. There is no product selector, fallback product, compatibility profile,
or online alternate-schema branch. Actual account margin remains `UNKNOWN`.

The accepted product specification and fixed Policy identities are:

```text
product spec identity:        sha256:ff90da92cefe8e530339df38505fe7726b92b45b1855b751f2633ffd4fdb2172
Radar Policy identity:        sha256:283c2a8cc5e14cbed94b0f2a41ddd18ff2410772ae45d07abfea80d04446b1af
Underwriting Policy identity: sha256:76a93725bb4923a70a2865b1e06add3b5a23ae80a831029c558ce188be6e7834
Position Policy identity:     sha256:cb3866b8efd45d5c05ed23ab56658c2cdbf0359132e39f52ce329761ad933b8e
```

The repository contains only those three Inverse Policy artifacts. Their accepted bytes, values,
and identities are unchanged. The one canonical `serve-shadow` startup has no product selector and
resolves structurally to this product and Policy chain. Unsupported product or schema input fails
without Candidate or Shadow admission.

The component-book lifecycle remains a public-book counterfactual. It is `NOT_AN_ORDER`,
`NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`, provides no liquidity reservation, and proves neither
fillability, strategy edge, profitability, nor qualification.

## Existing live process boundary

At the 2026-08-10 Authority freeze, the already-running loopback Workbench at
`http://127.0.0.1:8765` reported:

```text
code identity:                270920fb1fcb255c648e95361f31c1e5075ec294
runtime identity:             sha256:33dedd47cff3f6cb10bb5b2844f58b79218f40c931bf02221440a1894a785bf4
product spec identity:        sha256:ff90da92cefe8e530339df38505fe7726b92b45b1855b751f2633ffd4fdb2172
Radar Policy identity:        sha256:283c2a8cc5e14cbed94b0f2a41ddd18ff2410772ae45d07abfea80d04446b1af
Underwriting Policy identity: sha256:76a93725bb4923a70a2865b1e06add3b5a23ae80a831029c558ce188be6e7834
Position Policy identity:     sha256:cb3866b8efd45d5c05ed23ab56658c2cdbf0359132e39f52ce329761ad933b8e
observed service state:       RUNNING / CURRENT / ready
```

That process was launched from the pre-Inverse-only checkout. Its identity is a read-only
operational observation, not evidence that the accepted repository is deployed. Its health and
market counters may change after the observation. It must not be hot-swapped, stopped, restarted,
relaunched, repointed, or used for a post-change smoke under this Authority. A later restart
requires a new explicit task and permission boundary.

## Accepted repository closure

At historical base commit `270920fb1fcb255c648e95361f31c1e5075ec294`, `0 / 1` canonical default
`serve-shadow` startup routes were Inverse-safe because omitting an optional selector chose the
obsolete product. The accepted repository result is `1 / 1`: the startup and migration composition
roots resolve only `INVERSE_BTC_V1`, its `btc_usd` sources, BTC-native economics, explicit USD
valuation, schema-v4 Case family, and exact matching three-Policy chain.

The obsolete product specification, source/index/unit route, Policy artifacts, alternate Radar
parser, and obsolete Shadow Case compatibility reader/writer branch are absent. The future 2×2
product roadmap does not create code or authority for any unimplemented channel.

## Durable-data boundary

The repository closure had durable-data effect `NONE`. External state roots and Shadow Case
repositories were not enumerated, opened, migrated, rewritten, copied, or deleted. The accepted
Inverse Case shape, identities, process-independent Entry aggregate, Observation Segment,
first-CLOSE/attempt, and Outcome semantics remain unchanged.

## Current non-claims

Repository checks establish source behavior only. They do not authorize a live command or prove
the identity or health of a later process. They do not establish current market health,
fillability, opportunity frequency, account margin, edge, profitability, qualification, or
execution permission. Any later implementation, validation, restart, Policy discussion, or new
2×2 channel requires a new active task under the Delivery Contract.
