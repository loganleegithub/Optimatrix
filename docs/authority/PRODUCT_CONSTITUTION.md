# Optimatrix Product Constitution

**Status:** ACTIVE PRODUCT AUTHORITY

**Long-term product:** autonomous 0–3DTE options decision and trading system

**First product slice:** Deribit BTC-USDC defined-risk Short Vol

## Mission

Optimatrix turns authorized market facts into auditable deployed decisions, strictly future
Outcomes, and—only under separate capital/account authorization—executions.

Its long-term goal is autonomous operation inside a human-authorized product, governance, capital,
and account-risk envelope. Autonomy is an operating property. Machine learning is optional and
must earn deployment through evidence; it is not a product requirement.

The system optimizes declared executable utility under evidence and risk constraints, not trade
count, explanation count, model complexity, or headline win rate.

## First product slice

```yaml
market: Deribit
underlying: BTC
product: BTC_USDC_LINEAR_OPTIONS
entry_tte: 0_to_72_hours
strategy_family: DEFINED_RISK_SHORT_VOL
structure: 1x1_same_expiry_same_side_vertical
first_validation_environment: production_public_shadow
```

Deribit is the first market and Short Vol is the first strategy family. They are a vertical slice,
not a reason to build a generic market, strategy, model, or workflow platform.

## First Short Vol slice: economic decision

This section constrains the first Short Vol implementation contract, not every future strategy.

For each strict as-of market state, side, expiry, and allowed structure:

```text
visible executable premium
- declared forward risk-scenario reserves
- entry and close friction
- liquidity reserve
- model and method uncertainty
- currently authorized strategy constraints
```

Only a separately authorized Candidate contract may produce a candidate-class research decision.
Before doing so, it must freeze one structure-level aggregation over the complete forward
risk-scenario vector, one immutable Entry Policy, one immutable position-management/exit Policy,
and hard latest-exit/expiry boundaries. The Entry Policy may produce Candidate only when the
resulting structure-level conservative margin is positive under that declared exit behavior. A
positive result in one scenario alone cannot create a Candidate. A candidate is not Shadow
admission or trading authority. Future account and portfolio constraints belong to the separately
authorized execution path; they are not prerequisites for the current public Radar.

Forward risk scenarios describe how the same structure behaves under several future risk
intervals. They are not separate business opportunities, promised holding periods, or exit
clocks. Every configured slot has an explicit `CALCULATED | NOT_APPLICABLE_TTE | UNKNOWN` status;
“complete vector” means every slot is classified, not that an impossible post-expiry interval is
calculated. An all-not-applicable vector contains no risk estimate and cannot be Candidate evidence.
A future Candidate-capable closure must define how not-applicable slots are aggregated and must
define both Entry and position-management semantics before it may emit Candidate; otherwise the
purported entry edge has no defined exit behavior.

## Product business loop

```text
1. continuously consume and retain one shared stream of authorized public market facts needed by
   the product
2. update rolling strict-as-of state and, only when a consumed fact or necessary time boundary
   changes relevant economic state, assess the current authorized universe; implementation may
   recompute it or optimize affected structures without changing the business result
3. let the immutable deployed assessment method estimate a forward risk-scenario vector
4. compare visible premium with path, tail, liquidity, cost, and uncertainty reserves
5. only after separately authorized structure aggregation, Entry Policy, position-management
   Policy, and hard exit boundaries exist, emit CANDIDATE / WATCH / ABSTAIN without counting
   unchanged observations as new opportunities
6. apply separate Shadow admission and an immutable position-management Policy; on relevant
   post-Entry state changes emit HOLD / CLOSE / UNKNOWN and record actual Outcome or separately
   labeled counterfactual evaluation
7. let an offline AI Researcher propose one explicit Challenger
8. independently replay, test, and forward-validate incumbent and Challenger
9. promote only under a pre-registered qualification contract
10. execute only after separate account, capital, and execution authorization
```

The current implementation name `RESEARCH_CANDIDATE` is the public-Shadow encoding of the
candidate-class action. Renaming that schema is not implied by this Constitution.

Market facts flow through one shared collector and canonical tape used by online assessment and
Outcome evaluation; structures and Entries do not start their own collectors. Collection, state
update, and assessment are one continuous business flow even though fact storage and pure domain
calculation remain separate code responsibilities. The Online Runtime does not reread unchanged
local facts and call that a new scan. A duplicate or irrelevant event whose consumed-state
identity is unchanged produces no new economic Decision or opportunity episode.

This is not a network exactly-once claim. The longest observation window is rolling history: it
requires warm-up only when history is genuinely unavailable after initial startup or an unresolved
coverage gap. A time trigger is valid only when a declared consumed classification or membership
actually changes, such as fresh→stale, TTE eligibility, or rolling-window membership; raw clock
passage, continuously changing age/TTE, and heartbeat bookkeeping do not create economic states.
A bounded capture or evidence window is an acceptance harness, not the Online Runtime lifecycle
or a unit of business processing. New structure assessments continue while prior Shadow Outcomes
mature independently.

Readiness is scoped. Market-global facts may affect a whole evaluation, while a missing or stale
instrument fact makes only structures that consume that fact unavailable. Universe coverage,
structure availability, Policy action, admission, and Outcome maturity remain separate states.

## Roles and trust boundaries

### Online Runtime

The Online Runtime executes only immutable, identified, deployed Policy or Model artifacts. It may
collect, project, incrementally assess, infer, apply strategy-risk checks, and produce receipts. It
may not train,
rewrite, approve, promote, or replace its deployed artifact.

### Outcome and evidence plane

The evidence plane records Decision receipts and strictly post-Entry market facts for actual
Shadow Outcomes. Actual exposure ends only at the first executable close selected by the frozen
position-management Policy, or at settlement under a later authorized contract. A hard
latest-exit or maximum-exposure boundary creates an exit obligation; it does not fabricate a fill.
Fixed-time post-Entry checkpoints, when retained, are separate labeled counterfactuals and never
define actual holding time.

To measure false negatives and reserve conservatism, a pre-registered cohort of complete rejected
assessments may also receive strictly post-decision counterfactual evaluation from the same future
fact stream. Such evaluation is never a Shadow position, actual exposure, fill, or observed
strategy PnL.

### AI Researcher

The AI Researcher has read-only access to sealed facts, Decision receipts, and Outcome receipts. It
may propose one declared Challenger hypothesis and experiment. It may not:

- change qualification criteria after seeing validation results;
- verify, approve, promote, or deploy its own Challenger;
- write to the Online Runtime or active deployment pointer;
- access account credentials or execution interfaces.

### Independent Verifier and Promotion Controller

The Independent Verifier runs deterministic replay, leakage-safe historical evaluation, and
forward Shadow validation against criteria fixed before validation. A future Promotion Controller
may switch an incumbent only after a valid QualificationReceipt and only inside a separately
authorized promotion envelope.

### Human governance

Humans do not select individual decisions or trades. Humans own:

- this Product Constitution and the authorized product scope;
- the objective, qualification contract, and permitted promotion envelope;
- allowed data sources and model classes;
- account credentials and execution authorization;
- capital and portfolio/account hard-risk limits;
- emergency stop and stage transitions.

### Future execution gateway

Any private execution capability is a separate security and authorization boundary. A strategy
decision cannot bypass strategy risk, portfolio/account hard risk, credential isolation, order
state reconciliation, or emergency stop.

## Hard invariants

1. Decision inputs contain only facts known at or before the decision causal sequence.
2. Actual Shadow Outcome inputs contain only facts strictly after Entry. A separately labeled
   rejected-opportunity counterfactual contains only facts strictly after its Decision and never
   creates exposure.
3. Missing, stale, incomplete, or contaminated evidence is `UNKNOWN`, never zero or calm.
4. Executable entry, close, and PnL use visible bid/ask, a visible combo, or future actual fills;
   mark and mid are descriptive only.
5. Every decision freezes data lineage, code identity, Policy/Model identity, and parameters.
6. Every Shadow position freezes entry assumptions, fees, quantity, maximum loss, the
   position-management Policy identity, and hard latest-exit or settlement boundaries. Actual
   holding time is an Outcome, not an Entry parameter.
7. Availability is separate from economic action. An unusable assessment has no Policy action and
   cannot be counted as economic `ABSTAIN`.
8. `UNKNOWN` is scoped to the smallest affected fact, feature, structure, or admission gate unless
   a declared market-global dependency is actually unavailable.
9. Zero candidates and zero entries are valid recorded results. A numeric zero-Candidate count
   requires a nonzero Policy-evaluable unique-structure denominator and proves only that scoped
   window/subset's observed count or rate, not Policy value, conservatism, or qualification.
10. One continuous canonical fact stream is reused by structure assessment and Outcomes;
    structures do not start independent market-data captures.
11. Bounded evidence duration never defines the Online Runtime lifecycle.
12. Strategy risk and account risk may reduce or veto a decision; they may never create one.
13. An AI proposer may not verify, approve, promote, or deploy its own Challenger.
14. Qualification criteria are fixed before validation and include a cohort-aligned `NO_TRADE`.
15. Public Shadow evidence cannot be represented as real fill or execution evidence.
16. No later-stage authority is inferred from code presence, green tests, matching digests, prior
    stage success, or historical artifacts.
17. One legal leg pair at one relevant market state is one structure assessment unit. A vector of
    forward risk scenarios does not multiply it into several business opportunities.
18. An unchanged consumed-state identity cannot create another Decision or opportunity episode.
    Collector liveness and repeated computation are not opportunity evidence.
19. A future Candidate contract must pre-register episode identity, persistence/hysteresis, and
    re-arm rules. Repeated observations and microstructure flicker may not be assumed to be
    independent opportunities; forward risk-scenario labels may not enter the episode key.

## Stage authority

Runtime and development permissions are granted only by
[`CURRENT_STAGE.md`](CURRENT_STAGE.md). A later stage is not authorized merely because it appears in
the product loop or system architecture.

## Permanent development non-goals

- unbounded self-modification, self-approval, self-promotion, or self-deployment;
- compulsory machine learning;
- narrative labels that bypass auditable facts and executable risk assessment;
- optimizing for activity rather than declared executable utility;
- generic platforms or abstractions built before a current business closure consumes them.

Environment, data-source, private/account, and execution permissions are current-stage concerns.
Any private execution capability still requires a separate explicit authorization boundary.
