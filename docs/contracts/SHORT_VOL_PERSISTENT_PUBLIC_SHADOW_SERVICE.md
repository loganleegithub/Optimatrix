# Persistent Public Shadow Service and Trader Workbench Contract

**Status:** ACTIVE IMPLEMENTATION/EVIDENCE CONTRACT

**Owning semantic identity:** `SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`

**Current implementation state:** `PUBLICATION_COALESCING_IMPLEMENTATION_AUTHORIZED`

## Purpose and authority boundary

This contract owns one offline-implementable, public-only, long-running process capability and its
read-only trader projection. It does not authorize invocation, persistent deployment, a 24x7
acceptance run, private/account access, orders, fills, capital, qualification, promotion, or
execution. Permission remains governed by
[`CURRENT_STAGE`](../authority/CURRENT_STAGE.md), and live/deployment commands remain forbidden
until a later explicit task changes that authority.

The service reuses the exact accepted Radar reducer, fixed-contract Underwriting/Position owner,
Shadow Outcome owner, and three immutable Policies. It adds no second market client, reducer,
decision engine, Policy, model, database, replay calculator, full-book archive, or browser-side
strategy logic.

The existing bounded
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md) contract
remains unchanged for `observe-shadow`. Its manifest, enrollment cutoff, final-stop trigger,
terminal summaries, complete reader, and cohort claims are never reused or impersonated by this
service.

## Service contract identity

```text
PersistentServiceContractContentDigest =
    "sha256:" + lowercase_sha256_of_exact_accepted_contract_bytes

PersistentServiceContractIdentity =
    CanonicalIdentity(
        "PERSISTENT_SERVICE_CONTRACT",
        "SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE",
        PersistentServiceContractContentDigest,
        exact_code_identity,
        runtime_identity,
        Radar_Policy_identity,
        Underwriting_Policy_identity,
        Position_Policy_identity
    )
```

The exact typed `CanonicalIdentity` and `CanonicalValue` encoding is the one frozen by the Outcome
contract. Binary floating point, implicit serialization, platform-dependent map order, and
non-canonical identity aliases are forbidden.

A changed contract receives a new content digest and applies only to a newly started runtime.
Neither the process nor the browser may hot-reload or relabel a contract or Policy.

## One process, one runtime, one owner graph

One configured external `state_root` is one deployment boundary. Before any market client is
constructed, the process holds a non-blocking exclusive advisory lease at:

```text
<state_root>/service.lock
```

A second process using the same root fails closed. Releasing the first process permits a later
startup, but every startup creates a new canonical runtime identity and a new run directory:

```text
<state_root>/runs/<runtime_digest>/
    radar/
    downstream/
    service/
        events/
        terminal.json
```

`state_root`, `service.lock`, and `runs/` must be real filesystem entries rather than symbolic
links. The lock must be one regular file. A redirected or non-regular path fails before truncation,
run-directory creation, or client construction, so declared evidence ownership cannot escape the
configured root.

A reconnect increments the transport session epoch inside the same runtime. It does not create a
second owner, reuse retired continuity, or create a second business object for unchanged settled
facts. A process restart creates a new runtime identity and cannot continue old Candidate,
Position, or Outcome state.

The exact Radar, Underwriting, and Position Policy bytes are read and validated once before runtime
construction. The one frozen `PolicyChain` object is shared by the reducer and downstream owner.
There is no watcher, reload endpoint, mutable Policy reference, automatic threshold adjustment,
no-opportunity extension, or supervisor calibration surface.

## Lifecycle and currentness

Service phase and data state are independent exact enums:

```text
service_phase =
    STARTING | CONNECTING | RUNNING | RECONNECTING | STOPPING | STOPPED | FAILED

data_state =
    CURRENT | DEGRADED | STALE | UNKNOWN | INTERRUPTED | STOPPED
```

`health = true` means the process and read-only HTTP surface are responsive. `ready = true` requires
`service_phase = RUNNING`, an established current session, and `data_state = CURRENT`. A connected
socket never proves readiness. `STALE`, `DEGRADED`, `UNKNOWN`, and `INTERRUPTED` remain distinct.
None is rendered as calm, zero, no anomaly, or no opportunity.

The existing runtime remains the sole authority for heartbeat/test-request handling, liveness,
subscription acknowledgement, reconnection, resubscription, ingress continuity, order-book
continuity, clock/index/ticker currentness, queue lag, catalog reconciliation, and affected-scope
`UNKNOWN`.

## Atomic read-only workbench projection

The workbench snapshot is an immutable version-2 operational projection, not a new trading
Decision or durable business object. After each runtime fact transaction completes both Radar
settlement and the fixed-contract Shadow owner transition, `radar_runtime.runtime` invokes exactly
one configured snapshot publisher. The publisher always derives settled status and retains only
the latest settled reducer/commit reference. It constructs a complete JSON body and atomically
replaces one immutable byte reference when publication is due.

Version 2 adds only settled display metadata: human-readable short/long option names, combo name,
expiry, option type, strikes, and target quantity keyed by the exact existing Underwriting scope.
The adapter copies that metadata from the same settled `UnderwritingFacts` already consumed by the
owner. It does not change or duplicate an economic input, persisted payload, object identity,
Policy output, or business enum. Missing joins remain JSON `null`; the publisher and browser never
guess a structure from a hash.

The publisher may cache downstream-derived grouping, Underwriting rows, Shadow rows, Outcome rows,
and counts only under an exact monotonic downstream-writer revision. A successful durable object-set
change advances that revision; an identical no-op, rejected write, or failed write does not. Radar,
system status, published fact boundary, and time-sensitive Position projection are recomputed from
the latest settled state at every complete publication. A revision change invalidates the cache
before that publication.

A semantic status-key change publishes one complete immutable snapshot immediately. During a busy
status-stable interval, ordinary facts publish at most once per 500 monotonic milliseconds; facts
inside that interval replace only the pending in-memory latest-state reference. The first settled
fact at or after the interval publishes the latest complete state and latest settled fact boundary.
No timer or sleeping task is created: without a new fact there is no new business state to publish.

An explicit lifecycle status update publishes immediately and includes any pending latest business
state. After accepted events and barrier deadlines are drained, the runtime invokes
`flush_pending()` exactly once before `prepare_reconnect` or `clean_stop` mutates terminal state.
The flush is a no-op when no publication is pending.

Publication bookkeeping advances only after the snapshot store accepts the complete encoded body.
A serialization or store-publication failure preserves the prior immutable snapshot and leaves the
latest settled state pending for the owning failure path. There is no partial JSON patch, timer,
thread, queue, scheduler, new HTTP endpoint, or durable publication object.

HTTP handlers read only that immutable reference. They may not call detector freeze methods,
Policy/classification functions, market adapters, writers, or owner methods; they may not traverse
mutable reducer or owner containers.

The browser performs display formatting only. It never computes IV, baseline, richness,
Underwriting action, Candidate validity, entry or close economics, PnL, hard-close state, or Outcome
maturity. It opens no Deribit connection.

The version-2 browser accepts only the exact supported projection version and fails closed on a
missing, mixed, or unsupported version. It preserves the owning business enum and distinguishes:

- `UNKNOWN`: a required fact is not currently knowable;
- `NOT_EVALUATED`: the declared prerequisite has not activated that layer;
- `N/A`: a display field is semantically inapplicable, while the JSON value remains `null`;
- empty panel: no matching settled object exists; and
- proven numeric zero: only the independently conditioned nonzero denominator permits it.

Known-ineligible Radar early exits render unavailable formula fields as `N/A`, while a true unknown
detector evaluation renders its unavailable required calculations as `UNKNOWN`. Inactive episode
fields and unavailable Underwriting action/economics are `N/A`, not additional unknown facts.
Actual PnL under public Shadow is `N/A` with the explicit no-order/no-fill/no-position meaning. Raw
identities, exact decimals, enum reasons, and monotonic boundaries remain inspectable in read-only
details but do not dominate the trader summary.

The first view states service/data usability, known-versus-monitored coverage, the owning blocker,
and the separately conditioned Radar/Candidate zero claims. Radar and Underwriting rows use stable
actionability-first ordering and optional local-only filters. A filter transforms only the fetched
immutable array, sends no request, and is not a Policy or execution control. Tables own their
horizontal scrolling; the page itself must not overflow a 1,214-pixel viewport.

Any fetch, non-success HTTP, JSON decode, or render failure fails the entire trader page closed. A
global alert marks the workbench `UNKNOWN`, every cached Radar/Underwriting/Shadow/Position/Outcome
table is hidden, and the page shows the last successful fetch age plus the last publication
sequence and its unchanged age. A successful later fetch may replace that unavailable view with one
complete current snapshot; stale cached business rows are never left looking current. Publication
freshness is keyed by `(runtime_identity, publication_sequence)`, so a restarted runtime resets the
age even when its process-local sequence equals the prior runtime's sequence. Fetch-success and
publication bookkeeping commit only after the complete snapshot renders; a render failure preserves
the prior successful values shown by the unavailable view.

The HTTP server binds only to an explicit loopback address. It accepts only `GET` and `HEAD` for:

```text
/
/app.js
/styles.css
/api/workbench/current
/healthz
/readyz
```

All other methods return `405 Method Not Allowed`; unknown paths return `404`. There is no write
route, form, Policy control, private-account endpoint, order button, credential input, or browser
WebSocket.

## Empty panels and proven business zero

An empty panel means only that no matching settled object is present in the current immutable
projection. It is not a numeric zero claim.

A numeric zero-anomaly claim is permitted only when the current monitor denominator is known and
complete for a non-empty relevant scope. Otherwise `zero_anomaly_state = UNKNOWN` and the displayed
value is `null`.

A numeric zero-Candidate claim additionally requires a strictly positive
`underwriting_evaluable_denominator`. Otherwise `zero_candidate_state = UNKNOWN` and the displayed
value is `null`. Zero or unknown denominators never serialize or render as `0`, calm, or no
opportunity.

The version-2 snapshot therefore carries both panel emptiness and independently conditioned zero
claims:

```text
panel_state = HAS_SETTLED_OBJECTS | EMPTY_NO_SETTLED_OBJECT
zero_anomaly_state = PROVEN_ZERO | NOT_ZERO | UNKNOWN
zero_candidate_state = PROVEN_ZERO | NOT_ZERO | UNKNOWN
```

Rates whose denominator is zero or unknown are JSON `null`.

## Persistent service evidence objects

Service evidence is separate from Radar evidence and existing downstream business objects. It
contains only exact lifecycle and terminal records; it never stores full order books or browser
requests.

### Lifecycle event

Every persisted lifecycle transition has exact top-level keys:

```text
object_kind
content_schema_identity
object_identity
persistent_service_contract_identity
code_identity
runtime_identity
radar_policy_identity
underwriting_policy_identity
position_policy_identity
event_sequence
service_phase
data_state
health
ready
stale
reason
recorded_monotonic_ms
non_claims
```

```text
PersistentServiceLifecycleEventIdentity =
    CanonicalIdentity(
        "PersistentServiceLifecycleEventIdentity",
        PersistentServiceContractIdentity,
        event_sequence,
        service_phase,
        data_state,
        health,
        ready,
        stale,
        reason,
        recorded_monotonic_ms
    )
```

`event_sequence` starts at 1 and is contiguous. Files are append-only and exclusively published as
`events/<zero_padded_sequence>-<object_digest>.json`. A duplicate path with different bytes is an
integrity failure.

### Terminal record

Exactly one terminal record may exist. Its exact top-level keys are the same identity bindings plus:

```text
terminal_disposition
terminal_source_identity
terminal_fact_boundary
radar_evidence_status
downstream_evidence_status
service_evidence_status
radar_summary_relative_path
radar_object_count
radar_inventory_identity
downstream_object_count
downstream_inventory_identity
underwriting_counts
underwriting_rates
underwriting_conservation_status
cohort_counts
cohort_rates
cohort_conservation_status
cohort_enrollment_mode
forward_cohort_summary_emitted
lifecycle_event_count
lifecycle_inventory_identity
non_claims
```

`terminal_disposition` is `CLEAN_STOP | PROCESS_FAILURE`. `cohort_enrollment_mode` is exactly
`DISABLED_NON_COHORT_SERVICE`; every service-created admitted or rejected pair remains
`cohort_enrolled = false`. `forward_cohort_summary_emitted` is exactly `false`.

```text
PersistentServiceTerminalSourceIdentity =
    CanonicalIdentity(
        "PersistentServiceTerminalSourceIdentity",
        PersistentServiceContractIdentity,
        terminal_disposition,
        terminal_fact_boundary
    )
```

The terminal source is recomputed by the writer and complete reader. The final lifecycle event must
use the corresponding `STOPPED | FAILED` phase, `data_state = STOPPED`, the same disposition as its
reason, and exactly the terminal boundary monotonic time.

```text
PersistentServiceTerminalIdentity =
    CanonicalIdentity(
        "PersistentServiceTerminalIdentity",
        PersistentServiceContractIdentity,
        terminal_disposition,
        terminal_source_identity,
        terminal_fact_boundary,
        radar_evidence_status,
        downstream_evidence_status,
        service_evidence_status,
        radar_object_count,
        radar_inventory_identity,
        downstream_inventory_identity,
        underwriting_counts,
        underwriting_rates,
        underwriting_conservation_status,
        cohort_counts,
        cohort_rates,
        cohort_conservation_status,
        lifecycle_event_count,
        lifecycle_inventory_identity
    )
```

`radar_inventory_identity` binds the bytewise SHA-256 of every Radar filename in sorted order,
including valid partial anomaly/atomic evidence on process failure. `lifecycle_inventory_identity`
binds the bytewise SHA-256 of every contiguous lifecycle filename in sorted sequence order.
Changing, replacing, omitting, or adding a file changes the terminal identity or makes terminal
recomputation fail.

The terminal file is exclusively published at `terminal.json`. Repeating finalization with the
identical terminal identity is a no-op; a different terminal attempt is rejected.

## Terminal and conservation semantics

A clean stop latches one exact monotonic boundary, opens the existing runtime barrier, drains every
accepted envelope before that boundary, prevents new outbound work, terminalizes all valid
Candidates and pending observations exactly once, writes one Radar run summary, and then writes the
service terminal record.

If stop is already latched before the first market client is constructed, the service seals the
reducer's initial Radar coverage epoch directly. It does not fabricate a transport session,
reconnect, continuity restart, elapsed coverage, or business fact. Existing Radar run-summary
validation semantics remain unchanged.

A real transport generation may still retire at the exact monotonic instant at which its coverage
ledger starts, before any positive-duration segment exists. Only the service-specific Radar summary
writer/reader path may then accept a successor first represented continuity epoch. It requires an
exact contiguous restart chain from epoch 1, every omitted restart boundary equal to the first
segment start, and the first segment's trigger, blocker, blocking group, and affected scopes equal
to the last omitted restart. A recovery, if present, must remain an exact later diagnostics edge and
the matching blocker segment may not extend beyond it. The standard Radar summary and directory
readers remain strict and reject a first represented epoch other than 1.

A process failure terminalizes downstream state as `CENSORED_AT_FAILURE` where applicable and
writes one service terminal when terminalization succeeds. Radar evidence is then explicitly
`INCOMPLETE_PROCESS_FAILURE`; no Radar run summary is invented. A failure before terminalization or
an evidence write failure leaves no valid complete terminal and the complete reader fails closed.

Before a service terminal is accepted, the writer and reader independently require:

1. exact service contract, code, runtime, and three-Policy identities;
2. contiguous validated lifecycle events and exactly one immutable terminal;
3. strict current downstream object validation and complete attempt relationships;
4. no pending Candidate admission attempt or pending admitted/rejected observation;
5. `underwriting_conservation_status = MET`;
6. `cohort_conservation_status = MET` over all logical non-enrolled units;
7. no `UNDERWRITING_POSITION_SUMMARY` and no
   `SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY` in the persistent downstream directory;
8. recomputed ordered Radar, downstream, and lifecycle inventories, counts, rates, null
   denominators, and terminal identity;
9. a valid Radar run summary only for `CLEAN_STOP`, and its explicit absence for
   `PROCESS_FAILURE`;
10. every Radar anomaly/atomic file individually validates under the current Radar schema, matches
    the exact code/runtime/Policy identities, and falls no later than the service terminal causal
    boundary; object uniqueness and anomaly/atomic cross-bindings also validate when process failure
    leaves Radar incomplete, and no unknown file kind is accepted.

The existing bounded `read_complete_evidence` remains manifest/cohort-specific and is not a reader
for this service. The new `read_complete_persistent_service_evidence` is the only complete reader
for this run-segment format. The two formats are `NOT_COMPARABLE`; neither migrates or completes the
other.

## Append-only and persistence boundary

Durable service output is limited to:

- existing minimal Radar anomaly/atomic/run-summary objects;
- existing downstream Underwriting, Candidate, simulated Entry, Position, close-opportunity,
  Outcome, rejected-counterfactual, and aligned-pair objects;
- minimal lifecycle events and one service terminal.

Full option/combo books, ordinary no-anomaly updates, browser state, HTTP requests, credentials,
private/account facts, orders, fills, and actual exposure are not persisted.

`UNDERWRITING_AVAILABILITY_EVALUATION` is graph-independent in the accepted downstream attempt
relationship validator. Its write still runs complete per-object schema, identity, binding,
boundary, provenance, and semantic validation before exclusive publication, but it need not scan
the whole attempt graph whose rules do not consume that kind. Every other downstream object kind
retains the existing prospective whole-graph validation. This is an implementation optimization,
not a persisted compatibility or evidence-strength change.

## Direct verification and non-claims

Every lifecycle event, service terminal, and workbench snapshot carries
`THIS_ARTIFACT_DOES_NOT_GRANT_LIVE_OR_DEPLOYMENT_AUTHORITY`. This means the artifact cannot grant or
widen permission; it does not assert that `CURRENT_STAGE` forbids an otherwise explicitly
authorized invocation. Stage authority remains external to evidence and projection bytes.

Direct deterministic tests must cover lease exclusivity/release, new runtime identity per start,
Policy-chain immutability, reconnect/session continuity, health/readiness/currentness separation,
first-stop-boundary latching, pre-latched no-client stop, exactly-once downstream and service
terminalization, writer/reader identity recomputation, corruption/missing/mixed/incomplete failure,
partial-Radar corruption failure, atomic snapshot publication after Shadow settlement,
500-millisecond ordinary-publication coalescing, immediate semantic-status/lifecycle bypass,
latest-state terminal-boundary flush, publication failure atomicity, revision-keyed downstream
projection cache invalidation, graph-independent availability validation,
settled structure display joins, loopback-only read-only HTTP, escaped and executable fail-closed
browser rendering across fetch, HTTP, JSON, schema, render-failure, recovery, and same-sequence
new-runtime cases, trader-state formatting/sorting/local-filter behavior, artifact-versus-stage
authority wording, truthful empty/zero/null UI fixtures, and document-level overflow at the declared
viewport.

This offline implementation proves none of indefinite uptime, production deployment safety,
natural opportunity frequency, Policy quality, forecast skill, fillability, actual fees, actual
PnL, private-account truth, profitability, qualification, promotion, or execution permission.
