# Task — B3 Public Shadow Runtime closure

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** REQUIRED — one local Python process only

**Live commands:** `optimatrix-shadow runtime --event-state NONE --root "/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1" --workbench-port 8765`; one production Deribit Session from its `08:00 UTC` start through the following `08:00 UTC` settlement boundary, plus at most one bounded preflight before that Session; public methods only; no more than 32 option instruments per observation, depth 20, one Decision observation per 15-minute Window, one lifecycle observation per open Case per 60-second monitoring cadence, one settlement lookup after expiry, 10-second request timeout, at most three attempts with bounded backoff per observation boundary; every exhausted or invalid market input remains a recorded `UNKNOWN` or Gap and is never retried into an earlier causal boundary

**Owning authority/contract:** [`../docs/authority/SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md), [`../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`](../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md), and [`../docs/contracts/CASE_POSITION_OUTCOME.md`](../docs/contracts/CASE_POSITION_OUTCOME.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** commit `7e4c40414e9582b572ba891d767850947e00b6e6` passes the complete offline B1–B3 gate but has no continuous service, authorized public market population, stable record root, restart recovery, or continuously refreshed Workbench

**When:** one production Deribit Session is driven from its first pre-registered Window through expiry by one local process using the frozen Window and lifecycle cadences, including an observed restart recovery before the Session ends

**Then:** the stable root contains exactly one DecisionRecord for every Session Window, every opened TradeCase has a terminal accepted prefix after exit or official settlement, WindowOutcome coverage truthfully reports every Window, the Workbench continuously exposes current runtime, Window, market, Case, recovery, blocker, and population state, and the trader explicitly accepts that page before this task closes

**Affected identity and population:** all 96 `DecisionWindowId` values in the accepted Session and their causal `MarketObservationId` values; zero or one `TradeCaseId` per Candidate Window; every resulting `PositionId`; no `OpportunityEpisodeId`

**Baseline and denominator:** offline deterministic baseline `96/96` DecisionRecords and `96/96` WindowOutcomes; real production denominator `NOT_YET_MEASURED` until the runtime starts at an `08:00 UTC` Session boundary, after which it is exactly the 96 frozen Windows for that Session

**Primary blocker and expected delta:** `CONTINUOUS_PUBLIC_SHADOW_NOT_OBSERVED` becomes one trader-accepted, restart-recovered, complete real public Session without creating private-execution truth

**Known-at and DataHealth boundary:** each Window uses only a market cut observed inside that Window and known no later than its input deadline; lifecycle evidence must be strictly later where the contracts require it; Deribit source timestamps, local receive boundaries, universe completeness, continuity, freshness, and response environment are validated; timeout, source failure, parse failure, cadence miss, restart gap, or incomplete universe remains `UNKNOWN`/Gap and never becomes a Candidate, trigger, Entry, exit, or valid zero

## Effects and scope

**Risk allocation effect:** stable Public Shadow allocations use the existing `MAXIMUM_CONTRACTUAL_PAYOFF_USD_SUM`; restart reconstructs used amount and open-position count from same-Session accepted Journal prefixes; release occurs only at terminal no-Position Entry or terminal Position Outcome

**ObservationLedger / CaseJournal effect and consumer:** authorize one stable, exclusive runtime root at `/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1`; `ObservationLedger` stores all accepted DecisionRecords and WindowOutcomes, `CaseJournal` stores every accepted TradeCase prefix, and the runtime plus read-only Workbench are their only consumers; writes are append/atomic-replace with crash-tail recovery and no legacy import

**Legacy-data effect:** NONE — the runtime must refuse any root containing data not created by this implementation identity and never reads the preceding V2 root or historical Cases

**Permission effect:** authorize production Deribit public market-data methods only (`public/get_time`, `public/get_instruments`, `public/get_index_price`, `public/get_index_chart_data`, `public/get_order_book` or public aggregated book/ticker subscriptions, and `public/get_delivery_prices`) within the stated bounds; authorize the single stable root, one continuous local process, and loopback-only Workbench serving; private methods, credentials, accounts, orders, fills, capital, deployment, Policy promotion, and C1 remain forbidden

**Files and behavior in scope:** runtime orchestration and CLI; public Deribit response/environment and delivery translation; stable Ledger/Journal crash recovery and Case enumeration; same-Session Shadow-capacity reconstruction; WindowOutcome path accumulation; continuous read-only Workbench projection/loopback serving; direct tests; owning architecture, source index, package guidance, and final Stage snapshot

**Out of scope:** database, queue, message bus, microservice, generic strategy/runtime framework, WebSocket abstraction without a present need, private/authenticated call, credential handling, account truth, order lifecycle, execution, capital, deployment, Policy change or qualification, Edge/Alpha/profitability claim, legacy migration, missed-Window backfill, and automatic C1 activation

**Complexity added / deleted:** add one BTC-specific runtime owner, one durable-root manifest/lock, one loopback Workbench view, and the minimum recovery/path helpers consumed immediately by this closure; add no runtime dependency; delete any superseded one-shot presentation/runtime path or duplicate orchestration made obsolete by the accepted implementation

## Verification and closure

**Cheapest falsification:** focused fake-clock/fake-Deribit tests prove Window scheduling, request-failure `UNKNOWN`, lifecycle cadence, no duplicate Window, stable-root exclusivity, crash-tail recovery, restart of every unresolved Case, capacity reconstruction, official settlement, continuous Workbench refresh, and refusal of private methods or a foreign root; a causal append-only raw-Deribit market tape must also drive all 96 Window cuts and prove both complete four-leg paths — Candidate selection, frozen Shadow allocation, strictly later Entry and monitoring, public-market trigger, then either a still-later whole-product valuation or official settlement after a shallow-leg exit blocker — plus capacity freeze/recovery/release and trader-visible Case evidence

**Repository gate:** `make check`

**External evidence:** the exact authorized runtime command completes one production `08:00–08:00 UTC` Session with 96/96 DecisionRecords, truthful WindowOutcome coverage, no unresolved same-Session Case after settlement, an observed restart recovery, public-method audit only, and explicit trader acceptance of the loopback Workbench; until all facts exist this closure remains `UNVERIFIED`

Close only after directly observing the declared delta. Replace Stage with the post-task snapshot and remove this file; do not append completion history.
