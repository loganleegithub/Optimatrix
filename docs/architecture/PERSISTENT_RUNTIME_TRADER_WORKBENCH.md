# Persistent public Radar/Shadow runtime and trader workbench

## Purpose and boundary

This design turns the existing modular monolith into one long-running public-only process without
creating a second trading engine. It deliberately reuses the accepted Deribit public client,
`LiveRadarRuntime`, sole `RadarReducer`, fixed-contract Shadow adapter, and
`FixedContractShadowOwner`.

The implementation is a review candidate. It does not authorize a live invocation or persistent
deployment. It adds no private/account source, order/fill path, capital authority, Policy update
surface, qualification claim, or execution control.

## Minimal composition

```text
external lifecycle supervisor
        |
        | starts/stops only
        v
SingleInstanceLease  -- one state root / one process
        |
        v
Persistent service host
  |-- one immutable three-Policy chain
  |-- one new runtime identity and run directory
  |-- one Deribit public WebSocket session at a time
  |       `-- reconnect -> higher session epoch
  |-- one LiveRadarRuntime
  |       `-- one RadarReducer (sole market/current-state owner)
  |              `-- one PersistentShadowRuntimeAdapter
  |                     `-- one FixedContractShadowOwner
  |-- append-only Radar / Shadow / service evidence
  `-- immutable snapshot reference
          `-- loopback-only read-only HTTP workbench
```

There is no database, broker, event bus, cache, second client, second reducer, replay calculator,
frontend strategy module, or background Policy optimizer.

## Process identity and single instance

Every startup computes a new content identity from the exact code identity plus a random nonce,
process id, and startup time. The runtime writes to:

```text
<state-root>/
  service.lock
  runs/<runtime-identity-without-prefix>/
    radar/
    downstream/
    service/
      events/
      terminal.json
```

`service.lock` uses a non-blocking advisory exclusive lock. It prevents duplicate scanners and
duplicate business owners for one configured deployment state root. A different state root is an
explicitly different deployment boundary; an operator or supervisor must not generate a fresh root
to bypass the lease.

The state root, lock, and `runs/` directory reject symbolic-link redirection; the lock must also be
a single regular file. These checks happen before the lock target can be truncated or a run/client
can be created.

Restart never reuses the preceding runtime identity or run directory. Historical objects retain
their original runtime and Policy meaning.

## Frozen Policy graph

Startup reads the exact Radar, Underwriting, and Position files once and validates their chained
content identities and shared quantity/currentness members before any runtime is constructed. The
same immutable `PolicyChain` object is given to the Radar reducer and Shadow owner.

The process has no file watcher, reload endpoint, mutable Policy reference, or supervisor tuning
callback. Changing a Policy requires a separately authorized stop and a new process/runtime
identity. Lack of anomalies or Candidates cannot extend a test, weaken a threshold, or select a
successor.

## Connection, continuity, and currentness

The host does not replace transport logic. The existing runtime remains authoritative for:

- Deribit heartbeat configuration and test-request responses;
- bounded ingress and one ordered reduction path;
- liveness deadline and queue-lag currentness;
- subscription acknowledgement, reconnect, resubscription, and retired epochs;
- option/combo catalog reconciliation;
- snapshot/change continuity and affected-scope recovery;
- trusted Deribit time, source staleness, and `UNKNOWN` propagation;
- clean-stop drain and outbound/terminal barriers.

The host catches only the existing reconnectable exception set, reports `RECONNECTING`, waits with
the existing bounded backoff, and opens the next session epoch. Protocol incompatibility,
evidence-integrity failures, and unexpected runtime failures are terminal.

## Lifecycle and state meanings

Service phase and data state are separate axes:

| Axis | Values | Meaning |
|---|---|---|
| Service phase | `STARTING`, `CONNECTING`, `RUNNING`, `RECONNECTING`, `STOPPING`, `STOPPED`, `FAILED` | Process/session lifecycle only |
| Data state | `CURRENT`, `DEGRADED`, `STALE`, `UNKNOWN`, `INTERRUPTED`, `STOPPED` | Reducer currentness and continuity |
| Health | live except terminal failure/stop | The process and HTTP loop are responsive |
| Ready | `RUNNING` + established session + `CURRENT` data | Suitable for current trader inspection |
| Stale | explicit stale/liveness/queue-lag condition | Connection existence does not imply current data |

`DEGRADED` is not calm and `UNKNOWN` is not zero. `RECONNECTING` is an interruption even if the OS
process and Web server remain live.

The displayed coverage percentage has one narrow basis: known current instrument evaluations
divided by monitored instrument evaluations in the current snapshot. A zero denominator is
`null`. It is not full-market coverage, opportunity success, forecast accuracy, or profitability.

## Graceful stop and terminal ownership

SIGINT or SIGTERM latches the first exact monotonic stop boundary and moves the lifecycle to
`STOPPING`. Repeated signals do not replace that boundary.

A stop latched before the first client seals the reducer's initial coverage epoch directly. It does
not manufacture a transport session, reconnect, continuity restart, positive-duration segment, or
business fact. Existing Radar summary validation remains unchanged.

If a real transport generation retires at its coverage-start instant, the service-only Radar
summary writer/reader accepts the omitted zero-duration leading epoch only after exact restart-chain
and first-segment trigger/blocker/scope matching. The standard Radar readers stay strict.

If a transport is active, `LiveRadarRuntime.run` performs its existing exact drain. Between
sessions, the host invokes the same reducer clean-stop path without opening a market client or
creating another session epoch. The reducer owns:

1. outbound barrier;
2. accepted-envelope drain;
3. final currentness and episode censoring;
4. Shadow Candidate/Position/Outcome terminalization;
5. Radar summary publication;
6. adapter finalization.

The persistent adapter writes exactly one service terminal record. It intentionally does not call
the bounded forward-cohort summary builder because a persistent process has no pre-bound enrollment
cutoff or final-stop manifest. Reusing the forward-cohort summary would falsely turn process
lifetime into an evaluation cohort.

Fatal failure uses the existing Shadow failure terminalization path and writes a failure lifecycle
record. A partial Radar evidence directory remains partial if the underlying runtime contract does
not permit a clean summary. Its current objects must still be unique, mutually bound, and no later
than the service terminal causal boundary.

## Append-only evidence boundary

Durable output is limited to:

- existing minimal Radar anomaly/atomic/summary objects;
- existing downstream Underwriting, Candidate, simulated Entry, Position, close-opportunity, and
  Outcome objects;
- minimal service lifecycle events and one terminal record.

No full option or combo order book is persisted. Contract-permitted consumed levels remain part of
entry/close audit objects. Service records contain runtime/code/Policy identities, phase changes,
terminal source, and non-claims; they contain no credentials, private account data, orders, fills,
or browser requests.

## Read-only projection architecture

Snapshot construction runs synchronously in the same event loop as the sole reducer. It reads the
current reducer, adapter indexes, and already settled downstream objects, then replaces one
immutable snapshot reference. HTTP handlers read that reference only; they never touch mutable
runtime state.

The browser receives one versioned JSON projection and renders it. It does not calculate IV,
baseline, richness, fees, reserves, Candidate validity, entry economics, close economics, PnL,
hard-close rules, or Outcome maturity. Unit/date formatting is presentation, not a decision.

### HTTP surface

| Method/path | Behavior |
|---|---|
| `GET`/`HEAD /` | Trader-flow page |
| `GET`/`HEAD /app.js` | Static renderer |
| `GET`/`HEAD /styles.css` | Static styles |
| `GET`/`HEAD /api/workbench/current` | Current immutable snapshot |
| `GET`/`HEAD /healthz` | Process liveness |
| `GET`/`HEAD /readyz` | Current-data readiness |
| any mutation method | `405 Method Not Allowed` |

The server accepts only loopback hosts. Responses disable caching, MIME sniffing, framing, external
content, and cross-origin data dependencies. There is no form, button, write route, WebSocket from
the browser, private endpoint, or order action.

## Trader-flow field ownership

### System status

Runtime identity, exact Policy identities, service/session state, platform readiness, coverage
state/blocker, latest accepted market timestamp, delay, last-wire age, reconnect/session-gap count,
and bounded disconnect attribution come directly from runtime state and diagnostics.

### Radar

Instrument, expiry, TTE, type, strike, executable sell price/IV interval, causal baseline,
richness interval, detector state/reason, official atomic combo state, episode identity/start, and
active duration come from the reducer's current accepted evaluation. Missing calculation members
remain `null`.

### Underwriting

Availability, action, executable gross/net credit, contract payoff loss, fee reserve, future-cost
reserve, underwriting reserved loss, exact Policy reserve components, Candidate lifecycle, and
invalidation reason come from owner-settled objects and immutable Policy fields. The current
contract does not separately persist a failed economic-predicate vector, gamma reserve, or slippage
reserve; the workbench says so rather than reconstructing them.

### Simulated Shadow entry

Candidate boundary, official combo refresh terminal state, consumed entry levels, simulated credit,
target quantity, Entry identity, and no-entry reason come from Candidate/admission/Entry objects.
Every row carries `模拟入场，不是订单或成交`.

### Position and close

`HOLD`/`CLOSE`/`UNKNOWN`, atomic close quote state, contract-permitted close debit and projected
Shadow PnL, hard-close boundary/countdown, latched exit rules, close-opportunity eligibility/reason,
selected Shadow close opportunity, and Outcome state come from Position/close/Outcome objects plus
the frozen Position Policy. PnL is never rebuilt from component legs or mark/mid.

### Outcome

Mature-known, mature-unknown, censored, or pending status is a direct presentation of the contract
terminal state. Public-fee-reserved counterfactual economics, selected exit, censor mask, and
actual-value unavailability are shown without implying a fill or actual exposure.

## External supervisor boundary

A future authorized deployment may use launchd, systemd, Docker restart policy, or another simple
process supervisor. That supervisor may start, stop, restart after failure, and collect stdout. It
must not edit Policy files in place, create alternate state roots to evade the lease, query private
accounts, change thresholds, extend an evidence window, interpret no opportunity as failure, or
promote any Policy.

No supervisor unit is included in this implementation because deployment authority is separate
from process capability and platform choice.

## Non-claims

This implementation does not establish indefinite uptime, edge, forecast accuracy, profitability,
fill likelihood, actual fees, actual PnL, private-account correctness, qualification, promotion, or
execution permission. The workbench is an operational view of the current public-only runtime, not
an independent source of trading truth.
