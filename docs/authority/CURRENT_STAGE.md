# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Implemented capability:** `OUTCOME_TRUTH` (bounded contract only)

**Production Radar reachability:** `NOT_ESTABLISHED`

**Sole authorized next product-capability closure:** `STRUCTURE_ASSESSMENT_REACHABILITY`

## Authority

This document grants current permission under
[`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md). It does not define product purpose,
architecture, or delivery evidence, and it cannot widen the Product Constitution. Code presence,
green tests, historical receipts, or roadmap order do not grant a stage.

The current boundary authorizes continuous production-public acquisition and structure assessment
inside the existing modular monolith. Continuous operation here means one shared public fact
stream, rolling state, and event-driven evaluation when a consumed market fact or necessary time
boundary changes economic state. It does not mean periodically rereading an unchanged local tape.
It does not yet authorize structure-level aggregation, an Entry Policy, a
position-management/exit Policy, Candidate action, a long-running admission/Outcome cohort,
database, generic service platform, private/account access, orders, fills, capital, qualification,
promotion, or execution.

This permission is prospective for a separate `STRUCTURE_ASSESSMENT_REACHABILITY` implementation
task. That closure establishes one prerequisite for a future production Radar; it does not
establish Candidate-producing Radar reachability. An authority-only realignment task may not edit,
invoke, or validate runtime behavior.

## Implemented baseline

The repository implements and has accepted bounded Decision Truth and Outcome Truth semantics:

- production-public Deribit catalog, ticker, trade, platform, heartbeat, gap, and reconnect
  canonicalization;
- append-only canonical facts with causal sequence and persisted elapsed time;
- deterministic current-frame projection, structure construction, fixed transparent
  `OBSERVED_PATH_STRESS_FIXED_PRIOR` assessment, and Decision reconstruction;
- immutable Decision, Shadow Entry, Outcome fact-seal, and Outcome receipts;
- strict known-at Decision facts, strictly future actual-exposure facts, executable visible-quote
  economics, explicit missingness, and actual-versus-counterfactual separation;
- deterministic synthetic and bounded production-public replay and artifact verification.

This baseline proves that the bounded computations fail closed and can be reconstructed. It does
not prove that production inputs can reach a usable Radar state, that the full authorized
universe is assessable, that any production state contains a completed assessment, that a
continuous event-driven evaluator exists, or that the Policy has value. A historical
all-`UNKNOWN` result is truthful diagnostic evidence, not a production Radar or Fixed-Policy
baseline.

## Current business blockers

These are product reachability gaps, not permission for broad refactoring:

1. The current production path captures a bounded stream and evaluates only its final state. It
   does not incrementally evaluate changed live states inside the same acquisition pipeline.
2. Readiness is collapsed too broadly: unrelated missing or stale instrument facts can prevent
   otherwise usable structures from being assessed.
3. The production path has no authorized producer for `SCHEDULED_BLOCK_STATE`, although the
   accepted bounded Policy treats it as a hard gate. The target Radar assessment does not consume
   that non-market admission fact, does not add a source, and never fabricates `CLEAR`. A future
   structure-level Entry or Shadow-admission contract must explicitly decide whether a sourced
   scheduled-event veto is required.
4. Current structure accounting begins after important quote and executability filters, so it
   cannot report the legal-pair, observable, executable, and completed-assessment denominators
   needed to explain availability.
5. Unavailable evaluation can be encoded as `ABSTAIN`, preventing business reports from
   distinguishing “the historical Policy rejected it” from “the Radar could not assess it.”

## Sole authorized product-capability closure: Structure-assessment reachability

The next product-capability task may only establish that the production-public acquisition and
assessment path can reach and assess distinct real market states without stopping or replaying
the acquisition stream. It must implement the new `DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT` identity
and the prospective `OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_ASSESSMENT` identity. This closure
does not authorize a new Decision Policy, Candidate mapping, ranking rule, Entry, or exit
behavior. Production Radar reachability remains `NOT_ESTABLISHED`.

The frozen structure and sizing inputs remain OTM-only 1:1 same-expiry same-side verticals, TTE
1,800–259,200 seconds, quantity `0.04`, forward risk scenarios
`(1,800, 3,600, 7,200, 14,400)` seconds, and a 1,800-second settlement buffer. One unique legal
structure at one relevant market state is one structure assessment unit. Its four risk-scenario
calculations form one diagnostic vector; they are not planned holding periods, exit clocks, or
four business opportunities. This closure deliberately does not choose how that vector becomes a
future structure-level Candidate action. Each configured scenario slot is
`CALCULATED | NOT_APPLICABLE_TTE | UNKNOWN`. A slot beyond the structure's usable
pre-settlement lifetime is explicitly `NOT_APPLICABLE_TTE` unless a later authorized contract
models settlement risk; it is not a failed opportunity. A structure is risk-assessable when every
configured slot is calculated or explicitly not applicable, no required applicable input is
`UNKNOWN`, and at least one slot is `CALCULATED`. An all-not-applicable structure remains one
classified assessment with reason `NO_APPLICABLE_RISK_SCENARIO`, but it does not enter
`risk_assessable_structure_count`.

### Required operating behavior

- Capture authorized public facts through one shared collector/tape path rather than starting a
  collector per structure, Decision, or Entry. This is not a network exactly-once guarantee;
  duplicates and conflicts retain their canonical fail-closed treatment.
- Maintain rolling observation state. Initial warm-up is required only when the needed history is
  unavailable. Reconnect does not erase history already proved complete, but the disconnected
  interval is `UNKNOWN` until continuity or an authorized backfill positively covers it. Backfill
  may help only future evaluations and never rewrites an earlier result.
- Define `evaluation_state_digest` from the reduced semantic values actually consumed by universe
  construction, availability, executable economics, and risk assessment. Raw wall time,
  continuously changing quote age or TTE, heartbeat bookkeeping, and `capture_seq` by itself do
  not make a new economic state. Time creates a trigger only when a declared consumed
  classification or membership changes, such as fresh→stale, entry/exit from TTE eligibility, or
  a rolling-window member entering/leaving.
- Trigger evaluation only when an accepted fact changes that consumed state or when a named
  necessary time boundary changes quote/catalog freshness, TTE or settlement eligibility,
  rolling-window membership, or another consumed value. Duplicate, heartbeat, unrelated, replayed,
  or arbitrary timer events that leave the digest unchanged create no assessment, Decision,
  opportunity, or business artifact. Collector health may record them separately.
- Coalesce bursts when useful while binding the evaluation to the latest accepted `capture_seq`
  included in the strict as-of state. Implementation may recompute the whole current universe or
  optimize affected structures; this closure requires equivalent business results, not a generic
  dependency index. Deterministic inspection may reconstruct the whole state independently.
- Separate market-global risk-input readiness, universe coverage, per-structure quote and
  executability readiness, risk assessment, future Policy action, Shadow admission, and Outcome
  maturity.
- Localize missing, stale, or depth-unknown option facts to structures that consume those facts.
  Incomplete universe coverage remains explicit and may prevent a claim of complete-universe
  selection, but it may not erase completed local assessments. Ordinary fact changes follow the
  declared dependency graph: a leg-local input affects dependent structures, while a changed
  declared market-global aggregate legitimately affects every structure that consumes it. The
  existing whole-universe quote-age dispersion remains such a global dependency until a separate
  Policy change says otherwise.
- Report linked ledgers without mixing units:
  `accepted evaluation triggers → distinct changed evaluation states → executed evaluations →
  globally risk-ready evaluations`;
  `legal structures → quote-observable structures → round-trip-executable structures →
  risk-assessable structures`; and the diagnostic workload
  `configured risk-scenario slots → calculated + not-applicable-for-TTE + unknown`.
- Risk-scenario counts describe computation only. They are never structure-opportunity, Candidate,
  Entry, or Outcome denominators.
- Keep unavailable assessment separate from `CANDIDATE | WATCH | ABSTAIN`. No target
  `policy_action` exists in this closure. A legacy fail-closed `ABSTAIN` may remain only inside the
  historical contract and cannot enter target Radar counts.
- Under partial quote coverage, retain completed local structure assessments and label the
  coverage. This closure makes no complete-universe selection or Policy-value claim.
- Persist authorized canonical source facts incrementally. Online assessment does not require a
  second artifact for every changed quote or evaluated state. Bounded acceptance reuses existing
  inspection/recomputation output over a minimal sealed observation window and may show counts,
  reasons, assessment-set identity, and one sampled assessed structure. It creates no new Radar
  receipt, witness schema, or per-state artifact. The full derived structure universe is not
  stored. A future authorized Candidate transition may persist its selected structure under that
  later contract.

### Minimum acceptance evidence

A bounded production-public observation window is sufficient as an acceptance harness when it
shows all of the following:

- `distinct_evaluation_state_count >= 2` under the same continuously running collector/tape, with
  different `evaluation_state_digest` values and strictly increasing as-of `capture_seq` values;
- each accepted state change names an accepted relevant market fact or necessary time boundary;
- direct behavior tests prove that a duplicate, heartbeat, unrelated fact, replay, and arbitrary
  timer tick over unchanged consumed state do not increase evaluation, Decision, opportunity, or
  business-artifact counts;
- at least one distinct state had complete global risk inputs and known legal-universe scope, with
  `legal_structure_count > 0`, `round_trip_executable_structure_count > 0`, and
  `risk_assessable_structure_count > 0`, plus
  `calculated_risk_scenario_slot_count > 0`;
- direct behavior tests prove that missing, stale, or depth-unknown leg availability affects only
  dependent structures unless a declared global aggregate is unavailable. Whether implementation
  recomputes the whole universe or only affected structures, the reported business result must
  respect that dependency scope. Live evidence reports naturally observed unavailable facts but
  need not manufacture them;
- an independent recomputation using existing inspection support reproduces one sampled
  evaluation state and its structure-level denominators from the minimal sealed observation
  window, without introducing a new runtime artifact identity.

Candidate-class observations, Entries, and actual Outcomes are not outputs of this closure.
`STRUCTURE_ASSESSMENT_REACHABILITY` does not require or emit a Policy action.
An all-`UNKNOWN`, zero-legal-structure, zero-executable-structure, or zero-risk-assessable window
is valid incident evidence but does not accept `STRUCTURE_ASSESSMENT_REACHABILITY`.

This closure does not require a one-hour or six-hour run, a Candidate action, Entry, mature
Outcome, a whole-run receipt, an archive of historical runs, multi-layer drift reports, or a
bundle that revalidates the same facts repeatedly. This closure may reuse existing
inspection/replay support but does not authorize a new replay artifact, drift taxonomy, bundle,
or historical revalidation.

## Queued sequence — not authorized

After structure-assessment reachability is accepted and this authority is explicitly advanced,
the intended sequence is:

1. **Candidate, Entry, and position-management contract:** before any Candidate action, define one
   explicit structure-level aggregation of the forward risk-scenario vector, one immutable Entry
   Policy, one immutable state-driven `HOLD | CLOSE | UNKNOWN` position-management Policy, its hard
   latest-exit/expiry boundaries, and a new forward Outcome identity. Historical fixed-horizon exit
   behavior is not inherited.
2. **Fixed-Policy forward cohort:** keep those immutable Policies running long enough to measure
   complete Candidate episodes, admissions, actual holding times, executable exits, mature actual
   Outcomes, separately labeled rejected-opportunity counterfactuals, and a cohort-aligned
   `NO_TRADE=0` comparator.
3. **Challenger research and qualification:** only after a usable fixed-Policy cohort and a
   separately approved qualification contract.
4. **Promotion:** only after an independently verified Qualification receipt and a separately
   approved promotion envelope. Execution and capital authority remain separate.

A queued closure is not an active task. Activate exactly one by updating this authority in an
explicitly approved change after the preceding closure is accepted.

## Forbidden under the current boundary

- a target Entry/Candidate Policy, structure-level scenario aggregation, position-management
  Policy, exit thresholds, or reinterpretation of the historical fixed-horizon Policy;
- learned models, research automation, automatic promotion, or evolution;
- qualification or any claim of Policy value from the structure-assessment-reachability closure;
- generic databases, feature stores, model registries, workflow engines, or multi-service
  architecture;
- generic multi-market or multi-strategy abstractions;
- private/test/account APIs, credentials, balances, margin, positions, orders, fills, settlement,
  execution gateways, or money;
- account/portfolio risk and production capital authority;
- treating a bounded evidence window, replay, receipt graph, or bundle as the product runtime.

Update this document in the same merge that changes permission, implemented capability, blockers,
or the sole authorized next closure.
