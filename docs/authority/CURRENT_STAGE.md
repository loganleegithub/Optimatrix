# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_ONLY_REPOSITORY_ACCEPTED`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_V1_ONLY_REPOSITORY`

**Persistent service:** `RUNNING_CURRENT_GAPPED_ENTRY_RECOVERY`

**Live commands:** `NO_ADDITIONAL_START_STOP_OR_RESTART_AUTHORIZED`

**Sole authorized closure:** `NONE`

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

## Current live process boundary

At `2026-08-10T11:29:56+08:00`, the externally started loopback Workbench at
`http://127.0.0.1:8765` reported:

```text
code identity:                c5cc2e605de7df028be18b6ff00ca3b76dd86f27
runtime identity:             sha256:888729c63e0deec4aea2bb1a3787a205501910351ae66c4d07e66e5017048676
product spec identity:        sha256:ff90da92cefe8e530339df38505fe7726b92b45b1855b751f2633ffd4fdb2172
Radar Policy identity:        sha256:283c2a8cc5e14cbed94b0f2a41ddd18ff2410772ae45d07abfea80d04446b1af
Underwriting Policy identity: sha256:76a93725bb4923a70a2865b1e06add3b5a23ae80a831029c558ce188be6e7834
Position Policy identity:     sha256:cb3866b8efd45d5c05ed23ab56658c2cdbf0359132e39f52ce329761ad933b8e
observed service state:       RUNNING / CURRENT / ready
declared GET routes:          6 / 6 HTTP 200
declared HEAD routes:         6 / 6 HTTP 200
current Radar rows:           128
recovered admitted Entries:   14 / 14, latest Segment OPEN / GAPPED
```

The one authorized start has been consumed. The process runs the accepted Inverse-only source and
reuses `/private/tmp/optimatrix-inverse-btc-stable-97AYba`. Its identity and health are a bounded
operational observation; current health and market counters must be re-read before any later claim.
No additional start, stop, restart, repoint, Policy change, or live smoke is authorized. Any such
action requires a new active task and permission boundary.

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

The stable repository contains `51` Case directories. Recovery created no Case directory and no
Outcome, migrated/copied/deleted/rewrote no existing record, and did not restore the `37` historical
selected no-trade Controls. It appended one contract-owned `GAPPED` Observation Segment to each of
the `14` compatible non-terminal admitted Entries. Their latest Segments are `OPEN / GAPPED`; this
does not restore continuity or qualification across the prior unclean exit. The accepted Inverse
Case shape, identities, Entry aggregate, first-CLOSE/attempt, and Outcome semantics are unchanged.

## Current non-claims

The current live snapshot establishes only the identity, reachability, currentness, and recovery
state shown above. It does not establish continuous future uptime, fillability, opportunity
frequency, account margin, edge, profitability, qualification, or execution permission. The `14`
Outcome rows are pending Entry projections, not mature Outcomes. Any later implementation,
validation, stop/restart, Policy discussion, or new 2×2 channel requires a new active task under the
Delivery Contract.
