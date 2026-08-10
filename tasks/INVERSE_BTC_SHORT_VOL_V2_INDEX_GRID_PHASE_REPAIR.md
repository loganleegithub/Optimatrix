# Task — V2 source-grid and confirmation-continuity repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `89e83e04871fd2b230b1868d399d7dec45865a6b`

**Target branch/PR:** `codex/v2-index-grid-phase-fix` /
[Draft PR #48](https://github.com/loganleegithub/Optimatrix/pull/48)

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION.md`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_RADAR.md`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN → ANOMALY_ACTIVE`

**Baseline:** after the source-grid fixes, the clean Draft PR #48 runtime remained healthy, ready,
`CURRENT`, `KNOWN_COMPLETE`, and `128/128`, with zero schema-v5 Case. Eligible HIGH leaders in the
6-to-24-hour and 24-to-72-hour bands each reached confirmation `2/3` under their frozen 150-second
and 300-second separations. Three consecutive scheduled history-refresh cycles produced queue-lag
peaks of `3,045 ms`, `4,032 ms`, and `5,003 ms`.

**Primary blocker:** `ORDERED_QUEUE_LAG_DESTRUCTIVE_PRECONFIRMATION_RESET`. On the
threshold-crossing refresh, the queue-lag currentness gate correctly changed every current Radar
evaluation to `UNKNOWN`, but the bucket owner also erased every nonzero, not-yet-active
confirmation. One known HIGH target changed `2 → 0`; the global `CORE_UNKNOWN` reset counter
increased by `13`. About half a second later the same session, bucket leader, HIGH band, and
source-confirmed baseline recovered, yet confirmation restarted at `0 → 1`. Reconnect, protocol
gap, and continuity-epoch counts did not change.

**Expected user-visible delta:** while ordered queue lag is above the fixed currentness deadline,
Radar remains `UNKNOWN`, bucket coverage is `UNKNOWN`, no observation is counted, and no Episode or
downstream admission can occur. An inactive tracker retains only confirmations already accepted
before the lag. On catch-up the current facts are recomputed: the same leader and band continue
from the retained count, while a changed leader, band, scope, or persistent core loss resets under
the existing rules.

**Durable-data effect:** `NONE` before a normal V2 admission. The repair neither creates nor
migrates a Case and retains the existing stable schema-v5 repository.

**Complexity added:** one bounded currentness-pause branch in the existing runtime bucket owner, in
addition to the already-landed aligned-source timestamp tuple; no new state owner, timer, schema,
history, or baseline path.

**Complexity deleted:** the rotating five-phase sampling behavior, the wall-clock-ahead-of-source
anchor race, the misleading baseline source label, and the destructive interpretation of a
transient ordered backlog as lost pre-confirmation evidence.

## Business closure

**Given:** an inactive clue-eligible bucket tracker with accepted nonzero confirmation, followed by
an ordered envelope whose receive-to-reducer lag exceeds the fixed Policy currentness deadline.

**When:** the lagged envelope settles and a later ordered envelope catches the reducer up without a
session, continuity, scope, leader, or score-band change.

**Then:** the lagged frame remains `UNKNOWN` and contributes no observation or admission, the
previous confirmation count is unchanged, and recovery resumes from that count only after current
truth proves the same leader and score band.

**Valid zero/UNKNOWN:** the queue-lag interval itself remains current `UNKNOWN`; an active Episode
continues to end fail-closed on core loss. A missing interior index point, stale source, revision,
warmup, invalid input, real scope loss, leader change, score-band change, session gap, or run stop
still resets or ends through its existing owner. Zero canonical Shadow admissions is valid if no
corrected HIGH survives three real separated observations or Underwriting does not produce a
Candidate; a reset caused only by a transient ordered queue backlog is not valid.

**Cheapest falsification:** establish one pre-activation observation, process one deliberately
lagged but ordered envelope, catch up without counting a new observation, and observe any change in
the prior count or any Candidate/Case created during the `UNKNOWN` interval.

## Change declarations

**Market/Decision input contract change:** five-minute index-chart samples remain fixed to the
source-confirmed UTC epoch grid. Ordered queue-lag currentness is a pre-activation observation pause,
not evidence that previously accepted observations disappeared; current score and admission truth
remain `UNKNOWN` until catch-up.

**Decision Policy change:** `NONE`; the three Policy artifacts and identities remain byte-exact.

**Outcome/evaluation contract change:** `NONE`.

**Stage/authorization change:** authorize this bounded repair in the existing Draft PR and one
clean stop/start on `127.0.0.1:8675` from the clean checked commit, using the unchanged stable Case
root. Continued public-only observation runs until the first admitted active Shadow or a newly
measured fixed blocker is established. No private or execution permission is added.

## Scope

**In:** the sole runtime bucket-settlement owner and its queue-lag currentness transition; the
already-landed `IndexHistoryReducer` source-grid repair; focused market/runtime/Workbench tests;
owning contract, task, and Current Stage authority; the bounded public-only cutover and observation.

**Out:** score weights, thresholds, TTE/Delta rules, confirmation counts or separations, preservation
of an already-active Episode, any Policy artifact, Underwriting or Position economics, Case schema,
state-root migration, private data, orders, fills, capital, process supervision, or a second
baseline path.

**Owning module:** `apps/radar_runtime/src/radar_runtime/runtime.py`

## Validation

- focused tests: `.venv/bin/pytest -q tests/test_market_monitor.py tests/test_runtime_reducer.py tests/test_fact_boundary_business.py tests/test_trader_workbench.py`;
- repository gate: `make check`;
- public observation: after binding the Draft PR and passing repository checks, clean-stop the
  current runtime once, start the clean repair commit on port `8675` with
  `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`, verify exact runtime identity,
  health/readiness/currentness, fixed-grid baseline behavior across canonical boundaries, and
  continue the already-authorized public-only monitor;
- no manifest, receipt, commissioning subsystem, runtime self-acceptance, or host inspection.

## Definition of done

The rotating phase, source-ahead race, and queue-lag destructive pre-confirmation reset are
impossible by direct tests; the full repository gate passes; the live clean repair commit remains
current; threshold-crossing lag contributes zero observations while a same-truth recovery retains
the prior count; any first active admitted Shadow is verified through the API and official Case
reader, or the next truthful fixed funnel blocker is reported without changing Policy to
manufacture admission; the diff is bounded and remote state is exact.
