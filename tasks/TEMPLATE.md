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

**Given:** one observable input or precondition.

**When:** one bounded behavior or authority change occurs.

**Then:** one durable business output, contract, or receipt exists.

**Independent verification:** one assertion-appropriate independent path. Require a fresh process
or sealed replay only when its evidence class is `REQUIRED`.

**Valid zero/UNKNOWN result:** exact empty, unavailable, or fail-closed result, and whether it
satisfies or falsifies this business assertion.

**Upstream prerequisite:** the smallest independently falsifiable input or capability that must
already be reachable. If it is not established, make that prerequisite the task instead.

## Change declarations

Declare every axis independently as `NONE` or `APPROVED`, then name the exact semantic contract
identity and behavioral delta. Follow
[`DELIVERY_CONTRACT.md`](../docs/authority/DELIVERY_CONTRACT.md#change-integrity).

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE

## Product operating behavior

Describe the intended ongoing lifecycle independently of any bounded validation command: fact
capture, state, trigger/cadence, Decision, admission, and asynchronous Outcome behavior.

## Validation harness

Describe the smallest bounded observation, fixture, replay, or authority check that can prove the
task assertion, or `NOT_APPLICABLE`. Its duration, cutoff, bundle, or process lifetime does not
become product behavior.

## Evidence boundary

**Proves:** ...

**Does not prove:** ...

Mark every class independently:

| Evidence class | Requirement |
|---|---|
| Direct synthetic/behavior | REQUIRED \| NOT_APPLICABLE |
| Bounded public capture | REQUIRED \| NOT_APPLICABLE |
| Production Radar reachability | REQUIRED \| NOT_APPLICABLE |
| Fresh-process replay | REQUIRED \| NOT_APPLICABLE |
| Shadow Outcome | REQUIRED \| NOT_APPLICABLE |
| Qualification | REQUIRED \| NOT_APPLICABLE |
| Execution environment | REQUIRED \| NOT_APPLICABLE |

## Scope

**In:** ...

**Out:** ...

**Owning module/artifact:** ...

## Contract

**Inputs and known-at rule:** ...

**Durable output and identity:** ...

**Missing/invalid/UNKNOWN semantics:** ...

**Persisted contract identity/replay compatibility:** ... | `NOT_APPLICABLE`

**Business denominators:** name every numerator, unit, and conditioning denominator. Keep scan
cycles, structures, structure-by-horizon assessment opportunities, completed and Policy-evaluable
assessments, actions, Entries, and mature Outcomes distinct, or mark `NOT_APPLICABLE`.

## Acceptance

### Direct behavior

1. Given ... when ... then ...
2. Missing/invalid ... fails closed as ...
3. Applicable causal/replay/Outcome boundary verifies ... | `NOT_APPLICABLE`

### Required commands

- `make sync` | `NOT_APPLICABLE` with reason
- focused tests: ...
- `make check` or exact applicable authority/document gate
- task-specific inspect/replay/Outcome command: ... | `NOT_APPLICABLE`

### Real evidence

**Required:** YES | NO

**Environment and minimum duration:** ...

**Required report:** only fields that prove the assertion. For a full Radar/Shadow report include
records and actual trades; due scans and funnel denominators; coverage/readiness;
gap/reconnect/platform/source anomalies; actions/candidates/entries/Outcomes including zero;
causal sequences; applicable artifact digests; fresh-process equality when required; limitations.

**Private API:** FORBIDDEN unless `CURRENT_STAGE.md` explicitly grants it.

## Artifacts and delivery report

**Capture/receipt/replay paths and hashes:** ... | `NOT_APPLICABLE`

**Policy/contract identities:** ...

**Commit/PR:** recorded by Git and the final delivery report; do not require a commit to contain
its own hash.

**Unknowns and non-claims:** ...

## Definition of done

The durable closure exists; required direct tests, applicable repository gates, evidence classes,
and independent verification pass; all four declarations are satisfied; limitations and zero
activity are honest; authority/status match reality; committed and remote scope contain only this
closure; and the completed task file is not retained on `main`. Delivery and Git safety remain
governed by
[`DELIVERY_CONTRACT.md`](../docs/authority/DELIVERY_CONTRACT.md#git-and-pr-contract).
