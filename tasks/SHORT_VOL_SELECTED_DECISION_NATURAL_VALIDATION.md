# Task — Selected Decision Natural Validation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** CURRENT_PROCESS_ONLY_NO_RESTART

**Runtime code commit:** `6dee819961d76b622dbc6b77997e1f987451a096`

**Runtime identity:** `sha256:fdb4f0b3eadfc0f892cfad210142d14c521394cfeb6fbd5c761554228c45998f`

**State root:** `/private/tmp/optimatrix-natural-shadow-currentness-repair-T6MhNA`

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** selected-decision research branch after `UNDERWRITING_EVALUABLE`, separate
from the canonical `CANDIDATE → SHADOW_CASE_OPENED` conversion

**Baseline:** the queue-lag throughput repair is merged and live. The exact current process reached
`RUNNING/CURRENT`, then produced 600/600 one-second CURRENT samples with zero STALE or unavailable
samples and maximum observed data delay `4,783 ms`. This proves the frozen three-observation path
has one uninterrupted 600-second window. The same window produced zero natural Episode, activation
batch, Candidate, Case, or Outcome, so selected-decision Outcome quality remains `NOT_YET_OBSERVED`.

**Primary blocker:** `NATURAL_SELECTED_DECISION_SAMPLE_NOT_YET_OBSERVED` over zero naturally
observed activation batches on the repaired accepted runtime

**Expected user-visible delta:** the existing Workbench continues to expose current health,
canonical and selected-decision funnels, original/refreshed action and complete margins, exact
refresh terminal, enrollment, future Outcome or honest pending/censoring, and reconnect state.

**Durable-data effect:** only an admitted Candidate or the one pre-outcome selected WATCH/ABSTAIN
control may create the already-authorized `SHADOW_CASE_OPENED`, optional first CLOSE, and Outcome
records beneath this runtime's Case directory. Zero enrollment creates zero Case files.

**Complexity added:** NONE

**Complexity deleted:** the completed queue-lag implementation task and merged feature branch

## Business closure

**Given:** the exact already-running public-only process, its frozen three-Policy chain, current
128/128 option scope, fresh external state root, and no other authorized public Shadow process.

**When:** that same process continues without restart through natural public facts.

**Then:** `funnel.decision_control_research.decision_outcome_count >= 1` and the corresponding
`decision_controls.rows[].case_state` is neither `PENDING_OUTCOME` nor `NOT_OPENED`, conserving the
first naturally completed selected-decision Outcome from activation batch through future-blind
selection, strictly later paired refresh, discriminated Case enrollment, strictly future
Position/close, and Outcome. The operator then requests one clean stop.

Explicit human stop, renewed `QUEUE_LAG_CURRENTNESS`, or fatal process failure is also a terminal
boundary but does not manufacture a successful Outcome sample. Zero activation or an unevaluable
selection remains exact zero/`UNKNOWN`, not 0% Outcome quality.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** retain only the currently running repaired production-public
process. No second process or restart is authorized.

## Scope

**In:** loopback Workbench reads, the current process's public Deribit facts, resulting authorized
Case records, clean operator stop, and deterministic offline repository inspection.

**Out:** implementation or Policy edits; a probe, smoke, second process, or restart; threshold,
fee, quantity, universe, or currentness-deadline changes; private/account API; order/fill/capital;
supervisor; manifest; replay; full-feed persistence; qualification or Policy promotion.

**Owning module:** current `radar_runtime` process; no implementation changes

## Validation

- current loopback `/healthz`, `/readyz`, and `/api/workbench/current` identities and truth;
- pre-registered canonical and selected-decision funnel fields;
- exact refresh terminal/reasons, enrollment, Case/Outcome/censoring, session epoch and reconnects;
- Case reader conservation for any enrollment;
- clean terminal summary after first selected-decision Outcome or explicit human stop;
- no new live command, process, runtime dependency, manifest, or receipt.

## Definition of done

The current process either produces one complete selected-decision Outcome or terminates with an
exact zero/`UNKNOWN` summary. Any Case conserves through the existing reader; pre-enrollment durable
writes remain zero; and the final conclusion separates implementation acceptance, live currentness,
natural sample quality, and strategy non-claims.
