# Task — Workbench publication coalescing

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED — only the settled Workbench publication path and its
pre-terminal flush boundary

**Live commands:** FORBIDDEN — no service process or observation remains active; this task does not
deploy, restart, probe, commission, or collect market evidence

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `4c054013de9254854d2e20647b4963f40a617697`

**Target branch/PR:** `codex/workbench-publication-coalescing`; one bounded Draft PR after
independent exact-candidate review, with no force push or direct `main` edit

## Business closure

**Given:** the public-Shadow runtime settles every accepted fact through the complete Radar,
Underwriting, Shadow, Position, and Outcome path, while the read-only Workbench currently rebuilds
and serializes a complete schema-2 snapshot for every settled fact.

**When:** ordinary status-stable Workbench publications are coalesced to one complete publication
per 500 monotonic milliseconds, semantic safety/lifecycle status changes bypass that interval, and
the latest pending business state is flushed once after accepted-event draining and before
reconnect or clean-stop terminalization.

**Then:** all business facts continue to settle in causal order, the browser receives complete
immutable schema-2 snapshots at at most 2 Hz during a busy status-stable interval, safety status is
visible immediately, and no latest settled fact is lost at a runtime terminal boundary.

**Independent verification:** direct publisher and runtime-boundary tests prove the exact cadence,
latest fact boundary, status bypass, terminal flush ordering, and publication atomicity; focused
tests and `make check` prove no adjacent behavior changed.

**Valid zero/no-hit/UNKNOWN result:** panel emptiness, numeric-zero conditioning, `UNKNOWN`, and
`NOT_EVALUATED` remain semantic equivalents in each published snapshot. Coalescing does not create,
remove, or reinterpret a business object and does not satisfy a market or economic denominator.

**Upstream prerequisite:** the accepted schema-2 immutable snapshot publisher and the runtime's
existing drain-before-reconnect/clean-stop barrier already exist.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — invalidate the rejected historical online results and
authorize only this offline implementation and its deterministic verification. Public/private
scope and execution authority do not change; live commands are forbidden.

## Product operating behavior

Every accepted runtime fact still completes the full owning reducer and fixed-contract Shadow
transaction. The publisher then derives the lightweight settled status and remembers only the
latest reducer plus committed fact boundary.

- A semantic status-key change publishes one complete immutable snapshot immediately.
- An ordinary status-stable fact publishes only when at least 500 monotonic milliseconds have
  elapsed since the last complete publication; otherwise it replaces the pending in-memory
  reference to the latest settled state.
- An explicit lifecycle status update publishes immediately and includes the latest pending
  settled business state.
- `flush_pending()` is a no-op when clean. When dirty, it publishes the latest complete snapshot.
  Runtime invokes it exactly once after accepted-event and barrier-deadline draining and before
  `prepare_reconnect` or `clean_stop` mutates terminal state.
- Publication and cached-state bookkeeping commit only after the immutable snapshot store accepts
  the complete encoded body. A serialization/publication failure preserves the prior snapshot and
  leaves the latest state pending for the owning failure path.

There is no timer, thread, queue, scheduler, partial-patch protocol, new endpoint, or durable
publication record. If no fact or lifecycle event arrives, there is nothing new to publish.

## Validation harness

Use deterministic monotonic boundaries already carried by status and committed facts. Do not add a
clock service or sleep-based test.

Direct tests prove:

1. many ordinary status-stable facts inside 500 ms cause one initial complete publication;
2. the first settled fact at or after 500 ms publishes the latest state and fact boundary;
3. a semantic safety-status transition bypasses the interval;
4. a lifecycle update immediately flushes pending business state;
5. runtime flushes pending state after drain and before reconnect/clean-stop terminal mutation;
6. failed serialization/publication does not replace the store or advance committed publication
   state, and the latest settled state remains pending.

No production-public observation is required: cadence and ordering are deterministic runtime
behavior, and no runtime is currently deployed.

## Evidence boundary

**Proves:** deterministic publication coalescing, complete latest-state publication, immediate
status bypass, terminal-boundary flush ordering, and atomic snapshot replacement.

**Does not prove:** lower production CPU, 24x7 stability, market coverage, opportunity frequency,
Policy quality, fillability, profitability, actual exposure, PnL, or deployment acceptance.

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

**In:** `apps/radar_runtime/src/radar_runtime/workbench.py`; the settled-publisher protocol and one
pre-terminal `flush_pending()` call in `apps/radar_runtime/src/radar_runtime/runtime.py`; direct
tests; the persistent-service contract; architecture/authority/README truth; this task.

**Out:** `commissioning.py`; `service.py`; Radar, Underwriting, Shadow, Position, Outcome, owner,
evidence-writer, or Policy semantics; workbench schema version, HTTP routes, browser polling,
partial/SSE transport, dependencies, containers, launchd, live deployment, and deleted historical
evidence.

**Owning module/artifact:** `radar_runtime.workbench.WorkbenchPublisher` and the existing
`LiveRadarRuntime.run` drain-to-terminal boundary.

## Contract

**Inputs and known-at rule:** the latest fully settled reducer transaction, its immutable
`CausalCommit`, and the current lifecycle status. A published snapshot may include only a commit
already settled at or before its `published_fact_boundary`.

**Durable output and identity:** `NOT_APPLICABLE`; Workbench snapshots remain non-durable schema-2
operational projections.

**Missing/invalid/UNKNOWN semantics:** unchanged. A pending projection never turns missing facts
into zero or keeps an earlier row current after a complete later snapshot is published.

**Persisted meaning and compatibility:** the Workbench JSON schema and service evidence schemas are
`COMPATIBLE` and unchanged. The changed implementation-contract bytes receive a new content digest
for any future newly authorized runtime. Deleted historical evidence is not reconstructed,
migrated, or relabelled.

**Business denominators:** unchanged. Publication calls, coalesced facts, snapshots, and elapsed
milliseconds are operational units, not Radar, Candidate, Entry, Position, or Outcome units.

## Acceptance

### Required commands

- `make sync`
- focused publisher/runtime tests
- `pytest tests/test_authority_and_architecture.py`
- `make check`
- production-public command: `NOT_APPLICABLE` — direct tests fully falsify this behavior

## Artifacts and delivery report

**Artifact paths and digests:** `NOT_APPLICABLE`

**Policy/contract identities:** all three Policy files remain byte-identical; record the new exact
persistent-service contract digest in the delivery report.

**Commit/PR:** record exact commit/tree, checks, independent review, remote state, and non-claims.

**Unknowns and non-claims:** offline verification does not claim measured CPU reduction, Radar
acceptance, deployment acceptance, or 24-hour stability.

## Definition of done

The six direct behaviors pass; focused tests and `make check` pass; the final diff contains only
the declared publication boundary, direct tests, and required authority/contract truth; no runtime
or market command was issued; and no deployment or stage acceptance is inferred from green tests.
