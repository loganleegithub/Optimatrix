# Optimatrix Delivery Contract

**Status:** ACTIVE DEVELOPMENT AUTHORITY

**Applies to:** every code, contract, evidence, and documentation change

## Objective

Development is evidence-driven and depth-first. Each task closes one falsifiable business loop
without constructing a platform for later stages.

When an upstream business prerequisite can fail independently, close that prerequisite before the
downstream loop. Once evidence shows that the intended business behavior is unreachable, do not
expand reporting, replay, provenance, or durability to make the unreachable loop look complete.

## Task admission

A task is ready for implementation only when it states:

1. one business assertion to prove;
2. its task kind: `AUTHORITY_ONLY`, `IMPLEMENTATION`, or `EVIDENCE_ONLY`;
3. its active authority and current stage;
4. observable input and durable output;
5. exact in-scope and out-of-scope behavior;
6. all four change axes as `NONE` or an exact approved change;
7. direct behavioral tests;
8. an evidence matrix marking synthetic, bounded public, Radar reachability, live/replay, Outcome,
   and qualification evidence as `REQUIRED` or `NOT_APPLICABLE`;
9. valid zero-activity, `UNKNOWN`, and failure results;
10. whether each valid zero or `UNKNOWN` result satisfies or falsifies the business assertion;
11. claims the task explicitly cannot make;
12. product operating behavior separately from its bounded validation harness.

`AUTHORITY_ONLY` tasks default runtime edits, live commands, replay, and runtime artifacts to
`FORBIDDEN` or `NOT_APPLICABLE`. Prospective permission is implemented only by a later, separate
`IMPLEMENTATION` task.

Use [`../../tasks/TEMPLATE.md`](../../tasks/TEMPLATE.md). If these items cannot be
answered, clarify the contract before writing implementation code.

## Bounded change protocol

Before editing:

- read all authority and the task completely;
- inspect worktree, current branch, local HEAD, `origin/main`, and supplied anchors;
- preserve unrelated human changes without staging, reverting, or relocating them;
- create or use one bounded task branch;
- run `make sync` after checkout when implementation or repository tests consume the environment;
  a documentation-only task may declare it `NOT_APPLICABLE`;
- map requirements to owning modules, tests, and evidence.

During implementation:

- work in the owning module and keep the diff coherent and minimal;
- add a direct regression or boundary test before or with a behavioral fix;
- parse and validate external data at the boundary;
- keep pure domain calculations independent from network and filesystem I/O;
- preserve exact causality, missingness, lineage, and artifact identity;
- do not clean up unrelated code or add extension points for hypothetical callers.

After implementation:

- run focused behavioral tests first;
- run the full `make check` gate for implementation or shared-contract behavior; use focused
  authority/link checks for documentation-only changes;
- run task-specific public/live commands outside CI only when the evidence matrix requires them;
- inspect every claimed artifact rather than trusting process exit zero;
- independently replay sealed input in a fresh process only when applicable to the assertion;
- review both unstaged and staged diffs;
- leave the worktree clean after commit unless preserved human work predates the task.

## Change integrity

Every task declares these four axes independently:

```text
Market/Decision input contract change: NONE
Decision Policy change: NONE
Outcome/evaluation contract change: NONE
Stage/authorization change: NONE
```

`Market/Decision input contract` owns canonicalization, source validation, time domains,
causality, missingness, lineage, projection, readiness, freshness, tradability facts, and the
meaning of executable observations. Its changes require an explicit semantic contract identity
when persisted meaning changes, direct fail-closed tests, replay compatibility classification,
and a decision-drift classification. When no comparable complete historical Decision exists,
record `NOT_COMPARABLE`; do not manufacture a baseline by replaying a large unavailable dataset.
They are not automatically Policy changes.

`Decision Policy` is the immutable mapping from a valid DecisionFrame and executable inventory to
an action. It includes the approved structure/horizon universe, risk and insurance formulas,
thresholds, ranking, reserves, vetoes, and candidate eligibility. An approved change must identify
every old/new value or formula, create a new identity and digest, preserve the incumbent, and
pre-register evaluation before seeing claimed validation Outcomes.

`Outcome/evaluation contract` owns Shadow admission, entry, actual exposure, exit, executable PnL,
counterfactual paths, horizons, scoring, and qualification comparisons. Its changes require a new
artifact/contract identity and explicit comparability with historical Outcomes. Actual Shadow
Outcome tests enforce strictly post-Entry facts; rejected-opportunity counterfactual tests enforce
strictly post-Decision facts and the absence of exposure/fill/Policy-PnL claims.

`Stage/authorization` owns allowed environments, data sources, private/account surfaces,
promotion, execution, capital, and runtime permissions. It changes only through explicit human
authorization recorded in `CURRENT_STAGE.md`; implementation cannot grant it.

Changing one axis never silently changes another. Capture, replay, provenance, storage, and
reporting work must declare any behavioral effect on the first three axes rather than hiding it in
infrastructure scope.

## Evidence ladder

| Evidence | May prove | Does not prove |
|---|---|---|
| Direct unit/synthetic test | formula, boundary, fail-closed, causality | production data availability or strategy quality |
| Bounded public capture | real public connectivity and canonicalization | full warm-up, mature Outcome, or fills |
| Production Radar reachability | repeated real scans with usable global inputs and nonzero completed and Policy-evaluable assessment denominators | Policy value, mature Outcome, profitability, or qualification |
| Live/replay equality | deterministic reconstruction of the same sealed input | data completeness, Policy correctness, or profitability |
| Actual public Shadow Outcome | strictly post-entry public path and executable-quote close observation | rejected-opportunity value, strategy qualification, or actual fills |
| Rejected-opportunity counterfactual | strictly post-decision path under a pre-registered hypothetical rule | Shadow exposure, fills, observed Policy PnL, or qualification by itself |
| Pre-registered qualification vs `NO_TRADE` | result under that exact evidence contract | account or trading authority |
| Test/private execution receipt | order-path behavior in its named environment | production-capital authority |

Evidence classes never upgrade themselves. Old timestamps, schemas, Policies, or receipts may be
replay regression evidence without becoming fresh production or qualification evidence.

## Live evidence

When production-public evidence is required, report the fields consumed by that task's assertion.
For a full Radar/Shadow report, the minimum is:

- environment, capture format identity, duration, record and actual trade counts;
- current window coverage and readiness;
- gap, reconnect, platform, and source-time anomaly counts;
- due scan, executed-scan, global-risk-ready, universe-coverage, legal-structure, quote-observable,
  round-trip-executable, assessment-opportunity, completed-assessment, Policy-evaluable-assessment,
  passing-assessment, action, Entry, and Outcome counts, including zero;
- final event and DecisionFrame sequences;
- capture, frame, Policy, decision, and Outcome digests as applicable;
- independent recomputation or replay equality when its evidence class is `REQUIRED`, plus all
  evidence limitations.

CI must not depend on live Deribit. Live evidence is a task artifact, not a flaky repository gate.

## Independent replay

Independent replay means a fresh process reads a sealed artifact and reconstructs the result. It
does not mean querying the live in-memory projector twice.

Only a task whose evidence matrix marks replay `REQUIRED` inherits this section. Replay is scoped
to the sealed segments or window that can prove the task assertion. Each segment is read once,
validated with its contained facts, and then projected into the requested results; verification
must not reread a whole segment once per contained fact or replay unrelated history. It
reconstructs computation and artifact identity, not the external collection process.

Replay acceptance checks the capture or segment hash, causal sequence, requested frames, artifact
contract identities, Policy identity, lineage, and relevant digests. Matching digests are
necessary but do not establish input reachability, business qualification, or external-source
attestation.

## Denominator integrity

Business reports keep units and denominators distinct:

```text
cycle ledger:
  due scan cycles → executed cycles → globally risk-ready cycles → action cycles

structure ledger:
  legal structures → quote-observable structures → round-trip-executable structures

assessment ledger:
  assessment opportunities (legal structure × every configured horizon)
  → completed assessments → Policy-evaluable assessments → passing assessments

admission/outcome ledger:
  Candidate observations → admitted Entries → mature Outcomes
```

Rates name their numerator and conditioning denominator. Candidate observations, distinct
opportunity episodes, and admissions are different quantities. `NO_TRADE=0` is the no-position
comparator over the same usable cohort; it does not turn unavailable Policy value or null Outcome
PnL into zero. A denominator is numeric only when its upstream scope is known; otherwise it and
dependent rates are `null/UNKNOWN`, never zero.

## Review standard

Review the behavior, not only the diff:

- Does the implementation prove the task assertion?
- Is every upstream input needed by the assertion reachable in the authorized environment?
- Could missing evidence become zero, calm, open, or executable?
- Could `UNKNOWN` satisfy a task whose assertion requires usable assessment?
- Could future facts enter a Decision, pre-Entry facts enter an actual Outcome, or pre-Decision
  facts enter a rejected-opportunity counterfactual?
- Is a public quote presented as a real fill?
- Is a bounded evidence harness being mistaken for the product runtime lifecycle?
- Does the task declaration match every changed input, Policy, Outcome, or permission surface?
- Is new infrastructure consumed by this closure?
- Is governance or replay cost directly necessary to prove the business behavior?
- Are actual exposure and counterfactual analysis separated?
- Are evidence claims no stronger than the artifact permits?

## Git and PR contract

- One bounded branch and one task scope.
- Completed task files do not remain on `main`; commits, PRs, and durable receipts are the archive.
- Stage only files within the approved task scope.
- Do not reset, clean, overwrite, or delete unrelated human work.
- Record and verify task base/head and `origin/main` before rewriting any branch.
- Default to a Draft PR with business closure, scope/non-scope, all four change declarations,
  evidence-class `REQUIRED | NOT_APPLICABLE` states, applicable tests/artifacts, unknowns, and
  base/head. Attach live evidence, replay, or hashes only when their class is `REQUIRED`.
- Do not mark ready, merge, rewrite `main`, or delete refs without explicit authorization.
- After authorized push/merge/deletion, verify local and remote state directly.

## Definition of done

A task is done only when:

- the durable closure output exists;
- required direct behavior tests and applicable repository gates pass;
- every evidence class marked `REQUIRED`, including real evidence or fresh-process replay, passes;
- all four change declarations and current stage authority are satisfied;
- unknowns, non-claims, and zero-activity results are explicit;
- documentation and `CURRENT_STAGE.md` reflect the delivered reality;
- committed and remote scope match the task.
