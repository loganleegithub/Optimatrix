# Optimatrix Delivery Contract

**Status:** ACTIVE DEVELOPMENT AND EVIDENCE AUTHORITY

## Purpose

Deliver one explicitly approved business closure as the smallest coherent change. Evidence must
prove that closure directly. Do not add capture, replay, storage, reports, schemas, abstractions,
or defensive branches merely to make an unreachable business loop look complete.

## Authority and task route

Before any task, read the Product Constitution, Current Stage, this contract, the System
Architecture when implementation may change, the owning implementation contract, and exactly one
active semantic task.

If the request has no active task, create one from `tasks/TEMPLATE.md` before changing product
behavior, authority, contracts, code, or durable artifacts. A task names a business closure, not a
work sequence.

Task kinds:

- `AUTHORITY_ONLY`: may change authority, contracts, task template, README, and direct authority
  tests; runtime edits and live commands are forbidden.
- `IMPLEMENTATION`: changes one authorized runtime behavior and verifies it directly.
- `EVIDENCE_ONLY`: runs an already accepted immutable implementation to collect the exact evidence
  required by the active task; code and Policy changes are forbidden.

### Terminal business-goal delegation

One explicit human terminal business goal may conditionally authorize a bounded sequence of
authority amendment, implementation, evidence, and stage recording inside the same semantic
closure. The owning authority and active task must record the delegation before its first runtime
or remote action. The record freezes the permission boundary, allowed terminal state, change
axes, acceptance predicates, forbidden capabilities, branch scope, and role separation.

Exact technical identities are not separate product decisions. Before each remote or live action,
the controller durably binds the exact commit/tree, verified remote ref, immutable Policy
path/digest, new empty absolute evidence directory, deterministic result-independent stop
predicate, and required checks. A candidate author cannot be its sole verifier; the independent
verifier is read-only for that candidate and issues an exact-identity `PASS | FAIL` receipt. Code
changes invalidate the receipt. Evidence is append-only, an unsuccessful retry uses a new empty
directory, and old evidence is never retroactively authorized.

Evidence does not create stage permission. It proves whether the predicates of a prior human
conditional stage decision were met. A stage record may change only when the exact delegation and
an independent pass receipt both say that all frozen predicates passed.

## Business closure contract

Every task states:

1. `Given / When / Then` in observable business terms;
2. the smallest upstream prerequisite whose absence would make the closure unreachable;
3. exact known-at inputs and the durable output, if any;
4. truthful zero, no-hit, unavailable, and `UNKNOWN` behavior;
5. the unit and denominator of each reported count or rate;
6. exact evidence that proves the assertion and explicit non-claims;
7. owning module and bounded file scope;
8. current permission and the one semantic identity changed.

If the upstream prerequisite is not established, make it the closure. Do not work around it by
building later-stage reporting or by running the same unavailable path for longer.

## Change integrity

Declare each axis independently as `NONE` or `APPROVED`, then name the exact identity and
behavioral delta:

1. **Market/Decision input contract** — sources, universe, timing, continuity, freshness,
   missingness, executable quote inputs, or persisted consumed facts.
2. **Decision Policy** — Short Vol detector, structure authorization, formula, thresholds,
   confirmations, persistence, clear/re-arm, Underwriting action, Shadow admission, executed
   entry, or Position action.
3. **Outcome/evaluation contract** — strictly future facts, close-opportunity semantics,
   actual-versus-counterfactual status, scoring, cohort, comparator, or qualification.
4. **Stage/authorization** — public/private data, account, capital, execution, research,
   qualification, promotion, or product capability.

Changing capture, storage, replay, provenance, or reporting does not hide an effect on these
axes. A code change cannot silently amend an authority or immutable Policy identity.

## Product behavior versus validation harness

The task separately describes:

- **Product operating behavior:** what the continuously running product does.
- **Validation harness:** the smallest fixture, live observation, sealed sample, or independent
  calculation needed to prove the task.

A duration, cutoff, file, archive, replay command, or process lifetime used by the harness never
becomes a product cadence, opportunity definition, or holding rule.

For the first Short Vol Radar, normal product behavior is an event-driven in-memory monitor that
persists one minimal anomaly event on activation, a separate minimal official atomic-quote event
when available, and one run summary. A bounded full-stream capture is permitted only when a task
proves why that evidence is necessary; it is never the default response to uncertainty.

## Evidence classes

Mark every class `REQUIRED` or `NOT_APPLICABLE`:

| Evidence class | What it can prove | What it cannot prove |
|---|---|---|
| Direct behavior | deterministic formula, boundary, state transition, fail-closed behavior | natural production reachability |
| Production-public Radar | real connectivity, coverage, usable detector evaluation, and any anomaly or atomic quote actually observed | unobserved event reachability, fill, edge, Candidate quality |
| Minimal-hit recomputation | the hit follows from its frozen consumed inputs | completeness of the unselected market |
| Bounded stream reconstruction | deterministic reconstruction of the exact sealed sample | live lifecycle, data completeness, profitability |
| Shadow forward Outcome | future public executable-close observations under a frozen contract | actual execution or fill |
| Qualification | pre-registered incumbent-versus-Challenger criteria on an accepted cohort | execution permission |
| Execution | authorized orders, fills, positions, and capital facts | out-of-sample strategy value by itself |

Synthetic and production-public evidence remain separate. A visible quote is not a fill.
Matching calculations prove reconstruction only. A long run proves only what occurred inside its
covered interval.

## Assertion-proportional verification

Use the cheapest independent path that can falsify the business claim:

- a pure formula or state rule: direct unit/property tests;
- a public connectivity or observed-natural-event claim: production-public observation;
- a minimal event recomputation claim, only when its owning task requires one: independent pure
  calculation from that event;
- a persisted-format change: direct fail-closed tests and an explicit compatibility decision;
- a full-stream reconstruction claim: a fresh process over the exact sealed sample;
- an Outcome claim: strictly future facts under the frozen Shadow-admission or opening-fill
  boundary and Position identity.

Do not require full replay, hashes, archives, receipts, or broad reports for a claim that a direct
test and minimal event can prove. Do not turn occurrence of a rare natural market event into a
software-readiness prerequisite unless that occurrence is itself the exact approved claim.

## Radar establishment evidence

The active [Short Vol Radar contract](../contracts/SHORT_VOL_RADAR.md) owns the detector, its
independent public atomic-quote availability state, denominators, minimal events, and
establishment acceptance. One process freezes one exact content-identified Policy before live
evidence. Direct tests prove deterministic boundaries; production-public observation proves only
the connectivity, coverage, usable evaluations, anomalies, and quotes that actually occurred.
`REACHABILITY_SMOKE` and `OPERATIONAL_SOAK` are independent evidence gates with separately
pre-bound exact code, Policy, evidence, and stop boundaries. A named terminal business-goal
delegation may replace repeated per-run human commands, but authorization, completion, or
acceptance of one never accepts the other.

The service runs continuously until a human or a pre-registered external goal supervisor stops it,
or the process fails. A supervisor stop predicate is frozen before startup and cannot depend on
whether the evidence currently appears likely to pass. Predetermined elapsed time may bound a
validation run but neither accepts nor rejects a capability and may not trigger threshold changes.
A covered production interval with at least one real instrument, one known per-instrument
evaluation, and a known full baseline/IV/Delta/richness calculation inside a complete non-empty
aggregate `NO_ANOMALY` evaluation can establish runtime reachability; a natural anomaly and atomic
quote are separately `OBSERVED | NOT_OBSERVED`. The human emergency stop remains valid.

Policy scope/parameter calibration is permitted only between runs through a human-approved
successor identity and new forward interval. It cannot relabel earlier evidence. Without a
strictly future forecast or Outcome label, such calibration can improve only operational
coverage, frequency, and flicker behavior—not claim better prediction or trading value.

Evidence stays proportional to the claim: this closure requires no full-feed archive, replay,
independent offline calculator, provenance command, Candidate, fill, Outcome, or profitability
proof.

## Availability and zero semantics

- Missing, stale, discontinuous, incomplete, or contaminated facts are `UNKNOWN` at the smallest
  declared consumer scope.
- `UNKNOWN` is neither numeric zero nor economic `ABSTAIN`.
- `NO_ANOMALY` requires usable detector inputs and known coverage.
- `ANOMALY_ACTIVE` depends only on detector inputs and its frozen activation/clear Policy.
- Official combo availability is independently
  `NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO | NO_TARGET_SIZE_CREDIT_QUOTE |
  PUBLIC_ATOMIC_QUOTE_AVAILABLE`; it is `NOT_EVALUATED` when no anomaly is active.
- A combo state cannot overwrite detector truth; a public quote cannot create an order or fill.
- Negative absence states require complete relevant scope; a positive witness does not imply best
  price or complete-market selection.
- No current Radar event creates Shadow admission, executed entry, or an Outcome object.
- A Shadow admission or executed entry with incomplete strictly future facts may create its own
  `UNKNOWN` Outcome with null economics.

Serializers use null/undefined for a rate whose denominator is zero or unknown. They never replace
an undefined rate with `0`.

## Denominator integrity

Name every numerator, denominator, unit, scope, and conditioning event. Keep separate:

- monitor covered/degraded/unknown time;
- relevant state changes;
- distinct short-leg anomaly episodes after clear, known ineligibility, scope/membership/input
  loss, continuity loss, or stop, separated by call/put and attributed once to their activation
  TTE band;
- active-anomaly combo evaluations and official target-size atomic-quote availability states;
- Underwriting-evaluable future opportunities and Candidate/Watch/Abstain actions;
- Candidates and Entries;
- Entries and mature/unknown Outcomes;
- counterfactual observations and actual exposure.

Messages, detector calculations, repeated quotes, legs, theoretical structures, elapsed runtime,
files, receipts, replay checks, and AI explanations are not Radar episodes or Candidate
opportunities.

## Persisted meaning

When a task changes a durable contract it must declare:

- semantic identity and content digest;
- required fields, units, enum meanings, nullability, and validation;
- writer and every reader;
- compatibility as `COMPATIBLE | MIGRATION_REQUIRED | NOT_COMPARABLE`;
- fail-closed behavior for missing or mixed identities.

Do not create a new persisted identity when no durable business object is required. A Radar
`NO_ANOMALY` does not require a receipt. The first Radar closure persists only a minimal anomaly
event, a separate official atomic-quote event when observed, and one run summary. Their task
requires direct schema and behavior tests, not a second persisted recomputation path.

## Causality and Outcome

- Decision, anomaly, and atomic-quote inputs are known at or before their bound causal sequence.
- `SHADOW_ENTRY` starts counterfactual strictly future observation and creates no exposure.
- Actual exposure begins with the first opening fill, including a partial or single-leg fill.
- Shadow Outcome observations are strictly after `SHADOW_ENTRY`; actual execution Outcome facts
  are strictly after the first opening fill and processed in causal order.
- `CLOSE` is a Position Policy action, not proof that exposure ended.
- `close_quote_state` is separately
  `ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`. An unavailable
  quote cannot erase a known hard-close action.
- A public target-size close quote is a Shadow close opportunity, not a fill.
- A Shadow close opportunity additionally requires Position action `CLOSE`, a strictly later
  atomic combo quote for the full remaining Shadow quantity. A legged reference is diagnostic
  until a separate legging exit Policy is authorized.
- Future actual exposure ends only when every leg is flat after the final closing fill or
  authorized settlement.
- Rejected-opportunity evaluation is separately labeled and never enters actual Outcome counts.

## Implementation and testing

Before editing, inspect branch, HEAD, worktree, remote refs, and task scope. Preserve unrelated
human changes. Work only in the owning module and reuse current patterns.

Implementation tasks:

- add direct tests at the changed business boundary;
- fail closed on missing and invalid facts;
- avoid speculative abstractions and infrastructure;
- run focused tests and `make check`;
- run live or independent evidence only when its task class is `REQUIRED`;
- inspect final artifacts and Git diff before claiming completion.

`AUTHORITY_ONLY` tasks run link, consistency, and authority tests but no market commands.

## Review questions

- Does the change establish the current business prerequisite, or decorate a downstream failure?
- Is the live product consuming changed market state, or rereading stored facts?
- Does the Short Vol signal compare like-for-like remaining-life variance under one exact Policy
  that cannot change during its run?
- Are detector truth, official atomic-quote availability, future maker/order state, Candidate,
  Shadow admission, executed entry, and fill distinct?
- Does a successor inside the declared Policy schema receive a new identity and forward interval
  without retroactive claims?
- Are clear/re-arm rules preventing quote flicker from multiplying Radar episodes?
- Does `UNKNOWN` remain outside economic denominators?
- Is position closure driven by current risk and executable close state?
- Are Shadow close opportunity and future actual fill duration separate?
- Is every evidence demand necessary to falsify this exact assertion?
- Did the change add storage, platform, or defensive complexity without a current consumer?

## Git and PR contract

- Protect `main`; never rewrite or delete remote state without explicit authorization.
- Preserve unrelated human work and do not stage it.
- Use one bounded branch and one Draft PR for the closure unless the user explicitly authorizes
  more.
- A recorded terminal-goal delegation may authorize a non-force push of its bounded non-`main`
  branch after an independent exact-commit pass receipt and must verify remote equality.
- Record base/head, checks, evidence classes, zero activity, `UNKNOWN`s, non-claims, Git state, and
  remote state in the delivery report.
- Green checks and a Draft PR do not accept authority, advance stage, merge, deploy, or grant
  execution.
- Completed task files do not accumulate on `main`; Git and accepted durable evidence are the
  archive.

## Definition of done

The requested business closure exists; all four axes match authority; the direct behavior and
every required evidence class pass; invalid and zero cases remain truthful; final diff and
artifacts contain only the closure; limitations and non-claims are explicit; and remote state is
reported accurately. If a required natural market fact has not occurred, the implementation may
be ready but the business closure remains unaccepted.
