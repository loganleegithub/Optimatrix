# Task — C1/C2 Branch Consolidation

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Runtime implementation:** REQUIRED only to recover the already completed isolated C1/C2
entrypoints into `main`; the deployed B3 and daily Review runtimes remain unchanged

**Live commands:** Git-only merge, commit, push, worktree removal, safe merged-branch deletion, and
worktree-prune operations are authorized for this repository. Existing offline repository checks
and disposable simulation roots are authorized. Market calls, credentials, account reads, orders,
process control, restart, deployment, and durable runtime access are forbidden.
No other process control is authorized.

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION.md`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`BTC_0DTE_TWO_SIDED_SHORT_VOL.md`](../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md),
[`CASE_POSITION_OUTCOME.md`](../docs/contracts/CASE_POSITION_OUTCOME.md), and
[`PRIMARY_SOURCES.md`](../docs/research/PRIMARY_SOURCES.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** `main` at `3de9ecb` contains the accepted B3/D1 system but does not contain the completed
C1/C2 source from `codex/c-recovered` at `d12fc4a`. That branch has two non-patch-equivalent commits,
five source modules, five focused test modules, two console entrypoints, and direct owner updates
that are absent from `main`. Two other development branches are already ancestors of `main`; three
development branches are still checked out by auxiliary worktrees, one of which contains an
obsolete partial C1 draft.

**When:** Merge `codex/c-recovered` into `main` with full ancestry, resolve its old Stage and owner
snapshots against the current B3/D1 truth, retain only the isolated C1 mainnet read-only capture and
C2 Testnet Combo probe with their direct tests and package entrypoints, verify the full repository,
then remove only proven merged worktrees, branches, and stale worktree metadata and push `main`.

**Then:** `d12fc4a`, `f82c989`, and `f247b28` are ancestors of `main`; the final tree contains the
isolated C1/C2 implementation without reverting current B3/D1 behavior or Authority; the repository
gate passes; local and remote branch inventories contain only `main`; and no credential, private
call, order, process, deployment, Policy, or durable runtime fact changes.

**Affected identity and population:** `NOT_APPLICABLE`; repository consolidation creates or mutates
no MarketObservation, DecisionWindow, OpportunityEpisode, TradeCase, Position, or Outcome fact.

**Baseline and denominator:** Three local development branches and three branch-owning auxiliary
worktrees. `codex/ai-lab-session-review` and `codex/c1-private-read-only` have zero commits outside
`main`; `codex/c-recovered` has exactly two. Remote `origin` has only `main`, while local `main` is
seven commits ahead before this task.

**Primary blocker and expected delta:** `SUBSTANTIVE_C1_C2_HISTORY_OUTSIDE_MAIN` changes to
`NONE`; obsolete branch/worktree count changes from three to zero without losing unique source or
uncommitted user content.

**Known-at and DataHealth boundary:** `NOT_APPLICABLE`; historical live C1/C2 evidence remains Git
history and is not promoted into a current connectivity, execution, fill, fee, Position, Policy, or
Edge claim.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** NONE

**Legacy-data effect:** NONE

**Permission effect:** NONE after closure; the recovered CLIs remain disabled unless a later exact
task and Stage authorize their bounded use.

**Files and behavior in scope:** `account.py`, `deribit_private.py`, `private_cli.py`,
`deribit_combo.py`, `combo_cli.py`; their five focused tests; `pyproject.toml`; direct package
guidance; the five owning Authority/contract/source-index files above; `tests/test_authority.py`;
this task and `CURRENT_STAGE`; local worktree and branch refs; and the `origin/main` push.

**Out of scope:** Credentials or credential discovery; live mainnet or Testnet calls; accounts,
orders, fills, capital, runtime roots, process control, deployment, B3 WebSocket changes, D1 logic,
Policy, qualification, promotion, repair, backfill, and Edge claims.

**Complexity added / deleted:** Recover exactly five already completed source modules, two console
entrypoints, five focused test modules, and their direct owner references with no new dependency;
delete three obsolete auxiliary branch worktrees, three merged branch refs, and three stale
worktree registrations.

## Verification and closure

**Cheapest falsification:** Run the five focused C1/C2 test modules and `tests/test_authority.py`,
then prove the merged ancestry and inspect the final owner/source diff for old Stage residue.

**Repository gate:** `make check`, `git diff --check`, clean status, ancestry checks for all three
development tips, local/remote ref enumeration, and `git worktree list`.

**External evidence:** Current official Deribit documentation is checked only for the fixed method,
scope, and parameter surfaces. Connectivity, account, order, fill, fee, Position, and deployment
evidence are `UNVERIFIED` because every live interface remains forbidden.
