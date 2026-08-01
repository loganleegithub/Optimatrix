# Task — Persistent public Shadow service observation

**Status:** ACTIVE

**Task kind:** EVIDENCE_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `70185e8b7b7b5066c5148c1763947011b8508ea8`

**Target branch/PR:** `codex/persistent-public-shadow-observation`, Draft PR against `main`

## Terminal-goal delegation

The user's 2026-08-01 instruction `部署上线，开始观察` authorizes one bounded sequence inside this
closure: publish and independently verify this authority gate; merge it; bind the resulting exact
remote `main` commit/tree and immutable Policy/contract identities into one deployment envelope;
install exactly one local launchd service and one read-only periodic probe; start exactly one
production-public `serve-shadow` invocation; commission its loopback workbench; and observe it
read-only until the user explicitly says `停止` or the process reaches a terminal failure.

On `停止`, the controller first unloads the periodic probe, makes exactly one final-online probe
attempt, then sends exactly one label-bound `SIGINT`, waits up to 120 seconds for terminal
publication, and performs a separate terminal audit that is not a probe-ledger row or HTTP-success
denominator. Final-probe failure is recorded, makes the 24-hour gate `NOT_MET`, and never delays or
retries the stop. A seal timeout is reported as a blocker; it never causes a second signal. A process
failure consumes this attempt and authorizes no automatic or manual retry. This delegation does not
authorize a second invocation, result-dependent extension, Policy tuning, private/account access,
credentials, orders, fills, capital, execution, Internet binding, or promotion.

## Business closure

**Given:** the persistent public Shadow service/workbench offline implementation is independently
accepted at commit `67085248fffb1b20bae1c9512ae1191d166a6509`, tree
`9f5ded618fb5fe803fd8e8b2ffa533f0b49268aa`, under service-contract digest
`sha256:9c3b46eae8b646d2c86f38df35cfcf962605c0b670385376d7c2ebef3a771778`.

**When:** one exact merged activation candidate launches one public-only persistent service from a
fresh external state root and a loopback-only workbench, while an external read-only probe records
its current operational facts until the result-independent human stop boundary.

**Then:** the trader can inspect current Radar, Underwriting, Shadow, Position, Outcome, health,
readiness, continuity, and publication freshness without any control surface; the service preserves
one runtime identity and append-only evidence until one clean stop or truthful terminal failure.
After clean stop, a separate gate reports whether the same runtime supplied at least 86,400,000 ms
of continuous service observation and whether complete-reader/conservation predicates pass.

**Independent verification:** a read-only verifier binds the activation merge, remote `main`, clean
worktree, exact argv/cwd/state root, launchd label, PID, loopback listener, Policy and contract
digests, runtime identity, HTTP projections, 60-second probe ledger, service lifecycle, Radar and
downstream evidence, and terminal conservation. The implementation author is not the sole
candidate verifier.

**Valid zero/no-hit/UNKNOWN result:** zero natural anomaly, Candidate, Shadow Entry, close
opportunity, or Outcome is `NOT_OBSERVED` and does not trigger extension, restart, or tuning.
Missing, stale, discontinuous, unready, zero-denominator, or unavailable facts remain `UNKNOWN` or
the owning unavailable enum. They do not satisfy market-data currentness or any current-market
coverage metric. They remain separately reported but do not remove elapsed time from the 24-hour
service-running-and-trader-observability gate while the single process, probe, `/healthz`, and
workbench API predicates remain satisfied; they do not by themselves falsify service integrity.

**Upstream prerequisite:** the exact offline implementation acceptance above is established and
merged in PR #7. No runtime source repair is permitted in this task.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — activate exactly one
`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_OBSERVATION` using the command, state root, loopback surface,
supervisor behavior, read-only probe, and stop boundary declared here. Permission returns to live
commands forbidden after terminal acceptance is recorded.

## Product operating behavior

One `radar_runtime serve-shadow` process owns the public Deribit transport, bounded in-memory Radar,
fixed-contract Underwriting/Shadow/Position/Outcome composition, append-only non-cohort service
evidence, and immutable loopback workbench projection. Same-process network reconnect is product
behavior. launchd is only a process host: `KeepAlive=false`, `RunAtLoad=false`, and
`LaunchOnlyOnce=true`, so a terminal process cannot be kicked off again during this boot and a host
reboot does not start it. The first process starts through one explicit `launchctl kickstart`
without `-k` after all preflight bindings pass.

The service continues across ordinary no-opportunity updates and truthful `UNKNOWN` intervals.
Only existing minimal anomaly, atomic-quote, downstream, lifecycle, and terminal objects are
durable. Full books, ordinary no-anomaly rows, browser state, HTTP requests, and probe data are not
business evidence. The workbench remains `GET`/`HEAD` only on `127.0.0.1:8765`; it cannot recompute
strategy facts, edit Policy, access accounts, or send an order.

## Validation harness

Before startup, publish one external deployment envelope under
`/Users/logan/Optimatrix-public-shadow-observation/deployment/` containing the exact merged
activation commit/tree, remote-main equality, clean worktree, service contract and three Policy
digests, absolute argv/cwd/state root, launchd plist/script digests, port, labels, start predicate,
and stop boundary. The state root
`/Users/logan/Optimatrix-public-shadow-observation/state` must be absent before commissioning,
absolute, repo-external, non-symlinked, and owned by this one attempt.

The service launchd label is `com.optimatrix.public-shadow`; `KeepAlive=false`, `RunAtLoad=false`,
and `LaunchOnlyOnce=true`, and its one explicit kickstart is the sole authorized invocation. The
probe label is `com.optimatrix.public-shadow.probe`; it may only read process metadata, loopback
HTTP, and evidence inventory and append one compact JSON object approximately every 60 seconds to
the external probe ledger. It cannot signal, restart, mutate evidence, call Deribit, or decide
acceptance.

Each probe row has schema version 1, one contiguous ledger sequence, UTC wall time, monotonic
milliseconds, exact launchd label/PID/argv/cwd, process count/CPU/RSS/elapsed time, loopback endpoint
HTTP statuses, parsed JSON health/readiness/runtime/publication facts, expected-versus-observed
runtime identity, and read-only evidence file/count/byte inventory. One exclusive file lock guards
one `O_APPEND` write plus `fsync`; a failure is still one explicit failed row, never a missing zero.
The first successful row freezes the runtime identity for every later row. Probe shutdown must
finish before the manual final-online probe, so no periodic row can race with stop.

The observation does not stop automatically at 24 hours. The user stop remains the terminal
boundary. The 24-hour gate is `MET` only after the same runtime spans at least `86,400,000` ms from
its first lifecycle monotonic fact to the clean-stop terminal boundary, with no second service
invocation, the first probe within 120 seconds of startup, the final probe within 180 seconds of the
terminal, no consecutive probe gap above 180 seconds, exactly one service instance plus successful
`/healthz` and workbench API responses in every recorded probe, and the complete evidence reader
passing. `/readyz` may truthfully be unavailable during `UNKNOWN` or degraded market data and is
reported separately. If the user stops earlier or any predicate fails, report
`24_HOUR_CONTINUOUS_PUBLIC_SERVICE_SAMPLE = NOT_MET` and accept only the actually covered interval.

## Evidence boundary

**Proves:** exact deployment identity; one-invocation service lifecycle; public connectivity facts
actually observed; loopback workbench availability and fail-closed presentation; covered runtime,
probe, continuity, publication, evidence-integrity, clean-stop, and conservation facts; natural
events actually observed.

**Does not prove:** indefinite uptime; reboot or power-loss recovery; universal market completeness;
future opportunity frequency; Policy quality; forecast skill; fillability; private account state;
orders, fills, actual exposure, fees, realized PnL, qualification, promotion, or execution safety.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED — accepted frozen implementation plus activation-candidate checks |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE — natural occurrences are reported only |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** this task and `CURRENT_STAGE`; authority tests; exact activation PR; external deployment
envelope, launchd plists, read-only probe, logs, fresh state root, one service start, loopback browser
commissioning, read-only observation, one later clean stop, and terminal acceptance record.

**Out:** runtime/package/schema/contract/Policy edits; dependency changes; a second service start;
automatic restart; reuse or deletion of evidence; Policy calibration; public Internet binding;
private/account APIs; credentials; margin; orders; fills; capital; actual execution; qualification;
promotion; databases; full-feed capture; replay; and result-dependent stop changes.

**Owning module/artifact:** `docs/authority/CURRENT_STAGE.md`, this task, direct authority tests, and
the exact external deployment/evidence paths declared above. Runtime source is immutable.

## Contract

**Inputs and known-at rule:** the post-merge deployment envelope freezes exact remote `main`
commit/tree, clean checkout, absolute command and cwd, service-contract digest, three Policy paths
and byte digests, launchd configuration digests, unused loopback port, new state root, and absence of
a conflicting process before the first start. Facts observed later never rewrite those bindings.

**Durable output and identity:** existing
`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE` run-segment lifecycle/terminal evidence plus the
external deployment envelope, 60-second probe ledger, launchd/stdout/stderr logs, and final
acceptance record. The runtime identity is created once by the accepted service and binds all
service, Radar, downstream, and workbench facts.

**Missing/invalid/UNKNOWN semantics:** any identity mismatch, dirty checkout, unexpected listener,
duplicate service process, redirected state path, evidence corruption, private endpoint, or
non-loopback workbench blocks startup or fails the attempt closed. During observation, HTTP/probe
failure is `UNKNOWN` and cached browser business rows are hidden. A terminal process is consumed and
not retried.

**Persisted meaning and compatibility:** service evidence remains exact semantic identity
`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`, digest
`sha256:9c3b46eae8b646d2c86f38df35cfcf962605c0b670385376d7c2ebef3a771778`, and
`NOT_COMPARABLE` to a bounded forward cohort. External deployment/probe artifacts are validation
records, not business objects or compatible substitutes for service evidence.

**Business denominators:** continuous-service duration is milliseconds between the first service
lifecycle monotonic fact and the terminal fact for one runtime identity. Probe endpoint success is
successful responses divided by scheduled probe records; a missing probe is not silently zero.
Business-data `UNKNOWN` duration is reported separately and never counted as known-current market
coverage, even when the operational 24-hour service/workbench predicate remains met.
Radar, Underwriting, Candidate, Entry, Position, and Outcome counts and rates retain their existing
contract-owned denominators and null behavior. Probe rows, HTTP requests, files, and elapsed checks
are never market opportunities.

## Acceptance

### Direct behavior

1. The activation diff contains only authority/task/tests; runtime, dependencies, contracts, and
   Policies equal merged PR #7 bytes.
2. Before startup, exact remote-main equality, clean worktree, contract/Policy hashes, new
   non-symlink state root, free port, absent service label, and zero conflicting service processes
   pass independently.
3. Exactly one launchd service starts through `launchctl kickstart` without `-k`, with
   `KeepAlive=false`, `RunAtLoad=false`, and `LaunchOnlyOnce=true`; one PID has the registered
   argv/cwd, one listener is loopback-only, and lifecycle/runtime identities match the deployment
   envelope.
4. `/healthz`, `/readyz`, and `/api/workbench/current` expose truthful independent facts; the
   browser shows Radar, Underwriting, Shadow, Position, Outcome, system, freshness, empty, and
   `UNKNOWN` semantics with no control or private surface.
5. The read-only probe appends approximately every 60 seconds without writing the service state
   root. Ordinary `UNKNOWN`, zero natural opportunities, or unready intervals do not stop, extend,
   restart, or tune the process.
6. On explicit `停止`, unload and confirm the periodic probe is gone, make one final-online probe
   attempt, then run exactly
   `launchctl kill SIGINT gui/501/com.optimatrix.public-shadow`. Wait at most 120 seconds for seal;
   do not delay the stop, retry the probe, or send a second signal if that probe or seal fails. A
   later separate terminal audit must publish one terminal, a clean Radar summary, complete
   downstream evidence, and met conservation before covered-interval or 24-hour acceptance is
   calculated; that audit is outside the probe denominator.
7. A fatal/process failure is truthfully terminal, consumes this attempt, and authorizes no retry.

### Required commands

- `make UV='python3 -m uv' sync`
- focused authority tests: `.venv/bin/pytest -q tests/test_authority_and_architecture.py`
- repository gate: `make check`
- production-public command, installed with absolute paths by launchd:
  `/Users/logan/Optimatrix-public-shadow-observation/repo/.venv/bin/python -m radar_runtime serve-shadow --state-root /Users/logan/Optimatrix-public-shadow-observation/state --workbench-host 127.0.0.1 --workbench-port 8765`
- live current reader: `read_current_persistent_service_evidence(...)` from the merged project
  virtualenv using the exact runtime bindings from the first lifecycle event
- clean-stop command after the probe shutdown/final-online sequence:
  `launchctl kill SIGINT gui/501/com.optimatrix.public-shadow`
- post-stop reader: `read_complete_persistent_service_evidence(...)` plus the existing strict Radar
  and downstream complete-reader/conservation validators using the same exact bindings

### Real evidence

**Required:** YES

**Environment and stopping condition:** Deribit production-public sources only; one service process
continues until the user explicitly says `停止` or it fails terminally. Twenty-four elapsed hours is
an acceptance threshold, not an automatic stop or opportunity condition.

**Required report:** activation/main/deployment/runtime identities; exact invocation count and stop
mode; loopback/listener and trader-view checks; probe coverage; lifecycle and evidence integrity;
covered duration; Radar/Underwriting/cohort conservation; natural anomaly/Candidate/Entry/close/
Outcome observations; `UNKNOWN`s; 24-hour gate; and every non-claim above.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** exact post-merge deployment envelope, launchd plists, probe script,
probe ledger, logs, state root/run directory, and final acceptance record are recorded before their
relevant action and reported with SHA-256 where immutable.

**Policy/contract identities:** Radar
`sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4`;
Underwriting `sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af`;
Position `sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439`;
service contract
`sha256:9c3b46eae8b646d2c86f38df35cfcf962605c0b670385376d7c2ebef3a771778`.

**Commit/PR:** append-only non-force branch and Draft PR; activation must be independently verified,
pushed, green, ready, and merged before deployment. Exact deployment commit is the resulting remote
`main` merge commit, recorded in the external envelope before first start.

**Unknowns and non-claims:** natural opportunities may remain `NOT_OBSERVED`; permanent 24x7,
restart/reboot recovery, performance, strategy quality, and every execution claim remain unproved
unless the later exact evidence says otherwise. The operational 24-hour gate never claims 24 hours
of known-current market data; `UNKNOWN` market-data duration remains explicit.

## Definition of done

The activation is merged; one exact public-only service and read-only probe are running from the
bound deployment envelope; loopback trader observability is independently commissioned; and the
task remains active during observation. Final closure occurs only after the user stop or a terminal
failure is sealed and independently evaluated. A clean interval shorter than 86,400,000 ms may be
accepted only for its covered operation and must record the 24-hour gate `NOT_MET`.
