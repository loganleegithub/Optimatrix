# Task — SHORT_VOL_PUBLIC_SHADOW_TWO_LAYER_ENGINEERING_ACCEPTANCE

**Status:** ACTIVE

**Task kind:** `EVIDENCE_ONLY`

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md) /
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) /
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)

**Authority base commit:** `07d035c5ee798cfd11de9bcc75592071652e232d`

**Authority base tree:** `7aeb85661cd129b05035ff85b4c4229b1ddd4362`

**Frozen runtime implementation commit:** `6eaaddfecf4c59a19c8029682a80fc52b7896a64`

**Frozen runtime implementation tree:** `f9ce7f98623ed7249160ee29c940c9c026fc4173`

**Target branch/PR:** `codex/short-vol-public-shadow-smoke`; one Draft PR against `main`

## Business closure

**Given:** the fixed-contract public Shadow runtime and exact three-Policy chain are accepted and
unchanged, and current deterministic tests already exercise the real `EpisodeTracker`, concrete
runtime adapter, downstream owner, full Candidate-to-Outcome lifecycle, strict readers, and
conservation without claiming that their fixtures are market trades.

**When:** first, the exact frozen candidate re-runs the pre-registered deterministic engineering
suite; second, one and only one result-independent production-public Shadow smoke runs
from a remotely equal activation commit under one exact manifest, one 14-minute enrollment cutoff,
one 29-minute final-stop trigger, and two new empty evidence directories. The one-minute remainder
is reserved for supervisor polling and clean-stop drain so the realized process interval must not
exceed 30 minutes.

**Then:** acceptance reports three independent results:

```text
engineering_end_to_end = PASS | FAIL
production_public_integration = PASS | FAIL
natural_shadow_opportunity = OBSERVED | NOT_OBSERVED
```

The first two are engineering gates. The third reports whether any natural Candidate,
`SHADOW_ENTRY`, or Outcome appeared and is never an engineering gate.

The natural report also preserves three independent facts:

```text
natural_candidate = OBSERVED | NOT_OBSERVED
natural_shadow_entry = OBSERVED | NOT_OBSERVED
natural_shadow_outcome = OBSERVED | NOT_OBSERVED
```

**Independent verification:** a read-only verifier binds the exact activation commit/tree before
publication; after the run, Codex re-reads the immutable manifest and both evidence directories,
runs the current strict Radar/downstream readers and conservation, and independently checks the
terminal source, source/RPC allowlists, summaries, null rates, object counts, one-process rule, and
zero private/account/order/fill activity.

**Valid zero/no-hit/UNKNOWN result:** zero natural Candidate, Entry, Position, close opportunity,
Outcome, or aligned pair is `NOT_OBSERVED` and satisfies this engineering acceptance when the
Radar integration predicates, clean stop, complete summaries, readers, and conservation pass.
Missing, stale, incomplete, or contaminated required engineering evidence remains `UNKNOWN` or
`FAIL`; it is never converted to zero. At least one real anomaly episode and its downstream
Underwriting-availability handoff are required for the production-public integration gate because
this smoke specifically closes the historical real-identity failure. Their absence is
`NOT_ACCEPTED`, but still cannot extend the window, change a Policy, or authorize another run.

**Upstream prerequisite:** exact accepted implementation commit/tree above, with no runtime or
Policy change after that implementation boundary.

## Change declarations

**Market/Decision input contract change:** `NONE` — source families, universe, timing,
currentness, continuity, executable quote meaning, and missingness are unchanged.

**Decision Policy change:** `NONE` — Radar, Underwriting, admission, Position, threshold,
quantity, fee-reserve, persistence, and clear/re-arm bytes are unchanged.

**Outcome/evaluation contract change:** `NONE` — strictly-future exit, Outcome, rejected path,
aligned pair, denominators, readers, and conservation are unchanged. This task changes only which
facts are current engineering gates.

**Stage/authorization change:** `APPROVED` — authorize exactly one manifest-bound under-30-minute
production-public Shadow smoke after every exact preflight passes. This grants no second process,
retry after a terminal/preflight/fatal failure, private/account/order/fill/capital capability,
qualification, promotion, or persistent deployment.

## Product operating behavior

One existing `radar_runtime observe-shadow` process owns the production-public Deribit WebSocket,
Radar reducer, exact three-Policy downstream owner, request-id allocator, two evidence writers,
and result-independent supervisor. It consumes only the frozen production-public source allowlist.
An official public quote is never an order or fill.

The frozen runtime may reconnect inside the same process after a recoverable public
WebSocket/continuity failure. Such reconnects remain continuity facts and are reported separately;
they are not a second evidence invocation. A preflight, terminal, fatal runtime, or fatal evidence
failure ends this task's sole invocation and is never automatically retried or pointed at reused
paths.

The manifest pre-binds runtime start, enrollment cutoff exactly 14 minutes after runtime start,
and final-stop trigger exactly 29 minutes after runtime start. The realized terminal must be no
later than 30 minutes after runtime start; trigger-observation and drain latency are reported.
None depends on anomaly, Candidate, Entry, Outcome, PnL, counts, coverage, or pass likelihood. No Policy tuning, duration extension, replay,
synthetic live event, standalone probe, second client, or second process is authorized.

## Validation harness

### Layer 1 — deterministic engineering chain

The existing suite is a composed proof, not one monolithic test:

1. the real `EpisodeTracker.observe()` path produces the composite Radar episode identity and the
   concrete adapter/owner accepts it at the Underwriting boundary;
2. the concrete adapter/owner deterministically drives atomic quote, Candidate, refreshed quote,
   `SHADOW_ENTRY`, Position actions, later close opportunity, and `SHADOW_OUTCOME` exactly once;
3. the complete downstream reader re-derives summary counts and conservation.

These are deterministic engineering fixtures. They do not claim a natural market opportunity,
order, fill, exposure, actual PnL, or strategy value.

### Layer 2 — production-public integration smoke

Before Deribit I/O, prove a clean exact candidate, fresh remote equality, exact contract/Policy
digests, one canonical manifest, two distinct absent external evidence directories, exact argv/cwd,
and fixed supervisor triggers. After the one terminal, require:

- process exit `0` and `PLANNED_CLEAN_STOP` at the pre-bound final-stop trigger;
- downstream
  `terminal_fact_boundary.received_monotonic_ms - runtime_start_fact_boundary.received_monotonic_ms
  <= 1800000`;
- one strict `RADAR_RUN_SUMMARY` with positive observation and `KNOWN_COMPLETE` time, zero coverage
  partition error, and a non-null current-epoch joint witness;
- at least one same `counts_by_scope` row with a real applicable instrument, a known
  per-instrument evaluation, a known full-formula evaluation, a complete aggregate, and a complete
  aggregate with full formula, all positive and cross-bound to that witness;
- `index`, `option_book`, `option_ticker`, and `public/get_instruments` source-shape rows each
  `VALID` with positive valid count;
- complete Underwriting/Position and cohort summaries, both current/complete readers passing, and
  conservation `MET`;
- at least one real anomaly artifact whose composite episode identity is well formed, and at least
  one downstream Underwriting-availability evaluation reached without the historical fatal;
- zero private/account/order/fill/capital calls or artifacts; and
- one process invocation, zero retry after terminal/preflight/fatal failure, and no reused path.

## Evidence boundary

**Proves:** the frozen engineering chain is deterministic end to end, and one exact public-only
runtime can ingest real Deribit data, execute non-vacuous Radar formulas, hand any naturally
observed real episode to downstream without the repaired fatal, cleanly stop, and write a complete
strictly readable conserved evidence set.

**Does not prove:** natural opportunity frequency, a usable long-run cohort, Policy quality,
forecast skill, edge, profitability, fillability, account fees, actual PnL, actual exposure,
execution, qualification, promotion, indefinite uptime, or persistent deployment.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | REQUIRED for complete lifecycle evidence; natural nonzero count is not required |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE / FORBIDDEN |

## Scope

**In:** one authority/task activation; existing deterministic tests; one post-publication manifest;
one under-30-minute production-public invocation; strict Radar/downstream readers; conservation; exact
Git/remote/PR, source allowlist, terminal, process-count, and zero-private verification; one final
external terminal record.

**Out:** runtime/package/schema/contract/Policy changes, dependencies, locks, replay, synthetic
market events, calibration, private/account methods, credentials, balances, margin, orders, fills,
settlement, capital, execution, qualification, promotion, persistent service, second invocation,
retry after terminal failure, `main`, merge, rebase, force-push, and history rewriting.

**Owning module/artifact:** permission routing in `CURRENT_STAGE.md`; this active task; external
manifest, Radar evidence directory, downstream evidence directory, process log, and terminal
record. Runtime source and Policy bytes are read-only.

**Exact allowed repository files:**

```text
README.md
docs/authority/CURRENT_STAGE.md
tasks/SHORT_VOL_PUBLIC_SHADOW_TWO_LAYER_ENGINEERING_ACCEPTANCE.md
tests/test_authority_and_architecture.py
```

## Contract

**Inputs and known-at rule:** exact public facts known at or before each decision `causal_seq`;
Outcome facts strictly after Entry; all existing currentness, frontier, continuity, official combo,
admission, attempt, and terminal rules are unchanged.

**Durable output and identity:** one external exact-byte manifest; one strict Radar directory; one
strict downstream directory; one process log; and one terminal record, all bound to the exact
post-publication activation commit/tree/ref, runtime/clock, contract, Policies, paths, and terminal.

**Missing/invalid/UNKNOWN semantics:** any pre-run identity/path/digest/remote/cleanliness failure
blocks startup. Runtime missingness remains `UNKNOWN`. A process failure uses the frozen failure
terminal and does not receive a second invocation. Partial or incomplete bytes cannot satisfy
either engineering gate.

**Persisted meaning and compatibility:** `COMPATIBLE`; no schema, identity formula, unit, reader,
Policy, or accepted business meaning changes.

**Business denominators:** all contract-defined Radar, Underwriting, Candidate, admission, Entry,
Position, close-opportunity, Outcome, and pair units remain unchanged. Zero or unknown denominators
serialize rates as `null`; duration, messages, files, tests, and reconnects are not business units.

## Acceptance

### Layer 1 — deterministic end to end

1. Real `EpisodeTracker.observe()` produces the composite episode identity and the adapter/owner
   accepts both no-combo and quoted/unknown projections without the historical fatal.
2. The concrete adapter/owner produces exactly one Candidate/Entry path, `HOLD | CLOSE`, one later
   full-quantity close opportunity, one Outcome, and no duplicate on unchanged replay of the same
   settled boundary.
3. The complete downstream reader re-derives the terminal summary and conservation.
4. Result: `engineering_end_to_end = PASS` only when all three existing tests pass on the exact
   activation candidate.

### Layer 2 — production-public smoke

1. Exact preflight binds local HEAD/tree, fresh remote ref, Draft PR head, six immutable digests,
   manifest, absent paths, argv/cwd, and 14/29-minute triggers before any Deribit I/O.
2. Exactly one process reaches the planned clean-stop boundary with complete Radar and downstream
   summaries; strict current/complete readers pass, conservation is `MET`, and downstream terminal
   minus runtime-start monotonic time is at most `1800000` milliseconds.
3. Radar source shapes prove real Deribit index/ticker/book/catalog traffic; coverage partition
   error is zero; the five non-vacuous Radar counts listed above are positive.
4. At least one naturally observed real anomaly enters downstream without fatal identity failure;
   zero anomaly or zero Underwriting handoff makes this layer `FAIL` without extending or retrying
   the run. Layer 1 independently proves the same identity boundary deterministically.
5. Source/RPC inspection proves the exact public allowlist, zero private/account/order/fill/capital
   activity, one process invocation, zero post-terminal retry, and honest reconnect accounting.
6. Result: `production_public_integration = PASS` only when all engineering predicates above pass.

### Natural Shadow opportunity

Candidate, Entry, and Outcome counts are reported separately from
`UNDERWRITING_POSITION_SUMMARY.payload.counts.candidate_count`,
`UNDERWRITING_POSITION_SUMMARY.payload.counts.shadow_entry_count`, and
the sum of `SHORT_VOL_SHADOW_FORWARD_COHORT_SUMMARY.payload.counts.shadow_outcome_count` and
`.rejected_outcome_count`. Admitted and rejected Outcome counts remain separately visible. Each maps
independently to `OBSERVED` when positive and otherwise `NOT_OBSERVED`; the overall natural Shadow
opportunity is `OBSERVED` when any of the three is positive. Either overall result satisfies this
task and cannot change the window, Policy, retry count, or later development permission.
These labels are computed only after both strict directories are complete and conserved; a failed
process or incomplete reader result makes all three `NOT_EVALUABLE`, never `NOT_OBSERVED`.

### Required commands

- `make sync`
- deterministic chain:
  `.venv/bin/python -m pytest tests/test_fixed_contract_shadow.py::test_real_episode_identity_round_trips_without_economic_action tests/test_fixed_contract_shadow.py::test_concrete_adapter_runs_candidate_admission_position_and_future_exit_once tests/test_complete_downstream_evidence.py::test_complete_reader_closes_manifest_summaries_and_rederived_counts`
- focused authority, preflight, runtime barrier/composition, complete-reader, Underwriting, and
  Radar regression suites
- `make check`
- `git diff --check`
- production-public command: exactly one
  `.venv/bin/python -m radar_runtime observe-shadow --manifest <frozen-manifest> --radar-evidence-dir <new-radar-directory>`
- independent verification: current strict repository readers and conservation only; no replay or
  synthetic reconstruction

### Real evidence

**Required:** YES

**Environment and stopping condition:** Deribit production-public only. Enrollment cutoff is
exactly 14 minutes after runtime start, the final-stop trigger is exactly 29 minutes after runtime
start, and the realized terminal must be no later than 30 minutes after runtime start. A safety or
fatal failure may stop earlier. No market or strategy result may extend, shorten, retry, or select
the interval.

**Required report:** exact commit/tree/ref/PR and checks; manifest/path/hash; actual start/cutoff/
stop/failure boundaries; deterministic layer result; Radar/downstream summary identities and
ordered file hashes; source allowlist; coverage/full-formula counts; reader/conservation results;
all natural Candidate/Entry/Outcome counts and `OBSERVED | NOT_OBSERVED`; all `UNKNOWN`/null/zero;
terminal/process/reconnect/retry facts; remote equality; limitations and non-claims; zero
private/account/order/fill/capital activity.

**Private API:** FORBIDDEN.

## Frozen external paths

All five targets must be absent before manifest creation and must never reuse or mutate the sealed
`public-shadow-forward-001` attempt:

- Manifest: `/Users/logan/Optimatrix-shadow/manifests/public-shadow-engineering-smoke-002.json`
- Downstream evidence:
  `/Users/logan/Optimatrix-shadow/evidence/public-shadow-engineering-smoke-002-downstream`
- Radar evidence:
  `/Users/logan/Optimatrix-shadow/evidence/public-shadow-engineering-smoke-002-radar`
- Process log: `/Users/logan/Optimatrix-shadow/logs/public-shadow-engineering-smoke-002.log`
- Final terminal record:
  `/Users/logan/Optimatrix-shadow/receipts/public-shadow-engineering-smoke-002-terminal-record.json`

## Immutable identities

- Radar contract:
  `sha256:b9733ad0c90837338b88fb5b6eb66ad8eed448cce6372a3f527988395087b3fe`
- Underwriting/Position contract:
  `sha256:9cbaecf57fb1db0dedf782a4ab002b655e43319a1ad7c5880db3d7b4682d4b03`
- Outcome/cohort contract:
  `sha256:61a032fe0fe265d66a38bcbb1a3c8498409664fedbda2c8bd0a245180581a695`
- Radar Policy:
  `sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4`
- Underwriting Policy:
  `sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af`
- Position Policy:
  `sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439`

## Artifacts and delivery report

**Artifact paths and digests:** the five exact external paths above. The final report records
SHA-256 for every authoritative artifact and one ordered absolute-path file manifest.

**Policy/contract identities:** the six immutable identities above remain byte-identical.

**Commit/PR:** one activation commit and one later terminal-record authority commit may be
published append-only on the target branch/Draft PR. The activation task cannot contain its own
future commit hash; the external manifest binds it after publication. No merge, rebase, force-push,
or history rewrite is authorized.

**Unknowns and non-claims:** natural market/business activity is unknown before the run and
non-gating afterward. Even a nonzero cohort is not qualification. No account, fill, exposure,
actual fee, actual PnL, execution, promotion, or deployment claim is permitted.

## Definition of done

The deterministic composed chain is `PASS`; exactly one remotely bound under-30-minute public process
reaches its pre-bound clean stop; Radar and downstream summaries are complete; strict readers and
conservation pass; real public coverage/full-formula evidence is non-vacuous; forbidden capability
and post-terminal retry counts are zero; natural Candidate/Entry/Outcome is reported only as
`OBSERVED | NOT_OBSERVED`; and manifest, evidence, log, terminal record, Git, remote, and PR are
independently reconciled without changing runtime or Policy bytes.
