# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:** `SELECTED_UNDERWRITING_DECISION_OUTCOME_ACTIVE`

**Accepted implementation boundary:** `COMPONENT_BOOK_SHADOW_LIFECYCLE_ACCEPTED`

**Production Short Vol Radar:** `CREDIBLE_CLUE_GENERATOR_FROZEN`

**Persistent service:** `NATURAL_PUBLIC_SHADOW_STOPPED_NO_DEPLOYMENT`

**Live commands:** `NONE_AUTHORIZED_PAIR_TIMING_PROBE_EXHAUSTED`

**Sole authorized closure:** `SHORT_VOL_SELECTED_UNDERWRITING_DECISION_OUTCOME`

## Current truth

The component-book Shadow lifecycle remains the accepted public-only implementation. It freezes one
protective long for each Radar Episode, prices both legs at target quantity from one causal public
boundary with adverse one-tick stress and both standard option fees, and keeps official Combo
discovery as a parallel diagnostic rather than a Candidate veto. Every component-book entry and
close requires exactly two strictly later `public/get_order_book` responses and remains a
counterfactual: `NOT_AN_ORDER`, `NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`,
`NO_LIQUIDITY_RESERVATION`, and `ATOMIC_EXECUTABILITY_UNPROVEN`.

The authorized natural public Shadow on code identity
`240a925288efe744cdf263f3fd61eb5a49f09ea8` stopped cleanly at explicit human request after
`10,307.658` seconds. Its final observed funnel was:

```text
APPLICABLE_MARKET_SCOPE                         1,812,600 contract evaluations
RADAR_KNOWN                                    1,811,662 contract evaluations
ANOMALY_ACTIVE                                        10 distinct Episodes
STRUCTURE_REVIEWABLE                                   7 distinct Episodes
COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE                7 distinct Episodes
UNDERWRITING_EVALUABLE                                 7 distinct Episodes
CANDIDATE                                               0 distinct Episodes
SHADOW_CASE_OPENED                                      0 Cases
SHADOW_CASE_OUTCOME                                     0 Outcomes
```

Post-warmup Radar loss was exactly `OPTION_BOOK_UNKNOWN 670` plus
`POST_STATUS_BOOTSTRAP_REQUIRED 268`, conserving the `938`-evaluation gap. Three Episodes were not
component-book evaluable because of `NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE 3`. All seven
Underwriting-evaluable Episodes stopped at `CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE 7`. Official Combo
diagnostics independently reported `NO_ACTIVE_COMBO 10`; this did not veto the component-book
path. No Candidate, Shadow Case, Outcome, or durable Case file was created.

The observation therefore established a working public component-book evaluation path and located
the measured conditional loss at the frozen future-cost reserve. It produced no Candidate/Case
sample and no Outcome sample, so it does not establish fillability, profitability, Policy edge,
qualification, deployment readiness, or private execution permission.

## Allowed work

- inspect the repository, accepted contracts, and final aggregate Shadow facts read-only;
- run deterministic offline tests and repository checks that do not contact a live venue;
- implement the one active task
  [`SHORT_VOL_SELECTED_UNDERWRITING_DECISION_OUTCOME`](../../tasks/SHORT_VOL_SELECTED_UNDERWRITING_DECISION_OUTCOME.md)
  without changing any economic threshold, fee, target quantity, or Radar screen.

## Forbidden work

- any public probe, public smoke, natural Shadow runtime, private/account API call,
  Combo creation, RFQ, order,
  fill, margin, balance, capital, deployment, commissioning, or actual exposure without a new
  active task and explicit authorization;
- changing Radar thresholds, benchmark, TTE/Delta universe, target quantity, reserve thresholds,
  or fees to manufacture a Candidate;
- automatically persisting every WATCH/ABSTAIN, selecting a control after seeing future facts, or
  counting a selected decision control as a Candidate/admitted-trade funnel conversion;
- treating component-book snapshots as an atomic execution, guaranteed simultaneous fill,
  liquidity reservation, or proof of strategy edge;
- database, replay platform, full-feed persistence, ML, SVI/Heston, GEX, microservice split,
  supervisor, automatic restart, host inspection, or operational control.

## Acceptance boundary

The component-book lifecycle, formal all-leg Underwriting selector, complete predicate-margin
truth, and fail-closed pair timing boundary are the accepted implementation baseline. The completed
observation remains a measured zero-Candidate market result, not a strategy qualification; its
seven decisions predate the formal selector and cannot calibrate the new path. The sole active
closure removes the selective-label dead end by designating at most one Episode from each causal
Radar activation batch before action or margin is known. Its first evaluable decision is observed
only after a strictly later valid paired refresh: a decision selected as Candidate and still
Candidate reuses ordinary admission, while every other evaluable selection may open an explicitly
tagged no-trade control Case. The canonical
Candidate funnel remains unchanged. Completion requires offline direct tests and repository checks;
no live command or Shadow runtime is authorized.
