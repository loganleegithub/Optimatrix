# Optimatrix Product Constitution

**Status:** ACTIVE PRODUCT AUTHORITY

**Long-term product:** autonomous 0–3DTE options decision and trading system

**First product slice:** Deribit BTC-USDC defined-risk Short Vol

## Mission

Optimatrix continuously observes an authorized market, detects a strategy-specific Radar signal,
decides whether its executable reward pays for the risk, records strictly future evidence, and
may execute only after separate account and capital authorization.

The product optimizes declared executable utility under evidence and risk constraints. It does
not optimize run count, replay count, trade count, model complexity, or headline win rate.
Machine learning is optional and must earn deployment through pre-registered validation.

## First product slice

```yaml
market: Deribit
underlying: BTC
product: BTC_USDC_LINEAR_OPTIONS
universe: actual_time_to_expiry_greater_than_0_and_at_most_72_hours
strategy_family: DEFINED_RISK_SHORT_VOL
initial_structure_family: 1x1_same_expiry_vertical_credit_spread
first_validation_environment: production_public_shadow
```

The universe is selected from actual expiry timestamps. A Daily, Weekly, Monthly, or Quarterly
label neither includes nor excludes an instrument; any authorized BTC option enters when its
actual remaining life is inside the window and leaves when it expires.

Deribit and defined-risk Short Vol are one vertical product slice. They do not authorize a generic
market, strategy, model, storage, or workflow platform.

## Authoritative business objects

### Market Monitor

`MARKET_MONITOR` is the always-on ingestion and in-memory maintenance of the current authorized
option chain. Receiving a relevant public market event, validating continuity, updating the
current state, and notifying the first Radar are one product flow. There is no second job that
periodically rereads saved market data and calls that another scan.

Normal market events that produce no Short Vol hit are not durable business objects. Raw full-chain
ticks and per-update `NO_HIT` rows are not persisted by default. The runtime may retain bounded
in-memory history required by a declared causal feature. Minimal service coverage and gap metadata
may be retained so a report can distinguish observed `NO_HIT` from blindness; it is not market
evidence and cannot reconstruct the chain.

An explicitly approved evidence task may temporarily seal a bounded public stream. That mode is a
validation harness, never a dependency of the Online Runtime and never its unit of work.

### Short Vol Radar

`SHORT_VOL_RADAR` is the first strategy-specific Radar. A relevant state change immediately
re-evaluates the affected current market state. Static saved facts are never scanned repeatedly,
and an arbitrary timer does not manufacture a new Radar episode.

The Radar asks exactly:

> Is option-implied volatility unusually rich under the frozen detector, and does the same
> strict-as-of state contain an authorized, defined-risk net-credit structure with a visible
> target-size atomic combo quote?

The Radar separates:

- `NO_HIT`: required current facts are usable, but the detector did not produce a hit;
- `UNKNOWN`: required facts are missing, stale, discontinuous, or cannot be aligned;
- `ANOMALY_OBSERVED`: the volatility detector fired, but no authorized target-size atomic combo
  quote was found; component-leg quotes are diagnostic only;
- `RADAR_HIT`: the detector fired and at least one authorized target-size atomic combo quote
  exists.

`NO_HIT` is a current query result, not a receipt written for every update. `UNKNOWN` is never
converted to `NO_HIT`, zero, calm, or economic rejection.

A Short Vol detector is an immutable `SHORT_VOL_RICHNESS_RADAR_POLICY` artifact. Before live use it
must freeze:

- feature definitions, units, instrument scope, and strict known-at inputs;
- a causal same-remaining-life baseline or forecast;
- trigger formula and numerical boundary;
- any confirmation or persistence rule;
- clear, hysteresis, episode identity, and re-arm rules;
- quote freshness, continuity, warm-up, and missingness behavior.

The primary signal is a pre-registered pointwise hypothesis: target-size executable sell-side
implied total variance versus a causal forecast of physical total variance over the same
now-to-expiry interval. It is not model-free VRP or a proven edge. The Policy maps each
expiry/option-type episode to an exact triggered-short-leg set; a structure may qualify only when
its short leg belongs to that set. Same-expiry skew, adjacent-expiry total variance, and local
surface richness may be declared confirmations. Order-book, trade, volume, or open-interest
changes may trigger recomputation but cannot alone prove that volatility is rich.

No universal numerical threshold is part of this Constitution. A later implementation task must
freeze and test the exact first detector before observing its production acceptance result.
Changing that artifact is a Radar Policy change, not an operational adjustment.

On `RADAR_HIT`, the runtime freezes one minimal `SHORT_VOL_RADAR_HIT` snapshot containing the
detector's causal feature-state digest and outputs, the complete triggered-short-leg set, plus
every qualifying atomic structure within the declared usable combo-book scope at the first hit
state in canonical order, including target quantity, combo quote and depth, fees, net credit,
maximum-loss inputs, and causal boundary. The snapshot declares unavailable related scope and
does not claim complete-universe selection from partial coverage. Radar does not secretly rank or
select among the observed set. Direct sequence tests verify the rolling feature engine; the hit
snapshot verifies the final comparison and economics without storing the full feed. Only then may
the system begin targeted analysis or future-path collection for that hit.

### Underwriting Decision

`RADAR_HIT` says that an anomaly and an atomic quote-executable structure coexist. It does not say
the trade is worth taking.

A separately authorized immutable Underwriting Policy compares:

```text
visible executable net premium
- path and jump risk
- short-leg gamma and tail risk
- entry, exit, and legging friction
- liquidity and closeability reserve
- model and evidence uncertainty
- authorized strategy constraints
```

It may output `CANDIDATE | WATCH | ABSTAIN` only when its required facts and its complete
position-management Policy are frozen. Unavailable underwriting has no economic action.
Candidate is not Shadow admission, executed entry, qualification, or trading authority.

### Shadow admission, execution, position management, and Outcome

`SHADOW_ENTRY` requires a still-valid Candidate and a refreshed target-size atomic combo quote
under the exact public admission facts authorized for Shadow. It freezes that counterfactual entry
quote and starts strictly future public path observation. It is not an order, fill, position, or
actual exposure. A future legged admission requires its own legging Policy.

`EXECUTED_ENTRY` exists only under future account, capital, order, and fill authority. Actual
exposure begins with the first opening fill, including a partial or single-leg fill; it does not
wait for every intended leg to fill.

Neither entry kind selects a planned holding duration. After `SHADOW_ENTRY`, or while any future
actual quantity remains open, one immutable Position Policy continuously evaluates relevant state
and outputs:

- `HOLD`: the position thesis and executable exit economics do not require closing now;
- `CLOSE`: a known Policy condition or hard boundary requires an exit attempt now;
- `UNKNOWN`: required facts are insufficient to decide safely between hold and close.

Its inputs include remaining premium, short-leg location and Greeks, actual path and jump state,
volatility-surface state, time to expiry, visible close debit, quote depth and spread, fees,
liquidity, platform state, and explicit latest-exit or settlement boundaries. A boundary creates
an obligation to close or settle; it is not a planned holding duration and does not itself prove
a close.

`CLOSE` is an instruction, not a closing fact. `close_quote_state` is separately one of
`ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`. A missing quote
cannot erase a known hard-close obligation; it makes execution evidence unavailable.

`SHADOW_CLOSE_OPPORTUNITY` exists only when the Position action is `CLOSE` and a strictly later
state has `ATOMIC_COMBO_CLOSE_QUOTE` for the entire remaining Shadow quantity. A
`LEGGED_CLOSE_REFERENCE` is non-simultaneous diagnostic evidence; without a separately authorized
legging exit Policy it does not create a close opportunity, end Shadow duration, or create Shadow
PnL. An atomic Shadow close opportunity is still not a fill or actual holding time.

Under future execution authority, actual exposure ends only when the final closing fill reduces
every leg's remaining quantity to zero or an authorized exchange settlement closes it. Actual
exposure duration runs from the first opening fill to that fact.

A `SHADOW_ENTRY` may create a `SHADOW_OUTCOME`. An `EXECUTED_ENTRY` may create a separately
identified actual execution Outcome. A rejected or merely observed Radar hit may be studied only
under a labeled counterfactual contract and never creates exposure. No Radar hit means no Shadow
admission and no Outcome object; it does not create an `UNKNOWN` Outcome.

## Product business loop

```text
1. continuously maintain the live Deribit BTC 0–3DTE option-chain state in memory
2. on relevant changed facts, run the frozen Short Vol anomaly detector
3. on anomaly, construct and quote-check the authorized defined-risk structures
4. persist only a minimal RADAR_HIT snapshot when anomaly and atomic combo structure coexist
5. let the frozen Underwriting Policy compare premium with path, tail, liquidity, cost, and
   uncertainty
6. output CANDIDATE / WATCH / ABSTAIN; admit SHADOW_ENTRY only under the current authorization
7. after Shadow admission, continuously output HOLD / CLOSE / UNKNOWN from the frozen Position
   Policy
8. record strictly future executable close opportunities and Outcomes without claiming fills
9. let an offline AI Researcher propose one explicit Challenger
10. independently test and forward-validate incumbent and Challenger; promote only under a
    pre-registered qualification contract
11. execute only after separate account, capital, order, and fill authorization
```

Radar continues while prior hits, Decisions, positions, and Outcomes mature independently. There
is no one-hour or six-hour business run. A bounded observation duration may limit an acceptance
test, but it cannot force the market to produce a hit and does not define product behavior.

## Roles and trust boundaries

### Online Runtime

The Online Runtime may ingest authorized facts, maintain bounded current state, apply immutable
deployed Radar, Underwriting, and Position Policy artifacts, and emit the artifacts permitted by
the current stage. It may not train, rewrite, approve, promote, or replace them.

### AI Researcher

The AI Researcher has read-only access to authorized hit, Decision, and Outcome evidence. It may
propose one declared Challenger. It may not change criteria after seeing results, approve its own
work, write to the Online Runtime, or access execution interfaces.

### Independent Verifier and Promotion Controller

The Independent Verifier performs assertion-appropriate reconstruction, leakage-safe historical
evaluation, and forward validation. A future Promotion Controller may switch an incumbent only
after a valid QualificationReceipt and inside a separately authorized promotion envelope.

### Human governance

Humans own this Constitution, data and market scope, allowed strategy and model classes,
qualification criteria, capital and account limits, credentials, emergency stop, and every stage
transition. They do not manually choose individual machine decisions or trades.

### Future execution gateway

Private execution is a separate security and authorization boundary. No strategy decision can
bypass strategy risk, account risk, credential isolation, order reconciliation, or emergency
stop.

## Hard invariants

1. Decision inputs contain only facts known at or before their causal boundary.
2. Shadow Outcome inputs are strictly after `SHADOW_ENTRY`; actual execution Outcome inputs are
   strictly after the first opening fill. Counterfactuals are labeled and never create exposure.
3. Missing, stale, discontinuous, incomplete, or contaminated evidence is `UNKNOWN`, never zero
   or calm.
4. The first slice's Shadow admission and close economics require visible target-size atomic combo
   quotes. Component-leg references are diagnostic until an exact legging Policy is authorized;
   actual execution economics use fills. Mark and mid are descriptive only.
5. Public quotes, Radar hits, Shadow Entries, and Shadow close opportunities are never represented
   as fills.
6. Every Radar hit freezes code and Policy identity, causal feature-state digest, feature outputs,
   trigger values, and qualifying structure economics. It does not require the full market feed.
7. Normal non-hit full-chain events are not durably retained as product evidence. A bounded
   evidence capture requires an explicit task and never changes Online Runtime semantics.
8. The Radar, Underwriting action, admission, Position action, and Outcome are separate states.
9. Availability is separate from economic action. `UNKNOWN` has no `ABSTAIN` action and no zero
   contribution.
10. One anomaly episode is counted once until its frozen clear and re-arm rule has completed.
    Repeated observations and quote flicker do not multiply Radar episodes.
11. A structure identity is its product, canonical legs, direction, expiry, and target quantity.
    Strict as-of state belongs to an observation, not the identity; quote flicker and individual
    legs are not new structures or Radar episodes.
12. An unchanged consumed market state cannot create a new hit, Decision, or Radar episode.
13. A numeric zero-hit statement requires known monitor coverage. A numeric zero-Candidate
    statement additionally requires a nonzero Underwriting-evaluable Radar-hit denominator.
14. Without a Radar hit, the pipeline creates no Outcome object. A `SHADOW_ENTRY` or
    `EXECUTED_ENTRY` with incomplete strictly future evidence may create its own `UNKNOWN`
    Outcome; these are different facts.
15. Strategy risk and future account risk may reduce or veto a decision; they may never create
    one.
16. Qualification criteria are frozen before validation and include a cohort-aligned `NO_TRADE`.
17. An AI proposer may not verify, approve, promote, or deploy its own Challenger.
18. No permission is inferred from code presence, green tests, matching digests, historical
    receipts, or earlier stage success.

## Stage authority

Runtime and development permissions come only from
[`CURRENT_STAGE.md`](CURRENT_STAGE.md). Appearance in the product loop or architecture does not
authorize a later stage.

## Permanent development non-goals

- unbounded self-modification, self-approval, self-promotion, or self-deployment;
- compulsory machine learning;
- persisting the complete market merely because it can be observed;
- replaying unchanged stored facts and calling it live Radar work;
- narrative labels that bypass auditable facts and executable economics;
- optimizing for activity rather than declared executable utility;
- generic platforms or abstractions built before a current business closure consumes them.
