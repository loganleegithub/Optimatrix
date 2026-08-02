# Optimatrix engineering map

## Purpose

Route one explicit business closure into the smallest coherent change. This file is not a second
constitution, incident archive, deployment controller, or evidence specification.

## Read route

Before work, read:

1. `docs/authority/PRODUCT_CONSTITUTION.md`
2. `docs/authority/CURRENT_STAGE.md`
3. `docs/authority/DELIVERY_CONTRACT.md`
4. the one active task under `tasks/`

Read `docs/authority/SYSTEM_ARCHITECTURE.md` before changing modules, dependencies, runtime state,
persistence, or deployment shape. Read only the owning implementation contract(s) for the changed
business boundary.

## Hard execution rules

1. Every task moves one product-funnel node, reduces its largest measured blocker, or removes a
   proven non-product subsystem that blocks the funnel.
2. Before editing, state the current funnel baseline, primary blocker, expected user-visible delta,
   durable-data effect, and complexity added/deleted. Test count and runtime duration are not
   product progress.
3. Before `SHADOW_CASE_OPENED`, durable business record count is zero. A task-specific diagnostic
   capture must stay outside the product path and cannot become a runtime dependency.
4. The Online Runtime owns current state and Shadow Cases, not qualification Cohorts. Cohort,
   aligned-pair, comparison, and Challenger datasets are derived offline.
5. `UNKNOWN` is a truthful current state, not a completion claim. Fix the largest funnel loss,
   whether it is `UNKNOWN`, known no-combo/no-credit, ineligibility, WATCH, or admission failure.
6. `UNKNOWN` cannot create Candidate or Shadow admission, but a bounded trader-facing review may
   show the opportunity, exact blocker, and upgrade condition.
7. Each external trust boundary has one input validator. Each business invariant has one owning
   calculator. Do not add a second schema, whole-history graph rebuild, or validator-of-validator.
8. Do not add application commissioning, host PID/log/`lsof`/launchd inspection, runtime self-
   acceptance, manifest, receipt chain, Workbench persistence, or host-resource gates.
9. When the same non-product control subsystem causes a second real run failure, default to delete
   or externalize it. Continue patching only when it protects current capital, account permission,
   or durable Shadow Case integrity.
10. Public-only engineering validation is direct tests, `make check`, and at most one explicitly
    authorized bounded read-only smoke. Strict independent audit belongs to qualification,
    promotion, and execution.
11. A proposed durable object must name its Shadow Case, direct human/AI consumer, and why it cannot
    be derived offline. Any missing answer prohibits the object.
12. A task is not complete unless it moves the funnel, lowers its primary blocker, improves the
    trader-visible product, or deletes net complexity. Green tests alone are insufficient.

## Repository discipline

Inspect branch, exact base, worktree, task scope, and remote state before editing. Preserve unrelated
work. Use one bounded branch and Draft PR. Stage only task files. Run focused tests and the full
repository gate. Report exact limitations and remote state; never infer permission from code or CI.

Completed tasks do not accumulate on `main`. Git is the engineering history; active Authority is
not an incident ledger.
