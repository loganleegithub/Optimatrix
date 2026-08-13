# Optimatrix Product Authority

**Status:** ACTIVE PRODUCT AUTHORITY — UNQUALIFIED PUBLIC SHADOW

## Product

The sole product Authority is `INVERSE_BTC_SHORT_VOL`: a same-Deribit-Session, two-sided, four-leg
BTC inverse-option premium sale whose wings cap contractual intrinsic payoff in USD. Current source
conformance belongs to `CURRENT_STAGE.md`.

```text
buy lower-strike Put
sell higher-strike Put
sell lower-strike Call
buy higher-strike Call
```

The two Credit Verticals are structure and pricing components only. A Vertical is not the product
and is not an independent acquisition route. BTC Long Gamma and both ETH Channels are reserved
descriptors; they authorize no Policy, runtime, schema, task, or shared framework.

Decision semantics belong to `../contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`. Case, Position, and
Outcome semantics belong to `../contracts/CASE_POSITION_OUTCOME.md`.

## Thesis to falsify

The product tests whether a whole-product, same-Session premium-sale opportunity, after applicable
fees, slippage, exit or settlement cost, and inverse-BTC valuation, compensates the subsequent
physical path, Gamma, jump, event, concentration, directional, and execution risk. Theta is a
monetization mechanism, not independent Edge. High premium or time passing cannot prove the thesis.

All current proxies, scores, thresholds, and phase boundaries are launch hypotheses. They are not
calibrated probabilities, forecasts, dealer positioning, expected return, Alpha, profitability, or
a qualified trading zone.

## Identity and truth boundaries

The online business chain has four identities; offline research may add one derived grouping:

```text
MarketObservationId → DecisionWindowId → TradeCaseId → PositionId
DecisionWindowId[] → OpportunityEpisodeId (optional, future-blind grouping)
```

These identities never substitute for one another. Objects below `DecisionWindow` never multiply
the learning denominator; a later TradeCase or Position never backfills a missing Window. Exact
fields and cardinality for MarketObservation, DecisionWindow, and optional OpportunityEpisode belong
to the BTC contract; TradeCase and Position belong to the Case/Position/Outcome contract.

Every fact also has one truth layer:

- `PUBLIC_OBSERVATION`: provenance-bound public or explicit human/external input fact and its
  explicitly named deterministic proxy;
- `SHADOW_PROJECTION`: counterfactual research result derived by a frozen model;
- `PRIVATE_EXECUTION`: authenticated order, trade, fee, account, margin, Position, or settlement
  fact.

Shadow and real are truth layers, not additional identities. A public quote or Shadow result is
never an order, fill, RFQ, liquidity reservation, account Position, margin fact, capital exposure,
realized PnL, or proof of atomic exchange execution.

## Permanent evidence boundaries

`UNKNOWN` means a required fact is missing, stale, discontinuous, malformed, contradictory, outside
its causal boundary, or numerically unresolved. It is not zero, calm, negative, eligible, flat, or
terminal. `NOT_YET_MEASURED` means the required business population does not exist. A valid zero
requires a complete scope and a known positive denominator.

The preceding V2 repository, runtime, Policies, schemas, Case root, and historical Cases are
external assets. This product may not read, write, translate, migrate, relabel, recover, import, or
count them.

AI may be an offline Challenger only after aligned DecisionWindows, frozen Base and Challenger
Policies, chronological or walk-forward evaluation, and actual future paths exist. AI cannot choose
the denominator, rewrite a frozen Policy after Outcomes, promote itself, or receive account,
capital, order, or execution permission. Promotion is a human decision under a separately
authorized task.
