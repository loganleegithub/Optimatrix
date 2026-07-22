# Optimatrix Delivery Contract

**Status:** ACTIVE DEVELOPMENT AUTHORITY

**Applies to:** every code, contract, evidence, and documentation change

## Objective

Development is evidence-driven and depth-first. Each task closes one falsifiable business loop
without constructing a platform for later stages.

## Task admission

A task is ready for implementation only when it states:

1. one business assertion to prove;
2. its active authority and current stage;
3. observable input and durable output;
4. exact in-scope and out-of-scope behavior;
5. all four change axes as `NONE` or an exact approved change;
6. direct behavioral tests;
7. required synthetic, bounded, live, Outcome, and replay evidence;
8. valid zero-activity, `UNKNOWN`, and failure results;
9. claims the task explicitly cannot make.

Use [`../../tasks/TEMPLATE.md`](../../tasks/TEMPLATE.md). If these items cannot be
answered, clarify the contract before writing implementation code.

## Bounded change protocol

Before editing:

- read all authority and the task completely;
- inspect worktree, current branch, local HEAD, `origin/main`, and supplied anchors;
- preserve unrelated human changes without staging, reverting, or relocating them;
- create or use one bounded task branch;
- run `make sync` after checkout;
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
- run the full `make check` gate;
- run task-specific public/live commands outside CI when required;
- inspect every claimed artifact rather than trusting process exit zero;
- independently replay sealed input in a fresh process when applicable;
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
and a decision-drift report. They are not automatically Policy changes.

`Decision Policy` is the immutable mapping from a valid DecisionFrame and executable inventory to
an action. It includes the approved structure/horizon universe, risk and insurance formulas,
thresholds, ranking, reserves, vetoes, and candidate eligibility. An approved change must identify
every old/new value or formula, create a new identity and digest, preserve the incumbent, and
pre-register evaluation before seeing claimed validation Outcomes.

`Outcome/evaluation contract` owns Shadow admission, entry, actual exposure, exit, executable PnL,
counterfactual paths, horizons, scoring, and qualification comparisons. Its changes require a new
artifact/contract identity, strict post-entry tests, and explicit comparability with historical
Outcomes.

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
| Live/replay equality | deterministic reconstruction of the same sealed input | data completeness, Policy correctness, or profitability |
| Future-only public Shadow Outcome | post-decision public path and executable-quote close observation | strategy qualification or actual fills |
| Pre-registered qualification vs `NO_TRADE` | result under that exact evidence contract | account or trading authority |
| Test/private execution receipt | order-path behavior in its named environment | production-capital authority |

Evidence classes never upgrade themselves. Old timestamps, schemas, Policies, or receipts may be
replay regression evidence without becoming fresh production or qualification evidence.

## Live evidence

When production-public evidence is required, report at minimum:

- environment, capture format identity, duration, record and actual trade counts;
- current window coverage and readiness;
- gap, reconnect, platform, and source-time anomaly counts;
- action, candidate, entry, and Outcome counts, including zero;
- final event and DecisionFrame sequences;
- capture, frame, Policy, decision, and Outcome digests as applicable;
- independent replay equality and all evidence limitations.

CI must not depend on live Deribit. Live evidence is a task artifact, not a flaky repository gate.

## Independent replay

Independent replay means a fresh process reads a sealed artifact and reconstructs the result. It
does not mean querying the live in-memory projector twice.

Replay acceptance checks the capture hash, causal sequence, current final frame, artifact contract
identities, Policy identity, lineage, and relevant digests. Matching digests are necessary but do
not establish business qualification.

## Review standard

Review the behavior, not only the diff:

- Does the implementation prove the task assertion?
- Could missing evidence become zero, calm, open, or executable?
- Could future facts enter a Decision or pre-entry facts enter an Outcome?
- Is a public quote presented as a real fill?
- Does the task declaration match every changed input, Policy, Outcome, or permission surface?
- Is new infrastructure consumed by this closure?
- Are actual exposure and counterfactual analysis separated?
- Are evidence claims no stronger than the artifact permits?

## Git and PR contract

- One bounded branch and one task scope.
- Completed task files do not remain on `main`; commits, PRs, and durable receipts are the archive.
- Stage only files within the approved task scope.
- Do not reset, clean, overwrite, or delete unrelated human work.
- Record and verify task base/head and `origin/main` before rewriting any branch.
- Default to a Draft PR with business closure, scope/non-scope, all four change declarations,
  tests, live evidence, replay, hashes, unknowns, and base/head.
- Do not mark ready, merge, rewrite `main`, or delete refs without explicit authorization.
- After authorized push/merge/deletion, verify local and remote state directly.

## Definition of done

A task is done only when:

- the durable closure output exists;
- direct behavior tests and repository gates pass;
- required real evidence and fresh-process replay pass;
- all four change declarations and current stage authority are satisfied;
- unknowns, non-claims, and zero-activity results are explicit;
- documentation and `CURRENT_STAGE.md` reflect the delivered reality;
- committed and remote scope match the task.
