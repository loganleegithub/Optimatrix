# Task — Selected Underwriting Decision Outcome

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Base commit:** `2b23de06ef9e7b0e208967c234e00c6097735c3c`

**Target branch/PR:** `codex/selected-underwriting-decision-outcome`; stacked Draft PR against
`codex/underwriting-selection-margin-truth`

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** research branch after `UNDERWRITING_EVALUABLE`, kept separate from the
canonical `CANDIDATE → SHADOW_CASE_OPENED` conversion

**Baseline:** the completed natural run produced `7` Underwriting-evaluable Episodes, `0`
Candidates, `0` Shadow Cases, and `0` Outcomes. Those seven structures predate the accepted formal
all-leg selector and therefore justify the selective-label closure but do not calibrate its sampling
or economic thresholds.

**Primary blocker:** `SELECTIVE_LABELS_NO_NON_CANDIDATE_FUTURE_OUTCOME`: when the Policy rejects
every evaluable structure, the product cannot learn whether a rejection avoided loss or missed a
strictly future opportunity.

**Expected user-visible delta:** Workbench separately shows the one bounded selected-decision
control for a temporal activation batch, its original and refreshed Underwriting action/margins,
exact enrollment state, and strictly future Outcome without counting it as a Candidate, admitted
trade, order, fill, or canonical funnel conversion.

**Durable-data effect:** a fully evaluable decision selected before its future is known may open one
`SHADOW_CASE_OPENED` with `enrollment_kind=SELECTED_UNDERWRITING_DECISION_CONTROL`, followed by the
existing bounded first-CLOSE and Outcome records. The direct consumers are trader/AI Case review
and later offline rejection-quality research. This open-time selection and paired entry witness
cannot be reconstructed after restart from current memory. Unselected Episode, WATCH, ABSTAIN,
UNKNOWN, Workbench, and batch state remain non-durable.

**Complexity added:** one bounded in-memory causal activation-batch selector derived from the
already-frozen Radar activation sequence; one paired control-enrollment attempt; one explicit Case
enrollment variant; one separate Workbench/funnel research projection.

**Complexity deleted:** the selective-label dead end in which only current-Policy Candidates can
ever receive a future label.

## Business closure

**Given:** one or more formally selected component-book Verticals whose Radar Episodes were newly
activated in the same settled reducer transaction and therefore share one frozen activation causal
sequence, with no decision already selected for that batch.

**When:** the action-blind designated Episode reaches its first fully evaluable decision before
future facts, receives exactly two strictly later paired public component-book refreshes, and remains
Underwriting-evaluable as `CANDIDATE`, `WATCH`, or `ABSTAIN` at that refreshed boundary.

**Then:** at most one selected-decision Case opens for that batch, freezes the selection rule,
original and refreshed complete predicate-margin vectors, pair timing/economics, and follows the
same strictly future Position/paired-close/Outcome model. A decision selected as Candidate and still
Candidate at refresh reuses its ordinary admitted `SHADOW_ENTRY` Case; every other evaluable
selected decision uses the discriminated no-trade control enrollment and remains semantically and
metrically separate from Candidate admission.

**Valid zero/UNKNOWN:** no fully evaluable decision, an ambiguous batch input, failed/missing/skewed
pair, or refreshed Underwriting `UNKNOWN` opens no Case and remains an exact current blocker. A
clean stop after control opening writes `CENSORED_AT_STOP`; required future quote absence yields the
existing honest `UNKNOWN` Outcome semantics. Natural occurrence is not required for this offline
implementation closure.

**Cheapest falsification:** deterministic owner/adapter/store tests construct two evaluable Episodes
in one batch, an `UNKNOWN`, an ABSTAIN paired refresh, and a strictly future close; they must prove
one selection, zero Candidate/`SHADOW_ENTRY`, one control Case, and one conserved Outcome.
Candidate-owned refresh terminals that retire with their Candidate must remain exactly visible from
the resulting current enrollment rather than from retained history.

## Change declarations

**Market/Decision input contract change:** carry the already-owned Episode activation causal
sequence into Underwriting composition solely to freeze membership in the reducer transaction that
created the Episodes; entry and exit still require the accepted paired component-book witness.

**Decision Policy change:** no economic threshold, target quantity, fee, Radar screen, or protective
leg selection change. A batch is every Episode newly activated in one reducer transaction and is
identified by its shared Radar activation causal sequence. Before action or margin is known, the
unique designated Episode is the minimum canonical hash of batch identity, Episode identity, and
the frozen Underwriting/Position Policy identities. Only that Episode's first fully evaluable
decision may be enrolled; `UNKNOWN` has no fallback to another member. Maximum one selected unit
per batch.

**Outcome/evaluation contract change:** authorize a selected Underwriting decision to reuse the
exact Position and paired component-book Outcome calculator after its Case-open boundary. Candidate
selection reuses ordinary admission rather than scheduling a duplicate refresh; all evaluable
selections that do not produce an admitted Candidate use the control-open variant. The descriptive
result does not establish causal effect, profitability, or Policy qualification.

**Stage/authorization change:** authorize Task B implementation and deterministic offline tests only;
no public probe, smoke, natural run, deployment, private API, order, or capital action.

## Scope

**In:** current owner/adapter typed state, bounded research counters, Workbench projection, Shadow
Case schema/open validation, owning contracts/Authority, and direct tests.

**Out:** economic threshold changes; automatic persistence of every rejection; random or
outcome-conditioned sampling; online Cohorts/aligned pairs; full-feed history; database/replay;
qualification/promotion; public live commands; private execution.

**Owning module:** `packages/short_vol_underwriting`

## Validation

- focused tests: `.venv/bin/python -m pytest -q tests/test_short_vol_underwriting.py tests/test_shadow_case_store.py tests/test_fixed_contract_shadow.py tests/test_funnel.py tests/test_trader_workbench.py tests/test_authority_and_architecture.py`;
- repository gate: `make check`;
- public observation: `NOT_APPLICABLE`;
- no manifest, receipt, commissioning, broad evidence package, or natural-event requirement.

## Definition of done

The deterministic selector admits at most one control per activation batch; `UNKNOWN` and failed
paired refreshes write no Case; a refreshed WATCH/ABSTAIN opens no Candidate and no `SHADOW_ENTRY`
but can open one explicitly tagged Case; all Case economics and future boundaries conserve; the
canonical Candidate funnel is unchanged; focused tests and `make check` pass; no economic Policy
number changes; the diff adds no online Cohort/history subsystem; and the stacked Draft PR remote
state and dependency are reported exactly.
