# Optimatrix Agent contract

## Job

Complete one authorized business closure with the smallest coherent final system. Documents in this
repository are instructions for Agents: read only the current task and its exact owner, do not
reconcile every document before acting.

Authority defines product intent and permission. Source defines current implementation; tests and
direct observations provide evidence about it. If these layers conflict, record the conflict as the
task blocker instead of changing whichever layer is easier. Reports, screenshots, memory, package
text, and prior CI are leads only.

## Route before any write

1. Read `docs/authority/CURRENT_STAGE.md`.
2. If it links an active task, read that one task.
3. Read only the owner needed by that task:
   - product identity, thesis, evidence semantics, or permanent boundary:
     `docs/authority/PRODUCT_CONSTITUTION.md`;
   - modules, dependencies, transient state, or persistence location:
     `docs/authority/SYSTEM_ARCHITECTURE.md`;
   - Session, MarketContext, Policy decision, structure, funnel, or Entry result:
     `docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`;
   - Decision Case, Position, remediation, terminality, Outcome, or recovery:
     `docs/contracts/SHADOW_LIFECYCLE.md`.

When the Stage says `NONE`, read-only discovery and existing offline checks are allowed. The only
repository-file writes allowed are creation of one task from `tasks/TEMPLATE.md` and the matching
Stage link. Every other write waits for that activation.

## One task and one permission boundary

`CURRENT_STAGE` and `tasks/` must agree exactly: `NONE` means only the template exists; otherwise
exactly one non-template task is `ACTIVE` and linked from the Stage.

- `AUTHORITY_ONLY` may change Agent instructions, Authority, contracts, task templates, and their
  direct tests. It may not change runtime behavior or run live commands.
- `IMPLEMENTATION` may change one bounded behavior and its direct documentation and tests.
- `VALIDATION_ONLY` may observe an already-implemented behavior but may not hide an implementation,
  Policy, or schema change.

The Stage is the permission ceiling; the task may only narrow it. A live call, durable root,
continuous process, private method, account action, or deployment requires matching, exact text in
both. Technical capability is not permission.

An active task states the observable Given/When/Then, owner, unit, baseline/denominator, earliest
blocker, expected delta, known-at/source boundary, durable and legacy effects, bounded files,
complexity added/deleted, and the cheapest falsification. Use `NOT_YET_MEASURED` rather than inventing
a baseline.

## Product guardrails

- The sole implemented product is one same-Deribit-Session, two-sided, four-leg, defined-risk BTC
  premium sale. A Vertical is a component, not a fallback product.
- The denominator is one `SessionDecisionUnit`; options, legs, candidates, quotes, retries, and UI
  rows do not multiply opportunities.
- Required missing, stale, contradictory, or causally ineligible facts remain `UNKNOWN`; they do
  not become zero, calm, Candidate, Entry, flat risk, or terminality.
- `FULL_ENTRY` requires one coherent four-leg attempt. Partial short exposure enters remediation,
  never normal carry.
- A Gap, restart, unavailable market, or failed quote does not erase a Position.
  `SHORT_RISK_FLAT` and `PORTFOLIO_TERMINAL` are different facts.
- Public Shadow facts are counterfactual observations, not orders, fills, account exposure,
  realized PnL, reserved liquidity, Edge, or Policy qualification. Legacy V2 state remains outside
  this product.

Exact definitions belong to the linked product or lifecycle owner. Do not expand these guardrails
into a second specification.

## Implementation rule

Search the current owner, code, tests, manifest, lockfile, and direct references before changing
them. Reuse a fitting implementation first; otherwise make the smallest direct local change. Every
new abstraction, option, dependency, durable fact, retry, and file must serve the active acceptance
criterion and an existing direct consumer. Build nothing for a hypothetical product, caller,
scale, migration, deployment, or failure mode.

Remove obsolete code, tests, documents, configuration, and references in the same change. Do not
leave a compatibility path or archive unless the current task has a consumer for it. Preserve
unrelated user work.

## Verification and closure

Use the cheapest check that can falsify the declared delta, then run the materially affected
repository gate. Inspect the final diff and references. Green tests, object counts, document counts,
and prior runtime evidence do not by themselves prove product progress, live reachability, Edge, or
completion.

A task closes only after its declared product, trader-visible, blocker, or complexity delta is
directly observed. Replace `CURRENT_STAGE` with the post-task current snapshot, remove the completed
task, and report any unavailable external check as `UNVERIFIED`. Git retains history; Authority does
not.
