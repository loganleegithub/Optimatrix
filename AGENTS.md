# Optimatrix Agent contract

## Job

Complete one authorized business closure with the smallest coherent final system. Repository
documents are instructions for Agents, not a narrative archive.

Authority defines product intent, identity, ownership, and permission. Source defines current
implementation. Tests and direct observations provide evidence. When these layers conflict, record
the conflict in the active task and `CURRENT_STAGE`; never change the easier layer to hide it.
Reports, screenshots, memory, package text, and prior CI are leads only.

## Route before any write

1. Read `docs/authority/CURRENT_STAGE.md`.
2. If it links an active task, read that task.
3. Read only the owner required by the task:
   - permanent product, thesis, truth layers, evidence semantics, or isolation:
     `docs/authority/PRODUCT_CONSTITUTION.md`;
   - current maturity, permission, active task, or next blocker:
     `docs/authority/CURRENT_STAGE.md`;
   - modules, dependencies, state location, or record boundaries:
     `docs/authority/SYSTEM_ARCHITECTURE.md`;
   - MarketObservation, DecisionWindow, OpportunityEpisode, environment, structure, risk allocation,
     Decision, or Entry truth: `docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`;
   - TradeCase, Position, monitoring, exit, Outcome, recovery, or learning protocol:
     `docs/contracts/CASE_POSITION_OUTCOME.md`;
   - exchange or API fact: `docs/research/PRIMARY_SOURCES.md`;
   - task fields: `tasks/TEMPLATE.md`.
4. For an implementation task, then inspect the owning source, tests, manifest, lockfile, and direct
   references.

`README.md` is package guidance, not Authority. Do not restate owner-defined business semantics in
this file or reconcile unrelated owners before acting.

When Stage says `NONE`, read-only discovery and existing offline checks are allowed. The only
repository writes allowed are creation of one task from `tasks/TEMPLATE.md` and the matching Stage
activation. Every other write waits for that activation.

## One task and one permission boundary

`CURRENT_STAGE` and `tasks/` agree exactly: `NONE` means only the template exists; otherwise exactly
one non-template task is `ACTIVE` and linked from Stage.

- `AUTHORITY_ONLY` may change Agent instructions, Authority, contracts, the external-source index,
  task templates, and their direct structural tests. It may not change runtime behavior or run live
  commands.
- `IMPLEMENTATION` may change one bounded behavior and its direct documentation and tests.
- `VALIDATION_ONLY` may observe an implemented behavior but may not hide an implementation, Policy,
  schema, or permission change.

Stage is the permission ceiling; the task may only narrow it. Market calls, durable roots,
continuous processes, private methods, accounts, orders, fills, capital, deployment, and Policy
promotion each require exact authorization in both. A maturity-stage name grants no permission.
An active task must replace every template placeholder before other writes begin.

## Change rule

Implement only the active acceptance criterion. Do not prebuild a later maturity stage, alternate
product, generic framework, migration, deployment, or hypothetical failure path. Reuse a fitting
current owner first; otherwise make the smallest direct change. Every new abstraction, option,
dependency, durable fact, retry, and file needs a current consumer.

Remove only surfaces made obsolete by the active criterion. Keep no compatibility alias or archive
without a verified consumer. Preserve unrelated user work.

## Verification and closure

Run the cheapest falsification, then the materially affected repository gate. Inspect the final
diff, owner references, and obsolete residue. Green tests, counts, and prior runtime evidence do not
prove product progress, market reachability, Edge, or completion.

Close only after directly observing the declared business, blocker, or complexity delta. Replace
`CURRENT_STAGE` with the post-task snapshot, remove the task, and report unavailable external checks
as `UNVERIFIED`. Git retains history; Authority does not.
