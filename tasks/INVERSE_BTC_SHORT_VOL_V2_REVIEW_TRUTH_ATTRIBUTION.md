# Task — V2 review truth and blocker attribution

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Base commit:** `5a32e62069324ac83a389ca899ef0cf878650105`

**Target branch/PR:** `codex/v2-review-truth-attribution` / Draft PR pending creation

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN -> ANOMALY_ACTIVE`, plus the separate selected-decision
research projection before `SHADOW_CASE_OPENED`

**Baseline:** in the bounded pre-task observation of the accepted running code, two review-only
HIGH leaders were rendered as `0/3` confirmation despite being ineligible for a clue; the same
runtime had `21` activation batches, `18` selected decisions, `18` `KNOWN_NO_CONTROL` terminals,
and zero opened Cases, but exposed no bounded confirmation-reset or known-no-control reason split

**Primary blocker:** `REVIEW_ONLY_CONFIRMATION_MISREPRESENTED_AND_TERMINALS_UNATTRIBUTED`; the
display cannot distinguish an ineligible score row from an eligible confirmation, and collapsed
terminal counts cannot identify which fixed business condition stopped conversion

**Expected user-visible delta:** review-only TTE/Delta rows never display confirmation progress;
the Workbench shows bounded runtime counts for pre-activation confirmation resets and exact
`KNOWN_NO_CONTROL` reasons

**Durable-data effect:** `NONE`; all new diagnostics are cumulative in-memory scalars and reset
with the runtime

**Complexity added:** two fixed reason enums carried by existing Radar/Underwriting transitions and
two bounded Funnel counters; no dependency, process, storage, queue, schema family, or history

**Complexity deleted:** the false review-only `CONFIRMING 0/3` path and the unqualified collapsed
`KNOWN_NO_CONTROL` presentation

## Business closure

**Given:** a V2 score row whose TTE or Delta bucket is explicitly review-only, or an eligible
leader/selected decision whose current confirmation or refresh terminates before Case opening.

**When:** the same existing Radar tracker and Underwriting owner settle that current fact.

**Then:** review-only state remains `IDLE` and is rendered as review-only without a confirmation
fraction; every lost non-zero pre-activation confirmation and every `KNOWN_NO_CONTROL` terminal
contributes exactly one fixed, bounded, trader-readable reason count.

**Valid zero/UNKNOWN:** zero reason counts means the new runtime has not observed that transition;
it is not proof of strategy quality. Required market facts may remain `UNKNOWN`, and that does not
create an Episode, Candidate, Control Case, or Shadow admission.

**Cheapest falsification:** pure tracker/attempt tests, one deterministic reducer-to-Funnel fixture,
and one browser rendering harness.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** add only non-durable fixed reason attribution to existing
pre-activation reset and selected-decision terminal projections; no Outcome arithmetic or Case
eligibility change

**Stage/authorization change:** authorize offline implementation, tests, and one Draft PR only;
live probe, restart, deployment, and state-root access remain forbidden

## Scope

**In:** Radar bucket transition/projection, runtime-to-Funnel aggregation, Underwriting control
terminal reason, Workbench renderer, owning contracts, and direct tests

**Out:** Policy artifacts or hashes, score formula/thresholds, T/S construction, ATM interpolation,
TTE/Delta eligibility, persistence count, Case schema/root, source topology, process lifecycle,
8675 probe/restart/deployment, and private execution

**Owning module:** `short_vol_radar.bucket` for confirmation truth and
`short_vol_underwriting.owner/control` for known-no-control truth; `radar_runtime.funnel/workbench`
only project those owner-generated facts

## Validation

- focused tests: `.venv/bin/pytest -q tests/test_authority_and_architecture.py tests/test_radar_score.py tests/test_fact_boundary_business.py tests/test_selected_decision_control.py tests/test_funnel.py tests/test_trader_workbench.py tests/test_workbench_frontend_v1.py`;
- repository gate: `make check`;
- public observation: `NOT_APPLICABLE` and forbidden by this task;
- no manifest, receipt, commissioning, or broad evidence package.

## Definition of done

The declared user-visible truth and bounded attribution exist, direct and repository checks pass,
the three Policy bytes and durable schema remain unchanged, the diff is bounded, no pre-Shadow
durable record is introduced, the Draft PR reports that 8675 still runs the prior accepted main,
and no deployment authority is inferred from tests or Git.
