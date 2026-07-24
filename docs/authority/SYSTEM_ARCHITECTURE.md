# Optimatrix System Architecture

**Status:** ACTIVE STRUCTURAL AUTHORITY

## Architectural position

Optimatrix is a modular monolith with one continuous live data path. The architecture separates
pure domain responsibilities without turning them into separate business runs, services, queues,
or databases.

```text
Deribit public WebSocket
→ validate and update bounded current market state
→ Short Vol richness detector
→ authorized structure builder and executable-quote check
→ minimal SHORT_VOL_RADAR_HIT snapshot
→ later Underwriting Decision
→ later Shadow admission and Position Policy
→ later strictly future Outcome
```

The first four arrows are one event-driven Market Monitor and Short Vol Radar flow. There is no
capture job followed by a scan job, and no scanner that repeatedly rereads an unchanged local
dataset.

## Data lifecycles

### Transient live state

Normal Deribit catalog, book, ticker, trade, index, and platform events update a bounded in-memory
state. A declared detector may retain only the causal rolling history it consumes. Static facts,
unselected structures, and no-hit updates are not durable product records.

Minimal continuity, uptime, and gap metadata may be retained separately from market facts to
support an honest coverage statement. It cannot be used to reconstruct prices or claim a
complete market observation.

### Durable business evidence

The first durable strategy object is `SHORT_VOL_RADAR_HIT`. It freezes only the facts consumed by
that hit, the detector identity and result, the complete triggered-short-leg set, every qualifying
atomic structure within the declared usable combo-book scope at the first hit state, visible
target-size execution economics, coverage, and the causal boundary. Later authorized stages add
separate Decision, Shadow Entry, executed-entry, Position-action, close-opportunity, and Outcome
objects.

No-hit market updates produce no receipt. An anomaly without an atomic combo structure may be
counted in bounded runtime metrics, but it does not persist the full option chain or create a
Shadow Outcome.

### Optional evidence capture

A task may explicitly require a bounded sealed stream to test reconstruction or a historical
contract. That evidence adapter is off the product hot path. Its duration, file format, replay
command, and archive are not Online Runtime semantics and cannot become prerequisites for Radar.

## Live event semantics

Every accepted source event receives a monotonic internal causal sequence. Source timestamps are
market facts; receipt time and monotonic sequence establish what the runtime knew and in what
order. A hit binds the latest sequence it consumed.

A relevant source change may update the current chain and evaluate the frozen detector. A time
boundary is relevant only when it changes a declared discrete fact such as instrument membership,
freshness class, or expiry/settlement eligibility. Continuous clock movement, a heartbeat, a
duplicate, an unrelated update, or an arbitrary polling interval does not create another
Radar episode.

Implementation may recompute the small authorized universe or only affected structures. Both are
valid if they produce the same strict as-of business result. The architecture does not require a
generic dependency engine.

Detector clear, hysteresis, and re-arm rules define Radar episodes. Evaluations inside one armed
episode update the current observation but do not multiply the Radar-episode count.

## Continuity and availability

Streaming order books begin from an accepted snapshot and then require continuous changes. A
sequence gap, reconnect, missing snapshot, stale quote, crossed/invalid book, missing instrument
leg, or unavailable global input creates `UNKNOWN` only for its declared consumers.

The runtime must replace or resynchronize affected state before using it again. Old quotes may not
be carried through an unproved gap. Covered unaffected structures remain usable when their
declared dependencies remain complete.

An initial start or unresolved gap may require causal warm-up for the Radar Policy. During that
period the affected detector is `UNKNOWN`. Persisting a previous market stream is not required to
avoid that result; any future warm-state restoration needs its own explicit contract and proof.

## Module ownership

### `market_monitor`

Owns public source adapters, canonical event validation, monotonic known-at order, continuity and
freshness state, bounded in-memory rolling facts, and the optional historical evidence adapter.

The name reflects the product behavior: it maintains current state. Normal live operation does
not seal every market event.

### `options_domain`

Owns BTC-USDC option instrument facts, actual time-to-expiry membership, option-side and strike
relationships, target-size visible quote economics, fee inputs, net credit, and bounded
maximum-loss calculations. It does not decide whether volatility is rich.

### `short_vol_radar`

Owns the immutable `SHORT_VOL_RICHNESS_RADAR_POLICY`, causal feature calculation, detector state
machine, episode identity and re-arm behavior, authorized vertical construction, execution-grade
classification, and minimal `SHORT_VOL_RADAR_HIT` projection.

It returns `NO_HIT | UNKNOWN | ANOMALY_OBSERVED | RADAR_HIT`. It does not output Candidate,
admit Shadow Entry, manage a position, or produce Outcome.

### Later position and Outcome boundary

Separately authorized future code will own Underwriting, Shadow admission, immutable
post-admission Position actions, strictly future close-opportunity facts, and
actual-versus-counterfactual Outcome semantics. No current package implements this boundary, and
it is not a consumer during `SHORT_VOL_RADAR_ESTABLISHMENT`.

### `radar_runtime`

Composes the Deribit public adapter, bounded current state, detector, domain construction, health
metrics, and permitted artifact sink in one continuously running process. It owns process
lifecycle and stop/reconnect behavior, not economic Policy.

## Dependency direction

```text
market_monitor → options_domain → short_vol_radar
       \________________________________/
                    radar_runtime
```

Lower layers never import higher layers. Runtime composition may depend on all internal packages.
Any later Underwriting or position module must be introduced by its own authorized closure. No
module receives private/account access under `PUBLIC_SHADOW`.

## Short Vol Radar boundary

The Radar's exact detector is a content-identified immutable artifact. Its first hypothesis is a
pointwise target-size executable-IV total-variance comparison against a causal physical
total-variance forecast for the same now-to-expiry interval. It must declare units, exact causal
feature inputs, numerical trigger, optional confirmations, episode scope and short-leg mapping,
warm-up, freshness, persistence, clear, hysteresis, and re-arm. It is not a model-free VRP claim.

Structure search occurs only after or together with a detector anomaly in the same current state.
The initial authorized structures are same-expiry 1:1 call or put vertical credit spreads with a
protective long wing. The detector produces an exact triggered-short-leg set for each
expiry/option-type episode; a qualifying vertical must use one of those short legs. Each exact leg
pair is assessed once at a declared target quantity.

`RADAR_HIT` executable economics require a target-size bid from an active official combo book,
classified `ATOMIC_COMBO_QUOTE`.

Target-size sell-at-bid and buy-at-ask component quotes may be classified
`LEGGED_QUOTE_REFERENCE`, but they have leg risk, are not simultaneous, and cannot create a Radar
hit. Neither class is a fill. Depth, fees, net credit, and maximum-loss inputs must remain
inspectable.

## Hit snapshot and independent recomputation

A `SHORT_VOL_RADAR_HIT` contains only:

- market, product, actual expiry, detector and episode identities;
- causal as-of sequence and consumed-fact freshness/continuity status;
- causal feature-state digest, detector feature outputs, score, trigger boundary, confirmations,
  and triggered short-leg set;
- the bid levels and price-to-IV inputs for every triggered short leg;
- every qualifying atomic structure within the declared usable combo-book scope at the first hit
  state in canonical order, with its legs, quantity, and consumed combo price/depth levels;
- each structure's fee inputs, net credit, strike-width/multiplier inputs, and bounded maximum
  loss;
- combo-catalog and matching-combo-book coverage, including unavailable related scope;
- code and contract identities required to recompute the claim.

An independent pure calculation reproduces the final trigger comparison and structure economics
from the frozen outputs. Direct tests verify the causal rolling reducer. This is not a requirement
to archive and replay the full market.

## Later Decision and position architecture

After separate authorization, Underwriting consumes a Radar hit and compares its executable
premium with declared path, jump, tail, friction, liquidity, and uncertainty reserves.

Candidate is permitted only when a complete Position Policy is already frozen. `SHADOW_ENTRY`
freezes a refreshed target-size atomic combo entry quote and creates no exposure. A legged Shadow
admission requires its own later Policy. Future actual exposure begins at the first opening fill,
including a partial or single-leg fill.

The Position Policy consumes current position-specific facts and returns
`HOLD | CLOSE | UNKNOWN`. It has explicit latest-exit and settlement boundaries but no
preselected holding duration.

`close_quote_state` is separately
`ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`. A known hard-close
condition remains `CLOSE` when its quote is unavailable. Public Shadow records
`SHADOW_CLOSE_OPPORTUNITY` only when action is `CLOSE` and a strictly later atomic combo quote
covers the full remaining quantity. A legged reference is diagnostic until an explicit legging
exit Policy is authorized. Future execution must reconcile orders and fills; exposure ends only
when the final closing fill makes every leg flat or authorized settlement completes. Shadow and
actual durations are different fields and may never be collapsed.

## Denominator model

Each layer has its own unit:

```text
monitor: covered / degraded / unknown time
radar: distinct detector episodes and RADAR_HIT episodes
structure: unique canonical leg pairs per episode; as-of state is an observation
underwriting: evaluable hits and Candidate / Watch / Abstain actions
admission: Candidates and Shadow Entries / future executed Entries
position: Shadow Entries or opening fills and their separate mature / unknown Outcomes
```

Market messages, detector calculations, quote updates, legs, reconstruction checks, and elapsed
runtime are neither Radar-episode nor Candidate-opportunity denominators.

## Structural non-goals

- a durable full-market event store on the Online Runtime hot path;
- periodic batch scanning or one process per structure;
- a generic scheduler, dependency graph, stream platform, feature store, or model registry;
- persisting every evaluation or theoretical structure;
- services split before a business closure requires them;
- private execution components under public Shadow authority.
