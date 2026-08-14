# Task — B3 forward WindowOutcome evidence

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** FORBIDDEN

**Live commands:** the already deployed launchd label `com.optimatrix.b3-public-shadow` may continue
its exact current public Shadow command and append to the exact v2 root under `KeepAlive`; this task
may not start, stop, restart, replace, signal, or reconfigure it. At or after
`2026-08-15T08:15:00Z`, one read-only process may inspect the root, runtime audit, and loopback
Workbench and join the fixed audit population to existing WindowOutcomes. If the expected outcome
population is still absent at `2026-08-15T09:00:00Z`, the task closes `UNVERIFIED` with the exact
runtime state and does not retry, wait for a Candidate, or call the market itself.

The preserved runtime and read-only join use Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888` and exact root
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`, and
`docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** reachability snapshot
`sha256:984cb26a2112979ac34453ad00265f6b7e2ed3506a976b0edceab76ba01d25fc` contains `21`
DecisionRecords through `2026-08-14T17:01:00Z`, including `9` environment-pass Windows and `0`
WindowOutcomes; removing only the frozen `7%` gate changes exactly one Window from `0` to `5`
selection-eligible structures without changing Policy

**When:** the unchanged runtime performs its existing post-expiry official-settlement and public
future-index-path finalization for the Session ending `2026-08-15T08:00:00Z`, and one bounded
read-only join evaluates the nine audit Windows against only the resulting actual WindowOutcomes

**Then:** the five `7%`-only structures in the affected Window are reported against actual
short-strike touch/breach, path extrema, and settlement availability when those facts exist; every
missing or discontinuous dimension remains exact `UNKNOWN`/`UNVERIFIED`, and the task closes without
requiring a Candidate or changing the `7%` threshold

**Affected identity and population:** exactly these nine environment-pass `DecisionWindowId`
values from the frozen snapshot; later DecisionRecords and every structure count remain outside the
Window denominator:

```text
sha256:76a4fd7a05ca0a3e16fe2284f21ced8bc5cbd026f19342ca4c4219d7c12fad32
sha256:02ff123b5fd9447ac94039a7f878c55b0e23bb379891f952ec007d651b4c660e
sha256:dbd50cb7c52daf2f2c80e697c1b6735a8a56fb7a949bb6dc8190981bfbdf9bbb
sha256:c6d2c3299e18a1c0dd94eccdaf34a8054f1827dea843a2eb83f6909c5e035a5a
sha256:9df895a3d280644e3d78a2bf798c3899f8eb6650f323659137ddb1d5097dfd52
sha256:69719492306bae6d5e8c0c4f2808ff9dec82eb177e8c12a237be5744f2f949b2
sha256:bd19514e54db26b49413284b7b0926aca481cce0879bb0b4022724f55b7e81cf
sha256:ea2d1f6332229306da9ffc0ad510cd6f8e28105aa7898163d4bbe51a77c28f85
sha256:5575c855c4ffe2081e193715a7d580df647f1196e9e47d71da6509c47c8d0fce
```

**Baseline and denominator:** `9` audit Windows, `755` price-evaluable structures, `0` Base-eligible
structures, `5` structures in `1` Window after removing only `7%`, and `0` WindowOutcomes at the
audit boundary; structures do not multiply the denominator

**Primary blocker and expected delta:** `FILTER_FORWARD_VALUE_NOT_YET_MEASURED` becomes actual
path evidence for the fixed affected Window or an exact bounded `UNVERIFIED` reason by
`2026-08-15T09:00:00Z`; natural Candidate occurrence has no role in closure

**Known-at and DataHealth boundary:** only content-bound WindowOutcome path and official-settlement
facts appended by the existing runtime may enter the join. Later option books, synthetic paths,
host wall time, hindsight regime grouping, or a fabricated Entry/exit cannot price the five
counterfactual structures

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** the existing runtime remains the sole
writer; this task reads the exact v2 Ledger and no CaseJournal fact is required. The join writes no
record, report, enrichment, copy, or backfill

**Legacy-data effect:** NONE; v1 remains excluded

**Permission effect:** preserve only the exact existing public launchd deployment and add no market,
private, order, capital, Policy-promotion, or remote-deployment permission

**Files and behavior in scope:** the fixed nine-Window identity set, their existing WindowOutcomes,
this task, matching Stage snapshot, and direct Authority structural checks

**Out of scope:** waiting for a Candidate, runtime or Policy implementation, changing `7%` or `$10`,
sizing, new Policy identity, Challenger, durable audit artifact, synthetic or Monte Carlo path, HAR
or another model, Combo or fill claim, private fact, order, capital, Policy qualification, Edge
claim, and B4

**Complexity added / deleted:** add no abstraction, option, dependency, schema, retry, or durable
file; delete only the completed reachability-audit task

## Verification and closure

**Cheapest falsification:** prove all joined WindowOutcomes belong to the fixed identities and
Policy, preserve actual known-at/path-continuity facts, and do not infer an unobserved option route
or Position from index path

**Repository gate:** focused Authority tests; rerun `make check` only if tracked source or structural
tests change

**External evidence:** bounded to the existing runtime's post-expiry output; Candidate and natural
chain evidence are explicitly unnecessary

Close after the first bounded post-expiry inspection, including an honest `UNVERIFIED` result.
Replace Stage with the post-task snapshot and remove this file; do not append completion history.
