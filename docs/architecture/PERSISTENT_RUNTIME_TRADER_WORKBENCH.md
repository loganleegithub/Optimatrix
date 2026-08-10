# Persistent public Shadow runtime and trader Workbench

## Shape

```text
Deribit public Inverse BTC WebSocket
  → fixed `INVERSE_BTC_V1` product and `INVERSE_BTC_SHORT_VOL_V2` three-Policy chain
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

The Workbench renders server-owned V2 score/leader/coverage truth and selection-to-entry score
drift. It never reads durable Case files and never performs strategy calculations. Ordinary
status-stable updates publish at most 2 Hz;
readiness/currentness changes publish immediately; pending state flushes before reconnect or stop.
Every active admitted Entry appears once by `shadow_entry_identity`, with origin runtime, current
Observation Segment, gap/currentness, first-CLOSE attempt, Outcome quality, and qualification
eligibility kept distinct from runtime health.

## Persistence

The external stable non-temporary state root may contain only the bounded schema-v5 Case family:

```text
service.lock
cases/<case-id>/opened.json
cases/<case-id>/segments/<segment-sequence>/opened.json
cases/<case-id>/segments/<segment-sequence>/closed.json   # optional
cases/<case-id>/first-close.json                          # optional
cases/<case-id>/outcome.json                              # optional
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

The current V2 process uses the fresh stable non-temporary root declared in `CURRENT_STAGE`. The V1
temporary root remains separate historical truth; no V1 Case is copied, migrated, or recovered into
V2. Runtime reachability grants no automatic restart authority.
