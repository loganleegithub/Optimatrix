# Optimatrix Current Stage

**Status:** B3 RECONNECT INDEX HISTORY RECOVERY — ACTIVE

**Current maturity:** `B3_ATOMIC_PUBLIC_SHADOW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `IMPLEMENTATION`

**Sole authorized closure:** [`B3_RECONNECT_INDEX_HISTORY_RECOVERY`](../../tasks/B3_RECONNECT_INDEX_HISTORY_RECOVERY.md)

## Current permissions

Stage is the permission ceiling; a future active task may only narrow it.

**Offline checks and simulation:** deterministic reconnect, history-reseed, causal-boundary, and
runtime-recovery tests for the exact active task are authorized under caller-supplied ignored roots;
synthetic market evidence, simulated Policy Outcomes, and durable review artifacts are forbidden

**Public market calls:** only unauthenticated production `wss://www.deribit.com/ws/api/v2` public
heartbeat, subscribe, unsubscribe, test, BTC index, and aggregated `100ms` BTC option book/ticker
channels, plus `https://www.deribit.com/api/v2` public clock, instrument metadata, initial and at
most one reconnect index-history recovery seed per new WebSocket connection epoch, affected-book
resync, and official settlement calls made only by the launchd runtime identified below

**Stable ObservationLedger root:** only
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`

**Disposable offline ObservationLedger:** authorized only under caller-supplied ignored roots

**Stable CaseJournal root:** only
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`

**Frozen prior evidence:** `/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1`
is retained without migration or mutation and remains ineligible for the current Policy.

**Continuous runtime:** only launchd label `com.optimatrix.b3-public-shadow`, executing the
`origin/main` console script from `/Users/logan/Optimatrix`, with EventState `NONE`, Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, the exact v2 root,
loopback Workbench port `8765`, and no duration expansion into another process or root; after the
active task's full repository gate, this exact job may be replaced once by the verified reconnect
recovery implementation

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** the exact already deployed local launchd public Shadow job is
deployed and may remain under `KeepAlive`. Any other local or remote deployment, orders, fills,
capital, and private access remain `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current evidence state

- `B3_PIPELINE_CAPABILITY_ACCEPTED`: production-shaped deterministic scenarios cover Candidate,
  later Entry reunderwriting, Shadow Position, repeated monitoring, trigger, strictly later exit or
  settlement, explanatory Outcome, restart recovery, Ledger/Journal ownership, and Workbench;
  live public v2 evidence separately proves healthy cuts, causal `UNKNOWN`, truthful `ABSTAIN`,
  stable-root recovery, and a healthy loopback surface without manufacturing a Candidate.
- `natural_chain=NOT_YET_OBSERVED`: v2 contains no causally complete natural
  Candidate-to-Outcome chain. This remains stronger evidence to collect, not a capability failure.
- `completed_session_review=ADJUDICATED`: Session
  `2026-08-14T08:00:00Z/2026-08-15T08:00:00Z` has `96` pre-registered calendar Windows, `15`
  contiguous pre-enrollment absences, `81/81` enrolled DecisionRecords, and `81/81` matching
  WindowOutcomes. Results are `64 ABSTAIN` and `17 UNKNOWN`; phase counts are `69 CORE_CARRY`,
  `6 LATE_THETA`, `4 EXIT_ONLY`, and `2 DELIVERY_TWAP`. No Candidate, TradeCase, or Position exists.
- `policy_reachability=COMPLETED_SESSION_LOCAL_RESPONSIBILITY_MEASURED`: `64` records bind healthy
  observations and none binds an unhealthy observation; `17` have no bound observation, comprising
  `15 NO_OBSERVATION` and `2 OBSERVATION_OUTSIDE_WINDOW`. Of the healthy population, `16` pass the
  environment layer. Across all `64` healthy Windows, `19` contain `1,200` price-evaluable
  structures and none is Policy-eligible, including every structure behind an environment blocker.
  Within the environment-pass population, `9` Windows contain the same `755` price-evaluable
  structures and `7` have no legal structure.
- `environment_frontier=ONE_SESSION_ONLY`: `43/64` healthy Windows fail only the VRP proxy gate;
  the remaining five environment-blocked Windows are already closed to new Entry, three with
  additional jump or persistence blockers. Removing any one environment gate exposes no
  Policy-eligible structure. This measures responsibility, not the gate's risk value.
- `credit_to_payoff_distribution=MEASURED_LOCAL_SAMPLE`: among the `755` environment-pass
  structures, nearest-rank median is `1.155678540625%`, p95 is `3.145764%`, p99 is
  `4.96479909375%`, and maximum is `9.851412375%`. Removing only `$10` admits `2` structures and
  removing only `7%` admits `5`; all seven occur in the single `2026-08-14T15:00:00Z` Window.
- `filter_forward_value=FIXED_WINDOW_PATH_OBSERVED`: all `9/9` frozen audit Windows now have known,
  continuous actual paths and official settlement. The sole `7%`-only affected Window's path did
  not breach its `62000` short Put, but reached `63172.323833`, breaching its shared `63000` short
  Call by `172.323833 USD`; official delivery was `63013.74`. This is path-risk evidence, not a
  counterfactual Entry, executable route, PnL, Policy qualification, or reason to change `7%`.
- `window_outcome_population=PATH_COMPLETE_NOT_INDEPENDENT_TRADES`: all `81` enrolled Windows have
  a known continuous public path and official delivery `63013.74`; `64` Decisions are evaluable,
  all `81` path populations are eligible, and zero is execution-attributable or Policy-qualified.
  Their overlapping horizons are Window facts, not `81` independent trades or PnL observations.
- `runtime_continuity=RECONNECT_GAP_AMPLIFICATION_OBSERVED`: after the deployed Window-watermark
  correction, `61/69` Decisions were evaluable. One `04:30 UTC` WebSocket disconnect directly
  failed its Window and left a material gap in the retained index history that failed five more
  consecutive Windows through `05:45 UTC`; the cache only seeds index history at initial startup.
  The disconnected Window remains correctly `UNKNOWN`, but later Windows lack one bounded
  reconnect reseed that could restore causal history without backfilling Decisions.
- `workbench_projection=CURRENT_SESSION_TRUTHFUL`: loopback Workbench renders the active Session's
  current counts, Gap state, evidence boundary, public-Shadow disclaimer, and no fabricated
  Challenger results without console errors. It has no completed-Session selector, so the prior
  Session review remains a Ledger audit; adding historical UI is not the current trading blocker.
- `policy_qualification=NONE` and `edge_claim=NONE`: deterministic scenarios, a local ablation,
  Candidate frequency, one Session, and natural-chain occurrence cannot qualify the Policy.

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
- An initialized book retains its depth through notification silence while its connection epoch and
  verified change chain remain intact. Each option contributes the later book/ticker source and
  receive boundary to cross-instrument freshness and span checks; a last content-change timestamp is
  not itself a continuity failure.
- A scheduled Window may consume its one public cut only after the source watermark reaches that
  Window's start. The existing bounded cache wait owns this lower boundary; retained pre-Window
  state cannot consume the attempt while the input grace remains available.
- Merge `a3ba716` deployed that correction under launchd from `/Users/logan/Optimatrix` onto v2.
  The job exclusively acquired the v2 lock, served loopback HTTP `200`, and appended complete public
  cut `sha256:a6b09ceaa75803d689fda2169319cc5b493df6c042ee9ccfb19a16453ff4b897` at
  `2026-08-14T14:45:07.048000Z` without a startup error. The interrupted startup Window still failed
  closed as `UNKNOWN/NO_OBSERVATION`; this is deployment evidence, not chain acceptance.
- Disconnect, incomplete initialization, staleness, and sequence loss fail through the exact
  Runtime Gap path. One affected-book REST snapshot may seed resynchronization, but that instrument
  rejoins only after a matching WebSocket continuation or a new full WebSocket snapshot.
- HTTP remains limited to clock preflight/re-anchor, Session instrument metadata, initial index-path
  recovery seed, official settlement, and explicit affected-book recovery fallback. The feed adds
  no durable store, database, bus, replay framework, private method, or authenticated `raw` channel.
- The complete repository gate passes: `226` tests and `8` deterministic business scenarios. This
  is offline implementation evidence, not current market, execution, or profitability evidence.
- Outside the exact active-task command, live runtime, stable-root writes, and market calls remain
  disabled. Private facts, orders, capital, and any other local or remote deployment remain
  unconditionally disabled.

**Primary blocker:** `RECONNECT_INDEX_HISTORY_GAP_AMPLIFICATION` — the current feed correctly fails
closed on disconnect, but one missing WebSocket interval remains inside the matched risk horizon and
turns one transport interruption into multiple later `UNKNOWN` Windows. The active task may add one
bounded public index-history reseed per new connection epoch and require a later same-epoch
WebSocket continuation before readiness. It may not backfill a Decision, poll REST continuously,
change `7%`, `$10`, sizing, Policy identity, durable schema, or truth semantics.

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

**Active closure boundary:** implement only reconnect index-history recovery for the exact public
feed: at most one validated historical BTC index seed per new WebSocket connection epoch, followed
by a strictly later same-epoch WebSocket index continuation before a cut can become ready. Preserve
the disconnected Window as `UNKNOWN`, all Decision identities, the Policy, root, feed universe,
component route semantics, and fail-closed behavior. Continuous polling, Decision backfill, generic
replay, durable history infrastructure, private facts, orders, v1 reuse, threshold or sizing
changes, Policy qualification, Edge claims, remote deployment, and B4 remain forbidden.
