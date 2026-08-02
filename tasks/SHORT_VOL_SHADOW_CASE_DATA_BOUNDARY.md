# Task — Implement the Shadow Case data boundary

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Base commit:** `77d9d67`

**Target branch/PR:** `agent/shadow-case-data-boundary` / Draft PR #18

**Owning authority/contract:**
`docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md`, and
`docs/contracts/SHORT_VOL_SHADOW_CASE.md`

## Product movement

**Current funnel node:** `CANDIDATE → SHADOW_CASE_OPENED`

**Baseline:** current legacy runtime writes Radar and downstream files before any Shadow admission.

**Primary blocker:** persistence is attached to computation internals rather than explicit Shadow
Case enrollment.

**Expected user-visible delta:** Workbench continues to show current Radar/Underwriting state, while
disk contains only admitted Shadow Cases and their future outcomes.

**Durable-data effect:** pre-Shadow durable records become exactly zero; the only durable kinds are
`SHADOW_CASE_OPENED`, `SHADOW_CASE_FIRST_CLOSE`, and `SHADOW_CASE_OUTCOME`.

**Complexity added:** one bounded Shadow Case writer/reader.

**Complexity deleted:** Radar file writer, downstream filesystem writer, contract-byte identities,
automatic rejected-counterfactual enrollment, online aligned-pair persistence, and filesystem-backed
Workbench/anchor discovery.

## Business closure

**Given:** the fixed public-only Radar/Underwriting/Position chain settles current state.

**When:** no Shadow admission occurs, or an admitted Candidate opens and later terminates one Case.

**Then:** the first path writes zero business files; the second writes exactly one opened record,
at most one first-CLOSE record, and at most one terminal Outcome.

**Valid zero/UNKNOWN:** zero Shadow admissions is valid and produces zero durable records. A Case
opened before an unclean process loss is read as `INCOMPLETE_UNCLEAN_EXIT`.

**Cheapest falsification:** deterministic end-to-end owner/service tests plus the full repository
gate.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** APPROVED — replace internal-object persistence with the
minimal Shadow Case records; remove automatic rejected controls and online aligned pairs.

**Stage/authorization change:** NONE — live remains forbidden.

## Scope

**In:** Radar current event sink, Underwriting in-memory state store, Shadow Case store/reader,
owner/adapter/Workbench/service composition, direct tests, current contract-conformance tests.

**Out:** Policy bytes or thresholds, Deribit source semantics, private/account/order/fill/capital,
Cohort qualification, cross-runtime recovery, database, replay, event bus, commissioning, manifest,
or receipt chain.

## Validation

- focused Case/owner/service tests;
- all offline tests;
- GitHub `make check`;
- public observation: `NOT_APPLICABLE`.

## Definition of done

No pre-Shadow code path writes a product file; one admitted Case has bounded durable cardinality and
a minimal reader; Workbench/active ownership use in-memory typed state; fixed Policies and public
market semantics are unchanged; the implementation remains live-disabled.
