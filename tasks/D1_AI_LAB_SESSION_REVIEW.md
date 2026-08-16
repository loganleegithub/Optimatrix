# Task — D1 AI Lab Session Review

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `D1_AI_LAB_SESSION_REVIEW`

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN; tests use deterministic synthetic data. A real ObservationLedger and
real Codex process are reserved for a later exact validation task.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`, and
`docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** the isolated Challenger Lab begins with a Base-versus-Challenger comparison and cannot
decide, explain, or remember whether an ended Session contained any post-Session opportunity

**When:** integrate it into the modular monolith as `optimatrix.ai_lab`, add one deterministic
Session-first adjudicator over aligned DecisionRecords and WindowOutcomes, a separate append-only
learning root, one strict read-only Codex CLI adapter, and a trader-readable report

**Then:** classify each ended Session as `UNKNOWN`, `NO_OPPORTUNITY`, `MISSED_OPPORTUNITY`, or
`BASE_FOUND_OPPORTUNITY`; zero opportunity requires complete evidence and stops before Codex even
when Base produced an unconfirmed Candidate, missed opportunity exposes quantitative Base-gate
attribution, and Challenger comparison is enabled only for a complete Base-found Session

**Affected identity and population:** the exact 96 pre-registered DecisionWindow identities of one
caller-selected ended Deribit Session under frozen Base Policy
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, plus immutable Base
DecisionRecords and WindowOutcomes; Lab identities never substitute for the Window denominator

**Baseline and denominator:** four deterministic Sessions cover all verdict branches with the
Policy's exact 96-Window schedule; actual production Sessions are `NOT_YET_MEASURED`

**Primary blocker and expected delta:** `AI_LAB_SESSION_FIRST_WORKFLOW_NOT_IMPLEMENTED` becomes one
auditable verdict funnel, blocker-distance table, sealed memory chain, and bounded AI explanation

**Known-at and DataHealth boundary:** only immutable decision-time MarketObservation facts may
establish ex-ante structure and price eligibility; only matching known continuous WindowOutcome
paths plus matching official settlement may establish post-Session economics. Missing, stale,
discontinuous, rank-unresolved, or identity-incoherent facts remain `UNKNOWN`.

## Effects and scope

**Risk allocation effect:** NONE; the control preserves frozen option amount, full-amount price
evaluability, standard Combo cost, boundary-loss control, and Session USD-risk ceiling

**ObservationLedger / CaseJournal effect and consumer:** read-only interface only; this task uses
synthetic inputs and writes separate content-sealed review events and reports under a Lab root

**Legacy-data effect:** the external isolated Lab remains untouched as recovery evidence while the
integrated replacement becomes the only maintained source path

**Permission effect:** offline derived research only; no market call, runtime, account, order, fill,
capital, deployment, Policy qualification, Edge, or promotion permission

**Files and behavior in scope:** `src/optimatrix/ai_lab/`, shared structure enumeration,
`optimatrix-ai-lab` packaging, direct tests, `docs/AI_LAB.md`, and direct Authority/contract status

**Out of scope:** weakening Policy to manufacture Candidates, long-vol/long-gamma product work,
online training, daemon, autonomous edits, Workbench assets, production Ledger writes, C1/C2,
orders, fills, capital, deployment, Policy qualification, Edge, and automatic promotion

**Complexity added / deleted:** add one integrated package, append-only review memory, strict Codex
subprocess boundary, and Markdown/JSON projection; remove the separate-project entrypoint and share
the existing structure enumerator as the single formula owner

## Verification and closure

**Cheapest falsification:** reject incomplete zero-opportunity claims, unresolved books, mismatched
settlement, tampered memory, uncited Codex output, unbounded prompt population, and actual-path
Challenger comparison before an eligible Base-found Session Review

**Repository gate:** `make check`

**External evidence:** `UNVERIFIED`; no real ObservationLedger or real Codex invocation is required
or authorized by this implementation task

Close after deterministic reports show the workflow and the repository gate passes. Replace Stage
with the post-task snapshot and remove this file; do not append completion history.
