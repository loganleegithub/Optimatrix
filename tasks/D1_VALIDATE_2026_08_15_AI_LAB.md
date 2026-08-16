# Task — Validate 2026-08-15 Session in AI Lab

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `D1_AI_LAB_SESSION_REVIEW`

**Runtime implementation:** FORBIDDEN

**Live commands:** exactly one attempt of:

```text
PYTHONPATH=src /Users/logan/Optimatrix/.venv/bin/python -m optimatrix.ai_lab review-session
  --ledger-root /Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2
  --lab-root /Users/logan/Library/Application Support/Optimatrix/ai-lab
  --session-id 2026-08-15T08:00:00Z
  --with-codex
```

The command may read the exact Ledger root and append only to the exact Lab root. Codex is
conditional on the deterministic verdict and has zero retry allowance. Focused tests, report reads,
memory verification, Git inspection, and filesystem metadata inspection are also authorized.

**Owning authority/contract:** `docs/authority/CURRENT_STAGE.md`,
`docs/authority/SYSTEM_ARCHITECTURE.md`, and `docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** AI Lab is implemented and offline-verified, but no production Session Review or real
Codex analysis has been observed

**When:** review the ended Deribit Session `2026-08-15T08:00:00Z` once from the exact stable
ObservationLedger root, optionally invoking Codex only when the deterministic workflow permits

**Then:** write and inspect one content-addressed Session Review/report, verify the append-only Lab
memory, and record the exact verdict, denominator, gaps, opportunity counts, Codex status, and
evidence limits without changing the Ledger or runtime

**Affected identity and population:** Session `2026-08-15T08:00:00Z` and its exact `96`
pre-registered DecisionWindow identities under Base Policy
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Baseline and denominator:** expected `96`; recorded Decisions, Outcomes, auditable Windows, and
opportunities are `NOT_YET_MEASURED` until the one command reads the Ledger

**Primary blocker and expected delta:** `2026_08_15_SESSION_AI_LAB_VERDICT_NOT_YET_OBSERVED`
becomes one exact real-ledger verdict and visible report

**Known-at and DataHealth boundary:** only existing immutable DecisionRecords, decision-time
MarketObservations, matching known continuous WindowOutcomes, and official settlement may support
the verdict. Every absent or incoherent fact stays `UNKNOWN` and is never backfilled.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** read-only ObservationLedger input; no
Ledger or Journal write. AI Lab consumes it and writes only its separate research memory/report.

**Legacy-data effect:** NONE

**Permission effect:** one bounded validation only; no persistent new permission

**Files and behavior in scope:** exact Ledger read, exact Lab-root append, report inspection,
append-only memory verification, current task/Stage closure, and focused validation tests

**Out of scope:** any source, Policy, threshold, schema, Workbench, runtime, process, market call,
private fact, account, order, fill, capital, deployment, second Session, retry, Policy qualification,
Edge claim, Challenger experiment, or automatic promotion

**Complexity added / deleted:** NONE

## Verification and closure

**Cheapest falsification:** the command must fail closed on root overlap, identity mismatch,
duplicate divergent review, malformed Ledger evidence, or forbidden Codex transition; afterward
`verify-memory` must accept both hash chains and the report must match the sealed Review identity

**Repository gate:** focused `tests/ai_lab` plus `tests/test_authority.py`

**External evidence:** exact read-only Ledger result, exact Lab memory verification, and exact
JSON/Markdown report paths from the one authorized attempt

Close after directly observing and recording the result. Replace Stage with the post-task snapshot
and remove this file; do not append completion history.
