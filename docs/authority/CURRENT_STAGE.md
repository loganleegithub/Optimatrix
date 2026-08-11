# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_POSITION_LIFECYCLE_REALISM_ACTIVE`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_LEGACY_9002B6E_PENDING_AUTHORIZED_CUTOVER`

**Live commands:** `TASK_SCOPED_SIMULATION_CUTOVER_AND_FIRST_NATURAL_OUTCOME_MONITOR_AUTHORIZED`

**Sole authorized closure:**
[`SHADOW_POSITION_LIFECYCLE_REALISM`](../../tasks/SHADOW_POSITION_LIFECYCLE_REALISM.md)

## Current business baseline

The stable repository is
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. Before this task, its official
reader validated 62 schema-v5 Cases, including 40 compatible non-terminal admitted Entries and
zero admitted Outcome files. Their latest Segments were open and gapped. The repository also held
12 Radar-score Controls and 10 selected Underwriting Controls created under the legacy segmentless
Control contract.

The sole Online Runtime still serving `127.0.0.1:8765` at task start came from
`/Users/logan/Optimatrix-runtime` and legacy code
`9002b6ef7b0ec183cd1448fc975a4b7ebea19084`. It is the pre-cutover baseline, not acceptance of the
new lifecycle. No state-root file may be rewritten, migrated, copied over, or relabeled during the
cutover.

The primary funnel blocker is `SHADOW_CASE_OPENED -> SHADOW_CASE_OUTCOME`: immutable first-CLOSE
history was coupled to a lifetime single quote attempt, and normal expiry had no official
delivery-price settlement path. The active task must preserve the first Policy reason while
continuing exit responsibility after failed pairs and process loss, produce official Inverse
settlement economics at expiry, recover future Segment-bearing Controls, and derive named offline
Cohort eligibility without online global qualification authority.

## Authorized live closure

This task authorizes exactly:

1. one isolated full-business-chain simulation on non-production data using the modified runtime;
2. one clean cutover of the sole stable runtime to the accepted task commit while preserving every
   existing Case byte and opening truthful `HANDOFF_GAP` Segments;
3. bounded loopback/API/browser and single-writer validation of that runtime;
4. read-only monitoring until at least one admitted `EXITED_KNOWN | SETTLED_KNOWN` Outcome is
   naturally produced from public Deribit facts and validated end to end.

If validation exposes a lifecycle defect, the task may repair the same owning boundary on the same
branch, rerun the complete business matrix and repository gate, and repeat the cutover. It does not
authorize another product, Policy-threshold change, Case migration, replay, supervisor, database,
order, fill, account, margin, capital, or private execution.

## Fixed product and Policy truth

The sole Online Runtime product is `INVERSE_BTC_V1`. There is no product selector, fallback product,
compatibility profile, alternate online schema, or in-process Policy switch. The repository
contains only the three fixed V2 Inverse Policy artifacts:

```text
product spec identity:        sha256:a7880d3a0b3da12f74438b292ed49d7c034e683d2e1654037229c62474127131
Radar Policy identity:        sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d
Underwriting Policy identity: sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d
Position Policy identity:     sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe
```

The current Position thresholds remain frozen for the legacy book. This task separates intent,
acquisition, observation quality, and terminal method; it does not silently reinterpret the nine
Policy predicates or change their identity.

## Permission and non-claims

Permission remains `PUBLIC_SHADOW`: production public market facts and counterfactual economics
only. A public book or official delivery price is not an order, fill, settlement action, actual
position, account PnL, or capital exposure. `PENDING`, `GAPPED`, a responsive Workbench, green tests,
and a recovered Case are not terminal economics or Policy qualification.
