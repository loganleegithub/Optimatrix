# Optimatrix System Architecture

**Status:** ACTIVE ARCHITECTURE AUTHORITY

## One dependency path

Optimatrix is one Python modular monolith. The intended business path is:

```text
pre-registered DecisionWindow
→ causal MarketObservation and enrolled-Window DecisionRecord
→ optional OpportunityEpisode
→ selected TradeCase
→ TradeCase and Position journal
→ Window/Case/Position Outcome and read-only presentation
```

Lower-level facts and calculators do not depend on strategy composition or presentation. The engine
composes owners; it does not copy their formulas. Workbench renders validated projections and owns
no business calculation. Current source deviations and maturity belong to `CURRENT_STAGE.md`.

## Current module owners

```text
identity.py          content identities
products.py          inverse BTC product arithmetic
channels.py          fixed Channel descriptors
session.py           Deribit Session and phase classification
market.py            typed market facts, settlement facts, and evidence validation
deribit_snapshot.py  bounded public-response translation
deribit_websocket.py BTC-only public incremental cache, continuity, watermark, and REST resync
pricing.py           neutral depth projections plus fee, payoff, valuation, and settlement math
policy.py            fixed launch hypotheses and causal budgets
structure.py         BTC 0DTE whole-four-leg discovery and ranking
risk.py              BTC ShadowRiskAllocation
radar.py             BTC Window Decision evaluation
decision.py          DecisionWindow, MarketObservation, and DecisionRecord identities
observation_ledger.py Session coverage plus append-once enrolled DecisionRecord/WindowOutcome facts
lifecycle.py         atomic BTC Shadow TradeCase, Position, trigger, terminal, and Outcome rules
case_journal.py      append-only TradeCase snapshots and accepted-prefix recovery
engine.py            BTC 0DTE Short Vol path composition
runtime.py           one manifest-enrolled BTC public cross-Session scheduler and recovery owner
workbench.py         read-only display projection
cli.py               offline and explicitly authorized entrypoints
scenarios.py         deterministic evidence, not product Authority
ai_lab/              ended-Session adjudication, append-only research memory, and offline AI
```

Business definitions live in the two contracts, not this table. Exact Policy values and formulas
remain in their content-identified source owners.

## One time authority

All backend absolute business time is Deribit UTC. The daily Session is the half-open interval
anchored at `08:00 UTC`; its Session, Window, option-expiry, lifecycle, and settlement boundaries
are never selected from the host wall clock or a browser timezone. Deribit source timestamps state
when a market fact occurred. A distinct `known_at` states when that fact was causally available to
Optimatrix, but it is mapped into the same Deribit UTC clock domain from validated response timing.
Keeping those two meanings separate prevents look-ahead; it does not create a second business
clock. Public WebSocket notifications have no HTTP response envelope, so their receipt boundary is
the conservative latest value of that already validated and monotonically projected Deribit clock
at frame receipt. This projection does not turn local elapsed time into a market timestamp.

Elapsed request time, retry delay, and process sleep use a suspend-aware monotonic clock and are
never serialized as market facts. On the authorized macOS runtime that elapsed clock must continue
through host sleep so a wake cannot leave Deribit UTC frozen in an earlier Window or Session. Host
wall time is not an input to Session, Window, cadence, expiry, Decision, Entry, trigger, exit,
settlement, or Outcome truth. The Workbench receives canonical UTC values; the browser may convert
explicitly marked timestamps into the trader's local display timezone, but that presentation cannot
change an identity or backend calculation.

## Data health is not trading risk

`DataHealth` describes source completeness, freshness, continuity, coherence, and known-at status.
`TradingRisk` describes known market or Position exposure. Missing or unhealthy data produces
`UNKNOWN` or a Gap; it cannot synthesize a market-risk trigger, Entry, Position, close, or terminal
fact. Only the owning contract may define how a known risk fact changes a Decision or Position.

The production forward-observation owner is one BTC-specific in-memory public WebSocket cache.
Each option book verifies its own ordered change chain; cross-instrument notifications remain
asynchronous and become one immutable cut only when the BTC index and every requested book/ticker
pair share the current connection epoch and satisfy the Policy's source and receive watermarks. A
book snapshot remains the current depth state through silence while that verified chain and epoch
remain intact. The effective member watermark is the later boundary of the retained book/ticker
pair, so content-change time is not confused with continuity time; cross-instrument freshness and
span checks still apply to the index and every effective instrument member. For a scheduled Window,
the cache also waits until the source watermark reaches the Window start instead of consuming the
retained pre-Window cut; that wait remains bounded by the existing source timeout and Window input
grace. Disconnect or sequence loss is an exact Gap. A bounded REST book snapshot may seed recovery,
but the instrument cannot rejoin the incremental cut until a later matching WebSocket continuation
or new full snapshot proves continuity. HTTP remains the clock, Session metadata, the initial
index-history seed, at most one validated recovery seed per new connection epoch, official
settlement, and explicit resynchronization path; it is not the continuous Runtime market-cut path.
A recovered history seed remains transient and cannot make a cut ready without a strictly later
same-epoch WebSocket index continuation. A failed recovery invalidates its epoch and can be
attempted again only after capped backoff opens a new epoch. Transport Ping/Pong and the exchange
heartbeat jointly
detect a dead or silent socket; a task-bounded lack of valid inbound frames or desired market
notifications closes the current connection even when heartbeat responses, the process, proxy
socket, and Workbench remain alive. That deadline uses only
suspend-aware elapsed time, opens a new continuity epoch through capped reconnect backoff, and is
never a market timestamp. Connection-open, market-stream-resumed, recovery, and loss transitions
use the existing append-only runtime audit rather than a new durable owner. The cache creates no new
durable record owner.

## Record boundaries

`ObservationLedger` measures each scheduled Session denominator and appends the enrolled-Window
DecisionRecord defined by `../contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md` and WindowOutcome defined
by `../contracts/CASE_POSITION_OUTCOME.md` across successive Sessions; missing pre-enrollment
Windows remain Session-scoped coverage facts. It owns no order, trade, account, or TradeCase fact.
It is implemented and authorized only when `CURRENT_STAGE.md` says so.

`CaseJournal` begins only after a Candidate opens a TradeCase. It stores accepted immutable-prefix
snapshots of the TradeCase, later Entry truth, Position lifecycle, and Case/Position Outcome defined
by the same contract. A terminal snapshot is otherwise closed; the only post-terminal append is the
contract-owned official-settlement enrichment of an already pending early-exit hold counterfactual,
with all terminal economics and risk state unchanged. It cannot replace Session coverage or infer
missing Window evidence.
At B3 the active runtime task authorizes one exact manifest-enrolled stable root and one process-
exclusive continuous writer. The manifest freezes implementation and Policy identity plus the
Session, Window, and boundary of first enrollment; it does not bind the root forever to that
Session. The runtime rejects foreign members and cross-Policy records, but appends records created
by its own identity across successive Sessions. A new empty root enrolls the Session active at
process start and its current Window. At each later `08:00 UTC` boundary the same process activates
the new Session denominator in place, while accepted unresolved Cases from older Sessions remain in
the global CaseJournal and continue through monitoring, later whole-product valuation, or official
settlement. Restart preserves first-enrollment provenance, resumes the Session then active, and
never backfills a missed causal cut. A Window missed before runtime enrollment remains absent rather
than becoming a synthetic `UNKNOWN` record, and is not a reason to wait for another Session. Outside
that exact task boundary, caller-supplied disposable roots remain the only authorized record
location. On every online tick, due Decision and Case work precedes expired-Session analytics.
WindowOutcome construction consumes at most one append-once unit per tick and resumes from existing
Ledger facts after restart; a completed Session therefore cannot monopolize the current-Window
scheduler or require a queue, cursor file, or second worker.

The two records may reference the same immutable identities; neither copies, rewrites, or backfills
the other's truth. Raw capture is added only when an authorized replay consumer requires it. These
boundaries authorize no database, bus, schema registry, replay service, retention system, migration,
or dual-write protocol.

`AI Lab` is part of the same Python modular monolith but owns a separate read-only/offline path. It
may read a caller-selected completed Session from `ObservationLedger`, combine it with
content-sealed post-Session public evidence, derive content-sealed Policy-quality reviews, and write
only to its distinct Lab root. Its deterministic adjudicator compares immutable Base actions
Window by Window against the post-Session IV/RV, physical-path, cost, and settlement oracle;
terminal payoff is not a verdict. Missing Windows remain in the denominator and widen explicit
logical bounds without erasing complete Windows.

A separately authorized bounded command may fetch official historical public evidence after a
Session ends. The command must fix the production host and public-method allowlist, bind Deribit
response time, source method, requested range, raw points, cadence, coverage, and exact gaps, and
append only to the Lab root. It cannot write or repair an `ObservationLedger`, reconstruct a
decision-time option book, or turn hindsight into a causal Base Decision. Standard public APIs may
backfill index/RV, trade/mark, volatility-index, and delivery facts; only a previously captured
decision-time full-amount component book can support the ex-ante structure and cost side of a
Window classification. If official history lacks the required scope or cadence, the affected fact
stays `UNKNOWN`; a later exact task may authorize one indexed external raw-data source without
changing that evidence boundary.

The deterministic trader report is projected before an optional one-shot Codex CLI process
receives a bounded fact bundle. Codex may append only a separate schema-validated explanation and
cannot block or alter the Review. Superseded Policy-quality Reviews and retired terminal-positive
reviews remain in verified append-only history and are excluded from current verdict memory and
Challenger gates. The Lab never writes Ledger/Journal facts and has no continuous runtime, private
market-data, account, order, Policy-mutation, deployment, or promotion path.
