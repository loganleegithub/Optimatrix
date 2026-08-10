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
source-event age was `4,616 ms` and maximum last-wire age was `4,068 ms`. The later pre-stop
same-frame inventory caught `RUNNING / STALE / ready=false`, `QUEUE_LAG_CURRENTNESS`, and `0 / 128`
known instruments with no reconnect or session gap, proving that reducer backlog is intermittent.

**Primary blocker:** `GENERIC_MARKET_DELAY_SEMANTICS_CONFLATED`

**Expected user-visible delta:** Workbench distinguishes latest exchange-event age, local wire
silence, and the Policy-owned application queue-lag state; a value above five seconds no longer
misstates which boundary is delayed. This task attributes the now-observed intermittent reducer
backlog but does not pretend that a presentation/schema change eliminates it or add an unmeasured
synchronous hot-path optimization.

**Durable-data effect:** `NONE`. The consumed pre-stop Workbench and official schema-v5 report both
found `0` Case/Entry/Position/Outcome/Control rows, so no Segment is closed or recovered and no Case
is migrated, copied, deleted, or rewritten.

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

**Valid zero/UNKNOWN:** the first sample's zero queue-lag incident count was valid for that bounded
window, not proof of absence. The pre-stop inventory later proved an intermittent reducer backlog;
schema v7 makes that blocker visible without converting a transient `UNKNOWN` into readiness or
authorizing speculative runtime optimization.

**Cheapest falsification:** a direct Workbench projection test that holds wire age/currentness
healthy while source-event age exceeds five seconds, plus one bounded live sample and focused
runtime tests for any measured hot-path change.

## Change declarations

**Market/Decision input contract change:** `NONE`

**Decision Policy change:** `NONE`

**Outcome/evaluation contract change:** `NONE`

**Stage/authorization change:** the pre-stop inventory is consumed. Authorize PR #39 merge and
topic-branch deletion, one clean-stop of the owned 8675 session, and one schema-v7 restart from
clean synchronized `main` on the same stable root, followed by one bounded loopback/Case-reader
smoke. No second restart or root is authorized.

## Scope

**In:** current latency ownership in `radar_runtime`, Workbench projection/rendering, direct tests,
owning contract wording, bounded live inventory, PR #39 merge, branch deletion, and one clean 8675
schema-v7 cutover after its durable effect is fixed.

**Out:** Radar score or threshold changes, Policy artifacts, Underwriting, Candidate, Case/Control,
Position/Outcome, durable schema, state-root migration/copy/delete, transport reconnect policy,
process supervision, host PID/log/resource inspection, and unrelated UI redesign.

**Owning module:** `apps/radar_runtime/src/radar_runtime/workbench.py`; `runtime.py` owns only the
already-calculated current queue-processing-lag scalar.

## Validation

- focused tests: exact Workbench/frontend/runtime tests selected after attribution;
- repository gate: `make check`;
- public observation: the consumed maximum 45-second latency sample; one pre-stop same-frame
  inventory; then, only after exact cutover authority, six GET/HEAD routes plus schema-v7 identity,
  latency-field, readiness, coverage, and official Case-reader checks;
- no manifest, receipt, commissioning, host audit, or broad evidence package.

## Definition of done

The apparent-delay root cause is quantitatively attributed; Workbench exposes the correct latency
meaning; currentness remains fail-closed;
focused and repository checks pass; no Policy or durable-data change exists; and the Draft PR plus
remote state are reported accurately.
