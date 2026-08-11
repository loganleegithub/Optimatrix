# Optimatrix Delivery Contract

**Status:** ACTIVE DEVELOPMENT AUTHORITY

## Purpose

Deliver the smallest product change that moves one measured business-funnel node, reduces its
largest measured blocker, or deletes a proven non-product obstacle. Verification is proportional
to the claim. Tests, receipts, object counts, document counts, runtime duration, and operational
proof are never substitutes for product progress.

## Task route

Every change has exactly one active semantic task created from [`tasks/TEMPLATE.md`](../../tasks/TEMPLATE.md).
The task is read after the Product Constitution, Current Stage, this contract, the System
Architecture when structure changes, and the owning implementation contract.

Task kinds:

- `AUTHORITY_ONLY`: authority, contracts, task template, README, and direct authority tests only;
- `IMPLEMENTATION`: one bounded runtime or domain behavior;
- `VALIDATION_ONLY`: one already-implemented public-only observation or qualification evaluation,
  with no code or Policy changes.

Completed tasks are removed from the final tree. Git and the PR provide engineering history;
product runtime files do not archive development process.

## Required task statement

Every task declares:

1. observable Given / When / Then;
2. current funnel node and baseline;
3. largest measured blocker and its denominator;
4. expected user-visible or funnel delta;
5. exact source/known-at boundary;
6. durable-data effect, including why any new record cannot be derived;
7. direct verification and non-claims;
8. bounded files and one owning module;
9. all four change axes: input, Decision Policy, Outcome/evaluation, authorization;
10. complexity added and complexity deleted.

If the upstream prerequisite is absent, that prerequisite is the task. Do not build reporting,
storage, replay, schemas, or later-stage objects around an unreachable path.

## Product progress gate

A task is complete only when at least one is true:

- one funnel stage becomes reachable or measurably improves;
- the largest measured blocker is reduced or made precisely attributable;
- the trader receives a materially better current opportunity explanation;
- a non-product subsystem that blocked progress is removed with no loss of product truth.

Green tests alone never satisfy this gate.

## Data boundary

Pre-Shadow persistence is forbidden by default.

Before `SHADOW_CASE_OPENED`, durable business writes are forbidden by default. Market facts,
Radar, anomalies, component-book counterfactuals, atomic diagnostics, Underwriting, Candidate,
admission attempts, Workbench, funnel metrics, service state, and run summaries remain non-durable.

A new durable record is permitted only when both answers are explicit:

1. Which already-open Shadow Case owns it?
2. Which trader/AI research or qualification computation consumes it directly and why can it not be
   derived from existing Case records?

No answer means no record.

Current permitted durable kinds are only:

```text
SHADOW_CASE_OPENED
SHADOW_CASE_SEGMENT_OPENED
SHADOW_CASE_SEGMENT_CLOSED
SHADOW_CASE_FIRST_CLOSE / FIRST_CLOSE_INTENT_LATCHED
SHADOW_CASE_OUTCOME
```

Immutable legacy `FIRST_CLOSE_AND_ATTEMPT_SCHEDULED` bytes remain valid reader input. New exit
acquisition attempts are bounded in-memory facts and cannot become a second durable history merely
to support retry.

The Observation Segment pair is owned by an already-open admitted Entry. The Online Runtime,
trader Workbench, and AI Researcher consume its runtime provenance, adoption/end boundaries,
predecessor, and `CONTINUOUS | GAPPED` quality. Those facts cannot be derived from
`SHADOW_CASE_OPENED` or Outcome because process start, stop, failure, and unobserved intervals occur
later. Segment records are not service receipts or per-tick checkpoints.

Qualification Cohorts, aligned pairs, comparison tables, Challenger features, and denominators are
offline derived views, not Online Runtime records.

## Unknown and blocker semantics

`UNKNOWN` remains a truthful current state, never zero, calm, WATCH, ABSTAIN, or a Candidate.
However, `UNKNOWN` is not a delivery outcome. The task must attribute the largest funnel loss,
which may instead be known absence or ineligibility.

Keep these distinct:

- source/currentness `UNKNOWN`: repair or expose the source blocker;
- model/forecast uncertainty: lower confidence without erasing a reviewable opportunity;
- component-book counterfactual `UNKNOWN`: block Shadow admission, not trader display;
- post-enrollment unknown/censoring: valid durable research result.

## Validation proportionality

Use the cheapest path that can falsify the exact claim:

- pure formula, classifier, identity, or state rule: direct tests;
- integration/composition: deterministic end-to-end fixture;
- public source shape/cadence/revision assumptions: one explicitly authorized bounded source
  contract probe;
- public source connectivity and current-state reachability: one explicitly authorized bounded
  read-only integration smoke;
- Shadow Case persistence: direct write/read/crash-incomplete tests;
- cross-process Position recovery: two successive restart fixtures over one stable Case repository,
  segment ordering/gap truth, immutable first-CLOSE intent, continuing bounded acquisition,
  future-Control recovery, official settlement, and named gapped-Outcome Cohort tests;
- Challenger qualification or Policy promotion: later pre-registered independent evaluation;
- private execution: later account/order/fill reconciliation and capital controls.

For public-only implementation, the normal gate is:

```text
focused tests
make check
at most one explicitly authorized source-contract probe when an undocumented provider behavior is material
at most one explicitly authorized bounded read-only integration smoke when current reachability is the claim
```

This is a maximum validation shape, not standing live authority. `CURRENT_STAGE` and the one active
task may forbid every probe, smoke, service start, or restart, or may authorize one exact bounded
public-only topology. A consumed or failed one-start topology grants no retry.

Public-only validation does not require a manifest, receipt chain, fresh empty evidence directory,
commissioning controller, host probe, 24-hour Soak, replay, full-market archive, independent commit
ceremony, or post-push acceptance ledger.

A rare natural market event is not a software-readiness prerequisite unless the user explicitly
makes that occurrence the product claim. Neither a short probe nor a short smoke may be used to tune
thresholds, demand a clue, or estimate strategy frequency.

## Single-owner validation rule

Each external trust boundary has one production validator and each business invariant has one
production calculator. Tests may independently exercise pure functions, but production must not
add:

- a second schema for owner-generated objects;
- prospective whole-history relationship validation;
- provenance/manifest graphs around typed output;
- validator-of-validator or writer/readback proof on every transition;
- Markdown-byte digests as runtime business identities.

The exact three Policy artifacts remain content-identified because they change decisions. Source
code is identified by commit. Durable record format uses an explicit schema version.

## Operations boundary

The application may expose health, readiness, current state, and funnel diagnostics. It may not:

- manage or inspect launchd/systemd/Docker/Kubernetes;
- execute `lsof`, OS log queries, PID inventories, or host resource acceptance;
- decide whether it has been online long enough;
- generate commissioning, operability, or acceptance receipts.

Process supervision, restart decision, CPU, memory, logs, and deployment are external operational
concerns. Rehydrating admitted Entry business state when an externally started process opens the
stable repository is application behavior, not process supervision.

## Two-strike deletion rule

When the same non-product control subsystem causes a second real runtime failure, the next task is
a delete-or-externalize review. Local repair is forbidden unless the task proves that removal would
cause an incorrect trader decision, lose an admitted Shadow Case, or expose actual account/capital
risk.

## Implementation discipline

- preserve unrelated human work;
- one branch and one Draft PR for the combined requested closure;
- no speculative platform or abstraction;
- no dependency addition when a direct function or typed state suffices;
- no hidden Policy change inside input, persistence, reporting, or performance work;
- profile the direct owning function before a second performance architecture;
- stop when the declared acceptance passes.

## Public/private boundary

Public-only code may use authorized Deribit public facts and public quote calls. It may not contain
or infer credentials, balances, margin, orders, fills, actual positions, capital, or execution
permission. Visible public quotes remain counterfactual.

## Definition of done

The declared funnel/product delta exists; direct and repository checks pass; invalid and
`UNKNOWN` cases remain truthful; pre-Shadow durable writes are zero; any Case record has one direct
consumer; the diff contains no unrelated infrastructure; complexity and remaining blocker are
reported; and no authority is inferred from a test or commit.
