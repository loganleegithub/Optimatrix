# Optimatrix System Architecture

**Status:** ACTIVE ARCHITECTURE AUTHORITY

## Shape and dependency direction

Optimatrix is one Python modular monolith. Data moves through one causal path:

```text
bounded typed market facts
→ product, Session, pricing, and risk calculators
→ joint structure selection and one Decision
→ product funnel
→ Decision Case and Position lifecycle
→ journal recovery and read-only presentation
```

Lower-level facts and calculators do not depend on strategy composition or presentation. The engine
composes existing owners; it does not reimplement their formulas. Workbench renders validated
objects and owns no business calculation.

## Module owners

```text
identity.py          canonical content identities
products.py          inverse BTC product arithmetic
channels.py          fixed Channel descriptors and implemented flag
session.py           Deribit Session identity and phase classification
market.py            typed market facts, evidence, and source validation
deribit_snapshot.py  one bounded public-response translator
pricing.py           depth, tick, fee, Vertical, payoff, valuation, settlement math
policy.py            fixed BTC Short Vol thresholds and causal budgets
structure.py         bounded joint Put/Call structure generation and selection
radar.py             one Decision evaluation and blocker vector
product_funnel.py    SessionDecisionUnit stages, denominators, and earliest blocker
lifecycle.py         Entry classification, Position duties, remediation, and terminal state
persistence.py       sole append-only Decision journal codec and recovery
engine.py            composition of the one implemented product path
workbench.py         static display projection
cli.py               offline and explicitly authorized command entrypoints
scenarios.py         deterministic acceptance evidence, not product authority
```

Decision and Entry definitions are owned by
`../contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`; lifecycle definitions are owned by
`../contracts/SHADOW_LIFECYCLE.md`. Exact thresholds remain in the content-identified Policy and
source.

## State boundaries

Instrument catalogs, books, market context, scores, candidates, blockers, funnel snapshots,
unselected attempts, public snapshots, and presentation projections are bounded transient state.
The public adapter translates data into the same typed facts and calls the same engine; it is not a
second Policy, persistence path, or continuous service.

The only durable product path is the append-only Decision journal. It begins at
`DECISION_OPENED`, accepts only lifecycle-owned facts, and recovers only that Case and its continuing
duties. Before that event, authoritative durable business record count is zero. A journal root must
be explicitly supplied and must satisfy the product's legacy isolation boundary.

Current authorization for public calls, roots, continuous processes, private methods, accounts, and
deployment belongs only to `CURRENT_STAGE.md` and its active task; architecture does not grant it.
