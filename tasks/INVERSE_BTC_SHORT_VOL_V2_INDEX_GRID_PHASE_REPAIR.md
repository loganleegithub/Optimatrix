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

**Current funnel node:** `ANOMALY_ACTIVE → UNDERWRITING → SHADOW_CASE_OPENED`

**Baseline:** after the source-grid and confirmation-continuity fixes, clean code identity
`6fbcf9fbf4237d6685cbf7ae986dc4dfa4dfee76` remained healthy, ready, `CURRENT`,
`KNOWN_COMPLETE`, and `128/128`. Three HIGH Episodes reached fully evaluable Underwriting; each was
a known non-Candidate because credit did not exceed the fixed future-cost reserve. One bounded LOW
research Control opened in the stable schema-v5 repository, while admitted Shadow count remained
zero.

**Primary blocker:** `ORDERED_QUEUE_LAG_DESTRUCTIVE_PRECONFIRMATION_RESET`. On the
threshold-crossing refresh, the queue-lag currentness gate correctly changed every current Radar
evaluation to `UNKNOWN`, but the bucket owner also erased every nonzero, not-yet-active
confirmation. One known HIGH target changed `2 → 0`; the global `CORE_UNKNOWN` reset counter
increased by `13`. About half a second later the same session, bucket leader, HIGH band, and
source-confirmed baseline recovered, yet confirmation restarted at `0 → 1`. Reconnect, protocol
gap, and continuity-epoch counts did not change.

That runtime blocker is repaired. The next observed verification blocker is
`OFFLINE_CASE_DIRECTORY_IDENTITY_MISPARSE`: the CaseStore writes a canonical `sha256:<digest>` Case
under a bare `<digest>` directory, but `report-v2-cases` duplicated the scanner and required the
directory name itself to match `sha256:<digest>`. The official report therefore rejected the first
valid Control Case before reading it. This is not Case corruption and is not the current business
funnel blocker; the measured business blocker remains
`CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE` for all three observed HIGH Episodes.

**Expected user-visible delta:** while ordered queue lag is above the fixed currentness deadline,
Radar remains `UNKNOWN`, bucket coverage is `UNKNOWN`, no observation is counted, and no Episode or
downstream admission can occur. An inactive tracker retains only confirmations already accepted
before the lag. On catch-up the current facts are recomputed: the same leader and band continue
from the retained count, while a changed leader, band, scope, or persistent core loss resets under
the existing rules.

The offline report additionally reads the exact directories produced by `ShadowCaseStore`, keeps
Control and admitted enrollment strata separate, and can independently verify the first future
admitted Shadow without changing the running service.

**Durable-data effect:** `NONE`. The repair neither creates, rewrites, migrates, nor deletes a Case
and retains the existing stable schema-v5 repository.

**Complexity added:** one bounded currentness-pause branch in the existing runtime bucket owner, in
addition to the already-landed aligned-source timestamp tuple; one public CaseStore-owned
directory-name conversion function; no new state owner, timer, schema, history, or baseline path.

**Complexity deleted:** the rotating five-phase sampling behavior, the wall-clock-ahead-of-source
anchor race, the misleading baseline source label, the destructive interpretation of a transient
ordered backlog as lost pre-confirmation evidence, and the offline report's duplicate Case identity
parser.

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

For the reader boundary, create or observe one store-written bare 64-hex Case directory and run the
official report. Rejecting that directory, changing its Case identity, or mixing its Control row
into admitted Shadow is a direct falsification.

## Change declarations

**Market/Decision input contract change:** five-minute index-chart samples remain fixed to the
source-confirmed UTC epoch grid. Ordered queue-lag currentness is a pre-activation observation pause,
not evidence that previously accepted observations disappeared; current score and admission truth
remain `UNKNOWN` until catch-up.

**Decision Policy change:** `NONE`; the three Policy artifacts and identities remain byte-exact.

**Outcome/evaluation contract change:** `NONE`.

**Stage/authorization change:** authorize the bounded offline reader closure in the existing Draft
PR without restarting `127.0.0.1:8675` or changing its stable Case root. Continued public-only
observation runs until the first admitted active Shadow or a newly measured fixed blocker is
established. No private or execution permission is added.

## Scope

**In:** the sole runtime bucket-settlement owner and its queue-lag currentness transition; the
already-landed `IndexHistoryReducer` source-grid repair; the CaseStore-owned directory identity
conversion and read-only V2 report; focused market/runtime/Workbench/Case/report tests; owning
contracts, task, and Current Stage authority; continued bounded public-only observation.

**Out:** score weights, thresholds, TTE/Delta rules, confirmation counts or separations, preservation
of an already-active Episode, any Policy artifact, Underwriting or Position economics, Case schema,
state-root migration, private data, orders, fills, capital, process supervision, or a second
baseline path.

**Owning modules:** `apps/radar_runtime/src/radar_runtime/runtime.py`,
`apps/radar_runtime/src/radar_runtime/offline_report.py`, and
`packages/short_vol_underwriting/src/short_vol_underwriting/case_store.py`

## Validation

- focused tests: `.venv/bin/pytest -q tests/test_market_monitor.py tests/test_runtime_reducer.py tests/test_fact_boundary_business.py tests/test_trader_workbench.py`;
- repository gate: `make check`;
- public observation: after binding the Draft PR and passing repository checks, clean-stop the
  current runtime once, start the clean repair commit on port `8675` with
  `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`, verify exact runtime identity,
  health/readiness/currentness, fixed-grid baseline behavior across canonical boundaries, and
  continue the already-authorized public-only monitor;
- run `report-v2-cases --runtime-active` against the unchanged stable root and prove the first
  store-written Control Case is readable under its canonical prefixed identity;
- no manifest, receipt, commissioning subsystem, runtime self-acceptance, or host inspection.

## Definition of done

The rotating phase, source-ahead race, and queue-lag destructive pre-confirmation reset are
impossible by direct tests; the official reader accepts store-owned bare digest directories and
preserves their canonical prefixed Case identities; the full repository gate passes; the live
clean repair commit remains current; threshold-crossing lag contributes zero observations while a
same-truth recovery retains the prior count; any first active admitted Shadow is verified through
the API and official Case reader, or the next truthful fixed funnel blocker is reported without
changing Policy to manufacture admission; the diff is bounded and remote state is exact.
