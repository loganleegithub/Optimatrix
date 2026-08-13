# Case, Position, and Outcome Contract

**Status:** ACTIVE BUSINESS CONTRACT — B3 PUBLIC SHADOW SOURCE CONFORMANT; PRIVATE AND D1 ABSENT

This contract owns the chain after each Window Decision: TradeCase, Position, monitoring,
management, trigger, exit, terminality, Outcome, recovery, and offline learning. DecisionRecord and
Entry truth come from
`BTC_0DTE_TWO_SIDED_SHORT_VOL.md`; permanent evidence boundaries come from
`../authority/PRODUCT_CONSTITUTION.md`.

## TradeCase and record boundary

Every pre-registered DecisionWindow has one BTC-contract-owned DecisionRecord in the
`ObservationLedger`. Candidate selection is not the start of the learning population.

A Candidate opens at most one TradeCase in `CaseJournal`. It freezes truth layer, product, Window,
optional Episode, Policy, causal Decision boundary, selected four-leg structure, target amount,
`ShadowRiskAllocation` or future `AccountRiskReservation`, EntryEvaluationPolicy, planned window,
maximum wait boundary, and pricing basis. Permanent non-claims remain owned by the Constitution and
are inherited through the frozen truth layer rather than copied into each Case. The actual causal
Entry observation boundary and result are later immutable facts. All later facts bind the same
identities. A TradeCase may end without a Position; it cannot rewrite its Decision or Entry result,
and a Shadow TradeCase cannot be upgraded in place to a private-execution TradeCase.

`TradeCaseId` content-binds product, truth layer, DecisionWindowId, DecisionPolicyId, selected
structure, amount, and Decision boundary.

`CaseJournal` preserves the accepted causal prefix needed to recover the TradeCase and any Position.
It does not record every tick and does not validate the all-Window denominator. Exact codec and
event shape are implementation facts, not a second business specification.

## Position truth

A Public Shadow Position exists only after `SHADOW_ATOMIC_EVALUABLE` establishes complete
whole-product counterfactual economics. It keeps `truth_layer=SHADOW_PROJECTION` and must never be
described as held, filled, bought, sold, or exposed account risk.

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
market-risk conclusion. It is not itself proof that the market moved or that a close occurred.

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

A Shadow TradeCase without a Position terminates when its `SHADOW_ATOMIC_NOT_EVALUABLE` or `UNKNOWN`
Entry result and reason are frozen. With a Position, it terminates only when whole-product exit
economics or official expiry settlement economics are known. Its truth layer remains
`SHADOW_PROJECTION`.

For a real Position:

```text
SHORT_RISK_FLAT      authenticated account or official settlement proves every short quantity zero
PORTFOLIO_TERMINAL   authenticated account or settlement proves every leg quantity zero
```

The first may precede the second if real account truth contains residual long legs. Process loss,
stale data, Gap, rejected order, or one failed quote proves neither.

## Outcome populations

`WindowOutcome` belongs to every DecisionWindow, including no observation, `UNKNOWN`, `ABSTAIN`,
`REVIEW`, Candidate without Position, and Position. It binds the declared horizon, actual future
path or missing reason, delivery fact, path continuity, regime/event labels, and exact known-at
boundary. It is appended to the ObservationLedger and is required to measure selection bias and
missed opportunity; TradeCase Outcomes alone are not a learning denominator.

`ShadowCaseOutcome` contains either the no-Position Entry result and reason or the counterfactual
entry plus whole-product exit or settlement economics. It also records standard/public fee model,
Shadow model identity, native BTC result when evaluable, explicit boundary-valued USD diagnostics,
and observation quality. It is never called realized PnL.

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
