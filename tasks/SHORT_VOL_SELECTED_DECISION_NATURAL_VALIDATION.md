# Task — Selected Decision Natural Validation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Base commit:** `92cb0fe2663db4ed9c2d99d87895c903ce4e58f7`

**Target branch/PR:** `codex/selected-decision-natural-validation`; Draft PR against `main`

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** selected-decision research branch after `UNDERWRITING_EVALUABLE`, separate
from the canonical `CANDIDATE → SHADOW_CASE_OPENED` conversion

**Baseline:** the completed pre-selector natural run produced `7` Underwriting-evaluable Episodes,
`0` Candidates, `0` Cases, and `0` Outcomes. No natural activation batch has yet been observed on
the accepted selector/control implementation, so its Outcome denominator is zero and quality is
`NOT_YET_OBSERVED`, not 0%.

**Primary blocker:** `NATURAL_SELECTED_DECISION_SAMPLE_NOT_YET_OBSERVED` over `0` naturally
observed activation batches under the accepted implementation

**Expected user-visible delta:** one live Workbench exposes current health plus separate canonical
and selected-decision funnels, original/refreshed actions and complete margins, exact refresh
terminal, enrollment, future Outcome or honest pending/censoring, and reconnect state.

**Durable-data effect:** only an admitted Candidate or the one pre-outcome selected WATCH/ABSTAIN
control may create the already-authorized `SHADOW_CASE_OPENED`, optional first CLOSE, and Outcome
records beneath this runtime's Case directory. Zero enrollment creates zero Case files.

**Complexity added:** `NONE`; this task runs the accepted service without new code, schema,
Policy, monitor, manifest, supervisor, or diagnostic store.

**Complexity deleted:** the completed implementation task and both merged feature branches.

## Business closure

**Given:** clean merged `main`, successful repository CI, the exact three Policy identities in
`CURRENT_STAGE`, a fresh absolute state root outside the repository, and no other authorized public
Shadow process.

**When:** exactly one `serve-shadow` process starts, reaches `RUNNING/CURRENT` through its own
loopback Workbench, and continues without restart through natural public facts.

**Then:** `funnel.decision_control_research.decision_outcome_count >= 1` and the corresponding
`decision_controls.rows[].case_state` is neither `PENDING_OUTCOME` nor `NOT_OPENED`, conserving the
first naturally completed selected-decision Outcome from activation batch through pre-outcome
selection, strictly later paired refresh, discriminated Case enrollment, strictly future
Position/close, and Outcome. The counter covers both a selected Candidate admitted Outcome and a
selected WATCH/ABSTAIN control Outcome. The operator then requests one clean stop. Explicit human
stop or fatal process failure is also a terminal run boundary but does not manufacture a successful
Outcome sample.

**Valid zero/UNKNOWN:** readiness failure, no natural activation batch, an unevaluable selection,
invalid paired refresh, or a still-pending Case remains exact zero/`UNKNOWN`. A clean human stop with
zero Outcome is a valid terminal observation but does not close the sample blocker.

**Cheapest falsification:** in the same service process, `/healthz`, `/readyz`, and
`/api/workbench/current` must show the frozen identities and `RUNNING/CURRENT`; any mismatch or fatal
startup ends this run without a restart. There is no separate smoke process.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** authorize one production-public natural Shadow process from the
clean post-merge main code through first selected-decision Outcome, explicit human stop, or fatal
process failure. Recoverable reconnect stays inside the same runtime; process restart requires new
explicit authorization.

## Scope

**In:** Authority/task cleanup, existing offline gates, one fresh external runtime/state root,
loopback Workbench health/current-state reads, public Deribit facts, and resulting authorized Case
records.

**Out:** implementation or Policy edits; threshold/fee/quantity/Radar changes; separate probe or
smoke; second process; automatic restart; private/account API; Combo creation; RFQ; order; fill;
capital; qualification; deployment supervisor; host inspection; manifest; receipt chain; full-feed
history; online Cohort or Challenger.

**Owning module:** `radar_runtime` existing persistent public Shadow service

## Validation

- focused tests: `.venv/bin/python -m pytest -q tests/test_authority_and_architecture.py`;
- repository gate: `make check`;
- public observation: `.venv/bin/python -m radar_runtime serve-shadow --state-root <fresh-absolute-root> --workbench-host 127.0.0.1 --workbench-port 8765`;
- same-process startup gate: loopback `/healthz`, `/readyz`, and `/api/workbench/current`;
- pre-registered observation: frozen code/runtime/three-Policy identities; service/data/ready state;
  canonical post-warmup numerator/denominator and blockers; activation batches; original and
  refreshed action counts/margins; attempt terminals/reasons; Candidate/Control enrollment;
  `funnel.decision_control_research.decision_outcome_count` and corresponding
  `decision_controls.rows[].case_state`; Case/Outcome/censoring; session epoch and reconnects;
- terminal boundary: first selected-decision Outcome followed by clean operator stop, explicit human
  stop, or fatal process failure;
- no manifest, receipt, commissioning, host audit, separate smoke, or qualification claim.

## Definition of done

The clean merged code reaches same-process `RUNNING/CURRENT`, its identities match the frozen
Authority, and the natural run either produces one complete selected-decision Outcome or reports an
exact terminal zero/`UNKNOWN` without changing Policy or contaminating the canonical Candidate
funnel. Any Case conserves through the existing reader; pre-enrollment durable writes remain zero;
the final conclusion separates code gates, live health, natural sample, and strategy non-claims.
