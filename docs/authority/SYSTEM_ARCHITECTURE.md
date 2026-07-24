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
→ repeated authorized-universe scan cycles
→ per-structure availability and immutable deployed Policy or Model
→ DecisionReceipt with explicit funnel denominators
→ separate Shadow admission
→ asynchronous strictly future Outcome trackers
→ OutcomeReceipt
```

Market facts flow through one shared adapter/tape path. Scan cycles, admitted Shadow positions, and
later evaluation reference that tape rather than starting structure-specific or Entry-specific
collectors. This is not a network exactly-once guarantee. The scan trigger may be time-based,
event-based, or coalesced as declared by the active task; it does not terminate acquisition.

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

Owns rolling DecisionFrame projection, observation windows, market-global risk readiness,
universe coverage, per-structure readiness, the deployed finite-horizon risk method, insurance
assessment, ranking, and candidate/watch/abstain decision.

It must not perform network I/O, consume post-entry Outcome facts, train a model, or access an
account.

### `shadow_engine`

Owns entry-frozen Shadow positions, strictly future Outcome points, observed exits, executable
close economics, and matured Outcomes.

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

### Implemented Decision Truth

- explicit immutable Policy identity and digest;
- one durable `DecisionReceipt` with opportunity counts, deterministic assessment-set identity,
  full selected assessment, code/Policy identity, and lineage.

Raw tape plus code and Policy identity must permit reconstruction of the full structure universe.
The receipt need not duplicate every structure if it preserves counts, failure summaries, the
selected assessment, and a digest of the deterministic assessment set. Do not create a separate
scan artifact unless an active task proves an independent consumer needs it.

### Implemented Outcome Truth

- one immutable `ShadowEntryReceipt` bound to its accepted Decision, structure, assessment,
  horizon, entry economics, Policy, and causal entry sequence;
- one strictly future `OutcomeReceipt` separating actual exposure through exit from any labeled
  later counterfactual and binding executable close plus control-fact lineage;
- independent reconstruction from sealed public facts.

These are bounded Outcome Truth artifacts only. Their implementation does not itself permit a run
ledger, scheduler, generic storage, qualification, promotion, private/account access, or execution.

### Current authorized Radar establishment closure

- one continuously acquired production-public fact stream inside the modular monolith under the
  prospective `DERIBIT_PUBLIC_SHORT_VOL_RADAR_INPUT` identity;
- rolling state and at least two executed scan cycles under one declared trigger rule;
- explicit separation of global risk-input readiness, universe coverage, local structure
  readiness, Policy action, and admission;
- one compact prospective `SHORT_VOL_RADAR_SCAN_SUMMARY` per due cycle; the closure does not alter
  or impersonate `SHORT_VOL_DECISION_RECEIPT`;
- the exact `OBSERVED_PATH_STRESS_FIXED_PRIOR_RADAR_POLICY` delta authorized by
  `CURRENT_STAGE.md`, with no other Policy tuning.

The bounded observation window is only acceptance evidence for the continuous lifecycle. This
closure does not consume a run-wide receipt, Entry, mature Outcome, historical archive, generic
scheduler, database, service platform, qualification, Challenger, promotion, private/account
access, or execution.

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

Outcome trackers mature independently while new scans continue. A later evidence snapshot may
partition Outcomes into mature and immature without stopping the scanner or retroactively changing
earlier Decisions. Counterfactual evaluation of a pre-registered rejected-opportunity cohort uses
the same future tape but remains separately labeled and never creates exposure.

Rejected-opportunity evaluation is a future, explicitly authorized extension of `shadow_engine`,
not part of `RADAR_ESTABLISHMENT` and not a reason to add a generic evaluation service now.

## Persistence

The production-public lifecycle uses ordered append-only segments that can be rotated, flushed,
and sealed incrementally. `capture_seq` establishes known-at order. Durability must preserve
accepted facts and Decision boundaries, but the architecture does not require per-fact or per-RPC
`fsync`, cross-binding before the next network event, or a single ever-growing run bundle.

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
