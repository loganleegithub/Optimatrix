# Task — SHORT_VOL_SHADOW_ATTEMPT_EVIDENCE_INTEGRITY

**Status:** ACTIVE

**Task kind:** `IMPLEMENTATION`

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md) /
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) /
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)

**Base commit:** `a7bb495a391cbf76377356c9b31b0360667104dd`

**Base tree:** `3d4eba9e3ec5dd2bb103da7e60463fe4ce6baee7`

**Target branch/PR:** `codex/short-vol-fixed-contract-public-shadow-runtime`; Draft PR #5

## Business closure

**Given:** the exact base runtime sends only positive-id `public/get_order_book` Shadow requests,
but its repository-owned downstream writer/current reader/complete reader do not independently
enforce every reconstructible frozen scheduled-attempt shape, terminal-source, same-boundary,
atomic Entry, provenance, and terminal-to-opportunity relationship after an attacker recomputes
affected identities.

**When:** one bounded implementation repair makes those existing contract rules fail closed in the
shared semantic and complete-graph validation paths without changing the owner, market source,
Policy chain, economics, or Outcome definitions.

**Then:** malformed or incomplete Admission and post-CLOSE attempt evidence cannot be written or
accepted; both legitimate not-requestable same-boundary branches and legitimate requestable
strictly-later branches remain round-trippable; the fixed-contract runtime returns to
`IMPLEMENTED_AWAITING_FORWARD_EVIDENCE` only after exact-commit independent acceptance.

**Independent verification:** stable red tests on the exact base, focused writer/current/complete
reader and owner round-trip tests on the repair, full `make check`, immutable digest checks,
independent exact-commit review, and local/remote/PR-head equality.

**Valid zero/no-hit/UNKNOWN result:** no market result can satisfy this offline integrity repair.
The two frozen not-requestable markers and their exact `UNKNOWN`/known-unavailable semantics must
be tested directly; no production-public command is permitted.

**Upstream prerequisite:** exact base `a7bb495a391cbf76377356c9b31b0360667104dd`, whose fixed-contract
Shadow runtime is implemented but whose evidence gate remains closed.

## Change declarations

**Market/Decision input contract change:** `NONE` — no source, known-at rule, currentness rule,
request timing, official combo meaning, or missingness meaning changes.

**Decision Policy change:** `NONE` — the Radar, Underwriting, and Position Policy bytes, identities,
fees, thresholds, admission decision, Position action, and hard-close order remain unchanged.

**Outcome/evaluation contract change:** `NONE` — terminal states, causal-first exit, opportunity
classification, Outcome economics, cohort denominators, conservation, and compatibility remain
unchanged; the implementation is repaired to enforce their already frozen evidence relations.

**Stage/authorization change:** `APPROVED` — activate only this offline implementation-integrity
repair. Permission remains `PUBLIC_SHADOW`, the evidence gate remains `CLOSED`, and every live,
private/account, order, fill, capital, qualification, promotion, and deployment action remains
forbidden.

## Product operating behavior

The existing runtime remains the sole process and sole public client. Admission and requestable
post-CLOSE attempts use one process-global positive integer id, exact method
`public/get_order_book`, and exact `{instrument_name, depth: 10000}` params. A not-requestable
post-CLOSE attempt uses exactly one frozen marker with null params and atomically creates its
terminal and attempt-owned close-opportunity evaluation at first CLOSE. Requestable terminals are
strictly later. An `ENTRY_EMITTED` admission terminal and its Entry are one atomic boundary and
consume the same official combo source. No network behavior is added by this task.
The reader proves the exact request JSON shape and the cross-object identities persisted by this
schema. It does not possess the upstream market-catalog preimage needed to authenticate an
arbitrary alternative non-empty `instrument_name` against the opaque canonical combo identity.

## Validation harness

Tests mutate complete evidence while recomputing every affected content identity and reference so
that rejection proves semantic validation rather than a stale filename or hash. Direct owner tests
also prove both legitimate not-requestable paths can finalize complete evidence. Writer,
`read_current_evidence`, and `read_complete_evidence` are separately exercised where their proof
boundaries differ.

## Evidence boundary

**Proves:** repository-owned Shadow evidence rejects illegal request capability, identifier,
marker/params shape, terminal source/response projection, causal-boundary, atomic Entry,
provenance consistency, and missing ordinary terminal-opportunity relations covered by the frozen
contracts.

**Does not prove:** production connectivity, a natural Candidate/Entry/Position/Outcome, a usable
cohort, Policy quality, edge, profitability, fillability, execution, that an illegal private
request actually occurred, or authenticity of an arbitrary syntactically valid external source or
instrument name whose upstream preimage is not persisted by the frozen one-hop schema.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE / FORBIDDEN |

## Scope

**In:** exact scheduled-attempt payload-shape validation; Admission/post-CLOSE terminal state and
source-projection validation; exact attempt-control provenance; graph-wide downstream request-id uniqueness;
attempt/schedule/Entry boundary and source binding; post-CLOSE terminal-to-opportunity forward and
reverse closure; legal not-requestable round trip; direct authority and regression tests.

**Out:** contracts, Policy files, economics, detector behavior, source ingestion, runtime sender,
transport, CLI, manifest schema, dependencies, locks, live evidence, replay, qualification,
execution, and persistent service work.

**Owning module/artifact:** `short_vol_underwriting` validation/evidence boundary and its direct
tests; permission routing remains owned by `CURRENT_STAGE.md`.

**Exact allowed files:**

```text
README.md
docs/authority/CURRENT_STAGE.md
packages/short_vol_underwriting/src/short_vol_underwriting/evidence.py
packages/short_vol_underwriting/src/short_vol_underwriting/validation.py
tasks/SHORT_VOL_SHADOW_ATTEMPT_EVIDENCE_INTEGRITY.md
tests/test_authority_and_architecture.py
tests/test_complete_downstream_evidence.py
tests/test_short_vol_underwriting.py
```

## Contract

**Inputs and known-at rule:** unchanged exact downstream envelopes and local object graph. Unknown,
stale, malformed, or missing facts remain `UNKNOWN`; evidence cannot convert an invalid request
shape or relationship into an accepted observation.

**Durable output and identity:** no new object kind or identity. Existing identities are recomputed
as before, but a matching hash is necessary and no longer sufficient when semantic members or
relationships violate the frozen contract.

**Missing/invalid/UNKNOWN semantics:** malformed method/id/marker/params shape, source projection,
provenance, and impossible causal or reverse-closure graphs fail closed.
`NOT_REQUESTABLE_UNKNOWN` remains a legal
same-boundary `UNKNOWN / QUOTE_OR_ATTEMPT_UNKNOWN`; known atomic unavailability remains a legal
same-boundary `INELIGIBLE / KNOWN_ATOMIC_UNAVAILABLE`.

**Persisted meaning and compatibility:** `COMPATIBLE`; no schema member, unit, contract, Policy,
identity formula, or accepted business meaning changes. Invalid historical bytes never become
valid by compatibility claim.

**Business denominators:** unchanged. Attempt and opportunity counts continue to count distinct
contract identities; zero or unknown denominators remain `null`, never zero.

## Acceptance

### Direct behavior

1. Writer/current/complete paths reject non-public methods, non-positive ids, invalid markers,
   missing/extra/empty params members, depth other than 10000, and graph-wide
   Admission/post-CLOSE id reuse after identities are recomputed. A different non-empty
   `instrument_name` is outside reader authentication without the upstream catalog preimage.
2. Admission and post-CLOSE terminal source/matched-response matrices and exact attempt-control
   provenance fail closed; `ENTRY_EMITTED` is atomic and source-bound to its Entry.
3. Admission and requestable post-CLOSE terminals are strictly later than their schedule; the two
   not-requestable marker terminals and attempt-owned opportunities are exactly same-boundary.
4. Every ordinary non-success post-CLOSE terminal has exactly one correctly classified,
   source-bound attempt-owned opportunity; missing, duplicate, orphan, or mismatched relations fail.
5. Existing requestable, stop/failure, `UNKNOWN`, duplicate, conservation, and Radar regressions
   remain green.

### Required commands

- `make sync`
- focused tests: `tests/test_complete_downstream_evidence.py`,
  `tests/test_short_vol_underwriting.py`, and `tests/test_authority_and_architecture.py`
- `make check`
- `git diff --check`
- production-public command: `NOT_APPLICABLE / FORBIDDEN`
- independent recomputation or reconstruction command: `NOT_APPLICABLE`; adversarial identity
  recomputation is covered directly by the focused tests

### Real evidence

**Required:** NO

**Environment and stopping condition:** offline deterministic tests only. No manifest, evidence
directory, receipt, Radar process, or Shadow process may be created.

**Required report:** exact commit/tree/parent, changed files, red/green evidence, focused/full
results, six immutable digests, remote branch/PR head, limitations, and zero live/private activity.

**Private API:** FORBIDDEN.

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

**Artifact paths and digests:** `NOT_APPLICABLE`; source/tests/authority only.

**Policy/contract identities:** the six immutable identities above must remain byte-identical.

**Commit/PR:** append-only commits on the existing task branch and Draft PR #5; connector-first
Git Database publication with `force=false`, or verified non-force local push only if connector
write actions are unavailable. No branch creation, rebase, merge, or history rewrite.

**Unknowns and non-claims:** no claim of market activity, online acceptance, cohort usability,
qualification, promotion, execution, persistent deployment, or authentication of opaque upstream
source/instrument preimages that this compatible schema does not persist.

## Definition of done

All direct behavior and complete-graph tests pass on one exact remote-equal commit; the six
immutable digests and dependency/lock bytes are unchanged; the diff contains only the allowed
scope; the task remains the sole active closure until Codex independently accepts the repair. Only
a later append-only authority transition may remove this task and activate a separately bounded
`EVIDENCE_ONLY` production-public run.
