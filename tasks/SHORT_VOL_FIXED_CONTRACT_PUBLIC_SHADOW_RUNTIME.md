# Task — SHORT_VOL_FIXED_CONTRACT_PUBLIC_SHADOW_RUNTIME

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

**Base commit:** `f0d852f46756b0f917a0e671a0de2644a34bfd10`

**Target branch/PR:** `codex/short-vol-fixed-contract-public-shadow-runtime`; Draft PR to `main`

## Business closure

**Given:** the production-public Radar is established, the accepted Underwriting/Position and
Outcome/forward-cohort contracts are frozen, and the exact three-Policy chain below is selected
without prior downstream Outcome evidence.

**When:** one bounded implementation adds the pure downstream owner and composes it into the
existing Radar process so that the accepted contracts are executable from one settled causal
stream, directly tested, and delivered as one exact remote-equal candidate.

**Then:** the repository contains one fixed-contract, fixed-Policy production-public Shadow
runtime capable of producing the complete accepted Underwriting, Candidate/admission, Shadow
Entry, Position/hard-close, close-opportunity, rejected-counterfactual, Outcome, aligned
`NO_TRADE`, and forward-cohort object families. The implementation task may terminate only as
`IMPLEMENTED_AWAITING_FORWARD_EVIDENCE`; it does not establish an online cohort or authorize a
production-public run.

**Independent verification:** direct deterministic tests against both accepted contracts,
existing Radar regressions, complete `make check`, exact Policy byte/digest checks, independent
review of one exact commit/tree, and post-push equality of the bounded remote ref.

**Valid zero/no-hit/UNKNOWN result:** offline tests may validly exercise zero Candidate, zero
Entry, zero close opportunity, zero mature Outcome, or explicit `UNKNOWN`, but none alone
satisfies this closure. Direct tests must make every required positive, negative, race,
strictly-future, hard-close, censoring, conservation, duplicate, malformed, and mixed-identity
path independently reachable. A later live zero/no-hit/UNKNOWN result belongs only to a separate
`EVIDENCE_ONLY` task.

**Upstream prerequisite:** accepted `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`, active
`SHORT_VOL_UNDERWRITING_POSITION`, active `SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`, and the exact
three immutable Policy files below.

## Change declarations

**Market/Decision input contract change:** `NONE` — implement the already accepted
production-public known-at, completeness, currentness, post-Candidate refresh, and post-entry
lifecycle semantics without adding a source, changing a boundary, or using private/account data.

**Decision Policy change:** `APPROVED` — select the exact ordered tuple
`[Radar Policy identity, Underwriting Policy identity, Position Policy identity]` frozen below.
The tuple is not a Policy, semantic identity, manifest, or artifact. The only cross-family
identity is the accepted contract's `OutcomeContractIdentity`, which consumes those three
identities in that order.

**Outcome/evaluation contract change:** `NONE` — implement the accepted strictly-future exit,
four terminal states, rejected counterfactual, aligned `NO_TRADE`, conservation, provenance,
writer, and reader semantics byte-for-byte without reinterpretation.

**Stage/authorization change:** `APPROVED` — activate only this construction task. Permission
remains `PUBLIC_SHADOW`; the accepted implemented runtime capability remains
`PRODUCTION_PUBLIC_SHORT_VOL_RADAR` before and after this implementation task. The downstream
candidate has its own narrower terminal status. Only local construction, offline tests,
append-only commits, non-force push, and a Draft PR are authorized. Live/public observation,
private/account API, credentials, orders, fills, capital, qualification, promotion, persistent
deployment, merge, and stage acceptance remain forbidden.

## Construction and evidence gates

`SHORT_VOL_PUBLIC_SHADOW_TERMINAL_GOAL_DELEGATION` opens the implementation leg for this exact
task, base, branch, contracts, and Policy chain. It does not create a second delegation and does
not open an evidence gate.

1. This task owns implementation, direct tests, independent exact-candidate review, non-force
   branch delivery, and a Draft PR only.
2. Green tests, a pushed branch, a Draft PR, or the terminal label
   `IMPLEMENTED_AWAITING_FORWARD_EVIDENCE` do not prove an online cohort, business stability,
   Policy quality, edge, profitability, fillability, or execution.
3. After accepted implementation, this task is physically removed and the sole next closure
   returns to `NONE`.
4. A later production-public cohort requires a new `EVIDENCE_ONLY` task with runtime and Policy
   changes forbidden. That task must bind the exact candidate commit/tree/verified remote ref,
   all three Policy paths and digests, the accepted Outcome contract identity, one new empty
   downstream external evidence directory and one separate Radar evidence directory, exact
   process argv/cwd/checks, pre-bound start/cutoff/stop triggers, a result-independent clean-stop
   predicate, emergency-stop authority, and explicit non-claims. Contract digests not present in
   the accepted manifest schema remain task/report/object-schema bindings rather than extra
   manifest members.

The implementation terminal matrix is exact:

```text
Current permission boundary = PUBLIC_SHADOW
Implemented runtime capability = PRODUCTION_PUBLIC_SHORT_VOL_RADAR
Production Short Vol Radar = ESTABLISHED
Fixed-contract public Shadow runtime = IMPLEMENTED_AWAITING_FORWARD_EVIDENCE
Sole authorized next product-capability closure = NONE
Evidence gate = CLOSED
Live commands = FORBIDDEN
Active implementation task = physically absent
```

## Frozen Policy chain

The fixed ordered choice is:

1. Radar:
   `policies/short-vol-fixed-public-shadow-radar.json`,
   `sha256:2bcb780e6a9bab0982e59a70929e0150f1113d39452fcdb35894e293431f93d4`;
2. Underwriting:
   `policies/short-vol-fixed-public-shadow-underwriting.json`,
   `sha256:be056d7fad71668954103e1e383372c3b03db9b27b8d03ce0a030d39285629af`;
3. Position:
   `policies/short-vol-fixed-public-shadow-position.json`,
   `sha256:498a298be50cb356f43886ae7ba02d1f6da065233ae9b2b52e9a230cf7f9c439`.

The Radar file is the exact 1,405-byte accepted operational-soak Policy copied byte-for-byte. The
Underwriting file embeds the exact Radar digest; the Position file embeds the exact Underwriting
digest. All three target `0.1 BTC`. The two downstream files share exact currentness budgets and
fee metadata.

The fixed downstream values are engineering choices for a first forward cohort, not conclusions
from prior Outcome evidence. The report label is
`POLICY_CHOICE_WITHOUT_PRIOR_OUTCOME_EVIDENCE`; the later cohort baseline label is
`NON_QUALIFIED_FORWARD_OBSERVATION_BASELINE`. Neither label is a Policy field.

The Deribit fee source was retrieved at `2026-07-30T10:47:09Z`. Because implementation and every
later evidence interval are after preparation and may begin no earlier than the page's published
change boundary, the exact schedule label is `FEE_TIER_CHANGES_EFFECTIVE_2026-08-01`. The official
table keeps Standard linear-options maker/taker at `0.0003` with the 12.5% cap. The page's update
timestamp is not presented as an effective date. No production-public interval may start before
the stated schedule becomes effective, and this immutable chain never silently follows a later
webpage change.

Contract byte identities frozen by this task are:

- Radar contract:
  `sha256:b9733ad0c90837338b88fb5b6eb66ad8eed448cce6372a3f527988395087b3fe`;
- Underwriting/Position contract:
  `sha256:9cbaecf57fb1db0dedf782a4ab002b655e43319a1ad7c5880db3d7b4682d4b03`;
- Outcome/forward-cohort contract:
  `sha256:61a032fe0fe265d66a38bcbb1a3c8498409664fedbda2c8bd0a245180581a695`.

## Product operating behavior

The existing `radar_runtime` remains the sole process composer, transport owner, public Deribit
client, ingress boundary, outbound sender/queue, request-id allocator, clock/control stream, and
Radar evidence owner. It projects settled immutable facts to one pure downstream owner and maps
that owner's typed request intent back to the existing sender. No second client, queue, service,
database, workflow engine, or replay calculator is permitted.

The downstream owner deterministically evaluates Underwriting availability/action, Candidate
activation and the exact ten-reason terminal invalidation order, one Candidate-scoped admission
refresh and terminal outcome, one-entry slot consumption, Shadow Entry economics, Position
evaluation/action and the exact nine-reason hard-close order/latch, close quote/opportunity, the
accepted strictly-future exit and rejected-counterfactual reducers, terminal Outcome, aligned
pair, and cohort conservation.

After Entry, the Position lifecycle remains independent of the Radar episode. The composer
continues the accepted catalog, platform, clock, index, ticker, Delta/IV, combo subscription, and
Candidate/Position-scoped RPC lifecycles required by the contracts. On clean stop or fatal
failure, it preserves the accepted Outcome contract's terminal order. Clean stop and authorized
emergency stop execute exactly: open the barrier and reject new work/enrollment; stop producers;
settle accepted application events; settle accepted send/failure/cancellation/response/deadline
controls; apply qualifying first exit/maturity; commit one immutable stop boundary; terminalize
every still-pending admitted/rejected post-CLOSE attempt as `CENSORED` owned by `STOP` and
transition every pending admitted, rejected, and aligned object to `CENSORED_AT_STOP`; then durably
write terminal objects and the conservation summary. A pending admission attempt is never
`CENSORED`: before Outcome terminalization it consumes the Candidate's exact ten-reason order and
ends as exactly one of `ENTRY_EMITTED | KNOWN_COMPLETE_NO_ENTRY |
KNOWN_INVALIDATED_BEFORE_REFRESH | UNKNOWN_CONSUMED`; a committed runtime-ending barrier is the
known `RUNTIME_OR_CODE_IDENTITY_CHANGED` invalidation when no earlier reason/fact already owns the
terminal outcome. Failure uses the same accepted-fact drain, a failure boundary, post-CLOSE
`CENSORED` attempts owned by `FAILURE`, and `CENSORED_AT_FAILURE`. An ordinary terminal accepted
before the barrier remains ordinary. If writer/directory failure prevents complete terminal
publication, the directory is `INCOMPLETE/invalid`; no terminal-state or conservation success is
inferred. Existing Radar writer/readers, schemas, sealed compatibility, and its separate evidence
directory remain unchanged.

The existing guarded `observe` command remains unchanged. Construction adds one separately guarded
`observe-shadow` composition accepting the exact Outcome manifest path plus a distinct Radar
evidence-directory path; it refuses to start before pure manifest/Policy validation and adapter
preflight succeed. The pure owner validates schema and identities without I/O. The runtime adapter
alone performs Git/remote/worktree/path/directory preflight and public transport I/O.

## Frozen upstream durable interface

The Underwriting/Position family uses exactly these implementation object kinds; no other
upstream kind is admitted:

```text
UNDERWRITING_AVAILABILITY_EVALUATION
UNDERWRITING_ACTION
CANDIDATE_ACTIVATION
CANDIDATE_INVALIDATION
ADMISSION_ATTEMPT_SCHEDULED
ADMISSION_ATTEMPT_TERMINAL
SHADOW_ENTRY
POSITION_EVALUATION
POSITION_ACTION
CLOSE_QUOTE_EVALUATION
POST_CLOSE_ATTEMPT_SCHEDULED
POST_CLOSE_ATTEMPT_TERMINAL
CLOSE_OPPORTUNITY_EVALUATION
SHADOW_CLOSE_OPPORTUNITY
UNDERWRITING_POSITION_SUMMARY
```

Every file lives at
`objects/<object_kind>/<lowercase-object-identity-without-sha256-prefix>.json` and has exactly:

```text
object_kind
content_schema_identity
object_identity
underwriting_position_contract_digest
code_identity
runtime_identity
radar_policy_identity
underwriting_policy_identity
position_policy_identity
fact_boundary
source_provenance
payload
non_claims
```

`content_schema_identity` is
`CanonicalIdentity("UNDERWRITING_POSITION_CONTENT_SCHEMA",
UnderwritingPositionContractContentDigest, object_kind)` using the accepted Outcome contract's
native canonical encoding. `object_identity` is the owning identity equation in the
Underwriting/Position contract: availability, action, Candidate, scheduled attempt, terminal
attempt, Entry, Position evaluation/action, close quote, post-close scheduled/terminal attempt,
close-opportunity evaluation, or opportunity identity as applicable. The three identities added
by this implementation interface are exact:

```text
CandidateInvalidationIdentity =
    CanonicalIdentity(
        "CANDIDATE_INVALIDATION",
        CandidateIdentity,
        primary_reason,
        ordered_applicable_reason_vector,
        terminal_FactBoundary
    )

AdmissionAttemptTerminalIdentity =
    CanonicalIdentity(
        "ADMISSION_ATTEMPT_TERMINAL",
        ScheduledAdmissionAttemptIdentity,
        terminal_outcome,
        terminal_FactBoundary
    )

UnderwritingPositionSummaryIdentity =
    CanonicalIdentity(
        "UNDERWRITING_POSITION_SUMMARY",
        UnderwritingPositionContractContentDigest,
        code_identity,
        runtime_identity,
        radar_policy_identity,
        underwriting_policy_identity,
        position_policy_identity,
        terminal_source_identity,
        terminal_FactBoundary,
        counts,
        rates,
        conservation_status
    )
```

`primary_reason` is the first present member of this exact total-order domain and
`ordered_applicable_reason_vector` contains every applicable member in this order, with no
duplicate or omission:

```text
RUNTIME_OR_CODE_IDENTITY_CHANGED
RADAR_POLICY_OR_EPISODE_PAUSED_ENDED_OR_CHANGED
UNDERWRITING_OR_POSITION_POLICY_IDENTITY_CHANGED
POSITION_SLOT_CONSUMED_BY_SHADOW_ENTRY
STRUCTURE_LEG_LIFECYCLE_OR_TARGET_QUANTITY_CHANGED
SOURCE_GAP_PLATFORM_DEGRADATION_OR_REQUIRED_FACT_UNKNOWN
LATEST_ADMISSION_BOUNDARY_REACHED
CONSUMED_NON_ADMISSION_BUSINESS_FINGERPRINT_CHANGED
REUNDERWRITING_NO_LONGER_CANDIDATE
FAILED_ADMISSION_EVALUATION_CONSUMED
```

`terminal_outcome` is exactly
`ENTRY_EMITTED | KNOWN_COMPLETE_NO_ENTRY | KNOWN_INVALIDATED_BEFORE_REFRESH | UNKNOWN_CONSUMED`.
`counts` is one native object in this exact key order:

```text
underwriting_availability_not_evaluated_count
underwriting_availability_unknown_count
underwriting_availability_evaluable_count
underwriting_action_candidate_count
underwriting_action_watch_count
underwriting_action_abstain_count
candidate_count
admission_entry_emitted_count
admission_known_complete_no_entry_count
admission_known_invalidated_before_refresh_count
admission_unknown_consumed_count
shadow_entry_count
position_hold_count
position_close_count
position_unknown_count
close_quote_atomic_count
close_quote_legged_reference_count
close_quote_unexecutable_count
close_quote_unknown_count
close_opportunity_eligible_count
close_opportunity_ineligible_count
close_opportunity_unknown_count
shadow_close_opportunity_count
```

Every count is a nonnegative JSON integer over distinct changed business identities. `rates` is
one native object in this exact key order:

```text
underwriting_known_availability_rate
underwriting_evaluable_rate
underwriting_candidate_action_rate
underwriting_watch_action_rate
underwriting_abstain_action_rate
candidate_activation_rate
admission_evaluable_rate
shadow_entry_rate
position_known_action_rate
close_quote_known_state_rate
close_opportunity_rate_while_closing
```

Each rate is exactly `{numerator: nonnegative integer, denominator: positive integer}` or `null`
when its owning denominator is zero/unknown. `conservation_status` is `MET | NOT_MET | UNKNOWN`;
`MET` requires every contract equation, including availability, Candidate/admission, Entry,
Position, close-quote, and close-opportunity partitions. Activation and invalidation are separate
immutable objects; scheduled and terminal attempts are separate immutable objects. Identical
duplicate bytes at the same path are an idempotent no-op; a conflicting duplicate is a hard error.

The payload key set for each kind is a closed ordered projection of every field required by the
owning identity and the contract's durable-minimum list; no raw transport member, derived default,
or omitted `null` is permitted. `SHADOW_ENTRY` is the sole cross-family admitted anchor for the
Outcome family; a rejected `UNDERWRITING_ACTION` is the sole rejected anchor. The current reader
dispatches only the fifteen kinds above plus the accepted thirteen Outcome kinds, recomputes every
schema/object identity, arithmetic rule, source binding, path, Policy/contract/code/runtime
cross-bind, and never expands or repairs a sealed object from mutable source truth. Exact payload
constant tuples and golden vectors are written in red tests before the writer implementation;
changing one requires an authority-visible task amendment, not an implementation default.

## Validation harness

Use fake transport, deterministic settled fact boundaries, immutable fixtures, direct reducers,
writer/reader round trips, malformed-object matrices, and existing Radar integration seams.
Production-public connection is forbidden. Tests must start with stable failing behavior and then
apply the smallest owning-module implementation.

The direct suite covers at least:

- strict load-before-network Policy parsing, exact bytes/digests, cross-links, no default/hot
  reload, and no fourth Policy;
- fixed canonical identity vectors and exact downstream schemas/envelopes;
- `UNKNOWN != ABSTAIN`, availability/action de-duplication, ten Candidate invalidations, slot
  conservation, one admission RPC, send/response/deadline/error/orphan races, and terminal
  admission outcomes;
- full entry fees, three loss measures, public-not-actual non-claims, and strictly post-entry
  Position facts;
- all nine Position reasons in total order, first known hard-close latch, close quote classes,
  PendingRpc ordering, first eligible opportunity, and no hindsight;
- all thirteen exact Outcome/cohort kinds, rejected-counterfactual parity, terminal maturity and
  censoring, aligned `NO_TRADE`, conservation, exact rational/null rates, one-hop provenance,
  legal `UNKNOWN` persistence, identical-duplicate no-op, unknown-member/conflicting-duplicate/
  mixed-identity rejection, writer atomicity, and current-reader validation;
- the single queue/composer seam, post-Radar-episode Position maintenance, clean/failure stop
  barriers, and all existing Radar regressions.

## Evidence boundary

**Proves:** one exact repository candidate directly implements the accepted fixed-contract,
fixed-Policy behavior and passes offline falsification.

**Does not prove:** any production-public reachability or stability, natural Candidate/Entry/close
or mature Outcome, data completeness outside fixtures, Policy quality, edge, profitability, fill,
account fee, exposure, execution, qualification, promotion, persistent deployment, or acceptance.

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

**In:** one new pure package `packages/short_vol_underwriting/src/short_vol_underwriting/**`;
minimal sole-composer changes under `apps/radar_runtime/src/radar_runtime/**`; the smallest
`packages/options_domain/**` immutable `taker_commission` DTO/parser extension and direct tests
required by the accepted public instrument input contract; other lower-layer immutable projection
changes only when a direct red test proves they are unavoidable; package registration in
`pyproject.toml`; the three frozen Policy files; exact downstream schemas, writer, current reader,
manifest validator, reducers, typed composition intents, direct tests, necessary existing
runtime/authority regression tests, and task-terminal README/architecture/stage synchronization.
No downstream economic rule moves into a lower package.

**Out:** contract or Radar Policy semantics changes; a fourth Policy; lower-package business
logic; a second transport/queue/client; full-market persistence; replay; migration of existing
Radar evidence; generic database/service/registry/workflow abstractions; every new third-party
dependency or lock-file change; live commands; private/account access; credentials; margin;
orders; fills; capital; actual exposure/PnL; qualification; promotion; execution; merge;
deployment.

**Owning module/artifact:** `short_vol_underwriting` owns all downstream domain/evidence meaning;
`radar_runtime` owns only composition and lifecycle; the three JSON files own the fixed Policy
bytes.

### Preparation-only diff

This activation commit changes exactly:

- `README.md`;
- `docs/authority/CURRENT_STAGE.md`;
- this task;
- the three Policy files above; and
- `tests/test_authority_and_architecture.py`.

It creates no package, runtime, CLI, schema, writer, reader, manifest, dependency, or live
artifact. Those belong to the subsequent implementation commits on this still-active task.

## Contract

**Inputs and known-at rule:** only the public facts and settled causal boundaries accepted by the
three contracts. A missing, stale, incomplete, out-of-order, incompatible, or contaminated fact
fails closed as the contract's exact `UNKNOWN`, invalidation, ineligible, censor, or process
failure result; it never becomes zero, calm, `ABSTAIN`, an eligible quote, or business success.

**Durable output and identity:** the exact fifteen upstream kinds and thirteen Outcome/cohort
kinds frozen above, each with its closed schema, content/object identity, FactBoundary,
provenance, three Policy identities, contract/code/runtime binding, path, writer dispatch, current
reader, and non-claims. The thirteen Outcome kinds never substitute for upstream objects.

**Missing/invalid/UNKNOWN semantics:** explicit and contract-owned. A legal business `UNKNOWN`
state is durable and never rejected or converted to zero. Writers reject an unknown kind/member,
missing required member, malformed/non-finite/non-full-quantity value, conflicting duplicate,
mixed identity, arithmetic error, or incompatible object. A byte-identical duplicate at the exact
identity path is an idempotent no-op. Readers never repair, fetch mutable remote truth, or infer
absent data.

**Persisted meaning and compatibility:** new downstream objects bind the current exact contracts,
code/runtime, and three Policy chain. Existing Radar current/sealed readers and evidence remain
unchanged. There is no migration or reinterpretation; incompatible identities are
`NOT_COMPARABLE`.

**Business denominators:** the exact Underwriting, admission, Entry, Position, close-opportunity,
Outcome, rejected, aligned-pair, and cohort conservation denominators in the accepted contracts.
Counts are distinct changed business identities, not messages, ticks, repeated computation,
files, duration, or test cases. Zero or unknown denominator yields rate `null`, never `0`.

## Acceptance

### Direct behavior

1. Given the exact three Policy bytes and deterministic settled public facts, the owner emits only
   the exact contract-authorized action/object identities in causal order.
2. Missing, stale, malformed, mixed, or incomplete input fails closed without a network side
   effect, actual-execution claim, or fabricated zero.
3. Repeated equal business fingerprints do not duplicate objects; changed consumed facts create
   only the contract-authorized successor identity; terminal Candidate/Entry/Position/Outcome
   states never revive.
4. One composer and one outbound queue preserve global request identity, stop/failure barriers,
   Radar regressions, and post-entry lifecycle independence.

### Required commands

- `make sync` (or `make UV='python3 -m uv' sync` when `uv` is not on `PATH`)
- focused Policy, owner, writer/reader, runtime composition, and authority tests
- `make check`
- `git diff --check`
- independent exact-commit/tree and bounded-scope review
- post-push `refs/heads/codex/short-vol-fixed-contract-public-shadow-runtime` equality
- production-public command: `NOT_APPLICABLE` — live is forbidden
- independent reconstruction command: `NOT_APPLICABLE` — evidence belongs to a later task

### Real evidence

**Required:** NO

**Environment and stopping condition:** offline deterministic tests only.

**Required report:** exact commit/tree, contract and Policy digests, modified files, focused/full
checks, independent review, remote equality, zero activity, `UNKNOWN` coverage, limitations, and
non-claims.

**Private API:** FORBIDDEN

## Artifacts and delivery report

**Artifact paths and digests:** the three Policy paths/digests and three accepted contract
digests above; implementation objects are test artifacts only until a later evidence task.

**Policy/contract identities:** the exact tuple `[Radar, Underwriting, Position]` is consumed in
that order by `OutcomeContractIdentity`; it is not itself an identity or fourth artifact.

**Commit/PR:** append-only task-branch history and one Draft PR; neither grants acceptance.

**Unknowns and non-claims:** the chosen thresholds have no prior downstream Outcome evidence;
future natural opportunity, coverage, maturity, stability, edge, profitability, account fees,
fills, exposure, execution, qualification, deployment, and business acceptance remain unknown.

## Definition of done

The complete fixed-contract runtime exists in the owning modules; all four declarations remain
true; the three Policy bytes and identity chain are unchanged within the accepted candidate; all
direct and repository checks pass; an independent reviewer accepts the exact commit/tree and
scope; the bounded remote ref equals that commit; the Draft PR is open; task-terminal authority
records only `IMPLEMENTED_AWAITING_FORWARD_EVIDENCE`; this active task is physically removed; and
no live, merge, stage acceptance, qualification, promotion, execution, or deployment claim is
made. A separate `EVIDENCE_ONLY` task is required before any production-public run.
