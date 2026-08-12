# Optimatrix System Architecture

**Status:** ACTIVE ARCHITECTURE AUTHORITY

## One causal product path

One Python modular monolith owns the sole implemented Channel:

```text
translated bounded public facts
→ Inverse BTC product + Deribit MarketSessionId
→ one SessionDecisionUnit
→ same-Session market context
→ joint Put/Call Vertical generation
→ one selected asymmetric four-leg Condor
→ canonical funnel + fixed Decision Policy
→ future-blind DECISION_OPENED
→ one coherent four-leg entry attempt
→ entry result / partial remediation / residual-wing duty
→ SHORT_RISK_FLAT
→ PORTFOLIO_TERMINAL + Outcome eligibility
```

There is no single-side product selector, fallback V2 profile, second reducer, database, message
bus, dynamic plugin loader, generic N-leg engine, online trainer, host-control subsystem, replay
platform, or browser-side formula.

## Module ownership

```text
products.py        enabled Inverse BTC product identity and product arithmetic
session.py         08:00 UTC MarketSessionId and Session phases
market.py          bounded typed public facts and source validation
pricing.py         target-depth, adverse tick, fee, Vertical, payoff, valuation, settlement math
structure.py       bounded Put/Call Vertical generation and joint Condor selection
radar.py           sole two-sided Decision Policy evaluation and blocker ownership
product_funnel.py  canonical SessionDecisionUnit stages, denominators, and earliest blocker
lifecycle.py       Decision Case, coherent entry, remediation, risk-flat and terminal state
persistence.py     sole append-only Decision journal codec and recovery validator
engine.py          sole BTC Short Vol composition and business-state owner
channels.py        fixed 2x2 descriptors; one enabled Channel
deribit_snapshot.py bounded read-only translator for one current Session
workbench.py        validated static display projection; browser owns no strategy formula
```

Lower-level calculators do not depend on strategy composition. `engine.py` composes them but does
not duplicate product, pricing, Decision, or lifecycle formulas.

## SessionDecisionUnit and funnel owner

The engine constructs exactly one canonical unit from product identity, `MarketSessionId`, decision
window, and fixed Policy identity. Structure enumeration remains bounded transient work inside that
unit. The engine/funnel projection alone owns stage numerators, denominators, bounded blocker
counts, and earliest-material-loss selection.

The snapshot adapter must translate public HTTP responses into the same typed facts and call the
same owner. It is not a second strategy implementation, continuous Runtime, persistence path, or
Policy calculator.

## Four-leg structure and attempt boundary

`structure.py` selects one joint structure; no caller may select a Put and Call side independently
and later call the result a Condor. `lifecycle.py` owns one entry-attempt identity covering all four
selected legs at the full target quantity.

`FULL_ENTRY` requires all four leg acquisitions to be:

- strictly later than Decision opening;
- no later than the attempt boundary;
- attached to the same attempt and selected structure identities;
- full target quantity;
- within fixed per-pair and four-leg source/receive coherence budgets.

If these conditions fail, the owner emits a known partial/wings/no-entry result when provable, or
UNKNOWN when facts cannot establish a result. Independently successful component attempts cannot be
merged after the fact.

## Partial remediation owner

`lifecycle.py` alone owns remediation. `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`, and
`TWO_SIDES_INCOHERENT` never enter normal carry. They immediately create a bounded duty to remove the remaining short risk. Missing-leg completion
is permitted only when the fixed Policy explicitly authorizes it from strictly future eligible
facts; it must not become unbounded waiting for an intended Condor.

A dangerous short may be repurchased without requiring its long wing to have a bid. A remaining
long wing becomes bounded residual-wing duty. `WINGS_ONLY` begins with no short risk; `NO_ENTRY`
creates no Position.

Remediation facts never rewrite `ENTRY_TERMINAL`, promote a partial Case to `FULL_ENTRY`, or admit it
to normal carry or the primary strategy-Outcome denominator.

For `FULL_ENTRY` normal carry, `lifecycle.py` also owns one bounded Position-risk reducer. One caller-
supplied observation either keeps `MONITORING` or freezes a two-sided exit duty. A later observation
may project an exit only from quotes strictly newer than that duty. Repeated calls advance the same
recoverable responsibility; the reducer is not a scheduler, continuous runtime, order service, or
fill source. Missing or stale required facts are risk `UNKNOWN` and cannot be converted to calm.

## Transient and durable boundaries

Market catalogs, books, quotes, context, scores, structure candidates, blockers, funnel snapshots,
unselected attempts, and presentation projections remain bounded in memory. The public snapshot
adapter performs no durable write.

The first durable new-product fact is `DECISION_OPENED`. The persistence owner freezes one Decision
Case before entry facts are known and accepts only lifecycle-authorized, append-only, strictly
future facts. It validates exact keys, identities, sequence, and conflicts. Recovery reconstructs
only that new-product Case; it does not create a new decision, convert a Gap into an exit, or change
eligibility.

The current stage authorizes only explicitly supplied non-legacy test/simulation roots. No stable
Case root or continuous writer is authorized.

## Eligibility projection

The lifecycle owner projects, separately:

- Decision evaluability;
- entry-result knownness;
- primary strategy-Outcome eligibility;
- terminal-economics eligibility;
- continuous-path eligibility;
- later qualification eligibility.

`FULL_ENTRY` is required for primary strategy-Outcome eligibility. A known partial, wings-only, or
no-entry result remains acquisition evidence and cannot be counted as a full-Condor return. A Gap
may remove continuous-path eligibility without erasing known terminal economics. Offline research
owns Cohorts, aligned controls, comparison tables, Challengers, and promotion.

## Legacy data isolation

The legacy repository, deployment checkout, V2 Policies, schema-v5 reader, stable root, and 92 Cases
are external historical assets. No new-product module may import the legacy packages at runtime or
read, write, translate, migrate, relabel, recover, or count legacy Case bytes. There is no symlink,
shared root, fallback codec, compatibility translator, or dual-product owner.

## Public Shadow and operations boundary

The system consumes synthetic or bounded translated public market facts only. It owns no private
API, account, balance, margin, order, fill, RFQ, combo creation, capital, actual settlement action,
continuous process, deployment, supervisor, or host inspection. Public combo and component routes
are counterfactual labels, not fills or atomic-execution proof.

## Future Channels

Reserved Channels may reuse product/session/market/lifecycle code only where the business invariant
is identical. They require separate active tasks, strategy Policies, and permission. Their reserved
names do not justify factories, generic schemas, unused fields, or runtime selection today.
