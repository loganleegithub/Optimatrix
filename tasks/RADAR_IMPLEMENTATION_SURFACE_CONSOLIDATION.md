# Task — RADAR_IMPLEMENTATION_SURFACE_CONSOLIDATION

**Status:** ACTIVE IMPLEMENTATION — final gate not reached

**Task kind:** `IMPLEMENTATION`

**Runtime implementation:** `REQUIRED — PHASE_A`

**Live commands:** `REQUIRED — PHASE_B; currently NOT_RUN`

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `7ddb971436158d70094ea1070aa6f8ce5faaf0fd`

**Target branch:** `codex/radar-repository-consolidation`

## Business closure

**Given:** the production-public Short Vol Radar is accepted at candidate
`7c36a3aa4fc9e7bf1ef2977eaeb0c75a620b0ae0`, while its current implementation surface contains
the exact zero-caller and unreachable compatibility surface named below, plus one closed task
whose historical prose is incorrectly retained as a current test owner.

**When:** the repository consolidates that implementation surface on the bounded target branch,
passes direct offline verification, and then independently requalifies the exact candidate
through fresh Smoke and Soak gates.

**Then:** one smaller owning implementation surface preserves the established public Radar
behavior and every current/legacy reader boundary. Until both fresh live gates and the final
stage-record gate pass, the existing accepted candidate remains the only accepted production
implementation.

**Independent verification:** direct behavior and architecture tests, `make check`, independent
exact-candidate verification, then separately bound and independently accepted fresh
`REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` evidence.

**Valid zero/no-hit/UNKNOWN result:** direct tests may contain no natural anomaly or atomic quote.
A fresh Smoke or Soak may truthfully report zero natural events or `UNKNOWN` facts only as allowed
by the existing gate contract; it passes only if every unchanged gate predicate passes. A
`NOT_RUN`, incomplete, invalid, or `NOT_MET` Phase B gate leaves this task active and does not
change the accepted stage record.

**Upstream prerequisite:** the accepted `PRODUCTION_PUBLIC_SHORT_VOL_RADAR` stage record and exact
base commit above.

## Change declarations

**Market/Decision input contract change:** `NONE` — no source, universe, timing, continuity,
freshness, missingness, executable quote, or consumed-fact semantic changes.

**Decision Policy change:** `NONE` — no Policy bytes/schema, formula, scope, threshold,
persistence, clear/re-arm, structure, or runtime-limit changes.

**Outcome/evaluation contract change:** `NONE` — no future fact, denominator, replay,
recomputation, Candidate, Position, Outcome, comparator, or qualification change.

**Stage/authorization change:** `NONE` — permission remains `PUBLIC_SHADOW`, implemented
capability remains `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`, Radar remains `ESTABLISHED`, and the sole
authorized next product-capability closure remains `NONE`.

**Repository-internal Python API compatibility:** `REMOVE_EXACT_LEGACY_SURFACE` — remove only
`IndexTail` and the current-Python `INDEX_TAIL_PENDING` surface named in this task; retain
`IndexTailStatus`, `IndexBaselineState.status`, `tail.status.value`, and every other package
import.

## Bounded terminal-goal delegation

`RADAR_IMPLEMENTATION_SURFACE_CONSOLIDATION_DELEGATION` conditionally authorizes only this
semantic closure:

1. Phase A may consolidate the owning Python/module/test surface, update the exact authority and
   contract clarifications required by that consolidation, run focused checks and `make check`,
   create append-only commits on the target branch, obtain an independent exact-candidate pass
   receipt, and non-force push only the bounded target branch after that receipt.
2. Phase B may begin only after the pushed remote ref is independently verified equal to the
   exact Phase A candidate. It must pre-bind and run one fresh `REACHABILITY_SMOKE`, obtain
   independent post-stop acceptance, then separately pre-bind and run one fresh
   `OPERATIONAL_SOAK` with a new empty evidence directory and obtain independent post-stop
   acceptance.
3. Only after both Phase B gates pass may a final stage-record change bind the replacement exact
   candidate and its fresh evidence. That record changes no permission or product capability.
4. Any candidate code change invalidates the exact-candidate receipt and every later binding.
   A failed or incomplete live attempt uses a new manifest and new empty evidence directory.

The delegation does not authorize a `main` merge, force push, history rewrite, remote deletion,
persistent service deployment, Policy change, private/account API, credentials, capital, order,
fill, trade, execution, or later product closure. The human emergency stop remains effective.
This task must remain `ACTIVE` until the final gate records the independently accepted exact
replacement candidate; Phase A completion or green checks alone cannot close it.

## Product operating behavior

The established continuous public Radar behavior is unchanged. One process freezes one exact
Policy, maintains bounded current public state, evaluates causally changed facts, writes minimal
anomaly/atomic edges and one clean-stop summary, and exposes no Candidate, Position, Outcome,
private, or execution behavior.

The consolidation may remove only the exact symbols, export, closed task, and history-only tests
listed below. It may not relocate implementation ownership, split a module, replace the
currentness token, or introduce a compatibility layer.

## Validation harness

Phase A uses direct unit/architecture/reader tests and the complete repository check. Phase B uses
fresh production-public evidence under the unchanged `SHORT_VOL_RADAR` Smoke and Soak contracts.
Historical accepted evidence proves the current accepted candidate only and cannot requalify the
replacement candidate.

### Frozen Phase B bindings and acceptance

Phase B has no result-dependent choices. It is authorized only for the final Phase A commit/tree
after an independent exact-commit pass receipt and a post-push query prove
`refs/heads/codex/radar-repository-consolidation` equals that commit. Each run uses that exact clean
checkout, one immutable UTF-8 JSON
`OPTIMATRIX_PUBLIC_RADAR_EXTERNAL_RUN_MANIFEST` version 1 outside the worktree and evidence
directory, and one directory proved absent before the gate and empty immediately before child
creation. Each manifest binds the exact commit, tree, branch, intended/verified remote ref,
verified remote commit, Policy path/digest, evidence path and empty proof, exact `argv` and `cwd`,
focused and `make check` pass identities, independent exact-commit receipt path/hash, the frozen
stop object, and the exact gate threshold object. Missing or additional manifest keys,
placeholders, a dirty/different checkout, remote inequality, Policy mismatch, a pre-existing or
non-empty evidence directory, or a manifest not durably flushed before child start makes that
attempt `NOT_MET`.

The two exact-key templates below are independently parseable JSON. Angle-bracket strings are typed
identity slots in the task definition and must be replaced by concrete values before startup. The
integer values `0` and `300000`/`3900000` in each stop object are a parseable exemplar satisfying
`deadline = start + duration`; the runnable manifest replaces the two zero-origin values with the
actual non-negative monotonic start and its exact sum, preserving JSON integer type. Every object
has exactly the shown keys; object key order is irrelevant, but no key may be missing or added.

`REACHABILITY_SMOKE`:

```json
{
  "external_run_manifest_schema": "OPTIMATRIX_PUBLIC_RADAR_EXTERNAL_RUN_MANIFEST",
  "external_run_manifest_schema_version": 1,
  "gate": "REACHABILITY_SMOKE",
  "code": {
    "commit": "<40-lowercase-hex>",
    "tree": "<40-lowercase-hex>",
    "branch": "codex/radar-repository-consolidation",
    "intended_remote_ref": "refs/heads/codex/radar-repository-consolidation",
    "verified_remote_ref": "refs/heads/codex/radar-repository-consolidation",
    "verified_remote_commit": "<same-40-lowercase-hex-as-commit>"
  },
  "policy": {
    "policy_path": "/Users/logan/Optimatrix-smoke/policies/reachability-smoke-v2.json",
    "policy_digest": "sha256:faeff9740a43df6de5c85268571592a5d47d90f9c146b2ba8b812d4e3525e50d"
  },
  "evidence": {
    "evidence_directory": "/Users/logan/Optimatrix-smoke/evidence/reachability-smoke-radar-consolidation-001",
    "startup_empty_proof": {
      "checked_at_utc": "<RFC3339-UTC>",
      "checked_immediately_before_start": true,
      "entry_count": 0
    }
  },
  "execution": {
    "argv": [
      ".venv/bin/python",
      "-m",
      "radar_runtime",
      "observe",
      "--policy",
      "/Users/logan/Optimatrix-smoke/policies/reachability-smoke-v2.json",
      "--expected-policy-digest",
      "sha256:faeff9740a43df6de5c85268571592a5d47d90f9c146b2ba8b812d4e3525e50d",
      "--evidence-dir",
      "/Users/logan/Optimatrix-smoke/evidence/reachability-smoke-radar-consolidation-001"
    ],
    "cwd": "<absolute-exact-clean-worktree>"
  },
  "stop": {
    "deadline_monotonic_ms": 300000,
    "duration_ms": 300000,
    "emergency_stop": {
      "enabled": true,
      "signal": "SIGINT"
    },
    "kind": "MONOTONIC_DEADLINE",
    "result_independent": true,
    "signal": "SIGINT",
    "signal_count": 1,
    "supervisor_started_monotonic_ms": 0
  },
  "required_checks": {
    "focused_tests": "<exact-command-and-PASS-identity>",
    "independent_exact_commit_receipt": "<absolute-path-and-sha256>",
    "make_check": "<exact-command-and-PASS-identity>"
  },
  "thresholds": {
    "applicable_instrument_count": {
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": 1
    },
    "complete_aggregate_detector_evaluation_count": {
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": 1
    },
    "complete_aggregate_with_full_formula_evaluation_count": {
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": 1
    },
    "coverage_partition_error_ms": {
      "operator": "EQUALS",
      "value": 0
    },
    "forbidden_runtime_artifacts": {
      "orders_or_trades": 0,
      "persisted_normal_or_no_anomaly_rows": 0,
      "private_api_calls": 0
    },
    "grouping": [
      "policy_identity",
      "option_type",
      "tte_band"
    ],
    "known_full_detector_formula_evaluation_count": {
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": 1
    },
    "known_per_instrument_detector_evaluation_count": {
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": 1
    },
    "required_report_fields": [
      "known_full_formula_rate_given_known_per_instrument",
      "complete_aggregate_with_full_formula_rate_given_complete_aggregate",
      "detector_unknown_transition_count_by_reason",
      "distinct_anomaly_episode_count",
      "anomaly_activation_transition_count",
      "anomaly_end_count_by_reason",
      "known_active_duration_ms_sum_by_end_reason",
      "public_atomic_quote_state_transition_count"
    ]
  }
}
```

`OPERATIONAL_SOAK`:

```json
{
  "external_run_manifest_schema": "OPTIMATRIX_PUBLIC_RADAR_EXTERNAL_RUN_MANIFEST",
  "external_run_manifest_schema_version": 1,
  "gate": "OPERATIONAL_SOAK",
  "code": {
    "commit": "<40-lowercase-hex>",
    "tree": "<40-lowercase-hex>",
    "branch": "codex/radar-repository-consolidation",
    "intended_remote_ref": "refs/heads/codex/radar-repository-consolidation",
    "verified_remote_ref": "refs/heads/codex/radar-repository-consolidation",
    "verified_remote_commit": "<same-40-lowercase-hex-as-commit>"
  },
  "policy": {
    "policy_path": "/Users/logan/Optimatrix-soak/policies/operational-soak-successor.json",
    "policy_digest": "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4"
  },
  "evidence": {
    "evidence_directory": "/Users/logan/Optimatrix-soak/evidence/operational-soak-radar-consolidation-001",
    "startup_empty_proof": {
      "checked_at_utc": "<RFC3339-UTC>",
      "checked_immediately_before_start": true,
      "entry_count": 0
    }
  },
  "execution": {
    "argv": [
      ".venv/bin/python",
      "-m",
      "radar_runtime",
      "observe",
      "--policy",
      "/Users/logan/Optimatrix-soak/policies/operational-soak-successor.json",
      "--expected-policy-digest",
      "sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4",
      "--evidence-dir",
      "/Users/logan/Optimatrix-soak/evidence/operational-soak-radar-consolidation-001"
    ],
    "cwd": "<absolute-exact-clean-worktree>"
  },
  "stop": {
    "deadline_monotonic_ms": 3900000,
    "duration_ms": 3900000,
    "emergency_stop": {
      "enabled": true,
      "signal": "SIGINT"
    },
    "kind": "MONOTONIC_DEADLINE",
    "result_independent": true,
    "signal": "SIGINT",
    "signal_count": 1,
    "supervisor_started_monotonic_ms": 0
  },
  "required_checks": {
    "focused_tests": "<exact-command-and-PASS-identity>",
    "independent_exact_commit_receipt": "<absolute-path-and-sha256>",
    "make_check": "<exact-command-and-PASS-identity>"
  },
  "thresholds": {
    "acceptance_window_ms": 3600000,
    "incident_recovery_sla": {
      "formula": "(largest_lookback_minutes + 2) * 60000 + time_boundary_poll_interval_ms",
      "largest_lookback_minutes": 1,
      "time_boundary_poll_interval_ms": 1000,
      "value_ms": 181000
    },
    "index_baseline_publication": {
      "acceptance_budget_ms": null,
      "diagnostic_only": true,
      "omitted_interval_count": 0
    },
    "normalized_current_coverage": {
      "denominator": 3600000,
      "numerator": "duration(K)",
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": "0.99"
    },
    "normalized_option_local_availability": {
      "formula": "1 - duration(U) / duration(E)",
      "operator": "GREATER_THAN_OR_EQUAL",
      "value": "59/60"
    },
    "option_local_omitted_interval_count": 0,
    "post_stop_required": [
      "strict current-schema evidence-directory validation",
      "latest continuity incident recovered",
      "current-epoch witness is non-null and later than latest recovery",
      "witness binds one identical scope whose five reachability counts are each at least one",
      "gate-specific frozen accounting and thresholds"
    ]
  }
}
```

The durably flushed runnable manifest contains no angle-bracket strings. The supervisor log is the
separately pre-registered controller output path in the gate table; it is not a manifest key and
therefore does not widen this version-1 schema. The post-stop supervisor result binds the log path,
manifest path/SHA-256, exact commit/tree, deadline, actual one-signal stop, child exit, and evidence
directory.

The exact gate bindings are:

| Binding | `REACHABILITY_SMOKE` | `OPERATIONAL_SOAK` |
|---|---|---|
| Policy path | `/Users/logan/Optimatrix-smoke/policies/reachability-smoke-v2.json` | `/Users/logan/Optimatrix-soak/policies/operational-soak-successor.json` |
| Policy digest | `sha256:faeff9740a43df6de5c85268571592a5d47d90f9c146b2ba8b812d4e3525e50d` | `sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4` |
| Manifest | `/Users/logan/Optimatrix-smoke/manifests/reachability-smoke-radar-consolidation-001.json` | `/Users/logan/Optimatrix-soak/manifests/operational-soak-radar-consolidation-001.json` |
| Evidence directory | `/Users/logan/Optimatrix-smoke/evidence/reachability-smoke-radar-consolidation-001` | `/Users/logan/Optimatrix-soak/evidence/operational-soak-radar-consolidation-001` |
| Supervisor log | `/Users/logan/Optimatrix-smoke/logs/reachability-smoke-radar-consolidation-001.log` | `/Users/logan/Optimatrix-soak/logs/operational-soak-radar-consolidation-001.log` |
| Monotonic stop duration | `300_000 ms` | `3_900_000 ms` |

For each gate the external supervisor records
`deadline_monotonic_ms = supervisor_started_monotonic_ms + duration_ms`, durably flushes the
complete manifest, and starts exactly the selected gate's argument array:

```text
REACHABILITY_SMOKE:
.venv/bin/python -m radar_runtime observe
--policy /Users/logan/Optimatrix-smoke/policies/reachability-smoke-v2.json
--expected-policy-digest sha256:faeff9740a43df6de5c85268571592a5d47d90f9c146b2ba8b812d4e3525e50d
--evidence-dir /Users/logan/Optimatrix-smoke/evidence/reachability-smoke-radar-consolidation-001

OPERATIONAL_SOAK:
.venv/bin/python -m radar_runtime observe
--policy /Users/logan/Optimatrix-soak/policies/operational-soak-successor.json
--expected-policy-digest sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4
--evidence-dir /Users/logan/Optimatrix-soak/evidence/operational-soak-radar-consolidation-001
```

The supervisor never inspects live evidence, counters, thresholds, or provisional verdict. At the
deadline, or on a human emergency stop that cancels it, it sends exactly one `SIGINT` and waits for
the writer and child to finish. `SIGSTOP`, `SIGCONT`, `SIGKILL`, `kill -9`, and a second stop
signal are forbidden. Failure to complete the writer and exit cleanly is `NOT_MET`.

Smoke freezes `duration_ms = 300_000` and exactly these predicates:

```text
coverage_partition_error_ms = 0
applicable_instrument_count >= 1
known_per_instrument_detector_evaluation_count >= 1
known_full_detector_formula_evaluation_count >= 1
complete_aggregate_detector_evaluation_count >= 1
complete_aggregate_with_full_formula_evaluation_count >= 1
grouping = [policy_identity, option_type, tte_band]
private_api_calls = 0
orders_or_trades = 0
persisted_normal_or_no_anomaly_rows = 0
```

Its report must also contain
`known_full_formula_rate_given_known_per_instrument`,
`complete_aggregate_with_full_formula_rate_given_complete_aggregate`,
`detector_unknown_transition_count_by_reason`, `distinct_anomaly_episode_count`,
`anomaly_activation_transition_count`, `anomaly_end_count_by_reason`,
`known_active_duration_ms_sum_by_end_reason`, and
`public_atomic_quote_state_transition_count`. Rates with a zero/unknown denominator are `null`.
Strict current-version directory validation, the exact clean-stop identity, and the same-snapshot
full-formula/complete-aggregate witness must pass. Natural anomaly and public atomic quote
occurrence are reported `OBSERVED | NOT_OBSERVED` and are not acceptance predicates.

Soak freezes `duration_ms = 3_900_000`. Let:

```text
S = clean_stop_monotonic_ms
A = S - 3_600_000
W = [A, S)
L = Policy.largest_lookback_minutes = 1
R = (L + 2) * 60_000 + Policy.runtime_limits.time_boundary_poll_interval_ms
  = (1 + 2) * 60_000 + 1_000
  = 181_000 ms
```

The child must start no later than `A`; with the frozen supervisor duration this means no later
than `supervisor_started_monotonic_ms + 300_000`. Post-stop acceptance requires all of:

1. strict current-version directory validation and one canonical completed
   `radar-run-summary.json`; coverage partitions the complete runtime with zero error;
   `ingress received == reduced`; application gaps, duplicates, overflow, source-shape,
   RPC pre-/post-send, orphan, channel, transport-terminal, and writer-directory ledgers all
   reconcile;
2. `P`, the union inside `W` of generation-global
   `TIME_BOUNDARY_PENDING | WATERMARK_PENDING` publication rows, is diagnostic only, has no
   acceptance budget, is not deducted from another denominator, has
   `omitted_interval_count = 0`, and every row is bounded with an allowed owning end reason;
3. every non-pending currentness incident intersecting `W` recovers to complete current truth no
   later than its start plus `R = 181_000 ms`; no such incident is open at clean stop;
4. for `K`, the union of `KNOWN_COMPLETE` coverage inside `W`,
   `duration(K) / 3_600_000 >= 0.99`;
5. for `G`, the union inside `W` of global/session/clock/index incident intervals, `E = W \ G`,
   and `U`, the union across instruments and exact option-local reason intervals intersected with
   `E`: `duration(E) > 0`, option-local `omitted_interval_count = 0`, no option-local interval is
   open at clean stop, and `1 - duration(U) / duration(E) >= 59 / 60`;
6. the current-epoch global witness is non-null, later than the latest global-continuity recovery,
   binds one identical Policy/expiry/option-type/band/formula-instrument/boundary scope, and that
   scope's five reachability counts are each at least one; every formula-required source is
   observed and `VALID`;
7. `public/set_heartbeat` succeeds. If no server heartbeat is observed, no `test_request` or
   `public/test` success is fabricated. If observed, heartbeat shape/control/RPC/latency/channel
   and ingress counts cross-conserve; every scheduled `public/test` is sent and succeeds once with
   zero error, deadline, retirement, censor, or rate-limit count.

An incomplete/failed run, open recovery, zero/unknown denominator, all-`UNKNOWN` window, or any
failed predicate is truthful `NOT_MET`, never success. A retry is not authorized by the consumed
path: it requires a separately amended fresh manifest and fresh absent evidence directory.

## Evidence boundary

**Direct behavior:** `REQUIRED`

**Fresh REACHABILITY_SMOKE requalification:** `REQUIRED — NOT_RUN`

**Fresh OPERATIONAL_SOAK requalification:** `REQUIRED — NOT_RUN`

**Proves:** the exact consolidated candidate preserves the established implementation behavior
and satisfies fresh bounded production-public reachability and operating gates.

**Does not prove:** a product semantic change, forecast quality, edge, profitability, best-market
selection, fill, execution, indefinite uptime, or persistent deployment.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | REQUIRED |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** exactly:

- `market_monitor.index.IndexTail` and its package export;
- `PublishedIndexTail.publication_identity`;
- `IndexMinuteReducer.accepted_watermark_ms`;
- current-Python `TrackerState.INDEX_TAIL_PENDING`,
  `CurrentDisposition.INDEX_TAIL_PENDING`, their index-tail suspend/resume methods, and branches
  that serve only those unreachable states;
- `CausalCommit.source_currentness_causes`;
- `RadarReducer._coverage_affected_scopes`;
- `radar_runtime.runtime._current_for_index_tail` and `_index_tail_reason`;
- `tasks/SHORT_VOL_RADAR_ESTABLISHMENT.md`, tests that only lock its historical prose, and the
  smallest contract/authority/direct-test updates required by those removals;
- fresh unchanged-contract Smoke and Soak requalification of the final exact candidate.

**Out:** market or Policy semantics, diagnostics schema changes, new evidence formats, reader
migration, historical evidence edits, `IndexTailStatus`, `IndexBaselineState.status`,
`tail.status.value`, `_option_local_coverage_scopes`, currentness-token replacement, module
movement/splitting, unrelated refactors, downstream product stages, and all private/execution
behavior.

**Owning module/artifact:** the smallest existing owner of each redundant implementation surface;
this task and the current `SHORT_VOL_RADAR` contract own the consolidation boundary.

## Contract

**Inputs and known-at rule:** unchanged from `SHORT_VOL_RADAR`; every current result consumes only
facts known at or before its bound causal boundary.

**Durable output and identity:** unchanged `SHORT_VOL_ANOMALY_EVENT`,
`PUBLIC_ATOMIC_QUOTE_EVENT`, and `RADAR_RUN_SUMMARY` identities.

**Missing/invalid/UNKNOWN semantics:** unchanged; missing, stale, discontinuous, incomplete, or
invalid evidence remains `UNKNOWN` at the smallest declared consumer and never becomes zero or
calm.

**Persisted meaning and compatibility:** `COMPATIBLE`. The current diagnostics version 6
writer/reader and explicit read-only sealed diagnostics version 5, version 4, version 3, and
version 2 readers remain unchanged. No historical object is migrated, recomputed, relabelled, or
accepted under another reader.

**Business denominators:** unchanged from `SHORT_VOL_RADAR`; implementation classes, imports,
tests, files, commits, and repeated observations are not business units.

## Acceptance

### Direct behavior

1. The repository-internal package surface removes only the explicitly obsolete `IndexTail`
   import/export. Every other current import remains available, including the production
   projection `IndexTailStatus` plus `IndexBaselineState.status`.
2. `INDEX_TAIL_PENDING` was a repository-internal Python-only compatibility enum/disposition, not
   serialized evidence vocabulary. Its removal changes no owning-version reader.
   `CoverageBlockingReason.INDEX_TIME_BOUNDARY_PENDING`,
   `CoverageBlockingReason.INDEX_WATERMARK_PENDING`, `SOAK_PENDING_REASONS`, version-5 pending
   accounting, and all sealed fixtures remain unchanged.
3. Current diagnostics version 6 writer/reader behavior and explicit read-only sealed version
   5-through-2 readers remain unchanged.
4. Existing market, detector, episode, publication, evidence, and permission tests remain green,
   and dependency-direction tests prove the reduced ownership.

### Required commands

- `make sync`
- focused tests for every changed owner and `tests/test_authority_and_architecture.py`
- `make check`
- Phase B production-public commands: the exact unchanged-contract Smoke command and, only after
  independent Smoke acceptance, the exact unchanged-contract Soak command; both are `NOT_RUN`
  until their exact candidate/remote/Policy/evidence/stop bindings exist.

### Real evidence

**Required:** `YES — PHASE_B; currently NOT_RUN`

**Environment and stopping condition:** production-public only, with separate result-independent
stop predicates, new empty evidence directories, one clean-stop signal, completed writers, strict
validation, and independent acceptance.

**Private API:** `FORBIDDEN`

## Artifacts and delivery report

Record base/head/tree, target and verified remote ref, exact checks, independent receipt, both
fresh manifests/evidence identities and verdicts, zero activity, `UNKNOWN`s, non-claims, final
diff, and Git/remote state. Until the final gate, report the accepted
`7c36a3aa4fc9e7bf1ef2977eaeb0c75a620b0ae0` stage record separately from the unaccepted candidate.

## Definition of done

The consolidation is directly verified; the exact candidate is independently verified and
remote-bound; fresh Smoke and Soak each pass their unchanged contract under separate bindings;
the final stage record binds that exact replacement while preserving permission, capability,
`ESTABLISHED`, and next product closure `NONE`; no forbidden capability or historical rewrite
occurred; and this active task is removed in that accepted final change.
