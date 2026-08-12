# Task — BTC 0DTE Position Risk causal exit

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Base commit:** `4716b8714e3a85e1affb0236167b1db08e271a27`

**Target branch/PR:** `codex/position-risk-causal-exit` / local bounded closure

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/contracts/SHADOW_LIFECYCLE.md`

## Product movement

**Canonical unit:** one `FULL_ENTRY` Decision Case Position with live short risk

**Current funnel node:** post-`ENTRY_RESULT_KNOWN` Position duty toward
`DECISION_CASE_OUTCOME_KNOWN`

**Baseline:** `0 / 1` deterministic full-entry Positions keep risk-trigger intent and the first
executable exit observation on separate causal boundaries

**Primary blocker:** `EXIT_INTENT_AND_EXECUTABLE_SAMPLE_SHARE_BOUNDARY`

**Expected user-visible/funnel delta:** `1 / 1` risk-trigger observations create one durable,
two-sided `EXIT_REQUIRED` duty while leaving both shorts open; only a strictly later eligible public
book observation may flatten short risk, and an unknown or blocked observation leaves the duty
visible

**Known-at/source boundary:** `PositionInstruction.at`; exit quotes must have source and receive
times strictly later than that boundary and meet the existing full-quantity/coherence rules

**Durable-data effect:** reuse material `POSITION_CHECKPOINT` facts for intent and later exit
transition; no per-tick event or new event kind. Consumers are restart duty, trader review, and
Outcome latency/blocker fields

**Legacy-data access effect:** NONE

**Complexity added:** one bounded risk-observation result, one explicit five-second Position quote-
freshness budget, and strict-future exit eligibility in the existing lifecycle owner

**Complexity deleted:** same-observation trigger-and-exit and missing-short-quote-as-zero-Delta

## Business closure

**Given:** one fixed-Policy `FULL_ENTRY` public-Shadow Position with both shorts open.

**When:** a bounded observation triggers a risk exit or cannot establish required short-risk facts.

**Then:** the Position freezes one two-sided exit duty without using that observation as an exit;
the next strictly future eligible sample may reduce short risk, while a blocked sample preserves the
same duty and exact blocker.

**Valid zero/UNKNOWN:** zero exits at the trigger boundary is required; missing, stale, incoherent,
or unexecutable future quotes leave `EXIT_REQUIRED` and do not satisfy `SHORT_RISK_FLAT`.

**Cheapest falsification:** deterministic lifecycle scenarios for same-boundary trigger,
strictly-future exit, missing short quote, and blocked future depth.

## Change declarations

**Market/Decision input contract change:** exit price projections require strictly future quotes

**Decision Policy change:** full-Condor normal-carry triggers request both sides; partial-entry
remediation remains scoped; five-second quote age controls observation knownness, not Alpha

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** bounded Shadow reducer only; no runtime/private/order/fill/hedge

## Scope

**In:** lifecycle, composition, existing Position checkpoint codec, contract, scenarios and focused
tests

**Out:** Radar, thresholds, WebSocket/daemon, account/order/fill, Delta hedge, AI, stable root

**Owning module:** `src/optimatrix/lifecycle.py`

## Validation

- focused tests: `pytest -q tests/test_lifecycle.py tests/test_persistence.py`;
- deterministic business scenario: `python -m optimatrix simulate`;
- repository gate: `make check`;
- public observation: NOT_APPLICABLE;
- legacy-root reference/access check: `rg` over `src tests`;
- no manifest, receipt, commissioning, or evidence platform.

## Definition of done

The same observation cannot trigger and execute an exit; UNKNOWN never becomes calm; normal carry
preserves two-sided responsibility; a future eligible sample can flatten short risk; responsibility
survives restart; no runtime/new event kind exists; and this task is removed after `CURRENT_STAGE`
records the product result. Green tests alone do not satisfy the task.
