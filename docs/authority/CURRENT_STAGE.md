# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Implemented capability:** `OUTCOME_TRUTH` (bounded contract only)

**Production Radar reachability:** `NOT_ESTABLISHED`

**Sole authorized next product-capability closure:** `RADAR_ESTABLISHMENT`

## Authority

This document grants current permission under
[`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md). It does not define product purpose,
architecture, or delivery evidence, and it cannot widen the Product Constitution. Code presence,
green tests, historical receipts, or roadmap order do not grant a stage.

The current boundary authorizes continuous production-public Radar acquisition and scanning inside
the existing modular monolith. Continuous operation here means one shared public fact stream,
rolling state, and repeated scans. It does not yet authorize a long-running admission/Outcome
cohort, database, generic service platform, private/account access, orders, fills, capital,
qualification, promotion, or execution.

This permission is prospective for a separate `RADAR_ESTABLISHMENT` implementation task. An
authority-only realignment task may not edit, invoke, or validate runtime behavior.

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
universe is assessable, that any production scan contains a completed assessment, that a
continuous scanner exists, or that the Policy has value. A historical all-`UNKNOWN` result is
truthful diagnostic evidence, not a production Radar or Fixed-Policy baseline.

## Current business blockers

These are product reachability gaps, not permission for broad refactoring:

1. The current production path does not perform repeated online scan cycles over continuously
   maintained rolling state.
2. Readiness is collapsed too broadly: unrelated missing or stale instrument facts can prevent
   otherwise usable structures from being assessed.
3. The production path has no authorized producer for `SCHEDULED_BLOCK_STATE`, although the
   accepted bounded Policy treats it as a hard gate. This authority resolves the target behavior:
   do not add a source and do not fabricate `CLEAR`; remove the unavailable fact from economic
   Candidate eligibility under the new Radar Policy identity. A future Shadow-admission contract
   may add an explicitly sourced scheduled-event veto only under separate authorization.
4. Current opportunity accounting begins after important quote and executability filters, so it
   cannot report the legal-pair, observable, executable, and completed-assessment denominators
   needed to explain availability.
5. Unavailable evaluation can be encoded as `ABSTAIN`, preventing business reports from
   distinguishing “the Policy rejected it” from “the Radar could not evaluate it.”

## Sole authorized product-capability closure: Radar establishment

The next product-capability task may only establish that the production-public Radar can
repeatedly reach and evaluate real market opportunities. It must implement the new
`DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT` identity and
`OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY` identity. The latter preserves every economic
horizon, formula, structure-universe and OTM filter, configured quantity, threshold, reserve,
non-schedule veto, ranking rule, and WATCH mapping while removing only the unavailable
scheduled-block fact from Candidate eligibility.

The frozen universe parameters remain OTM-only 1:1 same-expiry same-side verticals, TTE
1,800–259,200 seconds, quantity `0.04`, four horizons
`(1,800, 3,600, 7,200, 14,400)` seconds, and a 1,800-second settlement buffer. Every legal
structure enters all four horizon opportunities; `TTE_BUFFER` remains a Policy predicate rather
than a denominator filter.

### Required operating behavior

- Capture authorized public facts through one shared collector/tape path rather than starting a
  collector per structure, Decision, or Entry. This is not a network exactly-once guarantee;
  duplicates and conflicts retain their canonical fail-closed treatment.
- Maintain rolling observation state. Initial warm-up is required only when the needed history is
  unavailable. Reconnect does not erase history already proved complete, but the disconnected
  interval is `UNKNOWN` until continuity or an authorized backfill positively covers it. Backfill
  may help only future scans and never rewrites an earlier Decision.
- Trigger scans at one predeclared cadence or trigger rule without stopping acquisition. Record
  due, executed, skipped, and unavailable cycles with exact reasons.
- Separate market-global risk-input readiness, universe coverage, per-structure quote and
  executability readiness, Policy action, Shadow admission, and Outcome maturity.
- Localize missing, stale, or depth-unknown option facts to structures that consume those facts.
  Incomplete universe coverage remains explicit and may prevent a claim of complete-universe
  selection, but it may not erase completed local assessments.
- Report three linked ledgers without mixing units:
  `due scan cycles → executed cycles → globally risk-ready cycles → action cycles`;
  `legal structures → quote-observable structures → round-trip-executable structures`; and
  `assessment opportunities (legal structure × every configured horizon) → completed assessments →
  Policy-evaluable assessments → passing assessments`.
- Keep unavailable evaluation separate from `CANDIDATE | WATCH | ABSTAIN` with
  `policy_action=null`. A legacy fail-closed `ABSTAIN` compatibility output may be retained only in
  its old field and may never enter the Policy action count or denominator.
- Under partial quote coverage, retain local completed and passing assessments and label the
  coverage. A Candidate observation may describe only the evaluated subset; it may not claim
  complete-universe selection, and this closure never admits it.
- Preserve every deployed economic horizon, formula, structure-universe and OTM filter, configured
  quantity, threshold, reserve, non-schedule veto, ranking rule, and WATCH mapping. The only
  approved Policy delta is the scheduled-block relocation above.

### Minimum acceptance evidence

A bounded production-public observation window is sufficient as an acceptance harness when it
shows all of the following:

- `executed_cycle_count >= 2` for consecutive due cycles using the same shared fact stream;
- at least one scan had complete global risk inputs and known legal-universe scope;
- in that scan, `assessment_opportunity_count > 0`,
  `completed_assessment_count > 0`, and `policy_evaluable_assessment_count > 0`;
- at least one executed scan emitted `policy_action != null` and `action_cycle_count = 1`;
- direct behavior tests prove that missing or stale option facts affect only dependent structures;
  live evidence reports naturally observed unavailable facts but need not manufacture them;
- an independent recomputation using existing inspection support reproduces one accepted cycle
  and its denominators from the minimal sealed observation window.

Candidate-class observations and Entries may both be zero. A zero Candidate count with a nonzero
Policy-evaluable denominator proves only the observed count/rate for that evaluated window; under
partial coverage it applies only to the evaluated subset. It does not prove Policy value, reserve
quality, or qualification. An all-`UNKNOWN`, zero-assessment, or zero-Policy-evaluable window is
valid incident evidence but does not accept `RADAR_ESTABLISHMENT`.

This closure does not require a one-hour or six-hour run, Entry, mature Outcome, a whole-run
receipt, an archive of historical runs, multi-layer drift reports, or a bundle that revalidates
the same facts repeatedly. This closure may reuse existing inspection/replay support but does not
authorize a new replay artifact, drift taxonomy, bundle, or historical revalidation.

## Queued sequence — not authorized

After Radar establishment is accepted and this authority is explicitly advanced, the intended
sequence is:

1. **Fixed-Policy forward cohort:** keep the immutable Policy running long enough to measure
   complete opportunity counts, assessment and Candidate rates, admitted and capacity-blocked
   opportunities, mature actual Outcomes, separately labeled rejected-opportunity
   counterfactuals, and a cohort-aligned `NO_TRADE=0` comparator.
2. **Challenger research and qualification:** only after a usable fixed-Policy cohort and a
   separately approved qualification contract.
3. **Promotion:** only after an independently verified Qualification receipt and a separately
   approved promotion envelope. Execution and capital authority remain separate.

A queued closure is not an active task. Activate exactly one by updating this authority in an
explicitly approved change after the preceding closure is accepted.

## Forbidden under the current boundary

- Policy tuning beyond the exact scheduled-block relocation, learned models, research automation,
  automatic promotion, or evolution;
- qualification or any claim of Policy value from the Radar establishment closure;
- generic databases, feature stores, model registries, workflow engines, or multi-service
  architecture;
- generic multi-market or multi-strategy abstractions;
- private/test/account APIs, credentials, balances, margin, positions, orders, fills, settlement,
  execution gateways, or money;
- account/portfolio risk and production capital authority;
- treating a bounded evidence window, replay, receipt graph, or bundle as the product runtime.

Update this document in the same merge that changes permission, implemented capability, blockers,
or the sole authorized next closure.
