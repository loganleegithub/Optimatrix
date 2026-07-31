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
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)

**Base commit:** `967e82ea36a7fcae13c6c8a8b07108af5b21a633`

**Target branch/PR:** `chatgpt/persistent-radar-shadow-web-workbench` / Draft PR against `main`

## Business closure

**Given:** the accepted production-public Radar reducer and fixed-contract public Shadow owner can
already consume one public Deribit session under one immutable three-Policy chain, but the
repository exposes only bounded observation commands and no trader-facing read-only projection.

**When:** one offline-qualified persistent process host owns one deployment state root, creates one
new runtime identity, freezes the three Policies, maintains one public connection/reducer/Shadow
owner across reconnects, and publishes an immutable read-only trader snapshot over loopback HTTP.

**Then:** an externally supervised process can continue until an explicit stop or fatal integrity
failure; duplicate processes sharing the same state root fail before market I/O; business objects
are terminalized once; and the trader can inspect system, Radar, Underwriting, simulated Shadow,
Position, close-opportunity, and Outcome truth without a second decision engine.

**Independent verification:** direct deterministic tests falsify lease exclusivity, runtime
identity renewal, Policy immutability, health/readiness separation, loopback/read-only HTTP,
terminal idempotence, no-client pre-latched stop, and the absence of a bounded-cohort summary.
Repository CI runs focused tests plus `make check` on the exact candidate.

**Valid zero/no-hit/UNKNOWN result:** zero anomalies, zero Candidates, zero Shadow Entries, zero
Positions, or only `UNKNOWN` rows is valid operating truth. It neither extends process duration nor
changes thresholds. Empty panels display no settled object; `UNKNOWN` is never rendered as zero or
calm.

**Upstream prerequisite:** exact main commit `967e82ea36a7fcae13c6c8a8b07108af5b21a633`,
which records the accepted Radar runtime, fixed-contract Shadow owner/adapter, immutable
three-Policy chain, and the completed two-layer public integration evidence. This task does not
re-open their economics, identity, or evidence semantics.

## Change declarations

**Market/Decision input contract change:** NONE. The same public source, trusted clock, continuity,
official combo, target quantity, and known-at rules remain authoritative.

**Decision Policy change:** NONE. Exact Policy bytes and identities are loaded once before runtime
construction and are not watched or reloaded.

**Outcome/evaluation contract change:** NONE. The existing bounded forward-cohort command retains
its manifest, cutoff, final-stop, summary, and acceptance semantics. The persistent service does
not impersonate a forward cohort and emits no cohort summary.

**Stage/authorization change:** APPROVED — this user-authorized branch may implement and test the
persistent service and read-only workbench offline. Production-public invocation, persistent
deployment, private/account access, orders, fills, capital, qualification, promotion, execution,
and supervisor installation remain forbidden. A later explicit authority task is required before
invocation or deployment.

## Product operating behavior

One process acquires an advisory exclusive lease at `<state-root>/service.lock`. A different state
root is a distinct deployment boundary and is not silently merged. After the lease is held, the
process owns one runtime identity, one Policy chain, one `LiveRadarRuntime`, one `RadarReducer`, one
fixed-contract Shadow owner, one downstream writer, and one public WebSocket client at a time.
Reconnects increment the session epoch but do not create a second business owner or reuse retired
continuity.

The existing runtime remains responsible for heartbeat/test-request handling, bounded ingress,
subscription acknowledgements, resubscription, book continuity, currentness, reconnect barriers,
and `UNKNOWN`. The new host owns only process lifecycle, reconnect delay, signal-to-stop latching,
loopback HTTP, and append-only operational records. It has no threshold, Policy, duration-extension,
or opportunity-generation setter.

SIGINT/SIGTERM latch one exact monotonic stop boundary. Runtime drain and the existing terminal
barrier settle already accepted envelopes, prevent new outbound work, terminate pending
Candidate/Position/Outcome objects once, write the Radar summary, and write one persistent-service
terminal record. A fatal protocol, evidence-integrity, or runtime failure follows the existing
failure terminalization path and cannot be relabeled as a clean stop.

Restarting creates a new runtime identity and a new run directory. Exact Policy identities remain
visible in every run. Policy files may change only between separately started runtimes after human
authorization; the running process never hot-reloads them.

The Web workbench reads immutable snapshots constructed synchronously from the same reducer,
Shadow adapter, and append-only downstream objects. HTTP handlers never call market, Policy,
Underwriting, Position, Outcome, account, or order logic. The browser performs formatting and
rendering only.

Transient facts are the in-memory current reducer/owner state and immutable Web snapshot. Durable
facts are the existing minimal Radar and downstream business objects plus minimal service lifecycle
records. Full order-book depth, private data, credentials, requests from the browser, and browser
state are not persisted.

## Validation harness

Use deterministic temporary state roots, repository Policies, an ephemeral loopback port, a fake
client factory that must remain unopened for a pre-latched stop, and the existing reducer's clean
terminal path. No production-public command, elapsed soak, replay, full-market archive, or external
supervisor installation is part of this task.

## Evidence boundary

**Proves:** the candidate process composition, lease, lifecycle state machine, read-only projection,
HTTP method boundary, and terminal plumbing behave as specified under deterministic tests.

**Does not prove:** indefinite uptime, production deployment safety, forward market coverage,
natural Candidate/Entry/Position/Outcome occurrence, Policy quality, forecast quality, edge,
profitability, fill quality, actual fees, private-account truth, or execution authority.

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

**In:** process lease; persistent runtime composition; reconnect loop using the existing runtime;
new runtime identity per start; immutable Policy chain; lifecycle/health/ready/stale projection;
minimal append-only service records; loopback read-only HTTP/API; trader-flow HTML; focused tests;
architecture documentation; the narrow CLI composition needed to expose the capability while its
invocation remains unauthorized.

**Out:** changing existing contracts or Policies; a second market client/reducer; database; queue;
microservice split; full order-book storage; replay; fixed process duration; automatic calibration;
launchd/systemd installation; production-public invocation; private/account/order/fill/capital;
write APIs; authentication exposed beyond loopback; public Internet binding; order buttons.

**Owning module/artifact:** `apps/radar_runtime/src/radar_runtime/service.py`,
`apps/radar_runtime/src/radar_runtime/workbench.py`, the existing CLI entry point, direct tests, this
task, `docs/architecture/PERSISTENT_RUNTIME_TRADER_WORKBENCH.md`, and the narrow authority record
that keeps live invocation and deployment disabled.

## Contract

**Inputs and known-at rule:** exact repository code identity; exact three-Policy bytes and digests;
one external state root; loopback port; public Deribit facts accepted only by the existing causal
runtime. The workbench may show only current reducer state or already settled downstream objects.

**Durable output and identity:** one new runtime directory per process identity; existing Radar and
downstream objects retain their contract identities; service events and the terminal record are
content-identified, append-only, runtime-bound operational evidence. They are not a forward cohort.

**Missing/invalid/UNKNOWN semantics:** missing clock/catalog/currentness/quote/economics remains
`UNKNOWN`; reconnect is `INTERRUPTED`; accepted but incomplete data may be `DEGRADED`; stale source
or liveness/queue-lag breach is `STALE`; stopped and failed are terminal process states. The front
end does not infer missing values.

**Persisted meaning and compatibility:** new workbench schema version `1` is a read-only runtime
projection and not a business contract or historical API promise. Existing business object schemas
remain `COMPATIBLE`; no migration occurs. Persistent service lifecycle objects are new and not
comparable to bounded forward-cohort summaries.

**Business denominators:** workbench `coverage_ratio_percent` is explicitly
`known current instrument evaluations / monitored instrument evaluations` for the current runtime
snapshot. Zero denominator is `null`. It is not market coverage, opportunity rate, success rate, or
forecast accuracy.

## Acceptance

### Direct behavior

1. A second process using the same state root fails its lease; after release the root can be used by
   a new runtime identity.
2. One startup constructs exactly one immutable Policy chain shared by the reducer and Shadow
   owner; no hot-reload or lifecycle threshold surface exists.
3. Process health can be live while readiness is false; stale/degraded/interrupted/unknown remain
   distinct and are projected without strategy recomputation.
4. HTTP binds only to loopback, accepts only `GET`/`HEAD`, exposes no mutation or order route, and
   labels Shadow Entry as simulation rather than an order or fill.
5. A pre-latched stop opens no market client and still writes one Radar summary and one service
   terminal record. Repeated terminal finalization creates no second terminal file or cohort
   summary.
6. Existing `observe` and `observe-shadow` commands retain their behavior and bounded evidence
   semantics.

### Required commands

- `make sync`
- focused tests: `pytest tests/test_persistent_service.py tests/test_trader_workbench.py`
- `make check`
- production-public command: NOT_APPLICABLE; live commands are forbidden
- independent recomputation or reconstruction command: NOT_APPLICABLE

### Real evidence

**Required:** NO

**Environment and stopping condition:** deterministic offline tests only. The implementation is not
invoked against Deribit and no supervisor is installed.

**Required report:** exact base/head/tree, changed files, focused tests, `make check`, CI, limitations,
no-live-command statement, and remote branch/PR state.

**Private API:** FORBIDDEN.

## Artifacts and delivery report

**Artifact paths and digests:** NOT_APPLICABLE until an authorized runtime is invoked. Test temp
files are not product evidence.

**Policy/contract identities:** unchanged exact repository Policy and contract identities at the
base commit.

**Commit/PR:** recorded by Git and the final delivery report.

**Unknowns and non-claims:** the workbench is not a second decision system, complete market view,
fill simulator, actual PnL ledger, cohort evaluator, qualification result, deployment receipt, or
execution surface.

## Definition of done

The offline implementation candidate satisfies the direct behavior above; existing business
contracts and commands remain unchanged; all tests and CI pass on the exact candidate; the diff is
bounded to this closure; no production-public command is run; and the Draft PR clearly requires
Codex review and separate authority before invocation or deployment.
