# Optimatrix

Optimatrix is a trader-facing BTC 0–3DTE options opportunity-discovery and Shadow-learning system.
The accepted implementation contains Deribit Linear BTC-USDC and Inverse BTC defined-risk Short Vol
as two strict product profiles without a second runtime architecture. One process selects exactly
one product and its matching three-Policy chain at startup; it never mixes products, legs, funnels,
state roots, or Outcomes. The system has no private account, order, fill, capital, actual-margin, or
actual-position capability.

## Product flow

```text
Deribit public facts
→ one startup-selected product profile and Policy chain
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

The permission boundary remains `PUBLIC_SHADOW`. The final accepted Linear process is
`STOPPED_CLEANLY`, is not authorized to restart, and reached
`5,043,177` applicable and `5,040,616` Radar-known evaluations, `11` Episodes, `6`
Underwriting-evaluable structures, and zero Candidates or admitted-Candidate Cases. All six
evaluable structures stopped at `CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE`. The separate
selected-decision projection made six future-blind selections: five opened complete no-trade
control Cases and one terminalized `UNKNOWN_CONSUMED` on receive skew. All five Outcomes are
`CENSORED_AT_STOP`; `COMPLETE` means lifecycle-terminal, not known economics or profitability.

PR #27 accepted `INVERSE_BTC_V1` construction at merged-main code identity `89a6eb02...` while
preserving exact Linear schema-v3 behavior. PR #28 authorized one Inverse-only process, which
reached exact-identity `RUNNING/CURRENT/ready` snapshots with `128 / 128` current-known instruments
and no product contamination. The snapshots were `100,000 ms` apart against the frozen `30,000 ms`
maximum, so the first-600-second gate is `REJECTED / GATE_OBSERVATION_INTERVAL_UNPROVEN`. The process
stopped cleanly without restart; the official verifier reports zero Cases and zero Outcomes. Every
live command is now forbidden pending fresh human Authority. This validation failure does not
establish a runtime defect, account margin, frequency, edge, profitability, or qualification.

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
