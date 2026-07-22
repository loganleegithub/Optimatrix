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

For each strict as-of market state, candidate holding horizon, side, expiry, and allowed structure:

```text
visible executable premium
- finite-horizon claim reserve
- entry and close friction
- liquidity reserve
- model and method uncertainty
- strategy and future account constraints
```

Only a positive conservative margin may produce a candidate-class research decision. A candidate
is not trading authority.

## Product business loop

```text
1. continuously capture authorized public market facts
2. construct a strict current DecisionFrame
3. scan the complete authorized executable structure universe
4. run the immutable deployed Policy or Model
5. emit CANDIDATE, WATCH, or ABSTAIN and a DecisionReceipt
6. record strictly future path, executable close cost, and Outcome
7. let an offline AI Researcher propose one explicit Challenger
8. independently replay, test, and forward-validate incumbent and Challenger
9. promote only under a pre-registered qualification contract
10. execute only after separate account, capital, and execution authorization
```

The current implementation name `RESEARCH_CANDIDATE` is the public-Shadow encoding of the
candidate-class action. Renaming that schema is not implied by this Constitution.

## Roles and trust boundaries

### Online Runtime

The Online Runtime executes only immutable, identified, deployed Policy or Model artifacts. It may
collect, project, scan, infer, apply strategy-risk checks, and produce receipts. It may not train,
rewrite, approve, promote, or replace its deployed artifact.

### Outcome and evidence plane

The evidence plane records Decision receipts and strictly post-entry market facts. It computes
observed Shadow Outcomes. Actual exposure ends at the selected exit; a full-horizon counterfactual,
when retained, is a separate labeled artifact.

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
2. Outcome inputs contain only facts strictly after entry.
3. Missing, stale, incomplete, or contaminated evidence is `UNKNOWN`, never zero or calm.
4. Executable entry, close, and PnL use visible bid/ask, a visible combo, or future actual fills;
   mark and mid are descriptive only.
5. Every decision freezes data lineage, code identity, Policy/Model identity, and parameters.
6. Every Shadow position freezes entry assumptions, fees, quantity, maximum loss, and horizon.
7. Zero candidates and zero entries are valid results.
8. Strategy risk and account risk may reduce or veto a decision; they may never create one.
9. An AI proposer may not verify, approve, promote, or deploy its own Challenger.
10. Qualification criteria are fixed before validation and include `NO_TRADE`.
11. Public Shadow evidence cannot be represented as real fill or execution evidence.
12. No later-stage authority is inferred from code presence, green tests, matching digests, prior
    stage success, or historical artifacts.

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
