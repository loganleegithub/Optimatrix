# Task — Persistent public Radar/Shadow runtime and read-only trader workbench

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md),
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `967e82ea36a7fcae13c6c8a8b07108af5b21a633`

**Target branch/PR:** `chatgpt/persistent-radar-shadow-web-workbench` / Draft PR against `main`

## Business closure

**Given:** the accepted public Radar reducer and fixed-contract public Shadow owner have passed
bounded deterministic and production-public integration evidence, but the repository exposes only
bounded `observe` / `observe-shadow` commands and no trader-facing read-only projection.

**When:** one offline-qualified persistent process host owns one external state root, creates one
new runtime identity, freezes the exact three Policies, reuses the sole public client/reducer/Shadow
owner across reconnects, writes the persistent-service evidence contract, and atomically publishes a
loopback read-only trader snapshot after each settled Radar-plus-Shadow transaction.

**Then:** the implementation is ready for Codex review without authorizing invocation or deployment;
a duplicate process fails before market I/O; a future authorized process can stop gracefully and
terminalize once; and a trader can inspect settled system, Radar, Underwriting, simulated Shadow,
Position, close-opportunity, and Outcome truth without a second decision engine.

**Independent verification:** deterministic tests falsify lease exclusivity, runtime identity
renewal, Policy immutability, reconnect continuity, state separation, exact service evidence,
complete-reader failure modes, atomic snapshot ordering, loopback/read-only HTTP, no-client
pre-latched stop, terminal idempotence, and truthful empty/zero/null UI fixtures. Repository CI runs
focused tests and `make check` on the exact candidate.

**Valid zero/no-hit/UNKNOWN result:** panel emptiness and business zero are separate. An empty panel
means no matching settled object is present; it is not a zero claim. A numeric zero-anomaly claim
requires a known complete non-empty monitor denominator. Numeric zero Candidate additionally requires a
strictly positive Underwriting-evaluable denominator. Unknown or zero denominators serialize and
render as `null / UNKNOWN`, never `0`, calm, or no opportunity.

**Upstream prerequisite:** exact accepted main commit
`967e82ea36a7fcae13c6c8a8b07108af5b21a633`, including the accepted Radar runtime, fixed-contract
Shadow owner/adapter, immutable three-Policy chain, and closed two-layer engineering evidence.

## Change declarations

**Market/Decision input contract change:** NONE. Public sources, universe, trusted time,
continuity/currentness, official atomic combo, target quantity, and known-at rules are unchanged.

**Decision Policy change:** NONE. Exact Radar, Underwriting, and Position Policy bytes and identities
are loaded once before runtime construction; no watcher, reload, tuning, promotion, or
no-opportunity extension surface is added.

**Outcome/evaluation contract change:** APPROVED — add exact semantic identity
`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`, contract digest
`sha256:e3e6c91aaefcdc867a0cdd64d528cebfe2b3a40681e192c7f4f924bdbfc27bff`, and its non-cohort
run-segment lifecycle/terminal/conservation/writer/reader semantics. It also adds one exact Radar
summary compatibility rule for a transport generation retired at the coverage-start instant: only a
contiguous unrecovered zero-duration restart chain may precede the first represented coverage epoch.
Existing Candidate, Position, Outcome, rejected-counterfactual, and aligned-pair objects remain
governed by their current contracts, but service-created units are explicitly
`cohort_enrolled=false`; no manifest, enrollment cutoff, or forward-cohort summary is emitted.
`observe` and `observe-shadow` business behavior and bounded evidence semantics remain unchanged.

**Stage/authorization change:** APPROVED — activate this exact offline implementation closure only.
Permission remains `PUBLIC_SHADOW`; `serve-shadow`, every production-public invocation, persistent
deployment, supervisor installation, 24x7 acceptance, private/account access, orders, fills,
capital, qualification, promotion, and execution remain `FORBIDDEN`.

## Product operating behavior

A future separately authorized process acquires a non-blocking exclusive lease at
`<state-root>/service.lock` before creating any client. One startup creates one new canonical
runtime identity and one run directory. Reconnects increment the session epoch but retain the same
runtime, reducer, owner, and frozen Policy chain. Process restart never resumes old business state.

The existing runtime owns heartbeat/test-request handling, bounded ingress, subscription
acknowledgement, reconnect/resubscription, catalog and book continuity, clock/index/ticker
currentness, queue lag, `UNKNOWN`, and drain barriers. The service host owns only lifecycle,
reconnect delay, first-signal stop latching, loopback HTTP, and exact service evidence. It has no
threshold, duration-extension, or opportunity-generation setter.

SIGINT/SIGTERM latch the first exact monotonic boundary. Runtime drain settles already accepted
envelopes, prevents new outbound work, terminalizes valid Candidates and pending observations once,
and writes the Radar summary on clean stop. Process failure preserves partial Radar semantics and
cannot be relabeled clean.

The persistent Shadow adapter uses no forward-cohort manifest or enrollment window. It writes normal
business objects through the existing downstream writer, terminalizes them through the existing
owner, and then writes one service-specific terminal record whose independently recomputed counts,
rates, inventory, and conservation statuses are `MET`. It rejects any bounded cohort summary in the
service directory.

After each normal fact transaction completes Radar settlement and Shadow owner settlement,
`runtime.py` invokes one snapshot publisher. The publisher builds complete immutable JSON bytes and
atomically replaces the published reference. HTTP handlers read only this reference. Lifecycle-only
republishing reuses the previous immutable business body and never traverses mutable runtime or owner
state.

Transient facts are current in-memory reducer/owner state and the immutable published snapshot.
Durable facts are existing minimal Radar/downstream objects plus exact service lifecycle/terminal
records. Full books, ordinary no-anomaly rows, HTTP requests, browser state, private data,
credentials, orders, and fills are not persisted.

## Validation harness

Use temporary external state roots, exact repository Policies, an ephemeral loopback port, fake
public client contexts, and deterministic reducer/owner fixtures. The pre-latched-stop fixture must
prove that no client factory is called and still produce one Radar summary and one valid service
terminal. No Deribit command, elapsed soak, replay, full-market archive, external supervisor, or
24x7 process is part of this task.

## Evidence boundary

**Proves:** offline process composition, lease, runtime identity renewal, immutable Policy sharing,
reconnect lifecycle, stop/terminal plumbing, service evidence identity/reader integrity, atomic
read-only projection, HTTP method/host boundary, and truthful zero/null rendering.

**Does not prove:** production invocation, indefinite uptime, deployment safety, forward market
coverage, natural Candidate/Entry/Position/Outcome occurrence, Policy quality, opportunity
frequency, forecast skill, edge, fillability, actual fees, actual PnL, profitability,
private-account truth, qualification, promotion, or execution.

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

**In:** Current Stage authorization for offline implementation; persistent-service contract;
single-instance lease; startup/run composition; new runtime identity; immutable three-Policy chain;
reconnect loop using the existing runtime; lifecycle/health/ready/stale/UNKNOWN state; exact
append-only service evidence and complete reader; runtime-settled immutable snapshot publisher;
loopback GET/HEAD workbench; CLI wiring; direct and authority tests; architecture documentation.

**Out:** Policy or business-rule changes; second market client/reducer/owner; database, queue, or
microservice split; full-book persistence; replay; automatic calibration; launchd/systemd/Docker
unit; production-public invocation; 24x7 evidence; private/account/order/fill/capital; write APIs;
Internet binding; browser Deribit connection; order controls.

**Owning module/artifact:** `apps/radar_runtime/src/radar_runtime/service.py`,
`service_evidence.py`, `workbench.py`, `runtime.py` publisher hook, the exact zero-duration
continuity validation in `short_vol_radar/evidence.py`, CLI, exact service contract, Current
Stage/System Architecture, and direct tests.

## Contract

**Inputs and known-at rule:** exact clean code identity; exact service-contract digest; exact
three-Policy bytes/identities; external state root; loopback host/port; only facts settled by the
existing causal runtime. The workbench displays only a published immutable settled snapshot.

**Durable output and identity:** one new runtime directory; existing Radar/downstream identities;
content-identified lifecycle events; one content-identified service terminal. No forward-cohort
manifest or summary.

**Missing/invalid/UNKNOWN semantics:** missing/stale/discontinuous facts remain `UNKNOWN` at their
smallest scope. `RECONNECTING` projects `INTERRUPTED`. Explicit currentness expiry projects `STALE`.
Connected but incomplete data may be `DEGRADED`. Empty panels do not imply zero. Invalid/mixed/
missing/incomplete service evidence fails closed.

**Persisted meaning and compatibility:** service schema version 1; exact required fields and identity
recomputation; dedicated current and complete readers; `NOT_COMPARABLE` to bounded
forward-cohort evidence; no migration. Existing business object schemas remain `COMPATIBLE`.

**Business denominators:** monitor zero-anomaly denominator is the current non-empty fully known
relevant monitor scope. Candidate zero denominator is the count of current or terminal
Underwriting-evaluable opportunities and must be positive. Coverage ratio is known current
instrument evaluations divided by monitored current instruments; denominator zero gives `null`.
No value is an opportunity-frequency or profitability claim.

## Acceptance

### Direct behavior

1. Same-root second lease fails before client construction; release permits a new, different runtime
   identity.
2. One startup shares one immutable PolicyChain across reducer and owner and exposes no reload path.
3. Reconnect retires prior continuity, increments session epoch, preserves the one business owner,
   and distinctly projects `INTERRUPTED / UNKNOWN / STALE / DEGRADED / CURRENT`; an immediate
   zero-duration first generation remains a validated diagnostics restart rather than a fabricated
   positive-duration coverage segment.
4. Snapshot publication occurs in `runtime.py` only after the same transaction's Shadow transition;
   GET/HEAD reads immutable bytes and never invokes business functions or mutable private containers.
5. HTTP rejects non-loopback binding, accepts only GET/HEAD, returns 405 for mutations, and contains
   no order, Policy, private-account, credential, or Deribit browser route.
6. Lifecycle/terminal writer and readers recompute exact identities, digests, schemas, inventory,
   counts, rates, null denominators, and conservation; missing/corrupt/mixed/duplicate/pending
   evidence fails closed.
7. Pre-latched stop opens no client, writes exactly one Radar summary and service terminal, emits no
   forward-cohort summary, and repeated finalization creates no second terminal.
8. Empty-panel fixtures remain separate from zero claims; zero or unknown denominators display
   `null / UNKNOWN` and never calm/no-opportunity text.
9. Existing `observe` and `observe-shadow` behavior and bounded evidence semantics remain green.

### Required commands

- `make sync`
- focused tests: `pytest tests/test_persistent_service.py tests/test_trader_workbench.py tests/test_authority_and_architecture.py`
- `make check`
- `git diff --check`
- production-public command: NOT_APPLICABLE; live commands are forbidden
- independent recomputation/reconstruction: NOT_APPLICABLE

### Real evidence

**Required:** NO

**Environment and stopping condition:** deterministic offline tests only.

**Required report:** exact branch/base/head/tree, commits and changed files relative to base, focused
and full checks, CI, Draft PR, explicit removal of temporary workflow, and all unexecuted/non-proven
items.

**Private API:** FORBIDDEN.

## Artifacts and delivery report

**Artifact paths and digests:** NOT_APPLICABLE; test temporary files are not product evidence.

**Policy/contract identities:** existing three contracts and three Policies unchanged; new service
contract digest exactly
`sha256:e3e6c91aaefcdc867a0cdd64d528cebfe2b3a40681e192c7f4f924bdbfc27bff`.

**Commit/PR:** append-only non-force commits on the named branch and Draft PR against `main`.

**Unknowns and non-claims:** implementation and green tests are not live authority, deployment,
24x7 evidence, strategy validation, a complete market view, actual PnL, qualification, or execution.

## Definition of done

The authority and contract accurately authorize only this offline implementation; the runtime,
service evidence, projection, HTTP, and tests satisfy the exact behavior above; existing commands
remain unchanged; focused/full/diff/CI checks pass; temporary transfer infrastructure is absent from
the final diff; the remote branch and Draft PR bind the exact candidate; and no live/private/account/
order/fill/capital/deployment action occurred.
