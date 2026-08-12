# Task — Business closure

**Status:** DRAFT | ACTIVE

**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | VALIDATION_ONLY

**Runtime implementation:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Live commands:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Base commit:** exact SHA

**Target branch/PR:** exact branch and PR

**Owning authority/contract:** exact link(s)

`CURRENT_STAGE` must link this file while it is the sole `ACTIVE` non-template task. No placeholder
may remain when status becomes `ACTIVE`.

## Product movement

**Canonical unit:** `SessionDecisionUnit` or exact other Authority-owned unit

**Current funnel node:** exact canonical stage

**Baseline:** exact numerator, denominator, and unit, or `NOT_YET_MEASURED` with reason

**Primary blocker:** exact earliest measured reason or `NOT_YET_MEASURED`

**Expected user-visible/funnel delta:** exact change

**Known-at/source boundary:** exact causal input boundary

**Durable-data effect:** `NONE` or exact Decision Case event change and direct consumer

**Legacy-data access effect:** `NONE` unless a later Authority explicitly changes isolation

**Complexity added:** exact modules/protocols/dependencies, or `NONE`

**Complexity deleted:** exact obsolete surface, or `NONE`

## Business closure

**Given:** one observable prerequisite.

**When:** one bounded behavior or Authority change occurs.

**Then:** one observable product result exists.

**Valid zero/UNKNOWN:** exact truthful result, denominator semantics, blocker, and whether it
satisfies the closure.

**Cheapest falsification:** direct test, deterministic scenario, bounded observation, or other
minimal check.

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
- deterministic business scenario: exact command or `NOT_APPLICABLE`;
- repository gate: `make check` or exact applicable gate;
- public observation: exact authorized command or `NOT_APPLICABLE`;
- legacy-root reference/access check: exact command;
- no manifest, receipt, commissioning, or broad evidence package unless the owning stage is an
  external release, qualification, promotion, or execution audit.

## Definition of done

The declared user-visible or funnel delta is directly observed; the canonical denominator and
earliest blocker remain truthful; required checks pass; the diff is bounded; durable facts stay
inside the Decision Case contract; legacy isolation remains intact; complexity is proportional to
product value; live authorization and remote state are reported accurately; and this task is
removed after `CURRENT_STAGE` records the accepted result. Tests alone do not satisfy the task.
