# Task — B3 Public Shadow Runtime closure

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** REQUIRED — one local Python process only

**Live commands:** `optimatrix-shadow runtime --event-state NONE --root "/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1" --workbench-port 8765`; bind a new empty root to the Deribit Session active at process start, run one bounded public clock preflight immediately, and begin with the currently active 15-minute Window instead of waiting for the next `08:00 UTC` boundary; public methods only; no more than 32 option instruments per observation, depth 20, one Decision observation per encountered 15-minute Window, one lifecycle observation per open Case per 60-second monitoring cadence, one settlement lookup after expiry, 10-second request timeout, at most three attempts with bounded backoff per observation boundary; earlier same-Session Windows remain missing and are never backfilled as observations or synthetic `UNKNOWN` Decisions, and neither their count nor a complete 24-hour sample is a runtime or trader-acceptance prerequisite

**Owning authority/contract:** [`../docs/authority/SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md), [`../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`](../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md), and [`../docs/contracts/CASE_POSITION_OUTCOME.md`](../docs/contracts/CASE_POSITION_OUTCOME.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** commit `7e4c40414e9582b572ba891d767850947e00b6e6` passes the complete offline B1–B3 gate but has no continuous service, authorized public market population, stable record root, restart recovery, or continuously refreshed Workbench

**When:** one local process starts against the production Deribit Session that is already active, immediately captures its current Window, and then keeps driving each encountered Window and open Case at the frozen cadences

**Then:** the stable root contains records only for Windows actually encountered by the runtime, every opened TradeCase is continuously monitored and recoverable, the Workbench exposes current runtime, Window, market, Case, recovery, blocker, and population state, and the trader explicitly accepts that the page shows the system working on current public market data before this task closes

**Affected identity and population:** the 96 scheduled `DecisionWindowId` values still define the Session denominator, but only Windows encountered after runtime start may bind causal `MarketObservationId` values; zero or one `TradeCaseId` per live Candidate Window; every resulting `PositionId`; no `OpportunityEpisodeId`

**Baseline and denominator:** offline deterministic tests retain `96/96` DecisionRecords and `96/96` WindowOutcomes to falsify scheduling and lifecycle behavior. Production retains the 96 frozen Window identities for honest missingness measurement, but sample completeness, evaluable count, elapsed runtime, and presence of a naturally occurring Candidate are observations rather than acceptance gates

**Primary blocker and expected delta:** `CURRENT_PUBLIC_SHADOW_NOT_OBSERVED` becomes a trader-accepted current public market runtime without creating private-execution truth

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

**External evidence:** after the exact authorized runtime command starts, its audit contains only authorized public calls, at least one current Window has a real causal market cut and DecisionRecord, the loopback Workbench continuously shows that market and any resulting Case state, restart recovery remains available rather than being deliberately exercised as ceremony, and the trader explicitly accepts the page; no fixed wait, complete 24-hour sample, `96/96` count, naturally occurring Candidate, or forced restart is required

Close only after directly observing the declared delta. Replace Stage with the post-task snapshot and remove this file; do not append completion history.
