# Case, Position, and Outcome Contract

**Status:** ACTIVE BUSINESS CONTRACT — B3 PUBLIC SHADOW SOURCE CONFORMANT; PRIVATE AND D1 ABSENT

This contract owns the chain after each Window Decision: TradeCase, Position, monitoring,
management, trigger, exit, terminality, Outcome, recovery, and offline learning. DecisionRecord and
Entry truth come from
`BTC_0DTE_TWO_SIDED_SHORT_VOL.md`; permanent evidence boundaries come from
`../authority/PRODUCT_CONSTITUTION.md`.

## TradeCase and record boundary

The 96 pre-registered DecisionWindows remain the Session denominator. Each Window whose causal cut
is attempted by an enrolled runtime owns exactly one BTC-contract-owned DecisionRecord in the
`ObservationLedger`: valid evidence yields its Decision, while an exhausted or invalid cut yields
`UNKNOWN` at the input deadline. A Window missed before enrollment remains absent as measured
coverage and is never backfilled. Candidate selection is not the start of the learning population.

A Candidate opens at most one TradeCase in `CaseJournal`. It freezes truth layer, product, Window,
optional Episode, Policy, causal Decision boundary, selected four-leg structure, target amount,
`ShadowRiskAllocation` or future `AccountRiskReservation`, EntryEvaluationPolicy, planned window,
maximum wait boundary, Decision component-route evidence, Decision Session phase, and Decision VRP
proxy. Permanent non-claims remain owned by the Constitution and are inherited through the frozen
truth layer rather than copied into each Case. The actual causal Entry observation boundary and
typed reunderwriting result are later immutable facts. That result binds the same Policy,
structure, allocation, and Decision metrics; stores current metrics, dimension-specific blockers,
and its distinct later route-evidence identity; and is recovered with the Case. All later facts bind
the same identities. A TradeCase may end without a Position; it cannot rewrite its Decision or
Entry result, and a Shadow TradeCase cannot be upgraded in place to a private-execution TradeCase.

`TradeCaseId` content-binds product, truth layer, DecisionWindowId, DecisionPolicyId, selected
structure, amount, and Decision boundary.

`CaseJournal` preserves the accepted causal prefix needed to recover the TradeCase and any Position.
It retains bounded representative Decision, Entry, monitoring, and exit points rather than every
tick. Every accepted observation still advances one exact count and updates content-addressed
landmarks for MFE/MAE, maximum short Delta, minimum distance to each short strike, IV/RV range, and
jump or directional extremes. Typed Gaps preserve their causal source, observation when one exists,
known-at boundary, and exact reason. The retained points, landmarks, and Gaps form one monotonic
explanatory prefix; they do not validate the all-Window denominator. Exact codec and event shape are
implementation facts, not a second business specification.

An unresolved same-Session Shadow Case retains its frozen `stress_reserve_usd` whether Entry is
pending or a Position exists. Recovery verifies the allocation identity and conservative component
maximum before reconstructing capacity. A terminal no-Position Entry or terminal Position Outcome
releases that exact reserve; restart, Gap, ExitIntent, or a merely attempted exit does not.

## Position truth

A Public Shadow Position exists only after `SHADOW_ATOMIC_EVALUABLE` establishes complete
whole-product counterfactual economics and one `EVALUABLE/COMPONENT_SYNTHETIC_ESTIMATE` Entry route
record for the exact frozen ratios and amount. Its different Decision and Entry route identities
remain recoverable. It keeps `truth_layer=SHADOW_PROJECTION` and must never be described as held,
filled, bought, sold, or exposed account risk.

A real Position is created from authenticated Combo trade and reconciled against account-position
truth. On recovery, an authenticated nonzero account Position is sufficient to restore risk
responsibility even when trade attribution is missing; attribution remains `UNKNOWN`. An accepted
or open order is not a Position. Trade and account facts that disagree remain `UNKNOWN` and preserve
risk responsibility. Public quote failure cannot create or mutate a real Position. If
a future account reports unexpected leg exposure, that fact requires a separately authorized
contingency task; this contract defines no speculative leg-remediation state machine.

`PositionId` binds TradeCase, truth layer, product, legs, Entry-attempt or account scope, and first
confirmed Entry boundary. Target and current actual amount are Case/exposure facts, not identity
parts. A Gap, restart, unavailable market, or failed observation never erases the Position.

## Continuous monitoring

Monitoring evaluates the frozen Position at Policy cadence against a causal observation stream.
All absolute lifecycle boundaries use the same Deribit UTC domain as the owning Window and frozen
expiry. `observed_at` and `known_at` retain their distinct causal meanings within that one domain;
host wall time and browser-local display time cannot advance Entry, monitoring, trigger, exit, or
settlement state. Monotonic process time may wake the runtime but cannot establish a lifecycle fact.
Every trigger or observation separates these categories:

```text
DATA        completeness, freshness, continuity, coherence
THESIS      volatility-premium thesis deterioration
POSITION    price path, Delta, defined loss, concentration, event or jump exposure
TIME        exit deadline and delivery boundary
ACCOUNT     authenticated margin, capacity, liquidation, and account Position facts
EXECUTION   Combo order, trade, cancel, reject, and executable-close facts
HUMAN       explicit authorized intervention
```

Only categories available to the Position's truth layer may be evaluated. DataHealth failure keeps
the observation `UNKNOWN`, preserves the Position and existing exit intent, and blocks a new
market-risk conclusion. It is not itself proof that the market moved or that a close occurred. A
deterministic `LATEST_EXIT` boundary depends only on the frozen expiry and validated Deribit UTC;
when that boundary is known, missing or invalid market prices must still freeze the whole-product
ExitIntent while keeping the exit estimate `UNKNOWN`. If the complete public market call fails,
the frozen time boundary owns a content-addressed time-evidence identity instead of pretending that
a MarketObservation existed.

The first known trigger freezes one `ExitIntent` with category, reason, observed-at and known-at
boundaries, source, Policy identity, and full-product scope. If several triggers share one
observation, frozen Policy priority selects the primary reason. Later urgency may raise execution
priority but cannot rewrite the first reason. DATA and EXECUTION failure preserve an existing
intent; HUMAN creates one only through a separately authorized interface.

## Position management and exit

V1 management has only three normal actions:

```text
HOLD
EXIT_WHOLE_PRODUCT
SETTLE_AT_EXPIRY
```

V1 does not roll, recenter, add, hedge, resize, or carry one Vertical as a new strategy. Those are
new products or Policies, not hidden recovery paths.

For Public Shadow, the trigger observation cannot also price the exit. A strictly later eligible
market cut produces a whole-product Shadow exit estimate or `UNKNOWN`; this prevents look-ahead and
does not claim an order or close.

For a future real Position, one reduce-only Combo order is the normal exit route. Order state, fill,
and reconciled account Position determine what remains; a quote or order intent cannot prove flat
risk. The research strictly-future pricing rule does not prohibit a real system from submitting an
order after the trigger against the currently available book.

## Terminal truth

A Shadow TradeCase without a Position terminates when its final Entry result and owning reason are
frozen. A known route, thesis, structure, economics, or Shadow-allocation rejection terminates
immediately; missing or causally invalid evidence remains provisional until the Entry deadline and
then terminates as `ENTRY_EVIDENCE_UNKNOWN`. With a Position, the Case terminates only when
whole-product exit economics or official expiry settlement economics are known. Its truth layer
remains `SHADOW_PROJECTION`.

For a real Position:

```text
SHORT_RISK_FLAT      authenticated account or official settlement proves every short quantity zero
PORTFOLIO_TERMINAL   authenticated account or settlement proves every leg quantity zero
```

The first may precede the second if real account truth contains residual long legs. Process loss,
stale data, Gap, rejected order, or one failed quote proves neither.

## Outcome populations

`WindowOutcome` belongs to every DecisionWindow with an authoritative Base DecisionRecord,
including `UNKNOWN`, `ABSTAIN`, `REVIEW`, Candidate without Position, and Position. A Window missed
before runtime enrollment has neither a synthetic DecisionRecord nor a synthetic Outcome; its
absence remains population coverage truth. A WindowOutcome binds the declared horizon, actual
future path or missing reason, delivery fact, path continuity, regime/event labels, and exact
known-at boundary. It is appended to the ObservationLedger and is required to measure selection
bias and missed opportunity among recorded Windows; TradeCase Outcomes alone are not a learning
denominator.

`ShadowCaseOutcome` contains either the no-Position Entry result and reason or the counterfactual
entry plus whole-product exit or settlement economics. It also records standard/public fee model,
Shadow model identity, native BTC result when evaluable, explicit boundary-valued USD diagnostics,
and observation quality. Its explanation binds the final Decision-to-Entry reunderwriting change,
the accepted path landmarks and Gaps, projected Entry and terminal Combo fees, primary terminal
category and reason, a zero-economics no-entry counterfactual, and a hold-to-expiry counterfactual.
These are Shadow projections and are never called realized PnL, fill, slippage, account Position,
or executable liquidity.

Alternative Outcomes are limited to the bounded alternative structures frozen by the owning
Decision. Their Entry basis is classified once against the same later Entry observation; an
evaluable basis is projected against the same actual terminal market cut or official settlement as
the selected structure. An unknown or not-evaluable alternative keeps its exact reason. Outcome
construction cannot rerun search, select a new structure, or infer unavailable route economics.

A whole-product Shadow exit freezes terminal economics and releases its exact reserve immediately.
Until expiry, its hold-to-expiry counterfactual remains `UNKNOWN` with the official-settlement-
pending reason. The matching official settlement may later perform exactly one append-only
explanatory enrichment: it fills only that counterfactual, cannot rewrite exit economics or the
primary exit reason, cannot reopen risk, and cannot append another market-path claim. Contract
settlement terminality records the same counterfactual as known at its original terminal boundary.

For a no-Position Outcome, a known Entry Policy/allocation/route rejection sets
`shadow_entry_evaluable=false` with its exact reason. Terminal `ENTRY_EVIDENCE_UNKNOWN` preserves
that eligibility as unknown and records a DataHealth gap; it cannot be counted as a known Policy
rejection.

`LivePositionOutcome` uses authenticated trades, actual fees, actual amounts, account
reconciliation, settlement/account cashflows, and terminal state. Shadow and live economics never
share one return population.

Each Outcome stores separate eligibility dimensions with an exact false or unknown reason:

```text
decision_evaluable
future_path_known
future_path_continuous
shadow_entry_evaluable
terminal_economics_evaluable
live_execution_attributable
strategy_population_eligible
qualification_eligible
```

One global eligibility Boolean cannot replace these facts. A known terminal result may remain
economically evaluable after a Gap while becoming ineligible for continuous-path analysis.

## Offline learning and AI

Qualification uses aligned DecisionWindows and actual future paths. At minimum it compares frozen
`BASE`, frozen `CHALLENGER`, `UNFILTERED_CONDOR`, and `NO_TRADE` under the same causal inputs,
future path, and cost model. It inspects tail loss, ES/CVaR, worst Session, drawdown, breach and
USD-contractual-cap and declared scenario-loss rates, fee-after economics, missed profit,
coverage/abstention, trade frequency, and regime stability. `UNFILTERED_CONDOR` keeps legal,
DataHealth, USD-payoff-cap, and cost constraints while removing the strategy filter being tested.
Trade count or average win rate alone is insufficient.

Evaluation is chronological or walk-forward. Training, threshold choice, and evaluation periods do
not leak into one another, including across the same Session or future-blind Episode. Promotion
threshold, minimum sample, and veto conditions are registered before evaluation. AI may recommend a
Challenger only after sufficient forward Outcomes; a human must approve a new immutable Policy
identity under a new task. Current maturity and permission belong to Stage. No online trainer,
feature store, model registry, or self-authorizing execution path is implied.

## Recovery

Recovery reconstructs the accepted Window, TradeCase, and Position facts from their owning records
and resumes unresolved monitoring or exit responsibility. It does not backfill missed observations,
convert `UNKNOWN` to calm, merge identities, adopt legacy state, or create a terminal Outcome from
process termination.
