# Task — Inverse BTC Natural Shadow Validation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN — the one authorized attempt is consumed and its gate is `REJECTED`

**Base commit:** `89a6eb02ab3771c5e6d2874a98463c6100b04165`

**Target branch/PR:** `codex/close-inverse-btc-gate-failure` / closure PR pending; authorization
history is PR [#28](https://github.com/loganleegithub/Optimatrix/pull/28)

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md),
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `APPLICABLE_MARKET_SCOPE` for `INVERSE_BTC_V1`

**Baseline:** PR #27 construction remains accepted at merged-main code identity
`89a6eb02ab3771c5e6d2874a98463c6100b04165`. The one Inverse process reached two valid
`RUNNING/CURRENT/ready` and isolated snapshots but the samples were `100,000 ms` apart against the
frozen `30,000 ms` maximum. It stopped cleanly with `0` Candidate, `0` Cases, and `0` Outcomes.

**Primary blocker:** `GATE_OBSERVATION_INTERVAL_UNPROVEN`; the first-600-second precondition cannot
be accepted and the one-start Authority is consumed.

**Expected user-visible delta:** current Authority no longer exposes stale start permission and
reports the exact failed gate, clean stop, zero Case/Outcome result, and upgrade condition of fresh
human Authority plus a fully prepared sampling procedure before any later start.

**Durable-data effect:** the consumed process wrote no Case business file. The official verifier
reports `case_count=0`; this closure changes only Authority/docs/tests.

**Complexity added:** `NONE`; this task uses the accepted runtime, Workbench, Policies, Case schema,
and official reader.

**Complexity deleted:** stale one-start permission after that start was consumed.

## Business closure

**Given:** PR #28 and its merged-main CI authorized one exact Inverse start.

**When:** the process produced valid exact-identity snapshots at fact monotonic boundaries
`324556817` and `324656817`, `100,000 ms` apart against a `30,000 ms` maximum.

**Then:** `CURRENT_AND_COMBO_ISOLATION` is rejected as unproven; the process stops cleanly without
restart; the official verifier reports zero Cases; and all live commands return to forbidden.

**Valid zero/UNKNOWN:** zero Cases and Outcomes is truthful but does not close the requested product
validation because the gate failed. No runtime or isolation defect is inferred from the unobserved
interval.

**Cheapest falsification:** the measured `100,000 ms > 30,000 ms` sample gap already falsifies gate
acceptance; no additional live check is authorized.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** mark the one-start authorization consumed, the gate rejected, the
service cleanly stopped, and every live command forbidden pending fresh human Authority.

## Scope

**In:** Authority/contracts, README, this active but incomplete validation task, direct Authority
tests, and read-only terminal verification of the consumed state root.

**Out:** every live command; runtime or Policy edits; second process/restart/state root; threshold
tuning; private APIs/orders/fills/capital/account margin; injected/replayed data; qualification;
execution; application commissioning; broad evidence package; host inspection or supervision.

**Owning module:** the accepted `radar_runtime` composition owns the one process; `options_domain`
owns product economics; `short_vol_underwriting.ShadowCaseStore` remains the sole durable reader and
writer.

## Validation

- focused tests: `pytest -q tests/test_authority_and_architecture.py`;
- repository gate: `make check`;
- public observation: `NOT_APPLICABLE`; the one authorized attempt is consumed;
- durable result: official Case-directory verification with `--allow-zero` reports `case_count=0`;
- no manifest, receipt, commissioning, host inspection, or broad evidence package.

## Definition of done

The requested validation is not done. This terminal closure is complete only when stale permission
is removed, the exact rejected-gate/zero-Case truth is authoritative, checks and merged-main CI
pass, and no restart occurs. A later attempt requires fresh human Authority and is not implied by
this task, code, tests, or CI.
