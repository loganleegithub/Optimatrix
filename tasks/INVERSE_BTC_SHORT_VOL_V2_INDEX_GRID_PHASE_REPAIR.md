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

**Current implementation blocker:** `INTERRUPTED_TERMINAL_CANDIDATE_RETIREMENT_GAP`. The first
repair covered an admission attempt that was already terminal while its Candidate remained
`VALID`. Continued live observation then reached seven HIGH Episodes and two simultaneous
Candidates before failure handling retired the epoch and reproduced
`ended Radar episode still owns an active Candidate`. The broader reproduction proves the remaining
root cause: a prior owner transition can terminalize a Candidate and then fail before
`_finish_transition()` removes it. The next retirement transition resets the pending-retirement
set, correctly avoids a duplicate invalidation for the already-terminal lifecycle, but previously
left that record in the active Candidate map. The cleanup exception masked the initiating failure,
whose exact type remains `UNKNOWN` for the stopped run.

**Measured business blocker:** 33 of the first 36 fully evaluable HIGH Episodes were first blocked
by `CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE`; one each was first blocked by
`MINIMUM_NET_CREDIT_TO_PAYOFF_CAP` and `MINIMUM_NET_ENTRY_CREDIT`, and one became the first
canonical Candidate. It was invalidated before paired admission and opened no Shadow Case. None of
these economic rules changes in this implementation repair.

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

**Durable-data effect:** no existing Case is created, rewritten, migrated, or deleted. Future Case
JSON may carry more significant raw-input digits, under the unchanged schema-v5 key shape and
Policy semantics, solely so its derived score remains exactly reproducible.

**Complexity added:** one bounded currentness-pause branch in the existing runtime bucket owner, in
addition to the already-landed aligned-source timestamp tuple; one public CaseStore-owned
directory-name conversion function; one idempotent Candidate-lifecycle cleanup condition in the
existing owner; no new state owner, timer, schema, history, or baseline path.

**Complexity deleted:** the rotating five-phase sampling behavior, the wall-clock-ahead-of-source
anchor race, the misleading baseline source label, the destructive interpretation of a transient
ordered backlog as lost pre-confirmation evidence, and the offline report's duplicate Case identity
parser. It also deletes the score packet's ambient-context-dependent Decimal normalization.

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

## Change declarations

**Market/Decision input contract change:** five-minute index-chart samples remain fixed to the
source-confirmed UTC epoch grid. Ordered queue-lag currentness is a pre-activation observation pause,
not evidence that previously accepted observations disappeared; current score and admission truth
remain `UNKNOWN` until catch-up.

**Decision Policy change:** `NONE`; the three Policy artifacts and identities remain byte-exact.

**Outcome/evaluation contract change:** preserve raw score-packet Decimal precision so the existing
policy-aware Case validator can reproduce exact derived truth; no Outcome arithmetic or economic
definition changes. Episode retirement also reconciles an already-terminal attempt with its
still-valid Candidate; it creates no Outcome or durable Case.

**Stage/authorization change:** the last runtime stopped fail-closed after the interrupted-terminal
cleanup failure. The next bounded clean start on `127.0.0.1:8675` is authorized from the checked
follow-up repair, using the unchanged stable Case root from the non-temporary
`/Users/logan/Optimatrix-runtime` checkout. Continued
public-only observation runs until the first admitted active Shadow or a newly measured fixed
blocker is established. No private or execution permission is added.

## Scope

**In:** the sole runtime bucket-settlement owner and its queue-lag currentness transition; the
already-landed `IndexHistoryReducer` source-grid repair; the CaseStore-owned directory identity
conversion and read-only V2 report; lossless V2 packet Decimal serialization; focused
market/runtime/Workbench/Radar/Case/report tests; owning contracts, task, and Current Stage
authority; one bounded cutover and continued public-only observation.

**Out:** score weights, thresholds, TTE/Delta rules, confirmation counts or separations, preservation
of an already-active Episode, any Policy artifact, Underwriting or Position economics, Case schema,
state-root migration, private data, orders, fills, capital, process supervision, or a second
baseline path.

**Owning modules:** `apps/radar_runtime/src/radar_runtime/runtime.py`,
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
- fixed-attribution live evidence: cross queue currentness above five seconds and prove the frame is
  UNKNOWN/non-countable, adds zero `CORE_UNKNOWN` reset, and preserves accepted pre-confirmation
  through catch-up; keep any separate transport/session reset explicitly attributed;
- no manifest, receipt, commissioning subsystem, runtime self-acceptance, or host inspection.

## Definition of done

The rotating phase, source-ahead race, and queue-lag destructive pre-confirmation reset are
impossible by direct tests; the official reader accepts store-owned bare digest directories and
preserves their canonical prefixed Case identities; high-precision raw score inputs round-trip and
recompute exactly; the full repository gate passes; the live clean repair commit remains current;
threshold-crossing lag contributes zero observations while a same-truth recovery retains the prior
count; any first active admitted Shadow is verified through the API and official Case reader, or
the next truthful fixed funnel blocker is reported without changing Policy to manufacture
admission; the diff is bounded and remote state is exact.
