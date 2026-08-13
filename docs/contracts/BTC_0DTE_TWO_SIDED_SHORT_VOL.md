# BTC 0DTE Two-Sided Short Vol Contract

**Status:** ACTIVE DECISION AND ENTRY CONTRACT

**Owning capability:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

This contract owns Session applicability, the decision unit, required MarketContext, joint
structure selection, the product funnel, and Entry acquisition truth. Product-wide evidence and
non-claim semantics remain in `../authority/PRODUCT_CONSTITUTION.md`; exchange mechanics and API
sources are indexed in `../research/PRIMARY_SOURCES.md`.

## Session and decision unit

An option is `0DTE` only when its expiry equals the end of the current Deribit settlement Session at
`08:00 UTC`. A rolling `TTE < 24h` label is insufficient.

```text
ROLL_REPRICE   review only
CORE_CARRY     entry may be evaluated
LATE_THETA     entry requires the Policy's additional qualification
EXIT_ONLY      no new short-premium entry
DELIVERY_TWAP  no new short-premium entry
```

Phase boundaries are Policy values, not a qualified sweet-zone claim.

The sole funnel unit is:

```text
SessionDecisionUnit =
  product_spec_identity
  + MarketSessionId
  + decision_window_identity
  + Decision Policy identity
```

One unit may inspect many options, Verticals, quotes, and joint candidates. The fixed Policy may
select at most one primary four-leg structure; internal objects never multiply the denominator.

## MarketContext gate

Before scoring or structure creation, one context must bind the exact Decision boundary and include:

- implied- and physical-variance method identities and matched horizon;
- historical coverage boundaries;
- public source and local receive boundaries; and
- event state, when it became known, and exact missing or contradictory reasons.

Complete causal evidence passes `MARKET_CONTEXT_KNOWN`. Incomplete evidence produces one
`Decision.UNKNOWN`, consumes that unit at this stage as `UNKNOWN`, and leaves later stages
`NOT_REACHED`. It creates no score, structure, or Decision Case and remains transient.

## Decision and joint structure

The engine evaluates one product object containing one Put Credit Vertical and one Call Credit
Vertical. The score is an ordinal, unqualified filtering hypothesis combining premium/Theta
context, path and event risk, body distance, and execution quality. Policy owns its exact weights,
thresholds, freshness limits, and coherence budgets. Hard blockers cannot be offset by a higher
score. The current implied input is a nearest-ATM mark-variance proxy and the physical input is a
trailing matched-horizon realized-variance proxy; neither is yet a qualified physical forecast or
model-free executable VRP measure.

Entry counterfactual pricing consumes full target quantity at adverse legal ticks:

```text
sell Short Put at stressed bid
buy Long Put at stressed ask
sell Short Call at stressed bid
buy Long Call at stressed ask
reserve all four standard public fees
```

`structure.py` jointly generates and filters legal four-leg candidates. Underwriting uses native
and boundary-valued credit, fee burden, side payoff and loss, nearer body distance, portfolio Delta,
the Policy's Gamma/jump/event/breakout limits, and full-quantity public buyback depth for both short
bodies. A heuristic rank cannot rescue a failed hard condition. If no joint candidate passes, the
unit stops at `ENTRY_ROUTE_EVALUABLE` with
`NO_JOINT_CANDIDATE_PASSES_HARD_UNDERWRITING`, exact rejection reasons, and no selected attempt.

Public component books are bounded counterfactual inputs. Public combo absence has the product-wide
`ON_DEMAND_COMBO_LIQUIDITY_UNOBSERVED` meaning; it is not an impossibility or atomic-execution claim.

## One coherent Entry attempt

Selection freezes the Case, unit, Policy, structure, all four legs, full target quantity, route,
attempt identity, decision and attempt boundaries, timing/coherence budgets, consumed levels, and
fee reserves.

Every acquisition fact must be strictly later than Decision opening, no later than the attempt
boundary, attached to the same selected structure and attempt, and measured at full target
quantity. `FULL_ENTRY` requires all four legs within the Policy's pair and all-four coherence
budgets. Separate attempts, later retries, different structures, or mismatched quantities cannot be
combined after the fact.

## Entry result

When facts suffice, the attempt produces exactly one result:

```text
FULL_ENTRY
PUT_SIDE_ONLY
CALL_SIDE_ONLY
TWO_SIDES_INCOHERENT
WINGS_ONLY
NO_ENTRY
```

- `FULL_ENTRY`: all four selected legs were acquired coherently; normal two-sided carry may open.
- `PUT_SIDE_ONLY` or `CALL_SIDE_ONLY`: one Credit Vertical was acquired; live short risk enters
  remediation immediately and never normal carry.
- `TWO_SIDES_INCOHERENT`: both side acquisitions were observable but violated cross-side coherence;
  both sides enter remediation and the result is not a full Condor.
- `WINGS_ONLY`: no short risk exists; residual long-wing duty remains.
- `NO_ENTRY`: no Position exists; the Case retains a known acquisition result.

If facts cannot establish one state, Entry remains `UNKNOWN`. Later remediation never rewrites this
result or promotes it to `FULL_ENTRY`. Position handling belongs to
`SHADOW_LIFECYCLE.md`.

## Canonical funnel

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

Each stage denominator is the preceding stage numerator. A known negative records one bounded
blocker; required-fact `UNKNOWN` is separate. The primary blocker is the earliest material loss.
`DECISION_CASE_OPENED` counts only a future-blind formal `CANDIDATE` enrollment, not Review or
Abstain. Test count, runtime duration, object count, and UI rows are supporting evidence, not funnel
movement.
