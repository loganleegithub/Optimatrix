# Task — Correct AI Lab policy-quality adjudication

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `D1_AI_LAB_POLICY_QUALITY_REVIEW`

**Runtime implementation:** REQUIRED only inside the offline `optimatrix.ai_lab` package

**Live commands:** FORBIDDEN. Tests may use synthetic temporary Ledger/Lab roots only. Reading the
production ObservationLedger, appending the stable AI Lab root, invoking Codex CLI, controlling the
B3 runtime, and reviewing another real Session require a later exact validation task.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/SYSTEM_ARCHITECTURE.md`, and `docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** the first 2026-08-15 review equated positive fee-after-settlement economics with a
post-Session opportunity and therefore sealed `MISSED_OPPORTUNITY` without proving that the
fixed ex-ante rule should have selected a sufficiently compensated, acceptably risky trade

**When:** replace terminal-result screening with one deterministic post-Session Policy-quality
oracle and compare that oracle with the immutable Base Decision for every registered Window

**Then:** the Lab classifies each complete Window as Base captured a hindsight opportunity, Base
correctly avoided hindsight risk, Base missed a hindsight opportunity, or Base took hindsight risk;
incomplete IV/RV evolution, physical path, cost, settlement, or denominator evidence stays
`UNKNOWN`, and the Session verdict reports whether the fixed rule was well calibrated, too
conservative, too aggressive, mixed, or unjudgeable

**Affected identity and population:** every pre-registered DecisionWindow of one ended Session,
its immutable Base DecisionRecord, decision-time candidate prices, post-decision IV/RV observations,
continuous physical path, official settlement, and bounded four-leg counterfactuals under Base
Policy `sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Baseline and denominator:** current review schema counts terminal-positive control structures;
the corrected denominator is the exact registered Window population, with separate complete,
unknown, captured, correctly avoided, missed, and over-risk counts

**Primary blocker and expected delta:** `TERMINAL_POSITIVE_IS_NOT_POLICY_QUALITY` becomes a
four-quadrant rule-quality judgment whose favorable conclusion requires zero misses, zero over-risk
decisions, and complete evidence for the whole Session

**Known-at and DataHealth boundary:** Base inputs and decisions stay frozen at their original
known-at boundaries. The oracle may use later facts only because it is explicitly hindsight. It may
not relabel a terminal profit as an ex-ante opportunity without a complete aligned IV/RV evolution,
continuous physical path, official settlement, decision-time cost, and a frozen risk-quality rule.
Any missing, stale, discontinuous, contradictory, or partial fact is `UNKNOWN`, never no-opportunity.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** NONE; implementation and tests do not read
or write the stable Ledger or any CaseJournal. AI Lab remains a separate offline consumer.

**Legacy-data effect:** the sealed Review
`sha256:09cd363e775fa41c26c5004712ee683252e6b154d35d99b235be6ee8973a8a63` remains immutable evidence
of the retired terminal-positive control, but must be marked `INVALID_FOR_POLICY_QUALITY` and must
never be presented to Codex or a human as proof of a missed opportunity

**Permission effect:** NONE; no Policy, execution, account, order, capital, deployment, promotion,
or live-process permission is added

**Files and behavior in scope:** direct AI Lab review models, adjudication, memory/report projection,
Codex eligibility/prompt, CLI terminality, exact Authority/contract wording, and focused tests

**Out of scope:** Policy threshold changes, a Challenger Policy, online training, a generic oracle
framework, production Ledger schema changes, reconstruction of facts that were never recorded,
Workbench/runtime changes, market calls, private facts, orders, fills, capital, deployment, Policy
qualification, Edge claims, and any real Session run

**Complexity added / deleted:** delete the terminal-positive opportunity verdict as Policy-quality
truth; add one current Policy-quality review schema and one deterministic four-quadrant adjudicator.
Legacy review parsing is retained only to verify and explicitly invalidate existing append-only data.

## Verification and closure

**Cheapest falsification:** focused synthetic tests must prove that terminal profit alone never
creates a hindsight opportunity; complete profitable/low-path-risk IV-over-RV evidence can create a
miss; a Base Candidate with adverse IV/RV or path evidence creates over-risk; complete correct
avoidance is distinct from missing evidence; and one missing Window forces Session `UNKNOWN`

**Repository gate:** focused `tests/ai_lab` plus `tests/test_authority.py`, followed by `make check`

**External evidence:** `UNVERIFIED`; a corrected 2026-08-15 run belongs to a later validation task

Close only after directly observing the declared implementation delta. Replace Stage with the
post-task snapshot and remove this file; do not append completion history.
