# Optimatrix North Star

**Status:** ACTIVE PRODUCT THESIS — UNQUALIFIED AND FALSIFIABLE

## Why same-Session two-sided premium sale exists

The product tests whether same-Deribit-session implied insurance can exceed the subsequent physical
path, jump, execution, and four-leg fee cost. Executable Session VRP is the reason to sell; Theta is
the speed at which an already-existing premium may be monetized. Time passing alone is not Edge.

The product seeks `SessionDecisionUnit`s where:

- same-Session implied variance is rich relative to a causally available physical-path forecast;
- combined executable Put and Call premium remains meaningful after four-leg fees and stress;
- the intended holding interval can capture a material fraction of remaining time value;
- both short strikes lie outside the bounded forecast range by the fixed Policy margin;
- realized-volatility acceleration, jump share, directional persistence, scheduled-event state,
  breakout, and strike concentration do not signal Gamma expansion;
- four-leg entry and short-risk exit are realistically evaluable at full target quantity.

This is a hypothesis to falsify with future Outcomes, not permission to assume a high win rate,
positive EV, Alpha, profitability, or safe execution.

## What the system must prevent

The system reduces, but cannot eliminate, “coins in front of a bulldozer” risk by excluding or
exiting:

- live scheduled-event and unscheduled-shock states;
- concentrated-strike breakout rather than stable oscillation;
- path acceleration or one-sided persistence;
- short bodies too near the forecast range;
- structures whose wings, four-leg fees, or execution stress consume the credit;
- incoherent four-leg attempts that masquerade as a full Condor;
- partial short exposure that drifts into normal carry;
- positions whose short risk cannot be flattened before the delivery window.

Defined-risk wings cap contractual payoff; they do not remove path, Gap, liquidity, execution, or
inverse-BTC valuation risk.

## Deribit time management

The system does not transplant SPX clock times. It maps the business stages to the Deribit Session:

```text
ROLL_REPRICE
CORE_CARRY
LATE_THETA
EXIT_ONLY
DELIVERY_TWAP (07:30–08:00 UTC)
```

Initial boundaries are Policy priors. Future pre-registered evaluation may learn differences by
phase, weekday, event state, and market regime; the current candidate does not claim a qualified
sweet zone.

## Learning North Star

The learning unit is one `SessionDecisionUnit`, not each option or structure considered inside it.
Primary strategy Outcomes require coherent `FULL_ENTRY`; partial, cross-side-incoherent, wings-only,
and no-entry results measure acquisition quality and operational loss without entering the
full-Condor return denominator.

Future comparison requires aligned `SINGLE_SIDE_VERTICAL_BASELINE` and `NO_TRADE_CONTROL` arms from
the same product Session and decision window. AI may propose a frozen Challenger for later offline
evaluation. It cannot rewrite Base, change denominators after observing Outcomes, qualify itself, or
grant execution authority.

## Four-channel direction

Shared foundations are product facts, Session identity, bounded public context, pricing, acquisition,
lifecycle, persistence, and evaluation only when their invariants are identical. Strategy formulas
remain separate:

- BTC Short Vol asks whether joint executable premium exceeds risk and uses asymmetric Iron Condors;
- Long Gamma, ETH, and any later Channel remain unimplemented until separately authorized.

The roadmap grants no current Policy, runtime, Case root, private permission, or generic strategy
framework.
