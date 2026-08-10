# Task — V2 index-grid phase repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `89e83e04871fd2b230b1868d399d7dec45865a6b`

**Target branch/PR:** `codex/v2-index-grid-phase-fix`; Draft PR to be bound before live cutover

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION.md`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_RADAR.md`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN → ANOMALY_ACTIVE`

**Baseline:** at `2026-08-11 02:32:18 +0800`, the live runtime had
`33,482,555` known post-warmup instrument evaluations and zero distinct canonical
`ANOMALY_ACTIVE` Episodes, zero admitted Shadow Cases, and zero Positions. Direct live sampling
observed the same eligible multiday HIGH leader recur approximately every five minutes, remain
HIGH for approximately 120 seconds, and reset before its 300-second second-confirmation boundary.

**Primary blocker:** `ROTATING_FIVE_MINUTE_INDEX_SAMPLE_PHASE`. The official chart returns
one-minute `average_price` points, while the current five-minute tail is re-anchored to the latest
completed one-minute point. Its five possible sampling phases produced live multiday annualized RV
values of approximately `28.0%`, `33.6%`, `33.1%`, `31.6%`, and `28.0%` from the same response,
making the V2 score alternate HIGH for two minutes and LOW for three minutes.

**Expected user-visible delta:** a declared five-minute baseline uses one UTC-epoch-aligned grid.
Trusted-time movement inside the same completed five-minute grid interval cannot rotate the sampled
price tuple, baseline RV, or score. Real source changes and canonical five-minute grid advancement
remain able to change the score. Workbench identifies this fixed source semantics explicitly.

**Durable-data effect:** `NONE` before a normal V2 admission. The repair neither creates nor
migrates a Case and retains the existing stable schema-v5 repository.

**Complexity added:** `NONE`; one existing tail selector gains a fixed alignment rule.

**Complexity deleted:** the rotating five-phase sampling behavior and its misleading baseline
source label.

## Business closure

**Given:** strictly chronological, minute-aligned Deribit index-chart `average_price` points and a
Policy return interval of five minutes.

**When:** trusted time advances within one canonical completed five-minute grid interval.

**Then:** `IndexHistoryReducer.current_tail` returns the same exact sampled tuple and economic
identity; it advances only after the next UTC-aligned five-minute point is causally complete.

**Valid zero/UNKNOWN:** a missing required UTC-aligned point remains `WINDOW_GAP`; stale,
revision, warmup, and invalid source states remain truthful. Zero canonical Shadow admissions is
valid if no corrected HIGH survives Policy persistence or Underwriting does not produce a
Candidate; artificial phase rotation is not valid.

**Cheapest falsification:** feed one-minute points whose five phase offsets have deliberately
different realized variance, advance trusted time minute by minute, and observe any sampled tail
or baseline change before the next aligned five-minute boundary.

## Change declarations

**Market/Decision input contract change:** five-minute index-chart samples are fixed to UTC epoch
alignment instead of being re-anchored to each latest completed one-minute source point.

**Decision Policy change:** `NONE`; the three Policy artifacts and identities remain byte-exact.

**Outcome/evaluation contract change:** `NONE`.

**Stage/authorization change:** authorize this one bounded repair, its Draft PR, one clean stop and
one start on `127.0.0.1:8675` from the clean repair commit using the unchanged stable Case root, and
continued public-only observation until the first admitted active Shadow or a newly measured fixed
blocker is established. No private or execution permission is added.

## Scope

**In:** the sole `IndexHistoryReducer` sampling owner; focused market/runtime/Workbench tests;
baseline-source wording in owning contracts and Workbench; task and Current Stage authority; the
bounded public-only cutover and observation.

**Out:** score weights, thresholds, TTE/Delta rules, confirmation counts or separations, any Policy
artifact, Underwriting or Position economics, Case schema, state-root migration, private data,
orders, fills, capital, process supervision, or a second baseline path.

**Owning module:** `packages/market_monitor/src/market_monitor/index_history.py`

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

The rotating phase is impossible by direct test; the full repository gate passes; the live clean
repair commit remains current while the baseline tuple advances only on the canonical grid; any
first active admitted Shadow is verified through the API and official Case reader, or the next
truthful fixed funnel blocker is reported without changing Policy to manufacture admission; the
diff is bounded and remote state is exact.
