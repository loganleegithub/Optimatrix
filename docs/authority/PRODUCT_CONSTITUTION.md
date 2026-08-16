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

`AI Lab` is the product name for offline learning. It judges the quality of an already frozen
ex-ante rule after an ended Session; it does not audit whether code merely followed that rule. The
Lab retains the complete aligned DecisionWindow denominator but adjudicates each Window
independently against one content-identified hindsight oracle. The oracle requires that Window's
decision-time full-amount four-leg cost and frozen risk-quality controls, plus sufficient
post-Session realized-variance path, physical-path extrema, and official settlement evidence.
Hindsight may test whether a record-level environment filter rejected a structure whose frozen
Candidate-level controls were all satisfied. It may never waive a Candidate-level structure,
minimum-credit, credit-to-payoff, net-Delta, fee, reference-loss, or payoff-cap blocker. A favorable
realized outcome behind any such blocker is a diagnostic Policy reject, not an opportunity or a
miss. Terminal profit alone is insufficient. A complete Window is classified as Base-captured
opportunity, correct avoidance, missed opportunity, or over-risk selection. A Window missing one of
its own required facts remains `UNKNOWN`; an unrelated missing Window cannot erase this known
classification.

Missingness is never assumed random. The Lab reports exact coverage and non-parametric
identification bounds over the registered denominator. In particular, the observed miss count is a
lower bound and observed misses plus unknown Windows is the upper bound; the same bound applies to
over-risk selections and opportunity incidence. These are logical bounds, not confidence intervals
or imputed estimates. A known miss or over-risk selection is valid adverse evidence even when the
rest of the Session is incomplete. If complete Windows show no rule error but unknown Windows
remain, the conclusion is only `PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR`, never a clean bill of
health.

Only a complete Session with zero misses and zero over-risk selections may say the rule was well
calibrated or that no opportunity existed for the whole Session. When Base missed, the Lab
diagnoses exact blockers and negative signed threshold margins. When Base selected
hindsight-ineligible risk, it diagnoses the IV/RV, path, or settlement failure. AI may act as an
offline Challenger only after Base itself captured a hindsight-confirmed opportunity without
Session evidence gaps or rule-quality errors, and aligned DecisionWindows, frozen Base and
Challenger Policies, chronological or walk-forward evaluation, and actual future paths exist. A
single Session cannot qualify Policy or establish Edge. AI cannot choose the denominator, rewrite a
frozen Policy after Outcomes, promote itself, or receive account, capital, order, or execution
permission. Promotion is a human decision under a separately authorized task.

## Capability acceptance and exogenous opportunity

A maturity gate must separate controllable system capability from the exogenous occurrence of an
eligible market opportunity. Pipeline capability may be accepted only when production-shaped
deterministic evidence covers the complete declared path and live public evidence proves the
causal input, `UNKNOWN`, and truthful no-trade boundaries that deterministic fixtures cannot.
Neither evidence class may substitute for the other.

`PIPELINE_CAPABILITY_ACCEPTED` means the declared system can preserve and process the product path
without manufacturing market facts. `NATURAL_CHAIN_OBSERVED` is strictly stronger evidence that a
causally complete eligible chain actually occurred under the frozen Policy. A natural chain that
has not occurred remains `NOT_YET_OBSERVED`; it does not invalidate accepted capability, prove that
the Policy is unreachable, or authorize threshold, sizing, ranking, route, or truth-layer changes.
A stage may never make progress depend on weakening the Policy merely to create an acceptance
example.

Pipeline capability, natural-chain observation, Policy reachability, Policy qualification, and
Edge are five distinct evidence states. Reachability may be audited from causal market inputs by
reporting raw values, threshold margins, and bounded counterfactual gate responsibility. Policy
qualification and Edge require aligned actual forward Outcomes under frozen Policies and cost
models. No implementation test, deterministic tape, Candidate count, no-trade count, single
Session, or natural chain alone proves either.
