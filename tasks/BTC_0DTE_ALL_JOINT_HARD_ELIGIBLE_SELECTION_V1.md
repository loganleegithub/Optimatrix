# Task — BTC 0DTE all-joint hard-eligible selection

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Base commit:** `72c5606`

**Target branch/PR:** `codex/radar-risk-admission` / local bounded closure

**Owning authority/contract:** `docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`,
`docs/authority/SYSTEM_ARCHITECTURE.md`

## Product movement

**Canonical unit:** `SessionDecisionUnit`

**Current funnel node:** `ENTRY_ROUTE_EVALUABLE`

**Baseline:** `0 / 1` adversarial units select the only joint Condor that passes hard economics and
full-quantity stressed short-buyback depth; current top-three side pruning or post-selection
underwriting hides it

**Primary blocker:** `JOINT_HARD_ELIGIBLE_CANDIDATE_NOT_SEARCHED`

**Expected user-visible/funnel delta:** enumerate every legal combination inside the already bounded
chain, apply joint hard admission and both-short buyback readiness before rank, and select only from
the passing set; an empty passing set stops at `ENTRY_ROUTE_EVALUABLE` with exact blockers

**Known-at/source boundary:** the same evidence-qualified Decision-boundary public books and fixed
Policy; buyback readiness is a present public-book counterfactual, not a future liquidity guarantee

**Durable-data effect:** NONE; selection remains transient before `DECISION_OPENED`

**Legacy-data access effect:** NONE

**Complexity added:** one candidate-level hard-admission result owned by `structure.py`

**Complexity deleted:** single-side top-N pruning and duplicate post-selection underwriting

## Business closure

**Given:** one evidence-qualified current-Session bounded chain with multiple legal Put and Call
Verticals.

**When:** Radar selects the one joint structure worth considering for risk.

**Then:** every legal four-leg combination is built, hard-underwritten, and checked for both-short
full-quantity stressed public buyback depth before any ranking; only passing candidates can be
selected.

**Valid zero/UNKNOWN:** zero hard-passing structures is a known `ENTRY_ROUTE_EVALUABLE` rejection
with precise candidate blockers; missing MarketContext remains the earlier `UNKNOWN` gate.

**Cheapest falsification:** one adversarial chain where the old fourth-ranked side component is the
only joint hard pass, and one chain whose sell-side entry books exist but one short lacks buyback ask
depth.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** remove the unsafe top-N selector field and rotate the unqualified Policy
identity; all numeric risk thresholds remain unchanged

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE; no live command or durable write

## Scope

**In:** structure enumeration, candidate hard admission, Decision-boundary short buyback readiness,
Radar/funnel projection, Policy shape/identity, contract, deterministic business acceptance

**Out:** entry-attempt refresh, combo/RFQ execution, private data, lifecycle, persistence, scheduler,
AI, threshold calibration

**Owning module:** `src/optimatrix/structure.py`

## Validation

- focused structure/Radar/funnel/Policy/business tests;
- repository gate: `make check`;
- public observation: NOT_APPLICABLE;
- legacy-root reference/access check: `rg` over `src tests`;
- no alternative selector, liquidity service, or second underwriting owner.

## Definition of done

The adversarial denominator moves from `0 / 1` to `1 / 1`; no hard-failing or buyback-unready
candidate can be selected; empty eligibility lands at the route node with exact blockers; Policy
identity rotates; net selector/config complexity falls; and this task is deleted after
`CURRENT_STAGE` records the result. Green tests alone do not satisfy the task.
