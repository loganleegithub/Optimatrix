# Optimatrix System Architecture

**Status:** ACTIVE ARCHITECTURE AUTHORITY

**Structural authority under:** [`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md)

**Permission boundary:** [`CURRENT_STAGE.md`](CURRENT_STAGE.md)

**Delivery authority:** [`DELIVERY_CONTRACT.md`](DELIVERY_CONTRACT.md)

## Architecture choice

Optimatrix is a Python modular monolith. It uses explicit immutable contracts, deterministic pure
domain logic, an append-only canonical tape, and small application-layer composition.

Do not split it into services or add a database, event bus, feature store, model registry, or
workflow engine without a current business closure that cannot be completed coherently inside the
modular monolith.

## Runtime and research planes

```text
Deribit public adapter
→ one continuously appended CanonicalEvent / Market Tape
→ rolling strict-as-of market and risk state
→ changed-consumed-state / necessary-time-boundary detection
→ event-driven evaluation of the current authorized structure universe
→ per-structure availability and forward risk-scenario assessment
→ existing inspection/recomputation output when bounded acceptance samples a state
→ later separately authorized Entry and position-management Policies
→ separate Shadow admission and asynchronous strictly future Outcome trackers
→ OutcomeReceipt
```

Market facts flow through one shared adapter/tape path. Structure assessment, admitted Shadow
positions, and later evaluation reference that tape rather than starting structure-specific or
Entry-specific collectors. This is not a network exactly-once guarantee. The adapter, reducer, and
assessment path are one streaming composition: accepted facts update state before the current
authorized universe is evaluated. An implementation may recompute that universe or optimize
affected structures; the architecture does not require a generic dependency index.

An evaluation trigger is a consumed market fact change or a necessary time boundary that changes
a declared semantic classification or membership, such as fresh→stale, TTE/settlement
eligibility, or rolling-window membership. Raw wall time, continuously changing age/TTE, and
`capture_seq` alone are not triggers. Bursts may be coalesced without losing the strict as-of
`capture_seq`. A heartbeat, duplicate, unrelated fact, replayed fact, or arbitrary timer tick that
leaves the consumed evaluation state unchanged may update collector health but creates no new
assessment, Decision, opportunity, or business artifact.

The offline, separately trusted path is:

```text
sealed tape + Decision receipts + Outcome receipts
→ read-only AI Researcher
→ ChallengerPackage
→ Independent Verifier
→ QualificationReceipt
→ future Promotion Controller
```

The future execution path, when separately authorized, is:

```text
candidate-class decision
→ strategy-risk gate
→ portfolio/account hard-risk gate
→ execution gateway
→ order/fill/reconciliation journal
```

Boxes for later stages define trust boundaries; they do not authorize their implementation.

## Current module boundaries

### `market_tape`

Owns strategy-neutral canonical public facts, causal capture order, collector and market clock
domains, durable capture/replay, gaps, reconnects, books, and reduced current market state.

It must not own candidate ranking, Policy thresholds, insurance formulas, or future Outcomes.

### `options_domain`

Owns option facts, descriptive surface facts, visible execution economics, fees, quantity
validity, and allowed defined-risk structure construction.

It must not acquire market data, select a strategy, qualify a Policy, or access an account.

### `short_vol_radar`

Owns rolling DecisionFrame projection, consumed-state identity, event-driven universe evaluation,
observation windows, market-global risk readiness, universe coverage, per-structure readiness,
forward risk-scenario vectors, and structure-level insurance assessment. It may recompute the
current universe or optimize affected structures without changing business semantics. Historical
bounded ranking and candidate/watch/abstain behavior remains implemented compatibility; a target
structure-level Candidate contract is not authorized by
`STRUCTURE_ASSESSMENT_REACHABILITY`.

It must not perform network I/O, consume post-entry Outcome facts, train a model, or access an
account.

### `shadow_engine`

Owns entry-frozen Shadow positions, strictly future Outcome points, observed exits, executable
close economics, actual holding time, and matured Outcomes. A future forward cohort must also
freeze an independently authorized position-management Policy and hard latest-exit/expiry
boundaries; it cannot inherit the historical fixed-horizon rule by implication.

It must not collect market data, mutate the deployed Policy, perform research, or execute orders.

### `radar_runtime`

Owns the Deribit public boundary and application composition. It may call the domain layers but
must not duplicate their formulas or introduce private/account/order behavior under the current
stage.

## Dependency rule

Internal package imports flow in one direction:

```text
market_tape → options_domain → short_vol_radar → shadow_engine
```

The arrow means the package on the right may depend on packages to its left. `radar_runtime` may
compose all packages. This direction is enforced by repository tests.

## Canonical time and causality

The system uses separate domains:

- `capture_seq` is the sole known-at and causal order within a capture;
- `collector_received_at_ms` is raw local wall-clock audit evidence and may jump;
- `collector_elapsed_ms` is persisted monotonic session time for durations and coverage;
- Deribit source timestamps are market-domain watermarks and market-time inputs.

Never infer known-at order by comparing independent wall and exchange clocks. Preserve skew and
regressions as evidence rather than clamping them away.

## Artifact contracts

Artifacts are immutable and content-addressed where practical. New artifact types are introduced
only by the closure that consumes them.

Content identity binds meaningful facts, deployed code/Policy, and sealed segments. It does not
require a distinct hash or synchronous disk flush for every network event, RPC, or in-memory
projection step.

### Existing

- `CanonicalEvent` and sealed capture manifest;
- `DecisionFrame`, `RadarDecision`, and `SHORT_VOL_DECISION_RECEIPT`;
- `ShadowPosition`, `OutcomePath`, and `MaturedOutcome`;
- inspect, replay, and Decision Truth evidence-bundle receipts.

### Implemented bounded Decision Truth

- explicit immutable Policy identity and digest;
- one durable `DecisionReceipt` with opportunity counts, deterministic assessment-set identity,
  full selected assessment, code/Policy identity, and lineage.

Raw tape plus code and Policy identity must permit reconstruction of the full structure universe.
The receipt need not duplicate every structure if it preserves counts, failure summaries, the
selected assessment, and a digest of the deterministic assessment set. This receipt describes the
accepted bounded contract; it is not reused as a target runtime receipt.

### Implemented Outcome Truth

- one immutable `ShadowEntryReceipt` bound to its accepted Decision, structure, assessment,
  horizon, entry economics, Policy, and causal entry sequence;
- one strictly future `OutcomeReceipt` separating actual exposure through exit from any labeled
  later counterfactual and binding executable close plus control-fact lineage;
- independent reconstruction from sealed public facts.

These are bounded Outcome Truth artifacts only. Their implementation does not itself permit a run
ledger, scheduler, generic storage, qualification, promotion, private/account access, or execution.
The frozen `horizon_seconds` and historical `PROFIT_TARGET | FIRST_TOUCH | HORIZON` exit behavior
belong only to that accepted bounded contract. They are not a position-management Policy for a
future forward cohort.

### Current authorized structure-assessment-reachability closure

- one continuously acquired production-public fact stream inside the modular monolith under the
  prospective `DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT` identity;
- rolling state and at least two distinct executed evaluation states caused by consumed market
  facts or necessary time boundaries under one continuously running collector;
- an `evaluation_state_digest` that excludes heartbeat bookkeeping, receipt time, and
  `capture_seq` by itself while retaining `capture_seq` as the causal as-of boundary;
- explicit separation of global risk-input readiness, universe coverage, local structure
  readiness, structure assessment, future Policy action, and admission;
- no new Radar receipt or witness schema; bounded acceptance reuses existing
  inspection/recomputation output over canonical facts for sampled distinct states, and emits no
  per-tick or unchanged-state artifact;
- the prospective `OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_ASSESSMENT`, in which the numerical
  30m/1h/2h/4h grid is one structure's forward risk-scenario vector, never four opportunities or
  fixed holding instructions.

The bounded observation window is only acceptance evidence for the continuous lifecycle. This
closure does not consume a run-wide receipt, Candidate action, Entry, position-management Policy,
mature Outcome, historical archive, generic scheduler, database, service platform, qualification,
Challenger, promotion, private/account access, or execution.

### Queued or later stages only

- `ChallengerPackage` and frozen experiment manifest;
- `QualificationReceipt` and deployment manifest;
- execution intent, account-risk decision, order, fill, and reconciliation receipts.

Queued artifacts are logical trust boundaries, not implementation permission. Do not implement
them until `CURRENT_STAGE.md` activates the closure that consumes them, and never add them as empty
abstractions.

## Policy and Model boundary

The Online Runtime receives an immutable deployed artifact. A transparent deterministic Policy is
a valid deployed artifact. A learned model is optional and must additionally freeze its feature
contract, training dataset identity, model bytes, parameters, and inference code identity.

Model output never bypasses deterministic structure legality, executable pricing, or hard-risk
gates. Generative AI and training code do not run in the per-decision or execution path.

## Shadow boundary

The Product Constitution and Short Vol contract own Shadow semantics. Structurally, Strategy
Decision is separate from experiment admission; actual exposure is separate from counterfactual
paths; and observed executable close is separate from any qualification penalty. One artifact may
reference another but may not collapse these meanings.

Outcome trackers mature independently while new market states are assessed. A later evidence
snapshot may partition Outcomes into mature and immature without stopping acquisition or
retroactively changing earlier Decisions. A future position-management Policy evaluates the same
fixed legs after Entry and emits `HOLD | CLOSE | UNKNOWN` from declared post-Entry inputs. Actual
exposure ends only at an executable selected close or later authorized settlement; a hard
latest-exit boundary creates an obligation to close, not an invented fill. Counterfactual
evaluation of a pre-registered rejected-opportunity cohort uses the same future tape but remains
separately labeled and never creates exposure.

Rejected-opportunity evaluation is a future, explicitly authorized extension of `shadow_engine`,
not part of `STRUCTURE_ASSESSMENT_REACHABILITY` and not a reason to add a generic evaluation
service now.

## Persistence

The production-public lifecycle uses ordered append-only segments that can be rotated, flushed,
and sealed incrementally. `capture_seq` establishes known-at order. Durability must preserve
accepted facts and Decision boundaries, but the architecture does not require per-fact or per-RPC
`fsync`, cross-binding before the next network event, or a single ever-growing run bundle.

Persistence does not duplicate the full derived structure universe or emit a Radar artifact for
every evaluated state. Canonical facts preserve reconstruction. Bounded acceptance reuses existing
inspection/recomputation output to show structure-level denominators, availability, reasons,
assessment-set identity, and a sampled assessed structure; it introduces no new artifact identity.
Future authorized Candidate transitions may persist their selected structures under a later
contract.

When replay is required, it reads each sealed segment once, validates the facts it contains, and
reconstructs the requested scan or Outcome window. Verified segments may be composed into later
cohort reports without re-reading the same bytes once per fact or pretending to replay the
external collection process. This continuous modular-monolith runtime does not authorize a
database, generic storage platform, workflow engine, or multi-service architecture.

## Architecture change rule

Change an established boundary only when the active task identifies the business behavior that
cannot be implemented cleanly under it. Add a direct dependency test or contract test with the
change. Refactoring for legibility is allowed when it is required by the same closure; speculative
generalization is not.
