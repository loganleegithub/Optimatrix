# Optimatrix

Optimatrix is intended to become an autonomous 0–3DTE options decision and trading system. Its
first product slice is Deribit BTC-USDC defined-risk Short Vol. The current permission is
production-public Shadow only: no private API, account, margin, order, fill, or money access.

## Current truth

This repository is a clean, authority-aligned implementation baseline. It has no product runtime
or product command today. In particular, it contains no bounded market-capture job, saved-data
scanner, replay closure, fixed holding-period Decision, Shadow position, or Outcome engine.

The production Short Vol Radar is `NOT_ESTABLISHED`. The sole authorized next product-capability
closure is `SHORT_VOL_RADAR_ESTABLISHMENT`.

## Intended first business flow

```text
live Deribit BTC-USDC 0–3DTE option-chain changes
→ frozen Short Vol richness detector
→ authorized target-size atomic combo credit spread
→ minimal SHORT_VOL_RADAR_HIT snapshot
```

Market ingestion, bounded in-memory chain maintenance, and Radar notification are one continuous
event-driven flow. The product does not first save the whole market and then repeatedly scan the
same facts. Ordinary no-hit updates and the theoretical structure universe are not persisted.

The Radar states remain distinct:

- `NO_HIT`: required current facts are usable and the detector did not fire;
- `UNKNOWN`: required facts are missing, stale, discontinuous, or unaligned;
- `ANOMALY_OBSERVED`: the detector fired but no authorized target-size atomic combo quote exists;
- `RADAR_HIT`: the anomaly and at least one such atomic combo structure coexist.

`RADAR_HIT` is not Candidate, Shadow Entry, fill, Outcome, or proof of an edge. A component-leg
quote is diagnostic and cannot create a hit.

## Later position behavior

Neither a future `SHADOW_ENTRY` nor a filled entry chooses a planned holding duration. A separately
authorized Position Policy will evaluate the current remaining premium, short-leg risk, path,
volatility state, liquidity, executable close debit, fees, and hard boundaries, then output
`HOLD | CLOSE | UNKNOWN`. None of that behavior is implemented or authorized in the current
closure.

## Authority

Start with [`AGENTS.md`](AGENTS.md). The
[`PRODUCT_CONSTITUTION`](docs/authority/PRODUCT_CONSTITUTION.md) owns product meaning,
[`CURRENT_STAGE`](docs/authority/CURRENT_STAGE.md) grants permission,
[`SYSTEM_ARCHITECTURE`](docs/authority/SYSTEM_ARCHITECTURE.md) owns structure, and
[`DELIVERY_CONTRACT`](docs/authority/DELIVERY_CONTRACT.md) owns development and evidence.
[`SHORT_VOL_RADAR`](docs/contracts/SHORT_VOL_RADAR.md) defines the first Radar.

## Repository shape

- `market_monitor`: future public adapters, known-at order, continuity, and bounded current state
- `options_domain`: future option facts, authorized leg relationships, executable economics, and
  bounded-loss calculations
- `short_vol_radar`: future detector state, episodes, structure checks, and minimal hit projection
- `radar_runtime`: future composition of the continuous public process

These packages are empty ownership boundaries, not implemented capabilities. There is no
compatibility package or alias for the removed pipeline.

## Local verification

```bash
make sync
make check
```

No live market command belongs to this clean-baseline closure. The next implementation task must
freeze its exact Radar Policy, tests, and production-public acceptance command before execution.
