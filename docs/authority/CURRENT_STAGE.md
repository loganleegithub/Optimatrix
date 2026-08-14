# Optimatrix Current Stage

**Status:** B3 ENTRY REUNDERWRITING — CLOSED

**Current maturity:** `B3_ATOMIC_PUBLIC_SHADOW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

## Current permissions

Stage is the permission ceiling; a future active task may only narrow it.

**Offline checks and simulation:** authorized only in caller-supplied ignored roots

**Public market calls:** `NONE_AUTHORIZED`

**Stable ObservationLedger root:** `NONE_AUTHORIZED`

**Disposable offline ObservationLedger:** authorized only under caller-supplied ignored roots

**Stable CaseJournal root:** `NONE_AUTHORIZED`

**Frozen prior evidence:** `/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1`
is retained without migration or mutation. Its records use the retired Policy identity and are not
eligible for current Base Policy evaluation or AI training.

**Continuous runtime:** `NONE`

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current implementation truth

- B1 Window observation, B2 whole-four-leg selection, all-Window Ledger records, atomic Public
  Shadow lifecycle, strictly later exit valuation, settlement fallback, and cross-Session runtime
  mechanics exist and pass deterministic repository evidence.
- Production-public v1 operation produced real Decision records but no naturally occurring
  Candidate-to-terminal chain. That runtime is stopped and its stable root remains frozen.
- Policy schema 6 gives new Decisions and Cases an identity distinct from the frozen v1 evidence.
- Decision and Entry call the same environment and exact-four-leg underwriting calculations.
  Entry evaluates only the Candidate's frozen legs; it cannot reselect a better later structure.
- Entry now freezes one typed reunderwriting result containing Decision-to-Entry phase, VRP,
  short-Delta, net-Delta, body-distance, credit/payoff, reference-loss, fee-burden, allocation, and
  route evidence. `CaseJournal` recovers it exactly and the Workbench exposes it.
- A Position is created only when later evidence is causal and healthy, phase and environment still
  admit new Entry, frozen structure limits still pass, full-amount pricing exists, current economics
  pass, and the frozen allocation remains valid. Known failures terminalize without a Position;
  missing evidence stays provisional until the Entry deadline.
- Shadow allocation still computes exit and inverse-delivery stresses while admission and capacity
  use only nominal contractual-payoff sum. Therefore the recorded budget can say `AVAILABLE` even
  when its own declared stressed loss exhausts the Session limit.
- The complete repository gate passes: `190` tests and `7` deterministic business scenarios. This
  is offline implementation evidence, not current market or profitability evidence.

**Primary blocker:** `STRESS_RISK_NOT_RESERVED` — `ShadowRiskAllocation` records stress but does not
use one conservative stress amount for admission, aggregation, recovery, and release.

## Maturity ladder

- `A0_AUTHORITY_CORRECTION` — one owner per concept, explicit truth layers, and no cross-layer
  inference.
- `B1_WINDOW_OBSERVATION` — causal all-Window ObservationLedger and measured reachability.
- `B2_STRUCTURE_PRICING` — route-independent whole-four-leg discovery and inverse-unit economics.
- `B3_ATOMIC_PUBLIC_SHADOW` — complete whole-product Shadow Case, monitoring, terminality, and
  explanatory Outcome without fill claims.
- `C1_PRIVATE_READ_ONLY` — authenticated account truth with no order permission.
- `C2_AUTHORIZED_COMBO_EXECUTION` — separately authorized bounded Combo execution.
- `D1_OFFLINE_AI_CHALLENGER` — forward Outcomes support human-governed Challenger evaluation.

**Next closure:** a bounded `B3_STRESS_RISK_RESERVATION` task must replace nominal-only admission
with one explicit conservative stress metric used consistently by Decision, allocation record,
capacity reconstruction, recovery, and release. It may not change market thresholds, Entry
reunderwriting, runtime permissions, private facts, orders, capital, or Policy qualification.
