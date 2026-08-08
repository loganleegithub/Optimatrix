# Persistent Public Shadow Runtime and Workbench Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`

## Purpose

Run one public Deribit → Radar → Underwriting → Shadow Case → Position → Outcome path for exactly
one startup-selected product profile in one long-lived process and expose current settled state
through a loopback read-only Workbench. The profile is `LINEAR_BTC_USDC_V1` or `INVERSE_BTC_V1` and
is immutable for the process.

The service adds no account, order, fill, capital, replay, database, qualification, or deployment
authority. Live invocation comes only from `CURRENT_STAGE`.

## Process shape

One process owns:

- one canonical product specification and one matching three-Policy chain;
- one selected-product public Deribit client and bounded application queue;
- one synchronous Radar reducer;
- one in-memory Underwriting/Admission/Position owner;
- one minimal Shadow Case store;
- one coalesced immutable Workbench snapshot store;
- one loopback GET/HEAD HTTP server.

Startup rejects an unsupported product, product/Policy mismatch, cross-product leg, or attempt to
compose both products. There is no second queue, reducer, owner, Case store, Workbench, or
cross-product funnel inside the process.

Recoverable transport failure starts a new session epoch without replacing the in-process owners.
A process restart creates a fresh runtime and does not resume prior open Cases.

The long-lived process retains only current option/Combo sources, frozen protective-leg bindings,
active Underwriting scopes, active Candidates and their bounded paired requests, open Shadow Cases,
and one latest terminal Case for trader display. Terminal identities are evicted at their owning
boundary. Durable Case files remain the source for historical research; neither the owner nor
Workbench keeps a second in-memory event history.

Every retained source, current-state identity, funnel denominator, and Case belongs to the one
selected product. Product comparison and aggregation are offline derived work, never a live
in-process projection.

## State root

One external absolute state root contains:

```text
service.lock
runs/<runtime-id>/cases/<case-id>/...
```

There is no `radar/` or `downstream/` evidence directory. The lock prevents two processes from
owning the same state root. A runtime cannot reuse another product's run directory or resume its
Case. The lock is not a commissioning or host-identity proof.

## Runtime lifecycle

`serve-shadow` performs only:

1. resolve one product specification, clean code identity, and exact matching three-Policy chain;
2. acquire the state-root lease and create a fresh runtime/cases directory;
3. start loopback Workbench;
4. connect/reconnect one public Deribit session;
5. settle each accepted fact through Radar and the current owner;
6. publish admitted Shadow Case records and their bounded future results;
7. stop on the first SIGINT/SIGTERM or fatal process failure.

Process supervision, restart policy, CPU, memory, host logs, and uptime monitoring are external.
The application does not inspect or control them.

Live invocation is governed only by `CURRENT_STAGE`. The current `VALIDATION_ONLY` task names one
exact Inverse code/product/Policy/state-root topology and one process start. Its first 600 seconds
are the same process's read-only currentness/isolation gate; a pass permits that process to continue
but never permits a restart or second product process.

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

The snapshot identifies the one selected product, exact product-spec identity, public/index/native
premium/settlement/strike/valuation units, and Policy chain. Every monetary value is labeled with
its server-owned native or valuation unit. Browser code may not infer a unit from a legacy key
suffix or convert between native, model, and valuation values.

There is no publication timer, event stream, durable Workbench file, SSE, partial patch, or browser
strategy engine. HTTP readers see old or new complete bytes only.

## Funnel diagnostics

The service exposes non-durable funnel counts and a primary blocker in the Workbench. They are
computed from current reducer/owner transitions and reset with the runtime. They do not create Case
files or qualify a Policy.

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
the outer acceptance window. The owner terminalizes pending Cases as censored when the failure/stop
boundary is available. An uncatchable process loss may leave only `opened.json`; the Case reader
reports it as `INCOMPLETE_UNCLEAN_EXIT`.

No terminal manifest, inventory, service receipt, host audit, or automatic restart belongs to this
contract.

## Direct verification

Offline tests cover exactly one selected-product owner graph, product/Policy compatibility and
mixing rejection, fixed Policies, reconnect without owner replacement, pre-Shadow file count zero,
paired component admission/close, exact Linear v3 and product-aware Inverse v4 reader states,
Workbench product/unit projection, coalescing/status bypass/flush, loopback HTTP, truthful
zero/UNKNOWN, and selected-product public-method allowlisting. Repeated Episode, Candidate,
scope-replacement, and completed-Case tests must prove that retained collections return to the
active-set bound. Public observation requires explicit `CURRENT_STAGE` authority. The current
Inverse gate may establish current-state reachability and negative product contamination only; a
later natural schema-v4 Outcome remains a separate product result.
