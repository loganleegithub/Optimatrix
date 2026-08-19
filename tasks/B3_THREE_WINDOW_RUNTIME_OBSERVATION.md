# Task — B3 Three-Window Runtime Observation

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Runtime implementation:** FORBIDDEN

**Live commands:** From activation at `2026-08-19T16:36:55Z` through at most
`2026-08-19T17:36:55Z`, read-only `launchctl print`, `ps`, `top`, `lsof`, local `curl` against
`127.0.0.1:8765`, `wc`, `tail`, and Python parsers may inspect the existing B3 process, stable-root
JSON/JSONL facts, Workbench projection, and runtime audit. File and audit polling may occur no more
often than every `10` seconds; CPU sampling may use at most six two-second samples per Window.
Existing frozen B3 public calls may continue through the deployed runtime only. No manual public
call, private method, account method, order, capital action, process control, restart, deployment,
durable write, repair, or backfill is authorized.
No other process control is authorized.

**Owning authority/contract:**
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`BTC_0DTE_TWO_SIDED_SHORT_VOL.md`](../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md), and
[`CASE_POSITION_OUTCOME.md`](../docs/contracts/CASE_POSITION_OUTCOME.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** The accepted deployed B3 runtime owns the stable root, label
`com.optimatrix.b3-public-shadow`, loopback port `8765`, direct public WebSocket route, and frozen
Policy above. The prior acceptance ended with `499` DecisionRecords, WebSocket epoch `1`, one
complete post-deployment market cut, and no observed post-deployment stream loss.

**When:** Observe the three consecutive DecisionWindows starting at `2026-08-19T16:45:00Z`,
`2026-08-19T17:00:00Z`, and `2026-08-19T17:15:00Z` through their respective input deadlines at
`17:01:00Z`, `17:16:00Z`, and `17:31:00Z`, plus at most five minutes for read-only evidence
collection.

**Then:** Classify the run as `NORMAL` only if one unchanged process owner remains live, Workbench
stays HTTP `200`, no socket uses `127.0.0.1:1082`, steady CPU samples remain below `20%` outside
bounded Window work, each Window receives an at-or-after-start complete public-market cut, and each
deadline produces exactly one durable DecisionRecord with causal `known_at` and internally
consistent result/blockers. Classify it as `DEGRADED_BUT_FAIL_CLOSED` if a transport/DataHealth gap
is truthfully preserved as `UNKNOWN` and a later epoch recovers without backfill. Classify it as
`FAILED` if the process/port dies, CPU returns to sustained one-core saturation, the proxy socket
returns, a Window has no record after its deadline, or incomplete evidence becomes a known
Decision.

**Affected identity and population:** Exactly the three declared `DecisionWindow` identities and
their runtime-produced Base `DecisionRecord` facts. Observation creates or mutates no fact.

**Baseline and denominator:** `3` consecutive registered DecisionWindows. Exact identities,
initial DecisionRecord count, PID, connection epoch, event offset, and current CPU are
`NOT_YET_MEASURED` because Stage `NONE` forbade a new runtime validation before this activation;
the first authorized read establishes them.

**Primary blocker and expected delta:** `THREE_WINDOW_FORWARD_RELIABILITY_NOT_YET_OBSERVED` changes
to one evidence-backed `NORMAL`, `DEGRADED_BUT_FAIL_CLOSED`, or `FAILED` classification. Historical
missing windows do not change.

**Known-at and DataHealth boundary:** A complete cut must have source watermark at or after its
Window start and retain one valid connection epoch. Disconnect, sequence loss, stale/incomplete
members, or a missing causal cut remains `UNKNOWN` or Gap; observation may not infer, repair, or
backfill it.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** NONE from the validation. Only the already
deployed runtime may append its ordinary frozen-policy Decision/Outcome/Case facts.

**Legacy-data effect:** NONE

**Permission effect:** Temporarily authorizes only the bounded read-only observation commands and
time interval above.

**Files and behavior in scope:** This task, `docs/authority/CURRENT_STAGE.md`, existing B3 process
ownership/CPU/socket/port, runtime audit, Workbench health, and the three declared Window records.

**Out of scope:** Source or test changes; process control; manual market calls; Policy, threshold,
schema, route, risk, Decision, Case, Outcome, D1, private/account/order/capital, deployment, repair,
backfill, qualification, promotion, or Edge changes.

**Complexity added / deleted:** No runtime complexity. Add and later remove only this validation
task; replace Stage with the post-observation snapshot.

## Verification and closure

**Cheapest falsification:** Before waiting, verify one process owner, loopback HTTP `200`, no
`127.0.0.1:1082` socket, stable DecisionRecord count, and exact future Window identities/deadlines.

**Repository gate:** `pytest -q tests/test_authority.py` and `git diff --check`

**External evidence:** Directly inspect audit transitions, complete cuts, durable records, socket
route, process continuity, Workbench response, and bounded CPU samples across all three declared
Windows. A responsive page, heartbeat, or TCP socket alone is insufficient.
