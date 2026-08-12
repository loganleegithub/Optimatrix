# Optimatrix Delivery Contract

**Status:** ACTIVE DEVELOPMENT AUTHORITY

## Purpose

Deliver the smallest change that moves one canonical product-funnel stage, reduces its earliest
material blocker, improves the trader-visible explanation, or deletes a proven non-product obstacle
without losing business truth. Tests, scenarios, objects, documents, manifests, archive digests,
runtime duration, and green CI are supporting evidence, never substitutes for product progress.

## One-active-task route

Every change has exactly one semantic task based on `tasks/TEMPLATE.md`.

```text
CURRENT_STAGE task kind = NONE
  ⇔ tasks/ contains TEMPLATE.md only

CURRENT_STAGE task kind != NONE
  ⇔ exactly one non-template task is ACTIVE
     and CURRENT_STAGE links that exact task
```

Task kinds are:

- `AUTHORITY_ONLY`: Authority, contracts, task template, and direct Authority checks only;
- `IMPLEMENTATION`: one bounded product or domain behavior;
- `VALIDATION_ONLY`: one already-implemented, explicitly authorized observation or offline
  evaluation, with no hidden product or Policy change.

The current rebuild uses the existing active `IMPLEMENTATION` task as its construction authority.
Completed tasks are removed; Git and the PR provide development history.

## Required task statement

Before editing, the active task declares:

1. observable Given / When / Then;
2. canonical `SessionDecisionUnit` funnel node;
3. exact numerator, denominator, and unit, or `NOT_YET_MEASURED`;
4. earliest measured primary blocker;
5. expected user-visible or funnel delta;
6. exact source and known-at boundary;
7. durable-data effect and direct consumer;
8. bounded files and one owning module;
9. input, Decision Policy, Outcome/evaluation, and authorization changes;
10. complexity added and deleted;
11. legacy-data access effect, which must remain `NONE` in the current stage;
12. cheapest check capable of falsifying the claimed delta.

If an upstream prerequisite is absent, that prerequisite is the task. Do not build reporting,
storage, replay, compatibility, or later-stage objects around an unreachable funnel path.

## Product progress gate

A task is complete only when at least one is directly observed:

- one canonical funnel stage becomes reachable or measurably improves;
- the earliest material blocker is reduced or made precisely attributable;
- the trader receives a materially more truthful current product explanation;
- a non-product subsystem that blocked progress is removed with no loss of product truth.

Green tests alone never satisfy this gate. Package build, manifest, and archive integrity may support
a release handoff but do not grant product, persistence, live-market, deployment, or execution
authority.

## Canonical funnel measurement

The funnel counts `SessionDecisionUnit`, never legs, options, quotes, Verticals, structures, retries,
journal events, or UI rows. Each stage denominator is the previous stage numerator. Known negatives
and required-fact unknowns remain separate. The primary blocker is the earliest material loss.

A valid zero requires complete scope and a known positive denominator. A zero denominator or absent
measurement produces `null` rate and `NOT_YET_MEASURED`, not a successful zero. A short public
snapshot may validate current reachability and source shape; it may not estimate market frequency or
tune thresholds.

## UNKNOWN and blocker semantics

`UNKNOWN` is a truthful current state, never zero, calm, REVIEW, CANDIDATE, entry, flat risk, or
terminality.

- source/currentness unknown: repair or expose the exact source blocker;
- forecast/model uncertainty: reduce confidence and block any stage for which the fact is required;
- four-leg coherence unknown: block `FULL_ENTRY`, not the visibility of the attempted structure;
- combo absence: report `ON_DEMAND_COMBO_LIQUIDITY_UNOBSERVED`, not impossibility;
- post-enrollment Gap: preserve responsibility and mark observation quality; do not synthesize an
  exit or erase known terminal economics;
- settlement missing: remain `SETTLEMENT_PENDING`;
- acquisition `NO_ENTRY`, `WINGS_ONLY`, `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`, and
  `TWO_SIDES_INCOHERENT` are known outcomes, not UNKNOWN.

## Decision Case data boundary

Before `DECISION_OPENED`, authoritative durable business writes are forbidden. Public facts,
candidate structures, scores, blockers, attempts not selected by the Policy, snapshot results,
Workbench views, service facts, and run summaries remain non-durable.

One future-blind `CANDIDATE` may open one Decision Case before acquisition results exist. The Case
must freeze the product, Policy, `SessionDecisionUnit`, selected four legs, full quantity, decision
boundary, entry-attempt contract, and non-claims. Every later event is append-only, identity-bound,
and strictly future. Normal ticks and rejected candidate history are never persisted.

Authorized new-product journal facts are limited to the owning lifecycle contract. A proposed fact
must name:

1. its already-open Decision Case;
2. its direct restart, trader-review, AI-outcome, or later offline-evaluation consumer;
3. why it cannot be derived truthfully from existing Case facts.

No answer means no record. A bounded public snapshot performs zero durable writes.

## Entry and Outcome eligibility gate

One entry attempt is one four-leg causal unit. Only `FULL_ENTRY` enters normal carry and the primary
strategy-Outcome denominator. `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`, and `TWO_SIDES_INCOHERENT` enter
immediate remediation; `WINGS_ONLY` enters residual-wing management; `NO_ENTRY` creates no Position. None may be relabelled
as a full Condor.

Decision evaluability, entry-result knownness, strategy-Outcome eligibility, terminal-economics
eligibility, continuous-path eligibility, and qualification eligibility are separate. Qualification
Cohorts, controls, aligned comparisons, Challenger datasets, and promotion decisions are later
offline, pre-registered views, not online journal facts.

## Legacy isolation

The current product may not read, write, import, translate, migrate, relabel, recover, or count the
legacy V2 repository, runtime checkout, Policies, Case schema, stable Case root, or 92 Cases. A local
Decision journal requires an explicitly supplied non-legacy root. No stable new-product root or
compatibility branch is authorized.

## Validation proportionality

Use the cheapest path that can falsify the exact claim:

- pure classifier, formula, identity, or state rule: direct tests;
- composition and lifecycle: deterministic end-to-end scenario;
- persistence: direct append/read/conflict/recovery tests in a temporary root;
- public source shape or current reachability: at most one active-task-authorized bounded read-only
  snapshot after offline gates pass;
- Policy qualification or promotion: later pre-registered independent evaluation;
- private execution: later account/order/fill reconciliation and capital controls.

The normal implementation gate is focused tests, full repository checks, deterministic business
scenarios, compilation/build checks where applicable, final diff/reference inspection, and exact
reporting of unavailable external checks. A failed or unavailable layer remains unverified.

## Single-owner and operations boundary

Each external trust boundary has one validator and each business invariant one calculator. Do not
add a second schema, validator-of-validator, whole-history graph, replay platform, database, message
bus, generic N-leg framework, browser-side formula, commissioning controller, host-resource gate,
or runtime self-acceptance system.

The application has no authority to inspect or control launchd/systemd/Docker/Kubernetes, PID/log
inventories, runtime age, or host acceptance. A later continuous runtime, stable root, private API,
account, order, fill, capital, or execution path requires a new active task and explicit permission.

## Implementation discipline

- preserve unrelated human work;
- keep one active task and one bounded branch/PR closure;
- use direct modules and no speculative extension points;
- keep Policy changes explicit and content-identified;
- remove obsolete V2 strategy paths rather than hiding them behind translators;
- stop when the declared business acceptance passes;
- report the product delta first, then checks and exact gaps.
