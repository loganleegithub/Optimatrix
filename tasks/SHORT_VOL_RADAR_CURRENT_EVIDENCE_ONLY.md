# Task — Short Vol Radar current evidence only

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `ec0b83023763aa56e3d6544f89b144712ddf0b42`

**Target branch:** `codex/radar-current-evidence-only`

## Business closure

**Given:** the production Radar writer emits diagnostics schema version 6, the production reader
accepts version 6, historical evidence directories have been deleted, and no production consumer
calls a version-2 through version-5 or legacy reader.

**When:** obsolete version-2 through version-5 readers, legacy Soak accounting, duplicate contract
text, and tests that exist only for those retired paths are removed.

**Then:** the repository has one Radar evidence contract: the current writer emits version 6 and
the current reader accepts exactly version 6 while rejecting every other version.

**Independent verification:** direct writer/reader tests plus repository search proving the
retired public entry points and version branches are absent.

**Valid zero/no-hit/UNKNOWN result:** unchanged. This task does not alter detector, coverage,
missingness, event counts, or any business denominator.

**Upstream prerequisite:** current version-6 writer and reader behavior already passes direct
offline tests.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE; only offline implementation and deterministic verification
of this active task are authorized.

## Product operating behavior

Runtime behavior and durable version-6 object meaning remain unchanged. No compatibility queue,
migration, fallback reader, or historical archive is introduced.

## Validation harness

Create a current version-6 summary and validate it. Mutate the version to a non-current integer,
remove it, or give it a non-integer value and require the current reader to fail closed. Repository
search must find no retired version-specific reader or legacy Soak accounting API.

## Evidence boundary

**Proves:** one current Radar evidence schema is emitted and accepted; unsupported versions fail
closed; obsolete compatibility code is gone.

**Does not prove:** production Radar correctness, uptime, market coverage, event frequency,
Policy quality, Shadow economics, execution, or PnL.

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

**In:** Radar evidence writer/reader compatibility code, direct tests, and exact authority/contract
statements that require retired readers.

**Out:** runtime reducer, market inputs, detector/Underwriting/Shadow/Position/Outcome semantics,
Policies, Workbench, downstream evidence, live execution, deployment, and historical reconstruction.

**Owning module/artifact:** `short_vol_radar.evidence` and the Short Vol Radar evidence contract.

## Contract

**Inputs and known-at rule:** unchanged version-6 summary and evidence-directory inputs.

**Durable output and identity:** unchanged `RADAR_RUN_SUMMARY` with integer
`operational_diagnostics_schema_version = 6`.

**Missing/invalid/UNKNOWN semantics:** missing, non-integer, or non-6 diagnostics versions fail
closed; business `UNKNOWN` semantics are unchanged.

**Persisted meaning and compatibility:** version 6 is `COMPATIBLE` with the current writer and
reader. Versions 2–5 and legacy objects are `NOT_COMPARABLE` and unsupported; there is no migration.

**Business denominators:** unchanged and not exercised by compatibility removal.

## Acceptance

1. A current version-6 directory passes the current reader.
2. Missing, non-integer, and non-6 diagnostics versions fail closed.
3. Retired version-specific reader/accounting entry points and their contract promises are absent.

Required commands: focused evidence and authority tests, repository search, and `make check`.
Production-public commands and real evidence are not applicable and forbidden.

## Definition of done

Only current version-6 evidence code and text remain; direct tests and `make check` pass; the final
diff changes no business semantics, stage permission, or remote state.
