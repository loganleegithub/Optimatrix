# Task — Business closure

**Status:** DRAFT | ACTIVE

**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | EVIDENCE_ONLY

**Runtime implementation:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Live commands:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):** exact link(s)

**Base commit:** exact SHA

**Target branch/PR:** exact branch and PR, if any

## Business closure

**Given:** one observable business precondition.

**When:** one bounded authorized behavior or authority change occurs.

**Then:** one observable business result or durable object exists.

**Independent verification:** the cheapest independent path that can falsify this exact assertion.

**Valid zero/no-hit/UNKNOWN result:** exact empty or unavailable behavior; state whether it
satisfies, leaves incomplete, or falsifies this assertion.

**Upstream prerequisite:** the smallest independently falsifiable capability that must already
exist. If it is not established, make that prerequisite the task.

## Change declarations

Declare every axis independently as `NONE` or `APPROVED`, then name the exact semantic identity
and behavioral delta. A storage, replay, provenance, or report change may not hide its effect.

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE

## Product operating behavior

Describe the ongoing lifecycle independently of validation commands: live source, bounded current
state, relevant-state trigger, unchanged-state behavior, durable output, downstream handoff, and
asynchronous work.

Name which facts are transient or durable and keep observed, counterfactual, and actual execution
states separate when they apply.

## Validation harness

Describe the smallest direct test, public observation, minimal snapshot recomputation, or sealed
sample needed to prove the assertion. A duration, file, cutoff, archive, or process lifetime never
becomes product cadence, opportunity identity, or holding behavior.

## Evidence boundary

**Proves:** ...

**Does not prove:** ...

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED \| NOT_APPLICABLE |
| Production-public Radar | REQUIRED \| NOT_APPLICABLE |
| Minimal-hit recomputation | REQUIRED \| NOT_APPLICABLE |
| Bounded stream reconstruction | REQUIRED \| NOT_APPLICABLE |
| Shadow forward Outcome | REQUIRED \| NOT_APPLICABLE |
| Qualification | REQUIRED \| NOT_APPLICABLE |
| Execution | REQUIRED \| NOT_APPLICABLE |

## Scope

**In:** ...

**Out:** ...

**Owning module/artifact:** ...

## Contract

**Inputs and known-at rule:** ...

**Durable output and identity:** ... | `NOT_APPLICABLE`

**Missing/invalid/UNKNOWN semantics:** ...

**Persisted meaning and compatibility:** semantic identity, fields, units, readers, and
`COMPATIBLE | MIGRATION_REQUIRED | NOT_COMPARABLE` | `NOT_APPLICABLE`

**Business denominators:** name numerator, denominator, unit, scope, conditioning event, and null
behavior. Do not count implementation work or repeated observations as business units.

## Acceptance

### Direct behavior

1. Given ... when ... then ...
2. Missing/invalid ... fails closed as ...
3. Duplicate/unchanged/re-arm/causal boundary behavior ... | `NOT_APPLICABLE`

### Required commands

- `make sync` | `NOT_APPLICABLE` with reason
- focused tests: ...
- `make check` or exact applicable authority gate
- production-public command: ... | `NOT_APPLICABLE`
- independent recomputation or reconstruction command: ... | `NOT_APPLICABLE`

### Real evidence

**Required:** YES | NO

**Environment and stopping condition:** use a business event or human stop when appropriate; do
not substitute a predetermined duration for a natural market condition.

**Required report:** only fields needed to prove the assertion, plus limitations and non-claims.

**Private API:** FORBIDDEN unless `CURRENT_STAGE.md` explicitly grants it.

## Artifacts and delivery report

**Artifact paths and digests:** ... | `NOT_APPLICABLE`

**Policy/contract identities:** ...

**Commit/PR:** recorded by Git and the final delivery report; a commit does not contain its own
future hash.

**Unknowns and non-claims:** ...

## Definition of done

The business closure exists; all four declarations match authority; direct behavior and every
required evidence class pass; zero/no-hit/UNKNOWN results are honest; final diff and artifacts
contain only this closure; limitations and remote state are reported; and no stage is inferred
from green checks or a Draft PR. Git and safety remain governed by
[`DELIVERY_CONTRACT.md`](../docs/authority/DELIVERY_CONTRACT.md#git-and-pr-contract).
