# Optimatrix System Architecture

**Status:** ACTIVE STRUCTURAL AUTHORITY

## Architectural position

Optimatrix is one event-driven modular monolith. Market transport, current-state reduction, Radar,
Underwriting, Shadow admission, Position management, bounded process-independent Shadow Entry
persistence, funnel
projection, and the loopback Workbench run in one process. Each process starts with the fixed
`INVERSE_BTC_V1` profile. It binds the public source universe,
native/model/valuation units, one exact three-Policy chain, Inverse Case schema, funnel, and
Workbench projection for the full run. There is no product selector, fallback profile, or runtime
product switch. No network service split, database, message bus, replay job, generic scheduler, or
browser strategy engine is part of the current slice.

```text
Deribit public WebSocket for `INVERSE_BTC_V1`
→ one bounded application queue
→ one synchronous causal reducer
→ Radar current state
→ fixed Underwriting/admission/Position owner
→ in-memory current view + bounded funnel diagnostics
→ stable Case repository: aggregate / Observation Segment / transition / Outcome records
→ coalesced immutable Workbench snapshot
→ loopback GET/HEAD HTTP
```

The Online Runtime owns current decisions and one Observation Segment for each active admitted
Entry. The stable Case repository owns Entry aggregates across processes. Qualification Cohorts,
aligned comparisons, Challenger datasets, and promotion decisions are offline concerns.

## Ownership and dependency direction

```text
market_monitor
    Inverse BTC public source parsing, clock, catalogs, books, `btc_usd` index continuity
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

Before constructing the graph, startup resolves the canonical `INVERSE_BTC_V1` product
specification and its exact matching Radar, Underwriting, and Position Policies. Product/Policy
mismatch fails before any business owner is constructed. There is no product argument, second
product reducer, owner, queue, Case store, Workbench, or in-process product-comparison funnel.

After acquiring the stable state-root lease and before public intake, startup scans
`state-root/cases` and validates every Case directory through the one official reader. It restores
all and only non-terminal `ADMITTED_SHADOW_TRADE` Entries bound to `INVERSE_BTC_V1` and the
exact frozen Policy chain. A malformed, unsupported, or mixed active Entry fails the whole startup;
the runtime cannot skip it. Terminal admitted Entries and selected no-trade Controls remain
research history and are not restored. No CLI allowlist chooses business Entries.

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

For a restored Entry, its new Observation Segment begins at the first accepted settled boundary.
Until required fresh facts arrive, current observation and Position availability are `UNKNOWN`.
`HANDOFF_GAP` records observation quality and never manufactures a Position predicate or `CLOSE`.

## Transient state boundary

The following remain bounded in memory:

- platform, clock, catalog, ticker, book, index, RPC, and continuity state;
- Radar calculations, V2 score/bucket leadership, HIGH and LOW/MID research-review episodes,
  component-book counterfactuals, atomic diagnostics, Underwriting, causal batch designation,
  selected-decision refresh, Candidate,
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
its strictly later accepted paired entry witness. Enrollment is either an admitted Candidate trade,
one action-blind HIGH selected decision, or one future-blind LOW/MID score-band Control for a
causal Radar batch. The stable
repository is reused across runtime identities:

```text
state-root/
  service.lock
  cases/<case-id>/
    opened.json
    first-close.json                       optional, at most one
    outcome.json                           optional, at most one mature Entry Outcome
    segments/<segment-sequence>/opened.json
    segments/<segment-sequence>/closed.json      optional
```

The store owns atomic file publication, exact record validation, duplicate conflict rejection, and
a bounded startup scan of this one Case repository. It does not own market reconstruction,
qualification, Cohort membership, process supervision, host acceptance, a database, manifest, or
fencing service. `service.lock` prevents simultaneous writers on one host; it is not a distributed
lease or commissioning proof.

A new admitted Entry Case is not visible record-by-record. The writer builds and validates
`opened.json` plus the origin `segments/0/opened.json` inside one staging Case directory on the same
filesystem, then makes that complete directory visible with one no-replace atomic directory
publication. A crash before publication leaves no visible Entry Case; after publication both
records are visible. This protects the Entry boundary using the existing single-instance lease and
is not a manifest or fencing protocol.

The one store/reader owns the accepted Inverse schema-v5 Case family. It binds `INVERSE_BTC_V1`
explicitly, conserves BTC-native entry/close/fee/PnL facts plus separately named USD valuation facts,
and freezes one canonical V2 score packet at selection plus the same shape at entry refresh. There
is no online legacy-product, alternate-schema, or migration branch. A new admitted Entry's origin
Segment persists `entry_position_baseline`: the exact entry index and short-leg mark-IV source
references required by a future Position owner.

Each admitted Entry has one or more Observation Segments. Segment-open freezes current
code/runtime, product/Policy binding, adoption FactBoundary, predecessor segment, and observation
quality. The origin Segment alone owns the immutable `entry_position_baseline`; later Segments read
it without copying or rewriting it. Segment-close freezes clean-stop or handled-failure boundary
and reason. A hard crash may leave segment-open without segment-close; the reader reports that segment
`INCOMPLETE_UNCLEAN_EXIT`, and the next runtime opens a `HANDOFF_GAP` segment rather than completing
the missing record. FactBoundaries order facts only inside one segment. The immutable predecessor
chain orders segments without pretending that different runtime clocks are directly comparable.

Clean stop and handled failure close each active admitted Entry's current segment; they no longer
write `CENSORED_AT_STOP` or `CENSORED_AT_FAILURE` as the admitted Entry's mature Outcome. The Entry
remains recoverable until `outcome.json` exists. Selected no-trade Controls are not restored and
retain their existing bounded terminal Case semantics.

The first Position CLOSE and scheduling of the one paired close attempt publish atomically as one
durable transition. No request may be sent before that transition exists. Presence of the
transition prevents every later runtime from latching another first CLOSE or scheduling another
attempt. If its attempt was pending when a segment became incomplete, recovery exposes
`ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS` and does not retry.

## Internal state versus durable records

Internal owner transitions may retain detailed typed state for correct in-process decisions and
Workbench projection. They are implementation details, not durable object contracts and not
inputs to offline research. Recovery uses only validated bounded Case records; it does not persist
per-tick Position state, replay facts, content manifests, or whole-history relationship graphs.

The durable Case store consumes only Case opening, segment open/close, combined first-CLOSE/attempt
schedule, and mature Outcome. Runtime owner, trader Workbench, and AI Researcher directly consume
segment provenance and quality because later process boundaries cannot be derived from the original
opened record.

## Funnel diagnostics

The runtime exposes non-durable cumulative funnel counters and blocker reasons. Diagnostics are
computed from the same settled reducer/owner state, never by rereading files.

Instrument-specific source labels are normalized into bounded blocker categories before entering
cumulative counters. Exact current instrument/scope detail remains available in the ordinary
Workbench rows; it cannot create an unbounded aggregate reason-key set.
The same bounded diagnostic surface owns two additional runtime-local reason counters: loss of a
nonzero pre-activation Radar confirmation count, and selected-decision `KNOWN_NO_CONTROL`. Their
fixed enums are emitted by the bucket tracker and Underwriting owner respectively; Funnel only
aggregates them. Neither counter creates a durable record or reconstructs pre-restart history.

For Radar knownness, the funnel uses the canonical `IndexHistoryReducer` tail state already owned
by the settled reducer; it does not recalculate the Radar formula. The history reducer is the sole
validator and in-memory owner of the official `public/get_index_chart_data` response for the fixed
`btc_usd` index. It accepts only
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


The V2 calculator in `short_vol_radar` is the sole owner of target-size bid/ask use, official native
tick stress, Inverse product-owned Black-model normalization, Black inversion, TTE/Delta
eligibility, mixed reference RV, score normalization, bucket leadership, and persistence truth.
Depth walking and adverse tick stress
happen in the exchange-native BTC premium unit before conversion. Native BTC premium is converted
with the declared forward for model use. The forward used for model normalization is not the causal
index used to value BTC cashflows. The same Radar owner derives path quality and bounded optional
surface/term adjustments. It also projects unsigned OI/gamma concentration, protective vertical
references, and transparent attention order; those diagnostics cannot imply dealer sign or select
an Underwriting structure. For each active HIGH or designated LOW/MID research Episode, composition
waits for a complete positive option scope, excludes
known inactive or quantity-ineligible legs, and keeps potentially legal metadata/book/source gaps
`UNKNOWN`. It then uses the sole component-book calculator on every legal target-size protective
quote and passes those economics to the Underwriting-owned selector. The selector orders action
class `CANDIDATE > WATCH > ABSTAIN`, then the complete signed predicate-margin vector, narrower
width, and instrument name. Composition freezes that result and does not switch it during the
Episode. Official Combo availability remains a separate diagnostic.

Cross-sectional S/T composition uses ticker source timestamps with one Policy-owned `6000 ms`
maximum skew and ATM proxies within five absolute Delta points of `0.50`. Missing or over-skew
optional neighbours remove only their optional adjustment. Forward, Delta, and mark-IV changes are
score-countable and invalidate Call/Put peers on the affected expiry plus the immediately shorter
expiry whose `T` depends on it; OI/gamma-only changes remain non-countable diagnostics. The existing
global ticker source-staleness owner is not duplicated.

The Underwriting owner freezes every eligible HIGH member's activation score packet when the
action-blind batch is registered. A later non-designated Candidate consumes its own frozen HIGH
packet at selection and a truly later recomputed packet at entry refresh; it never relabels the
current packet as the activation witness.

`options_domain` owns the one product specification and one component-book calculator. Entry walks
short bids and long asks at the full target quantity, stresses short sells down one native legal
tick and long buys up one native legal tick, then applies both standard fees in the product's native
settlement currency. Close walks short asks and long bids, stresses short buys up one native tick
and long sells down one native tick, then applies both native fees. The calculator also produces one
explicit valuation projection at the causal `btc_usd` index. Native values remain BTC and their
valuation fields are explicitly USD-equivalent. Strike
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

Restoring an admitted Entry does not recreate Candidate, admission, or `SHADOW_CASE_OPENED` and
does not increment those funnel counters. A mature Outcome is counted once for the Entry aggregate,
regardless of which runtime segment produced it. Observation quality and qualification eligibility
remain separate from funnel lifecycle completeness.

`APPLICABLE_MARKET_SCOPE` and `RADAR_KNOWN` use post-warmup countable instrument evaluations. The
separate `radar_knownness.startup_warmup` projection retains startup/recovery counts and reasons, so
`INDEX_WARMUP` remains visible without becoming the steady-state primary blocker. Every Radar
UNKNOWN contributes exactly one finite aggregate reason. The primary-blocker function identifies
the earliest material post-warmup conversion loss and its largest reason. Official Combo outcomes
are counted in a separate diagnostic projection and never enter the canonical Shadow funnel.

Selected-decision research has a second, explicitly non-canonical projection: HIGH activation or
LOW/MID research-review batches, pre-outcome selected decisions, Decision Cases, and strictly
future Outcomes. It may include any Underwriting action, but a no-trade Case never increments the canonical
Candidate, `SHADOW_CASE_OPENED`, or `SHADOW_CASE_OUTCOME` stages. The projection retains cumulative
scalars and only current/latest bounded identities.

The Workbench projects every active admitted Entry once by `shadow_entry_identity`, with origin
runtime, current segment runtime, segment availability, gap count, observation quality, and
qualification eligibility. A recovered Entry begins `UNKNOWN` until fresh facts settle. The browser
never infers `HOLD` or `CLOSE` from `HANDOFF_GAP`.

Funnel diagnostics may be displayed and logged externally, but they are not business evidence or
qualification data.

## Workbench boundary

Workbench publication occurs only after the full reducer-plus-owner transaction. Ordinary
status-stable updates are coalesced to at most 2 Hz; service/currentness changes publish
immediately; pending state flushes before reconnect or stop.

HTTP handlers read one immutable complete byte snapshot. They never traverse mutable reducer
state, read Shadow Case files, compute strategy truth, modify Policy, contact Deribit, or expose a
write route. The server binds only to loopback and supports the declared GET/HEAD surface. The
snapshot contains the fixed `INVERSE_BTC_V1` identity, public/index/native/settlement/valuation units,
a bounded Top-N attention view plus `ALL`, exact V2 score/leader inputs, source-contract facts, a
separate selected-decision panel with original/refreshed score packets, actions, and margin vectors,
enrollment/Outcome state, and diagnostic non-claims. Browser code only renders server-owned typed
truth; it does not infer a unit from an internal field suffix or recalculate score, leader, IV, RV, surface,
structure economics, or decision-control membership.
For review-only TTE/Delta rows it renders score context plus the server-owned review constraint,
never confirmation progress. Runtime-wide reason counts are explicitly labeled cumulative and not
as causal attribution for the selected row.

## Failure domains

- malformed or incompatible public protocol: fail the owning session or process as declared;
- unavailable index-chart refresh: retain the last valid in-memory history until its Policy stale
  deadline, then expose bounded Radar `UNKNOWN`; a completed-point revision is `REVISION/UNKNOWN`
  until one stable follow-up response; neither condition reconnects the streaming index;
- local option/book/ticker missingness: `UNKNOWN` at the smallest consumer;
- reconnect: rebuild current session facts without replacing the same in-process Shadow owner;
- process restart: after the external operator starts the service, validate and restore every
  compatible non-terminal admitted Entry, then expose `UNKNOWN` until fresh facts settle;
- Workbench publication error: explicit process failure in the current simple topology, not stale
  success;
- Shadow Case write conflict or I/O failure after enrollment: explicit process failure because an
  enrolled research Case must not be silently lost;
- active Case corruption, unsupported frozen Policy, segment-chain conflict, or omitted compatible
  admitted Entry: fail startup before public intake; never continue with a partial active book;
- host CPU, memory, process restart, launchd/systemd, logs, and deployment health: external
  operations, not application business truth.

## Validation ownership

Every external trust boundary has one validator:

- public JSON and source shapes: market/transport owner;
- Policy JSON and chain compatibility: Policy loader;
- business decisions: Radar/Underwriting/Position owner;
- durable aggregate, segment, transition, and Outcome records: Shadow Case store/reader.

No emitted result is re-run through a second business schema, relationship graph, provenance graph,
or validator-of-validator. The one Case store/reader accepts exactly the Inverse schema-v5 record
family bound to the fixed Policy chain. Unit tests may independently exercise pure formulas; they
do not create a second runtime truth path.

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
- per-tick Position checkpoints, gap backfill, restart-time `CLOSE` synthesis, Entry allowlists,
  process-owned continuation claims, manifests, or a distributed fencing service;
- private/account/order/fill/capital modules before separate authority.

## Complexity stop rule

If one non-product control subsystem causes a second real runtime failure, the default response is
delete or externalize it. Continued repair requires proving that removing it would create an
incorrect trader decision, lose an enrolled Shadow Case, or expose actual account/capital risk.

No pre-Shadow component may open a file.
