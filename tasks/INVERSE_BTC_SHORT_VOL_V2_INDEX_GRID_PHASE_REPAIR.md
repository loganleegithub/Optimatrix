# Task — V2 source-grid and confirmation-continuity repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `89e83e04871fd2b230b1868d399d7dec45865a6b`

**Target branch/PR:** `codex/v2-index-grid-phase-fix` /
[Draft PR #48](https://github.com/loganleegithub/Optimatrix/pull/48)

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION.md`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_RADAR.md`](../docs/contracts/SHORT_VOL_RADAR.md), and
[`SHORT_VOL_UNDERWRITING_POSITION.md`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE.md`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE → UNDERWRITING → SHADOW_CASE_OPENED`

**Baseline:** after the source-grid and confirmation-continuity fixes, clean code identity
`6fbcf9fbf4237d6685cbf7ae986dc4dfa4dfee76` remained healthy, ready, `CURRENT`,
`KNOWN_COMPLETE`, and `128/128`. Nine HIGH Episodes reached fully evaluable Underwriting; each was
a known non-Candidate because credit did not exceed the fixed future-cost reserve. One bounded LOW
research Control opened in the stable schema-v5 repository, while admitted Shadow count remained
zero. A later `5,011 ms` queue-lag frame became `STALE/UNKNOWN`, recovered about one second later,
and produced zero destructive pre-confirmation core resets.

**Repaired baseline blocker:** `ORDERED_QUEUE_LAG_DESTRUCTIVE_PRECONFIRMATION_RESET`. On the
threshold-crossing refresh, the queue-lag currentness gate correctly changed every current Radar
evaluation to `UNKNOWN`, but the bucket owner also erased every nonzero, not-yet-active
confirmation. One known HIGH target changed `2 → 0`; the global `CORE_UNKNOWN` reset counter
increased by `13`. About half a second later the same session, bucket leader, HIGH band, and
source-confirmed baseline recovered, yet confirmation restarted at `0 → 1`. Reconnect, protocol
gap, and continuity-epoch counts did not change.

That runtime blocker is repaired. The first observed verification blocker was
`OFFLINE_CASE_DIRECTORY_IDENTITY_MISPARSE`: the CaseStore writes a canonical `sha256:<digest>` Case
under a bare `<digest>` directory, but `report-v2-cases` duplicated the scanner and required the
directory name itself to match `sha256:<digest>`. The official report therefore rejected the first
valid Control Case before reading it. This is not Case corruption and is not the current business
funnel blocker. That reader defect is repaired.

**Current implementation blockers:**
`ACTIVATION_PACKET_MUTABLE_PROJECTION_GAP` and
`ORDERED_BUSINESS_QUEUE_HEARTBEAT_TEST_RESPONSE_DELAY`. Code identity
`6093cd0825cf6c7352d30270ecb2c5742c81182a` proved the interrupted-terminal Candidate cleanup:
two separate reconnects retired four Candidates without the former cleanup invariant. The
reconnects occurred `613,931 ms` apart, each near the ten-minute session boundary. Deribit requires
an immediate `public/test` response to each server `test_request`, but the response was previously
scheduled only after that notification traversed the same synchronous Radar/Underwriting queue
whose measured lag can exceed five seconds.

The same continued run then produced the first two admitted Shadow Cases. A later Candidate's
paired refresh remained Candidate, but Case creation stopped fail-closed with
`Radar-owned Underwriting facts lack their activation score packet`. The Radar Episode already
owned the immutable activation packet. At its activation boundary, however, composition looked up
the mutable current-packet cache and projected no Underwriting facts when that cache was absent.
The later Candidate was therefore valid but the owner had never received the original packet
needed for its schema-v5 Case. This is a composition-source bug, not a missing market fact or a
reason to weaken Case validation.

**Measured business blocker:** the stopped run reached `16` HIGH Episodes, `15` fully evaluable
Underwriting Episodes, `6` Candidates, and `2` admitted Shadow Cases. Four Candidates were first
blocked by `ADMISSION_KNOWN_INVALIDATED_BEFORE_REFRESH`; the two admitted Cases remain readable and
recoverable. The next admission reached complete Candidate economics but hit the activation-packet
composition defect before a third Case could open. None of the economic rules changes in this
implementation repair.

**Expected user-visible delta:** while ordered queue lag is above the fixed currentness deadline,
Radar remains `UNKNOWN`, bucket coverage is `UNKNOWN`, no observation is counted, and no Episode or
downstream admission can occur. An inactive tracker retains only confirmations already accepted
before the lag. On catch-up the current facts are recomputed: the same leader and band continue
from the retained count, while a changed leader, band, scope, or persistent core loss resets under
the existing rules.

The offline report additionally reads the exact directories produced by `ShadowCaseStore`, keeps
Control and admitted enrollment strata separate, and can independently verify the first future
admitted Shadow without changing the running service.

The score-packet projection additionally preserves every significant digit of each frozen raw
Decimal, so the sole policy-aware validator reproduces the exact stored A/S/T/D/E result after JSON
restoration. Online scores, bands, rankings, and admission decisions do not change.

Candidate cleanup additionally decouples two distinct transitions: an admission terminal record is
emitted only if the attempt first becomes terminal, while Episode loss always invalidates any
still-valid Candidate. A terminal attempt can therefore never strand its Candidate in the active
owner map or turn ordinary Episode retirement into a process-fatal integrity error.

Interrupted-transition cleanup additionally marks every Candidate owned by an ending Episode for
map retirement after terminalization. An already-terminal lifecycle produces no duplicate business
record, while any initiating exception remains available to be raised after cleanup instead of
being hidden by a second Candidate-owner invariant.

Activation composition additionally uses the Episode-owned frozen packet at the exact activation
causal boundary. Later boundaries continue to require a truly current packet. The transport
additionally answers Deribit `test_request` immediately, validates and consumes the matching
transport-local response, and leaves the reducer with no heartbeat-test RPC lifecycle to delay or
duplicate.

**Durable-data effect:** no existing Case is rewritten, migrated, or deleted. The stopped run's two
admitted Cases are preserved byte-for-byte and the official reader finds both as recoverable active
Entries whose prior Segments ended `CENSORED_AT_FAILURE`. The authorized recovery start opens one
ordinary `GAPPED` Observation Segment for each Entry; that process-boundary fact cannot be derived
offline. No heartbeat or pre-Shadow diagnostic is persisted.

**Complexity added:** one activation-boundary selection of the Episode-owned packet and one bounded
transport-local in-flight heartbeat request id, in addition to the already-landed currentness,
reader, Decimal, and Candidate-cleanup repairs. There is no new business owner, timer, schema,
history, or baseline path.

**Complexity deleted:** the rotating five-phase sampling behavior, the wall-clock-ahead-of-source
anchor race, the misleading baseline source label, the destructive interpretation of a transient
ordered backlog as lost pre-confirmation evidence, the offline report's duplicate Case identity
parser, the score packet's ambient-context-dependent Decimal normalization, and the reducer-owned
`HEARTBEAT_TEST` purpose/send/response lifecycle.

## Business closure

**Given:** an inactive clue-eligible bucket tracker with accepted nonzero confirmation, followed by
an ordered envelope whose receive-to-reducer lag exceeds the fixed Policy currentness deadline.

**When:** the lagged envelope settles and a later ordered envelope catches the reducer up without a
session, continuity, scope, leader, or score-band change.

**Then:** the lagged frame remains `UNKNOWN` and contributes no observation or admission, the
previous confirmation count is unchanged, and recovery resumes from that count only after current
truth proves the same leader and score band.

**Valid zero/UNKNOWN:** the queue-lag interval itself remains current `UNKNOWN`; an active Episode
continues to end fail-closed on core loss. A missing interior index point, stale source, revision,
warmup, invalid input, real scope loss, leader change, score-band change, session gap, or run stop
still resets or ends through its existing owner. Zero canonical Shadow admissions is valid if no
corrected HIGH survives three real separated observations or Underwriting does not produce a
Candidate; a reset caused only by a transient ordered queue backlog is not valid.

**Cheapest falsification:** establish one pre-activation observation, process one deliberately
lagged but ordered envelope, catch up without counting a new observation, and observe any change in
the prior count or any Candidate/Case created during the `UNKNOWN` interval.

For the reader boundary, create or observe one store-written bare 64-hex Case directory and run the
official report. Rejecting that directory, changing its Case identity, or mixing its Control row
into admitted Shadow is a direct falsification.

For packet integrity, calculate D from a baseline share carrying more than 28 significant digits,
serialize the packet, restore it, and policy-recompute it. Any lost raw digit or result mismatch is
a direct falsification.

For Candidate retirement, terminalize an admission attempt while its Candidate remains `VALID`,
then retire the owning Episode. Any duplicate admission terminal, retained Candidate, missing
Candidate invalidation, or runtime exception is a direct falsification.

For activation-packet closure, confirm an Episode, remove its mutable current-packet projection at
the same causal boundary, and project Underwriting. Missing the Episode-owned activation packet,
failing to register the batch, or later being unable to open a valid Candidate Case is a direct
falsification.

For transport liveness, queue business frames without reducing them, receive `test_request`, and
observe the required `public/test` on the socket before any application dequeue. Enqueuing a
heartbeat-test application RPC, accepting a mismatched/invalid response, or waiting for business
reduction is a direct falsification.

## Change declarations

**Market/Decision input contract change:** five-minute index-chart samples remain fixed to the
source-confirmed UTC epoch grid. Ordered queue-lag currentness is a pre-activation observation pause,
not evidence that previously accepted observations disappeared; current score and admission truth
remain `UNKNOWN` until catch-up. Deribit connection liveness is answered below the business queue;
it contributes no market or decision input.

**Decision Policy change:** `NONE`; the three Policy artifacts and identities remain byte-exact.

**Outcome/evaluation contract change:** preserve raw score-packet Decimal precision so the existing
policy-aware Case validator can reproduce exact derived truth; no Outcome arithmetic or economic
definition changes. Episode retirement reconciles an already-terminal attempt with its still-valid
Candidate. Case selection consumes the actual Episode-owned activation packet and never a later
substitute.

**Stage/authorization change:** code identity
`6093cd0825cf6c7352d30270ecb2c5742c81182a` produced and durably opened the first two admitted
Shadow Cases before the activation-packet composition failure stopped the service. The user's
continued-repair authorization permits one checked recovery cutover from the non-temporary
`/Users/logan/Optimatrix-runtime` checkout, reusing the unchanged stable root and recovering both
Entries. Continue production-public observation across a later ten-minute heartbeat boundary. No
private or execution permission is added.

## Scope

**In:** the sole public transport's Deribit heartbeat response, the sole runtime bucket-settlement
owner and its activation/currentness transition; the
already-landed `IndexHistoryReducer` source-grid repair; the CaseStore-owned directory identity
conversion and read-only V2 report; lossless V2 packet Decimal serialization; focused
market/runtime/Workbench/Radar/Case/report tests; owning contracts, task, and Current Stage
authority; one bounded cutover and continued public-only observation.

**Out:** score weights, thresholds, TTE/Delta rules, confirmation counts or separations, preservation
of an already-active Episode, any Policy artifact, Underwriting or Position economics, Case schema,
state-root migration, private data, orders, fills, capital, process supervision, or a second
baseline path.

**Owning modules:** `apps/radar_runtime/src/radar_runtime/deribit_public.py`,
`apps/radar_runtime/src/radar_runtime/runtime.py`,
`apps/radar_runtime/src/radar_runtime/offline_report.py`, and
`packages/short_vol_underwriting/src/short_vol_underwriting/case_store.py`, plus the score-packet
serializer in `packages/short_vol_radar/src/short_vol_radar/score.py` and the bounded Candidate
lifecycle owner in `packages/short_vol_underwriting/src/short_vol_underwriting/owner.py`

## Validation

- focused tests: `.venv/bin/pytest -q tests/test_market_monitor.py tests/test_runtime_reducer.py tests/test_fact_boundary_business.py tests/test_trader_workbench.py`;
- repository gate: `make check`;
- public observation: the official reader inventoried the already-stopped stable root, then clean
  code identity `21128eb6807cd1403b3b458da1c418c16dcdf099` started on port `8675` with
  `/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`; verify its exact runtime identity,
  health/readiness/currentness, fixed-grid baseline behavior across canonical boundaries, and
  continue the already-authorized public-only monitor;
- run `report-v2-cases --runtime-active` against the unchanged stable root and prove the first
  store-written Control Case is readable under its canonical prefixed identity;
- prove a greater-than-28-digit raw path share survives packet serialization and exact
  policy-aware recomputation, then validate live projected packets after the bounded cutover;
- prove the first post-repair decision Control on the former fatal path is published and restored
  by the official reader under its exact code/runtime and Policy identities, while admitted Shadow
  remains zero;
- prove an already-terminal admission attempt cannot strand a valid Candidate during Episode
  retirement, emits no duplicate terminal, and leaves no active Candidate or durable Case;
- prove a Candidate terminalized in an interrupted owner transition is removed by later Episode
  retirement without a duplicate emission, and that cleanup no longer masks an initiating failure;
- prove the exact activation boundary uses the Episode-owned packet when the mutable current cache
  is absent, and that Underwriting still registers the batch and Candidate;
- prove the transport sends `public/test` before any application dequeue, filters one valid matching
  response, rejects invalid/mismatched responses, and exposes no `HEARTBEAT_TEST` application RPC;
- use the official Case reader to recover both admitted Entries from the stopped run, then verify
  their new GAPPED Segments and active API identities after the clean start;
- fixed-attribution live evidence: cross queue currentness above five seconds and prove the frame is
  UNKNOWN/non-countable, adds zero `CORE_UNKNOWN` reset, and preserves accepted pre-confirmation
  through catch-up; keep any separate transport/session reset explicitly attributed;
- no manifest, receipt, commissioning subsystem, runtime self-acceptance, or host inspection.

## Definition of done

The rotating phase, source-ahead race, queue-lag destructive reset, activation-packet projection
gap, and queued heartbeat-test response are impossible by direct tests; the official reader accepts
store-owned bare digest directories and preserves canonical identities; high-precision raw score
inputs round-trip and recompute exactly; the full repository gate passes; both admitted Entries are
verified through the API and official Case reader after recovery; the connection crosses a later
ten-minute boundary without another heartbeat-driven reconnect; the diff is bounded and remote
state is exact.
