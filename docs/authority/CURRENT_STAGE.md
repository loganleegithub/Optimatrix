# Optimatrix Current Stage

**Status:** D1 DAILY REVIEW — C1/C2 ISOLATED CAPABILITIES CONSOLIDATED

**Current maturity:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

## Current permissions

No new validation, process control, deployment, durable write, merge, or live command is authorized
while there is no active task.

**Offline checks and simulation:** existing repository checks and caller-supplied disposable roots
only

**Public market calls:** `NONE_AUTHORIZED` for new or manual Agent actions. The already deployed B3
and daily Review LaunchAgents may continue only their exact frozen public-method manifests.

**Stable ObservationLedger root:** `/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`
remains writable only by the existing B3 runtime. The deployed daily Review job and Workbench
adapter open it read-only and cannot repair, backfill, or replace a Decision or Outcome.

**Stable CaseJournal root:** the same B3 root remains writable only by the existing B3 runtime; AI
Lab owns no CaseJournal write or derived Case fact

**Continuous runtime:** existing B3 launchd job remains unchanged at label
`com.optimatrix.b3-public-shadow`, EventState `NONE`, the stable root above, and loopback port
`8765`. Existing daily label
`com.optimatrix.d1-session-review` may run its repository-owned
one-shot command at load and every `900` seconds, enroll from `2026-08-17T08:00:00Z`, and process
at most one ready Session per invocation. It has no `KeepAlive`, internal wait, or retry loop.

**AI Lab stable durable root:** `/Users/logan/Library/Application Support/Optimatrix/ai-lab` remains
separate from B3. The deployed daily job may append only content-sealed official evidence, one
terminal V3 Review per Session, and deterministic reports; its mutable operation state and bounded
Workbench projection own no business truth.

**Codex CLI:** `NONE`

**Private read-only account permission:** `NONE`; the integrated C1 source grants no credential or
account-read permission

**Orders, capital, and deployment:** `NONE`; the two existing local LaunchAgents remain unchanged

**Policy mutation / promotion:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Implemented business state

- `ObservationLedger` retains one fully validated in-process Decision and Outcome population while
  the owning JSONL file signature is unchanged. Append, external file change, and accepted-prefix
  recovery refresh that cache without changing durable bytes, identities, ordering, duplicate
  rules, or denominator semantics.
- The production public WebSocket explicitly disables the client library's system-proxy discovery.
  This prevents an application-level connection to the configured loopback proxy, but it does not
  bypass a macOS TUN route or fake-IP DNS mapping. Disconnect, discontinuity, staleness, and
  incomplete cuts continue to produce `UNKNOWN` or Gap.
- Human acceptance establishes `B3_PIPELINE_CAPABILITY_ACCEPTED`; it does not manufacture a natural
  Candidate or execution chain. `natural_chain=NOT_YET_OBSERVED`,
  `policy_reachability=COMPLETED_SESSION_LOCAL_RESPONSIBILITY_MEASURED`,
  `policy_qualification=NONE`, and `edge_claim=NONE` remain the evidence boundary.
- Daily Review enumerates canonical Session expiries from the fixed enrollment boundary instead of
  discovering dates only from existing records. A zero-record day therefore remains a registered
  `96`-Window `UNKNOWN` Review rather than disappearing.
- Each invocation requires every recorded Decision to have its append-once WindowOutcome, lets the
  Deribit clock prove Session end, reuses the first valid stored official evidence after a crash,
  and writes the deterministic report before append-only Review memory. It never calls Codex by
  default and cannot create, mutate, or promote a Challenger or Policy.
- `policy-quality-reviews.jsonl`, content-addressed `evidence/`, and deterministic `reports/` remain
  the durable truth. `daily-review-state.json` is operation state only.
  `workbench-review-projection.json` is content-sealed, atomically replaced, bounded to the latest
  `32` current V3 Reviews, and rebuildable from memory; no database, queue, migration, or dual write
  was added.
- Workbench schema `8` exposes completed-Session selection, verdict, exact denominator, logical
  bounds, four quadrants, structure funnel, blockers, official evidence, IV/RV curves with explicit
  `UNKNOWN` breaks, all Window classifications, evidence boundary, and the human promotion gate.
  Full report detail is a separate local asset updated only when projection identity changes, so
  high-frequency Runtime publication does not rewrite historical Review bytes.
- Missing or corrupt AI Lab presentation is explicit and cannot stop the B3 runtime, alter a
  Decision, or grant execution, account, order, fill, capital, Policy, or promotion permission.
- The modular monolith includes isolated C1 mainnet fixed-read-method account capture and C2
  fixed-Testnet existing-Combo lifecycle entrypoints. Their CLIs, safe receipts, and fail-closed
  boundaries are offline verified and remain outside the B3 runtime, Ledger, Journal, D1 Lab, and
  shared Workbench. Package availability grants no credential, private-call, account, order, fill,
  Position, capital, or deployment permission.

## Current observed evidence

- The bounded route diagnosis found the unchanged B3 process still owns one established `:443`
  socket, but `www.deribit.com` resolves locally to `198.18.0.14`, that address routes through
  `utun4`, the socket is `198.18.0.1:54052 -> 198.18.0.14:443`, and Shadowrocket components plus
  the system HTTP/HTTPS proxy on `127.0.0.1:1082` are active. IANA reserves `198.18.0.0/15` for
  non-globally-reachable benchmarking, so the production path remains under Shadowrocket TUN even
  though `websockets.connect(proxy=None)` no longer opens the loopback proxy itself.
- The immediate disconnect mechanism is established as the local `websockets==17.0.1` client:
  production config sends a protocol Ping every `10` seconds and closes after a `10`-second missed
  Pong. The audit shows Deribit `public/test` responses through `16:55:14.725` followed by the
  client-originated `1011 keepalive ping timeout` at `16:55:36.702`; there was no REST book resync
  before the loss. Since the deployment opened epoch `1`, the audit contains `416` successful
  exchange-heartbeat responses, exactly one connection loss, epoch `2` recovery, and no second
  loss at diagnosis time.
- A loopback-only saturated-consumer reproduction with no Shadowrocket produced the exact same
  `sent 1011 (internal error) keepalive ping timeout; no close frame received` when the library's
  default `max_queue=16` paused network reads. The same bounded reproduction stayed open when
  protocol Pings remained enabled but `ping_timeout=None`. This proves that the exception text does
  not identify the network path and that receive backpressure can starve Pong handling locally.
- Shadowrocket is therefore `PLAUSIBLE_CONTRIBUTOR`, not `ESTABLISHED_CAUSE`: it is conclusively in
  the socket path, but neither historical proxy telemetry nor a Shadowrocket-off/direct A/B run was
  available to distinguish a TUN/egress stall from client receive-queue starvation. The mature
  remediation order is to make the Deribit route explicit and A/B it, prevent the aggressive
  protocol-Pong timeout from racing the existing Deribit heartbeat plus `30`-second inbound/market
  silence guards, instrument Ping latency and receive backlog, then run a multi-Window forward
  comparison without changing fail-closed epoch, Gap, or no-backfill semantics.
- Three exact forward Windows were observed from `16:45` through the final `17:31 UTC` input
  deadline and classified `DEGRADED_BUT_FAIL_CLOSED`. PID `67653`, launchd run count `3`, loopback
  listener, Workbench HTTP `200`, and the direct `:443` socket remained stable; no socket returned
  to `127.0.0.1:1082` and no process restart occurred.
- The `16:45 UTC` Window received a complete cut at `16:45:01.129` with source watermark
  `16:45:00.059`, then appended exactly one `ABSTAIN/SESSION_VRP_PROXY_BELOW_THRESHOLD` record at
  `17:01`. Epoch `1` later lost its connection at `16:55:36.702` to a keepalive ping timeout. The
  runtime opened epoch `2`, recovered index history, and resumed real market frames by
  `16:55:41.481`, approximately `4.8` seconds later.
- The `17:00 UTC` Window preserved that transport gap as `PUBLIC_MARKET_GAP` and appended exactly
  one `UNKNOWN/NO_OBSERVATION` record at `17:16`; it did not consume recovered epoch-2 data or
  backfill the missing causal cut. The `17:15 UTC` Window then received a complete epoch-2 cut at
  `17:15:01.835` with source watermark `17:15:00.651` and appended exactly one
  `ABSTAIN/SESSION_VRP_PROXY_BELOW_THRESHOLD` record at `17:31`.
- All eighteen declared per-Window CPU samples were below `20%`; a separate pre-Window sample had
  one transient `31.8%` value but no sustained one-core saturation. The validated Ledger population
  advanced from `499` to `503` because it also included the ordinary preceding `16:30` Window; the
  three target identities each occur exactly once.
- Final repository gate passed `336` tests, `52` subtests, and `8/8` deterministic business
  scenarios, plus formatting, Ruff, strict mypy, compilation, Authority, compatibility, and diff
  checks. The focused C1/C2 and Authority population passed `53` tests. No live private interface,
  account, order, fill, Position, process, or deployment check was authorized or performed.
- One bounded direct production canary received a BTC index notification in its second inbound
  frame. On a copied production root, startup performed the required full validation in `1.510`
  seconds, while a representative steady tick completed in `0.078` seconds with `8` public ledger
  reads and `0` `DecisionRecord.from_object` calls. Against the live `498`-record file, six repeated
  cached reads took approximately `0.000013` seconds after the first validation.
- `main` was fast-forwarded to implementation commit `0048125`; the sole B3 LaunchAgent was replaced
  once from PID `15272` to PID `67653`. The new process owns the lock and loopback listener, returns
  HTTP `200`, has no socket to `127.0.0.1:1082`, and opened one `:443` transport connection. Six
  steady CPU samples were `0.0%`, `11.9%`, `17.9%`, `9.2%`, `15.1%`, and `16.8%`.
- The deployed runtime opened WebSocket epoch `1`, resumed real market frames, produced one complete
  public-market cut, and recorded no post-deployment stream-loss transition during acceptance. The
  Decision population advanced from `498` to `499`; the restart-interrupted `16:15 UTC` Window was
  truthfully frozen as `UNKNOWN/NO_OBSERVATION` at `16:31 UTC`, without repair or backfill.
- Daily LaunchAgent completed its first automatic invocation with exit code `0`. AI Lab memory is
  `VALID_AI_LAB_MEMORY` with `3` current V3 Reviews and `0` Codex analyses. Workbench projection
  contains Sessions `2026-08-17`, `2026-08-16`, and `2026-08-15`, newest first.
- For `2026-08-17T08:00:00Z`, Review
  `sha256:0fa091e47f1f7dfdfd2350431ec91f8250ed6d14da32e8d6f72b6a416f564c72`
  binds official evidence
  `sha256:c7c5adc450bedce38c11f242014ce31295716c25c297a54e8a64eaef7f198370`:
  `2879` one-minute index points, complete Session coverage, and zero gaps. The exact population is
  `96` DecisionRecords and `96` WindowOutcomes; `86` Windows are auditable and `10` remain
  `UNKNOWN`. Known classifications are `0` captured, `86` correct avoidance, `0` missed, and `0`
  over-risk. Verdict is `PARTIALLY_IDENTIFIED_NO_KNOWN_RULE_ERROR`; miss, over-risk, and opportunity
  rates are each bounded by `[0/96, 10/96]`. Challenger comparison is not eligible.
**Primary blocker:** `PUBLIC_WEBSOCKET_TUN_VS_RECEIVE_BACKPRESSURE_NOT_DISAMBIGUATED` — application-
level proxy inheritance is closed, but the deployed socket still traverses Shadowrocket TUN and
the aggressive `10`-second protocol-Pong timeout can also be reproduced from local receive
backpressure without Shadowrocket. The client-originated close mechanism is established;
Shadowrocket is only a plausible contributor until one controlled route A/B and backlog/latency
instrumentation distinguish the underlying missed-Pong cause. No liveness or route hardening has
been implemented or deployed.
The underlying `DECISION_TIME_OBSERVATION_COVERAGE_INCOMPLETE` blocker also remains: a later history
seed cannot repair an absent decision-time option cut, qualify Policy, or establish Edge. Any new
diagnosis, implementation, validation, deployment, or live command requires one exact task and
matching Stage activation.
