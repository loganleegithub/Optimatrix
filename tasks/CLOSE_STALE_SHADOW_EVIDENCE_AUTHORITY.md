# Task — Close stale Shadow evidence authority prose

**Status:** ACTIVE

**Task kind:** AUTHORITY_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):** NOT_APPLICABLE — no contract meaning changes

**Base commit:** `df23a4a0e9cc8d708abde766f48410c93b8a9eb8`

**Target branch/PR:** `codex/short-vol-public-shadow-smoke` / PR #6

## Business closure

**Given:** the accepted two-layer Shadow evidence gate is closed and live commands are forbidden,
but one stale `Root blocker` paragraph still says an `EVIDENCE_ONLY` authority is active and its
acceptance is pending.

**When:** that stale paragraph is replaced with the already-authoritative closed state and a direct
regression rejects the obsolete active/pending wording.

**Then:** `CURRENT_STAGE.md` has one unambiguous permission result: no active task, evidence gate,
live command, persistent deployment, or additional public Shadow process.

**Independent verification:** focused authority tests plus `make check` on the exact final commit.

**Valid zero/no-hit/UNKNOWN result:** NOT_APPLICABLE — this is authority consistency only.

**Upstream prerequisite:** accepted two-layer Shadow evidence at
`df23a4a0e9cc8d708abde766f48410c93b8a9eb8`.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE — remove contradictory obsolete prose without granting,
revoking, or widening authority.

## Product operating behavior

Unchanged. Runtime, Policy, evidence, and command behavior are outside this task.

## Validation harness

Read the current authority as one document and fail if the obsolete active/pending evidence wording
coexists with the closed gate and forbidden live-command markers.

## Evidence boundary

**Proves:** the permission authority is internally consistent about this completed gate.

**Does not prove:** runtime behavior, long-run operation, opportunity frequency, Policy quality,
PnL, or any live/public/private capability.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** `docs/authority/CURRENT_STAGE.md`, direct authority regression, this task.

**Out:** runtime, contracts, Policy, dependencies, locks, evidence, commands, and other authority.

**Owning module/artifact:** permission authority and its direct consistency test.

## Contract

**Inputs and known-at rule:** accepted exact authority/evidence record at the base commit.

**Durable output and identity:** corrected `CURRENT_STAGE.md` prose; no new persisted business object.

**Missing/invalid/UNKNOWN semantics:** conflicting active/closed permission language fails the test.

**Persisted meaning and compatibility:** NOT_APPLICABLE

**Business denominators:** NOT_APPLICABLE

## Acceptance

### Direct behavior

1. Closed evidence and forbidden live markers remain present exactly once.
2. Obsolete active/pending evidence wording is absent.
3. Runtime, contracts, Policy, dependencies, locks, and evidence remain byte-identical.

### Required commands

- `make sync`: NOT_APPLICABLE — no dependency or environment change
- focused tests: `.venv/bin/python -m pytest tests/test_authority_and_architecture.py`
- `make check`
- production-public command: NOT_APPLICABLE and FORBIDDEN
- independent recomputation or reconstruction command: NOT_APPLICABLE

### Real evidence

**Required:** NO

**Environment and stopping condition:** NOT_APPLICABLE

**Required report:** exact final commit/tree, checks, diff scope, remote equality, and non-claims.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** NOT_APPLICABLE

**Policy/contract identities:** unchanged from the accepted base.

**Commit/PR:** recorded by Git and the final delivery report.

**Unknowns and non-claims:** no claim about service uptime, opportunity frequency, Policy quality,
PnL, fills, execution, or private/account capability.

## Definition of done

The stale permission contradiction is absent, direct and repository checks pass, the final tree has
no active task, the PR ref equals the verified commit, and no runtime/evidence meaning changed.
