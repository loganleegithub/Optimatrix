# Task — B3 Runtime Ledger And Transport Reliability

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Runtime implementation:** REQUIRED

**Live commands:** One unauthenticated production WebSocket canary may connect to
`wss://www.deribit.com/ws/api/v2` with `proxy=None`, subscribe only to
`deribit_price_index.btc_usd`, inspect at most `20` inbound frames, and stop after the first valid
index notification or `25` elapsed seconds. It may run once before deployment and once after a
failed first canary; the retry must use the same route and bounds. After the branch is fast-forward
merged into `main`, exactly one
`launchctl kickstart -k gui/$(id -u)/com.optimatrix.b3-public-shadow` is authorized. Read-only
`launchctl print`, `ps`, `lsof`, `curl` against `127.0.0.1:8765`, runtime-audit tail inspection, and
bounded CPU sampling are authorized for acceptance. No private method, account method, order,
capital action, backfill, or extra continuous process is authorized.
No other process control is authorized.

**Owning authority/contract:**
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`BTC_0DTE_TWO_SIDED_SHORT_VOL.md`](../docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md), and
[`CASE_POSITION_OUTCOME.md`](../docs/contracts/CASE_POSITION_OUTCOME.md)

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** The stable B3 root contains `497` DecisionRecords and `465` WindowOutcomes. One
unchanged-root `ObservationLedger.read()` takes approximately `1.28–1.35` seconds, a representative
steady tick performs six full reads, and an offline profile measured `195,492,813` calls in
`33.475` seconds, including `2,982` `DecisionRecord.from_object` calls. The deployed process is
continuously near one full CPU core. The installed WebSocket client defaults `proxy=True`; macOS
currently resolves the production WebSocket through `http://127.0.0.1:1082`, and the runtime audit
contains `204` proxy-rejected HTTP `503` losses among `392` WebSocket losses.

**When:** The existing `ObservationLedger` reuses a validated immutable population while the
owning file signature is unchanged, invalidates that cache on any file change, and the production
WebSocket connection explicitly uses the same direct-network boundary as the existing public REST
client. The bounded change is tested, merged into `main`, and the sole B3 LaunchAgent is replaced
once.

**Then:** Repeated reads of unchanged Decision and Outcome files perform no repeated
deserialization; append, external file change, and recovery still expose exactly the accepted
append-only population. A representative steady tick no longer replays the full ledgers. The
deployed main process opens a new direct WebSocket epoch without a socket to `127.0.0.1:1082`,
receives a valid BTC index notification, resumes a complete public-market cut, and continues the
next due Decision without rewriting or backfilling prior facts. Steady-state CPU is below `20%`
across at least five samples outside a due-Window calculation.

**Affected identity and population:** Existing and future `DecisionRecord` and `WindowOutcome`
bytes, identities, ordering, duplicate rules, and denominator remain unchanged. The transport fix
affects future public `MarketObservation` availability only; a connection loss remains a valid
`UNKNOWN` or lifecycle Gap.

**Baseline and denominator:** `497` DecisionRecords, `465` WindowOutcomes, six ledger reads per
representative steady tick, `2,982` Decision deserializations in the profile, and `392` audited
WebSocket loss transitions of which `204` are explicit proxy HTTP `503` rejections.

**Primary blocker and expected delta:** `LEDGER_REPLAY_PER_TICK` changes from six full-file
validation passes to at most one validation per changed file signature; `SYSTEM_PROXY_INHERITANCE`
changes from implicit to explicitly disabled for the production public WebSocket connection.

**Known-at and DataHealth boundary:** Cache reuse is permitted only after the exact durable bytes
were validated and only while their file signature is unchanged. It creates no market fact.
WebSocket loss, discontinuity, stale members, or an invalid cut remains `UNKNOWN` or Gap and is
never repaired or backfilled by this task.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** `ObservationLedger` adds only in-process,
signature-validated read caches consumed by its existing runtime and offline readers. Durable JSONL
shape, append/fsync, accepted-prefix recovery, and all `CaseJournal` behavior remain unchanged.

**Legacy-data effect:** NONE

**Permission effect:** Temporarily authorizes the bounded implementation, public canary, one B3
LaunchAgent replacement, and read-only acceptance checks above. It grants no Policy, private,
account, order, capital, or promotion permission.

**Files and behavior in scope:** `src/optimatrix/observation_ledger.py`,
`src/optimatrix/deribit_websocket.py`, their direct tests in
`tests/test_observation_ledger.py` and `tests/test_deribit_websocket.py`, this task, and
`docs/authority/CURRENT_STAGE.md`.

**Out of scope:** Policy or threshold changes; Decision, Outcome, ledger, journal, Workbench, or
audit schemas; historical fact repair; generic proxy configuration; authenticated channels;
private/account/order methods; D1 review behavior; another runtime, database, queue, migration, or
deployment topology.

**Complexity added / deleted:** Add two private tuple caches plus two private file signatures to the
existing ledger owner, with no new file, service, dependency, configuration, or durable state. Add
one explicit `proxy=None` argument to the existing connection owner. Delete repeated unchanged-file
deserialization and implicit dependence on mutable macOS proxy settings.

## Verification and closure

**Cheapest falsification:** Focused ledger tests prove unchanged reads reuse the validated tuple,
append and external mutation refresh it, malformed/unterminated tails still fail or recover exactly,
and outcome behavior matches Decision behavior. The direct WebSocket test proves `proxy=None` is
passed. A representative copied-root tick/profile must show no repeated deserialization.

**Repository gate:** `make check`

**External evidence:** The bounded direct canary must receive a production BTC index notification.
After deployment, observe the new process owner, direct socket route, new WebSocket epoch and market
stream resume, complete cut, advancing Decision population, Workbench HTTP response, and bounded
steady CPU. Natural Candidate, Entry, Position, Policy qualification, and Edge remain
`NOT_YET_OBSERVED` or `NONE` unless independently produced by frozen business facts.
