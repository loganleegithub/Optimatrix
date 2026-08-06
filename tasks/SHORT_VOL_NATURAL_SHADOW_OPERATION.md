# Task — Natural public Shadow operation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** COMPLETED — an ended Episode is retired only after its active Candidate
is terminalized by the Underwriting owner at the same settled boundary; bounded public smoke remains

**Live commands:** REQUIRED — one short public smoke, then one natural public Shadow runtime until human stop

**Base commit:** `553f763df77737e15ffe07879ad344070a567111`

**Target branch/PR:** `codex/component-book-shadow-lifecycle` / Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md) and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `CANDIDATE → SHADOW_CASE_OPENED`

**Baseline:** the first natural runtime reached `21` Radar Episodes, `17` reviewable/component-book/
Underwriting-evaluable Episodes, and `1` Candidate. A transport retirement then ended the owning
Episode while that Candidate remained active, causing a fatal integrity failure before the Case
opening transition could settle.

**Primary blocker:** `ended Radar episode still owns an active Candidate` at the Episode-retirement
owner boundary.

**Expected user-visible delta:** an ended Episode terminalizes its Candidate and paired refresh
attempt before retirement, so transport recovery cannot kill the runtime or leave admission state
owned by an ended clue.

**Durable-data effect:** zero writes before admission; only an admitted Case may own opened,
first-close, and Outcome records.

**Complexity added:** none; the existing Underwriting owner settles its existing Candidate
lifecycle before releasing Episode-owned state.

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
