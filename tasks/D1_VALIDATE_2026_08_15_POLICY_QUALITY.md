# Task — Validate 2026-08-15 Policy quality in AI Lab

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `D1_AI_LAB_POLICY_QUALITY_REVIEW`

**Runtime implementation:** FORBIDDEN

**Live commands:** exactly one attempt of:

```text
PYTHONPATH=src /Users/logan/Optimatrix/.venv/bin/python -m optimatrix.ai_lab review-session
  --ledger-root /Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2
  --lab-root /Users/logan/Library/Application Support/Optimatrix/ai-lab
  --session-id 2026-08-15T08:00:00Z
```

The command may read the exact Ledger root once and append only one current Policy-quality Review
plus its deterministic JSON/Markdown report to the exact Lab root. No Codex invocation or retry is
authorized. One subsequent `verify-memory`, report read, hash/file metadata inspection, focused
tests, Git inspection, and current task/Stage closure are authorized read-only checks.

**Owning authority/contract:** `docs/authority/CURRENT_STAGE.md`,
`docs/authority/SYSTEM_ARCHITECTURE.md`, and `docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** the corrected deterministic Policy-quality workflow is offline-verified, while the only
existing 2026-08-15 Lab Review used the retired terminal-positive definition and is
`INVALID_FOR_POLICY_QUALITY`

**When:** review ended Session `2026-08-15T08:00:00Z` once from the immutable production public-
Shadow Ledger using the fixed hindsight IV/RV, path, cost, and settlement Oracle

**Then:** append and inspect one content-sealed current Review and trader report that expose the
complete denominator, IV/RV curve coverage, four-quadrant counts, exact gaps, verdict, legacy
invalidation, and evidence boundary

**Affected identity and population:** Session `2026-08-15T08:00:00Z` and its exact `96`
pre-registered DecisionWindows under Base Policy
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Baseline and denominator:** expected `96`; prior validation observed `81` Decisions, `81`
Outcomes, and only `64` auditable terminal-control Windows, but the corrected IV/RV curve and
four-quadrant counts are `NOT_YET_MEASURED`

**Primary blocker and expected delta:** `2026_08_15_POLICY_QUALITY_REVIEW_NOT_YET_OBSERVED` becomes
one exact current verdict and visible deterministic report

**Known-at and DataHealth boundary:** only immutable Base decisions, decision-time public books,
the complete registered-cut IV/RV curve, matching continuous WindowOutcome paths, standard public
cost, and official settlement may support a classification. Missing facts remain `UNKNOWN`; the
command may not infer, repair, backfill, or reuse the legacy terminal-positive verdict.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** exact ObservationLedger is read-only input;
no Ledger or Journal fact is written. AI Lab writes only its distinct current review/report.

**Legacy-data effect:** existing `session-reviews.jsonl` is read and hash-verified only; its sealed
Review remains immutable and excluded from Policy-quality memory

**Permission effect:** one bounded validation only; no persistent permission

**Files and behavior in scope:** exact Ledger read, exact current Lab append, deterministic report
inspection, memory verification, focused tests, and task/Stage closure

**Out of scope:** source, Policy, threshold, schema, Workbench, B3 runtime/process, market call,
Codex, private fact, account, order, fill, capital, deployment, second Session, retry, Challenger,
Policy qualification, and Edge claim

**Complexity added / deleted:** NONE

## Verification and closure

**Cheapest falsification:** the command must fail closed on overlapping roots, duplicate divergent
current Review, malformed Ledger evidence, or identity mismatch; afterward `verify-memory` must
accept current and legacy chains, and both report files must bind the current Review identity

**Repository gate:** focused `tests/ai_lab` plus `tests/test_authority.py`; implementation's final
`make check` already passed and source is forbidden here

**External evidence:** exact read-only Ledger result, current/legacy memory verification, and exact
JSON/Markdown report paths from the sole command

Close only after directly observing the declared validation delta. Replace Stage with the
post-task snapshot and remove this file; do not append completion history.
