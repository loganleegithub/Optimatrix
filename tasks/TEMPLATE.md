# Task — Business closure

**Status:** DRAFT | ACTIVE

**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | EVIDENCE_ONLY

**Runtime implementation:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Live commands:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Base commit:** exact SHA

**Target branch/PR:** exact branch and PR

**Owning authority/contract:** exact link(s)

## Product movement

**Current funnel node:** exact node

**Baseline:** exact numerator, denominator, and unit

**Primary blocker:** exact measured reason or `NOT_YET_MEASURED`

**Expected user-visible delta:** exact change

**Durable-data effect:** `NONE` or exact Shadow Case record change

**Complexity added:** exact modules/protocols/dependencies, or `NONE`

**Complexity deleted:** exact obsolete surface, or `NONE`

## Business closure

**Given:** one observable prerequisite.

**When:** one bounded behavior or authority change occurs.

**Then:** one observable product result exists.

**Valid zero/UNKNOWN:** exact truthful result and whether it satisfies this closure.

**Cheapest falsification:** direct test, bounded observation, or other minimal check.

## Change declarations

**Market/Decision input contract change:** NONE | exact approved delta

**Decision Policy change:** NONE | exact approved delta

**Outcome/evaluation contract change:** NONE | exact approved delta

**Stage/authorization change:** NONE | exact approved delta

## Scope

**In:** exact files and behaviors

**Out:** exact forbidden changes

**Owning module:** exact owner

## Validation

- focused tests: exact command;
- repository gate: `make check` or exact applicable gate;
- public observation: exact command or `NOT_APPLICABLE`;
- no manifest, receipt, commissioning, or broad evidence package unless the owning stage is
  qualification, promotion, or execution.

## Definition of done

The declared user-visible or funnel delta exists, required checks pass, the diff is bounded, no
pre-Shadow durable record was introduced, complexity is proportional to the product value, and
remote state is reported accurately. Tests alone do not satisfy the task.
