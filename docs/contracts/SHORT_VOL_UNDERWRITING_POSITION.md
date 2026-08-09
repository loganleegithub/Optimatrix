# Short Vol Underwriting, Admission, and Position Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_UNDERWRITING_SHADOW_POSITION`

## Purpose

Consume settled current Radar state, decide whether one conservative frozen two-leg public-book
counterfactual merits review or admission under one fixed Underwriting Policy, admit only a paired
refreshed valid Candidate, select at most one future-blind decision observation per causal
activation batch, and manage either enrolled Case variant under one fixed Position Policy.

Before Shadow enrollment, every evaluation, action, Candidate, request attempt, and display row is
in-memory current state. None is a durable business record. `SHADOW_ENTRY` hands one admitted unit
to the Shadow Case owner and creates a process-independent Entry aggregate after its paired entry
witness. A runtime owns only the aggregate's current Observation Segment. The separately typed
decision-control open creates one selected no-trade Case, not a recoverable Entry.

## Fixed Policy chain

One runtime selects exactly one immutable product profile and loads exactly one matching chain:

```text
Product specification
→ Radar Policy bound to that product
→ Underwriting Policy bound to that Radar Policy
→ Position Policy bound to that Underwriting Policy
```

Target quantity, shared source-currentness budgets, fee role, fee reserve, and source metadata must
be compatible in the product's declared units. Product, Policy, or leg mismatch fails before
Candidate or Case. The runtime cannot observe both products, hot-reload, tune, approve, or replace
its product or any Policy.

Policy files are content-identified. Markdown contract bytes are not runtime business identities.

## Current Underwriting input

Underwriting consumes one settled scope containing, when applicable:

- active Radar episode and short leg;
- exact product specification and product-bound three-Policy identities;
- frozen short and protective long identities;
- full target-size public option-book depth for both legs;
- current option lifecycle, amount, and official price-tick rules;
- trusted time, current platform, index, short-leg Delta and mark IV;
- native premium/settlement unit, model rule, causal valuation index and valuation unit;
- public native taker-commission facts, USD-defined payoff convention, and fixed valuation reserves;
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

For exact target quantity `q`, the one component-book calculator first walks and stresses native
book prices:

```text
short_entry_native = walk short bids for q, then stress every level down one native legal tick
long_entry_native  = walk long asks for q, then stress every level up one native legal tick
native_gross_entry_credit = short_entry_native_total - long_entry_native_total
native_entry_fee_reserve = native_short_fee + native_long_fee
native_net_entry_credit = native_gross_entry_credit - native_entry_fee_reserve
```

Each native fee uses the selected product's standard public taker-fee rule and premium cap. Only
after native arithmetic conserves does the calculator value each cashflow at the causal entry index:

```text
boundary_valued_gross_entry_credit = value(native_gross_entry_credit, entry_index)
boundary_valued_entry_fee_reserve = value(native_entry_fee_reserve, entry_index)
boundary_valued_net_entry_credit =
    boundary_valued_gross_entry_credit - boundary_valued_entry_fee_reserve
payoff_cap_usd = abs(long_strike_usd - short_strike_usd) × q
underwriting_reserved_loss_valuation =
    max(0, payoff_cap_usd - boundary_valued_gross_entry_credit)
    + boundary_valued_entry_fee_reserve
    + future_cost_reserve_valuation
```

For `LINEAR_BTC_USDC_V1`, native and valuation amounts are USDC and this is the exact accepted v3
arithmetic. For `INVERSE_BTC_V1`, native premium, fees, settlement cashflow, and PnL are BTC while
the Underwriting comparison unit is explicitly `USD_EQUIVALENT`. Strike width caps contractual USD
payoff; the corresponding BTC settlement liability depends on settlement price. This public
counterfactual does not establish actual account margin, which remains `UNKNOWN`. New Inverse
Policy, product-value, Workbench, and schema v4 fields use explicit native or valuation names; they
must not reinterpret a legacy `*_usdc` suffix as USD equivalent.

Each leg's consumed amounts must sum exactly to `q`. No rounding, mark, mid, theoretical price,
imagined maker price, cross-product conversion, or official-Combo assumption may enter admission
economics. These prices are conservative public-book counterfactuals, not simultaneous fills.

## Protective-leg selection and margin truth

Underwriting does not freeze a leg until the option catalog and positive option scope are complete.
It excludes known inactive or target-quantity-ineligible legs, but any amount/tick/book/source fact
that is unknown for a still-potentially-legal leg keeps the whole selection `UNKNOWN` with the exact
instrument/reason. At the first settled boundary where every potential leg is classifiable,
Underwriting classifies every legal target-size quote under the same Policy and selects
lexicographically by:

1. action class `CANDIDATE > WATCH > ABSTAIN`;
2. signed margin for positive credit, credit above future-cost reserve, reserved-loss headroom,
   minimum credit, minimum credit/payoff ratio, and consumed-level headroom, in that order, with all
   monetary members labeled in the selected product's valuation unit;
3. narrower width;
4. protective instrument name.

The chosen long is frozen for the Episode and is not switched by later market movement. Workbench
projects the selector-rule identity, the number of legal quotes classified as Candidate, the same
owner-generated six-member signed margin vector, and every failed predicate. It also reports exact
`count/min/p50/max` over the bounded current Underwriting rows; it does not retain Episode history.
Workbench does not recalculate thresholds or replace them with one generic reason. Radar Top-3
order, mark IV, or official Combo state cannot affect this selection.

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
counterfactual, no-trade control, aligned pair, Cohort unit, or durable file. Only the following
pre-outcome selected-decision rule may enroll one.

## Selected-decision research enrollment

Every Episode newly activated in the same settled reducer transaction belongs to one batch
identified by runtime, product, Radar Policy, and its shared activation causal sequence. Before any member's
Underwriting action or future facts are consulted, the batch designates the unique Episode with the
minimum canonical hash over batch identity, Episode identity, and the frozen Underwriting/Position
Policy identities. Input order cannot affect the result. If the designated Episode is `UNKNOWN` or
ends, there is no fallback to another member. At most one decision is selected per batch.

The designated Episode's first fully evaluable `CANDIDATE | WATCH | ABSTAIN` freezes the original
complete predicate-margin vector and schedules one future-blind paired refresh. WATCH/ABSTAIN use
exactly two control-owned `public/get_order_book` requests under the same quantity, send/response,
session, continuity, and skew rules as Candidate admission. A Candidate reuses its ordinary
admission pair; scheduling a duplicate control pair is forbidden.

At the refresh boundary, `UNKNOWN`, invalid pair timing, missing full quantity, or a no-longer
evaluable structure opens no Case. A decision selected as Candidate and still Candidate opens the
ordinary admitted `SHADOW_ENTRY` Case. Any refreshed WATCH or ABSTAIN may open one
`SELECTED_UNDERWRITING_DECISION_CONTROL` Case without a Candidate, `SHADOW_ENTRY`, slot consumption,
order, fill, or capital exposure. A selected WATCH/ABSTAIN that refreshes to Candidate instead opens
no Case and terminalizes as `REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION`; the same refresh
cannot retroactively become the strictly later admission pair for a newly activated Candidate.
Both Case variants freeze original and refreshed actions/margins, then
use the same strictly future Position, paired-close, and Outcome calculators. The no-trade variant
is projected in a separate research funnel and never increments the canonical Candidate or
admitted-Case funnel. Because a settled Candidate and its admission terminal leave bounded current
state, either enrollment variant directly carries the consumed refresh terminal outcome, exact
unknown reasons, pair timing, and Policy limits needed by Workbench; the projection never depends
on retired Candidate history.

## Candidate lifecycle and admission

A Candidate is current in-memory state identified by the exact product, opportunity, Policies,
target quantity, and activation boundary. It is invalidated by identity/scope change, episode loss,
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

## Shadow enrollment handoff

A successful admission creates one in-memory `SHADOW_ENTRY` and asks the Shadow Case store to stage
one complete initial Case: exactly one `SHADOW_CASE_OPENED` plus its origin
`SHADOW_CASE_SEGMENT_OPENED`. The store validates both inside one staging Case directory and makes
them visible with one no-replace atomic directory publication. The opened record freezes only the
minimal facts required to reconstruct the admitted counterfactual:

- code, runtime, and three Policy identities;
- exact product identity and Case schema rule;
- entry and decision boundaries;
- frozen canonical legs, directions, expiry, strikes, and full quantity;
- paired source identity and both raw/stressed consumed leg levels;
- native entry levels/fees/economics and explicitly named causal valuation facts for schema v4, or
  the byte-exact accepted Linear v3 projection;
- USD-defined payoff facts and fixed valuation reserve components;
- the consumed Radar/Underwriting state required to explain the admission;
- the frozen protective-leg selector-rule identity and Candidate protective-leg count;
- explicit public-quote/not-fill non-claims.

If complete directory publication fails, admission fails visibly; the runtime must not silently
manage an unrecorded Shadow Case. A crash before publication leaves neither initial record visible,
never only `opened.json`.

For an admitted trade, the atomically published origin `SHADOW_CASE_SEGMENT_OPENED` freezes
`entry_position_baseline`: the causal entry index and short-leg mark IV with their exact source
identities and boundaries. Recovery does not widen the accepted v3/v4 `opened.json` shape or change
its product schema identity. A migrated legacy Entry whose accepted records lack those source
references carries `entry_position_baseline=UNKNOWN`; Position cannot infer the missing values.

A successful selected WATCH/ABSTAIN refresh creates the separately typed no-trade control open and
immediately requests the same durable `SHADOW_CASE_OPENED` record with
`enrollment_kind=SELECTED_UNDERWRITING_DECISION_CONTROL`. Its Candidate and `SHADOW_ENTRY` fields
must be null, and its additional non-claims must state `NOT_A_CANDIDATE_ACTIVATION`,
`NOT_A_SHADOW_ENTRY`, `NOT_AN_ADMITTED_TRADE`, and `NO_CAPITAL_EXPOSURE`.

## Position state

After opening, Position consumes only strictly later settled public facts inside its current
Observation Segment. It evaluates the exact
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
CLOSE and scheduling of its only paired close attempt create one atomic durable
`SHADOW_CASE_FIRST_CLOSE / FIRST_CLOSE_AND_ATTEMPT_SCHEDULED` transition. The request intents are
released only after publication succeeds. No runtime may create a second first CLOSE or attempt.

## Cross-process recovery

After acquiring the stable Case repository, a new runtime restores every non-terminal admitted
Entry bound to its exact product and frozen Policy chain. It reconstructs the frozen structure,
entry economics from `opened.json` and the immutable entry baseline from the origin Segment,
restores any durable first-CLOSE latch, and opens a new runtime Observation Segment. It does not
recreate Underwriting, Candidate, admission, slot consumption, or source Radar state. An
`UNKNOWN` legacy baseline remains `UNKNOWN` until fresh segment facts establish only the current
inputs; they do not rewrite the missing entry baseline.

Segment data availability starts `UNKNOWN`. `HANDOFF_GAP` permanently marks observation quality but
is not a Position predicate and cannot create `HOLD` or `CLOSE`. The first fresh complete facts are
evaluated normally; predicates whose missing cross-gap inputs cannot be established remain
`UNKNOWN` at that evaluation. A fresh known index becomes the new segment's prior-evaluation
baseline only after the truthful first evaluation.

If first CLOSE was already durable, it remains latched. If its one paired attempt was pending when
the process stopped or crashed without a mature Outcome, recovery exposes
`ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS` and does not retry. If first CLOSE occurs later from fresh
facts, the same atomic first-close/schedule rule applies. A mature economic Outcome formed after any
gap stores `observation_quality=GAPPED` and `qualification_eligible=false`; its public economics may
be known, but it is not a continuous-observation qualification result.

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

For an eligible paired component-book close, the same product-aware order applies:

```text
native_gross_close_cashflow = long_stressed_sale_total - short_stressed_buy_total
native_close_fee_reserve = native_short_fee + native_long_fee
native_net_close_cashflow = native_gross_close_cashflow - native_close_fee_reserve
native_net_pnl = native_net_entry_credit + native_net_close_cashflow
boundary_valued_net_pnl =
    value(native_net_entry_credit, entry_index)
    + value(native_net_close_cashflow, close_index)
exit_valued_native_net_pnl = value(native_net_pnl, close_index)
```

The boundary-valued and exit-valued views answer different declared questions and remain distinct;
neither may be selected after observing the Outcome. Linear preserves its exact USDC values. An
Inverse known Outcome conserves BTC-native PnL plus both explicitly USD-labeled valuation views.
Actual account margin, settlement action, and fill PnL remain outside the public contract.

## Currentness and failure behavior

Clock, platform, index, ticker, metadata, streaming book, and public refresh currentness use their
own Policy budgets and source semantics. Quiet continuous books do not expire by last mutation.
Missing or contaminated facts become `UNKNOWN` at their smallest consumer. A known hard CLOSE is
not erased by an unavailable quote.

A reconnect retains the same in-process Shadow owner but requires fresh current market state.
Current Candidate state does not survive process restart. Admitted Entry aggregates do survive:
the externally started next process restores them from the stable repository and creates new
Observation Segments. Selected no-trade Controls do not survive as active owners.

## In-memory owner view

The owner may retain typed current state needed by Workbench, the bounded selected-decision batch,
and all validated active admitted Entries. It must not
use a filesystem writer as an event bus, registry, or Workbench datastore. Funnel counts are
non-durable and derived from current owner transitions.

When an Episode or frozen component structure is replaced, the prior scope is settled once as no
longer current, its Candidate is invalidated, and its current-state indexes are removed. Candidate
terminalization removes both admission-request owners; Outcome terminalization removes the active
Position owner.
Only one latest terminal Case and one latest terminal selected-decision batch may remain in the
ordinary projection; every active admitted Entry is projected once from the owner. All historical
segment and terminal truth comes from the bounded Shadow Case files.

## Required verification

Direct tests cover one-product/one-chain compatibility, mixed-product rejection, both-leg target
depth, native adverse tick direction, product fee rules, native/model/valuation conservation, signed
economics, action boundaries, all-legal-leg selection outside Radar Top 3, product-labeled complete
predicate margins, frozen-leg identity, pair session/continuity/skew boundaries, paired admission
races, strictly post-entry Position order, first CLOSE latching, paired close classification, exact
Linear behavior, no pre-Shadow durable writes, repeated A→B→C process recovery, segment-gap
UNKNOWN, single durable attempt schedule, no retry after uncertain process loss, and mature gapped
Outcome classification. Full graph manifests, parallel schemas, per-tick checkpoints, replay, and
automatic rejected-counterfactual persistence are not required. Public observation is governed
only by `CURRENT_STAGE`.
