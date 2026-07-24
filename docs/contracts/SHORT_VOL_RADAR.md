# Short Vol Radar Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Current implementation state:** NOT IMPLEMENTED

**Current authorized closure:** `SHORT_VOL_RADAR_ESTABLISHMENT`

## Business statement

The first Radar continuously watches the current Deribit BTC-USDC option chain and asks:

> Is volatility unusually expensive under one frozen causal detector, and does the same market
> state contain an authorized, target-size, defined-risk net-credit structure with visible
> executable quotes?

It is not a scheduled batch, a long capture, a replay, an inventory of every theoretical spread,
or a Candidate Policy. Its first durable business result is a minimal `SHORT_VOL_RADAR_HIT`.

## Terms that must not be collapsed

| Term | Exact meaning | Not equivalent to |
|---|---|---|
| Market event | one accepted Deribit public update | scan, Radar episode, receipt |
| Market Monitor | ingestion plus current in-memory chain maintenance | durable full-market capture |
| Detector evaluation | apply the frozen Short Vol Policy to changed relevant state | new Radar episode by itself |
| Anomaly episode | one armed-to-clear detector event | every quote update |
| Quote-executable structure | authorized legs with a target-size atomic combo quote | component-leg reference, fill |
| `RADAR_HIT` | anomaly and atomic quote-executable structure coexist | Candidate, Shadow Entry, Outcome |
| Candidate | later Underwriting action | Radar hit |
| `CLOSE` | later Position Policy action | close quote or fill |
| Shadow close opportunity | `CLOSE` plus a later full-quantity `ATOMIC_COMBO_CLOSE_QUOTE` | legged reference, actual close |
| Actual exposure duration | first opening fill to every leg flat or authorized settlement | Shadow duration |

## Market Monitor contract

### Universe

`DERIBIT_BTC_USDC_0_3DTE_MARKET_MONITOR` includes an instrument exactly when:

- the instrument is an active Deribit linear BTC-USDC option;
- accepted market time and expiry are known;
- `0 < expiry_timestamp - market_time <= 72 hours`.

The calculation uses actual timestamps, not `Daily`, `Weekly`, `Monthly`, or `Quarterly` naming.
Catalog state changes add and remove instruments without restarting the process. If market time,
catalog state, or expiry cannot be trusted, affected membership is `UNKNOWN`.

`market_time` is a trusted Deribit server-time observation advanced only by local monotonic elapsed
time within the maximum clock-sync age frozen by the Monitor contract. Server-time uncertainty,
maximum sync age, and refresh behavior are explicit. Wall-clock time, an old market message, or
the newest timestamp from an unrelated channel cannot silently define universe membership. When
trusted market time expires, membership is `UNKNOWN` until resynchronized.

### Current facts

The monitor maintains only facts consumed by the detector and structure check:

- instrument catalog and state;
- index/underlying reference required by the frozen Policy;
- target instruments' order books, best prices, displayed depths, and quote-implied volatility;
- trades or rolling underlying facts explicitly consumed by the causal volatility forecast;
- active combo catalog and combo books when available;
- source/platform health, timestamps, sequence continuity, and freshness classes;
- official instrument metadata and applicable fee inputs.

The implementation may subscribe more broadly for source efficiency, but unused facts grant no
business meaning and are not persisted.

### Streaming continuity

An accepted initial full `book` snapshot establishes an order book. Each subsequent incremental
book update must have `prev_change_id` equal to the preceding accepted `change_id`. A mismatch,
missing snapshot, reconnect without proved coverage, stale quote, invalid book, or unknown depth
makes affected consumers `UNKNOWN` until resynchronized. Ticker or quote channels may trigger a
lightweight calculation but cannot by themselves prove target-size book depth.

A complete continuous book whose required side is empty, or whose visible cumulative depth is
below target quantity, is known `UNEXECUTABLE`, not `UNKNOWN`. A complete combo catalog with no
matching active combo is also known absence. This distinction keeps an observed quiet market from
becoming a data-availability failure.

Already proved unaffected state need not be discarded. Old state may not be carried across an
unproved gap. Backfill may support later evaluations but never rewrites an earlier no-hit or
unknown result.

### Trigger semantics

Ingestion, state update, and detector notification are one operation. Evaluation is triggered only
when an accepted event changes a detector or structure input, or when a declared discrete
freshness, universe-membership, expiry, or settlement boundary changes.

The following do not create a new Radar episode:

- a duplicate or replayed source event;
- heartbeat or collector bookkeeping;
- an unrelated instrument update;
- an unchanged reduced market state;
- an arbitrary timer;
- repeated calculation over saved facts.

Implementation may evaluate all current authorized instruments or an affected subset. It must not
build a second persistent scanner or a generic dependency platform to do so.

### Memory and persistence

The Online Runtime keeps bounded current state and only the causal rolling history declared by the
Policy. Normal raw option-chain updates, `NO_HIT` evaluations, and theoretical structures are not
written to durable product storage.

Minimal coverage/gap metadata may be retained to distinguish observed time from unavailable time.
It contains no reconstructable price chain. A task-required bounded evidence stream uses a
separate evidence sink and is never read by the live Radar.

## Short Vol richness detector

### Immutable Policy artifact

Before the first production acceptance observation,
`SHORT_VOL_RICHNESS_RADAR_POLICY` must freeze and content-identify:

1. exact instruments, moneyness/delta scope, target quantity, and units;
2. price-to-implied-volatility method and invalid-price behavior;
3. causal future-realized-volatility forecast and all rolling inputs;
4. trigger score, numerical trigger boundary, and comparison convention;
5. optional skew, term, or local-surface confirmations;
6. observation persistence, clear boundary, hysteresis, episode key, and re-arm;
7. warm-up, quote freshness, continuity, missingness, and recovery;
8. atomic combo qualification and non-qualifying component-leg diagnostic rules.

These values belong to the implementation task and immutable artifact. No operator or Agent may
tune them after seeing the live acceptance interval without declaring a new Radar Policy change
and restarting acceptance.

### Primary signal and scope

The first detector family is `POINTWISE_EXECUTABLE_IV_RICHNESS`.

For each eligible potential short leg:

```text
remaining_life_years = exact_now_to_expiry_under_the_frozen_day_count
sell_point_total_implied_variance =
    square(implied_volatility_from_target_size_executable_sell_price)
    × remaining_life_years
forecast_total_realized_variance =
    causal_forecast_of_integrated_realized_variance_from_now_to_that_expiry
point_richness_score =
    sell_point_total_implied_variance - forecast_total_realized_variance
```

The Policy freezes annualization, day count, integration units, price-to-IV inversion, rounding,
and boundary comparison. “Same remaining life” means only that both variance quantities cover the
same now-to-expiry interval; it is not a holding duration or exit clock.

The sell price is the cumulative visible price at which that exact prospective short option can
be sold at the declared quantity. Mark and mid cannot trigger the detector. If the causal forecast
is unavailable, or the required book is missing, stale, or discontinuous, that point is
`UNKNOWN`. A complete continuous book without enough target-size bid depth is known
`UNEXECUTABLE`; it cannot enter `triggered_short_leg_set` and does not turn monitor coverage into
`UNKNOWN`.

This is a pointwise executable-IV richness indicator. It is not the model-free variance risk
premium, which requires a same-expiry strip across strikes to estimate risk-neutral total
variation. A single OTM option price also contains skew, jump, and tail pricing. The Radar makes
no VRP or edge claim from this score.

Trailing realized volatility may be a forecast feature. Unless the Policy specifies a causal
mapping to future integrated physical variance, the comparison is incomplete and cannot trigger.

The Policy may require one or more frozen confirmations:

- `SKEW_RICHNESS`: a same-expiry wing is rich relative to the declared ATM/opposite-wing and
  causal conditional baseline;
- `TERM_RICHNESS`: near-expiry total variance is rich relative to the declared adjacent-expiry
  relationship and causal conditional baseline;
- `LOCAL_SURFACE_RICHNESS`: an executable quote is rich relative to a bid/ask-consistent,
  no-static-arbitrage local surface.

Order-book movement, trades, volume, open interest, index movement, or liquidation activity may
trigger recomputation. None alone is a Short Vol signal.

For the first Policy, `episode_scope_key` is:

```text
Radar Policy identity + expiry + option type
```

At each scope, the Policy outputs a canonically sorted `triggered_short_leg_set`. Every member must
pass the point trigger and its required confirmations. A vertical qualifies for that episode only
when its short leg is a member of this set; an anomaly at another expiry, option type, or strike
cannot be attached to it.

Several triggered strikes in the same expiry/option-type scope remain one detector episode.
Call-side and put-side scopes are distinct. Confirmations such as term or surface state must map
back to the exact eligible short-leg set under a rule frozen before live evidence.

### Detector state machine

```text
UNKNOWN
  required facts unavailable

ARMED
  required facts usable and no active episode

ACTIVE_EPISODE
  trigger and every required confirmation passed

CLEARING
  clear condition is being confirmed

ARMED
  clear completed and re-arm conditions passed
```

The Policy defines exact transition comparisons and persistence. One transition from `ARMED` to
`ACTIVE_EPISODE` creates one anomaly episode for its scope. Quote changes and membership changes
inside the same active scope update the episode but do not create another Radar episode. A new
episode requires the complete frozen clear and re-arm sequence.

## Radar result states

At a strict as-of market state:

- `UNKNOWN`: a required detector, universe, quote, depth, fee, or continuity fact is unavailable;
- `NO_HIT`: all required detector facts are usable and no active trigger exists;
- `ANOMALY_OBSERVED`: an active anomaly episode exists but no authorized target-size atomic combo
  quote is available; component-leg references may be reported only as diagnostics;
- `RADAR_HIT`: an active anomaly episode and at least one authorized target-size atomic combo
  quote coexist.

When some structures are unavailable and another complete atomic structure qualifies, the hit may
remain valid only if the frozen Policy permits partial-universe hits and the snapshot declares
coverage. It may not claim complete-universe selection.

The Radar never returns `CANDIDATE`, `WATCH`, or `ABSTAIN`.

## Authorized structure contract

The initial Radar may construct only same-expiry, same-option-type, 1:1 BTC-USDC linear vertical
credit spreads.

The short leg must be a member of the current episode's `triggered_short_leg_set`. The long wing
and atomic combo must share that short leg and strict as-of state. A rich point may not be used to
justify a structure whose short premium comes from another point.

### Call credit spread

- short one OTM call under the frozen forward-relative and delta predicate;
- long one higher-strike call with the same expiry;
- the long call fully caps expiry loss of the short call.

### Put credit spread

- short one OTM put under the frozen forward-relative and delta predicate;
- long one lower-strike put with the same expiry;
- the long put fully caps expiry loss of the short put.

Both legs must be active and use the same settlement product. Naked shorts, ratios, calendars,
cross-expiry structures, and structures outside the declared target quantity are forbidden.
At the strict as-of state, the frozen Greek method must classify the combined target quantity as
net short vega and net short gamma. Those model values establish strategy orientation only; they
cannot establish price or executability.

The Policy artifact freezes the short-leg delta/moneyness range, long-wing selection rule, target
quantity, minimum displayed depth, and any strike-width bound before production evidence. No
public paper supplies universal values for these parameters.

## Visible executable economics

### Execution evidence

`ATOMIC_COMBO_QUOTE` requires:

- an active official Deribit combo with the exact legs and direction;
- a visible target-size quote in the credit-sale direction;
- sufficient displayed combo depth;
- one strict as-of combo-book state.

`LEGGED_QUOTE_REFERENCE` requires:

- a visible target-size bid for the short leg;
- a visible target-size ask for the long leg;
- sufficient displayed depth on both legs;
- one strict as-of component-book state.

The component reference is conservative for the observed books but is not simultaneous and
carries leg risk. It may explain why an anomaly was interesting, but it cannot create
`RADAR_HIT`, enter the qualifying structure set, or satisfy Radar establishment. An implementation
without account authority cannot create a combo, request a quote, place an order, or prove a fill.

Public Shadow can observe only active public combo books; it cannot create the exact combo needed
for an anomaly. Active combo capacity and lifetime are exchange-limited. Therefore an
`ANOMALY_OBSERVED` result with only legged references may be a combo-availability limitation, not
evidence that the detector was wrong. It may not trigger detector tuning.

Executable value is the cumulative visible value obtained by walking the observed book only as
far as the declared target quantity. A top price multiplied by quantity is invalid when its
displayed depth is insufficient. The frozen Policy declares how a multi-level effective price is
converted to implied volatility and how price ticks and rounding are handled.

### Economics

For the declared target quantity and official contract metadata:

```text
atomic_gross_credit = executable_combo_credit
atomic_net_credit = atomic_gross_credit - applicable_atomic_entry_fees
legged_reference_credit =
    executable_short_sale_proceeds
    - executable_long_purchase_cost
    - applicable_legged_entry_fees
```

Only positive `atomic_net_credit` can qualify a Radar structure; an atomic quote is not repriced
from component books. `legged_reference_credit` is diagnostic and never substitutes for atomic
economics. All terms must share an explicit settlement unit and multiplier. The snapshot records
official fee inputs rather than silently hard-coding a historical fee.

Maximum expiry loss is reconstructed from the strike-difference payoff under official linear
contract size/multiplier and settlement rules, less received `atomic_net_credit`, at the declared
quantity. A structure whose maximum loss cannot be independently bounded is not authorized.

Atomic combo quote freshness, depth, net credit, and maximum-loss inputs must all be known. Exit
liquidity and close cost belong to later Underwriting; Radar does not claim that a visible entry
guarantees a future exit.

## `SHORT_VOL_RADAR_HIT`

One minimal hit snapshot contains:

- contract, code, monitor, and Radar Policy identities;
- anomaly episode id, detector state, feature values, score, trigger/clear configuration, and
  confirmations;
- the causal feature-state digest and frozen feature/forecast outputs; normal rolling input events
  remain transient;
- accepted market time, causal sequence, continuity, freshness, and declared coverage;
- for every member of `triggered_short_leg_set`, the exact cumulative target-size bid
  price/quantity levels and source timestamp plus the consumed forward/underlying reference,
  rate/discount or basis input, time to expiry, strike, and price-to-IV method identity;
- every qualifying atomic structure within the declared usable combo-book scope at the first hit
  state, canonically sorted by product, expiry, option type, short strike, long strike, direction,
  and target quantity;
- each structure's strict as-of combo bid price/quantity levels consumed through target quantity
  and source timestamp;
- fee inputs, gross and net credit, official contract units, and maximum-loss inputs/result;
- detector-scope, combo-catalog, and matching-combo-book coverage, including unavailable related
  scope and explicit non-claims;
- a content digest over the snapshot.

It does not contain the full option chain, every theoretical structure, Candidate action, Shadow
Entry, fill, or Outcome.

Radar does not choose a “best” structure. If several qualify within the declared usable
combo-book scope at the first hit state, all enter the canonically sorted set; source order,
hash-map order, or implementation traversal cannot choose one. Later quote observations may
update the active episode in memory but do not create another Radar episode. Any later
Underwriting selection needs its own authorized Policy.

A structure identity is product, expiry, option type, canonical short/long legs, direction, and
target quantity. Market as-of sequence belongs to the structure observation, not that identity.
Quote flicker therefore cannot manufacture new unique structures.

## Independent recomputation

A fresh pure-domain calculation using only the hit snapshot must reproduce:

- each triggered short leg's target-size effective sell price from its saved bid levels;
- `sell price → implied volatility → implied total variance → richness score → trigger`, using the
  saved price-to-IV inputs and frozen physical-variance forecast output;
- every required confirmation comparison from its frozen feature outputs;
- every authorized leg relationship and target quantity in the qualifying set;
- atomic combo direction, cumulative target-size value, and depth;
- each structure's atomic gross credit, fees, net credit, and maximum-loss inputs/result.

Direct deterministic tests, not the hit snapshot, verify the rolling state reducer and forecast
engine from causal input sequences. Snapshot recomputation verifies the final hit decision from
the feature state actually bound online without reintroducing full-feed persistence.

This verifies every recorded member, not that the online enumerator omitted no other active combo.
Complete-enumeration behavior is proved by direct tests with multiple qualifying and rejected
combos plus declared live combo-catalog coverage and freshness, continuity, and depth coverage for
each matching combo book; it does not require persisting the rejected combo universe. Partial
coverage proves only the recorded usable scope, never complete-universe selection. The snapshot
also does not prove a fill, Underwriting selection, or strategy edge. If it cannot recompute its
comparison and structure economics, it is invalid.

## Business denominators

Every report declares one observation interval. Report:

```text
monitor coverage in monotonic elapsed milliseconds:
  covered_time_ms
  degraded_time_ms
  unknown_time_ms

radar state and episode units:
  distinct_relevant_scope_state_count
  distinct_anomaly_episode_count
  distinct_radar_hit_episode_count

structure unit:
  qualifying_atomic_structure_count
```

At each instant the complete declared Monitor universe is exactly one coverage state: `COVERED`
when every required source scope is usable, `DEGRADED` when a proper subset is usable, and
`UNKNOWN` when no reliable coverage claim can be made. These mutually exclusive durations
partition the declared interval.

`distinct_relevant_scope_state_count` counts unique accepted
`(episode_scope_key, reduced_state_digest)` transitions, not source messages.
`distinct_anomaly_episode_count` counts `ARMED → ACTIVE_EPISODE` transitions.
`distinct_radar_hit_episode_count` counts each anomaly episode once when it first obtains at least
one qualifying atomic structure. `qualifying_atomic_structure_count` counts unique
`(anomaly_episode_id, canonical_structure_identity)` members observed within the declared usable
combo-book scope in those first-hit snapshots; later quote changes do not add structures to that
count. When coverage is partial, this is an observed usable-scope count, not a complete-market
total.

Legged references are diagnostics, not a business denominator. Rates condition on their named
denominator. Zero or unknown denominators produce null/undefined, not zero. Market messages,
evaluations, detector features, quote updates, legs, process hours, files, and recomputation
checks are neither Radar-episode nor Candidate-opportunity counts.

## Post-hit boundary

This closure stops at `SHORT_VOL_RADAR_HIT`.

A later Underwriting contract must compare executable premium with path, bidirectional jump,
short-gamma, tail, liquidity, entry/exit friction, and uncertainty before outputting
`CANDIDATE | WATCH | ABSTAIN`. It must freeze one Position Policy before Candidate is possible.
Any later `SHADOW_ENTRY` must refresh the target-size atomic combo quote; it cannot reuse a stale
Radar quote. A legged Shadow admission needs a separately authorized legging Policy.

After `SHADOW_ENTRY`, or after any future opening fill creates actual quantity, that Position
Policy evaluates remaining premium, short-leg state, actual path, volatility surface, time to
expiry, executable close debit, depth, spread, fees, platform state, and hard
latest-exit/settlement boundaries to return `HOLD | CLOSE | UNKNOWN`.

`CLOSE` means a known close condition or hard boundary requires an exit attempt.
`close_quote_state` is separately
`ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`; a missing quote
cannot erase a known hard-close obligation. Position `UNKNOWN` means the Policy cannot safely
decide between hold and close from the facts it requires. It never overrides a known hard-close
condition.

Neither entry kind has a planned holding duration. Public Shadow may record
`SHADOW_CLOSE_OPPORTUNITY` only when action is `CLOSE` and a strictly later
`ATOMIC_COMBO_CLOSE_QUOTE` covers the full remaining Shadow quantity. A
`LEGGED_CLOSE_REFERENCE` is diagnostic and does not end the Shadow position unless a later
contract authorizes an exact legging exit Policy. Future actual exposure starts with the first
opening fill and ends with the last closing fill that makes every leg flat, or authorized exchange
settlement. Shadow and actual durations remain separate identities.

## Establishment acceptance

`SHORT_VOL_RADAR_ESTABLISHMENT` is accepted only when:

1. direct tests prove the detector calculation, exact trigger boundary, warm-up, missingness,
   episode scope, triggered-short-leg mapping, persistence, clear/re-arm, and no-hit/unknown
   distinction;
2. direct tests prove market-time membership, continuity recovery, complete-empty-book versus
   unknown behavior, quote freshness, authorized verticals, atomic combo direction, depth, fee,
   net-credit, maximum-loss, and non-qualifying legged-reference behavior;
3. direct tests prove unchanged, duplicate, irrelevant, heartbeat, and timer-only events do not
   create hit episodes or durable no-hit artifacts;
4. one continuous production-public process naturally emits at least one `RADAR_HIT`;
5. that hit contains at least one target-size atomic combo quote for an authorized structure,
   saves every qualifying structure within its declared usable combo-book scope in canonical
   order, declares unavailable matching scope, and makes neither complete-universe nor fill
   claims;
6. independent minimal-snapshot recomputation passes;
7. inspection confirms normal non-hit full-chain data and theoretical structures were not
   persisted.

A covered zero-hit interval is truthful but does not establish hit reachability. An unavailable
interval is `UNKNOWN`. No fixed runtime duration is an acceptance rule; the process continues
until a hit occurs or a human stops it.

Candidate, Shadow admission, executed entry, future-path Outcome, profitability, replay archive,
and account execution are not acceptance requirements.

## Public-source basis and inference limits

### Exchange facts

- Deribit documents public real-time subscriptions, snapshots and subsequent updates:
  [Notifications](https://docs.deribit.com/articles/notifications) and
  [Market data collection practices](https://docs.deribit.com/articles/market-data-collection-best-practices).
- Exchange time used for clock-skew control is public:
  [Get time](https://docs.deribit.com/api-reference/supporting/public-get_time).
- Live instrument membership comes from the public instrument catalog and state notifications:
  [Get instruments](https://docs.deribit.com/api-reference/market-data/public-get_instruments) and
  [Instrument state](https://docs.deribit.com/subscriptions/market-data/instrumentstatekindcurrency).
- Public books expose bid/ask, quantities, implied volatility, and Greeks:
  [Get order book](https://docs.deribit.com/api-reference/market-data/public-get_order_book).
- Official combo books provide simultaneous multi-leg execution and explicitly distinguish leg
  risk, while active combo capacity is limited:
  [Combo Books](https://support.deribit.com/hc/en-us/articles/31424954956061-Combo-Books) and
  [Option Combo Order](https://support.deribit.com/hc/en-us/articles/25944794271261-Option-Combo-Order).
  Active USDC combos are publicly enumerable:
  [Get combos](https://docs.deribit.com/api-reference/combo-books/public-get_combos).
  Creating a combo is a private trade-scoped action:
  [Create combo](https://docs.deribit.com/api-reference/combo-books/private-create_combo).
- Product units, expiry/settlement, and current fees come from the exchange:
  [Linear USDC Options](https://support.deribit.com/hc/en-us/articles/31424932728093-Linear-USDC-Options),
  [Contract Introduction Policy](https://support.deribit.com/hc/en-us/articles/25944688876957-Contract-Introduction-Policy),
  and [Fees](https://support.deribit.com/hc/en-us/articles/25944746248989-Fees).

These sources define market and execution facts. They do not require Optimatrix to persist the
full stream and do not prove strategy edge. The in-memory/no-hit persistence design is an
Optimatrix product decision inferred from the availability of streaming state, not a Deribit
rule.

### Research basis

- Variance-risk-premium research defines the economic distinction between option-implied and
  physical expected variance:
  [Federal Reserve variance risk premium](https://www.federalreserve.gov/pubs/ifdp/2011/1035/ifdp1035.htm).
- Bitcoin-option research supports time-varying variance premium and volatility regimes, not an
  unconditional Short Vol edge:
  [The Bitcoin VIX and its Variance Risk Premium](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734)
  and
  [Bitcoin volatility regimes](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/).
- Short-expiry research emphasizes state dependence, friction, jumps, and tail risk:
  [Trading Strategies With 0DTE Options](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4641356)
  and
  [Bitcoin implied-volatility slopes and jumps](https://doi.org/10.1016/j.orl.2024.107135).
- Cboe's 0DTE material supports the practical importance of limited-risk spreads and rapid risk
  change, but it is equity-index evidence and cannot calibrate BTC:
  [Cboe 0DTE](https://www.cboe.com/tradable-products/0dte).

The Federal Reserve source constructs model-free implied variance from an option strip; it does
not authorize calling one OTM bid-implied variance “VRP.” The first Optimatrix detector is a
pre-registered, falsifiable product hypothesis, not a research-consensus trading rule. The cited
work motivates testing relative implied/realized variance and preserving skew, jump, tail,
liquidity, and friction boundaries. It does not validate an edge in 0–3DTE BTC pointwise
executable-IV richness and supplies no universal trigger, delta band, wing width, target quantity,
or exit threshold.

The cited historical Bitcoin studies largely predate the BTC/ETH USDC-settled option launch:
[Deribit USDC-settled BTC/ETH options launch](https://insights.deribit.com/education/usdc-settled-btc-eth-options-launch/).
They motivate mechanisms only and cannot establish liquidity, quote behavior, variance-premium
distribution, or transferable parameters for `BTC_USDC_LINEAR_OPTIONS`.

### Practitioner and social context

Practitioner material commonly combines variance premium, term structure, skew, liquidity, and
regime rather than using one raw IV number:
[Kaiko implied-volatility case study](https://www.kaiko.com/reports/implied-volatility-case-study)
and
[Amberdata public VRP/skew/term discussion](https://www.linkedin.com/posts/amberdata_amberdatas-btc-bitcoin-options-report-activity-7023696270498140161-UjN6).

Public trader discussions about managing short premium by remaining premium and thesis
invalidation are useful context only:
[Options practitioner discussion](https://www.reddit.com/r/options/comments/1uwkfpr/your_close_out_percentage/).
Social posts and anecdotes cannot define authority, numerical thresholds, profitability, or
qualification.
