# Persistent public Shadow runtime and trader Workbench

## Shape

```text
Deribit public WebSocket
  → one startup-selected `LINEAR_BTC_USDC_V1 | INVERSE_BTC_V1` profile and Policy chain
  → one bounded application queue
  → one RadarReducer
  → one in-memory Underwriting/Shadow/Position owner
  → coalesced immutable Workbench snapshot
  → loopback GET/HEAD HTTP

explicit Shadow admission
  → minimal Shadow Case store
```

The Workbench renders current in-memory state. It never reads durable Case files and never performs
strategy calculations. Ordinary status-stable updates publish at most 2 Hz; readiness/currentness
changes publish immediately; pending state flushes before reconnect or stop.

One process owns exactly one immutable product profile, source universe, index, three-Policy chain,
funnel, Case schema branch, and Workbench unit projection. It cannot mix or switch products.

## Persistence

A run may create only:

```text
runs/<runtime>/cases/<case-id>/opened.json
runs/<runtime>/cases/<case-id>/first-close.json   # optional, at most one
runs/<runtime>/cases/<case-id>/outcome.json       # optional, at most one
```

No Radar event, anomaly, quote, Underwriting evaluation, Candidate, Workbench snapshot, service
lifecycle, host metric, manifest, receipt, inventory, or full market fact is persisted.

## Operations

The application exposes `/healthz`, `/readyz`, and `/api/workbench/current`. Process supervision,
restart policy, CPU, memory, and host logs are external operational concerns. The application does
not inspect or manage them. Endpoint capability is not invocation authority: the current Inverse
construction closure forbids probes, smoke, service start, restart, and natural Shadow observation.
