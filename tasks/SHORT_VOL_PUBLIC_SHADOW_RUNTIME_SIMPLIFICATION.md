# Task — Public Shadow runtime simplification

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract:**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `89aca5b188d003401654eb3b0988d26c3071ce0b`

**Target branch:** `codex/public-shadow-runtime-simplification`

## Business closure

**Given:** the repository already has one public Deribit process that settles Radar, Underwriting,
Shadow admission, Position, Outcome, and a read-only Workbench, but the process is wrapped in a
macOS commissioning controller and a separate service lifecycle evidence ledger.

**When:** those non-business control/evidence systems are removed and the persistent service is
composed directly from the market client, owners, minimal business writers, and Workbench.

**Then:** one command runs the complete public-only business loop continuously until signal or
failure, reconnects with the same in-memory owner graph, publishes coalesced immutable Workbench
snapshots, and persists only Radar and downstream business objects needed by the product.

**Independent verification:** direct offline tests cover composition, single-instance ownership,
stop/reconnect/failure behavior, business-owner continuity, snapshot ordering/coalescing, and the
read-only health surface; `make check` covers the repository.

**Valid zero/no-hit/UNKNOWN result:** no anomaly, no Candidate, or missing current facts keep their
existing conditioned zero/null/`UNKNOWN` meaning. They neither fail the service nor create a
business object.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED only for this offline implementation refactor. It grants
no live, deployment, private API, order, fill, or capital authority.

## Product operating behavior

`serve-shadow` owns one process, one public Deribit client at a time, one reducer, one downstream
owner, one state root, and one loopback Workbench. It holds a simple process lock, reconnects after
recoverable public transport failures, and stops on `SIGINT`/`SIGTERM`.

Every accepted market fact still settles the complete business path before Workbench publication.
Ordinary stable snapshots remain coalesced to at most 2 Hz; safety/lifecycle changes publish
immediately; the latest settled state flushes before reconnect or stop. HTTP remains GET/HEAD-only
and loopback-only.

Durable output is limited to existing minimal Radar anomaly/atomic/run-summary objects and
downstream Underwriting/Shadow/Position/Outcome objects. Service lifecycle events, terminal
manifests, inventories, hashes, acceptance receipts, probes, `lsof`, unified-log inspection, and
launchd control are not product behavior and are removed.

The fixed-contract owner retains required domain validation and truthful `UNKNOWN` handling.
Deleting code by file size alone is forbidden when that code owns business economics, identity,
causality, or public/private separation.
Each downstream object is still validated directly before publication, but the online writer no
longer rescans the complete accumulated relationship graph on every transition. Current/complete
readers and direct tests retain graph validation.
For an omitted zero-duration leading session, the service summary validates the contiguous
restart boundary without requiring the first positive-duration coverage state to repeat a restart
reason that may already have recovered at the same timestamp.

## Evidence boundary

**Proves:** the simplified offline composition preserves the complete public business path and
removes the obsolete control/evidence layers.

**Does not prove:** production Radar correctness, uninterrupted 24-hour uptime, market coverage,
opportunity frequency, fillability, profitability, actual exposure, or PnL.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** persistent service composition and CLI, Workbench runtime bindings/status, downstream
writer hot-path graph-scan removal, the service-only zero-duration summary check, removal of
commissioning and service-evidence modules and their tests, direct replacement tests, and exact
authority/contract/architecture/README truth.

**Out:** Deribit protocol, universe, detector formula/Policy, Underwriting economics, Shadow
admission, Position and Outcome semantics, private APIs, order/fill/account code, live execution,
and deployment.

**Owning modules:** `radar_runtime.service`, `radar_runtime.workbench`,
`short_vol_underwriting.evidence`, and their direct tests.

## Acceptance

1. Importing/running the service has no commissioning, `launchd`, `lsof`, unified-log, probe,
   service-manifest, lifecycle-receipt, or service-inventory dependency.
2. The service still owns a single instance, creates one fresh runtime, loads exactly one frozen
   three-Policy chain, and composes Radar through Outcome plus Workbench.
3. Recoverable public failures reconnect without replacing the owner; terminal signals stop
   cleanly; fatal failures terminate downstream state and remain visible in Workbench status.
4. Workbench health/readiness, coalescing, terminal flush, loopback binding, and read-only routes
   pass direct tests.
5. Every downstream write still performs direct object schema/identity/provenance validation;
   accumulated relationship validation runs in readers/tests, not once per hot-path write.
6. Immediate recoverable reconnect followed by stop produces a valid summary instead of failing
   because a recovered first segment does not repeat the retired session's reason.
7. `make sync`, focused tests, authority tests, and `make check` pass.

## Non-claims

No live command is run. Green tests do not accept the Radar or deployment and do not establish a
24-hour result. Historical runtime/evidence material remains deleted from active locations and is
not reconstructed.

## Definition of done

The obsolete layers and references are absent; the remaining service is one coherent public-only
business runtime; direct and full checks pass; the final diff contains this one closure; and no
future refactor phase is required to obtain the simplified architecture described above.
