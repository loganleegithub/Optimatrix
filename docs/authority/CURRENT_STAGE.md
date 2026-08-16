# Optimatrix Current Stage

**Status:** D1 AI LAB SESSION REVIEW — ACTIVE

**Current maturity:** `D1_AI_LAB_SESSION_REVIEW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Current task kind:** `IMPLEMENTATION`

**Sole authorized closure:** [`D1_AI_LAB_SESSION_REVIEW`](../../tasks/D1_AI_LAB_SESSION_REVIEW.md)

## Current permissions

Stage is the permission ceiling; the active task may only narrow it.

**Offline checks and simulation:** deterministic synthetic Session fixtures only; opening a real
ObservationLedger remains a later read-only validation action

**Public market calls:** `NONE_AUTHORIZED`

**Stable ObservationLedger root:** the existing
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2` remains owned by
the deployed B3 runtime. This implementation task may not open or mutate it.

**Stable CaseJournal root:** the same existing v2 root remains owned by B3. AI Lab is not a
CaseJournal consumer and may not open or mutate it in this task.

**Continuous runtime:** the existing B3 launchd job remains outside this branch and unchanged. AI
Lab adds no daemon, scheduler, listener, runtime owner, restart, replacement, or deployment.

**AI Lab durable root:** default
`/Users/logan/Library/Application Support/Optimatrix/ai-lab`; it is a separate append-only research
root and must never be used as an ObservationLedger, CaseJournal, account, or runtime root

**Codex CLI:** optional fake-process validation of one-shot `codex exec` only. A real invocation is
not authorized by this implementation task.

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Required workflow

For every ended Session, the deterministic Lab must follow this order:

1. prove the exact DecisionWindow denominator, matching DecisionRecords, causal observations,
   continuous future paths, and official settlement;
2. enumerate one frozen `UNFILTERED_CONDOR` control from decision-time public facts while retaining
   legal geometry, full-amount pricing, standard cost, and USD-risk constraints;
3. return `NO_OPPORTUNITY` and stop only from complete zero-success evidence; missing evidence is
   `UNKNOWN`, and an unconfirmed Base Candidate cannot bypass the stop;
4. when an opportunity existed but Base missed it, return `MISSED_OPPORTUNITY` and expose exact
   Base blockers, values, thresholds, units, and signed margins where quantifiable;
5. only a complete `BASE_FOUND_OPPORTUNITY` Session may unlock a separately frozen
   Base-versus-Challenger comparison.

Memory may accumulate sealed verdicts, blocker counts, and falsifiable hypotheses. Evolution means
stronger cross-Session evidence, never self-modifying Policy, automatic code changes, execution
permission, or automatic promotion.

## Current evidence state

- The prior isolated Challenger Lab proves only an offline audit mechanism. Its useful frozen
  Base/Challenger, chronological split, append-only audit, and human-promotion boundaries are being
  integrated under the product name `AI Lab`.
- Session-first adjudication, missed-opportunity attribution, persistent memory, bounded Codex
  explanation, and trader-readable reports are `NOT_YET_IMPLEMENTED` at activation.
- `B3_PIPELINE_CAPABILITY_ACCEPTED` remains prior mechanism evidence; this branch neither changes
  nor re-accepts it. `natural_chain=NOT_YET_OBSERVED`,
  `policy_reachability=COMPLETED_SESSION_LOCAL_RESPONSIBILITY_MEASURED`,
  `policy_qualification=NONE`, and `edge_claim=NONE` remain unchanged evidence boundaries.

**Primary blocker:** `AI_LAB_SESSION_FIRST_WORKFLOW_NOT_IMPLEMENTED` — close only after all four
verdict branches, the append-only memory, the bounded/cited Codex boundary, actual-path Challenger
gate, visible report, and full repository gate pass. Real Session review remains `UNVERIFIED`.
