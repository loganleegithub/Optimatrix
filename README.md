# Optimatrix

Optimatrix is a trader-facing BTC 0–3DTE options opportunity-discovery and Shadow-learning system.
The Online Runtime has one economic product, Deribit `INVERSE_BTC_V1`, and one repository strategy
channel, `INVERSE_BTC_SHORT_VOL_V2`. V2 is an ordinal opportunity-ranking hypothesis, not an
oracle, calibrated probability, or Edge claim. One process binds the canonical Inverse product specification and
its exact three-Policy chain for the full run; there is no product selector, fallback, or runtime
product switch. The system has no private account, order, fill, capital, actual-margin, or
actual-position capability.

## Product flow

```text
Deribit public facts
→ fixed `INVERSE_BTC_V1` product specification and Policy chain
→ bounded current market state
→ Short Vol V2 score: premium evidence × path/liquidity quality
→ one leader per TTE/expiry/type/Delta bucket
→ Underwriting-selected frozen protective vertical
→ conservative full-quantity component-book counterfactual
→ Underwriting: CANDIDATE | WATCH | ABSTAIN when evaluable
→ ordinary HIGH Candidate admission, or at most one future-blind LOW/MID no-trade Control
→ Position: HOLD | CLOSE | UNKNOWN
→ strictly future Shadow Case Outcome
```

## Product roadmap

The roadmap is non-authorizing. Only the upper-left channel is implemented; the other cells create
no Policy, runtime, module, or placeholder in this repository.

| Channel | Implementation | Policy | Runtime |
| --- | --- | --- | --- |
| `INVERSE_BTC_SHORT_VOL` (`INVERSE_BTC_SHORT_VOL_V2`) | `IMPLEMENTED` | fixed V2 Inverse three-Policy chain | `PUBLIC_SHADOW` |
| `INVERSE_BTC_LONG_GAMMA` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |
| `INVERSE_ETH_SHORT_VOL` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |
| `INVERSE_ETH_LONG_GAMMA` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |

Before Shadow enrollment, market facts, Radar results, anomalies, quotes, Underwriting, Candidate,
and Workbench projections are in-memory current state. They are not durable research records. The
first durable product record is `SHADOW_CASE_OPENED`; a later qualification Cohort is derived
offline from Shadow Cases.

## Current stage

The permission boundary remains `PUBLIC_SHADOW`. H2 already started the sole V2 process on its
stable non-temporary root. The active repository-only task repairs V2 causal coherence for delayed
HIGH enrollment, optional S/T source skew, cross-Call/Put invalidation, ticker countability, tick
ladder distance, and Case-report strata. It changes the fixed three-Policy repository identity
chain but is explicitly not deployed.

This task neither inspects nor changes `127.0.0.1:8765`, the running H2 process, or any external
root. Deployment requires a later explicit task and a fresh Policy-compatible root boundary. A
historical live snapshot does not establish future uptime, fillability, account margin, frequency,
edge, profitability, or qualification. Exact runtime identity, durable effect, and permission
details are in `docs/authority/CURRENT_STAGE.md`.

See:

- `docs/authority/PRODUCT_CONSTITUTION.md`
- `docs/authority/CURRENT_STAGE.md`
- `docs/authority/SYSTEM_ARCHITECTURE.md`
- `docs/authority/DELIVERY_CONTRACT.md`
- `docs/contracts/SHORT_VOL_RADAR.md`
- `docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md`
- `docs/contracts/SHORT_VOL_SHADOW_CASE.md`
- `docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md`

## Repository shape

- `market_monitor`: Deribit public-source parsing, continuity, trusted time, and bounded market
  state;
- `options_domain`: one immutable product specification, instruments, native target-size depth and
  tick stress, product fee arithmetic, model normalization, and valuation conversion;
- `short_vol_radar`: V2 score/features, bucket/episode state, protective-structure review, and
  atomic diagnostics;
- `short_vol_underwriting`: Underwriting, admission, Position, Outcome, in-memory owner state, and
  the minimal Shadow Case store;
- `radar_runtime`: one process, one bounded queue, one reducer, Shadow adapter, funnel diagnostics,
  and loopback read-only Workbench.

## Engineering rules

Product progress means moving one funnel node or lowering its largest blocker—not producing more
receipts, hashes, tests, objects, or runtime hours. The application does not commission itself,
inspect host logs/PIDs, maintain a replay platform, or persist Workbench/operational state.

## Local verification

```bash
make sync
make check
```

Passing checks proves only the offline code behavior. It does not establish opportunity frequency,
strategy value, fillability, deployment, qualification, or execution permission.
