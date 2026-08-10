# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_H2_CUTOVER_AUTHORIZED_PENDING`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_H2_ONE_CUTOVER`

**Persistent service:** `V1_RUNNING_CURRENT_PENDING_CLEAN_HANDOFF`

**Live commands:** `ONE_V1_CLEAN_STOP_ONE_V2_START_ONE_BOUNDED_READ_ONLY_SMOKE`

**Sole authorized closure:** [`INVERSE_BTC_SHORT_VOL_V2_CLOSED_LOOP`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_CLOSED_LOOP.md)

## Active V2 cutover boundary

H1 directly replaced the repository's V1 ratio-only Radar with the sole
`INVERSE_BTC_SHORT_VOL_V2` ordinal opportunity-ranking Policy and connects its frozen
selection/entry-refresh facts to future schema-v5 Shadow Outcomes. The measured baseline is `0 / 1`
online Radar Policies with that causal V2 score-to-Outcome link; the primary blocker is
`V2_SCORE_TO_FUTURE_OUTCOME_LINK_ABSENT`.

H2 is now the one authorized clean handoff from the still-running V1 process to that V2 code. It
does not reopen H1 design or Policy tuning. The exact topology is:

1. read the current loopback snapshot and validate the V1 Case repository at
   `/private/tmp/optimatrix-inverse-btc-stable-97AYba` with the official V1 reader;
2. clean-stop that one V1 process once, close only its current admitted-Entry Observation Segments,
   and confirm the loopback surface is down;
3. preserve the complete V1 repository in place as read-only historical research truth, without
   copy, migration, deletion, synthetic Outcome, or V2 recovery;
4. create the previously absent stable V2 repository at
   `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2`;
5. from one clean commit on the declared task branch, invoke the canonical `serve-shadow` exactly
   once on `127.0.0.1:8765` with that fresh root; and
6. consume one bounded read-only smoke over the six declared GET/HEAD routes, the immutable current
   API snapshot, and the official schema-v5 reader.

No retry, second root, old-root repoint, Case copy, migration, compatibility mode, source-contract
probe, threshold tuning, process supervisor, PID/log/`lsof`/launchd inspection, or private action is
authorized. A failed stop/start/smoke is reported as the H2 blocker rather than silently retried.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. It uses active Deribit BTC options, the
`btc_usd` index, BTC-native premium/fees/settlement/PnL, and explicitly labeled
`USD_EQUIVALENT` valuation. There is no product selector, fallback product, compatibility profile,
or online alternate-schema branch. Actual account margin remains `UNKNOWN`.

The H1 repository target product specification and fixed V2 Policy identities are:

```text
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:79b5ec7c886964ee4c886fb272f287f0645cc69a0b585cf53711c7b5ad0fef57
Underwriting Policy identity: sha256:5cea5bc8153071359597526e0f1bd665bbf55215b5368ed6135f96ca3b607c31
Position Policy identity:     sha256:f05646f7c1ed1a55bd8747879f1153c2633afde83aa3652549e01140552a6c67
```

The repository contains only those three Inverse Policy artifacts. H1 intentionally changes all
three content identities because the Radar decision contract and schema-v5 product identity change
as one chain. The one canonical `serve-shadow` startup has no product selector and resolves
structurally to this product and Policy chain. Unsupported product or schema input fails without
Candidate or Shadow admission. These target identities are not a deployment claim.

The component-book lifecycle remains a public-book counterfactual. It is `NOT_AN_ORDER`,
`NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`, provides no liquidity reservation, and proves neither
fillability, strategy edge, profitability, nor qualification.

## Pre-cutover live process boundary

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

The prior V1 start has been consumed. The process runs the accepted Inverse-only source and
reuses `/private/tmp/optimatrix-inverse-btc-stable-97AYba`. Its identity and health are a bounded
operational observation; H2 must re-read its health, market counters, and durable Case state before
the clean stop. Only the exact H2 topology above authorizes one stop, one fresh-root start, and one
bounded read-only smoke. It grants no general deployment or restart authority.

## Accepted repository closure

At historical base commit `270920fb1fcb255c648e95361f31c1e5075ec294`, `0 / 1` canonical default
`serve-shadow` startup routes were Inverse-safe because omitting an optional selector chose the
obsolete product. The previously accepted V1 repository result was `1 / 1`: its startup composition
root resolved only `INVERSE_BTC_V1`. H1 replaces that repository path with the V2 Policy chain and
schema-v5 Case family and removes the obsolete schema-v4 migration command. It does not alter the
still-running V1 process or its external root.

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

The pre-cutover live snapshot establishes only the identity, reachability, currentness, and recovery
state shown above. It does not establish continuous future uptime, fillability, opportunity
frequency, account margin, edge, profitability, qualification, or execution permission. The `14`
Outcome rows were pending Entry projections, not mature Outcomes, and must be re-counted before
stop. H2 may establish only the declared V2 identity, fresh-root isolation, current public-source
reachability, and truthful zero/UNKNOWN state. It cannot establish Policy quality, market frequency,
profitability, qualification, or permission for another start.
