# Task — Radar authority realignment

**Status:** ACTIVE

**Task kind:** `AUTHORITY_ONLY`

**Runtime implementation:** FORBIDDEN

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md) /
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md) /
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `fb103f48d74eb084ad9bfc13df70984ce75a989f`

**Target branch/PR:** `codex/radar-authority-realignment` / Draft PR if published

## Business closure

**Given:** the active authority routes development into a long bounded Fixed-Policy evidence run
before production Radar input reachability has been established.

**When:** the authority chain is realigned around one continuously captured public fact stream,
rolling state, repeated scans, localized availability, explicit denominators, and asynchronous
Outcome maturity.

**Then:** later AI agents are authorized to establish production Radar reachability first and
cannot treat an all-`UNKNOWN` bounded run, replay equality, or evidence-bundle completion as a
usable Fixed-Policy business baseline.

**Independent verification:** a fresh authority read and repository-wide consistency search find
one next closure, one runtime lifecycle, and no active authority that makes a one-hour warm-up or
six-hour evidence window the product processing unit.

**Valid zero/UNKNOWN result:** existing all-`UNKNOWN`, zero-assessment evidence remains honest
diagnostic evidence. It does not close `RADAR_ESTABLISHMENT` or prove zero Policy opportunity.

**Upstream prerequisite:** explicit human authorization to amend the authority chain, supplied by
the request to correct the documented product direction.

## Change declarations

**Market/Decision input contract change:** APPROVED — define the prospective
`DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT` identity, which separates global risk-input readiness,
universe coverage, per-structure quote/executability readiness, and admission gates. This
authority-only task does not change persisted artifacts or runtime behavior.

**Decision Policy change:** APPROVED — define the prospective
`OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY` identity. It preserves all horizons, formulas,
structure-universe and OTM filters, configured quantity, thresholds, reserves, non-schedule
vetoes, ranking, and WATCH mapping; its only delta is removing the unavailable
`SCHEDULED_BLOCK_STATE` predicate from economic Candidate eligibility. No source is added and no
`CLEAR` is fabricated. Any future scheduled-event Shadow-admission gate requires separate
authorization.

The preserved values are OTM-only 1:1 same-expiry same-side verticals, TTE
1,800–259,200 seconds, quantity `0.04`, horizons `(1,800, 3,600, 7,200, 14,400)` seconds, and a
1,800-second settlement buffer. All four horizons remain assessment opportunities before the
`TTE_BUFFER` predicate.

**Outcome/evaluation contract change:** APPROVED FOR PRODUCT DIRECTION ONLY — existing deployed
strict-future actual Shadow Outcome semantics remain unchanged. A future forward-cohort contract
may add separately labeled, strictly post-decision rejected-opportunity counterfactuals; this task
does not change an Outcome identity, schema, or runtime.

**Stage/authorization change:** APPROVED — replace `FIXED_POLICY_PUBLIC_SHADOW` with
`RADAR_ESTABLISHMENT` as the sole next product-capability closure and permit continuous
production-public fact acquisition and Radar scanning. A long-running admission/Outcome cohort,
private/account data, orders, fills, capital, qualification, Challenger, promotion, and execution
remain forbidden.

## Product operating behavior

The long-term product uses one shared public fact stream, rolling state, repeated scans, immutable
Policy evaluation, separate admission, and asynchronous Outcomes. The current prospective
permission stops after continuous Radar acquisition and scanning; it does not authorize a
long-running admission/Outcome cohort.

## Validation harness

This documentation closure uses a fresh authority read, link/consistency searches, and repository
checks. It performs no bounded market run; a future Radar task may use a short observation window
only as evidence of the ongoing lifecycle.

## Evidence boundary

**Proves:** the authority chain describes the intended business lifecycle, orders the next
closure behind its real production prerequisite, and makes evidence requirements proportional to
the assertion.

**Does not prove:** production Radar reachability, any completed assessment, Policy value,
candidate rate, Entry, Outcome, qualification, profitability, or execution.

| Evidence class | Requirement |
|---|---|
| Direct synthetic/behavior | NOT_APPLICABLE |
| Bounded public capture | NOT_APPLICABLE |
| Production Radar reachability | NOT_APPLICABLE |
| Fresh-process replay | NOT_APPLICABLE |
| Shadow Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution environment | NOT_APPLICABLE |

## Scope

**In:** Product Constitution, Current Stage, System Architecture, Delivery Contract, Short Vol
contract, README status/legacy-tool labeling, task template, its direct authority test, and this
semantic task.

**Out:** Python behavior, schemas, persisted identities, all Policy changes except the exact
prospective scheduled-block relocation above, live Deribit runs, replay performance, evidence
bundles, Draft PR #3, and any merge or stage advance beyond `PUBLIC_SHADOW`.

**Owning module/artifact:** `README.md`, `docs/authority/`,
`docs/contracts/SHORT_VOL_RADAR.md`, `tasks/`, and
`tests/test_authority_and_architecture.py`.

## Contract

**Inputs and known-at rule:** authority text and currently verified production evidence; no market
fact or historical result is reinterpreted.

**Durable output and identity:** one reviewable Git diff on the bounded task branch.

**Missing/invalid/UNKNOWN semantics:** unavailable production inputs remain `UNKNOWN` at the
smallest affected business scope. An unavailable assessment cannot become Policy `ABSTAIN`, a
zero opportunity, or a successful Radar baseline.

**Persisted contract identity/replay compatibility:** `NOT_APPLICABLE`; no runtime artifact is
written or reinterpreted.

**Business denominators:** the authority must keep scan cycles, structures,
structure-by-horizon assessment opportunities, completed and Policy-evaluable assessments,
actions, Entries, and mature Outcomes distinct.

## Acceptance

### Direct behavior

1. Authority says facts use one shared collection path, windows roll after initial warm-up, scans
   repeat, and bounded evidence windows do not define Online Runtime lifetime.
2. Authority separates global readiness, universe coverage, per-structure readiness, Policy
   action, admission, and Outcome maturity.
3. Authority requires a nonzero Policy-evaluable-assessment denominator before recording a numeric
   zero-Candidate rate and reports the linked ledgers with matching units and denominators.
4. `CURRENT_STAGE` says production Radar reachability is not established and authorizes only
   `RADAR_ESTABLISHMENT` next.
5. Radar acceptance requires at least two executed scan cycles and at least one non-null Policy
   action; skipped/unavailable due cycles retain null frame/denominators and an exact reason.
6. The Radar establishment closure does not require Entry, mature Outcome, a six-hour run,
   RunReceipt, historical archive, multi-layer drift bundle, or Policy tuning beyond the exact
   scheduled-block relocation.
7. Evidence and replay requirements are `REQUIRED` or `NOT_APPLICABLE` according to the task
   assertion; Radar establishment reuses existing inspection support and creates no replay
   artifact or drift taxonomy.
8. The absent production scheduled-block source is not replaced. The target Radar Policy removes
   it from economic Candidate eligibility under a new identity; no document fabricates `CLEAR`.

### Required commands

- `make sync`: `NOT_APPLICABLE` — authority/docs-only
- authority-link and consistency searches
- focused authority test: `.venv/bin/pytest tests/test_authority_and_architecture.py -q`
- `make check`: `NOT_APPLICABLE` to acceptance; it may be run as an extra regression check
- live/replay/Outcome command: `NOT_APPLICABLE`

### Real evidence

**Required:** NO

**Environment and minimum duration:** `NOT_APPLICABLE`

**Required report:** `NOT_APPLICABLE`; the current production all-`UNKNOWN` evidence is context,
not acceptance evidence for this documentation closure.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Capture/receipt/replay paths and hashes:** `NOT_APPLICABLE`

**Policy/contract identities:** deployed bounded identities remain unchanged. Prospective Radar
identities are `DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT` and
`OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY`; its cycle artifact is
`SHORT_VOL_RADAR_SCAN_SUMMARY`. A future implementation must persist changed meaning only under
those identities.

**Commit/PR:** recorded by Git and the final delivery report if published.

**Unknowns and non-claims:** scheduled-event avoidance has no authorized production source and is
not part of target economic Candidate eligibility. No future admission veto is implied. The target
input/Policy contracts remain unimplemented and prove no production reachability or Policy value.

## Definition of done

The authority route, Short Vol contract, README, task template, and direct authority test agree on
the business lifecycle, stage order, availability semantics, denominators, evidence
proportionality, and non-claims; focused checks pass; only this authority closure is changed; no
runtime or evidence artifact is mutated; and the result remains unmerged pending explicit human
acceptance.
