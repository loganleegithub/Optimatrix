# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_POSITION_LIFECYCLE_REALISM_DEPLOYED_AND_FIRST_OUTCOME_VALIDATED`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_CODE_6FF78068A7990584AAE630BD31DBABCD6B90DA9A`

**Live commands:** `TASK_SCOPED_SIMULATION_CUTOVER_AND_FIRST_NATURAL_OUTCOME_MONITOR_COMPLETED_NO_ADDITIONAL_LIVE_AUTHORITY`

**Completed closure:**
[`SHADOW_POSITION_LIFECYCLE_REALISM`](../../tasks/SHADOW_POSITION_LIFECYCLE_REALISM.md)

## Current business baseline

The stable repository is
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. At task start its official reader
validated 62 schema-v5 Cases, including 40 compatible non-terminal admitted Entries and zero
admitted Outcome files. By the cutover boundary normal runtime intake had increased the repository
to 64 Cases. The task-start baseline also held 12 Radar-score Controls and 10 selected Underwriting
Controls under the legacy segmentless Control contract.

The sole Online Runtime serving `127.0.0.1:8765` at task start came from
`/Users/logan/Optimatrix-runtime` and legacy code
`9002b6ef7b0ec183cd1448fc975a4b7ebea19084`. Its final process boundary left the latest Position
Segments without close records. The new runtime did not repair or relabel those intervals: it
restored all 40 first-CLOSE Positions from `INCOMPLETE_UNCLEAN_EXIT`, opened truthful `HANDOFF_GAP`
Segments, and continued exit acquisition.

The primary funnel blocker was `SHADOW_CASE_OPENED -> SHADOW_CASE_OUTCOME`: immutable first-CLOSE
history was coupled to a lifetime single quote attempt, and normal expiry had no official
delivery-price settlement path. Runtime code
`6ff78068a7990584aae630bd31dbabcd6b90da9a` now serves the stable repository. Public Deribit facts
naturally produced 20 admitted `EXITED_KNOWN/MARKET_EXIT` Outcomes; all 20 validate exact first-CLOSE
identity, dual-leg source references, fee/PnL conservation, `GAPPED`, and
`terminal_economics_eligible=true`. The other 20 admitted Positions remain `EXIT_ACQUIRING` because
no full-quantity accepted pair has ended their responsibility.

The offline terminal-economics Cohort contains all 20 known Outcomes. Continuous-path and complete
exit-acquisition Cohorts contain zero because their histories are gapped; this is a per-question
qualification result, not a global economic rejection.

## Completed live closure

The authorized acceptance required one isolated full-business-chain simulation, bounded
loopback/API/browser and single-writer validation, and read-only monitoring until at least one
admitted `EXITED_KNOWN | SETTLED_KNOWN` Outcome appeared. Each requirement completed.

The task completed exactly:

1. an isolated full-business-chain simulation over a copy of all 64 Cases, including 40/40 Position
   recovery and 20 natural public-market exits;
2. a cutover of the sole stable runtime without rewriting existing Case bytes;
3. all six loopback routes under GET and HEAD, exact static-asset identity, API/browser rendering,
   one writer, `RUNNING/CURRENT/ready`, and PUBLIC_SHADOW non-order/non-fill validation;
4. natural production of 20 admitted `EXITED_KNOWN` Outcomes and end-to-end durable arithmetic and
   named-Cohort validation.

Validation exposed and repaired two owning-boundary defects: completed Outcome Segments were
initially excluded from offline Cohorts, and the Workbench still described recovered attempts as
"no retry." The final repository gate passes 769 tests. This completed closure grants no continuing
live command and no authority for another product, Policy-threshold change, Case migration, replay,
supervisor, database, order, fill, account, margin, capital, or private execution.

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
