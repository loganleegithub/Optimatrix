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

**Base commit:** `4b225ee1f199523fb052611d84612ec75c7abf78`

**Base tree:** `9e53c6233949348c5805e96ea1eefb5998bf4c49`

**Target branch/PR:** `codex/short-vol-fixed-contract-public-shadow-runtime`; Draft PR #5

## Business closure

**Given:** the single authorized production-public attempt is `CONSUMED_FAILED_NO_RETRY`. It
reached real anomaly activation, then failed closed while projecting a no-combo Underwriting fact
because the exact accepted upstream Radar episode identity was passed to a validator that accepts
only a canonical `sha256:` identity. The downstream failure summaries are complete and their
conservation is met, but the Radar run summary is absent, so the full evidence set is incomplete
and the forward closure is not accepted.

**When:** one bounded offline implementation repair preserves the exact upstream Radar episode
identity across the Underwriting boundary, rejects malformed impostors without weakening other
canonical identities, and preserves the existing legal downstream process-failure terminal.

**Then:** the real Radar episode identity no longer raises `Underwriting semantic identity must be
sha256:<64 lowercase hex>` on either the no-combo or quoted path; ordinary invalid identity still
fails closed; the existing downstream fatal path remains strictly readable and conserved; and the
runtime becomes eligible for independent exact-commit implementation acceptance only. No
production-public authority follows.

**Independent verification:** stable red tests using the actual Radar episode-identity format on
the exact base; focused owner/composition tests plus existing downstream process-failure
regressions; full `make check`; immutable digest and scope checks; an independent exact-commit
review; and local, remote-tracking, fresh remote, and PR-head equality.

**Valid zero/no-hit/UNKNOWN result:** no live or natural business result can satisfy this repair.
Offline tests must preserve `UNKNOWN`, null denominators, zero persisted downstream business counts,
and fail-closed invalid identities without creating Candidate, Entry, Position, Outcome, or cohort
evidence.

**Upstream prerequisite:** exact failed candidate and tree above, plus the sealed terminal record
for the consumed attempt. Old partial Radar artifacts and complete downstream failure summaries are
evidence of the defect only; they are never test fixtures, replay input, migrated evidence, or
authority for another run.

## Change declarations

**Market/Decision input contract change:** `NONE` — public sources, universe, causal boundaries,
currentness, official combo meaning, request timing, and missingness remain unchanged.

**Decision Policy change:** `NONE` — the Radar, Underwriting, and Position Policy bytes, identities,
fees, thresholds, actions, admission rules, and hard-close order remain unchanged.

**Outcome/evaluation contract change:** `NONE` — existing episode identity, terminal states,
Outcome meanings, conservation, denominators, compatibility, and non-claims remain unchanged. The
implementation is repaired to accept the already frozen upstream identity and emit the already
required terminal evidence.

**Stage/authorization change:** `APPROVED` — authorize this offline implementation-integrity repair
only. Permission remains `PUBLIC_SHADOW`; the evidence gate stays closed; every live command,
second attempt, private/account operation, execution, qualification, promotion, and deployment
action remains forbidden.

## Product operating behavior

The Radar-owned episode identity remains exactly
`runtime_identity × Radar_Policy_identity × instrument_name × activation_causal_seq` and is
not re-keyed, hashed again, or relabeled by the downstream owner. `short_vol_underwriting` accepts
that exact upstream semantic identity only at the declared field boundary while retaining strict
canonical `sha256:` validation for identities it owns. Malformed, truncated, cross-runtime,
cross-Policy, empty, or otherwise unproved values fail closed before an economic action.

The Online Runtime still owns one public client and one causal reducer. A fatal Shadow integrity
failure retains `PROCESS_FAILURE` / `FATAL_EVIDENCE_INTEGRITY`, stops without reconnect or retry,
and finalizes the existing downstream terminal summaries exactly once. The Radar contract writes
`RADAR_RUN_SUMMARY` only on clean operator or supervisor stop; failure may truthfully leave partial
Radar artifacts without a summary. No schema, enum, Policy, business denominator, network method,
or normal market persistence is added.

## Validation harness

Tests must construct an episode through the real `EpisodeTracker` activation path rather than
assign a fake `sha256:` episode id. They cover no-combo and quoted Underwriting projection, exact
identity preservation, malformed identity rejection, and unchanged owned-identity validation.
Existing failure regressions must continue to require complete-readable downstream summaries,
`PROCESS_FAILURE`, conservation, no retry, and no duplicate finalization while making no Radar
summary claim.

The sealed production-public directories are read-only evidence and are not replayed. No
production-public command is permitted by this task.

## Evidence boundary

**Proves:** exact contract-compatible identity handling on the repaired candidate without
regressing the existing deterministic downstream fatal-terminal behavior.

**Does not prove:** production-public success, a natural quote, Candidate quality, Shadow Entry,
Position or Outcome reachability, a usable cohort, Policy quality, edge, profitability, account
fees, fillability, execution, qualification, promotion, or deployment.

| Evidence class | Requirement |
|---|---|
| Direct behavior | REQUIRED |
| Production-public Radar | NOT_APPLICABLE / FORBIDDEN |
| Minimal-hit recomputation | NOT_APPLICABLE |
| Bounded stream reconstruction | NOT_APPLICABLE |
| Shadow forward Outcome | NOT_APPLICABLE |
| Qualification | NOT_APPLICABLE |
| Execution | NOT_APPLICABLE / FORBIDDEN |

## Scope

**In:** exact upstream Radar episode-identity validation at the downstream boundary; no-combo and
quoted projection; existing downstream fatal-terminal regression tests; authority/task consistency
and exact-commit delivery evidence.

**Out:** contract, Policy, schema, enum, formula, source, economic, admission, Position, Outcome, or
cohort changes; new dependencies or locks; replay, synthetic market evidence, live commands,
private/account methods, credentials, balances, margin, orders, fills, capital, execution,
qualification, promotion, persistent service, a second live invocation, `main`, merge, rebase,
force-push, or history rewriting.

**Owning modules:** `short_vol_underwriting` owns the declared semantic-identity validation and
`radar_runtime` owns its fixed-contract projection. Existing runtime terminal code, Radar evidence
schemas, and all three strategy Policies are read-only.

**Exact allowed files:**

```text
README.md
apps/radar_runtime/src/radar_runtime/fixed_contract_shadow.py
docs/authority/CURRENT_STAGE.md
packages/short_vol_underwriting/src/short_vol_underwriting/owner.py
tasks/SHORT_VOL_FIXED_CONTRACT_PUBLIC_SHADOW_FORWARD_EVIDENCE.md
tasks/SHORT_VOL_SHADOW_ATTEMPT_EVIDENCE_INTEGRITY.md
tests/test_authority_and_architecture.py
tests/test_fixed_contract_shadow.py
tests/test_shadow_cli_preflight.py
tests/test_short_vol_underwriting.py
```

## Contract

**Inputs and known-at rule:** the accepted Radar episode identity and its activation boundary remain
exact upstream facts. This repair may validate their declared structure and binding but may not
substitute a new identity or move any decision boundary.

**Durable output and identity:** unchanged. Existing Radar anomaly/atomic evidence and clean-stop
summary plus downstream object/summary formats only. Fatal downstream finalization remains exactly
once and binds the existing process-failure control; no Radar failure summary is introduced.

**Missing/invalid/UNKNOWN semantics:** a malformed or unbound episode identity is a fatal integrity
failure, never `UNKNOWN`, `NOT_EVALUATED`, or `ABSTAIN`. Ordinary missing public facts retain their
smallest-scope `UNKNOWN`/not-evaluable semantics. The resulting absent Radar run summary makes the
bounded evidence set incomplete, never a numeric zero; that absence on process failure remains
permitted and truthful.

**Persisted meaning and compatibility:** `COMPATIBLE`; no persisted identity formula, schema, enum,
unit, writer meaning, reader meaning, or historical artifact changes. The repair makes runtime
validation conform to the accepted upstream-semantic-identity rule.

**Business denominators:** unchanged. The failed attempt's downstream persisted counts may be
reported as zero because its complete summaries and conservation passed, while the overall business
result remains `NOT_EVALUABLE` because the Radar summary is absent. Files, exceptions, and test
cases are not business opportunities.

## Acceptance

### Direct behavior

1. A real composite Radar episode identity round-trips unchanged through no-combo and quoted
   Underwriting facts; no economic action is manufactured by unavailable atomic evidence.
2. Malformed, wrong-runtime, wrong-Policy, empty, and truncated upstream episode identities fail
   closed; canonical identities owned downstream remain exactly `sha256:<64 lowercase hex>`.
3. Existing fatal Shadow integrity regressions continue to write the downstream failure summaries,
   bind `PROCESS_FAILURE` / `FATAL_EVIDENCE_INTEGRITY`, pass downstream current/complete readers and
   conservation, and start no reconnect or retry; they do not introduce a Radar failure summary.
4. Stop/failure, duplicate, `UNKNOWN`, Candidate/admission, Position, Outcome, conservation, and
   established Radar regressions remain green.
5. Contracts, Policies, dependencies, lock, schemas, and files outside exact scope are unchanged.

### Required commands

- `make sync`
- focused tests: authority, Underwriting identity, fixed-contract projection, and existing
  downstream process-failure/conservation regressions
- `make check`
- `git diff --check`
- production-public command: `NOT_APPLICABLE / FORBIDDEN`
- replay or synthetic reconstruction: `NOT_APPLICABLE / FORBIDDEN`

### Real evidence

**Required:** NO. The consumed failed attempt is sealed defect evidence, not a retry fixture.

**Environment and stopping condition:** offline deterministic tests only.

**Required report:** root cause with file/symbol and red evidence; exact commit/tree/parent; changed
files; focused/full/diff/digest/scope results; independent review; remote branch and PR-head equality;
and explicit zero live/private/account/order/fill/capital activity.

**Private API:** FORBIDDEN.

## Sealed failed-attempt evidence

The one authorized attempt bound candidate `4b225ee1f199523fb052611d84612ec75c7abf78`, tree
`9e53c6233949348c5805e96ea1eefb5998bf4c49`, and the frozen `public-shadow-forward-001` external
manifest/evidence/log/terminal-record paths. It exited `1` after a fatal integrity error. Five Radar
anomaly files exist, but the Radar run summary is absent. Both downstream summaries are
`COMPLETE`, their complete reader passes, conservation is `MET`, and their persisted Candidate,
Entry, Position, Outcome, and aligned-pair counts are zero; the overall forward result remains
`INCOMPLETE`, `NOT_ACCEPTED`, and business-`NOT_EVALUABLE`.

Those paths are sealed append-only evidence. They may not be deleted, edited, completed
retroactively, migrated, relabeled, or reused. The single run is consumed and a second live
invocation remains forbidden.

The sealed controller terminal record is
`/Users/logan/Optimatrix-shadow/receipts/public-shadow-forward-001-terminal-record.json`, SHA-256
`1090b3d9b643c621721e59552fc0ca1e7b6a7616d9b6ec136c0660c936d62e45`, 26,919 bytes. It records
`FAIL` / `INCOMPLETE` only and grants no implementation acceptance or live authority.

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

**Artifact paths and digests:** direct test artifacts and exact Git evidence only. The failed live
paths remain external sealed inputs to the authority record, not implementation acceptance output.

**Policy/contract identities:** the six immutable identities above remain byte-identical.

**Commit/PR:** append-only commits on the existing task branch and Draft PR #5. Before publication,
the remote branch tip must equal that publication's expected parent. Prefer connector Git Database
`create_blob` / `create_tree` / `create_commit` / `update_ref(force=false)` actions; local push is
fallback only if connector writes are unavailable. Report exact commit, tree, parent, remote branch
tip, full compare range, and tests. No new branch, merge, rebase, or history rewrite.

**Unknowns and non-claims:** an offline repair is not production-public acceptance and cannot make
the sealed failed interval complete. It grants no second attempt, Candidate/Entry/Position/Outcome
reachability, usable cohort, edge, execution, or deployment claim.

## Definition of done

The exact identity mismatch has stable red tests and a minimal contract-compatible fix; the existing
legal downstream failure terminal remains green; focused/full/diff/digest/scope checks and
independent exact-commit review pass; local and all remote identities reconcile; zero live or
forbidden activity occurred; and the authority records only implementation repair. Any later
production-public attempt requires a new active `EVIDENCE_ONLY` task, new external paths, and
separate explicit live-run authorization.
