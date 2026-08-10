# Task — V2 index-grid phase repair

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

**Baseline:** at `2026-08-11 02:32:18 +0800`, the live runtime had
`33,482,555` known post-warmup instrument evaluations and zero distinct canonical
`ANOMALY_ACTIVE` Episodes, zero admitted Shadow Cases, and zero Positions. Direct live sampling
observed the same eligible multiday HIGH leader recur approximately every five minutes, remain
HIGH for approximately 120 seconds, and reset before its 300-second second-confirmation boundary.

**Primary blocker:** `ALIGNED_INDEX_HISTORY_REFRESH_RACE`. The initial repair removed
`ROTATING_FIVE_MINUTE_INDEX_SAMPLE_PHASE`: the official one-minute chart can no longer rotate the
five-minute sample phase. Live validation then reached confirmation `2/3`, but at the next UTC grid
boundary it reset `2 → 0 → 1` while the same leader remained known, HIGH, and book-usable. In that
same frame the global `CORE_UNKNOWN` counter increased by `12`. Trusted time had advanced the
required anchor before the independently phased five-minute chart refresh had delivered that
anchor, creating a one-frame `INDEX_HISTORY_WINDOW_GAP` across the active buckets.

**Expected user-visible delta:** a declared five-minute baseline uses the latest completed,
source-confirmed UTC-epoch-aligned grid point. Trusted-time movement cannot rotate its phase or
advance it ahead of the public chart response. A newly delivered aligned point advances the tuple
atomically. Workbench identifies this source-confirmed semantics explicitly, and the artificial
five-minute confirmation reset disappears.

**Durable-data effect:** `NONE` before a normal V2 admission. The repair neither creates nor
migrates a Case and retains the existing stable schema-v5 repository.

**Complexity added:** one bounded tuple of aligned source timestamps inside the existing history
owner for logarithmic source-ready anchor selection; no second history or baseline path.

**Complexity deleted:** the rotating five-phase sampling behavior, the wall-clock-ahead-of-source
anchor race, and the misleading baseline source label.

## Business closure

**Given:** strictly chronological, minute-aligned Deribit index-chart `average_price` points and a
Policy return interval of five minutes.

**When:** trusted time crosses a canonical five-minute boundary before or after the next public
chart refresh delivers the newly completed aligned point.

**Then:** `IndexHistoryReducer.current_tail` retains the prior exact sampled tuple and economic
identity until the next UTC-aligned five-minute point is both causally complete and source-confirmed;
it then advances atomically.

**Valid zero/UNKNOWN:** a missing interior point inside the selected aligned suffix remains
`WINDOW_GAP`; stale, revision, warmup, and invalid source states remain truthful. A newly completed
but not-yet-delivered leading anchor is normal refresh latency and retains the prior valid suffix.
Zero canonical Shadow admissions is valid if no corrected HIGH survives Policy persistence or
Underwriting does not produce a Candidate; artificial phase rotation or refresh-race reset is not
valid.

**Cheapest falsification:** feed one-minute points whose five phase offsets have deliberately
different realized variance, advance trusted time minute by minute, and observe any sampled tail
or baseline change before the next aligned five-minute boundary.

## Change declarations

**Market/Decision input contract change:** five-minute index-chart samples are fixed to UTC epoch
alignment and advance only to a completed aligned point already present in the public response,
instead of being re-anchored to finer points or projected ahead of the response.

**Decision Policy change:** `NONE`; the three Policy artifacts and identities remain byte-exact.

**Outcome/evaluation contract change:** `NONE`.

**Stage/authorization change:** authorize this bounded repair and its Draft PR. The first clean
stop/start established the source-ahead race; one additional clean stop/start on `127.0.0.1:8675`
from the amended clean repair commit may use the unchanged stable Case root. Continued public-only
observation runs until the first admitted active Shadow or a newly measured fixed blocker is
established. No private or execution permission is added.

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

The rotating phase and source-ahead race are impossible by direct tests; the full repository gate
passes; the live clean repair commit remains current while the baseline tuple advances only when a
canonical aligned point is source-confirmed; any first active admitted Shadow is verified through
the API and official Case reader, or the next truthful fixed funnel blocker is reported without
changing Policy to manufacture admission; the diff is bounded and remote state is exact.
