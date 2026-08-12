# Optimatrix Product Constitution

**Status:** ACTIVE PRODUCT AUTHORITY — STANDALONE LOCAL-VALIDATION CANDIDATE

**Long-term product:** autonomous 0–3DTE options decision and future trading system

**Current product:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

## Product and non-replacement boundary

Optimatrix is arranged as a fixed 2x2 Channel roadmap:

| Product | Short Vol | Long Gamma |
| --- | --- | --- |
| Inverse BTC | `IMPLEMENTED` | `RESERVED / UNIMPLEMENTED` |
| Inverse ETH | `RESERVED / UNIMPLEMENTED` | `RESERVED / UNIMPLEMENTED` |

The sole implemented Channel is `INVERSE_BTC_SHORT_VOL`. The other descriptors create no Policy,
selector, owner, Case codec, runtime, task, permission, or generic extension mechanism.

This branch is an isolated new-product candidate. It does not replace, migrate, reinterpret, or
operate the preceding V2 runtime or its historical Cases. The legacy repository, deployment
checkout, Policies, Case schema, and Case root remain outside this product boundary.

## North-star product question

For the option expiry ending the current Deribit `08:00–08:00 UTC` settlement Session:

> Is executable same-session implied variance rich enough relative to the forecast physical path,
> and is Theta monetizable quickly enough, while Gamma, jump, event, directional-breakout,
> concentrated-strike, and liquidity risks remain tolerable for a two-sided defined-risk sale?

The canonical structure is one asymmetric four-leg Iron Condor:

```text
buy lower-strike Put
sell higher-strike Put
sell lower-strike Call
buy higher-strike Call
```

The Put and Call Credit Verticals are reusable pricing and acquisition components. Neither a single
Vertical nor two independently selected Vertical scores are the product.

## Strategy identity

```text
Executable Session VRP       reason to sell
Theta capture                monetization speed
Range survival               probability-quality filter
Gamma / jump / event state   primary loss filter
Execution quality            whether the joint premium is collectible
```

The score is an ordinal filtering hypothesis, not a calibrated probability, expected return, Edge,
or sufficient condition for profit. High premium cannot compensate for a live event, shock,
concentrated-strike breakout, accelerating path, incoherent four-leg snapshot, or unavailable risk
exit.

## Session and canonical decision unit

An option is 0DTE only when its expiry equals the end of the current Deribit settlement Session at
`08:00 UTC`. Each fact belongs to one `MarketSessionId` and one phase:

```text
ROLL_REPRICE
CORE_CARRY
LATE_THETA
EXIT_ONLY
DELIVERY_TWAP
```

The initial phase boundaries are launch priors, not qualified sweet-zone claims.

The sole product-funnel counting unit is:

```text
SessionDecisionUnit =
  product_spec_identity
  + MarketSessionId
  + decision_window_identity
  + Decision Policy identity
```

One unit may inspect many options, Verticals, quotes, and joint structures, but the fixed Policy may
designate at most one primary four-leg structure. Legs, structures, refreshes, acquisition routes,
retries, journal records, and Workbench rows never multiply the opportunity denominator.

## Canonical product funnel

```text
APPLICABLE_SESSION_DECISION
→ MARKET_CONTEXT_KNOWN
→ VRP_THETA_QUALIFIED
→ GAMMA_JUMP_BREAKOUT_RISK_ACCEPTABLE
→ TWO_SIDED_STRUCTURE_EVALUABLE
→ ENTRY_ROUTE_EVALUABLE
→ ENTRY_ATTEMPT_SELECTED
→ DECISION_CASE_OPENED
→ ENTRY_RESULT_KNOWN
→ DECISION_CASE_OUTCOME_KNOWN
```

Each stage denominator is the preceding stage numerator. A known negative consumes that stage and
records one bounded blocker. Required-fact `UNKNOWN` is reported separately. The primary blocker is
the earliest material loss in the canonical funnel, not the largest later fraction. Tests, scenario
count, runtime duration, and durable object count are not funnel movement.

`DECISION_CASE_OPENED` counts only a future-blind formal entry-attempt enrollment. Review or Abstain
does not open a Case. The Case freezes the selected product, Policy, SessionDecisionUnit, four-leg
structure, causal decision boundary, and non-claims before acquisition results are known.

## Four-leg attempt coherence and entry truth

One selected entry attempt has one attempt identity, full target quantity, decision boundary,
attempt boundary, and bounded source/receive coherence budget across all four selected legs.
`FULL_ENTRY` requires every selected leg to be acquired at full quantity inside that same attempt.
Two Verticals acquired under unrelated or later attempts cannot be combined into a synthetic full
Condor.

The strictly later entry result is exactly one of:

```text
FULL_ENTRY
PUT_SIDE_ONLY
CALL_SIDE_ONLY
TWO_SIDES_INCOHERENT
WINGS_ONLY
NO_ENTRY
```

- `FULL_ENTRY` alone may enter normal Short Vol carry and become eligible for primary strategy
  Outcome evaluation.
- `PUT_SIDE_ONLY` and `CALL_SIDE_ONLY` contain unintended live short risk. They bypass normal carry,
  enter bounded partial remediation immediately, and remain ineligible for the primary full-Condor
  Outcome.
- `TWO_SIDES_INCOHERENT` preserves two separately observable side acquisitions whose combined
  four-leg attempt violated the cross-side coherence budget. Both sides enter remediation; the
  result is never a full Condor or strategy Outcome.
- `WINGS_ONLY` contains no short risk. It enters residual-wing management and is ineligible for the
  primary full-Condor Outcome.
- `NO_ENTRY` creates no Position but remains a known acquisition Outcome of the Decision Case.

An unknown or incoherent acquisition result cannot be converted to any of these known states.

## Position, remediation, and terminal truth

Partial remediation prioritizes removing unintended short risk. It may acquire missing protection
only when the same fixed Policy explicitly declares that route and all new facts are causally
eligible; it may not wait indefinitely to manufacture the intended Condor. A dangerous short may be
bought back independently when its wing lacks a bid.

Remediation can improve or flatten the residual portfolio, but it never changes the frozen
`ENTRY_TERMINAL` classification, promotes the Case to `FULL_ENTRY`, opens normal carry, or makes the
Case eligible for the primary full-Condor strategy Outcome.

```text
SHORT_RISK_FLAT      no short option remains open
PORTFOLIO_TERMINAL   every residual long wing is sold or officially settled
```

`SHORT_RISK_FLAT` does not imply `PORTFOLIO_TERMINAL`. Process loss, stale data, a Gap, one failed
exit attempt, or a missing wing bid does not synthesize either state or a terminal Outcome.

## Eligibility dimensions

The system keeps these independent:

```text
decision_evaluable
entry_result_known
strategy_outcome_eligible
terminal_economics_eligible
continuous_path_eligible
qualification_eligible
```

A primary `TWO_SIDED_SHORT_VOL` strategy Outcome requires `FULL_ENTRY` and a terminal result under
the frozen Policy. Partial, wings-only, and no-entry Cases remain valuable acquisition evidence but
cannot enter the primary strategy-return denominator. A Gap can disqualify continuous-path analysis
without erasing known terminal economics. Qualification remains a later, offline, pre-registered
view; the product runtime cannot approve itself.

## UNKNOWN and known-zero truth

`UNKNOWN` means a required fact is missing, stale, discontinuous, malformed, contradictory, outside
its causal budget, or numerically unresolved. It is never zero, calm, eligible, Candidate, Entry,
flat risk, or terminality. `NOT_YET_MEASURED` identifies an absent business denominator.

A business zero is valid only when its scope is complete and its denominator is known and positive.
`ON_DEMAND_COMBO_LIQUIDITY_UNOBSERVED` means only that private/on-demand liquidity was not publicly
observable. It does not prove the structure impossible.

## Data classes and isolation

Translated public market facts, formula outputs, rejected structures, Radar state, and Workbench
projections are bounded transient state. Before `DECISION_OPENED`, authoritative durable business
record count is zero. The bounded public snapshot adapter never opens or writes a Case.

The current local candidate may write a Decision journal only beneath an explicitly supplied,
non-legacy test or simulation root. It has no authorized stable Case root. It must not read, write,
translate, migrate, relabel, recover, count, or import the legacy V2 Case root or its 92 Cases. No
legacy Case is Iron Condor evidence.

## Public Shadow boundary and non-claims

The current permission is deterministic offline Shadow simulation plus at most one task-authorized,
bounded, read-only public Deribit snapshot. The product contains no credentials, private/account API,
balance, margin, order, fill, liquidity reservation, RFQ, combo creation, capital, actual exposure,
settlement action, continuous service, or deployment authority.

A public or component-book price is a counterfactual, not a fill. A Decision Case is a simulated
research enrollment, not an account position. Current Policies are unqualified and do not establish
Edge, Alpha, profitability, win probability, or execution readiness.

## Learning truth

The current candidate writes only the primary `TWO_SIDED_SHORT_VOL` arm. It does not pretend that a
durable `SINGLE_SIDE_VERTICAL_BASELINE` or `NO_TRADE_CONTROL` exists. A later research task may add
aligned offline comparisons without changing Base truth. Same-Session structures are clustered
rather than counted as independent events. AI may propose a Challenger; it cannot rewrite Base,
select its own favorable denominator, qualify itself, or grant execution permission.
