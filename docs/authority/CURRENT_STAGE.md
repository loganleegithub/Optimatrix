# Optimatrix Current Stage

**Status:** D1 AI LAB — POLICY-QUALITY REVIEW REDESIGN ACTIVE

**Current maturity:** `D1_AI_LAB_POLICY_QUALITY_REVIEW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Current task kind:** `IMPLEMENTATION`

**Sole authorized closure:** [`D1_POLICY_QUALITY_REVIEW_REDESIGN`](../../tasks/D1_POLICY_QUALITY_REVIEW_REDESIGN.md)

## Current permissions

Stage authorizes only the bounded offline AI Lab correction named by the active task.

**Offline checks and simulation:** synthetic temporary-root tests for the corrected post-Session
Policy-quality review

**Public market calls:** `NONE_AUTHORIZED`

**Stable ObservationLedger root:** `/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`
remains the authorized B3 runtime root outside this branch and unchanged; this task may not open or
mutate it

**Stable CaseJournal root:** `NONE`; this task may not create or mutate CaseJournal facts

**Continuous runtime:** the existing B3 launchd job remains outside this branch and unchanged; no
deployment or process control

**AI Lab stable durable root:** `NONE`; existing append-only data may not be opened or changed

**Codex CLI:** `NONE`; fake subprocess tests only

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Required correction

The sealed 2026-08-15 Review used a retired definition: a legal four-leg control with positive
fee-after-settlement economics was counted as an opportunity. That fact is a terminal-payoff control
only. It does not prove the trade was a sufficiently compensated, acceptably risky ex-ante choice,
so its `MISSED_OPPORTUNITY` verdict is `INVALID_FOR_POLICY_QUALITY`.

AI Lab must instead compare immutable Base decisions with a post-Session oracle over the complete
registered Window denominator. The oracle requires aligned decision-time cost, complete later IV/RV
evolution, continuous physical path, official settlement, and a frozen risk-quality definition.
It produces four business facts: captured opportunity, correct avoidance, missed opportunity, and
over-risk selection. Any incomplete required evidence makes that Window and the Session judgment
`UNKNOWN`.

A complete one-Session result can judge only that Session. It cannot qualify Policy or establish
Edge. Cross-Session chronological evidence and pre-registered promotion gates remain required for
either claim.

## Current evidence state

- The existing sealed Review and its hash chain remain immutable legacy evidence.
- `374` positive terminal-payoff findings are neither trades nor proved ex-ante opportunities.
- The observed 2026-08-15 population had `96` expected Windows, `81` Decisions, `81` Outcomes, and
  only `64` auditable Windows. Therefore the current evidence cannot prove either that Base missed
  no opportunity or that Base avoided all undue risk.
- Existing Outcome summaries do not by themselves prove a complete Session IV/RV evolution and
  full physical-path risk series. A corrected real review has not run.
- `B3_PIPELINE_CAPABILITY_ACCEPTED` remains prior mechanism evidence and is not reopened here.
- `policy_reachability=COMPLETED_SESSION_LOCAL_RESPONSIBILITY_MEASURED` remains a prior diagnostic,
  not Policy-quality proof.
- `natural_chain=NOT_YET_OBSERVED`, `policy_qualification=NONE`, and `edge_claim=NONE` remain.

**Primary blocker:** `TERMINAL_POSITIVE_IS_NOT_POLICY_QUALITY` — replace the retired verdict and
projection path with the exact four-quadrant, fail-closed Policy-quality review before attempting
another real Session validation.
