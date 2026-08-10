# Task — V2 market-latency attribution

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `52c61d411ada7838777b15a0555ddae3f7f26958`

**Target branch/PR:** `codex/v2-market-latency-attribution` / one Draft PR opened from that branch

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** the accepted cutover snapshot was `107,371 / 113,251` post-warmup known Radar
evaluations; the trader now observes the Workbench's generic market-delay display repeatedly above
`5,000 ms`, but its event-age, wire-age, and queue-lag denominator is `NOT_YET_MEASURED`.

**Primary blocker:** `GENERIC_MARKET_DELAY_NOT_ATTRIBUTED`

**Expected user-visible delta:** Workbench distinguishes latest exchange-event age, local wire
silence, and the Policy-owned application queue-lag state; a value above five seconds no longer
misstates which boundary is delayed. If the bounded observation proves actual queue lag, the direct
owning synchronous function is optimized without weakening currentness.

**Durable-data effect:** `NONE`; no Case record, state root, or pre-Shadow business fact is written.

**Complexity added:** at most bounded current latency scalars in the existing reducer/Workbench
snapshot; no new module, protocol, background task, queue, cache, retry, or dependency.

**Complexity deleted:** the ambiguous generic `data_delay_ms` product presentation and any proven
redundant hot-path work found by the direct measurement.

## Business closure

**Given:** the sole 8675 V2 runtime publishes current source timestamps, receive boundaries, and
queue-currentness truth from one causal reducer.

**When:** one bounded read-only sample attributes repeated apparent delay and the owning projection
is corrected or optimized.

**Then:** the trader can tell exchange-event silence from transport silence and reducer backlog;
actual queue lag, if observed, no longer repeatedly exceeds the fixed `5,000 ms` deadline under the
same public input workload.

**Valid zero/UNKNOWN:** no queue-lag incident during the bounded sample is valid evidence that the
reported symptom is not proven reducer backlog; it requires the semantic Workbench correction but
does not authorize speculative runtime optimization.

**Cheapest falsification:** a direct Workbench projection test that holds wire age/currentness
healthy while source-event age exceeds five seconds, plus one bounded live sample and focused
runtime tests for any measured hot-path change.

## Change declarations

**Market/Decision input contract change:** `NONE`

**Decision Policy change:** `NONE`

**Outcome/evaluation contract change:** `NONE`

**Stage/authorization change:** authorize exactly one loopback-only, read-only, maximum 45-second
sample of `/api/workbench/current` on `127.0.0.1:8675`; no stop, restart, root access, external
source probe, or second runtime.

## Scope

**In:** current latency ownership in `radar_runtime`, Workbench projection/rendering, direct tests,
owning contract wording, and the bounded 8675 sample.

**Out:** Radar score or threshold changes, Policy artifacts, Underwriting, Candidate, Case/Control,
Position/Outcome, durable schema, state roots, transport reconnect policy, process supervision,
host PID/log/resource inspection, stop/restart/deployment, and unrelated UI redesign.

**Owning module:** `apps/radar_runtime/src/radar_runtime/workbench.py`; `runtime.py` only if the
bounded sample proves real queue-processing lag.

## Validation

- focused tests: exact Workbench/frontend/runtime tests selected after attribution;
- repository gate: `make check`;
- public observation: maximum 45 seconds of loopback GET sampling from
  `http://127.0.0.1:8675/api/workbench/current`, retaining no runtime dependency or durable product
  record;
- no manifest, receipt, commissioning, host audit, or broad evidence package.

## Definition of done

The apparent-delay root cause is quantitatively attributed; Workbench exposes the correct latency
meaning; any measured direct hot path is minimally optimized; currentness remains fail-closed;
focused and repository checks pass; no Policy or durable-data change exists; and the Draft PR plus
remote state are reported accurately.
