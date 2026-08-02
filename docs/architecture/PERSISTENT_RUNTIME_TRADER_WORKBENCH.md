# Persistent public Shadow runtime and trader Workbench

## Shape

```text
Deribit public WebSocket
  → one LiveRadarRuntime / RadarReducer
  → one FixedContractShadowOwner
  → Radar and downstream business objects
  → coalesced immutable Workbench snapshot
  → loopback GET/HEAD HTTP
```

This is one process and one event-driven business path. There is no commissioning controller,
service-evidence ledger, database, broker, scheduler, replay job, second reducer, browser strategy
engine, or private execution surface.

## Startup and lifecycle

The process locks one external state root, creates a fresh runtime directory, loads one immutable
three-Policy chain, starts the loopback HTTP surface, and connects one public Deribit client. A
recoverable transport failure opens the next session epoch without replacing the reducer or
Shadow/Position owner. `SIGINT` and `SIGTERM` latch one stop boundary. Protocol incompatibility or
an unexpected runtime failure is terminal.

Lifecycle is projected in memory as service phase plus independent data currentness. `ready`
requires `RUNNING` and `CURRENT`; an open socket is insufficient. `UNKNOWN`, `STALE`, and
`DEGRADED` remain visible business availability states rather than process failures or zero values.

## Persistence boundary

Each run directory has only:

```text
radar/       minimal anomaly, atomic-quote, and clean-stop summary objects
downstream/  Underwriting, Shadow, Position, Outcome, and aligned business objects
```

The service does not persist lifecycle transitions, terminal manifests, inventories, Workbench
JSON, full books, ordinary ticks, probes, or host-resource observations.

## Workbench boundary

Business settlement completes before publication. Ordinary status-stable updates are coalesced to
at most 2 Hz; semantic status changes publish immediately; the latest pending state flushes before
reconnect or stop. Each publication atomically replaces one complete immutable schema-2 byte
snapshot. HTTP handlers never traverse mutable reducer/owner state.

The browser only renders the snapshot. Fetch/render failure hides stale tables and reports
`UNKNOWN`. Empty panels remain distinct from conditioned numeric zero. Public quotes and Shadow
entries remain explicitly not orders, fills, actual positions, or actual PnL.

## Operations boundary

Process restart and host CPU/memory monitoring belong to a standard external supervisor. The
Python application never calls launchd, `lsof`, or operating-system log tools and contains no
24-hour acceptance controller. Deployment remains separately authorized by `CURRENT_STAGE`.
