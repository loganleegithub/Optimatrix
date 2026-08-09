# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_ONLY_REPOSITORY_CLEANUP_AUTHORIZED`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_V1_ONLY_REPOSITORY_TARGET`

**Persistent service:** `STABLE_CASE_REPOSITORY_RECOVERY_ACCEPTED`

**Live commands:** `FORBIDDEN_DURING_INVERSE_ONLY_REPOSITORY_CLEANUP`

**Sole authorized closure:** `SHORT_VOL_INVERSE_ONLY_REPOSITORY_CLEANUP`

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

This cleanup does not change any value or byte in those three Policy artifacts. It removes every
online product-selection, fallback, and compatibility route so a future externally authorized
startup can resolve only this product and this Policy chain.

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

That process was launched from the old, pre-cleanup checkout. Its identity is a read-only
operational observation, not evidence that this repository cleanup is deployed. Its health and
market counters may change after the observation. The process must not be hot-swapped, restarted,
or repointed during this task. A later restart requires new explicit Authority after the cleanup is
merged and the exact checkout is chosen.

## Authorized repository closure

At base commit `270920fb1fcb255c648e95361f31c1e5075ec294`, the one canonical `serve-shadow`
startup path defaults to the wrong product when its optional selector is omitted. Therefore
`0 / 1` default startup routes are Inverse-safe. The primary blocker is
`LINEAR_DEFAULT_RESTART_MISROUTE`: an otherwise ordinary future restart can select a product and
Policy chain different from the live Inverse Entry repository.

The authorized closure makes `INVERSE_BTC_V1` structural rather than optional: remove the product
selector and fallback, remove obsolete product Policy/configuration support, accept only the
Inverse Case schema and units online, and align Authority, contracts, Workbench documentation, and
direct tests. The expected repository result is `1 / 1` default startup routes resolving the exact
Inverse product and three-Policy chain.

## Durable-data boundary

Durable-data effect is `NONE`. Existing state roots and Shadow Case repositories live outside the
Git repository and are not enumerated, migrated, rewritten, or deleted by this cleanup. The
accepted Inverse Case shape, identities, process-independent Entry aggregate, Observation Segment,
first-CLOSE/attempt, and Outcome semantics remain unchanged.

## Allowed work

- delete obsolete product selection, configuration, constants, Policy artifacts, compatibility
  readers, tests, and dual-product documentation from the repository;
- keep the three Inverse Policy artifacts byte-exact and content-identified;
- use direct tests and `make check` on the cleanup branch;
- report the existing 8765 process only by its observed old-checkout identity and non-claims.

## Forbidden work

- hot-swap, stop, restart, relaunch, or repoint the existing 8765 process;
- open, mutate, migrate, copy, or delete any repository-external state root;
- change any Inverse Policy value, threshold, target, reserve, unit, or identity;
- manufacture a clue, Candidate, Case, Outcome, or favorable funnel result;
- add private/account API, credentials, balance, margin, order, fill, capital, settlement action,
  actual exposure, deployment control, host inspection, commissioning, manifest, or receipt chain.

## Acceptance boundary

The closure is complete only when the repository exposes one fixed `INVERSE_BTC_V1` startup and
Policy chain, contains no obsolete online product/schema compatibility surface, preserves all
three Inverse Policy bytes and identities, passes focused tests and `make check`, and truthfully
leaves the running old checkout and every external state root untouched. Passing tests does not
authorize a restart or establish current market health, fillability, edge, profitability,
qualification, deployment, or execution permission.
