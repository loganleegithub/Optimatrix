# Task — B3 Policy reachability and filter audit

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** FORBIDDEN

**Live commands:** the already deployed launchd label `com.optimatrix.b3-public-shadow` may continue
its exact current public Shadow command and append to the exact v2 root under `KeepAlive`; this task
may not start, stop, restart, replace, signal, or reconfigure it. One bounded offline process may
read a fixed DecisionRecord snapshot from that root and emit audit facts to stdout. Read-only
`launchctl`, process, loopback HTTP, and root-integrity checks are allowed. The audit may make no
network call, write no Ledger or Journal member, and retry no market boundary.

The preserved runtime and audit both use Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888` and the exact stable root
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`, and
`docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** `B3_PIPELINE_CAPABILITY_ACCEPTED`, `natural_chain=NOT_YET_OBSERVED`, the unchanged schema-9
Policy, and an append-only v2 root whose pre-Authority snapshot contained `20` DecisionRecords,
including `11` DataHealth-healthy records, no Candidate, and no WindowOutcome

**When:** one immutable start-of-process DecisionRecord identity set is audited against the frozen
Policy by enumerating every Policy-legal four-leg structure and reporting every gate's raw value,
threshold margin, exact blocker set, Base eligibility, single-gate ablation, `0.1–0.5 BTC` full-depth
repricing, raw versus one-adverse-tick component crossing, fee/loss/reserve facts, and whether the
ranker ever receives more than one eligible structure; already recorded actual future paths and
official settlement may be joined by identity, while absent future facts remain absent

**Then:** the current snapshot has one exact reachability/responsibility result that distinguishes
Window-level contribution from structure count, unit economics from total-dollar sizing, local
component-stress sensitivity from executable route evidence, and near-term blocker location from
forward gate value; no Policy, Candidate, Position, Outcome, or market fact is created or relabelled

**Affected identity and population:** the ordered content-identified set of current-Policy
DecisionRecords present at audit-process start and their owning DecisionWindows; later appends are
outside that snapshot, and structures, legs, retries, Cases, and Positions do not change its
denominator

**Baseline and denominator:** pre-Authority observation `20` DecisionRecords, `11` DataHealth-healthy
records, `0` Candidates, and `0` WindowOutcomes; the audit must print its own exact start boundary,
identity count, DataHealth count, phase count, and evaluable-structure count before interpreting any
gate contribution

**Primary blocker and expected delta:** `POLICY_GATE_RESPONSIBILITY_UNMEASURED` becomes one bounded
measured snapshot; `FILTER_FORWARD_VALUE_NOT_YET_MEASURED` remains explicit for every gate lacking
aligned actual future paths and is not converted to failure, usefulness, or Edge

**Known-at and DataHealth boundary:** only immutable observations already bound to each
DecisionRecord may be repriced; `UNKNOWN`, missing observations, unhealthy data, absent future
paths, and unavailable settlement remain excluded or typed exactly as their owners require. No
later book, host wall time, synthetic path, or hindsight grouping may enter an earlier Window

## Effects and scope

**Risk allocation effect:** NONE; size-ladder calculations report counterfactual reserve and
capacity only and cannot reserve, release, or call a larger amount safer

**ObservationLedger / CaseJournal effect and consumer:** read-only access to
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`; stdout is the
only audit output, the existing runtime remains the sole writer, and no record is copied, migrated,
backfilled, or enriched

**Legacy-data effect:** NONE; v1 remains excluded

**Permission effect:** preserve only the exact existing public launchd deployment and add no market,
private, order, capital, Policy-promotion, or remote-deployment permission

**Files and behavior in scope:** the read-only v2 snapshot, existing Policy/structure/pricing codecs
as imported consumers, this task, matching Stage snapshot, direct Authority structural tests, and
package guidance that names the superseded task

**Out of scope:** runtime or Policy implementation, threshold or sizing change, new Policy identity,
Challenger, durable audit schema or report, raw tape, synthetic or Monte Carlo future path, HAR or
other model, public Combo claim, private `create_combo`, account facts, orders, fills, capital,
Policy qualification, Edge claim, and B4

**Complexity added / deleted:** add no abstraction, option, dependency, durable field, retry, or
file beyond this task; delete only superseded package guidance after the Authority transition

## Verification and closure

**Cheapest falsification:** the audit must reproduce each recorded Base result before any ablation,
show that one-variable counts are attributed per Window as well as per structure, and prove that
size changes rerun depth rather than multiplying `0.1 BTC` economics

**Repository gate:** focused Authority tests plus `make check`; audit commands use
`PYTHONDONTWRITEBYTECODE=1` and disable pytest cache writes

**External evidence:** actual future paths, official settlement, natural Candidate chain, and Combo
execution remain `UNVERIFIED` unless already content-bound in the audited root

Close only after directly observing the declared delta. Replace Stage with the post-task snapshot
and remove this file; do not append completion history.
