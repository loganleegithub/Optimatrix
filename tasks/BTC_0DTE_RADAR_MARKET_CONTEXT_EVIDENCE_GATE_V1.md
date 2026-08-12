# Task — BTC 0DTE Radar MarketContext evidence gate

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Base commit:** `6a29668`

**Target branch/PR:** `codex/radar-risk-admission` / local bounded closure

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`

## Product movement

**Canonical unit:** `SessionDecisionUnit`

**Current funnel node:** `MARKET_CONTEXT_KNOWN`

**Baseline:** `1 / 1` applicable deterministic units with numeric values but missing required
method/coverage/known-at evidence incorrectly pass `MARKET_CONTEXT_KNOWN`

**Primary blocker:** `MARKET_CONTEXT_EVIDENCE_NOT_BOUND`

**Expected user-visible/funnel delta:** incomplete evidence becomes `Decision.UNKNOWN`, the funnel
shows `MARKET_CONTEXT_KNOWN = UNKNOWN`, later nodes are `NOT_REACHED`, and no structure/score/Case is
created; complete evidence remains evaluable

**Known-at/source boundary:** context evidence binds physical/implied method identities, risk-horizon
coverage, source/receive boundary, event-state source, and exact blockers to `MarketContext.now`

**Durable-data effect:** NONE; all evidence remains transient before `DECISION_OPENED`

**Legacy-data access effect:** NONE

**Complexity added:** one transient typed evidence member owned by `MarketContext` and one explicit
funnel `UNKNOWN` status

**Complexity deleted:** hard-coded `MARKET_CONTEXT_KNOWN = True`

## Business closure

**Given:** one applicable current-Session decision window with fixed Policy and numeric context.

**When:** the Radar evaluates its method, coverage and known-at evidence.

**Then:** complete evidence can reach risk evaluation; any missing/stale/contradictory required fact
stops the same unit at `MARKET_CONTEXT_KNOWN = UNKNOWN` without structure, score or Case.

**Valid zero/UNKNOWN:** one unknown unit consumes the stage denominator as UNKNOWN with numerator
zero; it is not Abstain, Review, Candidate or an opportunity-rate zero.

**Cheapest falsification:** one incomplete-evidence and one complete-evidence deterministic Radar
projection.

## Change declarations

**Market/Decision input contract change:** `MarketContext` must bind transient evidence

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE; no live command or durable write

## Scope

**In:** market context, Radar early gate, engine composition, canonical funnel, snapshot translator,
Workbench projection, contracts and focused tests

**Out:** thresholds, structure rank, combo route, lifecycle, persistence, runtime, AI

**Owning module:** `src/optimatrix/market.py` and `src/optimatrix/product_funnel.py` at their existing
boundary

## Validation

- focused tests: `pytest -q tests/test_radar.py tests/test_product_funnel.py tests/test_deribit_snapshot.py tests/test_workbench.py`;
- deterministic business scenario: direct unknown/known scenarios;
- repository gate: `make check`;
- public observation: NOT_APPLICABLE;
- legacy-root reference/access check: `rg` over `src tests`;
- no evidence database, registry, replay, or validator-of-validator.

## Definition of done

The false pass moves from `1 / 1` to `0 / 1`; complete evidence still passes; Workbench exposes
knowledge/blocker truth; no score or structure exists for UNKNOWN; zero durable writes occur; and the
task is removed after `CURRENT_STAGE` records the result. Green tests alone do not satisfy the task.
