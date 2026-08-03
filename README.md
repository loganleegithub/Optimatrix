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
→ official atomic-combo availability
→ Underwriting: CANDIDATE | WATCH | ABSTAIN when evaluable
→ explicit Shadow admission
→ Position: HOLD | CLOSE | UNKNOWN
→ strictly future Shadow Case Outcome
```

Before Shadow enrollment, market facts, Radar results, anomalies, quotes, Underwriting, Candidate,
and Workbench projections are in-memory current state. They are not durable research records. The
first durable product record is `SHADOW_CASE_OPENED`; a later qualification Cohort is derived
offline from Shadow Cases.

## Current stage

The active permission remains `PUBLIC_SHADOW`. The minimal Shadow Case data boundary is implemented
offline: pre-Shadow state is memory-only and only an admitted Case can create durable files. The
sole active closure is `SHORT_VOL_RADAR_STEADY_STATE_KNOWNNESS`: separate startup or recovery
index warmup from the post-warmup Radar denominator, expose bounded steady-state UNKNOWN reasons,
and report `post-warmup RADAR_KNOWN / APPLICABLE_MARKET_SCOPE`.

Persistent deployment remains forbidden. After the exact candidate passes focused tests,
`make check`, and GitHub CI, `CURRENT_STAGE` authorizes exactly one pre-bounded public-only
observation. It does not require a natural anomaly or Shadow admission; when no Shadow Case opens,
the durable Case-file count must remain zero.

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
- `options_domain`: instrument and target-size quote arithmetic;
- `short_vol_radar`: detector, episode, and official atomic-combo state;
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
