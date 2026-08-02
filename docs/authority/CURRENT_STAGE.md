# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Implemented runtime capability:** `OFFLINE_PUBLIC_SHADOW_RUNTIME`

**Production Short Vol Radar:** `NOT_ACCEPTED_PENDING_REVALIDATION`

**Sole authorized closure:** `NONE`

**Persistent service:** `STOPPED_NO_DEPLOYMENT`

**Live commands:** `FORBIDDEN`

## Current truth

The user stopped the previous observation on 2026-08-02 and rejected its Radar results as
unreliable. Its active runtime, commissioning, probe, soak, and evidence roots were removed after
the process, launchd labels, and loopback listener were confirmed absent. Deleted history is not a
business premise, denominator, acceptance input, or permission source.

The repository implements a public-only modular monolith: Deribit ingestion, Radar, fixed-contract
Underwriting, Shadow admission, Position management, Outcome projection, and a loopback read-only
Workbench. This implementation fact does not prove production correctness, 24-hour stability,
Policy quality, fillability, profitability, actual exposure, or PnL.

## Current implementation

The merged offline implementation removed the obsolete macOS commissioning controller and the
separate service lifecycle evidence/terminal-manifest system. It simplified `serve-shadow` to the
business runtime itself: one public client, reducer, downstream owner, minimal business
persistence, reconnect loop, signal stop, coalesced Workbench publisher, and loopback
health/readiness HTTP.
It also removes accumulated whole-graph rescans from the downstream writer hot path while retaining
direct per-object validation and offline reader graph validation.
The service-only run-summary path may accept a contiguous omitted zero-duration leading restart
without demanding that a same-timestamp recovered segment repeat the retired reason.

It must preserve market/Decision inputs, all three Policies, Radar semantics, Underwriting,
Shadow, Position, Outcome, causal order, honest `UNKNOWN`, conditioned zero claims, public/private
separation, and GET/HEAD-only Workbench behavior.

## Change declarations

1. **Market/Decision input contract:** `NONE`
2. **Decision Policy:** `NONE`
3. **Outcome/evaluation contract:** `NONE`
4. **Stage/authorization:** `NONE`

## Permission boundary

Allowed:

- read-only inspection and deterministic offline tests of the merged implementation.
- create a new task before any further product, authority, contract, code, or durable-artifact
  change.

Forbidden:

- production-public market, service, probe, commissioning, deployment, or evidence commands;
- reconstructing or relabelling deleted historical results;
- changing market sources, universe, continuity, missingness, detector formulas/thresholds,
  Underwriting, Shadow admission, Position, Outcome, or cohort semantics;
- private/account APIs, credentials, balances, margin, positions, orders, fills, settlement,
  execution gateways, capital, qualification, promotion, or money;
- public Internet binding, databases, full-market persistence, replay platforms, schedulers,
  workflow engines, feature stores, registries, or new services.

## Acceptance and non-claims

Direct offline tests and `make check` must prove the simplified composition, owner continuity,
stop/reconnect/failure behavior, Workbench publication, health/readiness, and read-only loopback
surface. They cannot accept the Radar, authorize deployment, or prove uptime or economics.

Update this document only when capability, permission, the sole closure, or its blocker changes.
