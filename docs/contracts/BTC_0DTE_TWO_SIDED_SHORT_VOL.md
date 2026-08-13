# BTC 0DTE Two-Sided Short Vol Contract

**Status:** ACTIVE BUSINESS CONTRACT — B3 PUBLIC SHADOW SOURCE CONFORMANT; PRIVATE ENTRY ABSENT

**Owning capability:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

This contract owns the chain from MarketObservation through Decision and Entry truth. Product-wide
boundaries remain in `../authority/PRODUCT_CONSTITUTION.md`; TradeCase and later lifecycle belong to
`CASE_POSITION_OUTCOME.md`; exchange facts are indexed in `../research/PRIMARY_SOURCES.md`.

## Session and decision identities

An option is `0DTE` only when its expiry is the end of the current Deribit `08:00–08:00 UTC`
Session. A rolling `TTE < 24h` label is insufficient. A Session partitions expiry and evidence; it
is not one exclusive trading opportunity.

Deribit UTC is the only absolute backend business-time domain. Session and Window ownership use
validated Deribit time, never the host wall clock. A market source timestamp and `observed_at`
describe when the public market fact occurred; `known_at` describes when the complete causal cut
became available, mapped from validated Deribit response timing into that same UTC domain. They
remain separate because a fact may occur before it can legally be used. Monotonic process time may
measure transport and sleep durations but cannot appear in a Decision identity or market fact.

`MarketObservationId` identifies one immutable causal market cut with source and causal-known
boundaries, continuity identity, universe scope, values, method identities, and DataHealth. It may
contain many instruments without becoming many opportunities.

`DecisionWindowId` is the sole product and learning denominator:

```text
product identity
+ MarketSessionId
+ WindowSchedulePolicyId
+ scheduled window start
+ scheduled window end
```

The frozen schedule defines cadence, alignment, and input grace before Outcomes exist; Authority
does not hard-code a minute interval. A Session may contain many Windows, so materially later market
regimes can be evaluated independently. Each Window encountered by an enrolled runtime produces
exactly one authoritative Base DecisionRecord. A Window missed before enrollment remains measured
as missing and is never backfilled; a Window attempted by the runtime but lacking valid data becomes
`UNKNOWN`. No Candidate and no trade still consume an encountered Window. Re-runs reuse its
identity. Each Base or Challenger DecisionRecord separately binds its frozen DecisionPolicyId
without changing the shared Window.

`OpportunityEpisodeId` content-binds its grouping Policy and ordered DecisionWindowIds. It is an
optional, future-blind grouping for re-entry control or research stratification, not a learning
denominator, and cannot merge, delete, or create Windows. It has no runtime state machine until a
current consumer and frozen Policy require one. A grouping that uses future paths is an Outcome
label, never an online gate.

Each Base Window binds zero or one causal MarketObservation; absence yields `UNKNOWN` with
`NO_OBSERVATION`. The Window
may select at most one primary StructureCandidate, and only a final `CANDIDATE` Decision may open one
TradeCase. Observations, options, quotes, Verticals, Condors, retries, routes, TradeCases, Positions,
and UI rows never change the Window denominator. An offline Challenger shares the same Window and
causal inputs but has its own frozen Policy result; it cannot change the Base record. Existing
Position capacity or risk allocation may block a later Window without erasing it.

## Environment and DataHealth

Before scoring or structure selection, the Window must know:

- the bounded instrument universe and whether every requested fact was obtained;
- source, receive, freshness, continuity, and cross-input coherence boundaries;
- implied-variance and physical-path method identities with aligned horizon and coverage;
- event-state value, source, and known-at boundary; and
- exact missing, contradictory, or out-of-bound reasons.

Incomplete DataHealth produces `Decision.UNKNOWN`. It does not become calm market, risk trigger,
Candidate, or no-trade evidence. Known market facts may then produce `ABSTAIN`, `REVIEW`, or
`CANDIDATE`.

Current public measures must be named as proxies:

```text
nearest-ATM mark-IV variance proxy
trailing matched-horizon realized-variance proxy
shortlisted public OI × absolute Gamma concentration proxy
```

Their ratio is a `VRP proxy`, not executable model-free VRP. They are not a physical forecast,
dealer Gamma exposure, proof of pin/breakout/mean reversion, or a complete market view. Event state
remains explicit human or external-calendar input until another current owner exists.

## Four-leg structure

Each `StructureCandidate` is one whole product containing a Put and Call Credit Vertical. It is
jointly evaluated and selected under one causal cut. Component books are inputs; the two sides are
never independently selected trades.

The primary StructureCandidate freezes the four legs, ratios, option amount, expiry, Policy,
MarketObservation, Decision boundary, native BTC credit, contractual USD payoff cap,
boundary-valued USD diagnostics, and the reasons it outranked bounded alternatives. USD reference
values use an explicit index and known-at boundary; they are not account capital or margin.

Current public short-leg ask depth may be a liquidity score or stress diagnostic. It is not future
reserved liquidity and cannot be a hard structure veto. Public combo absence is likewise not a
veto: an authorized `private/create_combo` call can return an existing Combo or create one.

## Inverse units and risk allocation

BTC inverse-option units never substitute for one another:

- option amount is base-currency option amount and each contract multiplier is 1 BTC;
- option premium, trading fee, and cashflow are denominated in BTC;
- strikes, spread width, and contractual intrinsic-payoff cap are denominated in USD;
- settlement converts USD intrinsic payoff into BTC using the actual delivery price; and
- boundary-valued USD is a reference conversion of BTC at one explicit index and timestamp, not
  capital, margin, or final settlement truth.

Wings cap the spread's contractual intrinsic payoff in USD. Because inverse settlement divides
that USD payoff by the delivery price, this contract claims no unconditional maximum loss in native
BTC. Risk evidence retains the USD cap, BTC premium and fees, and declared delivery-price stress
scenarios separately.

Before the Decision may become `CANDIDATE`, Public Shadow freezes a `ShadowRiskAllocation`
containing:

- Policy and allocation identities and known-at boundary;
- budget metric, currency/unit, and stress-scenario aggregation rule;
- full-product option amount and selected structure;
- maximum contractual spread payoff in USD;
- entry premium and fee projection in BTC;
- boundary-valued USD reference with index and timestamp;
- declared delivery-price scenarios with BTC and USD stress loss;
- entry slippage and exit-cost/liquidity stress;
- same-Session Shadow budget used and remaining, plus concurrent-Position limit; and
- allocation expiry and release condition.

This is a research notional limit, not equity, margin, available funds, or a capital reservation. If
any required value is unknown, the Decision cannot become a Candidate. The allocation result is
`AVAILABLE`, `UNAVAILABLE(reason)`, or `UNKNOWN(reason)`: only `AVAILABLE` permits `CANDIDATE`.

A future real Position requires a separate `AccountRiskReservation` derived from authenticated
equity, margin, existing positions, available capacity, account-specific fees, and reservation
state. It belongs to private stages and cannot be inferred from Shadow allocation or public depth.

## Decision result and TradeCase boundary

The BTC contract owns each enrolled-Window `DecisionRecord`: it freezes DecisionWindow, Base Policy,
known-at boundary, the complete immutable causal MarketObservation input, DataHealth, result,
blockers, risk-allocation result, and selected structure or exact non-selection reason. The retained
observation includes its context, method and source boundaries, and full bounded quote/depth input
so the same Window can later be replayed against a Challenger without reconstructing or changing
the Base fact. One Window produces exactly one Base result:

```text
UNKNOWN     required fact or calculation is unresolved
ABSTAIN     facts are known and Policy rejects the opportunity
REVIEW      facts are known but the non-enrolled setup remains diagnostic only
CANDIDATE   one structure and ShadowRiskAllocation are frozen
```

A Candidate may open one future-blind TradeCase. `REVIEW` grants no manual override or Entry.
Entry evidence must be strictly later than the Decision boundary and bind the same product, Window,
optional Episode, Policy, structure, amount, and truth layer. A TradeCase is not an Entry or
Position.

## Public Shadow Entry

Public Shadow evaluates the selected four legs as one indivisible counterfactual product from one
causal market cut. Its result is one of:

```text
SHADOW_ATOMIC_EVALUABLE       full-amount whole-product economics are known
SHADOW_ATOMIC_NOT_EVALUABLE   complete facts show the declared estimate cannot be formed
UNKNOWN                       required facts are missing or causally invalid
```

`SHADOW_ATOMIC_EVALUABLE` means the frozen four legs at the same ratios and full target amount can
be priced by the declared Shadow model from one causal cut. It is not a Combo-executability or fill
claim. It may open a `truth_layer=SHADOW_PROJECTION` Position for research.

`SHADOW_ATOMIC_NOT_EVALUABLE` means complete facts prove that the declared Shadow model cannot
price the whole target product; it does not prove a real Combo cannot trade. Missing, stale,
discontinuous, or incoherent facts remain `UNKNOWN`. Public component-book failure, one evaluable
side, or smaller-amount depth cannot create a partial acquisition, live short risk, leg remediation,
or a Position.

The estimate labels its pricing basis. A synthetic four-leg component-book estimate is distinct
from an observed Combo book and neither reserves future liquidity.

## Future real Entry via Deribit Combo

The intended real route is one Deribit option Combo limit order for the complete leg ratios.
`private/create_combo` returns a matching Combo or creates its book, so an existing public Combo is
not a prerequisite. RFQ is only a request for market-maker interest, not execution. Exact order,
trade, and reconciled account facts are required before a `truth_layer=PRIVATE_EXECUTION` Position
exists. Order acknowledgement alone is insufficient.

Combo execution supports whole-order time-in-force and reduce-only exit controls. Exact TIF belongs
to a later authorized execution Policy. This contract defines no legged fallback without a separate
authorized route and authenticated account evidence. A partial Combo fill may change filled quantity
but cannot be relabelled as an independently acquired Vertical.

Fee facts are route-specific:

```text
COMPONENT_LEG_STRESS_FEE    sum of declared per-leg stress fees
COMBO_STANDARD_FEE          max(sum(buy-leg fees), sum(sell-leg fees))
ACTUAL_ACCOUNT_FEE          authenticated trade fee
```

Deribit reduces the lower fee direction to zero for a buy-and-sell option Combo, so the Combo
standard fee is not the sum of all four leg fees. Public synthetic pricing must label a different
assumption and cannot claim an account tier. Delivery fees follow instrument category: current BTC
daily options are exempt, while other categories follow the current fee schedule.

Monitoring, exit, settlement, Outcome, and learning populations belong to
`CASE_POSITION_OUTCOME.md`.
