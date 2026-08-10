# Task — V2 queue-throughput repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `c7f718b9f3b1d83ad17083c84466acbcc84dcc72`

**Target branch/PR:** `codex/v2-queue-throughput-repair` / Draft PR
[`#41`](https://github.com/loganleegithub/Optimatrix/pull/41)

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** schema v7 has separated latest market-event age, last wire-message age, and
receive-to-reducer queue lag. The accepted restart frame was current at `128 / 128` with queue lag
`3,925 ms` against a `5,000 ms` deadline. A separate pre-stop frame reached
`QUEUE_LAG_CURRENTNESS`, `0 / 128`, without reconnect or session gap. The trader now reports both
market-event age and queue-processing lag elevated. The one bounded sample was consumed but its
client-side summary failed serialization, so it produced no retained aggregate and is not retried.

**Primary blocker:** `QUEUE_PROCESSING_THROUGHPUT_INTERMITTENT`

**Expected user-visible delta:** remove the measured synchronous reducer hotspot so ordinary
public-market bursts no longer make local processing lag systematically cross the fixed deadline;
keep true exchange-event age separately visible and fail closed during any remaining overload.

**Durable-data effect:** diagnosis and code verification write no business data. Before any later
restart, an official Case inventory must fix the exact Segment-close/recovery effect; no Case may
be migrated, copied, deleted, or rewritten.

**Complexity added:** one optional locality input on the existing score-context calculator; no new
process, queue, worker, monitor, schema, cache, retry, controller, or dependency.

**Complexity deleted:** a single-instrument book fact no longer constructs score contexts for all
other instruments.

## Business closure

**Given:** one public transport feeds a bounded queue and one synchronous reducer, while schema v7
reports source-event, wire, and receive-to-reducer latency independently.

**When:** direct deterministic profiling identifies which existing reducer operation dominates a
lagging fact transaction, and the smallest owning-boundary repair removes that redundant work.

**Then:** direct regression/throughput tests prove unchanged decision truth with less repeated work,
and any later explicitly authorized live smoke reports each latency dimension without conflation.

**Valid zero/UNKNOWN:** a bounded sample that catches no lag is valid only for that window; it does
not erase the previously observed incident. `QUEUE_LAG_CURRENTNESS` remains fail-closed and cannot
be reclassified as healthy to make the test pass.

**Cheapest falsification:** the 128-instrument direct profile measured `10.698 ms` per single-book
transaction before the locality repair and `1.724 ms` after it; a regression test requires exactly
one score context for the one affected instrument while preserving the full surface point set.

## Change declarations

**Market/Decision input contract change:** `NONE`

**Decision Policy change:** `NONE`

**Outcome/evaluation contract change:** `NONE`

**Stage/authorization change:** the one loopback sample is consumed without a retained aggregate;
no retry, stop, restart, state-root mutation, or deployment is authorized yet.

## Scope

**In:** bounded loopback attribution, synchronous reducer transaction locality, the directly owning
calculator/projection, focused regression/throughput tests, and exact Workbench non-claim wording
only if the measured root cause requires it.

**Out:** Policy/threshold/universe/score changes, second queues or workers, async fan-out, sampling
or dropping market facts, Case/Outcome schema, state-root migration, transport reconnect policy,
process supervision, PID/log/resource inspection, and unrelated UI work.

**Owning module:** `short_vol_radar.review.build_score_feature_contexts`; runtime passes its already
owned `recalculation_names` locality.

## Validation

- focused test first reproduces redundant work or latency amplification;
- direct deterministic profile/benchmark validates the owning function rather than whole-host CPU;
- `make check`;
- live deployment only after a later explicit inventory and cutover authority.

## Definition of done

The real synchronous hotspot is identified rather than inferred from two correlated ages; its
redundant work is removed without changing business decisions or currentness; focused and full
checks pass; durable data is preserved; and remaining latency risk is reported without claiming a
single bounded window proves future performance.
