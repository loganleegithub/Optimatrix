# Persistent public Shadow runtime and trader Workbench

## Shape

```text
Deribit public Inverse BTC WebSocket
  → fixed `INVERSE_BTC_V1` product specification and three-Policy chain
  → one bounded application queue
  → one RadarReducer
  → one in-memory Underwriting/Shadow/Position owner
  → stable process-independent Shadow Entry repository
  → coalesced immutable Workbench snapshot
  → loopback GET/HEAD HTTP
```

There is no online product selector, fallback profile, or product switch. The fixed product owns
the `btc_usd` public source, BTC-native premium/fees/settlement/PnL, explicit `USD_EQUIVALENT`
valuation, Inverse Case schema, funnel, and Workbench unit projection.

The Workbench renders server-owned current state. It never reads durable Case files and never
performs strategy calculations. Ordinary status-stable updates publish at most 2 Hz;
readiness/currentness changes publish immediately; pending state flushes before reconnect or stop.
Every active admitted Entry appears once by `shadow_entry_identity`, with origin runtime, current
Observation Segment, gap/currentness, first-CLOSE attempt, Outcome quality, and qualification
eligibility kept distinct from runtime health.

## Persistence

The external stable state root may contain only the bounded Case family:

```text
service.lock
cases/<case-id>/opened.json
cases/<case-id>/segments/<segment-sequence>/opened.json
cases/<case-id>/segments/<segment-sequence>/closed.json   # optional
cases/<case-id>/first-close.json                          # optional
cases/<case-id>/outcome.json                              # optional
cases/<case-id>/legacy-migration.json                     # optional
```

The first durable product boundary is `SHADOW_CASE_OPENED`; for an admitted Entry its origin
Segment is published in the same complete initial Case directory. Market facts, Radar events,
anomalies, quotes, Underwriting evaluations, Candidates, Workbench snapshots, service lifecycle,
host metrics, manifests, receipts, inventories, and full-market facts are not persisted.

The stable repository owns admitted Entry continuity across processes. A runtime owns only its
Observation Segment. A later externally started runtime restores compatible non-terminal Inverse
Entries, starts their fresh current data at `UNKNOWN`, and records an observation gap without
synthesizing `HOLD` or `CLOSE`.

## Operations

The application exposes `/healthz`, `/readyz`, and `/api/workbench/current` on loopback. Process
supervision, restart policy, CPU, memory, and host logs are external operational concerns. The
application does not inspect or manage them.

The accepted repository state authorizes no live command. The existing `127.0.0.1:8765` process
was observed from the older code identity `270920fb1fcb255c648e95361f31c1e5075ec294`; repository
acceptance did not hot-swap, stop, restart, or repoint it and does not prove the accepted source is
deployed. A later restart requires a separate explicit task and permission boundary. External
state roots were not opened, migrated, rewritten, or deleted for the repository closure.
