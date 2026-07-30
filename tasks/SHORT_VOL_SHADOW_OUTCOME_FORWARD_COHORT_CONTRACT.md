# Task — Freeze Shadow Outcome and Forward Cohort Contract

**Status:** ACTIVE

**Task kind:** `AUTHORITY_ONLY`

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md) /
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) /
planned `docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md`

**Base commit:** `e4b4aad917c6ecf67b788ef80346837e8d668006`

**Target branch/PR:** `codex/short-vol-shadow-outcome-forward-cohort-contract` / one Draft PR

## Terminal business-goal delegation

The user's 2026-07-30 terminal goal authorizes the controller to complete, without repeated
technical approvals, the bounded sequence:

1. freeze and accept this missing Outcome/cohort prerequisite;
2. activate one later fixed-contract runtime and fixed-Policy forward-cohort implementation task;
3. implement and independently verify that one public-only closure;
4. only after exact-candidate gates, run its separately pre-bound bounded production-public
   evidence; and
5. record only the stage result proved by that evidence.

This delegation never authorizes private/account data, credentials, margin, orders, fills,
capital, money, actual execution Outcome, qualification, promotion, persistent deployment,
force-push, history rewriting, or a direct edit to `main`. This authority-only prerequisite grants
no runtime or live command.

## Business closure

**Given:** the production-public Short Vol Radar is `ESTABLISHED`, and
`SHORT_VOL_UNDERWRITING_POSITION` has accepted, implementation-ready semantics through
`SHADOW_CLOSE_OPPORTUNITY`, but explicitly creates no Position termination, Outcome,
rejected-counterfactual, or cohort-aligned `NO_TRADE`.

**When:** one narrow public-only contract freezes Shadow counterfactual exit selection,
Outcome maturity/censoring, known and unknown economics, rejected-counterfactual enrollment,
aligned `NO_TRADE`, conservation, denominators, durable identities, and result-independent forward
evidence.

**Then:** the queued fixed-contract runtime and fixed-Policy forward cohort has no remaining
semantic prerequisite; a later implementation task can be activated without inventing Outcome or
cohort behavior in code.

**Independent verification:** direct authority tests plus an independent read-only red-team pass
over the exact contract/test bytes and the bounded diff.

**Valid zero/no-hit/UNKNOWN result:** this authority-only task emits no market object and runs no
market command. Zero Entries, Outcomes, or cohort units is therefore not an observed result and
does not accept or reject later runtime reachability.

**Upstream prerequisite:** accepted commit
`12dd2239211afd03e1eef1ee13919bbbed1acac6` and its merge into base
`e4b4aad917c6ecf67b788ef80346837e8d668006`.

## Change declarations

**Market/Decision input contract change:** `NONE` — the contract may consume only public facts
already required by the accepted Radar and Underwriting/Position contracts. It must not add a
delivery-price, settlement-price, private, account, order, or fill source.

**Decision Policy change:** `NONE` — Radar, Underwriting, admission, and Position decisions,
Policy schemas, arithmetic, ordering, and identities remain unchanged.

**Outcome/evaluation contract change:** `APPROVED` —
`SHORT_VOL_PUBLIC_SHADOW_OUTCOME_FORWARD_COHORT`, defining only deterministic downstream
counterfactual Outcome/cohort meaning.

**Stage/authorization change:** `APPROVED` —
`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT_CONTRACT_ACTIVATION` activates only this authority-only
prerequisite and its bounded terminal-goal delegation. Permission remains `PUBLIC_SHADOW`;
runtime/live capability remains unchanged and unauthorized.

## Product operating behavior

The new contract must freeze future behavior without implementing it:

- a `SHADOW_ENTRY` or one separately labeled eligible rejected anchor starts exactly one strictly
  future public observation;
- the causal-order first eligible full-quantity atomic close opportunity after that observation's
  own latched `CLOSE` may be selected once as a counterfactual exit;
- the selected quote is never a fill, actual exposure, flatness, settlement action, or actual PnL;
- an observation with no selected exit reaches `MATURE_UNKNOWN` only at one exact natural
  public-lifecycle terminal rule; ordinary missingness and process stop cannot manufacture
  maturity;
- clean stop or failure censors pending observations and never uses a final mark, mid, component
  quote, stale quote, or stop-time quote as an exit;
- rejected anchors and admitted Shadow Entries remain different object families and denominators;
- every admitted or eligible rejected unit receives one aligned `NO_TRADE` comparison arm whose
  zero cashflow is an action definition, not inferred market evidence; and
- product behavior has no fixed holding duration. A validation enrollment interval, follow-up
  tail, or process stop is evidence scope only.

## Validation harness

Direct authority tests must prove total state/order tables, identities, strict-future boundaries,
economic equations, null propagation, conservation, no-hit behavior, task scope, and non-claims.
No live fixture, replay, stream capture, external artifact, or production-public command is
needed.

The later implementation/evidence task must pre-bind an enrollment cutoff and a strictly future
follow-up/stop boundary independent of anomaly, Candidate, Entry, Outcome, PnL, knownness, or pass
likelihood. That later manifest cannot be created until its exact candidate commit and Policy
digests exist.

## Evidence boundary

**Proves:** the previously missing Shadow Outcome/rejected-counterfactual/`NO_TRADE`/cohort
semantics are complete, internally consistent, implementation-ready, and do not widen current
permission.

**Does not prove:** runtime implementation, source reachability, Candidate quality, a natural
Entry or close, mature Outcome, usable nonempty cohort, edge, profitability, fill, account
economics, qualification, deployment, or execution.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE — authority only |
| Minimal-hit recomputation | NOT_APPLICABLE — no durable hit |
| Bounded stream reconstruction | NOT_APPLICABLE — no replay claim |
| Shadow forward Outcome | NOT_APPLICABLE — no runtime |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:**

- this one active task;
- `docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md`;
- the minimum consistent links/boundaries in `CURRENT_STAGE`, `SYSTEM_ARCHITECTURE`, and `README`;
- direct authority/architecture tests; and
- physical deletion of this task when the contract is accepted.

**Out:**

- changes to Product Constitution, Delivery Contract, Radar contract, accepted
  Underwriting/Position contract, or task template;
- package/application/runtime/CLI/Policy-instance/schema-writer implementation;
- dependency or lock-file changes;
- public market execution, capture, replay, or durable evidence;
- migration or reinterpretation of accepted/sealed objects;
- private/account/order/fill/capital/settlement action; and
- Challenger, qualification, promotion, deployment, or execution.

**Owning module/artifact:** this task owns only the new contract. The contract must name the one
future pure downstream module without creating it.

## Contract

**Inputs and known-at rule:** accepted immutable Radar, Underwriting, Candidate, admission,
`SHADOW_ENTRY`, Position, close-quote, and close-opportunity identities. Outcome facts are
strictly later than their own Entry or rejected anchor under same-runtime `FactBoundary` order.

**Durable output and identity:** contract-only definitions for
`SHADOW_COUNTERFACTUAL_EXIT`, `SHADOW_OUTCOME`, separately labeled rejected-counterfactual
anchor/exit/outcome, aligned `NO_TRADE`, and a forward-cohort summary. This task writes no instance.

**Missing/invalid/UNKNOWN semantics:** ordinary missing, stale, discontinuous, incomplete,
malformed, contradictory, or contaminated evidence leaves the observation pending/unknown; it
never becomes zero, no-trade, known loss, known win, or terminal maturity. Invalid identities fail
closed.

**Persisted meaning and compatibility:** the contract must freeze exact semantic identities,
fields, types, units, nullability, writer/readers, validation, conservation, and
`NOT_COMPARABLE` behavior for any future incompatible identity. No historical object is migrated.

**Business denominators:** separately conserve admitted Shadow observations, rejected
counterfactual observations, aligned comparison pairs, mature-known economics, mature-unknown,
censored-stop, and censored-failure. Zero or unknown denominator means rate `null`.

## Required contract decisions

The closure is incomplete unless the contract decides all of the following without `TBD`:

1. first-eligible causal close selection, exactly-once behavior, and no best-quote hindsight;
2. natural terminal lifecycle and the exact boundary for `MATURE_UNKNOWN` without adding a new
   settlement-price source;
3. `PENDING → MATURE_KNOWN | MATURE_UNKNOWN | CENSORED_AT_STOP |
   CENSORED_AT_FAILURE`, with terminal immutability;
4. exact rejected-anchor eligibility and at-most-one enrollment/de-duplication scope;
5. a separate rejected path reusing, but never impersonating, the frozen Position Policy;
6. admitted-trade versus `NO_TRADE`, and known-rejected `NO_TRADE` versus rejected trade,
   aligned at the same anchor, Policy identities, observation boundary, and censor mask;
7. no extra configurable Outcome/admission Policy unless authority proves it necessary;
8. exact gross/public-fee-reserve/net counterfactual equations and dependency-scoped nulls;
9. `actual_fee`, `actual_pnl`, actual exposure, and actual all-in loss remaining
   `null / UNKNOWN`;
10. object schemas, source/provenance versus business identity, compatibility, and fail-closed
    reader behavior;
11. all conservation equations, rates, natural zero, and empty-cohort non-claims; and
12. enrollment/follow-up/clean-stop evidence rules whose stop cannot depend on results.

## Acceptance

### Direct behavior

1. Given an eligible strictly later full-`q` atomic close opportunity, the contract selects the
   causal first one exactly once and derives counterfactual economics without claiming a fill.
2. Given absent or unknown close evidence, ordinary time, gap, or stop cannot create known or
   mature economics; only the exact natural terminal rule may create `MATURE_UNKNOWN`.
3. Given admitted, rejected, unknown, empty, duplicate, and censored paths, identities and
   conservation remain disjoint and every zero/unknown denominator serializes `null`.
4. The accepted Radar and Underwriting/Position semantics, permissions, and evidence identities
   remain byte-for-byte unchanged.

### Required commands

- `make UV='python3 -m uv' sync`
- focused tests: `.venv/bin/python -m pytest -q tests/test_authority_and_architecture.py`
- `make check`
- `git diff --check`
- production-public command: `NOT_APPLICABLE` — authority-only and forbidden
- independent recomputation/reconstruction: `NOT_APPLICABLE`

### Real evidence

**Required:** NO

**Environment and stopping condition:** `NOT_APPLICABLE`

**Independent verifier:** a read-only reviewer other than the candidate author verifies the exact
contract/test SHA-256 values, focused tests, full checks, diff scope, and non-claims before
acceptance.

## Completion state

Acceptance must:

- add the new contract as an active implementation/evaluation contract with runtime explicitly
  not implemented;
- return `CURRENT_STAGE` sole next closure to `NONE`, with the root blocker narrowed to activation
  of the fixed-contract runtime and fixed-Policy forward cohort;
- delete this task physically;
- leave no runtime, Policy instance, live artifact, or authority implication; and
- report the exact commit/tree, local/remote/PR state, checks, zero live activity, and remaining
  implementation risk.
