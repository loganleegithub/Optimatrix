# Task — Inverse BTC Product Contract and Normalization

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Base commit:** `e9ee9217be6189d4079548715b1c273813d6ef44`

**Target branch/PR:** `codex/inverse-btc-product-construction` / Draft PR pending creation

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md),
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `APPLICABLE_MARKET_SCOPE` for the requested Inverse BTC product slice

**Baseline:** accepted Linear BTC-USDC terminal funnel is `5,043,177` applicable,
`5,040,616` Radar-known, `11` Episode, `6` Underwriting-evaluable, and `0` Candidate. Inverse BTC
has `0` applicable evaluations because its product economics are not implemented or authorized to
run.

**Primary blocker:** `INVERSE_PRODUCT_SEMANTICS_UNSUPPORTED` over the one requested additional
product slice. The separate measured Linear downstream blocker remains
`CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE 6/6` and is not changed by this task.

**Expected user-visible delta:** the same application can be configured at startup for exactly one
strict `LINEAR_BTC_USDC_V1` or `INVERSE_BTC_V1` profile; Workbench state explicitly labels product,
price index, native premium/fee/settlement unit, and USD valuation basis. Linear behavior remains
unchanged.

**Durable-data effect:** no record is written by implementation or tests. Existing Linear schema
v3 Cases remain byte-compatible and readable. A future authorized Inverse `SHADOW_CASE_OPENED` may
use product-aware schema v4 and carry the minimum product/native-unit facts required to conserve
entry, first-close, and Outcome economics; those facts belong to that already-open Case and are
consumed directly by the Case reader and offline research.

**Complexity added:** one strict product specification/profile, three Inverse Policy artifacts,
product-aware branches in the existing calculator/runtime/Workbench/Case owner, and direct tests.

**Complexity deleted:** the stale running-runtime authority and completed validation task.

## Business closure

**Given:** the accepted Linear product behavior, official Deribit Inverse option contract/fee
semantics, and one shared modular-monolith state machine.

**When:** startup selects a content-bound product profile and product-aware facts pass through the
existing parser, Radar, component-book calculator, Underwriting, Case, and Workbench owners.

**Then:** deterministic fixtures reach the existing product flow with either strict profile;
Inverse native BTC/model/USD-valuation arithmetic conserves through a complete Case Outcome;
Linear policies, schema v3, arithmetic, and existing Case reads remain unchanged; and every mixed
product or Policy boundary fails closed.

**Valid zero/UNKNOWN:** no live Inverse market sample is required or permitted. Actual account
margin, live liquidity acceptance, opportunity frequency, Candidate conversion, and Policy edge
remain `UNKNOWN`; this satisfies the implementation closure but not any future validation claim.

**Cheapest falsification:** direct product/fee/payoff/component/Case tests plus the repository gate.

## Change declarations

**Market/Decision input contract change:** add an explicit product identity and Inverse BTC source,
index, instrument-unit, tick, model-normalization, and valuation-conversion contract; preserve the
Linear source contract.

**Decision Policy change:** add a separate content-identified Inverse Radar/Underwriting/Position
chain; do not modify accepted Linear Policy bytes or thresholds.

**Outcome/evaluation contract change:** preserve Linear Case schema v3; add product-aware schema v4
for future Inverse native BTC entry/close/fee/PnL plus declared USD valuation boundaries and
truthful account-margin `UNKNOWN`. Schema v4 and the new Inverse Policies must use explicitly
USD/valuation-named fields; a legacy `*_usdc` name may not carry an Inverse USD-equivalent value.

**Stage/authorization change:** close the stopped Linear natural-validation task and authorize
offline Inverse implementation only. No public or private live command is authorized.

## Scope

**In:** `options_domain`, `market_monitor`, `short_vol_radar`, `short_vol_underwriting`,
`radar_runtime`, three Inverse Policy files, the owning authority/contracts, README, and direct
tests.

**Out:** live venue calls; a second runtime/reducer/calculator/store; Linear Policy changes;
threshold tuning; credentials/private APIs; orders/fills/capital; actual margin; database/replay;
runtime management; qualification; or Policy promotion.

**Owning module:** `options_domain` owns product economics; existing higher modules consume its one
strict product contract.

## Validation

- focused tests: `pytest -q tests/test_inverse_product.py` plus affected compatibility suites;
- repository gate: `make check`;
- existing Case compatibility: official reader over the five terminal Linear v3 control Cases;
- public observation: `NOT_APPLICABLE` and forbidden;
- no manifest, receipt, commissioning, host inspection, or broad evidence package.

## Definition of done

The dual-product startup and trader-visible unit delta exists; the one product owner conserves all
declared arithmetic; mixed products fail closed; Linear policies, v3 semantics, and records remain
compatible; focused tests and `make check` pass; the diff is bounded; no runtime data is written;
and exact remote/Draft PR state is reported. Tests alone do not authorize live use.
