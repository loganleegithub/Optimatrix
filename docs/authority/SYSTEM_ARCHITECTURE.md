# Optimatrix System Architecture

**Status:** ACTIVE STRUCTURAL AUTHORITY

## Architectural position

Optimatrix is a modular monolith with one continuous live data path. The architecture separates
pure domain responsibilities without turning them into separate business runs, networked
microservices, queues, or databases. The accepted offline implementation adds one long-running
process host and one in-process loopback read-only workbench; that is process lifecycle and
projection, not a service topology split or deployment authorization.

```text
Deribit public WebSocket
→ validate and update bounded current market state
→ Short Vol richness detector
→ minimal SHORT_VOL_ANOMALY_EVENT on activation
→ while active, independent official atomic-combo availability
→ optional minimal PUBLIC_ATOMIC_QUOTE_EVENT
→ fixed-contract Underwriting Decision
→ deterministic Shadow admission and Position Policy
→ strictly future Outcome and aligned evidence
→ atomic immutable trader snapshot after the settled Radar-plus-Shadow transaction
→ loopback GET/HEAD-only workbench
```

The market-state, detector, and public atomic-availability arrows are one event-driven Market
Monitor and Short Vol Radar flow. There is no
capture job followed by a scan job, and no scanner that repeatedly rereads an unchanged local
dataset. The downstream arrows are implemented in the same process. Their production-public
permission, and any permission to invoke or deploy the persistent host, comes only from
`CURRENT_STAGE` and an exact live task. The operability and version-2 trader-workbench repair is
accepted at exact commit `d4740d6a181efebc8dad6d1091a78fa44d885957`. Its one authorized fresh
restart is consumed after a commission-deadline failure and clean seal. The later R3 commissioning
attempt is also consumed after a projection-verifier failure and independent complete clean-stop
audit. All three persistent-observation roots are immutable. The sole active R4 task owns the
isolated repo-owned commissioning/stop controller and any exact observed minimal owning-module
repair allowed by `CURRENT_STAGE`. R4 attempt 001 closed terminally quiescent after the listener parser
rejected macOS `lsof`'s always-selected `f` field; attempt 002 closed terminally quiescent after a
normal RunningBoard `resource coalition id` row was misclassified as a CPU resource exception;
attempt 003 commissioned and then cleanly stopped after continuous observation found an exact-PID
macOS CPU resource violation caused by redundant inactive-scope projection and unchanged workbench
member encoding. Attempt 004 confirmed the hot-path repair but was cleanly stopped after a manual
`/usr/bin/log show` query self-record was falsely classified as a runtime resource event; the
first repair excluded the exact `com.apple.log` self-record shape. The final user-authorized
simplification removes Unified Log from the executable controller and keeps CPU, RSS, queue-lag,
and exact-PID `cpu_resource` DiagnosticReports as advisory evidence only. Those observations remain
recorded but do not decide commissioning or the 24-hour result; direct process identity,
listener, HTTP/schema/current-reader, probe-continuity, fatal, terminal, and quiescence gates remain
unchanged.
Attempt 005 commissioned and ran for 110 minutes before a valid atomic-quote evidence publication
exposed a local filesystem boundary: its legal 230-byte final name became a 268-byte temporary
basename and exceeded macOS `NAME_MAX`. The bounded owning-module repair keeps the same final
evidence identity and atomic hard-link publication, but uses a short same-directory UUID temporary
name. Local `EvidenceError` also crosses subscription dispatch unchanged instead of being
misclassified as public protocol input. This is evidence persistence and failure attribution, not
a market adapter, business semantics, schema, cadence, process, or deployment-topology change.
Under the 2026-08-02 Authority amendment, each observed implementation defect received one minimal
exact candidate and merged repair before one fresh R4 recommission attempt; failed attempts remain
preserved. Attempt 006 reached `COMMISSIONED` at merged commit
`1b10ecb3336c9b342e5ddb306ecbb9170c211d70` with runtime identity
`sha256:9b5772ce0b3aa0aa0773533fbec1eaf8af90edd9d0971b2e3b9d0aaf0a2be364` and remains under read-only
24-hour observation. Iterative repair/recommissioning authority is consumed. This changes no
service topology, market/Decision semantics, business owner, publication cadence, unattended
service retry loop, contract, or Policy.

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
separate `PUBLIC_ATOMIC_QUOTE_EVENT` containing only the official combo facts it consumed. The
fixed-contract public Shadow implementation can add separate Decision, Shadow Entry,
Position-action, close-opportunity, and Outcome objects only when a later evidence task authorizes
that composition to run. Executed-entry and fill objects remain unimplemented and unauthorized.

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

Operational truth is kept in four independent ledgers:

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
4. `index_baseline_publication` records generation-global successor pending independently from
   coverage. Its `CURRENTNESS_LOST` transition owns the exact invalidating reason and full
   `FactBoundary`; closing and invalidating publication is never conditional on whether an active
   continuity incident is allowed to create another epoch edge.

One joint operational witness is derived from one settled full current
`Policy identity × expiry_timestamp × option_type` scope snapshot. Its current-epoch durable row
freezes `Policy identity × expiry_timestamp × option_type × TTE band × formula instrument ×
boundary`. The same snapshot supplies both complete aggregate coverage and
`has_current_full_formula`; a historical formula result, a different instrument, or only the
boundary's affected subset cannot be combined with a separately computed complete scope.
`EvidenceWriter` persists only detector/atomic episode edges and the clean-stop summary and never
participates in current-truth decisions.

Index baseline availability and publication are separate. For each Policy return count, the
Monitor projects an exact `N + 1` immutable `MinuteClose` window ending at the latest minute jointly
proven by trusted-time lower bound and accepted source watermark. Per-band availability is
`AVAILABLE | WARMUP | WINDOW_GAP | SOURCE_STALE | CONTINUITY_GAP`; a shorter band may remain
available while a longer band is warming or contains an older window gap. Independently, one
tracker per acknowledged index generation and global-continuity epoch records only the immediate
successor publication phase `CURRENT | TIME_BOUNDARY_PENDING | WATERMARK_PENDING` after the first
immutable close exists. Normal pending does not invalidate the published tuple, resubscribe,
pause an episode, stop Layer 2, or alter persistence.

The reducer first seals minutes only after both proof boundaries, then atomically publishes the
latest exact continuous suffix. Expected minute time never impersonates an actual close; no
provisional current-minute close, clock-only seal, simple trailing list slice, intermediate-minute
observation replay, or cross-gap/epoch carry is permitted. `WINDOW_GAP` retains its scoped global
continuity restart without index resubscription. `SOURCE_STALE` and `CONTINUITY_GAP` invalidate all
index consumers and resubscribe. Publication-currentness invalidation is an independent,
exactly-once reducer transition. Incident de-duplication can suppress only a duplicate epoch edge
and restart count: a later session, clock, source-stale, or continuity loss inside an already
active incident still closes the current publication row and removes the reusable tuple.

An initial start or unresolved gap may require causal warm-up for a particular Radar Policy
return count. During that period only the affected detector query is `UNKNOWN`; generation-global
publication may already be observable from a shorter immutable history. Persisting a previous
market stream is not required to avoid that result; any future warm-state restoration needs its
own explicit contract and proof.

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

### `short_vol_underwriting`

[`SHORT_VOL_UNDERWRITING_POSITION`](../contracts/SHORT_VOL_UNDERWRITING_POSITION.md) owns
Underwriting, deterministic Shadow admission, immutable post-admission Position actions, and
strictly future close-opportunity semantics. The accepted contract below separately owns
counterfactual Outcome and cohort semantics.

[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)
owns causal-first public counterfactual exit selection, terminal Shadow Outcome and rejected-
counterfactual maturity/censoring, cohort-aligned `NO_TRADE`, forward-evidence conservation, and
strict downstream evidence compatibility. It introduces no Outcome/Cohort Policy and no new market,
delivery, or settlement-price source.

The pure downstream owner `short_vol_underwriting` consumes immutable public DTOs from the existing
lower layers and owns
Underwriting, admission, Position, counterfactual, Outcome, aligned-pair, and downstream evidence
semantics. Its schemas, writer, current/complete readers, manifest binding, canonical identities,
`UNKNOWN` handling, and conservation checks are strict and deterministic. It is a package, not a
service, client, queue, database, or authority to run live. The Online Runtime remains the sole
composer; no lower layer imports that owner.

### `radar_runtime`

Composes the Deribit public adapter, bounded current state, detector, domain construction,
fixed-contract Shadow adapter, health metrics, permitted artifact sinks, persistent process host,
exact service-evidence writer/reader, settled snapshot publisher, and loopback read-only HTTP
surface in one continuously running process. It owns client/queue/request identity, lease, runtime
identity, lifecycle, stop/reconnect barriers, atomic projection publication, and guarded CLI, not
downstream economic Policy. `observe` and manifest-bound `observe-shadow` remain separate bounded
commands with unchanged semantics.

## Persistent process and read-only projection boundary

[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)
owns the run-segment evidence and projection boundary. One external state root holds one advisory
lease, one runtime identity, one reducer, one downstream owner, and one public client at a time. A
reconnect retires the old session epoch and reuses the same owner; a process restart creates a new
runtime identity and cannot continue prior state. An immediate zero-duration transport generation
remains an exact diagnostics restart chain and never becomes fabricated elapsed coverage.

After one reducer fact transaction settles Radar truth and the same transaction's Shadow owner
transition, `runtime.py` invokes one publisher. The publisher serializes a complete immutable
snapshot before replacing the published reference. HTTP handlers read only that reference. They do
not call detector/Policy/classification functions, freeze mutable state, traverse owner private
containers, or connect to Deribit. Lifecycle-only publications reuse the last immutable business
projection.

Service lifecycle/terminal evidence is separate from Radar and downstream object directories. The
service terminal independently recomputes current downstream object relationships, inventory,
Underwriting conservation, and logical non-enrolled Outcome conservation. It emits no manifest and
no forward-cohort summary; every service-created pair is non-enrolled. Existing bounded complete
readers remain manifest/cohort-specific and are not reused for the service.

The loopback server exposes only static assets, immutable snapshot JSON, health, and readiness over
GET/HEAD. Other methods are 405. It has no Policy mutation, account, credential, order, fill, or
execution route.

## Dependency direction

Current implementation:

```text
market_monitor → options_domain → short_vol_radar
       \______________|_______________/
                      ↓
            short_vol_underwriting

radar_runtime composes every implemented owner
```

Lower layers never import higher layers. Runtime composition may depend on all internal packages.
`short_vol_underwriting` is one pure domain/evidence owner, not a service. It never imports
`radar_runtime`; runtime composition may depend on every implemented internal package. No module
receives private/account access under `PUBLIC_SHADOW`.

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

The accepted downstream contracts refine those later public fee-reserve, defined-risk loss,
Candidate, Position, and counterfactual Outcome meanings without changing the Radar boundary.

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

## Decision and position architecture

The implemented downstream owner follows the accepted contract. Underwriting consumes an active
anomaly plus a current official atomic quote and compares its executable premium with declared
path, jump, tail, friction, liquidity, and uncertainty reserves. Separate evidence authorization
remains required to run this behavior production-public.

Candidate is permitted only when a complete Position Policy is already frozen. `SHADOW_ENTRY`
requires a still-valid Candidate and a post-Candidate official public combo snapshot/change or
post-Candidate public snapshot response with a strictly later source and causal identity. It
freezes the refreshed target-size atomic combo entry quote and creates no exposure. Admission has
no separate configurable Policy; its fixed gates bind the separate Underwriting and Position
Policies. A legged Shadow admission requires its own later Policy. Future actual exposure begins
at the first opening fill, including a partial or single-leg fill.

The Position Policy consumes current position-specific facts and returns
`HOLD | CLOSE | UNKNOWN`. It has explicit latest-exit and settlement boundaries but no
preselected holding duration. Position evaluation starts strictly after Entry, and the first
`CLOSE` is latched for that Shadow Position.

`close_quote_state` is separately
`ATOMIC_COMBO_CLOSE_QUOTE | LEGGED_CLOSE_REFERENCE | UNEXECUTABLE | UNKNOWN`. A known hard-close
condition remains `CLOSE` when its quote is unavailable. Public Shadow records
`SHADOW_CLOSE_OPPORTUNITY` only when action is `CLOSE` and a strictly later atomic combo quote
covers the full remaining quantity. A legged reference is diagnostic until an explicit legging
exit Policy is authorized. Future execution must reconcile orders and fills; exposure ends only
when the final closing fill makes every leg flat or authorized settlement completes. Shadow and
actual durations are different fields and may never be collapsed.

After `SHADOW_ENTRY`, runtime composition must maintain the official public catalog, platform,
index, ticker, and active-combo-book lifecycle needed by the open Shadow
Position independently of the Radar anomaly episode. Episode clear, pause, or Layer 2 shutdown
cannot stop Position observation. Component-option books are optional diagnostics; their absence
or gap is not a required-source failure. Quiet continuous books do not expire because no level
changed; last-mutation age remains diagnostic. This is bounded current state, not full-market
persistence. A public close opportunity never reduces Shadow remaining quantity or creates a
fill, flatness, settlement, PnL, or Outcome.

### Frozen Outcome and forward-cohort extension

The accepted Outcome/cohort contract begins after these upstream identities. Each `SHADOW_ENTRY`
starts one strictly-future observation. Its own causal-order first `ELIGIBLE` full-quantity close
opportunity after first CLOSE is selected exactly once as `SHADOW_COUNTERFACTUAL_EXIT`; no later or
better quote can replace it. The selected quote is not a fill, flatness fact, settlement action, or
exposure change.

Without a selected exit, an observation may become `MATURE_UNKNOWN` only at a strictly later settled
boundary after both canonical option instruments are known `delivered | archivized`, first CLOSE is
latched, and the one post-CLOSE attempt is terminal. No settlement-price source or payoff is
introduced, and economics remain null. Stop and failure censor pending units after their barriers;
ordinary gaps and `UNKNOWN` do not mature them.

Each `UnderwritingPositionSlotKey` may also contribute at most one separately labeled rejected
counterfactual: the causal-order first complete `EVALUABLE` `WATCH | ABSTAIN`. It reuses the exact
Position Policy and close classifier under `REJECTED_COUNTERFACTUAL_*` identities and never becomes
a Candidate, Entry, Shadow Position, or Shadow Outcome. A later Entry in the same slot remains a
separate causal unit.

Every admitted unit is aligned as `SHADOW_TRADE` versus `NO_TRADE`; every rejected unit is aligned
as `NO_TRADE` versus `REJECTED_COUNTERFACTUAL_TRADE`. The no-trade cashflow is definitionally zero,
but a pair is economically comparable only when its trade arm is `MATURE_KNOWN`. Unknown and
censored trade arms cannot enter the comparison denominator.

The `short_vol_underwriting` owner writes these objects to one downstream evidence directory
separate from Radar evidence. Existing Radar schemas and current/sealed readers remain unchanged.
The runtime continues to maintain bounded current public state for open observations after the
Radar episode ends; this is not full-market persistence, replay, or a workflow service.

## Denominator model

Each layer has its own unit:

```text
monitor: covered / degraded / unknown time
radar: usable evaluations by current TTE band; distinct short-leg episodes attributed once to activation band
atomic availability: active-anomaly evaluations by official combo state
underwriting: evaluable future opportunities and Candidate / Watch / Abstain actions
admission: Candidates and Shadow Entries / future executed Entries
position: Shadow Entries or opening fills and their separate mature / unknown Outcomes
close opportunity: known CLOSE actions and strictly later full-quantity atomic opportunities
outcome: admitted or rejected observations partitioned into pending, mature, or censored state
aligned cohort: one policy/no-trade pair per admitted or rejected anchor
workbench panel: settled-object presence, independent from every business denominator
workbench zero anomaly: only a complete known non-empty monitor denominator
workbench zero Candidate: only a strictly positive Underwriting-evaluable denominator
```

`UNKNOWN` is excluded from economic action, PnL, win/loss, and aligned-comparison denominators.
`MATURE_UNKNOWN` enters only the known-maturity availability denominator. A zero rate requires a
known nonzero denominator; a zero or unknown denominator serializes `null`. An empty workbench
panel is not a zero claim. Unknown monitor coverage or a zero Underwriting-evaluable denominator
remains `UNKNOWN / null`, never calm or no opportunity.

Market messages, detector calculations, quote updates, legs, schema checks, and elapsed runtime
are neither Radar-episode nor Candidate-opportunity denominators. Source generations, request ids,
files, and elapsed runtime are not Outcomes or cohort units.

## Structural non-goals

- a durable full-market event store on the Online Runtime hot path;
- periodic batch scanning or one process per structure;
- a generic scheduler, dependency graph, stream platform, feature store, or model registry;
- persisting every evaluation or theoretical structure;
- replay, an offline second calculator, or provenance machinery for the first Radar closure;
- maker, order, fill, fee, margin, or maximum-loss machinery inside public availability;
- networked service splits before a business closure requires them; the one bounded in-process
  persistent host/workbench is not a microservice split;
- account, delivery-price, or settlement-price machinery under public Shadow;
- an Outcome or Cohort Policy beyond the three accepted strategy Policy identities;
- hindsight, best-quote, last-quote, mark, midpoint, or settlement-payoff exits;
- combining qualification, Challenger, promotion, or execution with the first fixed-contract
  runtime/cohort closure;
- private execution components under public Shadow authority.
