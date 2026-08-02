# Task — Business closure

**Status:** DRAFT | ACTIVE

**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | EVIDENCE_ONLY

**Runtime implementation:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Live commands:** REQUIRED | FORBIDDEN | NOT_APPLICABLE

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):** exact link(s) | `NOT_APPLICABLE`

**Base commit:** exact SHA

**Target branch/PR:** exact branch and PR | `NOT_APPLICABLE`

## Business closure

**Given:** one observable precondition.

**When:** one bounded authorized behavior or authority change occurs.

**Then:** one observable result or durable business object exists.

**Verification:** the cheapest independent path that can falsify this assertion.

**Valid zero/no-hit/UNKNOWN result:** exact behavior and whether it satisfies the assertion.

**Upstream prerequisite:** the smallest independently falsifiable required capability.

## Change declarations

Declare each axis as `NONE` or name the exact approved semantic delta.

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE

## Product operating behavior

State the current source, bounded state, trigger, unchanged-state behavior, durable output, and
downstream handoff. Keep observed, counterfactual, and actual execution states separate.

## Scope

**In:** ...

**Out:** ...

**Owning module/artifact:** ...

## Validation harness

Name only the direct tests or observations required by the closure. Validation duration and files
do not become product cadence or business identity.

## Evidence boundary

**Proves:** ...

**Does not prove:** ...

## Acceptance

- Focused tests: ...
- Repository gate: `make check` | exact applicable gate
- Public observation: exact command | `NOT_APPLICABLE`
- Required artifacts/digests: ... | `NOT_APPLICABLE`
- Honest zero/no-hit/UNKNOWN and non-claims are reported.

## Definition of done

The closure exists, all four declarations match authority, required checks pass, the diff contains
only this closure, remote state is reported when changed, and no permission is inferred from tests
or a commit.
