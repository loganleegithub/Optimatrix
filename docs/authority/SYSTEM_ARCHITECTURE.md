# Optimatrix System Architecture

**Status:** ACTIVE ARCHITECTURE AUTHORITY

## One dependency path

Optimatrix is one Python modular monolith. The intended business path is:

```text
pre-registered DecisionWindow
→ causal MarketObservation and all-Window DecisionRecord
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
observation_ledger.py append-once all-Window DecisionRecord and WindowOutcome populations
lifecycle.py         atomic BTC Shadow TradeCase, Position, trigger, terminal, and Outcome rules
case_journal.py      append-only TradeCase snapshots and accepted-prefix recovery
engine.py            BTC 0DTE Short Vol path composition
workbench.py         read-only display projection
cli.py               offline and explicitly authorized entrypoints
scenarios.py         deterministic evidence, not product Authority
```

Business definitions live in the two contracts, not this table. Exact Policy values and formulas
remain in their content-identified source owners.

## Data health is not trading risk

`DataHealth` describes source completeness, freshness, continuity, coherence, and known-at status.
`TradingRisk` describes known market or Position exposure. Missing or unhealthy data produces
`UNKNOWN` or a Gap; it cannot synthesize a market-risk trigger, Entry, Position, close, or terminal
fact. Only the owning contract may define how a known risk fact changes a Decision or Position.

## Record boundaries

`ObservationLedger` is the intended all-Window record. It stores the DecisionRecord defined by
`../contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md` and WindowOutcome defined by
`../contracts/CASE_POSITION_OUTCOME.md`; it owns no order, trade, account, or TradeCase fact. It is
implemented and authorized only when `CURRENT_STAGE.md` says so.

`CaseJournal` begins only after a Candidate opens a TradeCase. It stores accepted immutable-prefix
snapshots of the TradeCase, later Entry truth, Position lifecycle, and Case/Position Outcome defined
by the same contract. It cannot replace the all-Window population or infer missing Window evidence.
At B3 both records exist only under caller-supplied disposable roots; Stage authorizes no stable
root or continuous writer.

The two records may reference the same immutable identities; neither copies, rewrites, or backfills
the other's truth. Raw capture is added only when an authorized replay consumer requires it. These
boundaries authorize no database, bus, schema registry, replay service, retention system, migration,
or dual-write protocol.
