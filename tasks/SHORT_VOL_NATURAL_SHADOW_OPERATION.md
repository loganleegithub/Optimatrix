# Task — Natural public Shadow operation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** NOT_PLANNED — a proven defect requires changing this declaration before editing code

**Live commands:** REQUIRED — one short public smoke, then one natural public Shadow runtime until human stop

**Base commit:** `553f763df77737e15ffe07879ad344070a567111`

**Target branch/PR:** `codex/component-book-shadow-lifecycle` / Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md) and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE → SHADOW_CASE_OUTCOME`

**Baseline:** the accepted 600-second smoke reached current public market state but contained no
natural Radar Episode, Candidate, Shadow Case, or Outcome.

**Primary blocker:** no naturally occurring sample has yet exercised the frozen component-book
Candidate, paired admission, and future Outcome path.

**Expected user-visible delta:** naturally occurring Radar Episodes either expose an exact bounded
component/Underwriting blocker or progress into reviewable Shadow Cases and future Outcomes.

**Durable-data effect:** zero writes before admission; only an admitted Case may own opened,
first-close, and Outcome records.

**Complexity added:** none in the product runtime.

**Complexity deleted:** no fixed-duration completion claim, automatic restart, or operational
acceptance layer.

## Business closure

**Given:** the accepted frozen code and Policy chain has passed offline gates and a short public
smoke.

**When:** one natural public-only service receives market facts until a human requests stop or a
fatal failure terminates it.

**Then:** every funnel transition, Case, and Outcome remains attributable to current public facts;
zero activity remains a valid market result; a fatal failure is repaired offline before a new
identity is smoked and restarted.

**Valid zero/UNKNOWN:** zero Episode/Candidate/Case/Outcome is valid. Missing or stale required
facts remain bounded `UNKNOWN` and cannot create admission.

**Cheapest falsification:** current Workbench/funnel facts and admitted Case records; no host,
process-resource, replay, or commissioning evidence.

## Change declarations

**Market/Decision input contract change:** none.

**Decision Policy change:** none; all thresholds, universe, target quantity, fees, and reserves stay
frozen.

**Outcome/evaluation contract change:** none.

**Stage/authorization change:** authorize a short-smoke failure loop and one public-only natural
Shadow runtime until explicit human stop.

## Failure loop

An observed fatal failure censors that runtime. Diagnose its innermost business/source owner
offline. Before any code edit, change this task to `IMPLEMENTATION`; make the smallest repair, run
focused tests and `make check`, commit the identity, and repeat the short public smoke. Resume
natural Shadow only after that smoke terminates readably. Do not tune Policy or add a supervisor.

## Definition of done

The task remains active while natural Shadow is authorized. Human stop ends the current runtime
cleanly. Runtime duration, zero activity, or record count alone does not qualify the strategy or
grant execution authority.
