# Optimatrix Current Stage

**Status:** B3 PUBLIC SHADOW RUNTIME — ACTIVE

**Current maturity:** `B3_ATOMIC_PUBLIC_SHADOW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `IMPLEMENTATION`

**Sole authorized closure:** [`../../tasks/B3_PUBLIC_SHADOW_RUNTIME.md`](../../tasks/B3_PUBLIC_SHADOW_RUNTIME.md)

## Current permissions

Stage is the permission ceiling; a future active task may only narrow it.

**Offline checks and simulation:** authorized in disposable ignored `build/` roots

**Public market calls:** production Deribit public methods and exact bounds authorized only by the
active task

**Stable ObservationLedger root:** `/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1`
for the active task only

**Disposable offline ObservationLedger:** authorized only under caller-supplied ignored roots

**Stable CaseJournal root:** the same active-task root, isolated from every legacy or foreign root

**Continuous runtime:** one local Python process and one loopback-only Workbench authorized by the
active task

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current implementation truth

- `DecisionWindow` is a Policy-scheduled, Session-aligned denominator. The current 15-minute
  schedule produces 96 immutable Windows per Deribit Session; missing observations still produce
  one `UNKNOWN` DecisionRecord.
- `MarketObservation` binds one bounded universe, causal timestamps, DataHealth Policy, public
  facts, and named proxies. `ObservationLedger` appends at most one DecisionRecord and one distinct
  WindowOutcome per Window under a caller-supplied root.
- BTC selection directly evaluates whole same-Session four-leg structures. It separately reports
  legal, price-evaluable, and Policy-eligible populations, freezes bounded comparable alternatives,
  uses standard Combo fee projection, and treats current close depth as a diagnostic rather than an
  Entry veto.
- A Candidate requires one `AVAILABLE` ShadowRiskAllocation with explicit USD contractual-payoff
  budget, native-BTC economics, inverse delivery-price stresses, capacity boundary, expiry, and
  release rule.
- A Candidate opens one `truth_layer=SHADOW_PROJECTION` TradeCase. Entry is strictly later and only
  `SHADOW_ATOMIC_EVALUABLE` creates one whole-product Shadow Position; missing or shallow component
  facts never create partial exposure or remediation states.
- Position monitoring uses the frozen structure expiry and Policy cadence. DataHealth gaps preserve
  the Position and existing intent; the first known whole-product ExitIntent is immutable; only a
  strictly later whole-product estimate or a matching typed expiry-settlement fact terminalizes it.
- `CaseJournal` stores an append-only accepted TradeCase prefix under a caller-supplied root and can
  discard only an unterminated final write. `ShadowCaseOutcome` keeps terminal economics separate
  from all-Window future-path truth and exposes eight independent eligibility facts.
- The deterministic acceptance population contains `96/96` DecisionRecords and `96/96`
  WindowOutcomes. Seven offline scenarios pass, including atomic Entry/exit, Gap preservation,
  expiry settlement, and duplicate suppression. These fixtures are not market evidence.

The component-Vertical acquisition path, public-Combo discovery gate, buyback-depth hard veto,
partial/remediation graph, residual-wing lifecycle, and pre-A0 journal codec are absent.

No continuous observation service, stable durable root, private account truth, real Combo order or
fill lifecycle, account capital reservation, qualified Policy, Edge, Alpha, win-rate, or
profitability evidence exists.

**Primary blocker:** `CONTINUOUS_PUBLIC_SHADOW_NOT_OBSERVED` — source can express the complete
research loop, but no production Deribit Session has yet been continuously recorded, recovered,
rendered, and accepted by a trader. The active task must close this before C1 may be activated.

## Maturity ladder

This is the only maturity ladder. A stage name describes evidence maturity; it grants no permission.
Entry into a later stage requires a new active task, exact permissions, and measured acceptance of
its predecessor.

- `A0_AUTHORITY_CORRECTION` — one owner per concept, four online identities plus one optional
  derived Episode grouping, explicit truth layers, and no cross-layer inference.
- `B1_WINDOW_OBSERVATION` — pre-registered public DecisionWindows, causal DataHealth, all-Window
  ObservationLedger, measured denominator, and blocker/Candidate reachability.
- `B2_STRUCTURE_PRICING` — route-independent four-leg discovery, bounded alternatives, inverse-unit
  correctness, Combo fees, and measured liquidity/stress evidence.
- `B3_ATOMIC_PUBLIC_SHADOW` — complete whole-product public Shadow TradeCase, monitoring, exit or
  settlement, Outcome, and future-path population without fill claims.
- `C1_PRIVATE_READ_ONLY` — authenticated account, margin, order, fill, fee, and Position
  reconciliation with no order permission.
- `C2_AUTHORIZED_COMBO_EXECUTION` — bounded Deribit Combo execution beginning on testnet; any real
  capital requires separate exact authorization and acceptance.
- `D1_OFFLINE_AI_CHALLENGER` — sufficient forward Outcomes support frozen chronological or
  walk-forward Base-versus-Challenger recommendations with human promotion only.

**Next upgrade condition:** only after the active runtime task closes with one complete production
Session and explicit trader Workbench acceptance may a bounded `C1_PRIVATE_READ_ONLY` task be
activated. That task must name an exact private read-only permission, authenticated evidence source,
redaction boundary, and reconciliation acceptance. It may not place, edit, cancel, or simulate an
order, reserve capital, promote Policy, or infer real Position truth from Public Shadow records.
