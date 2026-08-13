# Shadow Lifecycle Contract

**Status:** ACTIVE CASE, POSITION, AND OUTCOME CONTRACT

**Owning capability:** `BTC_0DTE_DECISION_CASE_V1`

This contract owns the future-blind Decision Case, durable journal, Position duties, remediation,
terminal facts, Outcome eligibility, and recovery. Entry classifications come from
`BTC_0DTE_TWO_SIDED_SHORT_VOL.md`; product-wide evidence and non-claims come from
`../authority/PRODUCT_CONSTITUTION.md`.

## Durable boundary and Case identity

Before `DECISION_OPENED`, authoritative durable business record count is zero. Market facts,
scores, rejected structures, unselected attempts, snapshots, run summaries, and Workbench state are
transient.

One Case identity binds the product, Policy, `SessionDecisionUnit`, selected four-leg structure,
Decision identity and known-at boundary, and schema identity. Every later record binds the same
Case and causal predecessor; product, Policy, Session, structure, quantity, and attempt meaning
cannot change. Any journal root must be explicitly supplied and satisfy the product's legacy
isolation boundary.

## Journal records

The sole append-only journal accepts only:

```text
DECISION_OPENED      exactly one
ENTRY_TERMINAL       exactly one known acquisition result
POSITION_CHECKPOINT  zero or more material recovery states
OUTCOME              zero or one terminal Case result
```

Records have contiguous sequence, exact Case identity, event kind, and payload. The codec rejects
malformed, conflicting, duplicate, reordered, identity-mismatched, or unknown events. An append
cannot overwrite accepted bytes; failure leaves the accepted prefix unchanged.

`DECISION_OPENED` is written only for the selected formal `CANDIDATE`, before Entry facts are known.
It freezes the unit and Decision identities, causal boundary, selected structure and quantity,
Policy, permitted routes and budgets, source boundaries, and public-Shadow non-claims.

`ENTRY_TERMINAL` is strictly later. It records the BTC-contract-owned known Entry result, consumed
levels, fees, quantity, timing/coherence evidence, resulting legs, and counterfactual cashflows.
Strategy eligibility is derived from the frozen result rather than stored as a second mutable
truth. Only `FULL_ENTRY` can be eligible for the primary two-sided strategy Outcome.

## Position and remediation duties

`FULL_ENTRY` opens normal two-sided carry. Partial or incoherent short acquisition opens immediate
bounded remediation and never transitions into normal carry. `WINGS_ONLY` opens residual-wing duty
without short risk. `NO_ENTRY` opens no Position. Remediation cannot rewrite
`ENTRY_TERMINAL`, promote a Case, or change its strategy-ineligibility reason.

The Position preserves every leg and side independently. A normal-carry risk trigger freezes one
`BOTH_SIDES` exit duty; the surviving side cannot become an undeclared single-Vertical strategy.
Partial remediation is limited to exposure actually acquired. A dangerous short may be projected
closed even when its protective wing lacks a bid; the remaining long wing keeps a bounded duty.

Risk handling is causal:

```text
strictly-future Position observation
→ MONITORING or frozen EXIT_REQUIRED duty
→ strictly-future public-book exit observation
→ EXIT_REQUIRED, SHORT_RISK_FLAT, or PORTFOLIO_TERMINAL
```

The observation that creates an exit duty cannot also price or clear it. Exit quotes must be newer
than the frozen intent, within the projection boundary, fresh under Policy, full-quantity, and
coherent. Missing, stale, discontinuous, incoherent, or unexecutable facts preserve the same duty
and exact blocker; they do not synthesize a close or fill.

`POSITION_CHECKPOINT` records only material state that restart, trader review, or Outcome
calculation cannot derive from prior records: leg/side states, accepted counterfactual cashflows,
first risk action and intent boundary, last material attempt/blocker, and residual-wing duty. It is
not a per-tick history. A Gap, restart, unavailable market, or failed attempt does not create a new
Entry or clear an existing duty.

## Risk-flat and terminal truth

```text
SHORT_RISK_FLAT      every short leg is bought back or officially settled
PORTFOLIO_TERMINAL   every residual long wing is sold or officially settled
```

`SHORT_RISK_FLAT` may precede `PORTFOLIO_TERMINAL`. Process loss, stale or unknown facts, one failed
quote, or a Gap proves neither. Official delivery facts may settle contractual payoff; missing
delivery facts leave the duty pending.

## Outcome and eligibility

`OUTCOME` freezes terminal method and boundary, entry/exit/settlement cashflows, standard public fee
reserves, native BTC economics, separately labelled boundary-valued economics, observation quality,
and these independent dimensions:

```text
decision_evaluable
entry_result_known
strategy_outcome_eligible
terminal_economics_eligible
continuous_path_eligible
qualification_eligible
```

A primary strategy Outcome requires coherent `FULL_ENTRY` and a terminal result. Partial,
wings-only, and no-entry Cases remain acquisition evidence but never enter that return denominator.
A gapped Case may retain known terminal economics while losing continuous-path eligibility.
Qualification is a later offline decision and is never granted by the journal. One global
eligibility Boolean cannot replace these facts.

## Recovery

Recovery validates the complete accepted prefix through the same codec, reconstructs the same Case
and Position, and resumes every short-risk or residual-wing duty. It does not rewrite history,
backfill missed market facts, convert `UNKNOWN` to calm, merge attempts, adopt a legacy Case, or
create an Outcome from process termination.
