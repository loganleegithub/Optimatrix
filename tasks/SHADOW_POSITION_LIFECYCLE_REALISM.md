# Task — Shadow Position lifecycle realism

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED — one isolated full-chain runtime simulation, one stable-runtime
cutover, and bounded monitoring until the first naturally produced admitted Outcome

**Base commit:** `d0b5a4b6597077500c6fe4be69a73d5e2e765ea9`

**Target branch/PR:** `codex/shadow-position-lifecycle-realism` / Draft PR to be created

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md),
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `SHADOW_CASE_OPENED -> SHADOW_CASE_OUTCOME`

**Baseline:** 0 admitted Outcome files from 40 active admitted Entry aggregates; all 40 latest
Segments are `OPEN/GAPPED`. The same repository contains 12 Radar-score Controls and 10 selected
Underwriting Controls that are not recovered.

**Primary blocker:** 40/40 active admitted Entries have no terminal Outcome. The Position lifecycle
couples immutable first-CLOSE history, one public quote-acquisition attempt, and terminal Outcome;
one failed/lost attempt consumes future exit responsibility, while expiry has no official delivery-
price settlement path.

**Expected user-visible delta:** A first CLOSE remains immutable while the Workbench truthfully shows
ongoing exit acquisition across failed pairs and process recovery. At expiry an open Case moves to
official settlement acquisition and produces `SETTLED_KNOWN` when delivery economics are known.
Future selected Controls use the same process-independent Position terminal path. Gap quality no
longer acts as a global qualification verdict.

**Durable-data effect:** No new record kind and no pre-Shadow write. Existing opened/Segment/first-
CLOSE bytes remain immutable. Later public quote attempts remain in memory. Existing Segment facts
continue to preserve gap truth. `SHADOW_CASE_OUTCOME` gains one discriminated market-exit versus
contract-settlement terminal union and the official delivery-price source/economics directly
consumed by the trader, AI researcher, and offline terminal-economics Cohort; those future facts
cannot be derived from opened or first-CLOSE records. Future opened Control Cases gain ordinary
Observation Segments because process boundaries cannot be derived offline.

**Complexity added:** One typed official `public/get_delivery_prices` source route and validator;
one serial bounded exit-acquisition loop per open Case; one product-owned settlement calculator;
one terminal Outcome union; recovery of future position-bearing Controls. No dependency.

**Complexity deleted:** Lifetime single-attempt consumption, `MATURE_UNKNOWN` caused solely by no
eligible close quote at expiry, Control process-stop terminalization, and use of one online global
qualification Boolean as all-Cohort eligibility.

## Business closure

**Given:** One admitted or selected-Control Case has frozen entry economics and remains without an
Outcome after first CLOSE, failed quote acquisition, process loss, or arrival at expiry.

**When:** Fresh public component-book pairs or the official delivery-price fact arrive in the same
or a later truthful Observation Segment.

**Then:** The Case retains its first exit intent, repeatedly acquires at most one pair at a time,
selects the first causally eligible full-quantity pair as `EXITED_KNOWN`, or uses official expiry
economics as `SETTLED_KNOWN`; temporary missingness and Gap never consume that responsibility.

**Valid zero/UNKNOWN:** A temporarily unavailable close pair or delivery-price response remains
`EXIT_REQUIRED`, `EXIT_ACQUIRING`, or `SETTLEMENT_PENDING`. `TERMINAL_UNKNOWN` is allowed only after
the predeclared settlement-finality condition is known false; it does not satisfy the known-
economics closure.

**Cheapest falsification:** Deterministic owner/runtime A→B→C fixtures over one isolated Case root,
including every predicate class, pair failures/races, restart, Control recovery, settlement and
offline Cohort projections, followed by one modified-runtime isolated smoke and one authorized
stable-runtime cutover.

## Change declarations

**Market/Decision input contract change:** Add one validated Deribit public delivery-price fact for
the fixed `btc_usd` expiry date. No private or account input.

**Decision Policy change:** Current frozen Position threshold identities remain unchanged for the
active legacy book. Expiry and quote availability become lifecycle/execution state rather than a
claim that the Position ended. New threshold semantics remain a later Policy cutover after the
legacy book drains.

**Outcome/evaluation contract change:** Replace close-only `MATURE_KNOWN | MATURE_UNKNOWN` with a
versioned terminal union that distinguishes market exit, official contract settlement, and true
terminal unknown; offline Cohorts derive named eligibility from persisted facts.

**Stage/authorization change:** Permission remains `PUBLIC_SHADOW`. This task authorizes its exact
isolated simulation, one stable-runtime cutover, and bounded read-only monitoring until the first
naturally produced admitted Outcome. It grants no order, fill, capital, Policy qualification, or
private execution authority.

## Scope

**In:** Position/Outcome domain and owner, Inverse product settlement arithmetic, typed public
delivery-price transport, Case writer/reader compatibility, future Control recovery, Workbench and
offline Case projection, owning Authority/contracts, and direct/integration/runtime tests.

**Out:** Entry-window redesign, Policy threshold tuning, official Combo execution, per-attempt or
per-tick persistence, replay, database, supervisor, migration/rewrite of existing Case bytes,
orders/fills/accounts/capital, and automatic Policy qualification.

**Owning module:** `short_vol_underwriting` Position/Outcome owner, composed by `radar_runtime`.

## Validation

- focused tests: direct Position/Outcome, Case store, runtime composition, Workbench, offline report,
  and deterministic full-business-chain scenarios;
- repository gate: `make check`;
- public observation: one isolated modified-runtime simulation, then stable runtime GET/HEAD/API,
  exact active-Case recovery, single-writer, and natural-Outcome observation;
- no manifest, receipt, commissioning controller, replay, or broad evidence package.

## Definition of done

The modified runtime preserves all existing active Case bytes, repeatedly carries exit duty across
failed pairs and restart, settles expiry from the official public fact, restores future Controls,
projects named Cohort eligibility without online qualification authority, passes the full business
scenario matrix and repository gate, runs as the sole stable runtime, and produces and validates at
least one naturally occurring admitted Outcome. Tests alone do not satisfy the task.
