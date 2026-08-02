# Task — Rewrite authority around Shadow Case data

**Status:** ACTIVE

**Task kind:** AUTHORITY_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Base commit:** `53e02f042c9a3b4d04f0e347d6ba069cb8860a30`

**Target branch/PR:** `agent/shadow-case-data-boundary` / Draft PR #18

## Business closure

**Given:** the current authority treats Radar and pre-Shadow decisions as durable evidence and
rewards proof production even when the product funnel does not advance.

**When:** the active authorities and implementation contracts are rewritten as one consistent
product/data boundary.

**Then:** pre-Shadow state is explicitly in-memory, `SHADOW_CASE_OPENED` is the first durable
business object, online runtime owns no qualification Cohort, and every future task must move one
measured funnel node or remove its largest blocker.

**Verification:** direct authority/link/architecture tests and full offline tests.

**Valid zero/no-hit/UNKNOWN result:** real-time `UNKNOWN` remains truthful, but it is never a task
completion claim and must be attributed as one possible funnel blocker.

## Change declarations

**Market/Decision input contract change:** APPROVED — persistence begins only after explicit Shadow
Case enrollment; market sources and Policy inputs do not change.

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** APPROVED — online Cohort/aligned-pair persistence is removed
from the authority; Cohorts become offline derived views.

**Stage/authorization change:** APPROVED — old implementation is disabled pending the matching data
boundary implementation; live commands remain forbidden.

## Scope

**In:** Product Constitution, Current Stage, System Architecture, Delivery Contract, implementation
contracts, AGENTS, README, architecture note, task template, direct authority tests.

**Out:** Python runtime, Policies, dependencies, Deribit commands, private/account/order/fill/capital.

## Evidence boundary

**Proves:** the repository has one unambiguous data boundary and anti-defensive-development stop
rules.

**Does not prove:** implementation conformance, live Radar quality, funnel conversion, Shadow Case
reachability, strategy value, or execution permission.

## Acceptance

- authority tests pass;
- all repository tests remain green;
- active normative prose is net smaller;
- no manifest, receipt, commissioning, Soak, Radar-event persistence, or online Cohort requirement
  remains;
- no production code or Policy changes.
