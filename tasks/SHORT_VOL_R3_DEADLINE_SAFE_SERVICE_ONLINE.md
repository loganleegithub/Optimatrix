# Task — R3 deadline-safe persistent service online

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED — repo-owned commissioning/stop controller only; the
accepted `serve-shadow` hot path, market/runtime behavior, contracts, and Policies remain unchanged

**Live commands:** REQUIRED

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `ce1fbb48417f2b44ae3a69900d0b71c3e55c7565`

**Target branch/PR:** `codex/r3-deadline-safe-service-online` / one Draft PR, promoted and
merged only after exact-candidate independent review and CI pass

## Business closure

**Given:** the accepted persistent public-Shadow service/workbench runtime is immutable, the r1
and r2 attempts are sealed and consumed, no related process or launchd label is loaded, loopback
port `8765` is free, and no live command is currently authorized.

**When:** the repo-owned deadline-safe commissioning controller and this conditional authority are
independently accepted and merged, the controller binds the resulting remote `main` commit/tree
and unchanged service-hot-path/contract/Policy bytes into an entirely fresh r3 deployment
envelope, installs the fresh r3 service and read-only probe, and invokes that pre-bound controller
in `commission` mode exactly once.

**Then:** exactly one accepted runtime process is started under the fresh r3 label and root; its
loopback-only workbench at `127.0.0.1:8765` is commissioned against the actual lifecycle schema;
the first successful, contiguous read-only probe row is durably recorded no later than 120,000 ms
after the service lifecycle start; and read-only observation continues until an explicit user
`停止` or terminal process failure.

**Independent verification:** review the exact activation commit and frozen external artifact
digests; recompute the deployment envelope bindings; inspect launchd, PID, argv, cwd, listener,
run-root uniqueness, lifecycle identity, schema-2 health/ready/workbench responses, current reader,
probe sequence, and commissioning timestamps without using the controller's verdict as truth.

**Valid zero/no-hit/UNKNOWN result:** zero natural Candidate/Entry/close-opportunity/Outcome and
truthful business `UNKNOWN` are valid observable states and leave strategy quality, opportunity
frequency, PnL, and 24-hour acceptance incomplete. They do not falsify service commissioning.
Missing, stale, invalid, non-contiguous, late, or contaminated service/probe evidence fails closed,
consumes the one r3 attempt after start, and grants no retry.

**Upstream prerequisite:** exact accepted service/workbench runtime commit and contract identity,
plus clean r2 terminal closure at the base commit, are already established in
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md).

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — conditional terminal-goal delegation for the repo-owned
controller implementation, exact-candidate review/CI/merge, and then one r3 production-public
persistent-service invocation and its loopback read-only workbench/probe under the exact fresh
boundary below; one attempt, no retry, no reboot auto-start, and no alternate root or label. No
live or launchd mutation is allowed unless the exact controller candidate and resulting remote
`main` have first passed every pre-bound implementation gate.

## Product operating behavior

The accepted `serve-shadow` market/service hot path remains byte-for-byte unchanged and does not
import the new controller. It consumes only the already authorized production-public source,
writes its own append-only service/run evidence, exposes immutable read-only projections on
loopback, and creates no orders, fills, actual positions, realized PnL, or account/private-data
access. The resulting Git/code identity is new because this closure adds the sibling controller
and authority record; that identity is frozen and requalified before deployment. The service
remains active after successful commissioning until an explicit user `停止` or terminal failure;
observation duration is not a trading cadence.

The repo-owned controller is isolated deployment/validation tooling, not part of the service hot
path. It may read public service evidence and host process/network metadata, write only the fresh
deployment envelope, exact-once journal, commissioning receipts, probe ledger, logs, and audits,
and issue only the exact start/stop controls declared here. It may not recompute strategy
decisions, mutate service evidence, alter Policy, restart the service, or infer business truth
from UI rendering. Attempt-specific plists and any thin probe/audit launch wrappers remain fresh
external evidence assets whose exact bytes are bound by the envelope.

## Validation harness

The entirely new r3 boundary is frozen before start:

- root: `/Users/logan/Optimatrix-public-shadow-observation-003`
- service label: `com.optimatrix.public-shadow.r3`
- probe label: `com.optimatrix.public-shadow.r3.probe`
- installed service plist:
  `/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r3.plist`
- installed probe plist:
  `/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r3.probe.plist`
- listener: exactly `127.0.0.1:8765`
- service: `KeepAlive=false`, `RunAtLoad=false`, `LaunchOnlyOnce=true`
- probe: read-only, `RunAtLoad=false`, 60-second interval, no service control

The fresh pre-start deployment envelope binds the merged remote `main` commit/tree, task and
authority digests, accepted service-contract identity, exact three Policy identities,
runtime-identity derivation rule, the resolved fresh-checkout `.venv/bin/python` executable digest
and exact version, argv, cwd, root, labels, listener, plist bytes, repo-owned controller module
bytes, unchanged `apps/radar_runtime/src/radar_runtime/service.py` hot-path digest, probe/audit
wrapper bytes, old-root inventory hashes, and preflight facts. Its canonical-JSON
`sha256:<64 lowercase hex>` content identity is supplied independently to the controller CLI as
`--expected-envelope-identity`; mismatch fails before any mutation, and every intent journal and
success, failure, or stop receipt references that exact envelope identity.

The dynamic runtime identity cannot exist before start. The controller validates it from the first
actual lifecycle event, then creates the second-stage binding by freezing it in every later
runtime-bound journal, probe, audit, and receipt; no-runtime artifacts retain the pre-start envelope
identity and a null runtime identity rather than inventing one. Historical r1/r2 inventory hashes,
writer absence, old-label absence, and the facts that the r3 root and installed plists were absent
before materialization are independently recomputed by an external preflight while observable and
then frozen into the envelope. The controller validates their exact envelope shape plus every fact
still observable at invocation—Git/artifact/plist bindings, current labels/listener, output
freshness, and source readability—but does not claim that an already materialized r3 root can
re-prove its own earlier absence. The envelope also records that old roots are governed by sealed
hashes and absence of writers rather than falsely claiming filesystem read-only flags.
No r1/r2 state-directory, ledger, log, receipt, plist, or evidence-artifact byte may become r3
evidence; historical source patterns may be studied, but r3 attempt assets are newly authored and
independently bound.

The controller's `commission` mode owns the sole `launchctl kickstart` without `-k` and may be
invoked exactly once. Every host mutation first fsyncs an exact intent journal; once
`KICKSTART_INTENT` exists, every later `commission` invocation refuses a second start. Lifecycle
sequence 1 must appear no later than 30,000 ms after kickstart. From its actual
`recorded_monotonic_ms`, one absolute deadline governs every remaining commissioning wait:
read-only commissioning must pass by +60,000 ms, one manual probe ledger sequence 1 must pass by
+90,000 ms, and one independent current audit plus periodic-probe bootstrap must pass by
+110,000 ms, leaving a 10,000 ms fail-close margin before the hard 120,000 ms first-probe contract
deadline. No stage gets a fresh timeout.

The controller validates the actual first lifecycle schema and
`persistent_service_contract_identity`, one PID and one run, exact argv/cwd/root, loopback listener
uniqueness, schema-2 health/ready/workbench payloads, and the strict current reader. Honest
`ready=false`/HTTP 503 during market warmup is commissionable when schema and projection agree;
health must be true and the workbench must be a valid current publication. The controller executes
one identical read-only collection for ledger sequence 1 before loading the periodic probe, then
runs the independent current audit, and only after both pass bootstraps the periodic probe label.
It writes a durable success or failure receipt and never retries.

Before the live invocation, the exact repo-owned controller must pass focused tests, full
`make check`, independent exact-commit review, remote-branch equality, GitHub CI, and merge into
remote `main`. Direct offline tests must prove that it accepts the actual lifecycle field set,
rejects a fabricated `contract_digest` requirement, enforces every absolute deadline, cannot
issue more than one start, leaves the probe unloaded before commissioning and manual sequence 1
pass, produces contiguous ledger sequence 1, and invokes the exact failure-stop path once after a
post-start failure. The controller uses the fresh checkout `.venv` Python; it must not rely on the
previously observed incompatible system-Python monotonic clock. The preflight also freezes the host
DiagnosticReports inventory and the previous r2 CPU-resource report as old evidence. Each r3 probe
records exact-PID CPU and RSS plus any new exact-PID resource event; those facts are a separate
operability observation and never become Radar truth, business `UNKNOWN`, or a hidden readiness
override.

Those tests separately cover the 30,000/60,000/90,000/110,000 ms absolute boundaries; all
start/adjacent/end periodic gaps across the full 180,000 ms gate; the 30,000 ms resource grace and
unknown-source failure; kickstart/lifecycle absence with no-runtime closure; `stop` mode's lack of
start capability; terminal-before-bootout ordering; final label/PID/listener absence; duplicate
commission/stop refusal; and no second signal, start, or retry.

After periodic-probe bootstrap succeeds, `commission` durably records
`HOST_OPERABILITY_GATE_START` and remains responsible for a full 180,000 ms gate from that exact
monotonic boundary. The same PID must remain live with launchd `runs=1`; at least two successful
periodic rows strictly after manual row 1 must exist; every gap in the complete partition—gate
start to first row, each adjacent periodic-row pair, and latest row to gate end—must be at most
90,000 ms. Every attempted probe and required endpoint must remain operational, and the frozen
host-log/DiagnosticReports baseline must show no new exact-PID `cpu_resource` event. CPU-time
delta, monotonic elapsed, derived
single-process CPU utilization, RSS, HTTP latency, truthful readiness/currentness, and queue-lag
transitions are recorded with units and denominators. CPU/RSS values without a new host resource
event are diagnostic rather than an invented business or Policy threshold. Gate failure consumes
the attempt and uses the one failure-stop path; gate success establishes only this full bounded
operability interval, not 24x7.

Preflight must prove that the host unified-log source and DiagnosticReports directory are readable
and freeze their exact cursor/inventory. At gate end the controller waits one fixed 30,000 ms
resource-event publication grace, then queries both sources exactly through that audit boundary.
Unreadable sources, query failure, or indeterminate PID attribution is
`UNKNOWN_OPERABILITY_RESOURCE_GATE` and fails closed. A pass claims only that no new exact-PID
resource event was observable as of the frozen boundary; it makes no claim about later emission.

On commissioning or operability failure after lifecycle exists, the active `commission`
invocation first durably writes its failure receipt before the first cleanup mutation, then unloads
and confirms the probe. If the bound process remains live it journals and sends exactly one
label-bound `SIGINT`; if the process has already terminated naturally it records that branch and
sends no `SIGINT`. Both branches wait at most 120 seconds for the same bound terminal, run one
independent terminal audit, perform one non-signal service `bootout`, verify both
labels/PID/listener absent, and exit. Neither branch makes a final-online probe, sends a second
signal, starts, or retries. A timeout remains a blocker.

If `KICKSTART_INTENT` exists but lifecycle/run identity does not appear within 30,000 ms, the
controller cannot bind a signal or terminal reader. It writes
`STARTUP_FAILED_NO_RUNTIME_TERMINAL`, sends no SIGINT, performs one non-signal bootout of any loaded
service label, and verifies service/probe labels, matching PID, and listener absent. It never
fabricates a service terminal; this independently auditable failure receipt consumes and closes
the attempt without retry.

After online success, the same terminal-goal delegation authorizes at most one separate
start-incapable `stop`/close invocation after either explicit user `停止` or independently
observed natural process termination. It first records durable `STOP_INTENT` and unloads and
confirms the probe. The explicit-stop/live-process branch makes exactly one final-online probe
attempt and sends exactly one label-bound `SIGINT`; the natural-terminal branch makes no
final-online probe and sends no `SIGINT`. Both branches bind the existing runtime and terminal, run
one terminal audit outside the probe denominator, perform one non-signal service `bootout`, and
verify both labels/PID/listener absent. Duplicate `stop`/close is rejected by the same durable
`STOP_INTENT`; neither branch contains start capability or grants a retry.

## Evidence boundary

**Proves:** exact r3 service identity was started once, commissioned before deadline, reachable
only on loopback, projected accepted read-only evidence, passed the frozen 180-second host
operability gate, and entered contiguous read-only observation under a no-retry boundary.

**Does not prove:** 24x7 stability before 86,400,000 ms of clean continuous evidence; complete
market coverage; strategy quality; opportunity frequency; qualification; execution; actual fills,
positions, realized PnL, or any business result rendered as `UNKNOWN`.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** one isolated repo-owned commissioning/stop controller and direct tests; conditional
authority activation/closure; fresh r3 envelope and attempt-specific validation assets; exactly
one service start; deadline-safe commissioning; read-only loopback workbench/probe observation;
explicit clean-stop or terminal-failure audit; and truthful status reporting.

**Out:** changes to the `serve-shadow` hot path, market behavior, service/workbench schemas,
dependencies, locks, contracts, or Policies; reuse or relabelling of r1/r2 artifacts; private or
account APIs; orders, fills, capital, actual positions/PnL; qualification/promotion; restart;
reboot auto-start; retry; alternate root/label/port; market-opportunity waiting as a gate.

**Owning module/artifact:** `apps/radar_runtime/src/radar_runtime/commissioning.py`, its direct
tests, `docs/authority/CURRENT_STAGE.md`, this sole active task, authority tests, and the frozen r3
validation/deployment evidence root.

## Contract

**Inputs and known-at rule:** only immutable merged Git/authority/contract/Policy bytes, accepted
service evidence known at its capture sequence, loopback HTTP responses, launchd/process/listener
facts, and controller monotonic/wall-clock timestamps. Later evidence never repairs an earlier
deadline miss.

**Durable output and identity:** the fresh r3 deployment envelope identity, controller receipt,
contiguous probe rows, service run identity, final-online row when stopping, and terminal audit;
all identities are content-addressed and scoped to r3.

**Missing/invalid/UNKNOWN semantics:** any missing/invalid identity, lifecycle field, required
endpoint, current-reader result, timing bound, sequence, or unique process/listener fact is
`UNKNOWN`/failure, never zero or healthy. A UI `UNKNOWN` is not enough to decide whether the source
evidence is truly unknown; API, lifecycle, reader, and sequential log evidence are checked.

**Persisted meaning and compatibility:** runtime and service schemas remain `COMPATIBLE` and
unchanged; r3 validation receipts are new attempt-scoped evidence and are `NOT_COMPARABLE` to r1/r2
as a continuation.

**Business denominators:** probe success denominator is every append attempt in the r3 probe
ledger; endpoint success is evaluated per attempted endpoint; commissioning deadline denominator
is the sole r3 start; 24-hour duration is the covered interval of one continuously valid service
run. While the run is live its 24-hour result is `PENDING`; a clean audited terminal with at least
86,400,000 ms and every pre-bound predicate passing is `MET`; an earlier or failed terminal is
`NOT_MET`. Natural market objects are reported by canonical object identity and never by repeated
UI/probe observations.

## Acceptance

### Direct behavior

1. Given the frozen fresh envelope and loaded-but-not-started r3 service, one `commission`
   invocation issues one kickstart, observes lifecycle sequence 1 within 30,000 ms, commissions the
   exact process and loopback projection within 60,000 ms of lifecycle, records successful manual
   probe sequence 1 within 90,000 ms, and loads the periodic probe only after one current audit
   passes and before 110,000 ms; the hard first-probe deadline remains 120,000 ms.
2. Missing/invalid/stale/late identity, evidence, endpoint, process, listener, or sequence fails
   closed, writes a failure receipt before cleanup, performs the one-stop path after start, and
   cannot retry.
3. Duplicate `commission`, duplicate `stop`, second kickstart, old-root reuse, alternate
   label/root/port, reboot auto-start, and second stop signal are forbidden and independently
   detectable; `stop` mode contains no start capability.
4. For a full 180,000 ms after `HOST_OPERABILITY_GATE_START`, the same PID remains at launchd
   `runs=1`, at least two post-manual successful periodic rows make every start/adjacent/end gap at
   most 90,000 ms, required endpoint/probe attempts stay operational, CPU-time/RSS/latency units
   are recorded, and no new exact-PID host `cpu_resource` event appears; failure consumes and stops
   the attempt once.
5. Kickstart-command failure or lifecycle absence at +30,000 ms records
   `STARTUP_FAILED_NO_RUNTIME_TERMINAL`, sends no unbound SIGINT, bootouts the loaded label once,
   proves both labels/PID/listener absent, fabricates no terminal, and cannot retry.
6. Every lifecycle-bound failure, explicit stop, and natural-terminal close runs the terminal audit
   before one non-signal service bootout and final absence proof; natural-terminal closure sends no
   final-online probe or `SIGINT`, and no loaded LaunchOnlyOnce label remains.

### Required commands

- `make sync`
- focused tests: `tests/test_persistent_service_commissioning.py` plus authority activation tests
- `make check`
- production-public command: one `commission` invocation of the frozen r3 controller with the
  independently supplied `--expected-envelope-identity`, whose sole embedded live start is
  `launchctl kickstart gui/501/com.optimatrix.public-shadow.r3`; after a later explicit user stop or
  independently observed natural process termination, at most one start-incapable `stop`/close
  invocation
- independent recomputation: fresh audit that ignores controller verdict and recomputes envelope,
  process, listener, lifecycle, current-reader, HTTP schema, probe sequence, and deadline facts

### Real evidence

**Required:** YES

**Environment and stopping condition:** production-public Deribit source; continue after successful
commissioning until explicit user `停止` or terminal process failure. No duration, opportunity,
`UNKNOWN`, or zero result authorizes extension or retry.

**Required report:** exact Git/tree/contract/Policy/runtime/artifact identities; host labels/PID/
argv/cwd/listener; commissioning and first-probe timing; current-reader/HTTP/probe/audit status;
business object counts and `UNKNOWN`s; 24-hour covered duration; limitations and non-claims.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** recorded in the frozen r3 deployment envelope and final delivery
report; no r1/r2 state, ledger, log, receipt, plist, or evidence artifact is copied, relabelled,
extended, or treated as r3 evidence.

**Policy/contract identities:** exact accepted service contract and the three unchanged active
Policy identities are recomputed from the merged fresh checkout and bound before start.

**Commit/PR:** recorded by Git and the final delivery report; the activation commit does not
contain its own future hash.

**Unknowns and non-claims:** commissioning success is not 24x7 acceptance. While the service is
live, 24x7 is `PENDING`; it becomes `MET` only on a clean audited terminal after at least
86,400,000 ms with every predicate passing, otherwise terminal truth is `NOT_MET`. Natural zero
opportunities and truthful `UNKNOWN` make no quality, frequency, or PnL claim.

## Definition of done

The repo-owned controller is independently accepted at one exact merged remote-main identity; the
activation authority, frozen r3 validation boundary, one start, deadline-safe successful
commissioning, first probe, current independent audit, and continuing read-only observation all
exist and pass. The task remains active while the service is observing. It closes only after an
explicit user stop or terminal failure is sealed and independently audited, with Authority updated
to the exact truthful terminal state. No green test, Draft PR, elapsed time, UI rendering, or
controller self-verdict independently grants acceptance.
