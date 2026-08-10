# Task — V2 market-latency attribution

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `52c61d411ada7838777b15a0555ddae3f7f26958`

**Target branch/PR:** `codex/v2-market-latency-attribution` / Draft PR
[`#39`](https://github.com/loganleegithub/Optimatrix/pull/39)

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** the accepted cutover snapshot was `107,371 / 113,251` post-warmup known Radar
evaluations. In the authorized 45-observation sample, `45 / 45` were `KNOWN_COMPLETE 128 / 128`,
ready and current; queue-lag mentions, reconnects, and session gaps were all zero. Maximum generic
source-event age was `4,616 ms` and maximum last-wire age was `4,068 ms`.

**Primary blocker:** `GENERIC_MARKET_DELAY_SEMANTICS_CONFLATED`

**Expected user-visible delta:** Workbench distinguishes latest exchange-event age, local wire
silence, and the Policy-owned application queue-lag state; a value above five seconds no longer
misstates which boundary is delayed. The bounded observation found no actual queue-lag incident, so
the task adds no speculative synchronous hot-path optimization.

**Durable-data effect:** `NONE`; no Case record, state root, or pre-Shadow business fact is written.

**Complexity added:** one bounded current queue-lag scalar in the existing reducer/Workbench
snapshot; no new module, protocol, background task, queue, cache, retry, or dependency.

**Complexity deleted:** the ambiguous generic `data_delay_ms` product presentation.

## Business closure

**Given:** the sole 8675 V2 runtime publishes current source timestamps, receive boundaries, and
queue-currentness truth from one causal reducer.

**When:** one bounded read-only sample attributes repeated apparent delay and the owning projection
is corrected or optimized.

**Then:** the trader can tell exchange-event silence from transport silence and reducer backlog;
the fixed `5,000 ms` queue deadline is applied and displayed only against receive-to-reducer lag.

**Valid zero/UNKNOWN:** the observed zero queue-lag incident count is valid evidence that the
reported symptom is not proven reducer backlog; it requires the semantic Workbench correction but
does not authorize speculative runtime optimization.

**Cheapest falsification:** a direct Workbench projection test that holds wire age/currentness
healthy while source-event age exceeds five seconds, plus one bounded live sample and focused
runtime tests for any measured hot-path change.

## Change declarations

**Market/Decision input contract change:** `NONE`

**Decision Policy change:** `NONE`

**Outcome/evaluation contract change:** `NONE`

**Stage/authorization change:** the one loopback-only, read-only, maximum 45-second sample of
`/api/workbench/current` on `127.0.0.1:8675` is consumed; no further live command, stop, restart,
root access, external source probe, or second runtime.

## Scope

**In:** current latency ownership in `radar_runtime`, Workbench projection/rendering, direct tests,
owning contract wording, and the bounded 8675 sample.

**Out:** Radar score or threshold changes, Policy artifacts, Underwriting, Candidate, Case/Control,
Position/Outcome, durable schema, state roots, transport reconnect policy, process supervision,
host PID/log/resource inspection, stop/restart/deployment, and unrelated UI redesign.

**Owning module:** `apps/radar_runtime/src/radar_runtime/workbench.py`; `runtime.py` owns only the
already-calculated current queue-processing-lag scalar.

## Validation

- focused tests: exact Workbench/frontend/runtime tests selected after attribution;
- repository gate: `make check`;
- public observation: maximum 45 seconds of loopback GET sampling from
  `http://127.0.0.1:8675/api/workbench/current`, retaining no runtime dependency or durable product
  record;
- no manifest, receipt, commissioning, host audit, or broad evidence package.

## Definition of done

The apparent-delay root cause is quantitatively attributed; Workbench exposes the correct latency
meaning; currentness remains fail-closed;
focused and repository checks pass; no Policy or durable-data change exists; and the Draft PR plus
remote state are reported accurately.
