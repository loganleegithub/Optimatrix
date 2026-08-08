# Optimatrix System Architecture

**Status:** ACTIVE STRUCTURAL AUTHORITY

## Architectural position

Optimatrix is one event-driven modular monolith. Market transport, current-state reduction, Radar,
Underwriting, Shadow admission, Position management, bounded Shadow Case persistence, funnel
projection, and the loopback Workbench run in one process. Each process selects exactly one product
profile at startup: `LINEAR_BTC_USDC_V1` or `INVERSE_BTC_V1`. That profile binds the public source
universe, native/model/valuation units, one exact three-Policy chain, Case schema, funnel, and
Workbench projection for the full run. One process never observes, aggregates, or switches between
both products. No network service split, database, message bus, replay job, generic scheduler, or
browser strategy engine is part of the current slice.

```text
Deribit public WebSocket for one selected product
→ one bounded application queue
→ one synchronous causal reducer
→ Radar current state
→ fixed Underwriting/admission/Position owner
→ in-memory current view + bounded funnel diagnostics
→ optional SHADOW_CASE_OPENED / transition / outcome records
→ coalesced immutable Workbench snapshot
→ loopback GET/HEAD HTTP
```

The Online Runtime owns current decisions and Shadow Cases. Qualification Cohorts, aligned
comparisons, Challenger datasets, and promotion decisions are offline concerns.

## Ownership and dependency direction

```text
market_monitor
    selected-product public source parsing, clock, catalogs, books, index continuity
        ↓
options_domain
    one product specification, instruments, amount rules, native target-depth/tick stress,
    component-book fees, model normalization, and valuation conversion
        ↓
short_vol_radar
    detector, episode, protective-leg review, official atomic diagnostic, Policy parsing
        ↓
short_vol_underwriting
    Underwriting, Candidate, admission, Position, Outcome, Shadow Case store
        ↓
radar_runtime
    Deribit transport, one reducer, composition, funnel projection, Workbench
```

Lower packages do not import higher packages. `radar_runtime` may compose every layer but does not
own strategy formulas.

## One causal application path

Before constructing the graph, startup resolves one canonical product specification and its exact
matching Radar, Underwriting, and Position Policies. Product/Policy mismatch fails before any
business owner is constructed. The selected product is immutable for the runtime; there is no
second product reducer, owner, queue, Case store, Workbench, or in-process cross-product funnel.

One application-sequence allocator stamps every accepted decoded frame and transport-control fact
with a session epoch, consecutive ingress sequence, and monotonic receive boundary. One bounded
transport queue preserves application order; runtime does not drain it into a second unbounded
pending deque. One synchronous reducer exclusively owns mutable market and Radar state, processes a
local option fact locally, and never waits for network I/O. Cooperative yielding keeps reader,
sender, and clock-source tasks schedulable while the queue is non-empty.

The reducer settles one accepted fact completely before calling the downstream owner. The owner
then settles Underwriting, admission, every open Shadow Position, and Outcome before Workbench or
funnel publication. No second reducer, response-future owner, or persisted replay path may apply
business truth.

## Transient state boundary

The following remain bounded in memory:

- platform, clock, catalog, ticker, book, index, RPC, and continuity state;
- Radar calculations, detector episodes, component-book counterfactuals, atomic diagnostics,
  Underwriting, causal activation-batch designation, selected-decision refresh, Candidate,
  admission, and current Position state;
- internal typed transitions used by the owner and Workbench;
- service status and funnel diagnostics.

“Bounded” means current ownership, not retained process history. An ended Radar Episode, terminal
Candidate/admission attempt, and terminal Shadow Case are removed from their active owner maps.
Workbench may retain only the current live set plus one latest terminal Case projection. Funnel
diagnostics retain cumulative scalar counts and a fixed blocker-reason vocabulary, while completed
Episode, Candidate, and Case identities are discarded.

Normal market facts, anomalies, component quotes, atomic diagnostics, Underwriting decisions, Candidates, admission
attempts, run summaries, and Workbench snapshots are not written to disk.

An immutable in-memory snapshot is allowed for lock-free HTTP reads. Immutability for readers does
not make a snapshot a durable business record.

## Shadow Case persistence boundary

The first durable record is `SHADOW_CASE_OPENED`, emitted only after a pre-outcome enrollment and
its strictly later accepted paired entry witness. Enrollment is either an admitted Candidate trade
or the one action-blind selected no-trade decision for a causal Radar activation batch. A Case
directory may then contain at most:

```text
opened.json
first-close.json       optional, at most one
outcome.json           optional, at most one
```

The store owns atomic file publication, exact record validation, duplicate conflict rejection, and
a minimal read path. It does not own market reconstruction, runtime recovery, qualification,
Cohort membership, or host acceptance.

The one store/reader owns exactly two compatible versions of the same Case family:

- schema v3 remains the byte-exact Linear BTC-USDC record contract. It has no added keys and binds
  its product implicitly through the fixed Linear Policy chain;
- schema v4 is reserved for a future authorized Inverse BTC Case. It binds the product explicitly
  and conserves BTC-native entry/close/fee/PnL facts plus separately named USD valuation facts at
  their declared causal index boundaries.

These are version branches inside one validator, not parallel business schemas or a migration of
existing records. The current implementation closure writes neither version because live commands
are forbidden.

A new runtime never resumes another runtime's Case. If a hard crash leaves only `opened.json`, the
offline reader reports `INCOMPLETE_UNCLEAN_EXIT`. Clean stop and handled process failure ask the
business owner to emit a censored Outcome before process exit.

## Internal state versus durable records

Internal owner transitions may retain detailed typed state for correct in-process decisions and
Workbench projection. They are implementation details, not durable object contracts and not
inputs to offline research. They must not require filesystem I/O, content manifests, repository
readers, or whole-history relationship validation.

The durable Case store consumes only three bounded transition classes from that current state:
Case opening, first CLOSE, and terminal Outcome. Any new durable record requires explicit Product
Constitution authority and a direct offline consumer that cannot derive it from existing Case
records.

## Funnel diagnostics

The runtime exposes non-durable cumulative funnel counters and blocker reasons. Diagnostics are
computed from the same settled reducer/owner state, never by rereading files.

Instrument-specific source labels are normalized into bounded blocker categories before entering
cumulative counters. Exact current instrument/scope detail remains available in the ordinary
Workbench rows; it cannot create an unbounded aggregate reason-key set.

For Radar knownness, the funnel uses the canonical `IndexHistoryReducer` tail state already owned
by the settled reducer; it does not recalculate the Radar formula. The history reducer is the sole
validator and in-memory owner of the official `public/get_index_chart_data` response for the
startup-selected product index: `btc_usdc` for Linear or `btc_usd` for Inverse. It accepts only
bounded, strictly chronological, positive finite average-price points for that one index, applies
the configured completed-interval cutoff, exposes cadence/age/exact-suffix facts including whether
the newest response point falls outside that cutoff, and detects completed-overlap revision. It
never interpolates or fills a gap. The warmup gate is per Policy TTE band:

- `IndexHistoryReducer` owns causal sampling and availability; the Radar baseline calculator owns
  only multi-horizon variance selection over those samples. The streaming `IndexMinuteReducer`
  continues to own live index currentness and publication, but no longer owns the economic
  360-minute baseline;

- an applicable countable evaluation with current index availability `WARMUP` is assigned to the
  visible startup/recovery bucket and never to the steady denominator;
- the boundary at which that band first has an `AVAILABLE` tail is post-warmup;
- after a band has been available, later history `SOURCE_STALE`, `WINDOW_GAP`, or `REVISION`, or
  live-index `CONTINUITY_GAP`, evaluations remain post-warmup steady-state UNKNOWNs;
- a later `WARMUP` recovery interval returns to the startup/recovery bucket until availability is
  restored.


The hard-screen calculator in `short_vol_radar` is the sole owner of target-size bid/ask use,
official native tick stress, product-owned Black-model normalization, Black inversion, TTE/Delta
clue eligibility, and stressed IV/RV detector truth. Depth walking and adverse tick stress happen
in the exchange-native premium unit before conversion. Linear native premium is already in the
Black strike-currency domain; Inverse BTC native premium is converted with the declared forward for
model use. The forward used for model normalization is not the causal index used to value BTC
cashflows. The separate review calculator may derive semivariance/jump context, surface-lite context,
protective vertical references, and transparent attention rank from already settled current state.
Its bounded Top 3 is display-only and cannot select an Underwriting structure or feed detector
truth. For each active Episode, composition waits for a complete positive option scope, excludes
known inactive or quantity-ineligible legs, and keeps potentially legal metadata/book/source gaps
`UNKNOWN`. It then uses the sole component-book calculator on every legal target-size protective
quote and passes those economics to the Underwriting-owned selector. The selector orders action
class `CANDIDATE > WATCH > ABSTAIN`, then the complete signed predicate-margin vector, narrower
width, and instrument name. Composition freezes that result and does not switch it during the
Episode. Official Combo availability remains a separate diagnostic.

`options_domain` owns the one product specification and one component-book calculator. Entry walks
short bids and long asks at the full target quantity, stresses short sells down one native legal
tick and long buys up one native legal tick, then applies both standard fees in the product's native
settlement currency. Close walks short asks and long bids, stresses short buys up one native tick
and long sells down one native tick, then applies both native fees. The calculator also produces one
explicit valuation projection at the causal selected-product index. Linear values remain USDC;
Inverse native values remain BTC and their valuation fields are explicitly USD-equivalent. Strike
width and contractual payoff cap are USD-defined; Inverse BTC liability depends on settlement
price, while actual account margin remains `UNKNOWN`. The same product-aware value object owns the
canonical scalar fingerprint projection used by Underwriting and Position; no second leg-price
calculator or parallel quote schema is permitted.

Candidate admission, non-Candidate selected-decision enrollment, and post-CLOSE each schedule
exactly two bounded
`public/get_order_book` requests for the frozen legs. The downstream owner accepts a quote only
after both strictly later responses share one causal owner, session epoch, and global continuity
epoch; each covers the full quantity; source timestamps differ by no more than `6000 ms`; and local
receive boundaries differ by no more than `4000 ms`. A single response cannot open or close a Case.
Failure of either response retires the sibling and settles the one paired attempt. Session,
continuity, or skew mismatch is a bounded `UNKNOWN` with an exact reason, not an integrity exception.
When the selected decision is already a Candidate, its ordinary admission pair is the selection's
future-blind pair; a duplicate control refresh is forbidden. If that refresh remains Candidate it
opens the ordinary admitted Case, while a refreshed WATCH/ABSTAIN opens the discriminated no-trade
Case. A selected WATCH/ABSTAIN that refreshes to Candidate opens nothing, reports
`REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION`, and cannot bypass a later Candidate's own
strictly later admission pair. A selected `UNKNOWN` opens nothing and has no fallback Episode.

The canonical stages are:

```text
APPLICABLE_MARKET_SCOPE
RADAR_KNOWN
ANOMALY_ACTIVE
STRUCTURE_REVIEWABLE
COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
UNDERWRITING_EVALUABLE
CANDIDATE
SHADOW_CASE_OPENED
SHADOW_CASE_OUTCOME
```

The last two canonical stages count admitted-Candidate Cases only; selected no-trade Cases use the
separate research projection below despite sharing the durable Case record family.

`APPLICABLE_MARKET_SCOPE` and `RADAR_KNOWN` use post-warmup countable instrument evaluations. The
separate `radar_knownness.startup_warmup` projection retains startup/recovery counts and reasons, so
`INDEX_WARMUP` remains visible without becoming the steady-state primary blocker. Every Radar
UNKNOWN contributes exactly one finite aggregate reason. The primary-blocker function identifies
the earliest material post-warmup conversion loss and its largest reason. Official Combo outcomes
are counted in a separate diagnostic projection and never enter the canonical Shadow funnel.

Selected-decision research has a second, explicitly non-canonical projection: activation batches,
pre-outcome selected decisions, Decision Cases, and strictly future Outcomes. It may include
Candidate, WATCH, or ABSTAIN decisions, but a WATCH/ABSTAIN Case never increments the canonical
Candidate, `SHADOW_CASE_OPENED`, or `SHADOW_CASE_OUTCOME` stages. The projection retains cumulative
scalars and only current/latest bounded identities.

Funnel diagnostics may be displayed and logged externally, but they are not business evidence or
qualification data.

## Workbench boundary

Workbench publication occurs only after the full reducer-plus-owner transaction. Ordinary
status-stable updates are coalesced to at most 2 Hz; service/currentness changes publish
immediately; pending state flushes before reconnect or stop.

HTTP handlers read one immutable complete byte snapshot. They never traverse mutable reducer
state, read Shadow Case files, compute strategy truth, modify Policy, contact Deribit, or expose a
write route. The server binds only to loopback and supports the declared GET/HEAD surface. The
snapshot contains the one selected product identity, public/index/native/settlement/valuation units,
a bounded Top-N attention view plus `ALL`, exact rank inputs, source-contract facts, hard-screen
fields, a separate selected-decision panel with original/refreshed actions and margin vectors,
enrollment/Outcome state, and diagnostic non-claims. Browser code only renders server-owned typed
truth; it does not infer a unit from a legacy field suffix or recalculate rank, IV, RV, surface,
structure economics, or decision-control membership.

## Failure domains

- malformed or incompatible public protocol: fail the owning session or process as declared;
- unavailable index-chart refresh: retain the last valid in-memory history until its Policy stale
  deadline, then expose bounded Radar `UNKNOWN`; a completed-point revision is `REVISION/UNKNOWN`
  until one stable follow-up response; neither condition reconnects the streaming index;
- local option/book/ticker missingness: `UNKNOWN` at the smallest consumer;
- reconnect: rebuild current session facts without replacing the same in-process Shadow owner;
- Workbench publication error: explicit process failure in the current simple topology, not stale
  success;
- Shadow Case write conflict or I/O failure after enrollment: explicit process failure because an
  enrolled research Case must not be silently lost;
- host CPU, memory, process restart, launchd/systemd, logs, and deployment health: external
  operations, not application business truth.

## Validation ownership

Every external trust boundary has one validator:

- public JSON and source shapes: market/transport owner;
- Policy JSON and chain compatibility: Policy loader;
- business decisions: Radar/Underwriting/Position owner;
- durable Case records: Shadow Case store/reader.

No emitted result is re-run through a second business schema, relationship graph, provenance graph,
or validator-of-validator. The one Case store/reader may select its exact v3 Linear or v4 Inverse
version branch from the product-bound Policy chain; it never passes one record through both. Unit
tests may independently exercise pure formulas; they do not create a second runtime truth path.

## Structural non-goals

The current architecture forbids:

- application commissioning, `launchd`, `lsof`, Unified Log, PID inventory, host resource gates,
  acceptance supervisors, manifests, or receipt chains;
- pre-Shadow filesystem writes, Radar evidence writers, service ledgers, Workbench persistence, or
  online run summaries;
- online Cohort manager, automatic rejected-counterfactual lifecycle, aligned-pair persistence, or
  qualification controller;
- full-feed capture/replay, database, generic event platform, feature store, scheduler, workflow
  engine, or premature microservices;
- private/account/order/fill/capital modules before separate authority.

## Complexity stop rule

If one non-product control subsystem causes a second real runtime failure, the default response is
delete or externalize it. Continued repair requires proving that removing it would create an
incorrect trader decision, lose an enrolled Shadow Case, or expose actual account/capital risk.

No pre-Shadow component may open a file.
