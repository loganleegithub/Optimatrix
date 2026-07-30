# Task — Freeze Short Vol Underwriting, Shadow admission, and Position contract

**Status:** ACTIVE AUTHORITY

**Task kind:** `AUTHORITY_ONLY`

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):** `NOT_APPLICABLE AT ACTIVATION` — this authority-only closure
creates `docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md`. The established upstream contract
remains [`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md).

**Base commit:** `0529c9c9e380b8b62382fddda10b38f2571350e9`

**Target branch/PR:** `codex/short-vol-underwriting-shadow-position-contract`; no PR exists at
activation

## Business closure

**Given:** `PRODUCTION_PUBLIC_SHORT_VOL_RADAR` is independently established and can distinguish
an active short-leg anomaly from official target-size atomic-quote availability, but no
Underwriting, Shadow-admission, or Position implementation contract exists.

**When:** one authority-only closure freezes a complete public-Shadow contract for Underwriting,
Candidate validity, deterministic Shadow admission, Position action, atomic entry/close
economics, and strictly future Shadow close-opportunity semantics.

**Then:** one active implementation contract exists with no unresolved economic or causal choice,
so a later implementation task can be falsified without inventing authority in code. The current
runtime still emits no Candidate, Shadow Entry, Position action, close opportunity, or Outcome.

**Independent verification:** a read-only reviewer checks the exact authority diff and contract
truth tables, followed by the focused authority tests and `make check`.

**Valid zero/no-hit/UNKNOWN result:** this task runs no market process. Zero Candidates, Entries,
Position actions, close opportunities, and Outcomes are the only valid runtime result. In the
future contract, no evaluable opportunity produces no Underwriting action; missing required facts
produce `UNKNOWN` availability with no economic action; a zero or unknown denominator produces a
`null` rate, never zero.

**Upstream prerequisite:** the accepted `PRODUCTION_PUBLIC_SHORT_VOL_RADAR` record at runtime
commit `9c58120d358fd0e0ccb4885123ab95c67d1c3f31`. It is established. A complete Position Policy is
the smallest semantic prerequisite for Candidate; therefore Underwriting-only implementation is
not independently reachable.

## Change declarations

**Market/Decision input contract change:** `APPROVED` —
`SHORT_VOL_UNDERWRITING_SHADOW_POSITION_INPUT_CONTRACT` freezes only production-public known-at
facts, currentness, completeness, units, quote direction, target quantity, consumed levels, fee
source/assumption, maximum-loss inputs, and invalidation boundaries consumed after Radar. It does
not change Deribit sources, the option universe, Radar inputs, detector truth, or atomic
classification.

**Decision Policy change:** `APPROVED` —
`SHORT_VOL_UNDERWRITING_SHADOW_POSITION_POLICY_CONTRACT` freezes separate immutable
Underwriting and Position Policy identities, `CANDIDATE | WATCH | ABSTAIN`, Candidate validity,
the Shadow-admission gate, `HOLD | CLOSE | UNKNOWN`, and hard-close priority. It does not change
the Radar Policy, formula, scope, thresholds, persistence, or structure family.

**Outcome/evaluation contract change:** `APPROVED` —
`SHORT_VOL_SHADOW_CLOSE_OPPORTUNITY_CONTRACT` freezes only the `SHADOW_ENTRY` strictly-future
boundary, Position-action/quote-state separation, full-remaining-quantity
`SHADOW_CLOSE_OPPORTUNITY` eligibility, no-entry/no-Outcome semantics, and public-quote-not-fill
meaning. It does not authorize or define a Shadow Outcome cohort, PnL, scoring, comparator,
`NO_TRADE` cohort, or qualification.

**Stage/authorization change:** `APPROVED` —
`SHORT_VOL_UNDERWRITING_SHADOW_POSITION_CONTRACT` becomes the sole active product-capability
closure, restricted to authority and contract work. `PUBLIC_SHADOW`,
`PRODUCTION_PUBLIC_SHORT_VOL_RADAR`, Radar `ESTABLISHED`, and every runtime, private, account,
capital, order, fill, promotion, and execution permission remain unchanged.

## Product operating behavior

The current Online Runtime is unchanged for this task. It continues only the established Radar
flow and does not consume the new downstream boundary.

The contract created by this task must freeze the future continuous lifecycle without
implementing it:

1. a current active anomaly and current official target-size atomic quote can make one
   Underwriting opportunity;
2. complete known facts plus immutable Underwriting and Position Policy identities can produce
   one economic action; unavailable Underwriting produces no action, not `ABSTAIN`;
3. only a still-valid Candidate plus a post-Candidate `FactBoundary` that newly proves the same
   official full-quantity atomic quote current and complete can admit `SHADOW_ENTRY`; unchanged
   economics may remain usable, but a pre-Candidate quote projection cannot be reused;
4. after admission, a complete Position Policy continuously returns `HOLD | CLOSE | UNKNOWN`
   without a preselected holding duration;
5. a known hard-close condition keeps action `CLOSE` even when close-quote state is
   `UNKNOWN | UNEXECUTABLE`;
6. only a strictly later official atomic quote covering the full remaining Shadow quantity while
   action is `CLOSE` creates `SHADOW_CLOSE_OPPORTUNITY`.

The contract must separately freeze transient current facts, durable future object identities,
and invalidation rules. It may not make a bounded capture, replay, saved-data scan, report, or
fixed duration part of product behavior.

## Validation harness

The harness is authority-only. It checks exact links, single-active-task state, change
declarations, required contract sections, truth tables, denominator/null behavior, forbidden
runtime scope, and the absence of unresolved `TBD`/placeholder choices. No market event, evidence
directory, replay, or synthetic Candidate is required to freeze a contract.

## Evidence boundary

**Proves:** one complete, internally consistent, implementation-ready public-Shadow
Underwriting/admission/Position contract is frozen under the existing product authority.

**Does not prove:** runtime reachability, Candidate quality, forecast skill, edge, admission,
closeability, Shadow Outcome, PnL, maker feasibility, account fees, margin, a fill, qualification,
promotion, or execution permission.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED — authority, link, contract-truth-table, and scope tests only |
| Production-public Radar | NOT_APPLICABLE |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** create `docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md`; freeze the exact future
Underwriting, Candidate-validity, Shadow-admission, Position, close-quote, and close-opportunity
contract; update only the owning architecture/stage/README assertions and direct authority tests.

**Out:** runtime packages, CLI, writers/readers, Policy implementation, Radar behavior or schema,
live commands, evidence capture, replay, fixed-horizon behavior, forward cohort, Shadow Outcome,
Challenger, qualification, promotion, deployment, private/account APIs, maker orders, orders,
fills, margin, capital, and money.

**Owning module/artifact:** `docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md`. No runtime module
is authorized. The complete allowed task scope is:

- `docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md`;
- `docs/authority/SYSTEM_ARCHITECTURE.md`;
- `docs/authority/CURRENT_STAGE.md`;
- `README.md`;
- this active task;
- `tests/test_authority_and_architecture.py`.

## Contract

**Inputs and known-at rule:** the contract must enumerate each required fact's public source,
unit, causal boundary, currentness, completeness, nullability, validation, and invalidation. A
historical anomaly or atomic event proves its frozen boundary only; it does not prove current
Candidate or admission state. Component legs, mark, mid, imagined maker prices, sealed evidence,
and run summaries cannot substitute for current atomic economics.

**Durable output and identity:** this authority-only task persists only the new contract. That
contract must freeze the future identities and causal bindings of Underwriting action, Candidate,
Shadow Entry, Position action, close-quote state, and Shadow close opportunity without creating
their runtime writers.

**Missing/invalid/UNKNOWN semantics:** Underwriting availability and economic action are separate.
When there is no active/current opportunity, availability is `NOT_EVALUATED` and economic action
is absent. Missing, stale, incomplete, or contaminated required facts are `UNKNOWN` with no
action. Only complete evaluable economics may yield `CANDIDATE | WATCH | ABSTAIN`. Entry or
close-quote unavailability never becomes a fill failure, and a known hard-close action is not
erased by missing quote evidence.

**Persisted meaning and compatibility:** the new contract is a new downstream semantic boundary.
Existing Radar events, summaries, current writer/readers, and sealed readers remain `COMPATIBLE`
and unchanged as upstream evidence; no migration, replay, recomputation, or relabeling is
authorized.

**Business denominators:** the contract must separately define Underwriting-evaluable
opportunities, actions by type, Candidates, admission evaluations, Shadow Entries, Position
actions, close-quote states, and close opportunities. It must name numerator, denominator, unit,
scope, conditioning event, and `null` behavior. `UNKNOWN` is excluded from economic action
denominators; a zero or unknown denominator never serializes as rate zero.

## Acceptance

### Direct behavior

1. The new contract has no `TBD`, placeholder, or deferred economic choice and freezes separate
   content-identified Underwriting and Position Policies. Candidate binds both identities plus
   Radar Policy, episode, combo/legs/quantity, consumed facts, and its causal boundary.
2. Underwriting unavailable produces no action; `UNKNOWN`, no action, `WATCH`, and `ABSTAIN` are
   distinct. A numeric zero-Candidate claim requires a nonzero complete evaluable denominator.
3. Shadow admission requires a still-valid Candidate and a later `FactBoundary` that re-proves
   the exact official full-quantity quote current and complete. The contract explicitly decides
   whether admission has independent configurable Policy fields rather than adding a Policy for
   symmetry.
4. The contract freezes Candidate invalidation, fee and taker/maker assumptions without defaulting
   fee to zero, exact gross/net entry and close economics, maximum loss, remaining quantity, and
   hard-close total ordering.
5. Known hard close has priority over missing soft-risk facts and missing/unexecutable close
   quotes. Position action and close-quote state remain separate; component-leg references remain
   diagnostic only.
6. No fixed holding period, runtime package, CLI, writer, schema implementation, live command,
   replay, cohort, Outcome, or execution authority is introduced.

### Required commands

- `make UV='python3 -m uv' sync`
- focused tests: `.venv/bin/python -m pytest tests/test_authority_and_architecture.py`
- `make check`
- production-public command: `NOT_APPLICABLE — FORBIDDEN`
- independent recomputation or reconstruction command: `NOT_APPLICABLE`

### Real evidence

**Required:** NO

**Environment and stopping condition:** `NOT_APPLICABLE — authority-only contract freeze`

**Required report:** exact files, contract decisions, unresolved findings, tests, non-claims,
base/head, worktree, and remote state.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** `NOT_APPLICABLE` for external artifacts; Git owns the contract
bytes and history.

**Policy/contract identities:** the accepted contract must record its exact semantic Policy and
object identities without ordinal names or implementation defaults.

**Commit/PR:** recorded by Git and the final delivery report; a commit does not contain its own
future hash.

**Unknowns and non-claims:** contract completion with zero market activity is valid. It does not
establish any downstream runtime or business result.

## Definition of done

The exact contract exists and contains no unresolved choice; all four declarations match
authority; every required public fact, Policy identity, action, causal boundary, invalidation,
atomic economic, fee, maximum-loss, hard-close, denominator, zero, and `UNKNOWN` rule is frozen;
focused authority tests and `make check` pass; only the allowed files changed; and no runtime or
live action occurred. Acceptance removes the completed task, returns the sole next closure to
`NONE`, and does not automatically authorize implementation. Git and safety remain governed by
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md#git-and-pr-contract).
