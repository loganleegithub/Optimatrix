# Persistent Public Shadow Runtime and Workbench Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning semantic identity:** `SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`

## Purpose

Run the existing public Deribit → Radar → Underwriting → Shadow → Position → Outcome path in one
long-lived process and expose its settled current state through a loopback read-only Workbench.

This contract authorizes implementation only. Live invocation and deployment come from
[`CURRENT_STAGE`](../authority/CURRENT_STAGE.md). It adds no private/account source, order, fill,
capital, Policy mutation, replay system, database, service split, or trading control.

## One process and owner graph

One absolute external `state_root` owns:

```text
service.lock
runs/<runtime-digest>/
    radar/
    downstream/
```

The process takes a non-blocking advisory lock before constructing a market client. Each start
creates a new runtime identity and run directory. Reconnects increment the session epoch while
retaining the same reducer and downstream owner; restarts never continue in-memory Candidates,
Positions, or Outcomes.

Startup loads the exact Radar, Underwriting, and Position Policy files once. The same immutable
`PolicyChain` is shared by the reducer and downstream owner. There is no hot reload, threshold
adjustment, watcher, or no-opportunity extension.

## Continuous runtime

`serve-shadow` performs only these orchestration duties:

1. start the loopback Workbench;
2. open one public Deribit session;
3. let `LiveRadarRuntime` settle accepted facts through every business owner;
4. reconnect recoverable public transport failures with the existing bounded delay;
5. stop on the first `SIGINT` or `SIGTERM` boundary;
6. terminate downstream pending state on clean stop or fatal process failure.

The host does not inspect macOS logs, execute `lsof`, manage launchd, probe itself, calculate CPU
acceptance, write commissioning receipts, or decide whether a run has been online long enough.
Those are external operational concerns.

## Persistence

Durable output is limited to existing business records:

- minimal Radar anomaly and official atomic-quote events plus one clean-stop run summary;
- downstream Underwriting, Candidate, simulated Entry, Position, close-opportunity, Outcome, and
  aligned objects already required by the accepted business contracts.

Normal market ticks, complete books, no-anomaly updates, Workbench snapshots, HTTP requests,
service lifecycle events, terminal manifests, file inventories, and service acceptance receipts
are not persisted.

Domain writers retain their direct schema/identity validation because those checks define the
meaning of business objects. There is no second service-level reader or hash ledger around them.
The downstream writer does not rebuild and validate the complete accumulated relationship graph
for every new object, and the current offline reader does not recreate that graph.

## Lifecycle and currentness

Workbench service phase is:

```text
STARTING | CONNECTING | RUNNING | RECONNECTING | STOPPING | STOPPED | FAILED
```

Data state is independently:

```text
CURRENT | DEGRADED | STALE | UNKNOWN | INTERRUPTED | STOPPED
```

`health = true` means the process and HTTP surface are responsive. `ready = true` requires
`RUNNING`, an established current session, and `CURRENT` data. Connection alone never proves
readiness. Missing, stale, incomplete, or discontinuous business facts keep their owning
`UNKNOWN`; they do not stop an otherwise functioning process.

## Workbench publication

After a runtime fact settles Radar and the downstream owner, the publisher retains the latest
settled reducer/commit reference. It publishes a complete immutable schema-2 snapshot:

- immediately on a semantic safety or lifecycle status change;
- at most once per 500 monotonic milliseconds for ordinary status-stable facts;
- once for the latest pending state after accepted-event drain and before reconnect or clean stop.

There is no publication timer, queue, thread, partial patch, SSE stream, or durable snapshot.
Cached downstream grouping is invalidated only by the existing downstream writer revision.
Serialization and atomic store replacement complete before HTTP readers can observe new bytes.

An empty panel is not a zero claim. Zero anomaly requires a complete known non-empty monitor
denominator. Zero Candidate additionally requires a positive Underwriting-evaluable denominator.
Otherwise the value is `null` and the state is `UNKNOWN`.

## HTTP boundary

The server binds only to an explicit loopback IP and accepts `GET`/`HEAD` for:

```text
/
/app.js
/styles.css
/api/workbench/current
/healthz
/readyz
```

Other methods return 405 and unknown paths return 404. Handlers read only the current immutable
byte snapshot. The browser formats settled data only; it cannot calculate strategy truth, mutate
Policy, connect to Deribit, access an account, or submit an order.

Fetch, decode, schema, or render failure hides cached business tables and marks the page
`UNKNOWN`. A later complete successful render may replace it.

## Direct verification

Offline tests must cover:

- one state-root lease and fresh runtime identity;
- one shared immutable Policy/owner graph;
- reconnect without owner replacement;
- clean stop and fatal downstream terminalization;
- Shadow settlement before Workbench publication;
- 500 ms coalescing, status bypass, latest-state flush, and atomic replacement;
- loopback-only GET/HEAD HTTP plus independent health/readiness;
- truthful empty/zero/null and browser fail-closed rendering.

These tests prove implementation behavior only. They do not prove production Radar correctness,
24-hour uptime, opportunity frequency, forecast skill, fillability, profitability, actual
exposure, PnL, qualification, promotion, or execution permission.
