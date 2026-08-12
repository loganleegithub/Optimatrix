# Shadow Lifecycle Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `BTC_0DTE_DECISION_CASE_V1`

## Purpose

Preserve one future-blind formal entry attempt, its acquisition result, continuing short-risk and
residual-wing duties, and terminal facts for local recovery, trader review, AI Outcome analysis, and
later offline evaluation. A Case is a public Shadow research aggregate, not an account position.

## Durable boundary and isolation

Before `DECISION_OPENED`, authoritative durable business record count is zero. Normal market facts,
scores, rejected structures, unselected attempts, public snapshots, Workbench state, and run
summaries are never persisted.

The current stage permits journals only beneath an explicitly supplied non-legacy test/simulation
root. The lifecycle owner must not read, write, translate, migrate, relabel, recover, or count the
legacy V2 Case root or its 92 Cases. No stable new-product root or compatibility codec is authorized.

## Case and record identity

One Case identity canonically binds at least:

```text
"TwoSidedShadowDecisionCaseV1"
product_spec_identity
Decision Policy identity
SessionDecisionUnit identity
selected four-leg structure identity
decision identity
DECISION_OPENED known-at boundary
schema-v1
```

Every later record binds the same Case and causal predecessor. It cannot change product, Policy,
Session, structure, quantity, or attempt meaning. Source code, runtime, and schema provenance must be
explicit before a stable-root stage can be authorized; the current local stage must not claim that
test journals prove production provenance.

## Authorized record set

One append-only Case journal contains only:

```text
DECISION_OPENED          exactly one
ENTRY_TERMINAL           exactly one known acquisition result
POSITION_CHECKPOINT      zero or more bounded recovery states
OUTCOME                  zero or one terminal Case result
```

Every event has a contiguous sequence, exact key set, Case identity, event kind, and payload. The
sole codec rejects malformed, conflicting, duplicate, reordered, identity-mismatched, or unknown
events. Append publication must not overwrite accepted bytes. A failed append cannot mutate an
already accepted prefix.

## `DECISION_OPENED`

The record is written only for one Policy `CANDIDATE` selected for formal acquisition. It freezes:

- product, Policy, `MarketSessionId`, decision window, and `SessionDecisionUnit` identities;
- Decision identity, causal boundary, phase, score, blocker vector, and required source boundaries;
- selected four-leg structure and full target quantity;
- permitted entry routes, timing/coherence limits, and attempt contract;
- exact non-claims: public Shadow, not order, not fill, no liquidity reservation, atomic execution
  unproven, no account/capital exposure.

Entry facts are not known or stored in `DECISION_OPENED`.

## `ENTRY_TERMINAL`

Entry begins strictly after Decision opening. One attempt identity covers all four selected legs.
The terminal classification is `FULL_ENTRY`, `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`,
`TWO_SIDES_INCOHERENT`, `WINGS_ONLY`, or `NO_ENTRY`; if facts cannot establish one, no known
terminal event may be fabricated.

The record freezes raw/stressed consumed levels, fee reserves, quantity, timing/coherence evidence,
route, blockers, resulting legs, native/boundary-valued cashflows, and the entry status from which
strategy eligibility is derived. Eligibility is not stored as a second mutable truth.

Only `FULL_ENTRY` may set `strategy_outcome_eligible=true`. Partial, wings-only, and no-entry are
known acquisition evidence and set a precise primary-strategy ineligibility reason.

## Position and partial remediation

`FULL_ENTRY` opens normal two-sided carry. `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`, and
`TWO_SIDES_INCOHERENT` open immediate bounded remediation and cannot transition into normal carry
merely because time passes. `WINGS_ONLY` opens residual-wing duty with no short risk. `NO_ENTRY`
opens no Position.

Later remediation never rewrites `ENTRY_TERMINAL`, promotes a partial Case to `FULL_ENTRY`, or
changes its primary-strategy ineligibility reason.

The Position state preserves each leg and side independently. For a normal-carry `FULL_ENTRY`, any
Base risk trigger freezes one `BOTH_SIDES` exit duty; the system may not turn the surviving side into
an undeclared single-Vertical carry strategy. Partial-entry remediation remains scoped to the short
exposure that was actually acquired. During either duty, a dangerous short leg may be projected
closed without requiring its long wing to have a bid. The residual long option remains a bounded
duty.

Position risk handling is a causal reducer, not an instantaneous stop or continuous service:

```text
strictly-future Position risk observation
→ MONITORING or frozen EXIT_REQUIRED duty
→ strictly-future public-book exit-price observation
→ EXIT_REQUIRED, SHORT_RISK_FLAT, or PORTFOLIO_TERMINAL
```

The observation that creates an exit duty cannot also price or clear it. Every public quote used for
the exit projection must have source and receive timestamps strictly later than the frozen intent,
no later than the projection boundary, no older than the Policy freshness budget, and inside the
existing quantity and coherence constraints. Missing, stale, discontinuous, incoherent, or
unexecutable facts keep the same duty and exact blocker; they never become a zero Delta, a completed
exit, or a fill. Public-book exit calculations remain counterfactual price projections.

`POSITION_CHECKPOINT` exists only for state that restart, trader review, or Outcome computation
cannot derive from earlier facts. It is not a per-tick history. It freezes the originating Case and
Entry identities, side/leg states, accepted counterfactual cashflows, first risk action, intent
boundary, last material exit attempt/blocker, and residual wings. A Gap or restart does not create a
new Entry, clear a duty, or synthesize a transition.

## Risk-flat and terminal truth

```text
SHORT_RISK_FLAT      every short leg has been bought back or officially settled
PORTFOLIO_TERMINAL   every remaining long wing has been sold or officially settled
```

`SHORT_RISK_FLAT` can precede portfolio terminality. Process loss, stale/unknown public facts, one
failed attempt, or a Gap does not prove either. Official delivery price may settle remaining
contractual payoff; missing delivery facts remain pending.

## Outcome and eligibility

`OUTCOME` freezes the terminal method, terminal boundary, entry and exit/settlement cashflows,
standard public fee reserves, BTC-native economics, separately labelled boundary-valued economics,
observation quality, and eligibility dimensions.

The dimensions are independent:

```text
decision_evaluable
entry_result_known
strategy_outcome_eligible
terminal_economics_eligible
continuous_path_eligible
qualification_eligible
```

- Primary strategy Outcome: requires coherent `FULL_ENTRY` and terminal result.
- Partial/wings/no-entry: may have known acquisition or terminal economics, but never primary
  full-Condor return eligibility.
- Gapped: may retain known terminal economics while losing continuous-path eligibility.
- Qualification: remains a later offline, pre-registered decision and is not granted by the journal.

One global eligibility Boolean is forbidden.

## Recovery

Recovery validates the full accepted journal prefix through the sole codec, reconstructs the same
Case and Position identities, and resumes any short-risk or residual-wing duty. It never rewrites
history, backfills missed facts, converts UNKNOWN to calm, merges separate attempts, adopts a legacy
Case, or creates an Outcome from process termination.

## Non-claims

Journal events describe simulated public counterfactuals. They are not orders, fills, account
positions, realized account PnL, margin evidence, capital exposure, execution receipts, Policy
qualification, Edge, Alpha, or profitability evidence.
