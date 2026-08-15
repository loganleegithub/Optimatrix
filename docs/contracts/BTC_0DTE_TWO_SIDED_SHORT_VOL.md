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

For production forward observation, the source identity is the unauthenticated public aggregated
WebSocket path: BTC index notifications plus `100ms` option book and ticker channels. The first
book notification is a full snapshot; later changes are accepted only when that instrument's
`prev_change_id` equals its last accepted `change_id`. Instrument chains are ordered independently,
so no notification timestamp is treated as a cross-instrument atomic market. One cut instead binds
the minimum and maximum source boundaries, minimum and maximum receive boundaries, the connection
continuity epoch, and the causal known-at boundary when the final required member was received. An
initialized book remains the current depth state while its connection epoch and verified change
chain remain intact; absence of a content-changing book notification is not itself staleness. Each
instrument therefore contributes the later source and receive boundary of its retained book/ticker
pair, while the BTC index contributes its own boundary. The cut still applies freshness and span
bounds across those effective members. At a scheduled Window boundary the forward source waits,
within the unchanged input grace, until the cut's source watermark is at or after that Window start;
it never consumes a retained pre-Window state as that Window's one attempted observation.

A disconnect, missing initial snapshot, sequence mismatch, stale effective index/instrument member,
incomplete ticker/book pair, or source/receive span outside Policy invalidates the cut and yields
`UNKNOWN` or a lifecycle Gap. REST may supply Session instrument metadata, the initial rolling
index-history seed, at most one validated index-history recovery seed per new connection epoch,
official settlement, and one bounded affected-book resynchronization. A reconnect history seed
cannot make a cut ready until a strictly later BTC index notification and every required book and
ticker belong to that same epoch. A REST book-resync seed likewise requires a matching later
WebSocket change or a new full WebSocket snapshot. Authenticated `raw` channels, private facts, and
inferred cross-connection continuity are absent at B3.

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

Before environment scoring or structure selection, the Window must know:

- the bounded instrument universe, every usable component book, and typed metadata and reason for
  every requested component book that was not usable;
- source, receive, freshness, continuity, and cross-input coherence boundaries;
- the exact HTTP-bounded-snapshot, deterministic, or public-WebSocket market-source identity;
- implied-variance and physical-path method identities with aligned horizon and coverage;
- event-state value, source, and known-at boundary; and
- exact missing, contradictory, or out-of-bound reasons.

Incomplete DataHealth produces `Decision.UNKNOWN`. It does not become calm market, risk trigger,
Candidate, or no-trade evidence. Known market facts may then produce `ABSTAIN`, `REVIEW`, or
`CANDIDATE`.

Component-book availability is Candidate-local after global causal DataHealth passes. Selection
evaluates every Candidate supported by usable books under the unchanged Policy and ranker. A known
unavailable book that cannot participate in any Policy-legal Candidate does not invalidate an
unrelated Candidate. A Candidate that needs an unavailable book is not evaluable; when its known
geometry and unresolved quote facts could still produce a Policy-eligible structure that outranks
the observed Primary, the Primary rank is unresolved and the Window remains `UNKNOWN`. The system
may not convert unresolved rank into `ABSTAIN`, silently promote an observed alternative, or weaken
source, receive, freshness, continuity, cross-input, or required-metadata DataHealth.

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

Public Shadow capacity uses one conservative USD reserve per Candidate:

```text
exit_cost_stress_usd = exit_cost_stress_native × Decision boundary index
maximum_delivery_stress_usd = max(delivery-valued loss across declared scenarios)
stress_reserve_usd = max(
  maximum contractual payoff USD,
  exit_cost_stress_usd,
  maximum_delivery_stress_usd
)
```

The Session budget metric is
`MAX_OF_CONTRACTUAL_PAYOFF_EXIT_AND_DELIVERY_STRESS_USD_SUM`: admission sums exactly
`stress_reserve_usd` across unresolved same-Session Cases. It may not aggregate nominal payoff while
merely displaying a larger stress. Restart reconstruction reads the frozen reserve and its content
identity; a missing, obsolete, malformed, or incoherent reserve fails closed instead of becoming
zero. The reserve is released only when Entry terminalizes without a Position or the Position owns
a terminal Outcome.

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
- selected conservative stress reserve, same-Session stress budget used and remaining, plus
  concurrent-Position limit; and
- allocation expiry and release condition.

This is a research notional limit, not equity, margin, available funds, or a capital reservation. If
any required value is unknown, the Decision cannot become a Candidate. The allocation result is
`AVAILABLE`, `UNAVAILABLE(reason)`, or `UNKNOWN(reason)`: only `AVAILABLE` permits `CANDIDATE`.

A future real Position requires a separate `AccountRiskReservation` derived from authenticated
equity, margin, existing positions, available capacity, account-specific fees, and reservation
state. It belongs to private stages and cannot be inferred from Shadow allocation or public depth.

## C1 authenticated account observation

C1 adds one isolated, explicitly invoked `AuthenticatedAccountObservation`; it does not add real
Entry. The observation binds the exact Deribit `MAINNET` environment, an opaque account-scope
identity, authentication response boundary, independently
validated BTC account-summary and BTC-position components, each component's causal response
boundary, and exact blockers.

The only C1 exchange methods are:

```text
public/auth                       client_credentials with account:read trade:read
private/get_account_summary      currency=BTC, extended=false
private/get_positions            currency=BTC
```

Host selection is closed to the fixed Deribit mainnet endpoint. Arbitrary URL or host
input, every method outside this list, and every parameter expansion fail before transport. The
requested scope is always exactly `account:read trade:read`, because the summary requires the former
capability and Positions require the latter. The machine credential is explicitly supplied under a
user-declared read-only mainnet contract. The auth-response scope text is not normalized and never
decides whether these two fixed reads are called; it is not output, serialized, persisted, or
projected. `TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE` prevents an invented exact-effective-scope claim.
Missing or malformed access token, bearer type, expiry, mainnet environment, response envelope, or
timing remains closed before the two private reads.
Authentication, environment, currency, response-envelope timing, known-at, required numeric
values, instrument identity, and duplicate Position names are validated before a component becomes
known.

The two private components are independent. A known empty BTC-position array means empty only at
that response boundary. A failed or malformed component remains `UNKNOWN`; the other known
component may remain visible, but partial truth cannot infer flat risk, margin capacity, capital
availability, or a reservation. Credentials and bearer tokens are transport-only process memory:
they are absent from CLI arguments, identities, exceptions, serialization, Workbench, Ledger,
Journal, and every durable observation field.

Credential injection is explicit and local. The CLI either reads both selected-environment values
from an interactive no-echo terminal or from one caller-supplied credential-file path. It never
searches for or implicitly loads `.env`, process environment, browser state, Keychain state, or a
user directory. A credential file must be a same-owner, non-symlink regular file with exact mode
`0600`; only the selected `DERIBIT_MAINNET_*` pair is retained by the C1 command. Duplicate or
unknown keys, missing environment pairs, quotes, shell syntax, wider permissions, file replacement,
and non-regular input fail with value-free codes.

This observation is `truth_layer=PRIVATE_EXECUTION` and separates
`CREDENTIAL_SCOPE=USER_DECLARED_READ_ONLY|UNKNOWN`,
`TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE`,
`APPLICATION_METHOD_PERMISSION=READ_ONLY_FIXED_ALLOWLIST`, and `ORDERS_EXECUTED=NONE`. The last label
means this application executed no order during the capture; it does not claim that the account has
no external activity.
The observation cannot become a `ShadowRiskAllocation`, `AccountRiskReservation`, TradeCase,
Position, route, Entry, order, trade, fill, PnL, or execution attribution. C2 requires a separate
task, contract closure, and permission boundary.

## Decision result and TradeCase boundary

The BTC contract owns each enrolled-Window `DecisionRecord`: it freezes DecisionWindow, Base Policy,
known-at boundary, the complete immutable causal MarketObservation input, DataHealth, result,
blockers, risk-allocation result, typed route evidence, and selected structure or exact
non-selection reason. A Candidate's route evidence must be `EVALUABLE` and bind its exact selected
four legs, ratios, full target amount, causal observation, and synthetic economics. The retained
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
causal market cut. Entry does not call the structure selector: a different or better structure in
the later universe cannot replace the Candidate's exact frozen legs. Before a Position may exist,
the later cut reruns the same frozen Policy dimensions used by the Decision:

- current Session phase and environment proxies, including the phase-specific VRP threshold;
- exact frozen-leg product, expiry, strike geometry, amount, short-leg Delta, whole-product net
  Delta, and body distance;
- full-amount whole-product component-book pricing and the same credit, payoff-cap, reference-loss,
  and Combo-fee underwriting limits; and
- the frozen Shadow allocation's `AVAILABLE` result, identity, Policy, Candidate, Channel, amount,
  Session, known-at boundary, structure expiry, and coverage of the Entry deadline.

Decision and Entry each freeze a separate content-addressed route-evidence record. Route truth kinds
are disjoint:

```text
COMPONENT_SYNTHETIC_ESTIMATE   stressed estimate from four public component books
COMBO_BOOK_QUOTE              quote observed on one actual Combo instrument
RFQ                           request-for-quote fact; never a quote or execution
ACTUAL_FILL                   authenticated trade plus account reconciliation
```

B3 Public Shadow constructors and codecs accept only `COMPONENT_SYNTHETIC_ESTIMATE`. A component
record binds the Policy, frozen Candidate, causal observation boundaries, exact `+1/-1/-1/+1` leg
ratios, full target amount, per-leg depth coverage, component-estimate model, projected standard
Combo fee rule, and synthetic net economics. The fee projection is a cost-model fact; it does not
turn component books into a Combo quote. The strict record shape has no Combo instrument, RFQ,
order, trade, fill, account, executable-liquidity, or fill-probability field, and recovery rejects
such additions or any non-component kind under B3.

Route status is independent of the later business rejection dimension:

```text
EVALUABLE       one causal cut prices every exact ratio at the full target amount
NOT_EVALUABLE   complete causal component facts cannot form that declared estimate
UNKNOWN         a required causal or DataHealth fact is absent or invalid
```

`UNKNOWN` carries no invented depth or economics. `NOT_EVALUABLE` carries observed component depth
but no invented whole-product price. Neither can create a Position. A route rejection does not
claim that a future actual Combo is impossible; it describes only the named evidence kind.

The typed reunderwriting result freezes the Decision and Entry route identities and Session phases;
Decision-to-Entry VRP, short-leg Delta, net Delta, body-distance, credit/payoff, reference-loss,
and fee-burden metrics; each dimension's blockers; the exact observation boundaries; and the Entry
result. Its result is one of:

```text
SHADOW_ATOMIC_EVALUABLE          every reunderwriting dimension and route pass
SHADOW_ATOMIC_NOT_EVALUABLE      complete facts show the declared estimate cannot be formed
ENTRY_EVIDENCE_UNKNOWN           required facts are missing or causally invalid
ENTRY_THESIS_EXPIRED             current phase or environment rejects new Entry
ENTRY_STRUCTURE_LIMIT_BREACHED   the frozen four legs breach a current structure limit
ENTRY_PRICE_DETERIORATED         current whole-product economics fail underwriting
RISK_RESERVATION_INVALID         the frozen Shadow allocation no longer validates
```

`SHADOW_ATOMIC_EVALUABLE` means its Entry route evidence is `EVALUABLE` and the frozen four legs at
the same ratios and full target amount still satisfy every Policy dimension above. It is not a
Combo-executability or fill claim. It may open a
`truth_layer=SHADOW_PROJECTION` Position for research.

`SHADOW_ATOMIC_NOT_EVALUABLE` means complete facts prove that the declared Shadow model cannot
price the whole target product; it does not prove a real Combo cannot trade. Missing, stale,
discontinuous, incoherent, or causally invalid facts remain provisional `ENTRY_EVIDENCE_UNKNOWN`
until the Entry deadline and become terminal `ENTRY_EVIDENCE_UNKNOWN` at that deadline. A known
Policy or allocation rejection is terminal immediately and is not relabelled as missing evidence.
Public component-book failure, one evaluable side, or smaller-amount depth cannot create a partial
acquisition, live short risk, leg remediation, or a Position.

The content-addressed route record, rather than a free-standing pricing-basis label, owns this
distinction. A synthetic four-leg component-book estimate is distinct from an observed Combo book
and neither reserves future liquidity.

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
