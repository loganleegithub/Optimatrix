# Task — B3 post-remediation forward reliability

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** FORBIDDEN

**Live commands:** the existing launchd label `com.optimatrix.b3-public-shadow` may continue its
exact `/Users/logan/Optimatrix/.venv/bin/optimatrix-shadow runtime --event-state NONE --root
/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2 --workbench-port
8765` command under `KeepAlive`. Its public feed may reconnect naturally with the deployed bounded
liveness, backoff, and exactly-once-per-epoch recovery behavior. No manual restart, new process, new
root, synthetic production disconnect, implementation change, private call, order, or other
deployment is authorized. After `2026-08-16T08:20:00Z`, only read-only inspection of the exact root,
Workbench, launchd job, logs, and repository is authorized.

The runtime retains Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, the exact stable root,
loopback port `8765`, and EventState `NONE`.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`,
`docs/contracts/CASE_POSITION_OUTCOME.md`, and `docs/research/PRIMARY_SOURCES.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** commit `673c812` passed `236` tests and `8` deterministic business scenarios, was pushed
to `origin/main`, and replaced the exact launchd job once from PID `51093` to PID `12409`. The new
job retained one lock owner, one loopback listener, HTTP `200`, the same command/root/Policy/EventState
and port, and launchd `runs=3`. Epoch one opened at `2026-08-15T18:15:14.766000Z`, resumed desired
market data at `18:15:15.150484Z`, and completed observation
`sha256:16e6b4c991896cfec0bab1c6e4d945e03ac774f2bd254522696e92591542ec50` at
`18:15:15.167000Z` with `21/21` books, one continuity epoch, `knowledge=KNOWN`, and complete
Candidate-local data readiness. Heartbeats continued beyond one `30s` watchdog interval without a
false reconnect. The replacement's interrupted Window remains a causal restart Gap.

**When:** after `2026-08-16T08:20:00Z`, perform one bounded read-only audit of the `55` scheduled
DecisionWindows whose starts are in `[2026-08-15T18:15:00Z, 2026-08-16T08:00:00Z)`, plus the
`08:15 UTC` next-Session scheduler boundary where prior-Session WindowOutcome work becomes due

**Then:** report exact DecisionRecord coverage and results, causal observations versus typed Gaps,
connection epochs, liveness losses, backoff delays, reconnect-history attempts, recovery-to-healthy-
cut transitions, and any later-Window amplification. Verify that prior-Session WindowOutcomes
advance one count at a time and that current-Session Decision finalization/capture remains ahead of
that work with no new `DECISION_FINALIZATION_CADENCE_MISSED`. If no natural failure occurred, report
`NATURAL_FAILURE_RECOVERY_NOT_OBSERVED`; do not extend the task.

**Affected identity and population:** exactly those `55` future append-once DecisionRecords and the
ordinary future WindowOutcomes of their owning Session; every pre-replacement Window, existing
Decision/Outcome, TradeCase, Position, settlement, and restart Gap remains immutable

**Baseline and denominator:** `55` predeclared post-remediation Windows; at activation the first
Window has one healthy pending MarketObservation and none of the `55` Decisions is finalized. The
pre-remediation incident amplified one silent stream across more than twenty later Window attempts.

**Primary blocker and expected delta:** `POST_REMEDIATION_FORWARD_RELIABILITY_UNMEASURED` becomes
one bounded forward reliability and scheduler-isolation table; the expected delta is evidence, not
a required disconnect, Candidate, trade-frequency increase, or Policy result

**Known-at and DataHealth boundary:** only append-once records and runtime events with causal
boundaries inside the declared population may classify it. Missing, stale, silent, malformed,
discontinuous, or identity-incoherent facts remain absent or typed `UNKNOWN`; no Window, recovery,
Decision, or Outcome may be inferred or backfilled.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** the deployed runtime may append only its
ordinary future Decisions, WindowOutcomes, and genuine Case facts to the exact v2 root. The audit is
read-only, creates no durable review artifact, and performs no backfill or Journal mutation.

**Legacy-data effect:** NONE; v1 and every existing v2 record remain immutable

**Permission effect:** validation only; preserve the exact deployed public launchd runtime and its
bounded natural reconnect behavior, with no implementation, manual restart, deployment, private
access, order, fill, or capital permission

**Files and behavior in scope:** read-only v2 Ledger/runtime events, loopback Workbench, exact
launchd/log state, repository, and caller-supplied ignored temporary calculations; at closure only
this task and the matching Stage snapshot may change

**Out of scope:** implementation changes, forced reconnects, duration extension, Decision or
Outcome backfill, Policy, `7%`, `$10`, sizing, ranker, Candidate manufacture, private facts, orders,
fills, capital, Policy qualification, Edge, C1/C2, D1, remote deployment, and B4

**Complexity added / deleted:** NONE; use existing append-only facts and a bounded read-only join,
with no script, scheduler, schema, retry path, persistence layer, or new runtime consumer

## Verification and closure

**Cheapest falsification:** reconcile the `55` declared Windows against DecisionRecords,
observations, runtime lifecycle/Gap/call events, and unique continuity epochs; reject duplicates,
out-of-population rows, backfill, regressing boundaries, mismatched recovery counts, or an Outcome
count jump greater than one between consecutive append events

**Repository gate:** `make check`

**External evidence:** confirm the exact job remains singular with PID `12409` unless a natural
launchd or feed recovery is durably explained, Workbench returns HTTP `200`, and healthy observations
retain `DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1`. Claim a natural recovery only when a loss event,
capped delay, new epoch, exactly one recovery call, later desired market resume, and later healthy cut
form one causal sequence. Candidate, private execution, profitability, Policy qualification, and
Edge remain `UNVERIFIED`.

Close only after the fixed time and directly reconciled population. Replace Stage with the
post-task snapshot and remove this file; do not append completion history.
