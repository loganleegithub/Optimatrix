# Task — Component-book Shadow lifecycle

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED — one bounded production-public read-only smoke of at most 600 seconds

**Base commit:** `5cbcfdd31174a63ffe6f39d23017f0d359ae8fea`

**Target branch/PR:** `codex/component-book-shadow-lifecycle` / Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** `STRUCTURE_REVIEWABLE → COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE`

**Baseline:** fixed 43,200-second observation produced `84 / 84` reviewable contract-level Radar
Episodes and `0 / 84` official atomic quotes; exact diagnostic blocker `NO_ACTIVE_COMBO 84`.

**Primary blocker:** the Shadow funnel incorrectly required an already-active official Combo.

**Expected user-visible delta:** a reviewable frozen protective vertical can become Underwriting-
evaluable, Candidate, Shadow Entry, and future Outcome from conservatively stressed public depth on
both option legs; Combo status remains visible only as a diagnostic.

**Durable-data effect:** no pre-Shadow writes. An admitted Case schema v2 stores one paired entry
witness with raw/stressed legs and fees; a known Outcome stores one paired close witness and
recomputable PnL.

**Complexity added:** one pure component-book quote calculator; paired two-request admission and
close attempts in the existing owner/adapter; schema-v2 Case validation.

**Complexity deleted:** official Combo as a Candidate, admission, close, and Outcome prerequisite;
single-Combo consumed-level semantics from the active Shadow path.

## Business closure

**Given:** one active Radar Episode with a frozen same-expiry, same-type protective long and current
full-quantity public books for both legs.

**When:** Underwriting prices both legs with one-tick adverse stress and both standard fees, and a
Candidate receives exactly two strictly later causally paired public book responses.

**Then:** the Candidate may open one durable Shadow Case without requiring an active Combo; a later
paired reverse-side snapshot can produce one known Shadow Outcome with recomputable PnL.

**Valid zero/UNKNOWN:** no natural Episode/Candidate during the smoke is valid. Missing metadata,
one missing/failed response, insufficient target depth, or unresolved currentness is truthful
`UNKNOWN` or known no-entry and creates no Case.

**Cheapest falsification:** pure component arithmetic tests, deterministic paired lifecycle tests,
`make check`, then the single bounded public-only smoke.

## Change declarations

**Market/Decision input contract change:** official public option books for both frozen legs replace
the official Combo book as the Shadow price input.

**Decision Policy change:** execution model becomes
`BOUNDED_COMPONENT_BOOK_TAKER_COUNTERFACTUAL`; Radar thresholds, universe, target quantity, economic
thresholds, and reserves remain unchanged.

**Outcome/evaluation contract change:** known Entry/Close economics consume two stressed legs and
two standard fees; schema-v2 Case/Outcome persists exact paired facts and non-claims.

**Stage/authorization change:** one bounded public-only smoke is authorized after offline gates; no
private execution or deployment authority.

## Scope

**In:** `options_domain` component quote, existing Radar review handoff, Underwriting/Position owner,
runtime adapter, funnel, Workbench, Case schema v2, Policy identity chain, Authority/contracts, and
direct tests.

**Out:** Radar tuning, benchmark or universe changes, private Combo/RFQ, orders/fills/account,
atomic-fill claims, database/replay, model expansion, deployment, and operations controls.

**Owning module:** `options_domain.component` owns leg arithmetic;
`short_vol_underwriting.owner` owns admission/Position transitions; `ShadowCaseStore` owns durable
validation.

## Validation

- focused tests: component domain, Radar review, Underwriting, Case store, runtime adapter, funnel,
  and Workbench tests;
- repository gate: `make check`;
- public observation: one production-public read-only smoke with `duration_seconds <= 600` after
  commit identity is frozen;
- no manifest, receipt, commissioning, or broad evidence package.

## Definition of done

The component stage is reachable without an active Combo; both-leg stress, fee, pairing, failure,
durability, and PnL invariants pass direct tests; Workbench/funnel expose the new meaning; the full
gate passes; the single bounded smoke terminates readably without tuning; no pre-Shadow durable
record or private capability is introduced; and the Draft PR reports exact limitations.
