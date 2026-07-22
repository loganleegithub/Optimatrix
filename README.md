# Optimatrix

Optimatrix is being built as an evidence-driven autonomous 0–3DTE options decision and trading
system. Its first product slice under construction is Deribit BTC-USDC defined-risk Short Vol. The
current permission boundary is production-public Shadow only: no private API, account, margin,
order, fill, or money access exists.

The current system asks one finite-horizon underwriting question:

> For a BTC 0–3DTE defined-risk option structure and a finite holding horizon, is the visible
> executable premium sufficient for observed path, touch, tail, liquidity, cost, and uncertainty?

It returns `RESEARCH_CANDIDATE`, `WATCH`, or `ABSTAIN`. A research candidate is not a qualified
strategy and grants no trading authority.

## Authority and current status

Start with [`AGENTS.md`](AGENTS.md). The
[`PRODUCT_CONSTITUTION`](docs/authority/PRODUCT_CONSTITUTION.md) governs three orthogonal
authorities: [`CURRENT_STAGE`](docs/authority/CURRENT_STAGE.md) grants permission,
[`SYSTEM_ARCHITECTURE`](docs/authority/SYSTEM_ARCHITECTURE.md) owns structure, and
[`DELIVERY_CONTRACT`](docs/authority/DELIVERY_CONTRACT.md) owns development and evidence. The
active task and implementation contract must satisfy all four.

Repository-owned contracts, tasks, and receipts use semantic identities and content digests—not
ordinal product generations. External protocols, dependencies, and build tools retain the exact
versions required for compatibility; those versions grant no product authority.

The bounded Deribit capture/replay foundation is implemented. Decision Truth is the sole
authorized next closure. Production Shadow Decision-to-Outcome receipts, qualification,
Challenger research, promotion, and execution are not implemented or authorized.

## Repository shape

- `market_tape`: canonical public facts, causal order, gap/reconnect, capture, and replay
- `options_domain`: observed option facts and visible defined-risk structure economics
- `short_vol_radar`: current frames, finite-horizon risk, insurance assessment, and decision
- `shadow_engine`: entry-frozen future-only Shadow position and Outcome primitives
- `radar_runtime`: Deribit public adapter and deterministic CLI composition

The repository remains a modular monolith. Later-stage services and platforms are intentionally
absent.

## Local verification

```bash
make sync
make check
.venv/bin/python -m radar_runtime demo --output /tmp/optimatrix-demo
.venv/bin/python -m radar_runtime inspect /tmp/optimatrix-demo/capture
.venv/bin/python -m radar_runtime replay /tmp/optimatrix-demo/capture --output /tmp/replay
```

If the installed `uv` is available only as a Python module, use:

```bash
make UV='python3 -m uv' sync
```

## Production-public bounded capture

The Deribit collector requires no credentials:

```bash
.venv/bin/python -m radar_runtime capture \
  --duration-seconds 15 \
  --output /tmp/optimatrix-bounded
.venv/bin/python -m radar_runtime inspect /tmp/optimatrix-bounded/capture
.venv/bin/python -m radar_runtime replay \
  /tmp/optimatrix-bounded/capture \
  --live /tmp/optimatrix-bounded/live.json \
  --decision /tmp/optimatrix-bounded/decision.json \
  --output /tmp/optimatrix-bounded-replay
```

This creates one bounded capture receipt and one Decision receipt, not a continuous acquisition or
production Shadow service. A
duration above 3,600 seconds only makes a complete 60-minute observation possible; inspect/replay
must prove actual coverage, freshness, platform state, and contamination status.

Zero candidates are a valid market result. Matching live/replay digests prove deterministic
reconstruction of the sealed tape, not data completeness, strategy quality, fills, or trading
authority.
