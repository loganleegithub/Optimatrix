# Optimatrix

Optimatrix is a trader-facing BTC 0–3DTE options opportunity-discovery and Shadow-learning system.
The current product slice consumes Deribit BTC-USDC public data, evaluates one fixed defined-risk
Short Vol strategy chain, displays current opportunity state, and may enroll a simulated Shadow
Case for strictly future observation. It has no private account, order, fill, capital, or actual
position capability.

## Product flow

```text
Deribit public facts
→ bounded current market state
→ Short Vol Radar
→ Underwriting-selected frozen protective vertical
→ conservative full-quantity component-book counterfactual
→ Underwriting: CANDIDATE | WATCH | ABSTAIN when evaluable
→ at most one action-blind selected decision per causal activation batch
→ ordinary Candidate admission, or selected WATCH/ABSTAIN no-trade enrollment
→ Position: HOLD | CLOSE | UNKNOWN
→ strictly future Shadow Case Outcome
```

Before Shadow enrollment, market facts, Radar results, anomalies, quotes, Underwriting, Candidate,
and Workbench projections are in-memory current state. They are not durable research records. The
first durable product record is `SHADOW_CASE_OPENED`; a later qualification Cohort is derived
offline from Shadow Cases.

## Current stage

The active permission remains `PUBLIC_SHADOW`. The completed natural run observed `10` Radar
Episodes, `7` reviewable/component-book/Underwriting-evaluable Episodes, and zero Candidates,
Cases, or Outcomes. All seven selected structures first failed
`CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE`; `NO_ACTIVE_COMBO 10` remained a parallel diagnostic and did
not veto the component-book path. The formal whole-funnel primary loss still starts earlier at the
`938 / 1,812,600` Radar-knownness gap; the active task intentionally owns the Authority-selected
downstream `7 → 0` closure.

The active task now closes the selective-label gap without changing economic thresholds. For each
causal Radar activation batch it designates at most one Episode before action or future facts are
known, with no `UNKNOWN` fallback. The designated Episode's first evaluable decision receives one
strictly later paired refresh: a decision selected as Candidate and still Candidate reuses ordinary
admission, while every other evaluable selection may open an explicitly tagged no-trade Case.
Original/refreshed predicate-margin vectors and the
strictly future Outcome appear in a separate Workbench research panel and never alter the canonical
Candidate funnel.
The one calibration probe is exhausted; no public smoke, natural runtime, deployment, private API,
order, fill, or actual exposure is currently authorized.

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
- `options_domain`: instrument, target-size depth, component-leg stress, and fee arithmetic;
- `short_vol_radar`: detector, episode, protective-structure review, and atomic diagnostics;
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
