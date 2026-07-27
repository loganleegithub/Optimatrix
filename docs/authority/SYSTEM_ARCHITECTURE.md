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
→ minimal SHORT_VOL_ANOMALY_EVENT on activation
→ while active, independent official atomic-combo availability
→ optional minimal PUBLIC_ATOMIC_QUOTE_EVENT
→ later Underwriting Decision
→ later Shadow admission and Position Policy
→ later strictly future Outcome
```

The market-state, detector, and public atomic-availability arrows are one event-driven Market
Monitor and Short Vol Radar flow. There is no
capture job followed by a scan job, and no scanner that repeatedly rereads an unchanged local
dataset.

## Data lifecycles

### Transient live state

Normal Deribit catalog, book, ticker, trade, index, and platform events update a bounded in-memory
state. A declared detector may retain only the causal rolling history it consumes. Static facts,
unselected structures, and no-anomaly updates are not durable product records.

Minimal continuity, uptime, and gap metadata may be retained separately from market facts to
support an honest coverage statement. It cannot be used to reconstruct prices or claim a
complete market observation.

### Durable business evidence

The first durable strategy object is `SHORT_VOL_ANOMALY_EVENT`. It freezes only the detector facts
consumed at one activation, its exact Policy/code identity, coverage, and causal boundary. While
that episode is active, a first observed official target-size atomic quote for one combo creates a
separate `PUBLIC_ATOMIC_QUOTE_EVENT` containing only the official combo facts it consumed. Later
authorized stages add separate Decision, Shadow Entry, executed-entry, Position-action,
close-opportunity, and Outcome objects.

No-anomaly market updates produce no receipt. Neither event persists the full option chain or
creates a Shadow Outcome. One bounded run summary records coverage and counts, not reconstructable
market history.

### Optional evidence capture

A task may explicitly require a bounded sealed stream to test reconstruction or a historical
contract. That evidence adapter is off the product hot path. Its duration, file format, replay
command, and archive are not Online Runtime semantics and cannot become prerequisites for Radar.

## Live event semantics

The transport has one application-sequence allocator per session epoch. It stamps every decoded
socket frame, immutable send-completion/failure control, and connection-failure control with
`session_epoch`, one unique consecutive `ingress_seq`, and `received_monotonic_ms`, then places all
of them into one bounded queue. Here `ingress_seq` is the persisted application sequence, not a
wire-only sequence or a queue position. The allocator advances only after an event is accepted by
the queue. The reducer accepts exactly `last + 1` for every event kind and advances its frontier
exactly once; a duplicate or gap fails the epoch closed.

The socket reader and sender never apply market truth, resolve an economic response future, or
filter a frame by client-side subscription generation. One synchronous reducer is the sole owner
of session, channel, platform, catalog, market, detector, episode, coverage, RPC lifecycle, and
Layer 2 state. It consumes each accepted application event exactly once and never waits for
network I/O anywhere in its call tree. Only a real decoded socket frame advances session-wire
liveness; local send and connection controls cannot keep market truth current.

Reducer output is a finite list of purpose-specific `PendingRpc` commands. Sending is an
orchestration concern. Only successful completion of the transport send creates an immutable
`SENT` control boundary; the sender reports expected success, failure, or cancellation through
the application queue and does not own session termination. RPC ownership is explicit:

```text
SCHEDULED -> SENT | ERROR | DEADLINE_LATE | RETIRED | CENSORED
SENT      -> SUCCESS | ERROR | DEADLINE_LATE | RETIRED | CENSORED
```

`SCHEDULED` has a send deadline. `SENT` starts a separate response deadline and response latency
at its actual send-completion boundary. Terminal transitions are idempotent and cannot be
rewritten; unmatched or already-terminal responses remain separately counted as
`ORPHAN_LATE_WIRE`.

A failure/reconnect barrier first retires the epoch, stops producers, and then drains every event
already accepted by the transport or buffered by orchestration as retired/orphan facts before
propagating the failure. A clean-stop barrier rejects further outbound work, stops producers,
settles in-flight cancellation controls, drains every accepted event, and only then censors
remaining `SCHEDULED` and `SENT` RPCs and writes the summary. No queued RPC begins a transport
send after that barrier opens.

Every source boundary enters one non-reentrant reducer transaction: classify the candidate,
settle all source currentness, freeze the received cause plus concurrent effects and their complete
scope union once, commit current state, construct immutable full-scope snapshots, settle
detector/aggregate/atomic current truth, update observation/episode state, then persist only
resulting edges. Every committed source fact receives a monotonic internal causal sequence and one
`FactBoundary`. Source timestamps are market facts; receive time and ingress sequence establish
what the runtime knew and in what order. Deribit channels have no single exchange-global sequence,
so strict as-of means the latest individually continuous facts known to the process at one causal
boundary, not a matching-engine-wide simultaneous snapshot. Each emitted event binds the latest
boundary it consumed.

An option `ticker.<instrument_name>.100ms` notification is a complete snapshot, not a sequenced
change stream. Its `timestamp` is an as-of/currentness fact and is not a continuity token.
`ingress_seq` establishes application order. A shape-valid snapshot older than the currently
accepted ticker is `LATE_IGNORED`: it cannot overwrite the newer fact, request resubscription,
or restart any continuity epoch. The ignored candidate itself cannot change detector/episode
truth, but its receive boundary still settles independent accepted-source currentness; a TTL
crossing at that boundary therefore becomes an explicit concurrent `TICKER_SOURCE_STALE` effect.
Equal-timestamp snapshots remain ordered by `ingress_seq`. Shape validity, accepted-ticker
currentness, and application disposition are separate facts and diagnostics.

A relevant source change may update the current chain and evaluate the frozen detector. A time
boundary is relevant only when it changes a declared discrete fact such as instrument membership,
freshness class, or expiry/settlement eligibility. Continuous clock movement, a heartbeat, a
duplicate, an unrelated update, or an arbitrary polling interval does not create another
Radar episode.

Implementation may reuse immutable member results, but every affected aggregate scope is frozen
and settled as one complete snapshot before any aggregate, witness, or Layer 2 result is consumed.
The architecture does not require a generic dependency engine.

Detector clear, hysteresis, and re-arm rules define Radar episodes. Evaluations inside one armed
episode update the current observation but do not multiply the Radar-episode count.

## Continuity and availability

Streaming order books begin from an acknowledged subscription and accepted snapshot, then require
continuous `prev_change_id -> change_id` changes. A quiet unchanged book remains current while
the connection, subscription, instrument, platform, and sequence continuity remain healthy. Its
last-mutation age is diagnostic, not a reason to resubscribe or mark the quote stale.

Connection health is established, not assumed: the runtime acknowledges an official WebSocket
heartbeat, answers test requests, and uses monotonic deadlines loaded from the exact external
Policy artifact. Heartbeat traffic cannot refresh any economic quote or create a detector
observation. Platform health is a pure predicate over independent reducer-owned facts: lock
snapshot, latched maintenance guard, latched public-method guard, post-status probe, fresh-index
coverage, and bootstrap epoch. A negative guard cannot be overwritten by a positive notification
inside the same epoch. A half-open connection or unresolved initial platform state cannot preserve
old books as current.

A sequence gap, reconnect, missing snapshot, crossed/invalid book, missing instrument leg, or
unavailable global input creates `UNKNOWN` only for its declared consumers.

The runtime must replace or resynchronize affected state before using it again. Old quotes may not
be carried through an unproved gap. Covered unaffected structures remain usable when their
declared dependencies remain complete.

Operational truth is kept in three independent ledgers:

1. `global_continuity_epoch` restarts only for a retired session, non-contiguous/overflowed
   ingress, a trusted-clock gap, or a real index continuity loss. Option-local unavailability and
   current coverage changes never restart it. One root incident can restart at most once before
   its explicit recovery edge.
2. `current_market_truth_coverage` continues to partition every runtime millisecond into
   `NO_APPLICABLE_SCOPE | KNOWN_COMPLETE | KNOWN_DEGRADED | UNKNOWN`. Its segments identify why
   the state began, the affected global/aggregate/option scope, and the active continuity epoch.
3. `option_local_availability` records the smallest affected option, its unavailable reason, and
   bounded recovery timing. It can end or pause that option's current detector truth exactly as
   the owning contract specifies, but it cannot erase unrelated current truth or global
   continuity.

One joint operational witness is derived from one settled full current
`Policy identity × expiry_timestamp × option_type` scope snapshot. Its current-epoch durable row
freezes `Policy identity × expiry_timestamp × option_type × TTE band × formula instrument ×
boundary`. The same snapshot supplies both complete aggregate coverage and
`has_current_full_formula`; a historical formula result, a different instrument, or only the
boundary's affected subset cannot be combined with a separately computed complete scope.
`EvidenceWriter` persists only detector/atomic episode edges and the clean-stop summary and never
participates in current-truth decisions.

An initial start or unresolved gap may require causal warm-up for the Radar Policy. During that
period the affected detector is `UNKNOWN`. Persisting a previous market stream is not required to
avoid that result; any future warm-state restoration needs its own explicit contract and proof.

## Module ownership

### `market_monitor`

Owns public source adapters, canonical event validation, monotonic known-at order, continuity and
connection state, and bounded in-memory rolling facts.

The name reflects the product behavior: it maintains current state. Normal live operation does
not seal every market event.

### `options_domain`

Owns BTC-USDC option instrument facts, actual time-to-expiry membership, option-side and strike
relationships, target-size visible quote arithmetic, and official 1:1 vertical leg
relationships. It does not decide whether volatility is rich or whether a public quote is worth
trading.

### `short_vol_radar`

Owns the exact content-identified `POINTWISE_EXECUTABLE_IV_RICHNESS_BASELINE` Policy, causal
feature calculation, detector state machine, episode identity and re-arm behavior, official
vertical matching, separate public atomic-availability classification, and minimal event
projection.

It returns per-instrument `detector_state = UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE`, its
completeness-aware aggregate, and per-short-leg-episode
`public_atomic_quote_state = NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO |
NO_TARGET_SIZE_CREDIT_QUOTE | PUBLIC_ATOMIC_QUOTE_AVAILABLE`. It does not output Candidate,
admit Shadow Entry, represent a maker order or fill, manage a position, or produce Outcome.

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

The Radar's exact detector is a content-identified immutable artifact for one process lifetime.
The declared detector scope and numeric parameters live in the Policy rather than implementation
constants. A human-approved successor inside that Policy schema may change its scope/parameter
fields and uses a new identity, process, and forward interval; the runtime cannot hot-reload,
tune, train, approve, or deploy it.

Its first hypothesis is a
pointwise target-size executable-IV comparison against the annualized volatility implied by a
causal trailing-index-variance baseline scaled to the same now-to-expiry interval. Both total
variances remain inspectable, and IV percentages are not conflated with variance percentages.
This is not a delivery-TWAP distribution forecast or a validated physical forecast. It must
declare units, exact causal
feature inputs, numerical trigger, optional confirmations, episode scope and short-leg mapping,
warm-up, continuity, persistence, clear, hysteresis, and re-arm. It is not a model-free VRP claim
or a validated forecast.

Official combo matching occurs only while a short-leg detector episode is active.
The initial authorized structures are same-expiry 1:1 call or put vertical credit spreads with a
protective long wing. Each option instrument owns its pointwise episode. One complete active leg
is a positive anomaly witness even under degraded unrelated coverage; an aggregate no-anomaly
claim requires a complete non-empty
`Policy identity × expiry_timestamp × option_type` scope. OTM, Delta, and target-liquidity
ineligibility are known per-instrument results, not denominator exclusions. A qualifying vertical
must use that episode's short leg, and its atomic event references the episode directly. Each
exact leg pair is assessed at the Policy's declared target BTC quantity.

Episode identity is namespaced by runtime and Policy. Known ineligibility, detector-scope exit,
membership loss, a missing or invalid detector fact, a numerically unresolved derived detector
classification, source gap, and stop have distinct end reasons and immediately stop Layer 2;
recovery requires fresh activation. When trusted-time uncertainty straddles only an adjacent
enabled TTE-band boundary, the episode may instead pause with Layer 2 not evaluated and resume the
same identity after the boundary resolves, provided every market source stayed continuous.
Suspended time is not known-active time.

`PUBLIC_ATOMIC_QUOTE_AVAILABLE` requires target-size depth on the bid or ask implied by the
desired signed legs and positive normalized gross entry credit from an active official combo
book. `NO_ACTIVE_COMBO`, `NO_TARGET_SIZE_CREDIT_QUOTE`, and combo `UNKNOWN` do not change
`ANOMALY_ACTIVE`; with no active anomaly the state is `NOT_EVALUATED`.

Component-leg prices are not an input or diagnostic object in this closure: they are not
simultaneous, carry leg risk, and cannot substitute for an official atomic combo. A public atomic
quote is not a maker order or fill. Fee tiers, delivery fees, maximum loss, margin, Greeks-based
structure quality, and future closeability belong to later Underwriting or Execution.

## Minimal events and direct verification

`SHORT_VOL_ANOMALY_EVENT` contains only identity/causal facts, detector boundaries, a compact
causal baseline summary, and the one short leg with the bid levels and inputs consumed by the
live formula. `PUBLIC_ATOMIC_QUOTE_EVENT` references that short-leg episode and contains only the
official combo identity, signed legs, required combo order direction, target quantity, consumed
bid or ask levels, and normalized gross credit. One run summary contains coverage, state counts,
and `UNKNOWN` reasons.

Repository-owned schemas validate these objects directly. Formula, boundary, state-sequence,
continuity, and projection tests exercise the same small pure functions used by the live path.
The first Radar closure intentionally creates no replay path, second calculator, provenance graph,
or persisted recomputation contract.

## Later Decision and position architecture

After separate authorization, Underwriting consumes an active anomaly plus a refreshed official
atomic quote and compares its executable premium with declared path, jump, tail, friction,
liquidity, and uncertainty reserves.

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
radar: usable evaluations by current TTE band; distinct short-leg episodes attributed once to activation band
atomic availability: active-anomaly evaluations by official combo state
underwriting: evaluable future opportunities and Candidate / Watch / Abstain actions
admission: Candidates and Shadow Entries / future executed Entries
position: Shadow Entries or opening fills and their separate mature / unknown Outcomes
```

Market messages, detector calculations, quote updates, legs, schema checks, and elapsed runtime
are neither Radar-episode nor Candidate-opportunity denominators.

## Structural non-goals

- a durable full-market event store on the Online Runtime hot path;
- periodic batch scanning or one process per structure;
- a generic scheduler, dependency graph, stream platform, feature store, or model registry;
- persisting every evaluation or theoretical structure;
- replay, an offline second calculator, or provenance machinery for the first Radar closure;
- maker, order, fill, fee, margin, or maximum-loss machinery inside public availability;
- services split before a business closure requires them;
- private execution components under public Shadow authority.
