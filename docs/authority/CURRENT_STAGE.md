# Optimatrix Current Stage

**Status:** B3 WEBSOCKET FORWARD OBSERVATION — CLOSED

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
is retained without migration or mutation and remains ineligible for the current Policy.

**Continuous runtime:** `NONE`

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current implementation truth

- Entry reunderwriting requires later environment, exact frozen structure, economics, allocation,
  and route evidence to pass before a Shadow Position exists, and its complete Decision-to-Entry
  result remains recoverable.
- Policy schema 9 gives new MarketObservations, Decisions, route evidence, allocations, and Cases
  identities distinct from schema-8 and frozen v1 evidence without changing any Policy threshold or
  ranking rule.
- `ShadowRiskAllocation` records nominal contractual payoff, boundary-valued exit-cost stress,
  every inverse-delivery stress, their maximum delivery loss, and one conservative stress reserve.
  The reserve is exactly the maximum of nominal payoff, exit stress, and maximum delivery stress.
- The same reserve and metric own Decision admission, Session aggregation, the frozen allocation
  record, Case validation, restart reconstruction, and terminal release. Missing, malformed,
  identity-incoherent, or retired-metric allocation records fail closed rather than contributing an
  invented zero.
- The adversarial deterministic Candidate has `200 USD` nominal payoff and `402 USD` exit stress.
  With `300 USD` already reserved against the unchanged `600 USD` Session budget, it is rejected;
  the former nominal-only permissive branch is therefore absent.
- Every selected current-Policy Decision freezes one content-addressed route record, and every
  Entry freezes a distinct later record. Both bind the exact frozen `+1/-1/-1/+1` instruments,
  full target amount, causal cut, per-leg component depth, synthetic model, fee projection, and
  economics; Ledger, Journal, recovery, Outcome, and Workbench retain their identities.
- Route status distinguishes `EVALUABLE`, `NOT_EVALUABLE`, and `UNKNOWN` without inventing depth or
  whole-product economics. Only `EVALUABLE/COMPONENT_SYNTHETIC_ESTIMATE` can support a Shadow
  Position.
- B3 route constructors and strict codecs reject `COMBO_BOOK_QUOTE`, `RFQ`, and `ACTUAL_FILL`, plus
  every injected Combo-instrument, RFQ, order, trade, fill, account, executable-liquidity, and
  fill-probability field. A standard Combo fee projection remains only a cost-model fact.
- Every requested-but-unusable option book is retained as typed, content-addressed metadata with
  its instrument, product, expiry, strike, option type, and reason. A request failure is localizable
  only when the validated Deribit clock supplies its causal completion boundary; otherwise the
  bounded snapshot fails.
- Structure search evaluates every usable-book Candidate under the unchanged Policy. Missing books
  that cannot participate in any Policy-legal four-leg geometry do not block the observed Primary;
  if an unresolved Candidate could still change the rank, the Window is `UNKNOWN` with the exact
  missing book identities and cannot allocate risk.
- Source/receive span, freshness, continuity, required metadata, response timing, and instrument
  identity remain global causal DataHealth. The slow-unavailable-book fixture still fails globally
  on its original receive-span and stale boundaries.
- Every current-Policy Candidate Case owns one content-addressed Decision-to-Outcome explanation.
  It retains at most `20` representative market points while every accepted observation advances
  an exact count and monotonic evidence-bound landmarks for MFE/MAE, maximum short Delta, minimum
  distance to both short strikes, IV/RV range, and jump or directional extremes.
- Exact typed Gaps replace the former scalar flag and bind their causal source, known-at boundary,
  observation when one exists, Entry reunderwriting when applicable, and reason. `CaseJournal`
  rejects erased prefixes, non-monotonic extrema, and extrema not owned by the advancing cut.
- Final Entry freezes the status and later route evidence of every bounded Decision alternative.
  Evaluable alternatives use the same actual Entry and terminal cuts; unavailable alternatives
  preserve `UNKNOWN`, `NOT_EVALUABLE`, or `NOT_APPLICABLE` with an exact reason and are never
  reselected after the Decision.
- `ShadowCaseOutcomeV2` binds Decision and Entry metrics, path and Gap identities, standard Combo
  fee projections, MFE/MAE, Delta and short-strike breaches, alternative Outcomes, the primary
  terminal reason, an exact zero no-entry baseline, and a hold-to-expiry counterfactual. It makes
  no fill, slippage, account, executable-liquidity, real-Position, or realized-PnL claim.
- A strictly later whole-product Shadow exit remains economically terminal and releases its exact
  reserve immediately. Only the matching official settlement may append one hold-counterfactual
  enrichment; it cannot rewrite exit economics, primary reason, path, terminality, or risk state.
- Runtime root schema 3, `MarketObservationV3`, `TradeCaseSnapshotV3`,
  `ShadowExplanationPathV2`, and Workbench schema 7 reject prior source or explanatory shapes rather
  than migrating the frozen prior root. Workbench exposes market-source identity, Candidate-local
  readiness, the Decision-to-Outcome path, extrema, Gaps, alternatives, fees, and counterfactuals
  without inventing missing facts.
- The production Runtime source now composes every future market cut from one BTC-only
  unauthenticated public WebSocket cache over the BTC index and aggregated `100ms` option book and
  ticker channels. It no longer performs continuous HTTP index or component-book polling.
- Each option book validates its own `change_id` / `prev_change_id` chain. A cut is available only
  when every requested book/ticker pair and the index share one connection epoch and satisfy the
  unchanged source, receive, freshness, and cross-input bounds.
- Disconnect, incomplete initialization, staleness, and sequence loss fail through the exact
  Runtime Gap path. One affected-book REST snapshot may seed resynchronization, but that instrument
  rejoins only after a matching WebSocket continuation or a new full WebSocket snapshot.
- HTTP remains limited to clock preflight/re-anchor, Session instrument metadata, initial index-path
  recovery seed, official settlement, and explicit affected-book recovery fallback. The feed adds
  no durable store, database, bus, replay framework, private method, or authenticated `raw` channel.
- The complete repository gate passes: `221` tests and `8` deterministic business scenarios. This
  is offline implementation evidence, not current market, execution, or profitability evidence.
- Live runtime, stable-root writes, market calls, private facts, orders, and capital remain disabled.

**Primary blocker:** `NATURAL_FORWARD_CHAIN_UNVERIFIED` — the WebSocket path is deterministic and
offline-verified but has not yet been observed on a new isolated root across a naturally occurring
Candidate, later reunderwriting, Position, repeated monitoring, trigger, strictly later exit or
official settlement, and explanatory Outcome.

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

**Next closure:** a bounded `B3_NATURAL_FORWARD_CHAIN_ACCEPTANCE` task may authorize one new isolated
root and natural public observation. It must not lower thresholds to manufacture a Candidate,
reuse the frozen prior root, add private facts or orders, claim Edge, or expand into B4.
