# Task — Persistent Shadow operability and trader workbench repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contract(s):**
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `7ac3d999edaaaa48b5a920a07c7e9e9fa6cbd20b`

**Target branch/PR:** `codex/persistent-shadow-runtime-workbench-repair`, Draft PR against `main`

## Terminal-goal delegation

The user's 2026-08-01 instruction `停止并修复` closes the consumed observation under its exact
single-stop protocol and authorizes one bounded offline repair. The repair may amend the persistent
service/workbench implementation contract, owning runtime projection, graph-independent downstream
write validation, direct tests, authority, and this task. It may not start another public process,
reuse the consumed state root, alter a Policy or business Decision, call a private/account API,
create an order or fill, deploy, merge, promote, or infer live authority from green tests.

## Business closure

**Given:** the one authorized persistent observation sealed as complete process-failure evidence
after the service event loop stayed near one CPU core, repeatedly lost currentness, accumulated
6,442 graph-independent Underwriting availability objects, and exposed a projection that rendered
business `null`, `NOT_EVALUATED`, and not-applicable fields as visually identical `UNKNOWN` values.

**When:** the owning hot path avoids repeated whole-history work whose result cannot change, while
the immutable workbench projection carries settled display metadata and the browser formats each
business state according to its declared meaning.

**Then:** every settled runtime transaction still publishes one atomic read-only snapshot, but
unchanged downstream history does not trigger repeated grouping/relationship work; individual
availability objects retain strict validation without redundant graph validation; and a trader can
distinguish actionable facts, true `UNKNOWN`, `NOT_EVALUATED`, not-applicable fields, and empty
panels without reading hashes or raw timestamps.

**Independent verification:** direct regression tests count expensive work at the owning boundary,
exercise exact writer validation and cache invalidation, execute the browser fail-closed and display
semantics, and render the local page at a trader-sized viewport. A separate read-only reviewer binds
the final exact commit and confirms that Decision/evidence identities and live authority did not
change.

**Valid zero/no-hit/UNKNOWN result:** true missing, stale, or discontinuous facts remain
`UNKNOWN`; unavailable Underwriting remains `NOT_EVALUATED` with no action; not-applicable display
fields render `N/A`; empty panels and zero/unknown denominators never become a business zero.

**Upstream prerequisite:** the consumed observation is terminal and independently audited. Its
terminal audit at
`/Users/logan/Optimatrix-public-shadow-observation/deployment/terminal-audit.json`, SHA-256
`47d68c9603b4abf60b81b6af11a2e9d5f2b966579c75405ec7e4f1e353af0a2e`, records
`PASS_COMPLETE_PROCESS_FAILURE_EVIDENCE_ONLY`, `NOT_ACCEPTED_PROCESS_FAILURE`, and 24-hour
`NOT_MET`. It authorizes no retry and is not repair evidence.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — close the consumed persistent observation, forbid all
live commands, and authorize only this offline implementation repair and Draft PR.

## Product operating behavior

The one-process public-only runtime, one reducer, three frozen Policies, fixed-contract downstream
owner, minimal durable evidence, and loopback GET/HEAD-only workbench remain unchanged. A settled
transaction still hands one coherent post-Shadow state to the snapshot publisher. Repeated reads of
unchanged downstream history may be cached by an exact writer revision; a new durable object
invalidates that cache before the next publication. Graph-independent availability objects are
validated individually but do not trigger relationship validation that cannot consume them.

The browser remains display-only. It may sort, filter, translate, format, and progressively reveal
fields from one immutable snapshot. It may not recompute Radar, Underwriting, Position, or Outcome;
open a Deribit connection; call a private endpoint; mutate Policy; or expose an order/control route.

## Validation harness

Use direct deterministic fixtures with production-shaped object counts and repeated settled
transactions. Count projection rebuilds and relationship-validator calls instead of relying on a
wall-clock microbenchmark. Execute the existing Node browser harness and a local loopback browser
render using synthetic immutable snapshots. No public/live observation is part of this task.

## Evidence boundary

**Proves:** cache invalidation and atomic publication behavior; strict per-object validation;
unchanged durable identities; browser state semantics, escaping, fail-closed recovery, local
filtering, human-readable metadata, and bounded page overflow.

**Does not prove:** production CPU percentage, sustained public currentness, 24x7 availability,
natural opportunity frequency, Policy quality, fillability, private/account truth, orders, fills,
actual exposure, fees, PnL, qualification, promotion, or deployment safety.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE — live commands are forbidden |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE |

## Scope

**In:** this task, `CURRENT_STAGE`, `README`, the persistent service contract, direct authority tests,
`radar_runtime` settled projection/metadata/browser assets, graph-independent downstream writer
validation, and direct regression/browser tests.

**Out:** Radar formula/state changes; Policy files; Underwriting/Position/Outcome economics or
schemas; evidence migration; generic queues/databases/services; public deployment; a second run;
private/account APIs; credentials; orders; fills; capital; qualification; promotion; execution.

**Owning module/artifact:** `apps/radar_runtime/src/radar_runtime/workbench.py`,
`apps/radar_runtime/src/radar_runtime/fixed_contract_shadow.py`,
`apps/radar_runtime/src/radar_runtime/service_evidence.py` (changed contract digest binding only),
`packages/short_vol_underwriting/src/short_vol_underwriting/evidence.py`, their direct tests, and
the exact `README`/authority/contract/task files above.

## Contract

**Inputs and known-at rule:** the workbench consumes only the same fully settled reducer,
downstream writer revision, and adapter-owned display metadata available at the publication causal
boundary. Cached downstream projection data is reused only while that exact revision is unchanged.

**Durable output and identity:** existing Radar, downstream, lifecycle, and terminal identities and
bytes are unchanged. The workbench operational projection advances to schema version 2 because it
adds settled human-readable structure metadata and explicit display semantics; it remains
non-durable and non-authoritative.

**Missing/invalid/UNKNOWN semantics:** missing display metadata remains null and is never guessed.
Unsupported or malformed projection versions fail the whole browser view closed. True business
`UNKNOWN`, `NOT_EVALUATED`, `N/A`, empty, and numeric zero remain separate.

**Persisted meaning and compatibility:** durable evidence is `COMPATIBLE` because no persisted
schema, identity, writer bytes, or reader contract changes. Workbench projection version 1 and
version 2 are `NOT_COMPARABLE` as complete operational snapshots; the version-2 browser rejects
unsupported versions.

**Business denominators:** unchanged. UI row counts and filters are presentation counts, not Radar
episodes, Underwriting opportunities, Candidates, Entries, Positions, Outcomes, or rates.

## Acceptance

### Direct behavior

1. Repeated settled transactions with an unchanged writer revision perform downstream history
   projection once; a newly published object invalidates the cache before the next atomic snapshot.
2. `UNDERWRITING_AVAILABILITY_EVALUATION` still passes exact object/schema/identity/provenance
   validation but skips graph validation that has no relationship rule for that kind; every other
   kind preserves full relationship validation.
3. Projection version 2 joins only settled scope/structure display metadata and never alters persisted
   objects, Policy outputs, or business enums.
4. The browser displays true `UNKNOWN`, `NOT_EVALUATED`, `N/A`, empty, and proven zero distinctly;
   exposes a concise system/Radar/Candidate conclusion; sorts and filters locally; formats units and
   time; and keeps raw exact facts in read-only detail.
5. Fetch, HTTP, JSON, schema, or render failure hides all cached business panels; loopback-only,
   GET/HEAD-only, escaping, CSP, and absence of private/order/Policy surfaces remain green.
6. A 1,214-pixel viewport has no document-level horizontal overflow; only explicit table containers
   may scroll horizontally.

### Required commands

- `make UV='python3 -m uv' sync`
- focused tests: `.venv/bin/pytest -q tests/test_trader_workbench.py tests/test_persistent_service.py tests/test_complete_downstream_evidence.py tests/test_authority_and_architecture.py`
- repository gate: `make check`
- production-public command: `NOT_APPLICABLE — live commands forbidden`
- independent read-only exact-commit review after final commit

### Real evidence

**Required:** NO

**Environment and stopping condition:** deterministic offline tests and local loopback rendering
only; no Deribit connection or persistent service process.

**Required report:** final commit/tree, changed contract digest, focused/full checks, counted cache
and validator behavior, rendered viewport result, exact scope, `UNKNOWN` semantics, non-claims, Git
state, remote equality, and Draft PR state.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** local test/render artifacts are diagnostic and not business
evidence. The final report records only the changed service-contract digest and Git identities.

**Policy/contract identities:** all three Policy byte digests remain unchanged. The changed service
contract receives a new exact content digest and applies only to a future separately authorized
runtime.

**Commit/PR:** append-only non-force branch and one Draft PR; no merge or deployment authority.

**Unknowns and non-claims:** offline acceptance does not establish production CPU, currentness,
uptime, Policy quality, opportunity frequency, fillability, private/account truth, orders, fills,
actual exposure, fees, realized PnL, qualification, promotion, or execution safety.

## Definition of done

The minimal owning-module repair and direct regressions pass; the local rendered workbench is
trader-readable and fail-closed; final diff contains only this closure; an independent reviewer
passes the exact commit; branch and Draft PR are published without force; and live commands remain
forbidden. A later production-public validation requires its own task, state root, process, and
explicit authority.
