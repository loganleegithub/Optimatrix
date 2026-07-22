# Task — Business closure

**Status:** DRAFT | ACTIVE

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):** exact link(s)

**Base commit:** exact SHA

**Target branch/PR:** exact branch and PR, if any

## Business closure

**Given:** one observable input or precondition.

**When:** one machine behavior occurs.

**Then:** one durable business output or receipt exists.

**Independent verification:** fresh process, sealed input, or another independent path.

**Valid zero/UNKNOWN result:** exact empty, unavailable, or fail-closed result.

## Change declarations

Declare every axis independently as `NONE` or `APPROVED`, then name the exact semantic contract
identity and behavioral delta. Follow
[`DELIVERY_CONTRACT.md`](../docs/authority/DELIVERY_CONTRACT.md#change-integrity).

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE

## Evidence boundary

**Proves:** ...

**Does not prove:** ...

**Evidence class:** `SYNTHETIC_LOGIC | BOUNDED_PUBLIC_CAPTURE | LIVE_REPLAY |
SHADOW_OUTCOME | QUALIFICATION | EXECUTION_ENVIRONMENT`

## Scope

**In:** ...

**Out:** ...

**Owning module/artifact:** ...

## Contract

**Inputs and known-at rule:** ...

**Durable output and identity:** ...

**Missing/invalid/UNKNOWN semantics:** ...

**Persisted contract identity/replay compatibility:** ...

## Acceptance

### Direct behavior

1. Given ... when ... then ...
2. Missing/invalid ... fails closed as ...
3. Causal and replay/Outcome boundary verifies ...

### Required commands

- `make sync`
- focused tests: ...
- `make check`
- task-specific inspect/replay/Outcome command: ...

### Real evidence

**Required:** YES | NO

**Environment and minimum duration:** ...

**Required report:** records and actual trades; coverage/readiness; gap/reconnect/platform/source
anomalies; actions/candidates/entries/Outcomes including zero; causal sequences; artifact digests;
fresh-process equality; limitations.

**Private API:** FORBIDDEN unless `CURRENT_STAGE.md` explicitly grants it.

## Artifacts and delivery report

**Capture/receipt/replay paths and hashes:** ...

**Policy/contract identities:** ...

**Commit/PR:** recorded by Git and the final delivery report; do not require a commit to contain
its own hash.

**Unknowns and non-claims:** ...

## Definition of done

The durable closure exists; direct tests, repository gates, required real evidence, and independent
verification pass; all four declarations are satisfied; limitations and zero activity are honest;
authority/status match reality; committed and remote scope contain only this closure; and the
completed task file is not retained on `main`. Delivery and Git safety remain governed by
[`DELIVERY_CONTRACT.md`](../docs/authority/DELIVERY_CONTRACT.md#git-and-pr-contract).
