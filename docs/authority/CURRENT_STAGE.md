# Optimatrix Current Stage

**Status:** C1 MAINNET REQUEST-SCOPED READ CONNECTIVITY — ACTIVE

**Current maturity:** `B3_ATOMIC_PUBLIC_SHADOW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `IMPLEMENTATION`

**Sole authorized closure:** [`C1_MAINNET_REQUEST_SCOPED_AUTH`](../../tasks/C1_MAINNET_REQUEST_SCOPED_AUTH.md)

## Current permissions

Stage is the permission ceiling; a future active task may only narrow it.

**Offline checks and simulation:** the active task may change only C1 mainnet auth acceptance,
credential/token-scope truth labels, its direct owner text, isolated Workbench projection, and fake
tests. The fixed mainnet host, requested scope, three-method allowlist, credential reader, Public
Shadow, Policy, and every deployed runtime remain frozen.

**Public market calls:** the active implementation task grants no new public market call. Existing
ignored public snapshots may be read only by offline tests until the standard gate cleans them.
Otherwise only unauthenticated production
`wss://www.deribit.com/ws/api/v2` public
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
loopback Workbench port `8765`, and no duration expansion into another process or root; natural
WebSocket reconnects and launchd `KeepAlive` may preserve this exact job, but no manual restart,
replacement, new root, or other process is authorized

**Private read-only account permission:** `NONE` during implementation. No mainnet or testnet
authentication, account call, Positions call, Chrome action, credential read, or secret persistence
is authorized. The task removes only the local response-scope gate; it may not add a private method.

**Orders, capital, and deployment:** mainnet execution remains permanently `NONE`. Fake tests may
inject forbidden method names only to prove rejection. Every live order, fill, trade lookup, cancel,
Position mutation, capital action, restart, replacement, new process, root, and deployment remains
`NONE`.

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
- `reconnect_recovery_capability=DEPLOYED_AND_INITIAL_CUT_ACCEPTED`: commit `9969af3` adds one
  epoch-scoped index-history recovery attempt, rejects malformed, discontinuous, late, or repeated
  seeds, and requires a strictly later same-epoch WebSocket index continuation. It passed `228`
  tests and `8` scenarios, was pushed to `origin/main`, and was deployed once as PID `51093`.
  Loopback returned HTTP `200`; observation
  `sha256:ba830878949ef8930642b93ebba52b91cdce5643e209d8fc716931a5145283d2` completed at
  `2026-08-15T11:00:19.612000Z` with source
  `DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1`, `21` quotes, and one continuity epoch.
- `natural_reconnect_recovery=NOT_YET_OBSERVED`: the accepted post-deployment cut belongs to the
  new process's initial WebSocket epoch, so it proves startup and market-cut health but not the
  natural reconnect transition. The declared post-deployment population contains exactly `84`
  scheduled Windows from `2026-08-15T11:00:00Z` through Session end, but its completed reliability
  reconciliation is `UNVERIFIED`. The validation was ended by the explicit product decision to
  begin C1; it was not accepted, backfilled, or converted into a C1 gate.
- `workbench_projection=CURRENT_SESSION_TRUTHFUL`: loopback Workbench renders the active Session's
  current counts, Gap state, evidence boundary, public-Shadow disclaimer, and no fabricated
  Challenger results without console errors. It has no completed-Session selector, so the prior
  Session review remains a Ledger audit; adding historical UI is not the current trading blocker.
- `policy_qualification=NONE` and `edge_claim=NONE`: deterministic scenarios, a local ablation,
  Candidate frequency, one Session, and natural-chain occurrence cannot qualify the Policy.
- `c1_private_account_capability=IMPLEMENTED_OFFLINE_REQUEST_SCOPED_PENDING_GATE`: the fixed
  mainnet host and method surface contains exactly `public/auth`, BTC summary, and BTC Positions.
  Auth requests exactly `account:read trade:read`; auth-response scope text is neither an
  authorization gate nor an Observation field. Observation, CLI, and Workbench schema 9 separate
  `MAINNET`, `PRIVATE_EXECUTION`, `CREDENTIAL_SCOPE=USER_DECLARED_READ_ONLY`,
  `TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE`,
  `APPLICATION_METHOD_PERMISSION=READ_ONLY_FIXED_ALLOWLIST`, and `ORDERS_EXECUTED=NONE`, without
  storing credential, token, or raw scope material. The two failed testnet C1 auth guards remain
  historical evidence; testnet execution belongs only to a later explicit C2 task.
- `c1_initial_testnet_canary=FAIL_CLOSED_ACCEPTED`: the one authorized public snapshot completed
  with EventState `NONE`, `21/21` books, complete Candidate data readiness, and `NO_STRUCTURE`
  without Ledger recording. The existing user-declared `read_write` testnet key then authenticated
  only far enough to return an effective scope outside the C1 functional allowlist. The observation
  closed `UNKNOWN` with `AUTH_SCOPE_EXCEEDS_C1`; summary and Positions remained `UNKNOWN`, and zero
  private methods were called. This proves the key was not misused and is not a C1 capability
  failure.
- `c1_read_only_credential_remediation=SUPERSEDED_BEFORE_SIDE_EFFECT`: the testnet API-management
  page was inspected and the new-key form opened, then the explicit product decision removed the
  need for a separate testnet read-only key. The unsaved form was cancelled; no key was created,
  changed, deleted, copied, or used. Testnet credential capability and the application's method
  permission must now be represented as separate truths.
- `c1_environment_specific_canary_attempt=FAIL_CLOSED_NEEDS_OPEN_TOKEN_POLICY`: the exact prior
  public snapshot was rehydrated with its recorded SHA-256 and no new market call. One no-retry
  testnet auth then returned at least one scope token outside the implementation's fixed functional
  enumeration. The observation closed `UNKNOWN/AUTH_SCOPE_EXCEEDS_C1`; summary and Positions were
  both uncalled and remained `UNKNOWN`. Validation artifacts contain neither injected credential
  value. This is a remaining testnet token-policy mismatch, not permission to guess the token or
  broaden the method allowlist.
- `c1_open_scope_canary_attempt=FAIL_CLOSED_NEEDS_SELECTIVE_RECOGNITION`: the exact prior public
  snapshot was rehydrated again with matching SHA-256 and no new market call. One no-retry testnet
  auth returned `AUTH_SCOPE_UNKNOWN`; the observation is `TESTNET/UNKNOWN`, summary and Positions
  were both uncalled and remain `UNKNOWN`, and mainnet was not attempted. The five ignored
  validation artifacts contain neither selected credential value. The irrelevant raw token was not
  printed, persisted, or enumerated.
- `c1_mainnet_read_only_canary=FAIL_CLOSED_AUTH_SCOPE_UNKNOWN`: the explicit owner-only machine
  credential file passed its file contract and selected only mainnet fields. One no-retry mainnet
  auth returned `AUTH_SCOPE_UNKNOWN`; the observation is `MAINNET/UNKNOWN`, summary and Positions
  were both uncalled and remain `UNKNOWN`, and `ORDERS_EXECUTED=NONE`. The four ignored Workbench
  artifacts contain neither selected credential value. C1 mainnet connectivity remains
  `UNVERIFIED`; this does not authorize another scope-parser iteration inside C2.
- `c1_live_private_account=UNVERIFIED`: neither environment has a known private account observation.
  Mainnet remains strictly read-only and its response chain is unverified. Both failed testnet C1
  auth guards are retained as evidence but are not a C2 product gate. No C1 account value or Position
  fact has been accepted.
- `c2_testnet_combo_execution=DEFERRED_UNSTARTED`: the briefly activated C2 implementation task was
  superseded before any source, test, manifest, owner, or live change. No testnet order, trade, fill,
  fee, Position mutation, or cancel has occurred. C2 waits for the explicit C1 mainnet connectivity
  closure.

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
  `ShadowExplanationPathV2`, and Workbench schema 9 reject prior source or explanatory shapes rather
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
- Commit `9969af3` is deployed under the exact launchd job from `/Users/logan/Optimatrix` onto v2.
  The one authorized replacement changed PID `22801` to `51093`, retained the exact command, root,
  Policy, EventState, and port, served HTTP `200`, and produced the healthy `11:00 UTC` public cut.
  The interrupted `10:45 UTC` Window remained a causal restart Gap; no Decision was backfilled.
- Disconnect, incomplete initialization, staleness, and sequence loss fail through the exact
  Runtime Gap path. One affected-book REST snapshot may seed resynchronization, but that instrument
  rejoins only after a matching WebSocket continuation or a new full WebSocket snapshot.
- Each WebSocket epoch after the first attempts at most one validated two-day BTC index-history
  recovery. A seed alone is not ready: a strictly later same-epoch WebSocket index plus current
  same-epoch books and tickers remains mandatory. Failure stays a typed Gap with no within-epoch
  retry, polling loop, durable history, or Decision backfill.
- HTTP remains limited to clock preflight/re-anchor, Session instrument metadata, initial and
  epoch-bounded reconnect index-path recovery seeds, official settlement, and explicit affected-book
  recovery fallback. The feed adds no durable store, database, bus, replay framework, private
  method, or authenticated `raw` channel.
- The complete repository gate passes: `267` tests and `8` deterministic business scenarios. This
  is offline implementation evidence, not current market, execution, or profitability evidence.
- The active task is C1 implementation-only. It may delete the response-scope parser as a mainnet
  read gate, retain the fixed auth request `account:read trade:read`, and project only
  `CREDENTIAL_SCOPE=USER_DECLARED_READ_ONLY` plus
  `TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE`. No credential read or live call is authorized.

**Primary blocker:** `C1_MAINNET_RESPONSE_SCOPE_IS_FALSE_PRODUCT_GATE` — three live auth responses
have been blocked locally before summary and Positions because the client attempts to normalize an
exchange scope string that neither grants nor expands application methods. Safety already belongs
to the user-declared read-only mainnet credential, the exact requested read scope, and a closed
three-method allowlist. B3 reliability and the natural chain remain separately `UNVERIFIED`.

## Maturity ladder

- `A0_AUTHORITY_CORRECTION` — one owner per concept, explicit truth layers, and no cross-layer
  inference.
- `B1_WINDOW_OBSERVATION` — causal all-Window ObservationLedger and measured reachability.
- `B2_STRUCTURE_PRICING` — route-independent whole-four-leg discovery and inverse-unit economics.
- `B3_ATOMIC_PUBLIC_SHADOW` — complete whole-product Shadow Case, monitoring, terminality, and
  explanatory Outcome without fill claims.
- `C1_PRIVATE_READ_ONLY` — authenticated mainnet account truth through a fixed read-method
  application boundary and a user-declared read-only machine credential contract.
- `C2_AUTHORIZED_COMBO_EXECUTION` — separately authorized bounded Combo execution.
- `D1_OFFLINE_AI_CHALLENGER` — forward Outcomes support human-governed Challenger evaluation.

**Active closure boundary:** remove response-scope normalization and persistence from the C1 mainnet
read path while retaining the exact request scope, host, currency, parameters, and three methods.
Project the credential permission basis and unavailable token normalization truthfully. Live
credentials, Chrome, key mutation, mainnet execution, testnet, real capital, B3 runtime/root access,
Candidate manufacture, Policy, D1, Edge claims, and deployment remain forbidden.
