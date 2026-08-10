# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `VALIDATION_ONLY`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_8675_CUTOVER_AUTHORIZED_PENDING`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_ONE_8675_CUTOVER`

**Persistent service:** `H2_8765_RUNNING_PENDING_8675_HANDOFF`

**Live commands:** `ONE_NEW_ROOT_8675_START_ONE_BOUNDED_SMOKE_ONE_LATER_8765_CLEAN_STOP`

**Sole authorized closure:**
[`INVERSE_BTC_SHORT_VOL_V2_8675_CUTOVER`](../../tasks/INVERSE_BTC_SHORT_VOL_V2_8675_CUTOVER.md)

## Active cutover boundary

The repository repair is merged at `main@b6fb446ca608648ac4a0d872e656eaee0ddedbfb`.
It fixes delayed-HIGH activation-packet ownership, optional S/T cross-sectional source coherence,
cross-Call/Put dependency invalidation, score-relevant ticker countability, native tick-ladder
spread distance, and conditional Case reporting. The remaining measured baseline is `0 / 1` Online
Runtime instances binding that chain on the user-requested port `8675`; the blocker is
`V2_COHERENCE_POLICY_CHAIN_NOT_ONLINE`.

The sole authorized topology is:

1. read the current `127.0.0.1:8765` immutable snapshot and inventory its stable H2 root
   `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2` through the official schema-v5 reader;
2. verify the exact new root `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9` is absent;
3. from one clean commit on the declared task branch, invoke canonical `serve-shadow` exactly once
   on `127.0.0.1:8675` with that fresh root;
4. consume one bounded read-only smoke over the six declared GET/HEAD routes, immutable current API,
   exact product/Policy identities, and official schema-v5 reader;
5. only after every new-service gate passes, clean-stop the superseded `8765` process once and
   confirm its loopback surface is down; and
6. preserve both old historical roots and the superseded H2 root in place without copy, migration,
   deletion, rewrite, or recovery into the new root.

No retry, second new root, old-root repoint, Case compatibility mode, source-contract probe,
threshold tuning, process supervisor, PID/log/`lsof`/launchd inspection, or private action is
authorized. A failed new start or smoke leaves `8765` running and is reported as the blocker.

## Target identity chain

```text
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d
Underwriting Policy identity: sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d
Position Policy identity:     sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe
deployment state:             AUTHORIZED_NOT_YET_RUNNING
```

The numeric score weights, thresholds, TTE/Delta bands, persistence, Underwriting thresholds,
Position thresholds, Case schema, and Outcome arithmetic are unchanged by this cutover. The score
remains an expert ordinal hypothesis, not a probability, oracle, Edge, or profitability claim.

## Current product truth

The sole Online Runtime product is `INVERSE_BTC_V1`. There is no product selector, fallback
product, compatibility profile, alternate online schema, or in-process Policy switch. The
repository contains only the three fixed V2 Inverse Policy artifacts in the target chain. Both the
superseded and target services are Deribit production-public, BTC-native Shadow processes with no
private execution capability.

## Pre-cutover accepted online boundary

At the last accepted H2 observation, `http://127.0.0.1:8765` reported:

```text
channel:                      INVERSE_BTC_SHORT_VOL_V2
Workbench schema:             6
code identity:                cd9243ff9f92ca6e1b6c142dc9d61cbc5a21a359
runtime identity:             sha256:8c34f476bc91928678eb36b0e3528b2a7bc4f0b9d47157b018b805fb7d065260
Radar Policy identity:        sha256:79b5ec7c886964ee4c886fb272f287f0645cc69a0b585cf53711c7b5ad0fef57
Underwriting Policy identity: sha256:5cea5bc8153071359597526e0f1bd665bbf55215b5368ed6135f96ca3b607c31
Position Policy identity:     sha256:f05646f7c1ed1a55bd8747879f1153c2633afde83aa3652549e01140552a6c67
observed service state:       RUNNING / CURRENT / ready
```

That service uses `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2`. Its health and Case
inventory must be read again before cutover; the historical snapshot is not a present-state claim.

## Durable-data boundary and non-claims

The superseded H2 root remains its own immutable research epoch. Clean stop may append only the
contract-owned current Segment close for any admitted Entry. The new V2-v9 root starts empty and
accepts only schema-v5 Cases bound to the target chain. Zero new Cases or Outcomes is valid and is
not a zero-opportunity, zero-risk, frequency, qualification, or profitability claim.

The permission remains Deribit production public data and loopback read-only Workbench only. There
is no credential, account, balance, margin, order, fill, capital, settlement action, actual
position, or private execution authority.
