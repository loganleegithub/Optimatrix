# Optimatrix Current Stage

**Status:** B3 RUNTIME LEDGER AND TRANSPORT RELIABILITY — ACCEPTED AND DEPLOYED

**Current maturity:** `D1_AI_LAB_DAILY_SESSION_REVIEW`

**Product Authority:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Frozen Base Policy identity:**
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

## Current permissions

No new validation, process control, deployment, durable write, or live command is authorized while
there is no active task.

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
`8765`. Existing daily label `com.optimatrix.d1-session-review` may run its repository-owned
one-shot command at load and every `900` seconds, enroll from `2026-08-17T08:00:00Z`, and process
at most one ready Session per invocation. It has no `KeepAlive`, internal wait, or retry loop.

**AI Lab stable durable root:** `/Users/logan/Library/Application Support/Optimatrix/ai-lab` remains
separate from B3. The deployed daily job may append only content-sealed official evidence, one
terminal V3 Review per Session, and deterministic reports; its mutable operation state and bounded
Workbench projection own no business truth.

**Codex CLI:** `NONE`

**Private read-only account permission:** `NONE`

**Orders, capital, and deployment:** `NONE`; the two existing local LaunchAgents remain unchanged

**Policy mutation / promotion:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Implemented business state

- `ObservationLedger` retains one fully validated in-process Decision and Outcome population while
  the owning JSONL file signature is unchanged. Append, external file change, and accepted-prefix
  recovery refresh that cache without changing durable bytes, identities, ordering, duplicate
  rules, or denominator semantics.
- The production public WebSocket explicitly disables the client library's system-proxy discovery.
  It uses the same direct-network boundary as the existing REST client while disconnect,
  discontinuity, staleness, and incomplete cuts continue to produce `UNKNOWN` or Gap.
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

## Current observed evidence

- Final repository gate passed `290` tests, `52` subtests, and `8/8` deterministic business
  scenarios, plus formatting, Ruff, strict mypy, compilation, Authority, compatibility, and diff
  checks. Focused ledger and WebSocket coverage passed `29` tests.
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
**Primary blocker:** `DECISION_TIME_OBSERVATION_COVERAGE_INCOMPLETE` — the latest completed Session
still has `10/96` causally missing decision-time observations. Post-Session index history repairs
future sampled variance only; it cannot recreate absent option books, prove executable liquidity,
qualify the Policy, or establish Edge. `LEDGER_REPLAY_PER_TICK` and `SYSTEM_PROXY_INHERITANCE` are
closed implementation blockers; their closure does not repair prior gaps. Any new implementation,
validation, Policy experiment, deployment, or live command requires one new exact task and matching
Stage activation.
