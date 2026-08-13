# Optimatrix Product Authority

**Status:** ACTIVE PRODUCT AUTHORITY — UNQUALIFIED PUBLIC SHADOW

## Current product

The sole implemented Channel is `INVERSE_BTC_SHORT_VOL`, implemented as
`BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`.

It evaluates one asymmetric, defined-risk, four-leg Iron Condor for the option expiry ending the
current Deribit `08:00–08:00 UTC` Session:

```text
buy lower-strike Put
sell higher-strike Put
sell lower-strike Call
buy higher-strike Call
```

The Put and Call Credit Verticals are pricing and acquisition components. Neither one Vertical nor
two independently selected Verticals are the product. BTC Long Gamma and both ETH Channels are
reserved descriptors only; they grant no Policy, runtime, Case schema, task, or shared framework.

Exact Session, decision, structure, funnel, and Entry semantics belong to
`../contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`. Position and durable lifecycle semantics belong to
`../contracts/SHADOW_LIFECYCLE.md`.

## Thesis to falsify

The product tests whether executable same-Session implied insurance exceeds the subsequent physical
path, jump, execution, and four-leg fee cost. Executable Session VRP is the reason to sell; Theta is
the speed at which existing premium may be monetized. Time passing or high premium alone is not
Edge.

A Decision must reject rather than average away Gamma expansion, jump or event state, directional
breakout, strike concentration, accelerating path, insufficient body distance, fee burden,
incoherent acquisition, and unavailable short-risk exit. Defined-risk wings cap contractual payoff;
they do not remove path, Gap, liquidity, execution, or inverse-BTC valuation risk.

Current scores and thresholds are launch hypotheses. They are not calibrated probabilities,
expected return, Alpha, profitability, or a qualified sweet zone. No durable
`SINGLE_SIDE_VERTICAL_BASELINE` or `NO_TRADE_CONTROL` exists. Qualification, if separately authorized
later, must pre-register those aligned comparators, frozen Policies, `SessionDecisionUnit` windows,
and actual future paths; this condition does not authorize building them. AI may propose a
Challenger; it cannot choose a favorable denominator, rewrite Base after Outcomes, qualify itself,
or grant execution permission.

## Evidence semantics

One `SessionDecisionUnit` is the product and learning denominator. Options, legs, structures,
quotes, retries, routes, journal events, and UI rows are observations inside it, not additional
opportunities. The exact identity and funnel projection belong to the BTC contract.

`UNKNOWN` means a required fact is missing, stale, discontinuous, malformed, contradictory,
outside its causal budget, or numerically unresolved. It is not zero, calm, negative, eligible,
flat, or terminal. `NOT_YET_MEASURED` means the required business denominator does not yet exist. A
valid zero requires a complete scope and a known positive denominator.

`ON_DEMAND_COMBO_LIQUIDITY_UNOBSERVED` means only that private or on-demand liquidity was not visible
through public data. It does not prove that a structure or component route is impossible.

## Permanent boundaries

Public Shadow uses public observations to calculate counterfactual economics. A quote is not an
order, fill, RFQ, liquidity reservation, account position, margin fact, capital exposure, realized
PnL, or proof of atomic execution. A Decision Case is a simulated research enrollment. Current
Policy is unqualified and establishes no Edge, Alpha, win rate, profitability, or execution
readiness.

The preceding V2 repository, runtime, Policies, schemas, Case root, and historical Cases are external
assets. This product may not read, write, translate, migrate, relabel, recover, import, or count
them. It has no compatibility path. Current live, persistence, private, and deployment permissions
exist only in `CURRENT_STAGE.md` and its one active task.
