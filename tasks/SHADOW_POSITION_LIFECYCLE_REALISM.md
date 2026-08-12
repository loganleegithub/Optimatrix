# Task — Shadow Position lifecycle evidence closure

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED — one isolated full-business-chain simulation; stable cutover forbidden

**Base commit:** `d0b5a4b6597077500c6fe4be69a73d5e2e765ea9`

**Target branch/PR:** `codex/shadow-position-lifecycle-realism` / Draft PR `#51`

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md),
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `SHADOW_CASE_OPENED -> SHADOW_CASE_OUTCOME`

**Baseline:** 87 durable schema-v5 Cases, 65 immutable first-CLOSE records, 20 naturally produced
contract-v2 admitted `EXITED_KNOWN` Outcomes, zero natural `SETTLED_KNOWN`, and 43 current
non-terminal Positions at the repair boundary.

**Primary blocker:** 20/20 version-2 market exits have known aggregate economics but lack complete
durable pair timing/source evidence for independent reconstruction; 0 settlement Outcomes have
passed natural business acceptance, while the settlement reader does not yet recompute contractual
payoff/fee truth. Whole-lifecycle online Booleans also prevent the offline evaluator from answering
the narrower exit-acquisition question.

**Expected user-visible delta:** A future terminal Case states exactly which observed two-leg sample
or official delivery member ended responsibility, and the one official reader can reject a
causally or economically coherent-looking forgery. The offline report separately states terminal
economics, whole-path continuity, terminal sample integrity, and first-CLOSE-to-terminal window
quality without an online global eligibility verdict. The read-only Workbench presents only formal
Shadow Entries as a trader-facing expiry risk book, preserving current exit/settlement duty and
keeping full lifecycle/Cohort evidence behind disclosure.

**Durable-data effect:** No new record kind and no rewrite. Future intent-only first-CLOSE records
may bind one finite acquisition profile. Future `SHADOW_CASE_OUTCOME` records use contract version
3 and add only the accepted terminal pair timing/source evidence or official delivery
response/member evidence directly consumed by the AI researcher and offline evaluator. Existing
v1/v2 bytes remain readable and keep their legacy evidence level.

**Complexity added:** One typed exit-acquisition profile, one response-level delivery witness, and
one version-3 branch in the existing Case writer/reader.

**Complexity deleted:** Online Outcome Cohort Booleans, the report's version-2 terminal Segment
special case, request-owner delivery-date gating, and use of a network deadline as a sampling
cadence.

## Business closure

**Given:** One Position-bearing Case has a frozen Entry and optionally an immutable first CLOSE,
including legacy Cases recovered across truthful gaps.

**When:** It observes failed, incomplete, mismatched, or eligible paired close responses; crosses a
process boundary; or reaches expiry and receives complete, partial, empty, late, or malformed
official delivery history.

**Then:** First CLOSE remains immutable; one serial acquisition profile chooses only the first
eligible observed pair; valid response members settle every matching expiry independently of the
request owner; temporary absence remains pending; and every known terminal Outcome is independently
recomputable from its durable bounded evidence.

**Valid zero/UNKNOWN:** No eligible pair remains `EXIT_ACQUIRING`; a missing official member remains
`SETTLEMENT_PENDING`; legacy-minimal evidence remains valid terminal economics but is excluded from
strict terminal-sample and acquisition-window Cohorts. These states do not satisfy strict evidence
closure.

**Cheapest falsification:** Direct reader-tamper tests and deterministic A→B→C owner/runtime
fixtures over an isolated Case root, followed by one isolated simulation over a consistent copy of
the stable repository.

## Change declarations

**Market/Decision input contract change:** One delivery response witness owns zero or more validated
date/price members; accepted component-close facts retain their existing complete pair witness.

**Decision Policy change:** NONE. Current nine Position predicates and thresholds remain frozen.

**Outcome/evaluation contract change:** Add Outcome contract version 3, full terminal source
reconstruction, offline acquisition-window derivation, and legacy evidence-level classification.

**Stage/authorization change:** Authorize one isolated simulation; stable runtime cutover remains
forbidden until a later explicit authority update.

## Scope

**In:** `short_vol_underwriting` close/settlement/Outcome/Case reader, delivery composition,
offline Case report, the read-only Workbench Shadow expiry-risk projection, owning
contracts/authority, and direct/integration/simulation/browser tests.

**Out:** opened-record schema migration; Entry-window redesign; successor Position thresholds;
official Combo execution;
per-attempt/per-tick persistence; replay; database; supervisor; orders/fills/accounts/capital; and
automatic Policy qualification.

**Owning module:** `short_vol_underwriting`, composed by `radar_runtime`.

## Validation

- focused tests: Position/Outcome, Case store, delivery composition, offline report, and deterministic
  full-chain business scenarios, plus exact-identity Workbench lifecycle projection;
- repository gate: `make check`;
- public observation: one isolated modified-runtime simulation over a consistent stable-root copy;
- browser QA: isolated current-fact preview at matching desktop and responsive viewports, recorded in
  `design-qa.md` without changing the stable runtime;
- no stable runtime restart/cutover, manifest, receipt, commissioning controller, replay, or broad
  evidence package.

## Definition of done

The official reader accepts every existing Case unchanged, rejects coherent terminal-evidence
tampering, version-3 market exits and settlements recompute exactly, partial delivery fanout cannot
starve another expiry, Cohorts are offline and window-specific, every declared business scenario
passes on the modified runtime, `make check` passes without overwriting concurrent Web work, and the
isolated simulation preserves the original Case bytes. The trader Workbench must exclude Controls,
retain exit/settlement responsibility across Gap, and never render unknown economics as zero or a
terminal claim. Tests alone do not satisfy the task.
