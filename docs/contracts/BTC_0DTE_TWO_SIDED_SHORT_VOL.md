# BTC 0DTE Two-Sided Short Vol Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

## Decision object

One decision belongs to exactly one canonical unit:

```text
SessionDecisionUnit =
  INVERSE_BTC product identity
  + current Deribit 08:00 settlement MarketSessionId
  + decision window identity
  + fixed Decision Policy identity
```

The system may examine a bounded option chain and many candidate structures inside the unit, but it
selects at most one asymmetric four-leg Iron Condor. It first prices legal Put and Call Credit
Vertical components at full target quantity, retains a fixed bounded set on each side, and evaluates
joint combinations. It never adds independent single-leg or Vertical scores, and candidates do not
multiply the funnel denominator.

The selected canonical leg order is:

```text
LONG_PUT < SHORT_PUT < SHORT_CALL < LONG_CALL
```

All four legs share product, expiry, target quantity, and selected-structure identity.

## Applicable Session and phase

Only options whose expiry equals the current Deribit Session end at `08:00 UTC` are applicable.
`ROLL_REPRICE` is review-only. `CORE_CARRY` and Policy-qualified `LATE_THETA` may select an attempt.
`EXIT_ONLY` and `DELIVERY_TWAP` prohibit new short-premium entry. Boundary changes require a new
content-identified Policy.

## Joint score and hard blockers

The score is ordinal and unqualified:

```text
premium evidence   executable Session VRP + Theta-capture proxy
gamma safety       path × jump × event × breakout × concentration interaction
range quality      nearer short-body distance in forecast sigma
execution quality  joint spreads + depth + four-leg fees + route coherence
final score        bounded monotone combination of all four terms
```

The Policy owns exact weights and thresholds. A numeric score is not probability, expected return,
Edge, or profitability. Hard blockers remain explicit and cannot be offset by high premium.

Required missing, stale, discontinuous, contradictory, or incoherent facts produce `UNKNOWN` and an
exact bounded blocker. `ON_DEMAND_COMBO_LIQUIDITY_UNOBSERVED` reports only unobserved private/RFQ
liquidity; it is not a no-structure conclusion.

## Structure economics

Entry counterfactual pricing consumes full target quantity and applies legal adverse tick stress:

```text
sell Short Put at stressed bid
buy Long Put at stressed ask
sell Short Call at stressed bid
buy Long Call at stressed ask
reserve all four standard public fees
```

Underwriting evaluates one joint structure: native and boundary-valued net credit, four-leg fee
burden, maximum side payoff and maximum loss, nearer body distance, portfolio net Delta, and fixed
Gamma/jump/event/breakout/execution limits. Native BTC premium and USD-equivalent boundary valuation
remain distinct quantities.

## Four-leg attempt coherence

One selected attempt freezes:

- Decision Case, `SessionDecisionUnit`, Policy, and structure identities;
- all four canonical leg identities and full target quantity;
- one attempt identity and decision/attempt boundaries;
- permitted route (`PUBLIC_COMBO`, bounded two-Vertical route, or explicit wings-only fallback);
- per-pair and all-four source/receive timing limits;
- consumed raw/stressed levels and public fee reserves.

Every acquisition fact must be strictly later than Decision opening and no later than the attempt
boundary. `FULL_ENTRY` requires four full-quantity results within the same attempt and coherence
budgets. Results from separate attempts, later retries, different structures, or mismatched
quantities cannot be combined into `FULL_ENTRY`.

## Entry-result classification

The attempt produces exactly one known state when facts suffice:

```text
FULL_ENTRY
PUT_SIDE_ONLY
CALL_SIDE_ONLY
TWO_SIDES_INCOHERENT
WINGS_ONLY
NO_ENTRY
```

Otherwise its entry result remains `UNKNOWN` with exact reasons.

- `FULL_ENTRY`: all four selected legs acquired coherently; normal carry may open.
- `PUT_SIDE_ONLY`: Put Credit Vertical acquired without the Call side; immediate remediation, never
  normal carry.
- `CALL_SIDE_ONLY`: Call Credit Vertical acquired without the Put side; immediate remediation,
  never normal carry.
- `TWO_SIDES_INCOHERENT`: both side components were observable as acquired but violated the
  four-leg cross-side coherence budget; both sides enter remediation and remain strategy-ineligible.
- `WINGS_ONLY`: only long protection remains; no short risk, residual-wing management only.
- `NO_ENTRY`: no Position; known Decision acquisition Outcome.

The entry-result name describes public Shadow counterfactual acquisition, not an actual fill.

## Partial remediation

Partial short exposure is a failure state with one bounded objective: remove unintended short risk.
The Position owner must not wait indefinitely for the missing side to turn the failure into an
intended Condor. It may:

1. buy back the dangerous short using a strictly future eligible public counterfactual; or
2. acquire missing protection/side only when the frozen Policy explicitly authorizes that bounded
   route and its causal/timing limits remain satisfied.

A missing long-wing bid never blocks buying back the short. Residual long wings continue under the
Shadow lifecycle contract. Remediation never rewrites the frozen entry result, promotes the Case to
`FULL_ENTRY`, enters normal carry, or grants primary strategy-Outcome eligibility.

## Funnel projection

The owning engine projects, for one `SessionDecisionUnit`:

```text
APPLICABLE_SESSION_DECISION
MARKET_CONTEXT_KNOWN
VRP_THETA_QUALIFIED
GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE
TWO_SIDED_STRUCTURE_EVALUABLE
ENTRY_ROUTE_EVALUABLE
ENTRY_ATTEMPT_SELECTED
DECISION_CASE_OPENED
ENTRY_RESULT_KNOWN
DECISION_CASE_OUTCOME_KNOWN
```

Each stage has an exact numerator, denominator, known-negative blockers, unknown blockers, and
upgrade condition. The primary blocker is the earliest material loss.

## Non-claims

This contract authorizes public Shadow counterfactuals only. It grants no private API, account,
margin, order, fill, RFQ, combo creation, liquidity reservation, capital, actual execution,
settlement action, continuous runtime, Policy qualification, Edge, Alpha, win-rate, or profitability
claim.
