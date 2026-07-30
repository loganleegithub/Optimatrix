# Optimatrix

Optimatrix is intended to become an autonomous 0–3DTE options decision and trading system. Its
first product slice is Deribit BTC-USDC defined-risk Short Vol. The current permission is
production-public Shadow only: no private API, account, margin, order, fill, or money access.

## Current truth

The implemented capability is `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`: one guarded
production-public Radar runtime and its `observe` command. It contains no bounded market-capture
job, saved-data scanner, replay closure, fixed holding-period Decision, Shadow position, or
Outcome engine.

The production Short Vol Radar is `ESTABLISHED` by independently accepted, exact-commit Smoke and
Soak evidence. No successor product-capability closure is active. The downstream
[`SHORT_VOL_UNDERWRITING_POSITION`](docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) contract is
frozen as active implementation authority, but no Underwriting, Candidate, Shadow admission,
Position, close-opportunity, or Outcome runtime exists or is authorized. Establishment means the
bounded public runtime met its frozen reachability and operating predicates; it does not mean the
Radar is persistently deployed, always running, indefinitely stable, profitable, or authorized to
trade.

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
human-approved or expressly terminal-goal-delegated successor inside the declared Policy schema
uses a new identity and forward observation interval; current Radar evidence alone cannot prove
better forecasting or profitability.

## Later Underwriting and position behavior

The frozen downstream contract requires separate content-identified Underwriting and Position
Policies. Shadow admission is a deterministic gate rather than a third Policy: it requires a
still-valid Candidate and a strictly later current full-quantity official atomic quote proof.

Neither a future `SHADOW_ENTRY` nor a filled entry chooses a planned holding duration. A future
Position implementation will evaluate remaining premium, short-leg risk, path, volatility state,
liquidity, executable close debit, fees, and hard boundaries before returning
`HOLD | CLOSE | UNKNOWN`. A known hard-close obligation remains `CLOSE` when its quote is
unavailable. None of that runtime behavior is implemented or authorized.

## Authority

Start with [`AGENTS.md`](AGENTS.md). The
[`PRODUCT_CONSTITUTION`](docs/authority/PRODUCT_CONSTITUTION.md) owns product meaning,
[`CURRENT_STAGE`](docs/authority/CURRENT_STAGE.md) grants permission,
[`SYSTEM_ARCHITECTURE`](docs/authority/SYSTEM_ARCHITECTURE.md) owns structure, and
[`DELIVERY_CONTRACT`](docs/authority/DELIVERY_CONTRACT.md) owns development and evidence.
[`SHORT_VOL_RADAR`](docs/contracts/SHORT_VOL_RADAR.md) defines the established Radar.
[`SHORT_VOL_UNDERWRITING_POSITION`](docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) freezes the
later public-only Underwriting, Shadow-admission, and Position boundary without implementing it.

## Repository shape

- `market_monitor`: public adapters, known-at order, continuity, and bounded current state
- `options_domain`: option facts, authorized leg relationships, and target-size public
  quote arithmetic
- `short_vol_radar`: detector episodes, official atomic availability, and minimal event
  projection
- `radar_runtime`: guarded composition of the continuous production-public process

There is no current Underwriting or Position package and no compatibility package or alias for the
removed pipeline.

The current bounded runtime separates per-band immutable index-baseline availability from
generation-global successor publication. Normal time/watermark publication pending keeps an
already proven `N + 1` close tuple available and does not pause detector episodes, Layer 2, known
coverage, or persistence. Real window, source-stale, and continuity failures remain fail-closed.
Publication currentness invalidates exactly once independently from continuity-incident restart
de-duplication, so a stronger clock/session/index loss cannot leave a pending row or tuple alive.
Current run summaries use diagnostics schema version 6; sealed versions 5 through 2 remain
read-only and are never migrated.

## Local verification

```bash
make sync
make check
```

The guarded `python -m radar_runtime observe` command is the public-only runtime entry point under
`PUBLIC_SHADOW`. Each bounded observation still uses one immutable Policy identity and a fresh
evidence directory and preserves clean-stop and strict-validation behavior. The accepted Smoke and
Soak establish only their exact pre-bound observation windows; they do not authorize persistent
service deployment, private/account access, orders, fills, capital, execution, or any queued
product closure.
