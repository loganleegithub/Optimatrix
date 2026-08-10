# Task — V2 queue-lag root cause

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** IMPLEMENTED_OFFLINE

**Live commands:** CONSUMED

**Base commit:** `fbc2637f362745da42a1a986b099cbe8095719b0`

**Target branch/PR:** `codex/v2-queue-lag-root-cause` / Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** the trader observes processing queue lag around `5.0 s` and market-event age around
`5.2 s`; a fresh screen frame separately shows `4.4 s` and `4.7 s`. The service is visibly running,
but the queue lag remains close to its fixed `5,000 ms` currentness deadline. The prior local-book
profile excluded the global time-boundary and Workbench-publication paths.

**Primary blocker:** `TICKER_CROSS_SECTIONAL_CORE_RECOMPUTATION`, directly reproduced and removed
offline. The remaining trader-visible blocker is `REPAIR_NOT_DEPLOYED`.

**Expected user-visible delta:** identify the exact synchronous owner consuming the interval and,
only if directly proven, remove its redundant work so processing lag no longer tracks the deadline
under the same 128-instrument public workload.

**Durable-data effect:** `NONE`; this task does not write, read, migrate, copy, delete, or rewrite a
Shadow Case or state root.

**Complexity added:** `NONE`; no queue, cache, worker, process, schema, or new owner.

**Complexity deleted:** `3,645` redundant full core calculations per modeled `135`-fact market
second in the production-shaped profile.

## Direct attribution

The consumed `25.020 s` loopback sample observed `3,366` accepted ingress frames, approximately
`134.6 frames/s`. Queue lag stayed between `4,106 ms` and `5,041 ms` with a `4,600 ms` median;
`13/92` observations crossed the currentness deadline and reduced known Radar coverage to `0/128`.
Loopback request latency remained about `20 ms` median, so the displayed delay was settled-runtime
backlog rather than browser/API request latency.

A deterministic fixture with `128` different strikes and the observed `135` facts per modeled
second reproduced the overload without network or host assumptions. Before the repair it consumed
`1.268 s` per market second and called `calculate_current_evaluation` `3,907` times. Cross-sectional
ticker dependencies correctly require same-expiry and immediately shorter-expiry S/T score refresh,
but they do not change those peers' option book, forward, TTE band, currentness, or baseline core.
The reducer nevertheless repeated Black inversion and baseline economics for every peer.

The repair separates core recalculation names from score-only dependents. The directly changed
ticker still recomputes its core; each unchanged peer reuses its already-current core and runs the
sole Radar score finalizer against the new cross-sectional context. The identical fixture then
consumed `0.675 s` per market second and made `262` core calls, exactly the required calls for `67`
ticker facts, `67` book facts, and one `128`-instrument global boundary. Workbench projection was
separately measured at approximately `26 ms` per publication and was not patched.

## Business closure

**Given:** the single-threaded runtime receives public frames while one-second global time
boundaries and immutable Workbench projections share the same event loop.

**When:** one bounded latency sample distinguishes wire silence from queue waiting and deterministic
profiles compare local-book, global time-boundary, and Workbench-publication costs over the same
128-instrument state.

**Then:** one owner and repeated operation are named with direct timing/call-count evidence, or the
result remains `UNKNOWN`; a fix is allowed only for the proven owner.

**Valid zero/UNKNOWN:** a short sample below the deadline does not erase the trader's observed
near-deadline frames. Correlated market-event age and queue lag alone do not identify causality.

**Cheapest falsification:** if the global time-boundary and Workbench projection are both bounded
well below the observed lag and wire age is also high, the local synchronous-backlog hypothesis is
rejected rather than patched.

## Change declarations

**Market/Decision input contract change:** `NONE`

**Decision Policy change:** `NONE`

**Outcome/evaluation contract change:** `NONE`

**Stage/authorization change:** the one at-most-30-second loopback sample is consumed. The bounded
branch and Draft PR are authorized. Merge, restart, state-root access, and post-start smoke remain
unauthorized until a later explicit Authority update.

## Scope

**In:** schema-v7 latency attribution, runtime scheduling, Workbench publication, existing score
context/calculation locality, direct regression tests, and one owning implementation function if
proven.

**Out:** Policy/threshold/universe/score changes; another queue, worker, process, monitor, endpoint,
schema, cache subsystem, retry, controller, sampling/drop rule, source probe, PID/log/resource
inspection, Case/Outcome changes, and UI redesign.

## Validation

- one bounded same-frame loopback sample: consumed;
- direct failing regression before the fix: reproduced;
- deterministic profile of the three existing paths: complete;
- focused tests: `262` passed;
- `make check`: format, Ruff, mypy, and `732` tests passed.

## Definition of done

The complete current bottleneck is either directly attributed and minimally removed or explicitly
left `UNKNOWN`; queue and source age remain separately reported; and no Policy or durable truth is
changed to make the alert disappear.
