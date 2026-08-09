# Task — Inverse-Only Repository Cleanup

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Base commit:** `270920fb1fcb255c648e95361f31c1e5075ec294`

**Target branch/PR:** `codex/inverse-only-repository-cleanup`; PR `NOT_OPENED`

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

**Current funnel node:** `APPLICABLE_MARKET_SCOPE`

**Baseline:** at the base commit, `0 / 1` canonical default `serve-shadow` startup routes are
Inverse-safe: omitting the optional product selector resolves the obsolete default rather than
`INVERSE_BTC_V1`. The already-running 8765 process is correctly Inverse only because its old
checkout was launched explicitly; that does not make the repository default safe for a future
restart.

**Primary blocker:** `LINEAR_DEFAULT_RESTART_MISROUTE`, affecting the single canonical default
startup route and every future restart that relies on it.

**Expected user-visible delta:** the repository exposes one product and one startup behavior. A
later separately authorized ordinary `serve-shadow --state-root <root>` launch can resolve only
`INVERSE_BTC_V1`, its `btc_usd` sources, BTC-native economics, explicit USD valuation, schema-v4
Case family, and exact matching three-Policy chain. No obsolete product choice appears in CLI,
Workbench, Authority, or contracts.

**Durable-data effect:** `NONE`. Repository-external state roots and their Shadow Cases are not
opened, migrated, rewritten, copied, or deleted. The accepted Inverse Case records and
process-independent Entry semantics do not change.

**Complexity added:** `NONE`

**Complexity deleted:** the optional product CLI/configuration branch, obsolete product constants
and Policy artifacts, alternate source/index/unit routes, legacy online Case-schema compatibility,
dual-product documentation, and their tests.

## Business closure

**Given:** the accepted Online Runtime product is `INVERSE_BTC_V1`, its three Policy artifacts are
fixed, and the existing 8765 process continues on its pre-cleanup code identity.

**When:** the repository removes every alternate online product/schema route and makes the Inverse
product and Policy chain structural defaults rather than caller-selected options.

**Then:** `1 / 1` canonical default startup routes are Inverse-safe, unsupported product/schema
input fails, and the trader-facing repository has one coherent product identity and unit model.

**Valid zero/UNKNOWN:** zero live commands, zero durable writes, and zero new funnel observations
are required and satisfy this repository closure. They do not claim a deployed restart, current
market health, account margin, opportunity frequency, edge, profitability, or qualification.

**Cheapest falsification:** direct repository tests prove the CLI/configuration, source universe,
Case reader, Policy inventory/hashes, Authority, contracts, and Workbench expose only the fixed
Inverse product; `make check` proves the bounded repository remains coherent.

## Exact source / known-at boundary

- the base-commit parser is the source for the measured `0 / 1` unsafe default route;
- exact product and Policy identities come only from their registered content-identified artifacts;
- the 8765 code/runtime identities come only from one read-only Workbench snapshot and remain an
  operational observation of the old checkout;
- repository checks establish source behavior only, not the identity or health of a later process;
- no state-root content is inspected to complete this task.

## Change declarations

**Market/Decision input contract change:** remove selectable product routing; the public universe is
fixed to active Inverse BTC options and `btc_usd`.

**Decision Policy change:** `NONE`; the Radar, Underwriting, and Position Policy bytes, values, and
identities remain exact.

**Outcome/evaluation contract change:** remove online alternate-schema compatibility; accepted
Inverse schema-v4 economics, recovery, Position, and Outcome evaluation remain unchanged.

**Stage/authorization change:** make `INVERSE_BTC_V1` the sole repository product and forbid every
live command during cleanup. This does not authorize deployment or restart.

## Scope

**In:** product identity/configuration and public-source routing, runtime composition and CLI,
Case-reader product/schema acceptance, obsolete Policy artifact deletion, Authority, contracts,
README/Workbench documentation, active task replacement, and direct tests.

**Out:** any change to Inverse Policy values/hashes, public decision formulas, Case economics,
external state roots, current 8765 process, private/account/order/fill/capital capability,
deployment, process supervision, host inspection, commissioning, manifest, or receipt chain.

**Owning module:** `options_domain` owns the sole product specification; `radar_runtime` owns fixed
startup composition; `market_monitor` owns its Inverse public source boundary;
`short_vol_underwriting` owns exact Inverse Case acceptance.

## Validation

- focused tests: `.venv/bin/python -m pytest tests/test_authority_and_architecture.py tests/test_inverse_product.py tests/test_persistent_service.py tests/test_runtime_reducer.py tests/test_trader_workbench.py`;
- repository gate: `make check`;
- Policy integrity: SHA-256 of the three Inverse Policy files equals the frozen identities;
- public observation: `NOT_APPLICABLE`;
- no manifest, receipt, commissioning, restart, smoke, probe, or broad evidence package.

## Definition of done

The repository has one fixed `INVERSE_BTC_V1` online path, `1 / 1` default startup routes are
Inverse-safe, obsolete online product/schema support and its net complexity are deleted, the three
Inverse Policy artifacts are byte-exact, focused checks and `make check` pass, no pre-Shadow durable
record is introduced, and remote state is reported accurately. The old 8765 process and every
external state root remain untouched. Tests alone do not authorize a restart or satisfy any future
deployment/market claim.
