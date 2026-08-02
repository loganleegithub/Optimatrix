# Task — R4 commissioning integrity repair and fresh service boundary

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED — repo-owned commissioning/stop controller plus each exact
observed R4 owning-module repair declared below; market inputs, decision semantics, contracts,
dependencies, and three Policies remain unchanged

**Live commands:** REQUIRED — conditional terminal-goal delegation only after exact-candidate
acceptance, remote equality, GitHub CI, merge to remote `main`, and a fresh independently verified
R4 deployment preflight

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `f66fa97b66487cf593d5265a8ac79d013adda104`

**Target branch/PR:** one bounded branch/PR at a time; initial repair
`agent/r4-commissioning-integrity-repair`, iterative repairs `agent/r4-lsof-field-repair` and
`agent/r4-resource-log-classification-repair`, and current CPU repair
`codex/r4-workbench-publication-cpu-repair`, followed by exact log-observer repair
`codex/r4-log-observer-self-record-repair` and final advisory resource-observation repair
`codex/r4-remove-unified-log-gate`, which also owns the subsequently observed attempt-005 evidence
filename repair; no force push, history rewrite, main merge into a task branch, or live mutation
before exact-candidate acceptance

## 2026-08-02 R4 iterative recovery amendment

The user's direct instruction supersedes every older clause in this task that limits R4 to one
commissioning invocation, prohibits repairing R4 after a failed invocation, or requires a new
R-number. R4 attempt 001 is immutable and terminally quiescent: primary receipt SHA-256
`55b78cf3b4474949747efdd2b021ff7e039b5cc578afa5ea5b9357faca1e8f8f`, final closure SHA-256
`214ad3e29b3b66bffa54e5eb277a1ae4db0632b34dee72f590040a06b2d1c848`, terminal audit SHA-256
`7c8c7696a2150a57ef6ca772ff0d2bcab6bd88421270332f334fd418eda249d6`, and status
`COMMISSION_FAILED_TERMINAL_AUDITED_QUIESCENT`. It failed because real macOS `lsof -F` emits the
always-selected `f` field while the listener parser and test fixture modeled only `p/n`.

R4 attempt 002 is also immutable and terminally quiescent: primary receipt SHA-256
`1104318b552b3fd2878ca5b3d81ae7d835aac448ba8240a620a41bcc1e18c6c5`, final closure SHA-256
`a95824e3a633750a903395bf3cf4da61544fa7a87244f34ab2e5c21080ff9696`, terminal audit SHA-256
`68a798c7e9558c3a82a1e5c2043a4582729af20506e0bacbbff3c8423d44a2c2`, and status
`COMMISSION_FAILED_TERMINAL_AUDITED_QUIESCENT`. It used envelope identity
`sha256:1f143560025fd03adbcf44c8c0df795d9595b568051b4adedac4f1562d7c6199` and runtime identity
`sha256:1711deeac5701ee996c63529e4e6b770a0212ac6375dfb7be1c81f66364cb126`. Its four
contract-valid operational probe rows were falsely assigned one CPU resource event each because a
normal RunningBoard message contained the exact service PID and `resource coalition id`, but no
CPU-resource condition. The minimal repair requires an exact-PID unified-log row to contain both
`cpu` and `resource`, or the explicit phrase `burning cpu`; real CPU-resource messages and
diagnostic reports remain gating.

For each observed R4 implementation defect: preserve the failed attempt byte-for-byte under a
numbered R4 archive; add the smallest direct red/green fix in the owning module; run focused and
full repository gates; independently accept, push, pass CI, and merge the exact candidate; then
rematerialize the canonical R4 root/labels with fresh outputs and invoke `commission` once. Repeat
only until one R4 attempt reaches `COMMISSIONED`; leave that process online for read-only
observation. This authorizes no blind retry, parallel attempt, Policy or business-semantic change,
private/account access, order, fill, capital, qualification, promotion, public binding, or reboot
auto-start.

## 2026-08-02 R4 continuous-observation CPU amendment

The user's direct instruction also authorizes stopping, repairing, and recommissioning R4 when
continuous read-only observation finds an implementation defect after the bounded commissioning
gate. Attempt 003 was cleanly stopped and terminally sealed after macOS generated an exact-PID
`cpu_resource` diagnostic for PID 18470: 90 CPU seconds over 160 seconds, 56% average, above the
50%/180-second system threshold. This is an operational failure even though health, readiness,
Coverage, API projection, and browser rendering remained internally consistent.

The minimal repair may change only redundant runtime work. An Underwriting scope that already made
its one active-to-inactive transition is not reevaluated on every later unrelated fact; its settled
facts remain retained for evidence and display. Structurally unchanged workbench metadata and
top-level JSON members may reuse immutable cached bytes, while every settled fact still produces
one complete, byte-immutable, schema-2 snapshot with an advancing publication sequence. The repair
must not coalesce facts, change publication cadence, alter a fact boundary, remove settled evidence,
change a business enum/value/order, or amend a Policy, input, Outcome, HTTP, or stage contract.

The same loop also exposed one observer-only false event after attempt 004 commissioned normally.
macOS recorded a manual `/usr/bin/log show` query as a `com.apple.log` row whose command text
contained the exact runtime PID and CPU-resource search terms. The first minimal controller repair
excluded only rows whose `processImagePath` and `sender` are both `/usr/bin/log` and whose subsystem
is `com.apple.log`; it retained every other existing resource gate.

## 2026-08-02 R4 advisory resource-observation amendment

The user's subsequent instruction to avoid over-design and finish the solution in one implementation
round supersedes the requirement that host resource observations remain gating. The final minimal
controller repair removes `/usr/bin/log show` from preflight, periodic probes, final-online probes,
and the bounded operability audit. CPU, RSS, and DiagnosticReports are advisory facts only; they
remain recorded but do not determine `COMMISSIONED` or the 24-hour result. Queue-lag transition
counts retain the same advisory treatment. CPU above 50%, unreadable DiagnosticReports, positive
exact-PID report counts, and positive queue-lag transition counts are accepted and recorded. The
receipt/probe schema remains unchanged, and `unified_log_row_count_examined` is retained and
truthfully fixed at `0`. Well-typed facts and CPU-percentage consistency remain evidence-integrity
requirements: inconsistent CPU percentages, negative counts, and nonzero
`unified_log_row_count_examined` remain invalid evidence. PID, argv, cwd, launchd runs, listener,
HTTP/schema/current-reader, probe continuity, fatal process evidence, terminal-before-bootout, and
quiescence remain direct hard gates. No new module, endpoint, process, dependency, container,
automatic restart, warning type, business rule, Policy, or contract is authorized.

## 2026-08-02 R4 attempt-005 evidence publication amendment

Attempt 005 commissioned from merged commit `1993bc21566909310d7affea03c1c8a83d58fa9d`, then ran
`6644024` ms with 107 contiguous successful probe rows before a valid atomic-quote evidence write
terminated the process. Its legal 230-byte final filename was copied into a temporary basename and
extended with a UUID to 268 bytes, exceeding macOS `NAME_MAX=255`. `EvidenceError` inherits
`ValueError`, so both subscription dispatch boundaries then misclassified the local evidence
failure as a public combo-book payload incompatibility. The bound natural-terminal stop completed
with `NATURAL_TERMINAL_AUDITED_QUIESCENT`; the terminal reader records
`PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY`, `NOT_ACCEPTED_PROCESS_FAILURE`, and 24-hour
`NOT_MET`. The attempt root and installed plists are preserved as numbered attempt-005 archives.

The minimal repair may replace only the temporary basename with a short same-directory
`.evidence-{uuid.hex}.tmp` name,
retaining the existing exclusive-create, fsync, hard-link, cleanup, directory-fsync, duplicate,
final-name, and payload semantics. `EvidenceError` must pass unchanged through both subscription
dispatch boundaries without contaminating source-shape diagnostics. This authorizes direct
regressions in the owning Radar evidence writer and runtime reducer only; it changes no market
shape, business event identity, public protocol, Policy, contract, schema, cadence, dependency,
process, endpoint, or deployment topology.

## 2026-08-02 R4 attempt-006 commissioned observation amendment

Attempt 006 reached `COMMISSIONED` from merged remote `main` commit
`1b10ecb3336c9b342e5ddb306ecbb9170c211d70`, tree
`97f7f257979ab8e1613714f1bcded14f2f2e48cb`, envelope identity
`sha256:00f5a2ec633af5bf24543b9b3daee310b96620773a51659eea021ee580d14bbe`, and runtime identity
`sha256:9b5772ce0b3aa0aa0773533fbec1eaf8af90edd9d0971b2e3b9d0aaf0a2be364` under PID `91781`.
Its immutable commissioning receipt SHA-256 is
`ec5b85b19c4dff646d5209b4dce4add05ca8b5b7e12a0ab792455e6b9ff454f3`.
The gate covered `180000` ms with `18/18` successful HTTP attempts, zero queue-lag transitions,
zero exact-PID CPU resource events, and one launchd run. CPU and RSS remain advisory facts.

The exact runtime remains online for read-only observation and its 24-hour result is `PENDING`.
The iterative repair/recommissioning authority is consumed. Until the result-independent terminal
boundary, this task authorizes only read-only monitoring; at that boundary it authorizes the one
existing stop/terminal invocation already declared below. It authorizes no further implementation
repair, recommissioning, restart, alternate process/root/label/port, Policy change, contract change,
or workbench publication-cadence change.

## Business closure

**Given:** the sole R3 commissioning attempt is consumed. Its immutable primary receipt has SHA-256
`1fbe3b4daacdc26d6ca0a0ec2f46108fa355c7b8d62f698e09e7c85a7b5d25cd`, envelope identity
`sha256:41806d81ea9182f288f0a78925887c898a4cf2ee15420affb44d5e4934cd3e5c`, runtime identity
`sha256:a5a6571345b161fbad37f594626cee921614ae84ffdd776e58ae360d279f9be1`, and the pre-cleanup
status `COMMISSION_FAILED_CLEANUP_REQUIRED`. Its immutable complete terminal audit has SHA-256
`8c78722020b3e8b6c54140bb1a54ca30e2c86719e1ae9ef5e3f01a89625e08a1`; it records
`PASS_COMPLETE_CLEAN_STOP`, `CLEAN_STOP_COMPLETE`, `181274` ms of covered service, one valid
contiguous probe row, two explicit failed-probe markers, and
`OPERATIONAL_24H_GATE_NOT_MET`. Independent host inspection records both R3 labels absent, no
matching process, and no listener on `127.0.0.1:8765`. The R3 root, labels, plists, journals,
receipts, probe evidence, runtime, and attempt are sealed and may not be edited, restarted,
relabelled, repaired in place, or reused.

**When:** one bounded R4 implementation repairs the verifier's legal zero/unknown projection
semantics, replaces immediate launchd post-`bootout` assertions with bounded monotonic convergence,
separates the durable pre-cleanup failure fact from an immutable final cleanup conclusion, migrates
the controller to an entirely fresh R4 root/label/envelope boundary, passes focused tests and full
`make check`, receives independent exact-candidate review, reaches remote equality and passing
GitHub CI, and is merged to remote `main`. The final implementation also removes the recursive
Unified Log text gate while retaining CPU, RSS, queue-lag, and DiagnosticReports as advisory facts.

**Then:** each newly rematerialized R4 attempt may invoke `commission` once, and an observed
implementation defect may follow the iterative recovery amendment above until one attempt reaches
`COMMISSIONED`. A legitimate
schema-2 workbench projection cannot fail commissioning merely because an honest `UNKNOWN` claim
preserves a known zero or positive denominator, or because a positive numerator has an unavailable
denominator. A `launchctl bootout` success is followed by bounded observation of label and host
quiescence rather than an instantaneous assumption. Every post-start failure first writes an
immutable pre-cleanup receipt and later writes exactly one distinct final closure receipt proving
either audited quiescence or a specific blocked cleanup; neither receipt is rewritten. Successful
commissioning establishes only the same bounded 180,000 ms operability gate and begins read-only
observation; it does not establish 24x7 stability, Policy quality, opportunity frequency,
fillability, or PnL.

**Independent verification:** review the exact R4 candidate and its parent/tree; recompute every
changed-file digest; prove the exact CPU hot-path repair preserves publication cadence, contracts,
Policies, dependencies, and business schema/values; run focused tests and `make check`; verify
remote branch equality and GitHub CI; after merge,
independently recompute the detached deployment checkout, fresh envelope, plists, wrapper bytes,
old-root inventories, label/listener absence, and exact R4 output freshness before any live command.
The verifier must not rely on the controller's own receipt as its sole source of truth.

**Valid zero/no-hit/UNKNOWN result:** `UNKNOWN/value=null/numerator=0` with denominator `null`, `0`,
or a positive integer is valid when the producer cannot prove numeric zero. `NOT_ZERO` requires a
positive value equal to the positive numerator but permits an unavailable denominator; when a
denominator is known it must be positive and not smaller than the numerator. `PROVEN_ZERO` requires
value and numerator zero plus a positive denominator. These are projection-integrity rules, not a
change to Radar, Underwriting, Candidate, or Outcome economics. Zero natural Candidate, Entry,
close-opportunity, or Outcome remains valid and does not fail commissioning.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — consume and close R3; authorize this bounded R4
controller repair, exact-candidate acceptance sequence, and iterative repair/recommission attempts
under the 2026-08-02 amendment until one attempt is `COMMISSIONED`, plus result-independent
stop/terminal closure. No private, account, margin, order, fill, capital, execution, qualification,
promotion, unattended retry, reboot auto-start, or alternate label/port authority is granted.

## Product operating behavior

The `serve-shadow` market/service hot path changes only by the exact redundant-work repair declared
above and still does not import the commissioning controller. It continues to consume every
production-public Deribit fact, write append-only public Shadow evidence, and publish one immutable
GET/HEAD-only loopback projection per settled fact. The controller remains sibling deployment
tooling: it validates bound artifacts and host facts, controls one exact launchd lifecycle, records
attempt-scoped evidence, and never recomputes strategy decisions or mutates service evidence.

The fresh production boundary is exact:

- root: `/Users/logan/Optimatrix-public-shadow-observation-004`
- service label: `com.optimatrix.public-shadow.r4`
- probe label: `com.optimatrix.public-shadow.r4.probe`
- installed service plist:
  `/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r4.plist`
- installed probe plist:
  `/Users/logan/Library/LaunchAgents/com.optimatrix.public-shadow.r4.probe.plist`
- listener: exactly `127.0.0.1:8765`
- service: `KeepAlive=false`, `RunAtLoad=false`, `LaunchOnlyOnce=true`
- probe: read-only, `RunAtLoad=false`, 60-second interval, no service-control capability

The R4 envelope adds one fresh, distinct `failure_closure_receipt_path` inside the deployment root.
It also binds inventory identities for all consumed roots `r1`, `r2`, and `r3`; freezes
`r1_no_writer`, `r2_no_writer`, and `r3_no_writer`; freezes absence of all old labels; and records
the earlier observable facts `r4_root_absent_before_materialization`,
`r4_labels_absent_at_binding`, listener freedom, and installed-plist absence. The controller binds
the sole active R4 task rather than the deleted R3 task. All R3-specific executable constants,
production paths, error labels, wrapper sentinels, and CLI descriptions are replaced by R4 values;
historical prose remains historical only.

## Validation harness

The implementation must establish stable red tests before the minimal repair and retain them in the
final candidate. At minimum the direct suite proves:

1. The verifier accepts all producer-valid zero-claim shapes: honest `UNKNOWN` with denominator
   `null`, `0`, or positive; `NOT_ZERO` with a positive numerator/value and either unavailable or
   sufficient known denominator; and `PROVEN_ZERO` only with a positive denominator.
2. It rejects contradictions: `UNKNOWN` with a numeric value, negative or non-integer members,
   `PROVEN_ZERO` with zero/unavailable denominator, `NOT_ZERO` with mismatched value/numerator, and a
   known denominator smaller than the numerator.
3. Both probe and service `bootout` paths wait through transient loaded states until absence, use a
   single monotonic bounded deadline, and fail closed on timeout or an indeterminate inventory.
4. Final quiescence waits through transient label, listener, matching-process, and original-PID
   presence; succeeds only when all predicates are absent together; and fails closed at its bounded
   deadline without issuing another signal, start, or retry.
5. A failure receipt exists before the first cleanup mutation with status
   `COMMISSION_FAILED_CLEANUP_PENDING` or `STARTUP_FAILED_NO_RUNTIME_CLEANUP_PENDING`. A successful
   cleanup writes one exclusive final receipt with status
   `COMMISSION_FAILED_TERMINAL_AUDITED_QUIESCENT` or
   `STARTUP_FAILED_NO_RUNTIME_QUIESCENT`; a blocked closure writes one exclusive final receipt with
   status `COMMISSION_FAILED_CLEANUP_BLOCKED` or `STARTUP_FAILED_NO_RUNTIME_CLEANUP_BLOCKED` and the
   exact accumulated errors. The primary and final paths are distinct and neither is rewritten.
6. The exact envelope accepts only R4 root/labels/plists, includes the final closure receipt path,
   includes `r1/r2/r3` consumed-root identities and writer-absence facts, rejects R3 as a fresh
   production boundary, and keeps the loopback/one-start/no-`-k` constraints.
7. All existing absolute commissioning deadlines, exactly-once start/stop behavior, manual probe,
   periodic gate, resource audit, terminal audit, and stop semantics continue to pass. The
   executable controller contains no `/usr/bin/log` command; CPU above 50%, unreadable
   DiagnosticReports, positive exact-PID report counts, and positive queue-lag transition counts
   are accepted and recorded; inconsistent CPU percentages, negative counts, and nonzero
   `unified_log_row_count_examined` remain invalid evidence; and
   `unified_log_row_count_examined` is always `0`.
8. Authority tests prove exactly one active task, consumed R3 truth, the sole conditional R4
   boundary, and no stale executable R3 authorization.
9. A production-shaped 230-byte atomic evidence filename publishes through a short temporary
   basename with no residual temp file, and a local `EvidenceError` traverses the real subscription
   reducer path unchanged without incrementing public source-invalid diagnostics.

The controller's convergence waits are operational control waits, not business evidence. Each wait
uses its injected monotonic clock and a fixed 30,000 ms maximum with bounded 100 ms polling. A known
present state is retryable only until that deadline. An inventory command error, malformed output,
PID substitution, or any unknown state fails immediately. A later absence cannot repair a recorded
deadline miss.

The unchanged commissioning schedule remains one absolute lifecycle clock: lifecycle by 30,000 ms;
HTTP/current-reader commissioning by +60,000 ms; manual probe sequence 1 by +90,000 ms; current
audit and periodic-probe bootstrap by +110,000 ms; hard first-probe contract by +120,000 ms. After
bootstrap, `HOST_OPERABILITY_GATE_START` owns the full 180,000 ms gate, at least two successful
post-manual periodic rows, every complete-partition gap no greater than 90,000 ms, and a fixed
30,000 ms resource-event publication grace. Failure consumes that exact R4 attempt; the amendment
permits only a newly repaired, freshly materialized next R4 attempt after terminal quiescence and
full gates.

No live or launchd mutation is allowed from the implementation branch or PR. The eventual live
invocation requires the exact merged remote `main`, a detached clean checkout, an independently
created envelope and attempt-specific plists/wrappers, exact artifact digests, fresh output paths,
all three old-root inventories unchanged, no old or R4 label/process/listener, and bound resource
source configuration. The controller receives the independently calculated envelope identity through
`--expected-envelope-identity` and refuses mismatch.

## Evidence boundary

**Proves:** the R3 attempt is truthfully consumed and closed; each R4 attempt is independently
preserved and the R4 controller accepts the actual version-2 projection semantics, observes
asynchronous launchd teardown safely, records advisory resource facts without Unified Log text
classification, records temporally correct failure/closure evidence, and independently establishes
that exact attempt 006 reached `COMMISSIONED` under the bound R4 boundary.

**Does not prove:** 24x7 service stability; complete market coverage; strategy edge; opportunity
frequency; qualification; execution; actual fills, positions, fees, PnL, or capital safety.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | CONDITIONAL_AFTER_MERGE_AND_FRESH_PREFLIGHT |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** `apps/radar_runtime/src/radar_runtime/commissioning.py`; the exact redundant-work repair in
`apps/radar_runtime/src/radar_runtime/fixed_contract_shadow.py` and
`apps/radar_runtime/src/radar_runtime/workbench.py`; the exact attempt-005 temporary-name repair in
`packages/short_vol_radar/src/short_vol_radar/evidence.py` and evidence-error pass-through in
`apps/radar_runtime/src/radar_runtime/runtime.py`; their direct tests; R4 envelope,
failure-closure receipt, bootout/quiescence semantics, and fresh-boundary constants;
`docs/authority/CURRENT_STAGE.md`; `docs/authority/SYSTEM_ARCHITECTURE.md`; `README.md`; authority
tests; this sole active task; exact-candidate review/CI/merge; the commissioned attempt-006
read-only observation; and its one result-independent terminal close.

**Out:** `service.py`; workbench schema or publication-cadence changes; market adapters;
Radar/Underwriting/Position/Outcome formulas or state machines; contracts;
Policies; dependencies or lockfiles; private/account APIs; orders, fills, capital, execution;
qualification; automatic restart; reuse of R1/R2/R3 assets; alternate root/label/port; or any
retroactive edit to R3 evidence.

**Owning module/artifact:** `apps/radar_runtime/src/radar_runtime/commissioning.py`,
`packages/short_vol_radar/src/short_vol_radar/evidence.py`, the exact subscription dispatch boundary
in `apps/radar_runtime/src/radar_runtime/runtime.py`, their direct tests,
`tests/test_authority_and_architecture.py`, and the fresh R4 validation/deployment evidence root.

## Contract

**Inputs and known-at rule:** immutable merged Git/authority/task/contract/Policy/controller/plist/
wrapper bytes; public service evidence known at each lifecycle/probe boundary; and current
launchd/process/listener facts. A later host observation may establish convergence only within the
same declared wait deadline. It never rewrites an earlier receipt, probe row, deadline result, or
R3 artifact.

**Durable output and identity:** per attempt, one content-addressed R4 deployment envelope;
exactly-once intent journals; one primary commission receipt; on failure, one distinct final closure
receipt; one probe ledger; runtime-bound audits; and one stop receipt. Every artifact binds the envelope identity;
runtime-bearing artifacts additionally bind the actual lifecycle runtime identity.

**Missing/invalid/UNKNOWN semantics:** missing or malformed zero-claim members, host inventory,
identity, lifecycle, current-reader, endpoint, label/PID/listener, terminal, or output evidence fails
closed. Honest business `UNKNOWN` remains valid projection content and is never coerced to zero.
Known transient launchd presence is neither success nor an immediate permanent failure; it becomes
success only on observed absence before the bound deadline and failure at or before the deadline
otherwise.

**Persisted meaning and compatibility:** service and workbench schemas remain `COMPATIBLE` and
unchanged. R4 controller receipts are new attempt-scoped evidence and are `NOT_COMPARABLE` to R3 as
a continuation. The primary failure receipt means cleanup is pending at its write boundary; only
the separate final closure receipt claims quiescence or a cleanup blocker.

**Business denominators:** unchanged from the persistent-service contract. The commissioning
verifier validates projection shape; it does not invent a business denominator or turn an unknown
rate into zero. The probe denominator is every append attempt. The 24-hour denominator is one
continuous valid runtime interval and cannot be met by the bounded 180,000 ms operability gate.

## Acceptance

Acceptance requires all of the following on one exact candidate:

- focused commissioning, workbench, and authority tests pass;
- full `make check` passes without weakening existing assertions;
- diff review proves no out-of-scope hot-path, contract, Policy, dependency, or schema change;
- exact parent, commit, tree, and changed-file digests are recorded;
- an independent reviewer accepts the exact commit rather than only prose or a moving branch;
- non-force remote branch equality and GitHub CI pass;
- no live command was issued from the branch or PR;
- merge to remote `main` occurs only after those gates.

The commissioning result is accepted only from the independently recomputed attempt-006 host
evidence recorded above. The 24-hour result remains separately pending until its full denominator
and terminal evidence complete; a code/CI pass cannot supply either fact.

## Definition of done

- R3 is recorded as consumed with its exact receipt and terminal-audit facts.
- The deleted R3 task is not retained as an active or complete task file.
- Exactly one active R4 task and at most one bounded implementation branch/PR at a time exist.
- Stable regression tests cover every diagnosed defect and adversarial boundary above.
- The minimal exact R4 repair passes focused tests, `make check`, exact-candidate review, remote
  equality, and GitHub CI.
- The final candidate contains no temporary patch workflow, generated cache, test artifact, or
  unrelated formatting churn.
- The accepted code is merged before each R4 deployment materialization or launchd mutation.
- Each R4 attempt invokes commission once under fresh outputs; a failure is terminally closed and
  preserved before the next observed bug is repaired, with no blind retry or semantic inflation.
- Attempt 006 remains the sole commissioned runtime until its result-independent terminal close;
  the task stays active while its 24-hour denominator is incomplete and authorizes no further
  repair or recommissioning.
