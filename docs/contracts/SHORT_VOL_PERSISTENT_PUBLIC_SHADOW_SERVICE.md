# Persistent Public Shadow Runtime and Workbench Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`

## Purpose

Run one public Deribit → `INVERSE_BTC_SHORT_VOL_V2` Radar → Underwriting → process-independent
Shadow Entry/Control → Position → Outcome path for the fixed `INVERSE_BTC_V1` product in one
long-lived process and expose current settled state through a loopback read-only Workbench. There
is no product selector, fallback, or runtime product switch.

The service adds no account, order, fill, capital, replay, database, qualification, or deployment
authority. Live invocation comes only from `CURRENT_STAGE`.

## Process shape

One process owns:

- the canonical `INVERSE_BTC_V1` product specification and matching three-Policy chain;
- one Inverse BTC public Deribit client and bounded application queue;
- one synchronous Radar reducer;
- one in-memory Underwriting/Admission/Position owner;
- one stable minimal Shadow Case repository and every compatible active admitted Entry it restores;
- one coalesced immutable Workbench snapshot store;
- one loopback GET/HEAD HTTP server.

Startup rejects an unsupported product, product/Policy mismatch, or foreign-product leg. There is
no second queue, reducer, owner, Case store, Workbench, or product-comparison funnel inside the
process.

Recoverable transport failure starts a new session epoch without replacing the in-process owners.
A process restart creates a fresh runtime identity and reuses the stable Case repository. After
acquiring its lease, it restores every compatible non-terminal admitted Entry and opens a new
Observation Segment. Runtime identity is segment provenance, not Entry ownership.

The long-lived process retains only current option/Combo sources, frozen protective-leg bindings,
active Underwriting scopes, active Candidates and their bounded paired requests, restored/open
admitted Entries,
and one latest terminal Case for trader display. Terminal identities are evicted at their owning
boundary. Durable Case files remain the source for historical research; neither the owner nor
Workbench keeps a second in-memory event history.

Every retained source, current-state identity, funnel denominator, and Case belongs to
`INVERSE_BTC_V1`. Product comparison is not part of the Online Runtime.

Deribit session liveness is transport work, not business reduction. On a server `test_request`, the
public client sends the required `public/test` immediately before the notification can wait behind
the application queue. One transport-local request id binds and validates the matching version
response; the reducer cannot schedule a duplicate heartbeat-test RPC. Ordinary heartbeat
notifications remain non-causal and cannot change Radar, Underwriting, Candidate, or Case truth.

## State root

One external absolute, non-temporary state root is the stable business repository across process
starts. Startup rejects a root under the platform temporary directory, `/tmp`, or `/private/tmp`
before creating it:

```text
service.lock
cases/<case-id>/opened.json
cases/<case-id>/segments/<segment-sequence>/opened.json
cases/<case-id>/segments/<segment-sequence>/closed.json     # optional
cases/<case-id>/first-close.json                      # optional
cases/<case-id>/outcome.json                          # optional
```

There is no `radar/` or `downstream/` evidence directory. The lock prevents two processes from
writing the same local repository concurrently. Startup rejects any active Entry whose product or
frozen Policies differ from the selected runtime. The lock is not distributed fencing,
commissioning, or host-identity proof.

## Runtime lifecycle

`serve-shadow` performs only:

1. resolve one product specification, clean code identity, and exact matching three-Policy chain;
2. reject any temporary state root, acquire the stable state-root lease, and validate every Case in
   `state-root/cases`;
3. restore all compatible non-terminal admitted Entries and no Controls;
4. start loopback Workbench and connect/reconnect one public Deribit session;
5. on the first settled boundary, open one new `GAPPED` Observation Segment per restored Entry;
6. settle each accepted fact through Radar and the current owner, beginning restored current state
   at `UNKNOWN` until required fresh facts arrive;
7. publish each new admission only as one complete initial Case directory containing
   `opened.json + segments/0/opened.json`; publish later Segment records, the combined
   first-close/attempt transition, and mature Outcomes individually;
8. on SIGINT/SIGTERM or handled failure, close active Segments without terminating admitted Entry
   Outcomes.

Process supervision, restart policy, CPU, memory, host logs, and uptime monitoring are external.
The application does not inspect or control them.

Live invocation is governed only by `CURRENT_STAGE`. Reusing the stable Case repository is required
business recovery, not authority for automatic process restart: an external operator still decides
when to launch a process. Exactly one Inverse runtime may hold the repository lease.

## Current state and Workbench

Workbench service phase is:

```text
STARTING | CONNECTING | RUNNING | RECONNECTING | STOPPING | STOPPED | FAILED
```

Data state is:

```text
CURRENT | DEGRADED | STALE | UNKNOWN | INTERRUPTED | STOPPED
```

`health=true` means the process/HTTP surface responds. `ready=true` requires RUNNING and current
market truth. Connection alone is insufficient.

After a fact settles all business owners, the publisher retains the latest current references and
publishes one complete immutable schema snapshot:

- immediately on readiness/currentness/lifecycle change;
- at most once per 500 monotonic milliseconds for ordinary status-stable updates;
- once for pending state before reconnect or stop.

The schema-v7 snapshot identifies `INVERSE_BTC_SHORT_VOL_V2`, `INVERSE_BTC_V1`, their exact
product/Policy identities, V2 score/leader/coverage state, public/index/native
premium/settlement/strike/valuation units, and Policy chain. Every monetary value is labeled with
its server-owned native or valuation unit. Browser code may not infer a unit from an internal key
suffix or convert between native, model, and valuation values.

The Workbench keeps three latency meanings separate. `latest_market_event_age_ms` is trusted
exchange time minus the newest accepted index, ticker, or book source timestamp; it may grow when
an aggregated market channel emits no changed event. `last_wire_message_age_ms` is local monotonic
time since any public wire message. `last_queue_processing_lag_ms` is the most recently processed
envelope's local receive-to-reducer delay. Only the third value is compared with the fixed Policy
`queue_lag_deadline_ms` and may activate `QUEUE_LAG_CURRENTNESS`. A source-event age above that
queue deadline is not, by itself, a slow reducer, stale ticker, or reconnect condition.

`QUEUE_LAG_CURRENTNESS` makes current Radar truth and leader coverage `UNKNOWN` and blocks new
observations and admission until the ordered queue catches up. It does not by itself erase an
inactive bucket's earlier accepted confirmation observations. Recovery must recompute the current
leader and score band before that count can continue; changed truth still resets normally, and an
already-active Episode remains fail-closed.

Every active admitted Entry appears once by its original `shadow_entry_identity`, whether opened in
this runtime or restored. The snapshot distinguishes origin runtime from current Segment runtime
and exposes Segment state, `CONTINUOUS | GAPPED`, gap count, current-data availability, durable
first-CLOSE/attempt status, Outcome quality, and qualification eligibility. A restored row is
`UNKNOWN` until fresh facts settle; the browser cannot turn `HANDOFF_GAP` into `HOLD` or `CLOSE`.
Runtime health/readiness remains a separate service signal.

There is no publication timer, event stream, durable Workbench file, SSE, partial patch, or browser
strategy engine. HTTP readers see old or new complete bytes only.

## Funnel diagnostics

The service exposes non-durable funnel counts and a primary blocker in the Workbench. They are
computed from current reducer/owner transitions and reset with the runtime. They do not create Case
files or qualify a Policy.

Restoring an Entry increments no Candidate, admission, or `SHADOW_CASE_OPENED` counter. The Entry's
mature `SHADOW_CASE_OUTCOME` is counted once when it first becomes durable, while
`qualification_eligible` remains false for every gapped chain.

For each evaluable Underwriting row, Workbench projects the owner-generated selected protective leg,
complete signed six-predicate margin vector, and all failed predicates. Admission and close rows
project exact pair-timing failures, measured values, and frozen limits. Because a failed Candidate
is retired in the same owner transaction, the publisher keeps at most one non-durable admission
terminal per still-active Radar Episode; it is pruned when the Episode scope retires or replaced by
a new Candidate. Close timing truth is copied into the existing attempt-owned `UNKNOWN` opportunity.
The server derives exact `count/min/p50/max` only over bounded current Underwriting rows, never
retained Episode history. Browser code does not select a leg, recalculate a threshold, or turn a
pair-timing `UNKNOWN` into known economics.

Completed funnel identities are retired. Apart from the per-active-Episode terminal above, only
cumulative scalar counts and bounded normalized reason categories survive, so diagnostic memory is
bounded by current market scope rather than completed opportunity count.
The Workbench additionally renders runtime-local fixed counts for lost nonzero pre-activation Radar
confirmation and `KNOWN_NO_CONTROL`. Review-only TTE/Delta rows expose their score as review context
and never display a confirmation counter. Both projections are server-owned diagnostics, reset on
restart, and cannot be reconstructed from old snapshots or Case files.

## HTTP surface

Only explicit loopback addresses are permitted. GET/HEAD routes are:

```text
/
/app.js
/styles.css
/api/workbench/current
/healthz
/readyz
```

Other methods are rejected and unknown paths return 404. Browser fetch/schema/render failure hides
stale business tables and displays UNKNOWN until a complete later snapshot succeeds.

## Stop and failure

Before reconnect or clean stop, intake stops, every accepted fact remaining in the sole bounded
queue is settled, and pending Workbench state is flushed. A completed business summary is returned
independently of a bounded best-effort transport close; a WebSocket closing handshake cannot consume
the outer acceptance window. When the failure/stop boundary is available, the owner closes admitted
Entry Segments and terminalizes non-recoverable Controls. An uncatchable process loss may leave a
Segment without `closed.json`; the Case reader reports that Segment as
`INCOMPLETE_UNCLEAN_EXIT`.

For admitted Entries, clean stop and handled failure write only
`SHADOW_CASE_SEGMENT_CLOSED` with `CENSORED_AT_STOP | CENSORED_AT_FAILURE`; they do not write a
mature Entry Outcome. An uncatchable loss leaves Segment close absent. The next externally started
runtime restores all three states as gapped observation, starts current facts at `UNKNOWN`, and
does not retry a previously scheduled close attempt. Selected no-trade Controls retain their
existing bounded censoring behavior and are not restored.

No terminal manifest, inventory, service receipt, host audit, or automatic restart belongs to this
contract.

## Direct verification

Offline tests cover exactly one fixed Inverse owner graph, product/Policy compatibility and
foreign-product rejection, fixed Policies, reconnect without owner replacement, pre-Shadow file
count zero, paired component admission/close, exact Inverse schema-v5 reader states and V2 score
packets,
Workbench product/unit projection, coalescing/status bypass/flush, loopback HTTP, truthful
zero/UNKNOWN, transport-immediate heartbeat response and response filtering, and Inverse
application-method allowlisting. Repeated Episode, Candidate,
scope-replacement, and completed-Case tests must prove that retained collections return to the
active-set bound. Public observation requires explicit `CURRENT_STAGE` authority. A bounded gate
may establish current-state reachability and negative product contamination only; a later natural
Outcome remains a separate product result.

Recovery tests run at least runtime A → B → C over one repository and prove stable Entry identity,
all-active scanning, Control/terminal exclusion, recovery-first UNKNOWN, segment-chain ordering,
gap quality without synthetic CLOSE, one combined first-close/attempt schedule, no retry after
uncertain loss, one mature gapped Outcome with qualification false, no duplicate funnel admission,
and immutable records. The schema-v5 runtime has no V1 migration or compatibility command. Every
live invocation and stable-root choice remains governed by `CURRENT_STAGE`.
