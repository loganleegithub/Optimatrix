# Task — B3 post-recovery forward reliability

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** FORBIDDEN

**Live commands:** the existing launchd label `com.optimatrix.b3-public-shadow` may continue its
exact `/Users/logan/Optimatrix/.venv/bin/optimatrix-shadow runtime --event-state NONE --root
/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2 --workbench-port
8765` command under `KeepAlive`. Its public feed may reconnect naturally and make the existing
allowlisted calls, including at most one unauthenticated
`public/get_index_chart_data(index_name=btc_usd, range=2d)` recovery call in each new WebSocket
connection epoch. No manual `launchctl` restart, new process, new root, retry within an epoch,
private call, order, or deployment is authorized. After the Session ends, only read-only inspection
of the exact root, loopback Workbench, launchd job, logs, and repository is authorized.

The runtime retains Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, the exact stable root,
loopback port `8765`, and EventState `NONE`.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`,
`docs/contracts/CASE_POSITION_OUTCOME.md`, and `docs/research/PRIMARY_SOURCES.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** commit `9969af3` passed `228` tests and `8` deterministic business scenarios, was pushed
to `origin/main`, and was deployed once under the exact launchd job. PID `51093` served loopback
HTTP `200` and produced healthy WebSocket observation
`sha256:ba830878949ef8930642b93ebba52b91cdce5643e209d8fc716931a5145283d2` at
`2026-08-15T11:00:19.612000Z`. Deterministic tests prove the reconnect recovery transition, but no
post-deployment natural reconnect has yet exercised it.

**When:** Session `2026-08-15T08:00:00Z/2026-08-16T08:00:00Z` is complete, perform one bounded
read-only audit of the `84` scheduled DecisionWindows whose starts are in
`[2026-08-15T11:00:00Z, 2026-08-16T08:00:00Z)`

**Then:** report exact DecisionRecord coverage, evaluable versus typed-Gap counts, WebSocket
connection epochs, disconnect ownership, index-history recovery calls, and any later-Window gap
amplification. A Session with no natural reconnect closes with
`NATURAL_RECONNECT_RECOVERY_NOT_OBSERVED`; it does not fail the implementation, extend observation,
or require a Candidate.

**Affected identity and population:** exactly those `84` not-yet-finalized DecisionWindows and
their future append-once DecisionRecords and WindowOutcomes; the pre-deployment `10:45 UTC` Window,
all earlier Decisions, the completed prior Session, TradeCases, Positions, and settlements remain
immutable

**Baseline and denominator:** `84` predeclared post-deployment Windows; at activation one healthy
cut exists and zero of these Windows is finalized. The prior measured baseline was one disconnect
turning six Windows unavailable, five through a retained history gap.

**Primary blocker and expected delta:** `POST_RECOVERY_FORWARD_RELIABILITY_UNMEASURED` becomes one
bounded completed-Session reliability table; the expected delta is measurement, not a required
reconnect, Candidate, trade-frequency increase, or Policy result

**Known-at and DataHealth boundary:** only append-once records and runtime events whose causal
boundaries fall inside the declared population may classify it. Missing, stale, malformed,
discontinuous, or identity-incoherent facts remain absent or typed `UNKNOWN`; no Window, recovery,
or Decision may be inferred or backfilled.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** the already deployed runtime may append
only its ordinary future DecisionRecords, WindowOutcomes, and genuine Case facts to the exact v2
root. The audit is read-only, creates no durable review artifact, and performs no backfill or
Journal mutation.

**Legacy-data effect:** NONE; v1 and the completed prior Session remain immutable and excluded from
the validation population

**Permission effect:** validation only; preserve the exact existing public launchd runtime and its
bounded reconnect behavior, with no implementation, manual restart, deployment, private access,
order, fill, or capital permission

**Files and behavior in scope:** read-only v2 Ledger/runtime events, loopback Workbench, exact
launchd and log state, and caller-supplied ignored temporary calculations; at closure only this task
and the matching Stage snapshot may change

**Out of scope:** implementation changes, synthetic reconnects against production, process
replacement, duration extension beyond the declared Session audit, Decision or Outcome backfill,
Policy, `7%`, `$10`, sizing, ranker, Candidate manufacture, historical Workbench UI, private facts,
orders, fills, capital, Policy qualification, Edge, D1, remote deployment, and B4

**Complexity added / deleted:** NONE; use the existing append-only facts and a bounded read-only
join, with no script, scheduler, schema, retry path, persistence layer, or new runtime consumer

## Verification and closure

**Cheapest falsification:** after Session end, reconcile the `84` declared Windows against
DecisionRecords, runtime Gap/call events, observation source identities, and unique continuity
epochs; reject duplicate, out-of-population, backfilled, or causally inconsistent rows

**Repository gate:** `make check`

**External evidence:** confirm the exact launchd job and root remain singular, Workbench returns
HTTP `200`, and post-deployment healthy observations retain
`DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1`. Claim a natural reconnect recovery only if one new epoch
has exactly one audited recovery call followed by a later same-epoch healthy cut; otherwise report
it `NOT_YET_OBSERVED`. Candidate, private account truth, execution, profitability, Policy
qualification, and Edge remain `UNVERIFIED`.

Close only after the bounded population is complete and directly reconciled. Replace Stage with the
post-task snapshot and remove this file; do not append completion history.
