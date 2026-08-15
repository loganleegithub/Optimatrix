# Task — B3 public runtime reliability remediation

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** REQUIRED

**Live commands:** read-only inspection of the exact current launchd job, loopback Workbench, logs,
repository, and v2 root is authorized throughout. After the focused checks and `make check` pass,
commit and push the reviewed implementation plus active Authority to `origin/main`, then perform exactly one
`launchctl kickstart -k gui/<current uid>/com.optimatrix.b3-public-shadow`. The replacement must
retain the exact console command, EventState `NONE`, Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, v2 root, loopback port
`8765`, public method allowlist, and launchd `KeepAlive`. Do not interrupt production networking to
manufacture a reconnect. If repository gates or singular-process checks fail, do not replace the
runtime. No second manual replacement is authorized by this task.

After external acceptance, one second commit and push may contain only the matching post-task Stage
snapshot and removal of this task. No source or test change is allowed in that closure push.

The sole stable ObservationLedger and CaseJournal root remains
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`,
`docs/contracts/CASE_POSITION_OUTCOME.md`, and `docs/research/PRIMARY_SOURCES.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** the existing PID `51093` and loopback HTTP surface remained alive while its last audited
inbound Deribit `public/test` response was at `2026-08-15T12:05:47.666819Z`; every market-cut attempt
from `12:15 UTC` through at least `17:30 UTC` then failed without a new connection epoch. Source
sets the WebSocket library `ping_interval=None` and treats every bounded `recv` timeout as harmless
forever, so a silent half-open transport never calls `disconnect` or the deployed epoch recovery.
Separately, the `08:00 UTC` Window was discarded with
`DECISION_FINALIZATION_CADENCE_MISSED` after one tick synchronously constructed `81` prior-Session
WindowOutcomes; one representative path summary takes about `0.88s` before append-only ledger
validation, so bulk analytical work blocked the online scheduler for minutes.

**When:** add transport-level Ping/Pong failure detection, an application-level inbound-silence
deadline, bounded reconnect backoff and lifecycle audit events, and reduce expired-Session Outcome
construction to at most one WindowOutcome after current-window work in each runtime tick

**Then:** the first valid desired market notification resets the connection failure streak; `30s`
without any valid inbound frame, or `30s` without a desired market notification even while heartbeat
responses continue, closes the connection, records the exact reason, and enters
`1, 2, 4, 8, 16, 30s` capped reconnect backoff. Every new epoch preserves the existing exactly-once
REST history recovery and later same-epoch WebSocket continuation rule; a failed history recovery
invalidates that epoch and may be attempted again only after the capped backoff opens a new epoch.
Current Decision
finalization and market capture always precede at most one restart-safe Outcome unit, so a completed
Session cannot again monopolize the online scheduler. Genuine unavailable periods remain `UNKNOWN`
and are never backfilled.

**Affected identity and population:** transport continuity epochs and future public
MarketObservations after the single replacement boundary; future WindowOutcomes appended from
already authoritative DecisionRecords. Every already attempted Window and existing durable record
remains immutable.

**Baseline and denominator:** at `2026-08-15T17:33:51Z`, the active Session has `38` finalized
DecisionRecords (`14 ABSTAIN`, `24 UNKNOWN`); the declared post-`11:00 UTC` population has `26`
finalized records (`5 ABSTAIN`, `21 UNKNOWN`). These are incident evidence, not a target to rewrite.

**Primary blocker and expected delta:** `PUBLIC_RUNTIME_CAN_REMAIN_HEALTHY_WHILE_STREAM_IS_SILENT`
and `UNBOUNDED_OUTCOME_WORK_BLOCKS_WINDOW_SCHEDULER` become bounded, deterministic failure and work
budgets with append-only lifecycle proof; Candidate frequency and Policy results need not change.

**Known-at and DataHealth boundary:** liveness uses process-local elapsed time that advances through
host sleep only to decide when to close a transport; it never becomes market time. A reconnect seed
alone cannot make a cut ready. Missing, stale, discontinuous, malformed, or cross-epoch evidence
remains a typed Gap/`UNKNOWN`, and no Decision or Outcome is backfilled.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** no schema or identity change. The existing
runtime remains the sole writer. Outcome appends use the existing append-once record as their
restart cursor; no queue, cursor file, database, or compatibility layer is added.

**Legacy-data effect:** NONE; v1 and every existing v2 record remain immutable

**Permission effect:** permits this bounded public-runtime implementation, one implementation push,
one exact local launchd replacement after all repository gates pass, and one Authority-only closure
push after external acceptance; no private, order, fill, capital, Policy, or remote-deployment
permission

**Files and behavior in scope:** elapsed-clock helper, Deribit public WebSocket feed, production
runtime audit binding, expired-Session Outcome work scheduling, direct tests, this task, and the
matching Stage snapshot

**Out of scope:** Policy, `7%`, `$10`, sizing, ranking, Candidate manufacture, durable schema,
historical record rewrite, private facts, orders, fills, capital, C1/C2, D1, Policy qualification,
Edge, remote deployment, a generic scheduler, a second process, and forced production disconnects

**Complexity added / deleted:** enable the locked WebSocket client's existing Ping/Pong mechanism;
add inbound and desired-market elapsed-silence checks, one capped backoff counter, and one
existing-audit callback. Delete
the infinite timeout-ignore behavior and all-at-once Outcome loop. Add no dependency, worker,
durable control record, or generalized retry framework.

## Verification and closure

**Cheapest falsification:** deterministic fake connections prove: repeated `recv` timeouts cross
`30s`, close epoch one, wait `1s`, begin epoch two, attempt exactly one history recovery, and require
a later same-epoch stream continuation; heartbeat responses without desired subscription data also
close at `30s`; a failed epoch-two history recovery closes that epoch and is attempted exactly once
in epoch three; a valid desired market notification resets the failure streak; repeated pre-market
failures cap at `30s`; `_open_connection` configures `ping_interval=10` and `ping_timeout=10`. A
slow/failing Outcome append proves current Decision finalization occurs first and only one Outcome is
attempted per tick; restart resumes the remaining population without duplicates.

**Repository gate:** focused WebSocket, runtime, snapshot, Authority/reference tests, then
`make check`

**External evidence:** before replacement, record the exact launchd label, PID, command, root,
Policy, EventState, port, and singular lock owner. After the one replacement, require a different
single PID, `HEAD == origin/main`, loopback HTTP `200`, explicit stream-open and market-stream-resumed
audit events, and one healthy post-replacement
`DERIBIT_PUBLIC_WEBSOCKET_INCREMENTAL_V1` cut from the new epoch. A natural post-replacement
disconnect remains `NOT_YET_OBSERVED` unless it actually occurs; deterministic failure-injection
proves the mechanism, not production occurrence. Candidate, private execution, profitability,
Policy qualification, and Edge remain `UNVERIFIED`.

Close only after the code, repository gate, single deployment, and declared external evidence are
all directly observed. Replace Stage with the post-task snapshot and remove this file; do not append
completion history.
