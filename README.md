# Optimatrix

Optimatrix is intended to become an autonomous 0–3DTE options decision and trading system. Its
first product slice is Deribit BTC-USDC defined-risk Short Vol. The current permission is
production-public Shadow only: no private API, account, margin, order, fill, or money access.

## Current truth

This branch contains the implementation-under-review for one production-public Radar runtime and
its guarded `observe` command. It still contains no bounded market-capture job, saved-data scanner,
replay closure, fixed holding-period Decision, Shadow position, or Outcome engine.

The production Short Vol Radar is `NOT_ESTABLISHED`. The sole authorized next product-capability
closure is `SHORT_VOL_RADAR_ESTABLISHMENT`; code and tests alone do not establish it.

## Intended first business flow

```text
live Deribit BTC-USDC 0–3DTE option-chain changes
→ one exact content-identified Short Vol baseline
→ independent SHORT_VOL_ANOMALY_EVENT
→ while active, independent official atomic-combo availability
→ optional PUBLIC_ATOMIC_QUOTE_EVENT
```

Market ingestion, bounded in-memory chain maintenance, and Radar notification are one continuous
event-driven flow. The product does not first save the whole market and then repeatedly scan the
same facts. Ordinary no-anomaly updates and the theoretical structure universe are not persisted.

The three layers remain distinct:

- detector: `UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE`;
- existing official atomic combo:
  `NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO | NO_TARGET_SIZE_CREDIT_QUOTE |
  PUBLIC_ATOMIC_QUOTE_AVAILABLE`;
- future maker/order/fill: not implemented or authorized.

An anomaly or public atomic quote is not Candidate, Shadow Entry, fill, Outcome, or proof of an
edge. Component-leg prices cannot substitute for an official combo.

Exact quantity, Delta/TTE bands, return lookbacks, trigger/clear ratios, and persistence live in a
content-identified Policy file rather than code. One run cannot change its Policy. A
human-approved successor inside the declared Policy schema uses a new identity and forward
observation interval; current Radar evidence alone cannot prove better forecasting or
profitability.

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

- `market_monitor`: public adapters, known-at order, continuity, and bounded current state
- `options_domain`: option facts, authorized leg relationships, and target-size public
  quote arithmetic
- `short_vol_radar`: detector episodes, official atomic availability, and minimal event
  projection
- `radar_runtime`: guarded composition of the continuous production-public process

There is no compatibility package or alias for the removed pipeline.

## Local verification

```bash
make sync
make check
```

The implementation task's construction gate is open. Running `python -m radar_runtime observe`
still requires a separate explicit human production-observation command naming the exact Policy
path and expected digest.
