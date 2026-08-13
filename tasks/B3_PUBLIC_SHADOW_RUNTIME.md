# Task — B3 Public Shadow Runtime closure

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** REQUIRED — one local Python process only

**Live commands:** `optimatrix-shadow runtime --event-state NONE --root "/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1" --workbench-port 8765`; on a new empty root, preserve immutable provenance for the Session, current Window, and boundary first encountered at process start, run one bounded public clock preflight immediately, and begin with that current 15-minute Window instead of waiting for the next `08:00 UTC` boundary; at every later `08:00 UTC` boundary roll to the new Session inside the same process, with the same stable root and Workbench, while continuing every unresolved older Case through exit valuation or official settlement; public methods only; no more than 32 option instruments per observation, depth 20, one Decision observation per encountered 15-minute Window, one lifecycle observation per open Case per 60-second monitoring cadence, one settlement lookup after expiry, 10-second request timeout, at most three attempts with bounded backoff per observation boundary; Windows before runtime enrollment in an encountered Session remain missing and are never backfilled as observations or synthetic `UNKNOWN` Decisions, and neither their count nor a complete 24-hour sample is a runtime or trader-acceptance prerequisite

**Owning authority/contract:** [`../docs/authority/SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md), [`../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`](../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md), and [`../docs/contracts/CASE_POSITION_OUTCOME.md`](../docs/contracts/CASE_POSITION_OUTCOME.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** commit `7e4c40414e9582b572ba891d767850947e00b6e6` passes the complete offline B1–B3 gate but has no continuous service, authorized public market population, stable record root, restart recovery, or continuously refreshed Workbench

**When:** one local process starts against the production Deribit Session already active, immediately captures its current Window, keeps driving each encountered Window and open Case at the frozen cadences, and rolls each later `08:00 UTC` Session boundary in place without rotating the process, root, or Workbench

**Then:** the stable root is one append history of Session-scoped Ledger records and all accepted Case prefixes; it contains Decision records only for Windows actually encountered by the runtime, continues every unresolved older Case across Session rollover until later valuation or settlement terminality, keeps every opened TradeCase recoverable, exposes current runtime, Session, Window, market, Case, recovery, blocker, and population state in one Workbench, and the trader explicitly accepts that the page shows the system working on current public market data before this task closes

**Affected identity and population:** each encountered Session retains its own 96 scheduled `DecisionWindowId` denominator, but only Windows encountered after that Session's runtime enrollment may bind causal `MarketObservationId` values; zero or one `TradeCaseId` per live Candidate Window; every resulting `PositionId`, including unresolved Cases carried across a later Session boundary; no `OpportunityEpisodeId`

**Baseline and denominator:** offline deterministic tests retain `96/96` DecisionRecords and `96/96` WindowOutcomes to falsify one full Session's scheduling and lifecycle behavior. Each production Session retains its 96 frozen Window identities for honest missingness measurement, but `96/96`, sample completeness, evaluable count, elapsed runtime, uninterrupted 24-hour operation, and presence of a naturally occurring Candidate are observations rather than runtime-start or trader-acceptance gates

**Primary blocker and expected delta:** `CURRENT_PUBLIC_SHADOW_NOT_OBSERVED` becomes a trader-accepted current public market runtime without creating private-execution truth

**Policy correction boundary:** the current B3 numeric Policy is provisional. This task may change
an environment, structure, underwriting, Shadow-risk, Entry, monitoring, or exit value only when
primary-source mechanism evidence or a causal public-market replay demonstrates a concrete
incoherence or unsafe boundary. The change must state the rejected assumption, preserve immutable
Policy identity on prior records, compare the same tape before and after, and must not optimize for a
desired Candidate count, Outcome, hit rate, PnL, or promotion claim.

**Event-state evidence boundary:** the authorized production command pins `event_state=NONE` and
has no live calendar or human update source. Jump, realized-variance, and directional public-market
proxies remain active, but event blockers must not be reported as an operating live control during
this task. Connecting or defining a live event source requires a separately owned input and Policy.

**Time, known-at, and DataHealth boundary:** Deribit UTC is the sole backend absolute business-time authority, with each Session anchored at `08:00 UTC`; the process must establish that clock from `public/get_time` before creating or mutating the stable root and refresh it from validated JSON-RPC timing. Host wall time never selects a Session, Window, cadence, expiry, settlement, Decision, Entry, trigger, exit, or Outcome. Monotonic time measures only RTT, retry, and sleep durations, and the authorized macOS elapsed clock must continue across host sleep so wake cannot freeze the runtime in an earlier Deribit Window. Each Window uses only a market cut whose Deribit source boundary is inside that Window and whose distinct causal `known_at`, mapped into the same Deribit UTC domain, is no later than its input deadline; the complete cut covers index, instruments, history, and every required book response. Lifecycle evidence must be strictly later where the contracts require it. Clock uncertainty crossing a Window or `08:00 UTC` boundary, timeout, source failure, parse failure, cadence miss, restart gap, or incomplete universe remains `UNKNOWN`/Gap and never becomes a Candidate, trigger, Entry, exit, or valid zero. The backend exports UTC facts; only the browser converts marked timestamps for local display.

## Effects and scope

**Risk allocation effect:** stable Public Shadow allocations use the existing `MAXIMUM_CONTRACTUAL_PAYOFF_USD_SUM`; startup, restart, and rollover reconstruct the active Session's used amount and open-position count from its accepted Journal prefixes, while unresolved prior-Session Cases remain recoverable and monitored without being charged to the new Session's allocation denominator; release of each frozen allocation occurs only at terminal no-Position Entry or terminal Position Outcome

**ObservationLedger / CaseJournal effect and consumer:** authorize one stable, process-exclusive runtime root at `/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1`; its manifest freezes implementation and Policy identity plus immutable first-enrollment Session/Window/boundary provenance, not one permanent active Session; `ObservationLedger` appends Session-scoped DecisionRecords, each valid-input record retaining its complete immutable causal MarketObservation for same-tape replay, and WindowOutcomes across successive Sessions; `CaseJournal` appends every accepted TradeCase prefix across those Sessions; the runtime plus read-only Workbench are their only consumers; writes are append/atomic-replace with crash-tail recovery and no legacy import

**Legacy-data effect:** NONE — the runtime must refuse any root containing data not created by this implementation identity and never reads the preceding V2 root or historical Cases; records from an earlier Session created by this same manifest identity are current root history, not legacy data

**Permission effect:** authorize production Deribit public market-data methods only (`public/get_time`, `public/get_instruments`, `public/get_index_price`, `public/get_index_chart_data`, `public/get_order_book` or public aggregated book/ticker subscriptions, and `public/get_delivery_prices`) within the stated bounds; authorize the single stable root, one continuous local process, loopback-only Workbench serving, and only the evidence-bound B3 numeric corrections defined above; private methods, credentials, accounts, orders, fills, capital, deployment, Policy qualification or promotion, and C1 remain forbidden

**Files and behavior in scope:** runtime orchestration and CLI; public Deribit response/environment and delivery translation; the current BTC B3 Policy only under the correction boundary above; immutable first-enrollment provenance; in-process `08:00 UTC` Session rollover; stable cross-Session Ledger/Journal append, crash recovery, and Case enumeration; active-Session Shadow-capacity reconstruction; prior-Session Case monitoring and settlement; WindowOutcome path accumulation; continuous read-only Workbench projection/loopback serving; direct tests; owning architecture, source index, package guidance, and final Stage snapshot

**Out of scope:** database, queue, message bus, microservice, generic strategy/runtime framework, WebSocket abstraction without a present need, private/authenticated call, credential handling, account truth, order lifecycle, execution, capital, deployment, parameter optimization, Policy qualification or promotion, Edge/Alpha/profitability claim, legacy migration, missed-Window backfill, and automatic C1 activation

**Complexity added / deleted:** add one BTC-specific cross-Session runtime owner, one durable-root manifest/lock with immutable first-enrollment provenance, one loopback Workbench view, and the minimum rollover/recovery/path helpers consumed immediately by this closure; add no runtime dependency; delete any superseded one-shot presentation/runtime path or duplicate orchestration made obsolete by the accepted implementation

## Verification and closure

**Cheapest falsification:** focused fake-clock/fake-Deribit tests prove that host wall-clock offsets and jumps cannot change Session or Window ownership, `07:59:59.999` and `08:00:00.000 UTC` roll exactly once from validated Deribit time, an uncertain clock interval crossing a business boundary fails closed, response receipt after a deadline cannot be used, every process restart establishes Deribit time before touching the stable root, Window scheduling, request-failure `UNKNOWN`, lifecycle cadence, deterministic latest-exit responsibility despite unusable prices, no duplicate Window, stable-root exclusivity, crash-tail recovery, restart of every unresolved Case, active-Session capacity reconstruction, append of the next Session without changing first-enrollment provenance, continued monitoring and official settlement of an older Case after rollover, browser-local rendering without identity mutation, continuous Workbench refresh, and refusal of private methods or a foreign root; each valid-input DecisionRecord must round-trip its exact MarketObservation and reproduce its Base assessment from the same causal input; a causal append-only raw-Deribit market tape must also drive all 96 Window cuts and prove both complete four-leg paths — Candidate selection, frozen Shadow allocation, strictly later Entry and monitoring, public-market trigger, then either a still-later whole-product valuation or official settlement after a shallow-leg exit blocker — plus capacity freeze/recovery/release and trader-visible Case evidence

**Repository gate:** `make check`

**External evidence:** after the exact authorized runtime command starts, its audit contains only authorized public calls, at least one current Window has a real causal market cut and DecisionRecord, the loopback Workbench continuously shows that market and any resulting Case state, and the trader explicitly accepts the page; tested rollover and restart recovery remain available rather than requiring a live boundary wait or deliberately forced ceremony, so no fixed wait, complete 24-hour sample, `96/96` count, naturally occurring Candidate, live `08:00 UTC` observation, or forced restart is required

Close only after directly observing the declared delta. Replace Stage with the post-task snapshot and remove this file; do not append completion history.
