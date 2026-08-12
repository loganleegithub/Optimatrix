# Optimatrix engineering contract

## Purpose and read route

Route one explicit business closure into the smallest coherent change. Before changing behavior,
read, in order:

1. `docs/authority/PRODUCT_CONSTITUTION.md`;
2. `docs/authority/NORTH_STAR.md`;
3. `docs/authority/CURRENT_STAGE.md`;
4. `docs/authority/DELIVERY_CONTRACT.md`;
5. the one active task under `tasks/`;
6. `docs/authority/SYSTEM_ARCHITECTURE.md` when modules, persistence, runtime state, or dependencies
   change;
7. `docs/authority/EXECUTION_CONTRACT.md` and the owning contract under `docs/contracts/`.

Authority states current product truth. It is not an incident archive, deployment controller,
compatibility catalogue, proof package, or substitute for business acceptance.

## Product hard rules

1. The sole implemented product is same-Deribit-session, two-sided, four-leg, defined-risk BTC
   premium sale: one Put Credit Vertical plus one Call Credit Vertical. A single Vertical is a
   component and future comparison arm, never the canonical Short Vol product.
2. `0DTE` means expiry at the end of the current Deribit `08:00–08:00 UTC` settlement Session. A
   rolling `TTE < 24h` label is insufficient.
3. Executable Session VRP is the reason to sell and Theta is the monetization mechanism. High
   premium cannot override Gamma, jump, scheduled-event, directional-breakout, concentration, or
   execution risk.
4. One `SessionDecisionUnit` is the only funnel counting unit. Options, legs, Verticals, structures,
   quotes, retries, and UI rows do not create additional product opportunities.
5. One selected entry attempt is one coherent four-leg attempt. `FULL_ENTRY` requires the complete
   selected Condor at full quantity from one attempt identity and bounded causal/timing limits.
   Independently successful Verticals cannot be combined after the fact.
6. `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`, and `TWO_SIDES_INCOHERENT` are acquisition failures with live
   short risk. They enter bounded remediation immediately and can never enter normal carry.
   `WINGS_ONLY` and `NO_ENTRY` create no short-premium Position.
7. `SHORT_RISK_FLAT` and `PORTFOLIO_TERMINAL` are distinct. Flatten the dangerous short even when a
   protective wing lacks a bid; any residual long wing retains a bounded lifecycle duty.
8. Public combo absence means `ON_DEMAND_COMBO_LIQUIDITY_UNOBSERVED`; it does not prove that the
   structure or component routes are impossible. A public quote is never an order, fill, liquidity
   reservation, or atomic-execution claim.
9. BTC Short Vol is the only implemented Channel. The other three 2x2 cells are reserved
   descriptors with no Policy, owner, Case codec, runtime, or generic extension framework.

## Funnel and task gates

1. Every task must move one canonical funnel stage, reduce its earliest material blocker, improve
   the trader-visible explanation, or delete a proven non-product obstacle without losing truth.
2. Before editing, the active task names the `SessionDecisionUnit` denominator, exact baseline,
   primary blocker, expected user-visible or funnel delta, durable-data effect, and complexity
   added/deleted.
3. `CURRENT_STAGE` and `tasks/` agree exactly: `NONE` means only `TEMPLATE.md` exists; otherwise
   exactly one non-template task is `ACTIVE` and linked from `CURRENT_STAGE`.
4. Tests, scenario count, object count, document count, manifest, archive digest, runtime duration,
   and green CI are supporting evidence. None is product progress or Policy qualification.
5. A valid `0` requires a known positive denominator. Missing, zero, stale, contradictory, or
   incomplete required facts remain `UNKNOWN` or `NOT_YET_MEASURED`; they cannot create a Candidate,
   Decision Case, normal carry, known Outcome, or calm-market claim.

## Data and evidence gates

1. Before `DECISION_OPENED`, authoritative durable business record count is zero. A bounded public
   snapshot performs no durable write and cannot open a Decision Case.
2. A formal `CANDIDATE` may open one Decision Case before future acquisition is known. The Case
   freezes the selected product, Policy, SessionDecisionUnit, structure, decision boundary, and
   exact non-claims. Entry and later lifecycle facts must be strictly future facts.
3. Decision eligibility, strategy-Outcome eligibility, terminal-economics eligibility,
   continuous-path eligibility, and qualification eligibility are separate fields. Partial,
   wings-only, no-entry, gapped, and unknown results are never relabelled as full-Condor evidence.
4. The legacy repository, runtime checkout, V2 Case root, V2 Policies, and 92 historical Cases are
   external historical assets. This product may not read, write, translate, migrate, relabel,
   recover, count, or import them.
5. New Decision journals require an explicitly supplied non-legacy root. No stable production root,
   continuous service, private API, account, margin, order, fill, RFQ, capital, or execution
   permission exists in the current stage.
6. Current facts and every business formula have one owner. Do not add a second schema,
   validator-of-validator, replay graph, browser-side calculator, database, message bus, plugin
   discovery, generic N-leg engine, online trainer, host commissioning, or process self-audit.

## Engineering gates

- Reuse audited product, tick, depth, fee, settlement, identity, and lifecycle calculators when they
  fit the new product contract; do not preserve obsolete V2 strategy semantics for convenience.
- Prefer one direct module and focused dataclass over an abstract interface with one caller.
- Remove obsolete code in the same change; keep no parallel legacy strategy path or hidden
  translator.
- Run the task's focused checks and repository gate, inspect the final diff and references, and
  report unavailable external checks exactly.
- Do not claim completion until the active task's business delta is directly observed. Green tests
  alone never satisfy the task.
