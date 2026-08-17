# Task — D1 daily Session review and Workbench projection

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Runtime implementation:** REQUIRED

**Live commands:** after the repository gate passes, install exactly one user LaunchAgent
`com.optimatrix.d1-session-review` in `gui/501` from the repository-owned plist. It may run one
bounded `optimatrix-ai-lab daily-review` invocation every `900` seconds and at load, read only
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`, write only
`/Users/logan/Library/Application Support/Optimatrix/ai-lab`, enroll Sessions no earlier than
`2026-08-17T08:00:00Z`, and process at most one ready Session per invocation. Each invocation may
make at most one Deribit `public/get_time` clock preflight and one
`public/get_index_chart_data(index_name=btc_usd, range=2d)` call for that Session; it performs no
within-process wait or retry. After the code is committed and the working tree equals that commit,
the existing `com.optimatrix.b3-public-shadow` job may be replaced exactly once with its unchanged
command, root, Policy
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, EventState, and port so
the loopback Workbench loads the read-only Review projection. No other process control, root,
public method, private call, or deployment is authorized.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`, and
`docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** D1 already owns a separate AI Lab root, content-sealed official evidence, append-only V3
Policy-quality Review memory, and deterministic JSON/Markdown reports. Two current V3 Reviews exist
through `2026-08-16T08:00:00Z`, while report generation is manual and the Workbench `#review`
screen still projects only the active B3 Session plus a D1 placeholder.

**When:** add one idempotent ended-Session command, a derived bounded Web projection, and a read-only
Workbench adapter, then deploy the exact periodic LaunchAgent and refresh the existing loopback
runtime once

**Then:** every ready Session at or after the enrollment boundary produces at most one immutable V3
Review and one deterministic JSON/Markdown report; an identical rerun creates no new business fact;
an unready or failed invocation waits only for the next launchd interval and never writes a partial
Review. The Workbench provides a completed-Session selector and renders the selected Review's
verdict, denominator, evidence coverage, identification bounds, four-quadrant result, structure
funnel, blockers, Window classifications, evidence boundary, and Challenger/human gate from the
validated derived projection. Missing or corrupt AI Lab presentation data is explicit and cannot
stop the B3 runtime or alter a Decision.

**Affected identity and population:** each completed Deribit Session's exact `96`
`DecisionWindowId` denominator and its immutable Base DecisionRecords/WindowOutcomes; no new market,
TradeCase, Position, order, fill, or account identity

**Baseline and denominator:** two current V3 Reviews through `2026-08-16T08:00:00Z`; each new Review
retains exactly `96` expected Windows, preserves absent or causally incomplete Windows as `UNKNOWN`,
and reports recorded Decision/Outcome counts separately

**Primary blocker and expected delta:** `SESSION_REVIEW_MANUAL_AND_NOT_TRADER_VISIBLE` becomes one
bounded automatic Review attempt and one visible completed-Session report; the expected delta is
operational regularity and presentation, not more Candidates, Policy qualification, or Edge

**Known-at and DataHealth boundary:** the job selects an ended Session only after a validated
Deribit UTC preflight and appends a Review only after every recorded Decision for that Session has
one append-once WindowOutcome. Missing decision-time books, paths, settlement, or official history
remain Window-local `UNKNOWN`; post-Session evidence never backfills a Base Decision.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** the daily job is read-only over the exact
B3 Ledger root and never opens CaseJournal for writing. It writes immutable evidence, Review memory,
and deterministic reports only under the separate AI Lab root. Workbench consumes one bounded,
rebuildable presentation projection that is not a new business record.

**Legacy-data effect:** NONE; existing V1/V2/V3 Reviews and reports remain byte-identical and their
supersession rules remain enforced

**Permission effect:** authorize one public-data-only offline LaunchAgent and read-only Workbench
projection. Codex, Policy mutation, promotion, private methods, orders, fills, and capital remain
`NONE`.

**Files and behavior in scope:** `src/optimatrix/ai_lab/` daily orchestration, report ordering,
operational state, and Web projection; `src/optimatrix/workbench.py`, `src/optimatrix/runtime.py`,
and `src/optimatrix/workbench_static/`; one repository-owned LaunchAgent plist; direct tests and the
owning Authority/task documentation

**Out of scope:** database, message bus, queue worker, raw-market replay store, online trainer,
automatic Codex invocation, automatic Challenger creation or promotion, Policy/`7%`/`$10`/sizing/
ranking changes, Decision or Outcome backfill, private facts, orders, fills, capital, C1/C2, remote
deployment, and Edge claims

**Complexity added / deleted:** add one idempotent one-shot command, one `900s` LaunchAgent wakeup,
one small mutable operational-status file, and one bounded rebuildable Web projection. Reuse the
existing hash-chain memory and content-addressed reports; add no dependency, daemon loop, database,
queue, migration, dual write, or second source of business truth.

## Verification and closure

**Cheapest falsification:** with disposable Ledger/Lab roots, prove that an incomplete Outcome
population produces `NOT_READY` and no Review; a complete ended Session produces one report,
memory event, status, and Web projection; an identical rerun is a no-op; a crash boundary between
report creation and memory append is recoverable; a foreign/corrupt projection renders unavailable
without raising through the runtime publisher

**Repository gate:** `make check`

**External evidence:** verify the new LaunchAgent's exact argv, `900s` interval, one-session bound,
and successful latest run; verify the existing B3 job retains one PID, one lock owner, exact root,
Policy, EventState, port `8765`, and advancing public-market Decisions after its single replacement;
verify `http://127.0.0.1:8765/#review` displays the latest completed Review and another historical
Session without browser console errors. Candidate, execution, Policy qualification, and Edge remain
`UNVERIFIED`.

Close only after directly observing the automatic durable artifact and Web report. Replace Stage
with the post-task snapshot and remove this file; do not append completion history.
