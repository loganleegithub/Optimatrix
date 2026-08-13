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
clock.

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

## Record boundaries

`ObservationLedger` measures each scheduled Session denominator and appends the enrolled-Window
DecisionRecord defined by `../contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md` and WindowOutcome defined
by `../contracts/CASE_POSITION_OUTCOME.md` across successive Sessions; missing pre-enrollment
Windows remain Session-scoped coverage facts. It owns no order, trade, account, or TradeCase fact.
It is implemented and authorized only when `CURRENT_STAGE.md` says so.

`CaseJournal` begins only after a Candidate opens a TradeCase. It stores accepted immutable-prefix
snapshots of the TradeCase, later Entry truth, Position lifecycle, and Case/Position Outcome defined
by the same contract. It cannot replace Session coverage or infer missing Window evidence.
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
location.

The two records may reference the same immutable identities; neither copies, rewrites, or backfills
the other's truth. Raw capture is added only when an authorized replay consumer requires it. These
boundaries authorize no database, bus, schema registry, replay service, retention system, migration,
or dual-write protocol.
