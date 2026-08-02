# Task — Short Vol runtime evidence slimdown

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md) /
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `d8524ac5375d8c339d99afda559de2196871b83e`

**Target branch:** `codex/runtime-evidence-slimdown`

## Business closure

**Given:** `serve-shadow` is the sole continuous public-Shadow product path, all earlier runtime
and evidence artifacts were deleted, and no current product consumer uses Radar operational
diagnostics schema 6, the manifest-bound `observe-shadow` command, or the complete downstream
evidence reader to make a Radar, Underwriting, Shadow, Position, Outcome, health, or readiness
decision.

**When:** acceptance-only diagnostic ledgers, the bounded manifest/terminal-proof harness,
duplicate terminal graph validation, and their dead runtime state are removed.

**Then:** one process still performs the unchanged public business chain and persists only current
business objects plus a minimal Radar business summary; no acceptance controller, historical
compatibility layer, or complete-graph proof runs in the continuous product path.

**Independent verification:** direct reducer, persistent-service, Workbench, current-object writer
and reader tests plus repository search proving the removed public entry points and diagnostic
ledgers are absent.

**Valid zero/no-hit/UNKNOWN result:** unchanged. No anomaly, Candidate, Entry, close opportunity,
or Outcome may be manufactured; missing business facts remain `UNKNOWN` at the same consumer.

**Upstream prerequisite:** the current persistent public-Shadow composition and current object
writer/reader already pass deterministic offline tests.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE; this task authorizes offline code and durable-report
simplification only and does not authorize production-public activity or deployment.

## Product operating behavior

`serve-shadow` remains one modular-monolith process:

```text
Deribit public state -> Radar -> Underwriting -> Shadow -> Position -> Outcome -> Workbench
```

Relevant settled facts continue through the same reducer and owner. Normal market state remains
bounded and transient. Anomaly, atomic quote, Underwriting, Shadow, Position and Outcome objects
retain their current identities and semantics. Clean stop writes one Radar summary containing
coverage and business transition counts, without an operational acceptance ledger.

## Validation harness

Use deterministic tests only. Build and validate the minimal current Radar summary, exercise
clean stop and persistent Shadow termination, and verify current downstream objects through the
current reader. Do not run Deribit, a local persistent service, a probe, or a historical evidence
reconstruction.

## Evidence boundary

**Proves:** unused acceptance-only code is absent and the unchanged business path still passes its
direct tests.

**Does not prove:** production connectivity, uptime, latency under real load, Radar correctness,
Policy quality, fillability, profitability, actual exposure, or PnL.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** Radar run-summary projection/validation, runtime-only diagnostic accounting, persistent
Shadow composition, manifest-bound `observe-shadow`, downstream complete-reader/terminal-summary
surfaces, Workbench dead state, direct tests, and exact authority/contract statements that require
those removed surfaces.

**Out:** market sources, universe, source currentness, continuity decisions, detector formulas or
thresholds, all three Policies, Underwriting actions, Shadow admission, Position actions, Outcome
selection, current downstream object schemas, Workbench schema, deployment, and private APIs.

**Owning modules/artifacts:** `radar_runtime`, `short_vol_radar.evidence`, current-only portions of
`short_vol_underwriting.evidence`, and their direct contracts/tests.

## Contract

**Inputs and known-at rule:** unchanged public facts and causal boundaries.

**Durable output and identity:** anomaly and atomic-quote events are unchanged. The current
`RADAR_RUN_SUMMARY` drops `operational_diagnostics` and retains only coverage and business counts.
Current downstream business-object envelopes are unchanged.

**Missing/invalid/UNKNOWN semantics:** required fields in the smaller current objects still fail
closed; business missingness and `UNKNOWN` behavior are unchanged.

**Persisted meaning and compatibility:** deleted diagnostics-schema-6 summaries and deleted
manifest-bound complete downstream directories are `NOT_COMPARABLE`; they are not migrated or
accepted. All historical artifacts are already absent. The smaller current summary and current
downstream object reader are the only supported repository-owned readers.

**Business denominators:** coverage duration, detector evaluations, episodes, atomic availability,
Underwriting opportunities, Entries and Outcomes are unchanged. Removed RPC/message/diagnostic
counts are not business denominators.

## Acceptance

1. One minimal current Radar summary writes and validates without `operational_diagnostics`.
2. Current anomaly, atomic quote and downstream business objects retain exact behavior.
3. `observe-shadow`, manifest/complete-reader APIs, operational Soak accounting, retained
   diagnostic interval ledgers, duplicate online terminal graph validation and dead fields are
   absent.
4. Persistent service clean stop, reconnect/failure, Workbench publication and read-only HTTP tests
   remain green.

Required commands: focused evidence/runtime/service/Workbench tests, repository search, and
`make check`. Live and reconstruction commands are forbidden and not applicable.

## Definition of done

The continuous business path is unchanged; only current business evidence remains; direct tests
and `make check` pass; the final diff contains no new infrastructure or compatibility path; and
remote state, non-claims and any remaining defensive surface are reported truthfully.
