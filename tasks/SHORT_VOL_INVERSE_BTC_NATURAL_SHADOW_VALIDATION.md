# Task — Inverse BTC Natural Shadow Validation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Base commit:** `89a6eb02ab3771c5e6d2874a98463c6100b04165`

**Target branch/PR:** `codex/inverse-btc-natural-shadow-validation` / Draft PR pending

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

**Baseline:** PR #27 construction is accepted at merged-main code identity
`89a6eb02ab3771c5e6d2874a98463c6100b04165`, but Inverse has `0` natural applicable evaluations,
`0` natural Cases, and `0` natural Outcomes. The accepted Linear terminal funnel remains
`5,043,177` applicable, `5,040,616` Radar-known, `11` Episode, `6` Underwriting-evaluable, and
`0` Candidate; it is not part of this run.

**Primary blocker:** `INVERSE_NATURAL_SHADOW_NOT_OBSERVED` over the one requested product slice.

**Expected user-visible delta:** the one exact Inverse process first proves same-process public
`CURRENT` and negative cross-product/Combo contamination over 600 seconds, then continues without
restart until the first natural schema-v4 Outcome can be reviewed with its product, enrollment
kind, native BTC economics, explicit USD valuation, and truthful known/unknown terminal state.

**Durable-data effect:** the Authority/doc change writes no runtime data. After activation, only the
existing schema-v4 `SHADOW_CASE_OPENED`, first-close transition, and `SHADOW_CASE_OUTCOME` family may
be written under the one registered state root. Each record belongs to its already-open Inverse
Case and is consumed directly by the official reader and later offline research. The 600-second
gate and Workbench samples remain non-durable.

**Complexity added:** `NONE`; this task uses the accepted runtime, Workbench, Policies, Case schema,
and official reader.

**Complexity deleted:** the completed construction task and registered live topology `NONE`.

## Business closure

**Given:** PR #27 merged as `89a6eb02ab3771c5e6d2874a98463c6100b04165`, its merged-main CI
passed, and the Authority PR for this task is itself merged with merged-main CI passing.

**When:** exactly one clean `inverse-btc` process starts with the registered implementation,
three-Policy chain, state root, and loopback Workbench; its first 600 seconds are observed through
the same Workbench and the process then continues unchanged.

**Then:** that runtime passes the exact `CURRENT_AND_COMBO_ISOLATION` gate and later writes the first
official-reader-complete natural Inverse schema-v4 Outcome with terminal state `MATURE_KNOWN` or
`MATURE_UNKNOWN`; the enrollment kind and non-claims are reported, then the process stops cleanly.

**Valid zero/UNKNOWN:** zero clues, Episodes, Candidate, Cases, or Outcomes during the first 600
seconds is valid if the gate itself passes. Afterward, zero qualifying Outcomes is truthful but does
not close the task: the same process keeps waiting. `MATURE_UNKNOWN` is a qualifying research
Outcome; censoring, incomplete Case bytes, or gate failure is not.

**Cheapest falsification:** the first changed identity, Linear/USDC-contaminated fact, unreadable
Workbench snapshot after first response, non-`CURRENT` terminal gate sample, process exit, or
official-reader rejection ends the authorized attempt without restart.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** replace offline construction-only topology `NONE` with one exact
`VALIDATION_ONLY`, Inverse-only, single-process, no-restart natural Shadow topology whose first 600
seconds gate continued observation.

## Scope

**In:** Authority/contracts, README, this one active task, direct Authority tests, and—only after
Authority merge plus merged-main CI—the exact one-start public Inverse observation and official
schema-v4 Case read.

**Out:** runtime or Policy edits; Linear observation; second process/restart/state root; threshold
tuning; private APIs/orders/fills/capital/account margin; injected/replayed data; qualification;
execution; application commissioning; broad evidence package; host inspection or supervision.

**Owning module:** the accepted `radar_runtime` composition owns the one process; `options_domain`
owns product economics; `short_vol_underwriting.ShadowCaseStore` remains the sole durable reader and
writer.

## Validation

- focused tests: `pytest -q tests/test_authority_and_architecture.py`;
- repository gate: `make check`;
- public observation: the exact `serve-shadow` command and Workbench gate registered in
  `CURRENT_STAGE`, followed by the same-process Outcome wait;
- durable result: official reader over the first qualifying Inverse schema-v4 Case before and after
  one clean stop;
- no manifest, receipt, commissioning, host inspection, or broad evidence package.

## Definition of done

The Authority diff is bounded and merged-main CI passes; exactly one registered process starts;
that same runtime passes the full 600-second gate, yields one qualifying natural Inverse schema-v4
Outcome, and stops cleanly; the official reader accepts the Case; no restart, code/Policy change,
Linear contamination, or new durable kind occurs; and exact remote/runtime/result limitations are
reported. The gate alone and green checks alone do not satisfy this task.
