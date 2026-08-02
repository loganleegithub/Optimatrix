# Persistent Public Shadow Runtime and Workbench Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`

## Purpose

Run one public Deribit → Radar → Underwriting → Shadow Case → Position → Outcome path in one
long-lived process and expose current settled state through a loopback read-only Workbench.

The service adds no account, order, fill, capital, replay, database, qualification, or deployment
authority. Live invocation comes only from `CURRENT_STAGE`.

## Process shape

One process owns:

- one public Deribit client and bounded application queue;
- one synchronous Radar reducer;
- one in-memory Underwriting/Admission/Position owner;
- one minimal Shadow Case store;
- one coalesced immutable Workbench snapshot store;
- one loopback GET/HEAD HTTP server.

Recoverable transport failure starts a new session epoch without replacing the in-process owners.
A process restart creates a fresh runtime and does not resume prior open Cases.

## State root

One external absolute state root contains:

```text
service.lock
runs/<runtime-id>/cases/<case-id>/...
```

There is no `radar/` or `downstream/` evidence directory. The lock prevents two processes from
owning the same state root. It is not a commissioning or host-identity proof.

## Runtime lifecycle

`serve-shadow` performs only:

1. prepare one clean code identity and fixed three-Policy chain;
2. acquire the state-root lease and create a fresh runtime/cases directory;
3. start loopback Workbench;
4. connect/reconnect one public Deribit session;
5. settle each accepted fact through Radar and the current owner;
6. publish admitted Shadow Case records and their bounded future results;
7. stop on the first SIGINT/SIGTERM or fatal process failure.

Process supervision, restart policy, CPU, memory, host logs, and uptime monitoring are external.
The application does not inspect or control them.

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

There is no publication timer, event stream, durable Workbench file, SSE, partial patch, or browser
strategy engine. HTTP readers see old or new complete bytes only.

## Funnel diagnostics

The service exposes non-durable funnel counts and a primary blocker in the Workbench. They are
computed from current reducer/owner transitions and reset with the runtime. They do not create Case
files or qualify a Policy.

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

Before reconnect or clean stop, every accepted queued fact is drained and pending Workbench state
is flushed. The owner terminalizes pending Cases as censored when the failure/stop boundary is
available. An uncatchable process loss may leave only `opened.json`; the Case reader reports it as
`INCOMPLETE_UNCLEAN_EXIT`.

No terminal manifest, inventory, service receipt, host audit, or automatic restart belongs to this
contract.

## Direct verification

Offline tests cover one owner graph, fixed Policies, reconnect without owner replacement,
pre-Shadow file count zero, Case open/first-close/outcome persistence, minimal reader states,
Workbench coalescing/status bypass/flush, loopback HTTP, truthful zero/UNKNOWN, and public-method
allowlisting. A later bounded public smoke may prove current-state reachability only.
