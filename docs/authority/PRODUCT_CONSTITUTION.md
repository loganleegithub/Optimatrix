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

Normal market events that produce no Short Vol anomaly are not durable business objects. Raw
full-chain ticks and per-update `NO_ANOMALY` rows are not persisted by default. The runtime may
retain bounded
in-memory history required by a declared causal feature. Minimal service coverage and gap metadata
may be retained so a report can distinguish observed `NO_ANOMALY` from blindness; it is not market
evidence and cannot reconstruct the chain.

An explicitly approved evidence task may temporarily seal a bounded public stream. That mode is a
validation harness, never a dependency of the Online Runtime and never its unit of work.

### Short Vol Radar

`SHORT_VOL_RADAR` is the first strategy-specific Radar. A relevant state change immediately
re-evaluates the affected current market state. Static saved facts are never scanned repeatedly,
and an arbitrary timer does not manufacture a new Radar episode.

The Radar asks one question:

> Is target-size executable sell-side implied volatility unusually rich under the exact deployed
> causal baseline for the same remaining-life interval?

It then reports official atomic-quote availability as an independent fact. For each applicable
option instrument, detector truth is:

- `UNKNOWN`: required detector facts are missing/invalid or derived classification is numerically
  unresolved;
- `NO_ANOMALY`: required detector facts are usable and the activation rule has not passed;
- `ANOMALY_ACTIVE`: the activation rule has passed and the clear/re-arm rule has not completed.

For each short-leg episode, `public_atomic_quote_state` is independently
`NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO | NO_TARGET_SIZE_CREDIT_QUOTE |
PUBLIC_ATOMIC_QUOTE_AVAILABLE`. It is `NOT_EVALUATED` when no anomaly is active. A missing or
empty combo book cannot erase a known anomaly. Future order state and fill state form a third,
private-authority layer; they are not inferred from any public quote.

`NO_ANOMALY` is a current query result, not a receipt written for every update. `UNKNOWN` is never
converted to `NO_ANOMALY`, zero, calm, no-combo, or economic rejection.

A Short Vol detector is one content-identified
`POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE` Policy artifact. Before each live run it must freeze:

- feature definitions, units, instrument scope, and strict known-at inputs;
- a causal same-remaining-life trailing-index-variance baseline;
- trigger formula and numerical boundary;
- any confirmation or persistence rule;
- clear, hysteresis, episode identity, and re-arm rules;
- source continuity, warm-up, missingness behavior, and exact numeric parameter values.

The primary signal is a pre-registered pointwise hypothesis: target-size executable sell-side IV
versus the annualized volatility obtained by scaling a causal trailing-index-variance baseline
over the same now-to-expiry interval. Implied and baseline total variance remain inspectable, but
a stated IV percentage is never silently interpreted as the same percentage in variance. This
baseline is neither a delivery-TWAP distribution forecast nor a validated physical forecast,
model-free VRP, or proven edge. The Policy gives each option instrument its own pointwise
episode. One complete active short-leg episode is a positive anomaly witness even when unrelated
potential legs are unavailable; aggregate coverage is then `DEGRADED`. An aggregate
`NO_ANOMALY` requires complete relevant scope. Within one runtime that scope is exactly
`Policy identity × expiry_timestamp × option_type`, contains at least one reconciled catalog
instrument, and never drops a known OTM/Delta/liquidity-ineligible instrument merely to improve
coverage. An empty scope is not an evaluation. A structure may qualify only when its short leg has
a current active episode, which the atomic event references directly. Same-expiry skew,
adjacent-expiry total variance, and local
surface richness may be declared confirmations. Order-book, trade, volume, or open-interest
changes may trigger recomputation but cannot alone prove that volatility is rich.

No universal numerical threshold is part of this Constitution. Numeric values belong to the
Policy file, not implementation constants. One process binds one exact Policy identity for its
entire run and cannot hot-reload, tune, approve, or promote it. After an observation interval, a
human may approve a successor within the already authorized Policy schema, including target
quantity, TTE bands/gaps and call/put inclusion, lookbacks/weights/floor, Delta boundaries, and
activation/clear persistence. These are explicit detector scope/parameter changes, not silent
edits. The successor has a new identity, process, and forward interval; historical events are
never relabeled. Formula, source-family, structure-family, or evaluation-claim changes require a
new authorized task. Automatic training, selection, or deployment is never implied by calibration.

On one `ANOMALY_ACTIVE` episode transition, the runtime freezes one minimal
`SHORT_VOL_ANOMALY_EVENT` containing the consumed detector facts and Policy identity. If a
matching official atomic combo later exposes a positive normalized target-size credit quote in
the required combo direction, the runtime separately freezes `PUBLIC_ATOMIC_QUOTE_EVENT` with
only the official combo facts. Neither event
contains the full option chain. Direct tests verify formulas and state transitions; this first
closure does not require replay, a second calculator, or persisted recomputation evidence.

### Underwriting Decision

An active anomaly and an official target-size atomic quote are necessary inputs to later
Underwriting. Neither says the trade is worth taking.

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
identified actual execution Outcome. A rejected or merely observed anomaly/quote opportunity may
be studied only under a labeled counterfactual contract and never creates exposure. Without
Shadow admission there is no Outcome object; that absence does not create an `UNKNOWN` Outcome.

## Product business loop

```text
1. continuously maintain the live Deribit BTC 0–3DTE option-chain state in memory
2. on relevant changed facts, run the exact content-identified Short Vol anomaly detector
3. persist one minimal anomaly event on activation
4. while active, report official target-size atomic-combo availability independently
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

Radar continues while prior anomaly/quote events, Decisions, positions, and Outcomes mature
independently. There is no one-hour or six-hour business run. A bounded observation duration may
limit an acceptance test, but it cannot force the market to produce an anomaly or atomic quote
and does not define product behavior.

## Roles and trust boundaries

### Online Runtime

The Online Runtime may ingest authorized facts, maintain bounded current state, apply immutable
deployed Radar, Underwriting, and Position Policy artifacts, and emit the artifacts permitted by
the current stage. It may not train, rewrite, approve, promote, or replace them. Parameter
or declared detector-scope calibration happens only between runs through a human-approved
successor identity.

### AI Researcher

The AI Researcher has read-only access to authorized anomaly, quote, Decision, and Outcome
evidence. It may propose one declared Challenger. It may not change criteria after seeing
results, approve its own work, write to the Online Runtime, or access execution interfaces.

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
   Negative absence claims require complete relevant scope; one positive witness never implies a
   best-price or complete-market claim.
4. The first slice's Shadow admission and close economics require visible target-size atomic combo
   quotes. Component-leg references are diagnostic until an exact legging Policy is authorized;
   actual execution economics use fills. Mark and mid are descriptive only. Detector truth,
   public atomic-quote availability, and future order/fill state remain separate.
5. Public quotes, anomaly events, Shadow Entries, and Shadow close opportunities are never represented
   as fills.
6. Every anomaly event freezes code and Policy identity, one short-leg instrument, causal feature
   summary, outputs, coverage, and trigger values. Every atomic-quote event directly references
   that active short-leg episode and separately freezes official combo identity, direction,
   target quantity, and consumed required-side bid or ask levels. Neither requires the full market
   feed.
7. Normal non-anomaly full-chain events are not durably retained as product evidence. A bounded
   evidence capture requires an explicit task and never changes Online Runtime semantics.
8. The Radar, Underwriting action, admission, Position action, and Outcome are separate states.
9. Availability is separate from economic action. `UNKNOWN` has no `ABSTAIN` action and no zero
   contribution.
10. One observed anomaly episode is namespaced by runtime, Policy, short-leg instrument, and
    activation boundary. It is counted once until clear, known ineligibility, detector-scope exit,
    membership loss, a required detector fact becoming missing or invalid, a derived detector
    classification becoming numerically unresolved, source continuity loss, or run stop. Every
    end stops atomic availability and later recovery requires fresh activation. A source gap ends
    it with `UNKNOWN_AT_GAP`; resync never claims continuity across the gap. Only an explicitly
    declared adjacent-TTE-band suspension or the bounded index-tail
    `TIME_BOUNDARY_PENDING | WATERMARK_PENDING` rollover state may pause and resume the same
    identity while source continuity remains known. Both pause known-active duration, stop Layer
    2, reset incomplete persistence counts, and cannot themselves create an observation. Repeated
    observations and quote flicker do not multiply Radar episodes.
11. A structure identity is its product, canonical legs, direction, expiry, and target quantity.
    Strict as-of state belongs to an observation, not the identity; quote flicker is not a new
    structure or Radar episode.
12. An unchanged consumed market state cannot create a new anomaly, Decision, or Radar episode.
13. A numeric zero-anomaly statement requires known monitor coverage. A numeric zero-Candidate
    statement additionally requires a nonzero Underwriting-evaluable opportunity denominator.
14. Without a later authorized admission, the pipeline creates no Outcome object. A `SHADOW_ENTRY` or
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
