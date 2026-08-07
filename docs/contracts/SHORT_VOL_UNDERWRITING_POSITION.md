# Short Vol Underwriting, Admission, and Position Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_UNDERWRITING_SHADOW_POSITION`

## Purpose

Consume settled current Radar state, decide whether one conservative frozen two-leg public-book
counterfactual merits review or admission under one fixed Underwriting Policy, admit only a paired
refreshed valid Candidate, and manage an admitted Shadow Case under one fixed Position Policy.

Before Shadow admission, every evaluation, action, Candidate, request attempt, and display row is
in-memory current state. None is a durable business record. `SHADOW_ENTRY` hands one admitted unit
to the Shadow Case owner, which creates the first durable record.

## Fixed Policy chain

One runtime loads exactly:

```text
Radar Policy
→ Underwriting Policy bound to that Radar Policy
→ Position Policy bound to that Underwriting Policy
```

Target quantity, shared source-currentness budgets, fee role, fee reserve, and source metadata must
be compatible. The runtime cannot hot-reload, tune, approve, or replace any Policy.

Policy files are content-identified. Markdown contract bytes are not runtime business identities.

## Current Underwriting input

Underwriting consumes one settled scope containing, when applicable:

- active Radar episode and short leg;
- frozen short and protective long identities;
- full target-size public option-book depth for both legs;
- current option lifecycle, amount, and official price-tick rules;
- trusted time, current platform, index, short-leg Delta and mark IV;
- public taker-commission facts and fixed reserves;
- exact code, runtime, and three Policy identities.

Missing or invalid required input is `UNKNOWN`. Known structural/lifecycle unavailability is
`NOT_EVALUATED` or known ineligible as defined by the owning classifier. Neither creates an
economic action.

## Radar diagnostic separation

Surface-lite context, semivariance/jump context, and transparent attention rank are trader
diagnostics. They cannot create `EVALUABLE`, `WATCH`, `ABSTAIN`, `CANDIDATE`, an admission attempt,
or a Shadow Case. Radar's ranked protective-vertical Top 3 is display-only. Composition uses the
formal component-book calculator on every legal target-size protective leg and supplies those
economics to the Underwriting-owned selector.

Official Combo state is a parallel diagnostic. `NO_ACTIVE_COMBO`,
`NO_TARGET_SIZE_CREDIT_QUOTE`, and `PUBLIC_ATOMIC_QUOTE_AVAILABLE` neither create nor veto a
component-book Underwriting action.

## Entry economics

For exact target quantity `q`:

```text
short_entry = walk short bids for q, then stress each level down one official tick
long_entry  = walk long asks for q, then stress each level up one official tick
gross_entry_credit_usdc = short_entry_total - long_entry_total
leg_fee = min(fee_rate × index × q, 0.125 × stressed_leg_price × q)
entry_fee_reserve_usdc = short_fee + long_fee
net_entry_credit_usdc = gross_entry_credit_usdc - entry_fee_reserve_usdc
payoff_cap_usdc = abs(long_strike - short_strike) × q
underwriting_reserved_loss_usdc =
    max(0, payoff_cap_usdc - gross_entry_credit_usdc)
    + entry_fee_reserve_usdc
    + future_cost_reserve_usdc
```

Each leg's consumed amounts must sum exactly to `q`. No rounding, mark, mid, theoretical price,
imagined maker price, or official-Combo assumption may enter admission economics. These prices are
conservative public-book counterfactuals, not simultaneous fills.

## Protective-leg selection and margin truth

Underwriting does not freeze a leg until the option catalog and positive option scope are complete.
It excludes known inactive or target-quantity-ineligible legs, but any amount/tick/book/source fact
that is unknown for a still-potentially-legal leg keeps the whole selection `UNKNOWN` with the exact
instrument/reason. At the first settled boundary where every potential leg is classifiable,
Underwriting classifies every legal target-size quote under the same Policy and selects
lexicographically by:

1. action class `CANDIDATE > WATCH > ABSTAIN`;
2. signed margin for positive credit, credit above future-cost reserve, reserved-loss headroom,
   minimum credit, minimum credit/payoff ratio, and consumed-level headroom, in that order;
3. narrower width;
4. protective instrument name.

The chosen long is frozen for the Episode and is not switched by later market movement. Workbench
projects the same owner-generated six-member signed margin vector and every failed predicate. It
also reports exact `count/min/p50/max` over the bounded current Underwriting rows; it does not retain
Episode history. Workbench does not recalculate thresholds or replace them with one generic reason.
Radar Top-3 order, mark IV, or official Combo state cannot affect this selection.

## Underwriting action

When all required facts are evaluable, the fixed first-match Policy returns:

```text
CANDIDATE
WATCH
ABSTAIN
```

`ABSTAIN` covers known non-positive economics or excessive reserved loss. `WATCH` covers an
evaluable opportunity below the Candidate credit/ratio/depth thresholds. `CANDIDATE` satisfies all
current thresholds.

A WATCH or ABSTAIN remains current trader state. It does not automatically open a rejected
counterfactual, no-trade control, aligned pair, Cohort unit, or durable file. A future no-trade
control requires explicit pre-outcome selection authority.

## Candidate lifecycle and admission

A Candidate is current in-memory state identified by the exact opportunity, Policies, target
quantity, and activation boundary. It is invalidated by identity/scope change, episode loss,
structure or quantity change, source degradation, admission cutoff, slot consumption, changed
business facts that no longer qualify, or a consumed failed admission.

Admission schedules exactly two bounded public `get_order_book` refreshes: one for the frozen short
and one for the frozen protective long. Entry is emitted only after both matched responses:

- belong to the same runtime, Candidate, frozen pair, and quantity;
- are causally later than Candidate activation;
- each satisfies send/response budgets;
- each contains full target quantity on its required side;
- form one paired witness owned by the same Candidate origin;
- share one session epoch and one global continuity epoch;
- have source timestamps no more than `6000 ms` apart and local receive boundaries no more than
  `4000 ms` apart;
- remain an evaluable Candidate under the same Policies after adverse tick stress and both fees.

One response alone cannot emit Entry. Failure or retirement of either request retires its sibling
and consumes the attempt without Entry. Pair session, continuity, or skew mismatch settles
`UNKNOWN_CONSUMED` with its exact bounded reason, measured values, and Policy limits and cannot open
a Case. A public response is not a fill or liquidity reservation. The same pair contract applies to
post-CLOSE component refreshes; its transport attempt may terminalize `ERROR`, while the owned
close opportunity and Workbench business state remain explicitly `UNKNOWN`.

## Shadow admission handoff

A successful admission creates one in-memory `SHADOW_ENTRY` and immediately asks the Shadow Case
store to publish exactly one `SHADOW_CASE_OPENED`. The opened record freezes only the minimal facts
required to reconstruct the admitted counterfactual:

- code, runtime, and three Policy identities;
- entry and decision boundaries;
- frozen canonical legs, directions, expiry, strikes, and full quantity;
- paired source identity and both raw/stressed consumed leg levels;
- entry economics and fixed reserve components;
- the consumed Radar/Underwriting state required to explain the admission;
- explicit public-quote/not-fill non-claims.

If durable Case opening fails, admission fails visibly; the runtime must not silently manage an
unrecorded Shadow Case.

## Position state

After opening, Position consumes only strictly later settled public facts. It evaluates the exact
ordered close predicates for:

1. settlement/expiry;
2. latest exit;
3. platform/source discontinuity;
4. maximum projected net loss;
5. short-leg risk boundary;
6. path/jump boundary;
7. volatility-state boundary;
8. liquidity/exit boundary;
9. economic exit/take-profit boundary.

The action is:

```text
CLOSE   if any close reason has latched, and remains CLOSE thereafter
UNKNOWN if none has latched and a required predicate is unknown
HOLD    otherwise
```

Individual Position evaluations and HOLD/UNKNOWN changes are in-memory only. The first latched
CLOSE creates at most one durable `SHADOW_CASE_FIRST_CLOSE` transition.

## Close quote and opportunity

Close-quote state remains separate from Position action:

```text
COMPONENT_BOOK_CLOSE_QUOTE
LEGGED_CLOSE_REFERENCE
UNEXECUTABLE
UNKNOWN
```

Only a strictly later paired component-book snapshot for the same frozen legs can create an
eligible Shadow close opportunity. The short is bought from asks stressed up one tick and the long
is sold from bids stressed down one tick. Each leg must cover the full remaining quantity. One
response cannot close the Case.

For an eligible atomic close:

```text
gross_close_cashflow_usdc = long_stressed_sale_total - short_stressed_buy_total
close_fee_reserve_usdc = short_fee + long_fee
net_close_cashflow_usdc = gross_close_cashflow_usdc - close_fee_reserve_usdc
projected_shadow_net_pnl_usdc = net_entry_credit_usdc + net_close_cashflow_usdc
projected_net_loss_usdc = max(0, -projected_shadow_net_pnl_usdc)
```

## Currentness and failure behavior

Clock, platform, index, ticker, metadata, streaming book, and public refresh currentness use their
own Policy budgets and source semantics. Quiet continuous books do not expire by last mutation.
Missing or contaminated facts become `UNKNOWN` at their smallest consumer. A known hard CLOSE is
not erased by an unavailable quote.

A reconnect retains the same in-process Shadow owner but requires fresh current market state.
Current Candidate state does not survive process restart. The current slice does not resume an
open durable Case in a new runtime.

## In-memory owner view

The owner may retain typed current state needed by Workbench and active Shadow Cases. It must not
use a filesystem writer as an event bus, registry, or Workbench datastore. Funnel counts are
non-durable and derived from current owner transitions.

When an Episode or frozen component structure is replaced, the prior scope is settled once as no
longer current, its Candidate is invalidated, and its current-state indexes are removed. Candidate
terminalization removes both admission-request owners; Outcome terminalization removes the active
Position owner.
Only one latest terminal Case may remain in the Workbench projection; all historical terminal truth
comes from the bounded Shadow Case files.

## Required verification

Direct tests cover Policy compatibility, both-leg target depth, adverse tick direction, both fees,
signed economics, action boundaries, all-legal-leg selection outside Radar Top 3, complete predicate
margins, frozen-leg identity, pair session/continuity/skew boundaries, paired admission races, strictly
post-entry Position order, first CLOSE latching, paired close classification, and no pre-Shadow
durable writes. Full graph manifests, second schemas, and automatic rejected-counterfactual
persistence are not required.
