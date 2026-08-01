# Task — Fresh persistent public Shadow production restart

**Status:** ACTIVE

**Task kind:** EVIDENCE_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `d4740d6a181efebc8dad6d1091a78fa44d885957`

**Target branch/PR:** `codex/persistent-shadow-runtime-workbench-repair`, PR #9 against `main`

## Terminal-goal delegation

The user's 2026-08-01 instruction `部署重启上线` authorizes one bounded sequence inside this
closure: append this authority-only activation to PR #9 without force; independently verify its
exact commit and CI; mark the PR ready and merge it; bind the resulting exact remote `main`
commit/tree and frozen runtime, Policy, and service-contract bytes into one fresh deployment
envelope; install one new launchd service and one read-only periodic probe; invoke exactly one
production-public `serve-shadow` process; commission the loopback workbench; and observe it
read-only until the user explicitly says `停止` or the process reaches terminal failure.

The fresh root is `/Users/logan/Optimatrix-public-shadow-observation-002`. The consumed root
`/Users/logan/Optimatrix-public-shadow-observation` and its repo, state, deployment, probe, logs,
plists, receipts, and evidence remain immutable and are never reused, overwritten, migrated,
completed, or relabelled. The new labels are `com.optimatrix.public-shadow.r2` and
`com.optimatrix.public-shadow.r2.probe`; the workbench binds only `127.0.0.1:8765`.

On a later explicit `停止`, the controller first unloads and confirms the periodic probe is gone,
makes exactly one final-online probe attempt, then sends exactly one label-bound `SIGINT`, waits at
most 120 seconds for terminal publication, and performs one separate terminal audit. Probe failure
never delays or retries the stop. A seal timeout is reported as a blocker and never causes a second
signal. If commissioning fails after the service has started, the probe is not loaded: the
controller records the failed commission, sends exactly one label-bound `SIGINT` to the r2 service,
waits at most 120 seconds, and performs one terminal audit without a final-online probe or second
signal. A startup, commission, or process failure consumes this attempt and authorizes no automatic
or manual retry, alternate root, second invocation, or repaired evidence interval.

This task remains `ACTIVE` for the full observation. Successful deployment and commissioning are
an online milestone, not task completion. The task may be completed and removed only after an
explicit stop or terminal failure is sealed, the terminal audit is published, and `CURRENT_STAGE`
records the exact result and returns live commands to disabled.

This delegation does not authorize runtime/package/contract/Policy changes, result-dependent
extension, private/account access, credentials, orders, fills, capital, execution, Internet
binding, qualification, promotion, or claims about Policy quality, opportunity frequency, PnL, or
indefinite uptime.

## Business closure

**Given:** the operability and trader-workbench repair is independently accepted at exact commit
`d4740d6a181efebc8dad6d1091a78fa44d885957`, tree
`d5776f4f7c30763d095e36c7ea8b67209ec76448`, with service-contract digest
`sha256:4f94e8b8a8ddc1acbcd2c8eca47b4c0294f308500d21435c545346fba73971a7`.

**When:** the exact merged activation candidate launches one public-only persistent service from a
new external state root, exposes its immutable version-2 loopback projection, and records a fresh
external 60-second probe ledger from startup through the result-independent human stop boundary.

**Then:** a trader can inspect truthful current Radar, Underwriting, Shadow, Position, Outcome,
health, readiness, continuity, and publication facts while the service preserves one runtime
identity and append-only evidence. This startup commissions production operation but does not by
itself accept 24-hour continuity; that result remains pending until a later terminal audit.

**Independent verification:** a read-only verifier binds the activation merge, remote `main`, clean
checkout, exact argv/cwd/state root, labels, PID, loopback listener, contract and Policy digests,
runtime identity, lifecycle event, schema-version-2 endpoints, first successful probe, evidence
reader, and absence of a second invocation. The implementation author is not the sole verifier.

**Valid zero/no-hit/UNKNOWN result:** zero natural anomaly, Candidate, Entry, close opportunity, or
Outcome is `NOT_OBSERVED`; missing, stale, incomplete, or unavailable market facts remain
`UNKNOWN`, `NOT_EVALUATED`, or `N/A` as owned. These results do not stop, extend, retry, or tune the
service and do not prove business quality.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — accept the exact frozen repair and authorize exactly one
fresh production-public persistent-service invocation, one loopback workbench, one read-only probe,
and their result-independent stop protocol.

## Product operating behavior

One `radar_runtime serve-shadow` process owns the public Deribit transport, bounded in-memory Radar,
fixed-contract Underwriting/Shadow/Position/Outcome composition, append-only service evidence, and
immutable loopback projection. Same-process network reconnect is product behavior. launchd is only
a process host: the service has `KeepAlive=false`, `RunAtLoad=false`, and `LaunchOnlyOnce=true`, so
it cannot automatically restart or start after reboot. Its sole invocation is one explicit
`launchctl kickstart` without `-k` after every preflight binding passes.

The service is commissioned before the probe is loaded. Commissioning requires one exact PID,
argv and cwd; one loopback-only listener; one lifecycle sequence-1 event with matching code, Policy,
contract and runtime identities; `/healthz`, `/readyz`, and `/api/workbench/current` schema 2; and a
passing current evidence reader. Only then may the `RunAtLoad=true`, `StartInterval=60` read-only
probe be bootstrapped. Probe-ledger schema remains 1 and is distinct from endpoint schema 2.

## Validation harness

Before startup, publish one external deployment envelope under
`/Users/logan/Optimatrix-public-shadow-observation-002/deployment/`. It binds the exact merged
remote-main commit/tree, clean detached checkout, service contract digest
`sha256:4f94e8b8a8ddc1acbcd2c8eca47b4c0294f308500d21435c545346fba73971a7`, Radar Policy digest
`sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4`, Underwriting Policy
digest `sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af`, and Position Policy
digest `sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439`.
It also binds absolute argv/cwd/state root, script digests, port, labels, first-start predicate,
probe ordering, stop boundary, and the exact installed plist paths
`/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r2.plist` and
`/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r2.probe.plist` plus their digests,
mode, and owner. The state path must be absent before the sole invocation, absolute, repo-external,
non-symlinked, and owned by this attempt.

Preflight requires both new labels absent, both new installed plist paths absent, port 8765 free,
zero matching service processes, no fresh ledger/failure markers, and exact remote-main equality.
The old labels and old root must remain untouched. After commission, the first periodic probe must
be sequence 1, operationally successful, free of errors/failure markers, and within 120 seconds of
the service lifecycle start. Every later row freezes the same runtime identity.

The observation does not stop automatically at 24 hours. The user stop remains terminal. A future
24-hour gate can be `MET` only after the same runtime spans at least `86,400,000` ms with a complete
successful probe ledger, clean terminal, complete readers, and conservation. Until then it is
`PENDING`; stopping early or any predicate failure yields `NOT_MET`, never a retry.

## Contract

**Inputs and known-at rule:** before the first invocation, the deployment envelope freezes the
actual merged remote-main commit/tree, clean checkout, absolute command/cwd/state root, contract and
Policy byte digests, r2 labels/plists/scripts, free loopback port, absent state, absent labels, and
zero matching processes. Later observations never rewrite these bindings.

**Durable output and identity:** service evidence remains the frozen
`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE` identity. External deployment envelope, schema-1 probe
ledger, explicit probe-failure markers, logs, current audit, and terminal audit are validation
records, not business objects. The first lifecycle event creates one runtime identity that every
service, Radar, downstream, HTTP, probe, and audit fact must match.

**Missing/invalid/UNKNOWN semantics:** identity mismatch, dirty checkout, unexpected listener,
duplicate process, redirected state, malformed endpoint, evidence corruption, private endpoint, or
commission failure fails closed. `ready=false`, `UNKNOWN`, `NOT_EVALUATED`, `N/A`, and zero natural
opportunities remain truthful distinct states and never become a deployment or business success.

**Persisted meaning and compatibility:** no persisted business schema or contract changes in this
task. The immutable endpoint projection uses version 2 while external probe/audit records use
schema 1; neither substitutes for durable business evidence. Old and new observation roots are
distinct and never combined.

**Business denominators:** continuous-service duration is
`terminal.terminal_fact_boundary.received_monotonic_ms - lifecycle-sequence-1 recorded_monotonic_ms`
for exactly one runtime; the complete reader proves that terminal boundary equals the final
lifecycle event's recorded monotonic time.
Probe continuity requires sequence 1 within 120,000 ms of lifecycle start, contiguous ledger
sequence, no unledgered failure marker, no consecutive monotonic gap above 180,000 ms, and the
single final-online row within 180,000 ms before a user-request terminal. Endpoint success is
successful responses divided by recorded probe rows; a failed row or failure marker is never
silently omitted. The terminal audit is outside the probe denominator. Any failed predicate makes
the 24-hour gate `NOT_MET`; before terminal it remains `PENDING`. Business-object counts retain
their contract-owned denominators, and probe rows or elapsed time are never market opportunities.

## Evidence boundary

**Proves:** exact deployment identity; single-invocation lifecycle; public connectivity actually
observed; loopback workbench availability and fail-closed presentation; probe continuity actually
covered; current reader integrity; and natural events actually observed.

**Does not prove:** 24-hour continuity before terminal audit; indefinite uptime or reboot recovery;
universal market completeness; future opportunity frequency; Policy quality; forecast skill;
fillability; private account state; orders, fills, actual exposure, fees, realized PnL,
qualification, promotion, or execution safety.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED — frozen implementation plus activation checks |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE — natural occurrences are reported only |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** this task, `CURRENT_STAGE`, `README`, `SYSTEM_ARCHITECTURE`, direct authority tests, PR #9
activation and merge, fresh external repo/state/deployment/probe/log paths, two new launchd plists,
one service start, loopback commissioning, read-only observation, and one later clean stop.

**Out:** runtime/package/dependency/schema/contract/Policy edits; a second service start; automatic
restart; old-root mutation; evidence repair; Policy calibration; public Internet binding;
private/account APIs; credentials; margin; orders; fills; capital; actual execution; qualification;
promotion; databases; replay; and result-dependent stop changes.

**Owning module/artifact:** authority/task files and direct authority tests in Git; all deployment
artifacts live only under `/Users/logan/Optimatrix-public-shadow-observation-002` or the two new
launchd plist paths. Runtime source is immutable relative to the accepted repair commit.

## Acceptance

### Direct behavior

1. The activation diff from `d4740d6a181efebc8dad6d1091a78fa44d885957` contains only authority,
   task, README, architecture, and direct authority-test changes; runtime, packages, dependencies,
   service contract, and Policies are byte-identical.
2. The exact activation tip passes focused authority tests, `make check`, independent exact-commit
   review, non-force remote equality, CI, and merge; the deployment binds the resulting remote
   `main` commit/tree rather than the pre-merge branch identity.
3. Preflight and the deployment envelope satisfy every exact binding above before the state path or
   invocation exists.
4. Exactly one r2 service starts through `launchctl kickstart` without `-k`; it owns one exact PID,
   argv, cwd, state root, runtime identity, and `127.0.0.1:8765` listener.
5. Health, readiness and workbench endpoints return schema 2 and one identity. `ready=true` is valid
   only with HTTP 200 plus `RUNNING/CURRENT`; HTTP 503 plus `ready=false` remains an honest online
   but currently unavailable state.
6. The first periodic schema-1 probe is successful and identity-bound. A current audit reports
   `reader_verdict=PASS`, `PASS_CURRENT_INCOMPLETE`, `LIVE_INCOMPLETE_NO_TERMINAL`, and
   `business_acceptance=PENDING_LIVE` without treating that as 24-hour acceptance.
7. A commission failure never loads the probe and triggers exactly one r2 `SIGINT`, at most 120
   seconds of seal wait, and one terminal audit; a startup, commission, or process failure is
   terminal for this attempt and authorizes no retry or second signal.

### Required commands

- `make UV='python3 -m uv' sync`
- focused authority tests: `.venv/bin/pytest -q tests/test_authority_and_architecture.py`
- repository gate: `make check`
- production-public command, installed with absolute paths by launchd:
  `/Users/logan/Optimatrix-public-shadow-observation-002/repo/.venv/bin/python -m radar_runtime serve-shadow --state-root /Users/logan/Optimatrix-public-shadow-observation-002/state --workbench-host 127.0.0.1 --workbench-port 8765`
- current reader and current deployment audit from the exact merged checkout
- future clean-stop command after probe shutdown and one final-online probe:
  `launchctl kill SIGINT gui/501/com.optimatrix.public-shadow.r2`

### Real evidence

**Required:** YES

**Environment and stopping condition:** Deribit production-public sources only; the one service
continues until the user explicitly says `停止` or it fails terminally. Twenty-four hours is an
acceptance threshold, not an automatic stop or opportunity condition.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** report the exact deployment envelope, service/probe scripts and
plists, preflight receipt, probe ledger and failure-marker inventory, logs, current audit, and all
SHA-256 digests under `/Users/logan/Optimatrix-public-shadow-observation-002`; report the installed
r2 plist paths, owner, mode, and byte equality separately. Do not copy or modify an old artifact.

**Policy/contract identities:** report the exact service-contract and three Policy digests frozen
above, the merged commit/tree, runtime identity, lifecycle sequence, HTTP projection version, and
probe-record schema independently.

**Commit/PR:** report the activation commit/tree, PR #9 CI and merge state, resolved remote `main`
commit/tree, clean detached deployment checkout, and proof that runtime/package/contract/Policy
bytes equal the accepted repair.

**Unknowns and non-claims:** report readiness, currentness blockers, `UNKNOWN`, `NOT_EVALUATED`,
`N/A`, natural zeros, covered probe interval, and 24-hour `PENDING` without inferring Policy
quality, opportunity frequency, fillability, private/account truth, actual exposure, fees, PnL,
qualification, promotion, or execution safety.

## Definition of done

Deployment commissioning is complete when the activation is merged and exactly bound, the fresh r2
service is commissioned once, the first probe and current audit pass, the workbench is reloaded and
independently verified read-only, and no old artifact or private/order/fill surface is touched. The
task nevertheless remains `ACTIVE` while observation is live. Final task completion requires an
explicit stop or terminal failure, one sealed terminal audit, exact covered-interval and 24-hour
result reporting, and a same-change `CURRENT_STAGE` transition that disables live commands; no
business, Policy-quality, opportunity-frequency, fillability, or PnL claim follows.
