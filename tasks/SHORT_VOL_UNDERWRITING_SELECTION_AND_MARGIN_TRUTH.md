# Task — Underwriting selection and margin truth

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN — the one authorized read-only probe completed and is exhausted

**Base commit:** `94b002130a31540bb5b16e30beb02d523c87ccbf`

**Target branch/PR:** `codex/underwriting-selection-margin-truth` / Draft PR to be created

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md), and
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md)

## Product movement

**Current funnel node:** conditional `UNDERWRITING_EVALUABLE → CANDIDATE`

**Baseline:** `0 / 7` Underwriting-evaluable natural Episodes became Candidates. The formal
whole-funnel primary blocker remains the earlier `RADAR_KNOWN` loss of `938 / 1,812,600` contract
evaluations; this task intentionally owns the Authority-selected downstream conditional closure.

**Primary blocker:** `CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE 7 / 7` on the previously frozen
review-first protective leg; the result for every other legal protective leg and every remaining
Candidate predicate was not exposed.

**Expected user-visible delta:** after complete positive option scope, Underwriting freezes the best
formally classified legal protective leg rather than the first Radar review row. For every
evaluable selection, Workbench shows the selector-rule identity, Candidate protective-leg count,
full ordered predicate-margin vector, all failed predicates, the exact selected leg, and the
upgrade condition, plus exact `count/min/p50/max` over the bounded current rows. Paired admission/close
refreshes also expose and enforce same-session,
same-continuity-epoch, source-timestamp-skew, and receive-skew truth.

**Durable-data effect:** `NONE`; all selection, margins, timing measurements, and Workbench rows
remain bounded current memory before `SHADOW_CASE_OPENED`.

**Complexity added:** one pure Underwriting-owned selector/margin calculation; two explicit shared
pair-skew Policy members; bounded pair timing fields on the existing witness; at most one
non-durable failed-admission terminal per still-active Radar Episode in Workbench.

**Complexity deleted:** composition's `references[0]` business selector and Workbench's generic
`FAILED_ECONOMIC_PREDICATE_VECTOR_NOT_PERSISTED` placeholder.

## Business closure

**Given:** an active Radar Episode with complete positive option scope and one or more legal,
target-size component-book protective legs at one settled causal boundary.

**When:** the sole component-book calculator evaluates every legal leg and the Underwriting owner
classifies and deterministically selects among them under the unchanged economic gates.

**Then:** any legal `CANDIDATE` leg outranks every `WATCH`/`ABSTAIN` leg; otherwise the selected leg
and complete signed margin vector make the exact remaining blocker and threshold distance visible.
Admission/close accepts a paired refresh only inside the frozen pair-timing contract.

**Valid zero/UNKNOWN:** zero Candidates remains valid when no legal leg passes all frozen economic
predicates. Incomplete catalog, missing input for a potentially legal leg, or a cross-session,
cross-continuity, or over-budget refresh pair is truthful `UNKNOWN`; a known inactive or
target-quantity-ineligible leg is excluded. Both zero and `UNKNOWN` satisfy this closure only when
the exact blocker is visible.

**Cheapest falsification:** pure selector/margin tests, deterministic runtime composition and pair
tests, Workbench projection tests, then the full repository gate.

## Change declarations

**Market/Decision input contract change:** the formal Underwriting selection input is every legal
same-expiry protective leg with a target-size component quote, not only Radar's display Top 3;
paired refresh witnesses add continuity epoch and exact source/receive skew facts.

**Decision Policy change:** add only `6000 ms` maximum component-pair source-timestamp skew and
`4000 ms` maximum receive skew. Each is the corresponding 30-sample observed maximum multiplied by
`1.25` and rounded up to the next whole second. Radar thresholds, target quantity, economic
reserves, minimum credit/ratio, loss cap, level cap, fee rate, and action ordering remain unchanged.

**Outcome/evaluation contract change:** `NONE`.

**Stage/authorization change:** the exact one-time public timing probe below is exhausted; no
further public probe, smoke, natural Shadow, private API, order, fill, deployment, or execution is
authorized.

## Scope

**In:** the active task and Authority/README truth; Underwriting policy/domain/owner/admission
selection and margin truth; runtime composition and bounded current Workbench projection; exact
policy identities; owning contracts and direct tests.

**Out:** Radar detector/benchmark/universe/threshold changes; economic or fee changes; Candidate
manufacture; no-trade control Cases; Outcome qualification; persistence changes; private execution;
runtime control plane; replay/database/new dependency.

**Owning module:** `short_vol_underwriting`; `radar_runtime` only composes owner calculations and
projects their typed truth.

## Validation

- focused tests: `.venv/bin/python -m pytest -q tests/test_short_vol_underwriting.py tests/test_fixed_contract_shadow.py tests/test_trader_workbench.py tests/test_policy_and_math.py`;
- repository gate: `make check`;
- public observation: completed exactly once,
  `python3 /private/tmp/optimatrix-component-pair-timing-probe.py --samples 30 --interval-ms 1000`;
- observed source-timestamp skew: `count=30, min=72, p50=805, p95=2180, max=4763 ms`;
- observed local receive skew: `count=30, min=1, p50=149, p95=3098, max=3150 ms`;
- observed maximum request round trip: `count=30, min=697, p50=854, p95=3899, max=3930 ms`;
- the probe called only Deribit public HTTPS JSON-RPC methods, printed aggregate timing to the
  terminal, wrote no repository/product file, and completed within 120 seconds;
- no manifest, receipt, commissioning, or broad evidence package.

## Definition of done

The declared selection and explanation delta exists; incomplete/unknown/known-illegal legs conserve
their distinct semantics; pair integrity is explicit, fail-closed, and production-visible; focused
tests and `make check` pass; all economic thresholds are byte-for-byte unchanged; the diff adds no
pre-Shadow durable record or dependency; the one live probe is exhausted; complexity and remaining
blocker are reported; and the Draft PR remote state is exact.
