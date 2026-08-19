# Task — B3 WebSocket Route and Liveness Diagnosis

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Target maturity stage:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Runtime implementation:** FORBIDDEN

**Live commands:** One bounded read-only collection may use `launchctl print`, `ps`, `lsof`,
`scutil --proxy`, `scutil --dns`, `route -n get`, `netstat -rn`, `dig`, `rg`, `tail`, `wc`, and
Python parsers against the existing B3 process, the stable runtime audit, and non-secret local
Shadowrocket routing metadata. No command may call Deribit, open a new socket, reveal a proxy node,
subscription URL, credential, account value, or decrypted payload, or retry a failed check more
than once. Existing frozen B3 public calls may continue through the deployed runtime only. No
process control, restart, deployment, configuration change, durable runtime write, repair, or
backfill is authorized.
No other process control is authorized.

**Owning authority/contract:**
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** The three-Window observation recorded one
`ConnectionClosedError: sent 1011 (internal error) keepalive ping timeout` on the production
WebSocket after application-level proxy discovery was disabled with `proxy=None`; the process
recovered in a new epoch and failed closed, but its socket was observed at `198.18.0.14:443` while
Shadowrocket was in use.

**When:** Reconcile the frozen incident evidence with the exact `websockets==17.0.1` receive,
backpressure, and Ping/Pong behavior; inspect the current non-secret DNS/TUN/route and existing
socket ownership once; reproduce candidate client-side failure modes only on loopback; and compare
the result with current primary documentation for websockets, Deribit heartbeat, IANA special-use
addressing, and Shadowrocket routing semantics.

**Then:** Classify Shadowrocket as `ESTABLISHED_CAUSE`, `PLAUSIBLE_CONTRIBUTOR`, or
`NOT_SUPPORTED_BY_EVIDENCE`; identify the earliest established client/network mechanism; and
produce one ordered mature remediation and validation plan without changing runtime behavior.

**Affected identity and population:** `NOT_APPLICABLE`; diagnosis creates or mutates no market,
Decision, Case, Position, or Outcome fact.

**Baseline and denominator:** One observed production disconnect at `2026-08-19T16:55:36.702Z`,
one recovered epoch, and one causally lost `17:00 UTC` DecisionWindow. Current route and socket
state are `NOT_YET_MEASURED` because the prior validation task closed.

**Primary blocker and expected delta:** `PUBLIC_WEBSOCKET_KEEPALIVE_TIMEOUT_ROOT_CAUSE_UNESTABLISHED`
changes to an evidence-ranked cause classification and one bounded implementation/validation
recommendation; no reliability claim changes.

**Known-at and DataHealth boundary:** Historical audit and current route metadata may diagnose
transport handling but cannot repair the lost Window, prove future availability, or turn
`UNKNOWN` into a known Decision. HTTP, process, socket, or heartbeat health alone is insufficient.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** NONE

**Legacy-data effect:** NONE

**Permission effect:** Temporarily authorizes only the bounded read-only diagnostics above.

**Files and behavior in scope:** This task, `docs/authority/CURRENT_STAGE.md`, existing WebSocket
source/tests/locked dependency source, historical runtime audit around the incident, current B3
socket route, macOS DNS/proxy/TUN metadata, and official primary documentation.

**Out of scope:** Source/test/dependency/Shadowrocket changes; manual market calls; process control;
restart; deployment; Policy, schema, route mutation, Decision, Case, Outcome, private/account/order,
capital, qualification, promotion, repair, backfill, or Edge changes.

**Complexity added / deleted:** No runtime complexity. Add and later remove only this validation
task; replace Stage with the post-diagnosis snapshot.

## Verification and closure

**Cheapest falsification:** Prove whether `198.18.0.14` is globally reachable and whether a local
receive-queue stall can reproduce the exact production close reason without Shadowrocket.

**Repository gate:** `pytest -q tests/test_authority.py` and `git diff --check`

**External evidence:** One bounded non-secret route/socket/DNS collection plus current primary
documentation. No new Deribit connection is authorized.
