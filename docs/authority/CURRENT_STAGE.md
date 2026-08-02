# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Implemented runtime capability:** `OFFLINE_PUBLIC_SHADOW_RUNTIME`

**Production Short Vol Radar:** `NOT_ACCEPTED_PENDING_REVALIDATION`

**Sole authorized next product-capability closure:**
`SHORT_VOL_WORKBENCH_PUBLICATION_COALESCING`

**Fixed-contract public Shadow runtime:** `IMPLEMENTED_NOT_PRODUCTION_ACCEPTED`

**Persistent public Shadow service/workbench:** `STOPPED_NO_DEPLOYMENT`

**Evidence gate:** `NONE`

**Live commands:** `FORBIDDEN`

**Persistent deployment / 24x7 acceptance:** `NOT_CLAIMED`

## Current truth

This document grants permission under
[`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md). Code presence, green tests, old receipts,
elapsed runtime, browser output, contract presence, or historical stage text grants no acceptance
or deployment authority.

The user stopped the previous persistent observation on 2026-08-02 and explicitly rejected its
Radar results as unreliable. All runtime observation, smoke, soak, commissioning, probe, and
service-evidence roots were removed from active locations after the sole running process, both
launchd labels, and the loopback listener were confirmed absent. No historical runtime result is a
current business premise, acceptance input, denominator, or permission source.

The repository still contains an implemented public-only modular-monolith runtime: Deribit public
market ingestion, Radar, fixed-contract Underwriting, Shadow admission, Position management,
Outcome projection, and a loopback read-only Workbench. These are implementation facts only. They
do not currently prove production correctness, 24-hour stability, Policy quality, opportunity
frequency, fillability, profitability, actual exposure, or PnL.

## Active closure

`SHORT_VOL_WORKBENCH_PUBLICATION_COALESCING` is the sole active task. It may change only:

- ordinary status-stable Workbench publication cadence to at most one complete immutable snapshot
  per 500 monotonic milliseconds;
- immediate publication for semantic safety and lifecycle status changes;
- one latest-state `flush_pending()` after accepted-event draining and before reconnect or
  clean-stop terminal mutation;
- direct tests and the minimum authority, contract, architecture, and README truth required by
  that behavior.

The runtime continues to settle every accepted fact through Radar, Underwriting, Shadow, Position,
and Outcome owners. Only the non-durable Workbench JSON reprojection/serialization is coalesced.
The schema remains version 2 and every published body remains complete and immutable.

No timer, thread, queue, scheduler, new protocol, partial update, SSE path, service split,
container, dependency, durable publication object, or generic abstraction is authorized.

## Change declarations

1. **Market/Decision input contract:** `NONE`
2. **Decision Policy:** `NONE`
3. **Outcome/evaluation contract:** `NONE`
4. **Stage/authorization:** `APPROVED` only for the active offline implementation and deterministic
   verification; no live or deployment authority

## Permission boundary

Allowed:

- edit the owning Workbench publisher and the one existing runtime drain-to-terminal boundary;
- add direct deterministic tests;
- update the exact owning implementation contract and architecture/README truth;
- run offline tests, lint, type checks, and builds;
- use one bounded non-`main` branch and one Draft PR after independent exact-candidate review.

Forbidden:

- production-public market, service, probe, launchd, commissioning, or evidence commands;
- treating any deleted or historical evidence as accepted, reconstructing it, or relabelling it;
- changing market sources, universe, continuity, missingness, Radar formulas, thresholds,
  persistence, clear/re-arm, Underwriting, Shadow admission, Position, Outcome, or cohort semantics;
- Policy changes or hot reload;
- private/account APIs, credentials, balances, margin, positions, orders, fills, settlement,
  execution gateways, capital, qualification, promotion, or money;
- public Internet binding, automatic restart, or unattended deployment;
- databases, full-market persistence, replay, evidence chains, generic schedulers, workflow
  engines, feature stores, registries, or new services.

## Evidence boundary

This implementation closure requires direct behavior tests only. It requires no live observation,
sealed feed, replay, recomputation, Shadow forward Outcome sample, qualification, or execution
evidence.

Passing tests may prove only deterministic publication cadence, status bypass, latest-state flush,
and atomic snapshot replacement. They cannot accept the Radar, a deployment, 24x7 stability, market
coverage, strategy value, or trading performance.

## Next authority decision

After this implementation is independently accepted, a separate user decision must choose the
next smallest closure. A future production-public validation must start fresh, bind a new exact
runtime and evidence boundary, and must not depend on deleted history. Until then, live commands
remain forbidden.

Update this document in the same accepted change that changes permission, implemented capability,
the sole active closure, or the blocker.
