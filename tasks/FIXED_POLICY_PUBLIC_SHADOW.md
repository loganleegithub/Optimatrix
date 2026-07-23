# Task — Fixed-Policy Public Shadow

**Status:** ACTIVE

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md) `PUBLIC_SHADOW`

**Implementation contract:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `fb103f48d74eb084ad9bfc13df70984ce75a989f`

**Target branch/PR:** `codex/fixed-policy-public-shadow` / Draft PR to `main`

## Business closure

**Given:** before opening a network connection, one immutable
`FIXED_POLICY_PUBLIC_SHADOW_RUN` contract freezes the Decision input, deployed Policy, Outcome
contract, runtime-source identities, run schedule, twelve decision opportunities, single-exposure
admission rule, maturity rule, durability rule, and `NO_TRADE=0` comparator.

**When:** the Online Runtime executes that contract once against Deribit production-public facts,
accounts for every due slot, makes every event-backed Decision online, durably journals the
opportunity before it processes any later canonical event or closes a later slot, admits at most
one concurrent Shadow exposure, and observes every admitted Entry through a mature Outcome.

**Then:** exactly one immutable `SHORT_VOL_PUBLIC_SHADOW_RUN_RECEIPT` binds the complete opportunity
denominator, every Decision/admission/Entry/Outcome, all maturity partitions, descriptive
aggregates, the interleaved causal commit chain, sealed fact segments, anomalies, zero activity,
identities, and digests.

**Independent verification:** a fresh process reads only the pre-registered run contract,
append-only causal commit chain, sealed segments, online opportunity journal, and immutable
receipts; it reconstructs all twelve opportunities, every event-backed Decision, admissions,
Entries, Outcomes, maturity classifications, `NO_TRADE` comparators, aggregates, and the final Run
receipt with type-strict zero drift.

**Valid zero/UNKNOWN result:** every opportunity is classified as `OPPORTUNITY_UNKNOWN`,
`NO_ENTRY`, `ADMITTED`, or `CONCURRENCY_BLOCKED`. A run whose twelve opportunities are all
`OPPORTUNITY_UNKNOWN` or `NO_ENTRY` has zero Entry and zero Outcome and remains valid when the run
is otherwise complete.

**Valid failure result:** interruption, missing origin, an unsealed segment, a missing due
opportunity, or an admitted Entry without mature evidence produces a verifiable `complete=false`
prefix, not a successful Run receipt. The runtime may not resume or automatically retry that run.
Because no third-party attempt registry exists, the evidence explicitly reports
`attempt_selection_attested=false` and cannot prove that an external operator did not discard
another attempt.

## Change declarations

**Market/Decision input contract change:** APPROVED — add only the closure-scoped
`SHORT_VOL_PUBLIC_SHADOW_FACT_SEGMENT` and `SHORT_VOL_PUBLIC_SHADOW_CAUSAL_COMMIT` durability and
lineage contracts plus the pre-registered
`POST_ENTRY_AND_RECONNECT_PLATFORM_RESUBSCRIBE_THEN_STATUS` acquisition rule already authorized by
`CURRENT_STAGE`. Only latest-authoritative, request-correlated acquisition
acknowledgements/statuses materialize the existing canonical
`SUBSCRIPTION_START`/`PLATFORM_STATE` facts; they cannot change a frozen prior Decision, but by
`capture_seq` they do enter later DecisionFrames and may make later platform state `OPEN`,
`LOCKED`, or `UNKNOWN`. Superseded or uncorrelated responses become closure-owned
`PLATFORM_PROBE_RESPONSE_ANOMALY_COMMIT` control evidence and never canonical facts. Preserve every
existing canonical fact meaning,
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT` projection/readiness/missingness rule, and accepted
Decision receipt meaning. The accepted Decision runtime source digest
`eed711f1c924c73a0a61b562da5154873b40713f5b5e44c482882eecf7aee29c` is the baseline identity,
not a value that new source bytes may falsely retain. Because the required writer lives inside the
recursively scoped `market_tape` source tree, implementation must freeze and report the new
Decision runtime digest and prove zero semantic Decision drift on accepted sealed regression
inputs.

**Decision Policy change:** NONE — preserve
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY` and digest
`4b14a4a1a091a0530c43759f02f159592932efaf49fffe43a073d7062762a1ea`,
including every horizon, structure, formula, threshold, ranking, reserve, veto, and candidate
predicate.

**Outcome/evaluation contract change:** APPROVED — add only the run-level
`FIXED_POLICY_PUBLIC_SHADOW_RUN`, `SHORT_VOL_PUBLIC_SHADOW_OPPORTUNITY_RECORD`,
and `SHORT_VOL_PUBLIC_SHADOW_RUN_RECEIPT` semantics for cadence, admission/concurrency, opportunity
denominator, maturity, `NO_TRADE`, aggregate, durability, and replay. Preserve
`PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH` and every Entry/Outcome meaning. The accepted Outcome
runtime digest
`7fbb58658c1c86157e40d58b7315f015070f8c5fe1d70c6e002aa798fd955253` remains the historical
baseline, but the new `shadow_engine` source and CLI entry necessarily produce a new digest.
Implementation must report that new identity, prove zero semantic Outcome drift on accepted sealed
regression inputs, keep historical bundle bytes verifiable under their recorded source identity,
and never misrepresent different source bytes as a digest match.

**Stage/authorization change:** NONE — consume the already authorized bounded
`FIXED_POLICY_PUBLIC_SHADOW` closure inside `PUBLIC_SHADOW`. Do not authorize qualification,
Policy tuning, Challenger work, promotion, private/account data, execution, or capital. The
changes to `CURRENT_STAGE.md` and `SYSTEM_ARCHITECTURE.md` in this activation PR only clarify the
already authorized boundedness, causal durability, future-platform acquisition, final nonclosed
exposure, and attestation/non-proof boundaries; permission, implemented capability, stage, and
sole authorized closure do not change.

## Evidence boundary

**Proves:** one predeclared fixed-Policy run accounted for twelve production-public opportunities;
the identified runtime emitted a process witness and interleaved prefix-causal chain consistent
with each event-backed Decision being durably committed before later input; every admitted
exposure reached a mature classification under the accepted Outcome contract; and the complete
denominator is independently reconstructable.

**Does not prove:** real fills, continuous or service operation, Policy quality, profitability,
statistical significance, qualification versus `NO_TRADE`, Challenger superiority, promotion,
account behavior, execution, capital authority, externally witnessed physical fsync timing,
third-party proof that no post-run fabrication occurred, or that an external operator did not
discard another attempt.

**Evidence class:** `SYNTHETIC_LOGIC | BOUNDED_PUBLIC_CAPTURE | LIVE_REPLAY | SHADOW_OUTCOME`

## Scope

**In:** one pre-registered bounded run; twelve five-minute Decision slots; one-hour warm-up; one
single-exposure admission gate; strictly future Outcomes; complete maturity; contemporaneous
opportunity journaling; append-only segmented facts; interruption-evident prefixes; one Run
receipt; descriptive `NO_TRADE=0`; fresh-process replay; bundle, hashes, and Chinese report; and
non-expansive wording corrections in `CURRENT_STAGE.md` and `SYSTEM_ARCHITECTURE.md`.

**Out:** beyond the declared durability and probe-acquisition rule, changing canonical facts,
projection, readiness, Decision input, or Policy semantics; multiple simultaneous exposures;
adaptive cadence; retrying a missed slot; choosing a replacement run based on any observed result,
anomaly, readiness, `UNKNOWN` rate, activity, or PnL; generic storage; resume; daemon; database;
service; qualification; Challenger; promotion; private API; account; order; fill; execution;
capital; stage advancement.

**Owning module/artifact:** `market_tape` closure-owned segmented append-only fact writer;
`shadow_engine` pure run-level admission/maturity/aggregate contract;
`radar_runtime` bounded online schedule, composition, receipt, replay, and evidence bundle;
`SHORT_VOL_PUBLIC_SHADOW_RUN_RECEIPT`; plus the two authority documents named above for wording
clarification only.

## Contract

### Frozen run schedule

`RUN_CONTRACT.json` is written and fsynced before network acquisition. It freezes the schedule
formula, every semantic identity, `initial_setup_timeout_seconds=60`,
`network_open_timeout_seconds=10`, `network_retry_backoff_seconds=1`,
`maximum_network_retry_dispatch_latency_ms=1,000`, and
`maximum_opportunity_commit_latency_ms=5,000`. The setup deadline is the half-open invocation
interval `[0, 60,000)` milliseconds; a subscription fact with
`collector_elapsed_ms >= 60,000` is too late regardless of arrival/commit order. The concrete
`origin_elapsed_ms` is then fixed exactly once from the accepted
`INITIAL_REQUIRED_SUBSCRIPTIONS_PLUS_MAX_WINDOW` contract: the maximum
`collector_elapsed_ms` of the initial connection generation's `reference_price`,
`reference_trade`, and `platform_state` subscription-start facts. No other stream participates.

The pre-network contract also freezes
`runtime_environment_digest` over exact
`python_implementation=CPython`, `python_version=3.13.5`,
`python_cache_tag=cpython-313`, installed `websockets_version=16.1.1`, and the
`pyproject.toml` content digest. Capture and authoritative replay require type-strict equality of
those fields in addition to scoped source equality. OS and machine are reported as audit fields
but are not equality gates; static bundle-hash verification remains possible under a different
environment without becoming authoritative computation replay.

All three starts must exist strictly before the setup deadline. Failed WebSocket connect calls
before any established initial generation may retry under the frozen network-attempt loop without
moving that deadline. If any start is missing, or if the first successfully established initial
generation disconnects before origin, the runtime seals a verifiable `complete=false` prefix by
the deadline, does not enter the post-origin phase, emits no successful Run receipt, and does not
resume or automatically retry the Run. A reconnect never selects a new origin or moves a due
target. Thus network acquisition is bounded by at most `60 + 21,900 = 21,960` seconds of invocation
elapsed time before deterministic local finalization.

The schedule is:

```text
warm-up seconds              = 3,600
cadence seconds              = 300
due opportunity count        = 12
slot k target                = origin + 3,600s + k × 300s, k = 0..11
slot k interval              = [target_k, target_k + 300s)
decision phase end           = origin + 7,200s
maximum Policy horizon       = 14,400s
observation tail             = 300s
sealed run end target        = origin + 21,900s
```

The first canonical event in each half-open slot is its immutable Decision cutoff. One event
cannot fill multiple slots. If a slot contains no canonical event, its opportunity is
`OPPORTUNITY_UNKNOWN / NO_CANONICAL_EVENT_IN_SLOT`. A late event cannot backfill an earlier slot.
Missingness, reconnect, contamination, or an incomplete frame cannot move a target or trigger a
retry.

The invocation witness's monotonic elapsed clock, not the last canonical event, proves that the
production process remained alive through `origin_elapsed_ms + 21,900,000`. Sealed facts use the
half-open collector-elapsed interval ending at that target: events with
`collector_elapsed_ms < seal_end_elapsed_ms` are included, while events at or after the target are
excluded and cannot alter an Outcome. Last-event elapsed and any silent tail remain audit evidence,
not a duration gate. A requested duration alone is insufficient, and every admitted Entry still
requires its own qualifying post-horizon canonical observation for mature classification.

`final_event_capture_seq` is the greatest sequence among facts included before the half-open
endpoint. `final_decision_frame_capture_seq` is the sequence of the last DecisionFrame produced by
projecting those included facts, not the last due-slot cutoff. It must be
`<= final_event_capture_seq`; either field may be null only for an incomplete prefix with an exact
missing reason. Fresh replay reconstructs both values.

### Online known-at and opportunity journal

All canonical facts are processed once in increasing `capture_seq`. Every Decision uses only facts
with `capture_seq <= cutoff_capture_seq`. Before a canonical fact enters the projector, its
segment bytes and `FACT_COMMIT` are durable. After a slot cutoff or a no-event slot close, the
runtime writes and fsyncs exactly one `SHORT_VOL_PUBLIC_SHADOW_OPPORTUNITY_RECORD` and its
`OPPORTUNITY_COMMIT` before it may process the next canonical event or close a later slot. The
record contains:

- run, slot, target, interval, and cutoff identity or exact missing reason;
- rolling durable prefix/segment identity through the cutoff;
- causal commit ordinal, preceding fact-chain head, and preceding opportunity-journal head;
- Decision frame, receipt, action, readiness, input-contract, Policy, and runtime-source digests;
- admission classification and reason;
- any Entry receipt digest created at that slot;
- its own content digest.

For an event-backed slot, `opportunity_trigger_elapsed_ms` is the cutoff fact's persisted elapsed
value; for a no-event slot it is the half-open slot end. `opportunity_commit_elapsed_ms` is the
invocation-monotonic value immediately after the commit fsync. Both use the same persisted
monotonic domain. A negative latency is invalid and makes the Run incomplete. A latency above
5,000 milliseconds is a durably reported `OPPORTUNITY_COMMIT_LATENCY_BREACH` operational anomaly,
but does not invalidate a Run when the opportunity was still committed before every later
canonical fact and later-slot commit. This SLA does not override the causal known-at or complete
denominator requirements.

One append-only causal commit journal begins with a `RUN_CONTRACT_COMMIT`. Every WebSocket
`connect` call is then bracketed by a `NETWORK_OPEN_INTENT_COMMIT` fsynced before the call and a
`NETWORK_CONNECT_RESULT_COMMIT` for exact success/failure before any later connect call or
canonical network fact. Each pair binds the global `network_attempt_ordinal`, purpose, pending
connection generation, scheduled/actual elapsed values, timeout, result/error, and preceding
causal head. The journal otherwise interleaves `FACT_COMMIT`, `ORIGIN_COMMIT`,
`OPPORTUNITY_COMMIT`, semantic platform-probe control commits, and `SEGMENT_SEAL_COMMIT` records
under strictly increasing ordinals and a single previous-commit digest. An intent structurally
binds the contract before its connection call in the process witness; it is not external timing
attestation. `ORIGIN_COMMIT` binds the three exact initial subscription fact commits and all
derived targets before any later fact is processed. Every `FACT_COMMIT` binds its canonical fact
digest, segment byte range, latest durable opportunity-journal head, and latest platform-probe
control head. Every `OPPORTUNITY_COMMIT` binds its opportunity/receipt byte ranges, the fact-chain
head through its cutoff, and the preceding opportunity head. Every `SEGMENT_SEAL_COMMIT` binds the
segment manifest plus current opportunity and platform-probe heads. Referenced payload bytes are
fsynced before their commit record, and each commit record is fsynced before the next ordinal is
allowed. Therefore two merely self-consistent final trees are insufficient: any later fact or
segment seal must cross-bind every opportunity and probe-control transition that was due before
it.

All timer/fact ties use invocation monotonic elapsed plus this fixed order:

1. close and commit every earlier no-event slot whose half-open interval ended;
2. commit network-attempt timeout/retry transitions due at that elapsed value;
3. commit platform-probe timeout/retry transitions due at that elapsed value;
4. seal and commit every segment whose half-open interval ended;
5. append and commit the boundary event in the new segment;
6. process that event as the new slot cutoff and/or platform-probe evidence.

The setup deadline and normal sealed-run end are hard cutoffs: their timer transition and final
segment seal occur before any fact with elapsed time at the boundary, so that fact is excluded.
Within step 6, an Entry-creating fact is processed in this exact order: apply any old-exposure
exit, freeze the Decision, commit opportunity/Entry, commit the new probe obligation, then commit
and perform attempt 0 using its actual invocation-monotonic elapsed values before any later
canonical fact. Its due time is the obligation time, but its recorded send/result times are never
forced equal to that trigger or backdated. A reconnect-triggering fact instead commits barrier
invalidation for global projection and starts the network-attempt loop. Only when
`current_open_exposure_count=1` does it additionally commit a new Entry-bound probe obligation;
with zero open exposure it must not create one. The runtime then fsyncs the reconnect
`NETWORK_OPEN_INTENT_COMMIT` before the connection call and records
`NETWORK_CONNECT_RESULT_COMMIT` at its actual elapsed value. After each failure, later calls follow
the same bounded network-attempt loop; they do not require or fabricate another reconnect fact.
After successful connection establishment, the full bootstrap may satisfy Entry-bound attempt 0
only when its actual send-intent/result occur inside that attempt's half-open timely interval;
otherwise the fixed missed-deadline rule applies. A newly created attempt is not deferred merely
because the global timer phase for its due elapsed value already ran.

Final sealed receipts may be materialized after capture, but must reconstruct and bind the online
record byte-for-byte. The shipped runtime has no successful batch path that can substitute for the
causal journal and process witness. Replay verifies prefix causality and witness self-consistency;
without an external timing witness, it does not independently prove the physical fsync instant or
rule out an operator fabricating an entirely new self-consistent artifact after the run.

### Admission and concurrency

The run permits at most one actual Shadow exposure that has not reached an executable actual exit.
It starts with `initial_open_exposure_count=0`. Every due opportunity has exactly one mutually
exclusive admission class:

```text
OPPORTUNITY_UNKNOWN
NO_ENTRY
ADMITTED
CONCURRENCY_BLOCKED
```

- incomplete Decision or binding evidence is `OPPORTUNITY_UNKNOWN`;
- complete `WATCH` or `ABSTAIN` is `NO_ENTRY`;
- complete `RESEARCH_CANDIDATE` with empty capacity is `ADMITTED`;
- complete `RESEARCH_CANDIDATE` while an existing exposure remains open is
  `CONCURRENCY_BLOCKED`; the immutable Decision action remains `RESEARCH_CANDIDATE`;
- receipt/frame/Policy/sequence drift is a run error, not another scan opportunity.

For a `complete=true` run, the following accounting identities are exact:

```text
OPPORTUNITY_UNKNOWN + NO_ENTRY + ADMITTED + CONCURRENCY_BLOCKED = 12
event_backed_decision_count + no_event_slot_count = 12
RESEARCH_CANDIDATE + WATCH + ABSTAIN action count = event_backed_decision_count
RESEARCH_CANDIDATE action count = ADMITTED + CONCURRENCY_BLOCKED
incomplete_event_backed_opportunity_count + no_event_slot_count = OPPORTUNITY_UNKNOWN
complete WATCH/ABSTAIN count = NO_ENTRY
Entry count = ADMITTED
Outcome count = Entry count
MATURE_CLOSED + MATURE_UNEXITABLE + MATURE_UNKNOWN + IMMATURE_UNKNOWN = Entry count
IMMATURE_UNKNOWN = 0
final_open_exposure_count =
    MATURE_UNEXITABLE + MATURE_UNKNOWN + IMMATURE_UNKNOWN <= 1
MATURE_CLOSED + final_open_exposure_count = Entry count
NO_TRADE comparator count = 12
maximum concurrent actual Shadow exposure count <= 1
```

An incomplete prefix reports the same fields for its durable prefix but may not claim these
complete-run equalities. `UNEXITABLE`, `UNKNOWN`, and immature do not invent an executable exit;
their actual exposure remains open at the sealed end and blocks later admission.

At a slot cutoff, the runtime first applies that canonical event to any existing exposure and
freezes any executable exit, then evaluates the same-prefix Decision and applies admission. An old
exposure may exit and a new Entry may begin at the same `capture_seq`, but their actual exposures
must not overlap. The event is current Entry evidence for the new position, never future Outcome
evidence for it. Every new Entry still requires a strictly later connection-scoped platform
subscription/status barrier before any executable close.

All canonical events, including events outside Decision slots, continue to update the one active
actual-exposure Outcome path under the accepted Outcome Truth contract. Each exited Entry's
Outcome is frozen independently; any retained post-exit counterfactual remains separately labeled
and bound to that Entry. A later Entry creates a new path and never overwrites an earlier Outcome.

### Network-attempt lineage and recovery

The collector's network-recovery loop is run-level transport behavior, not one of the three
future-platform probe attempts. It is frozen as:

```text
network_open_timeout_seconds = 10
network_retry_backoff_seconds = 1
maximum_network_retry_dispatch_latency_ms = 1,000
```

Every WebSocket connection call receives one global, strictly increasing
`network_attempt_ordinal` and exactly one purpose, `INITIAL_SETUP` or `RECONNECT`. Its durable
intent/result pair binds the pending connection generation, due elapsed value, actual intent and
result elapsed values, effective timeout, success or normalized failure, and preceding causal
head. The first initial call is due when its pre-connection public inputs are ready; the first
reconnect call is due at the reconnect trigger. A retry is due exactly 1,000 milliseconds after
the preceding failed result. An intent may not precede its due time. A dispatch outside
`[due_elapsed_ms, due_elapsed_ms + 1,000)` records `NETWORK_RETRY_DISPATCH_LATE` at its actual
elapsed value as an operational anomaly and continues recovery when time remains; it is never
backdated. Missing intent/result lineage remains incomplete evidence.

An initial call uses pending generation 1. Repeated failures before any established connection
retain that generation and increment only `network_attempt_ordinal`. The first successful result
promotes pending generation 1 to the established initial generation. If that established
generation is then lost before origin, initial setup fails closed as specified above rather than
mixing subscription starts across generations. Before an established generation exists, the
initial loop continues under the frozen backoff until success or the setup deadline; stopping
after a recorded failure while another timely call remained possible is an incomplete
network-attempt sequence and cannot produce a successful Run receipt.

After origin, loss of one established connection emits exactly one canonical `RECONNECT` fact,
invalidates that generation, and creates pending generation `previous_successful_generation + 1`.
Every failed connect call for the same outage retains that pending generation and emits no new
`RECONNECT` fact. Only a successful `NETWORK_CONNECT_RESULT_COMMIT` promotes it; canonical
bootstrap facts then carry that established generation. A later loss starts a new outage, emits
one new `RECONNECT` fact, and creates the next pending generation.

No connect call starts at or after the applicable setup or sealed-run deadline. Its effective
timeout is the lesser of 10,000 milliseconds and the remaining time to that deadline; an
in-flight call is cancelled or timed out, and its result is committed, before the boundary's
failure transition or final segment seal. The post-origin loop continues under the frozen backoff
until successful recovery or the sealed-run end even after every platform-probe attempt has
expired and even when no exposure is open, because later Decisions still consume canonical
connection state.

A successful reconnect bootstrap inside attempt 0's timely interval may satisfy that attempt. A
later success is labeled `NETWORK_RECOVERY_BOOTSTRAP`, never retroactively counted as attempt 0 or
used to repair `MISSED_DEADLINE`. Its latest-authoritative request-correlated platform pair
nevertheless remains valid for later Decisions and for a still-open Entry's Outcome barrier under
the unchanged strict-future rule.

### Active future platform acquisition

Outcome barrier validity and acquisition SLA are separate. Under the unchanged Outcome Truth
contract, any durably request-correlated pair qualifies when its accepted `platform_state`
subscription-start and later canonical `public/status` are both strictly after Entry, in the
current connection generation, and the start remains the latest authoritative platform start
through the status response. The pair may come from the dedicated platform-only probe, the normal
reconnect bootstrap, later network-recovery bootstrap, or another predeclared collector
subscription path. A faithfully recorded timeout, send failure, or no-active-connection attempt
is an honest SLA result and does not by itself make the Run incomplete. A durably recorded
`MISSED_DEADLINE` or `OMITTED_BEFORE_LATER_FACT` is an operational anomaly when actual elapsed
time, canonical known-at order, and the opportunity denominator remain intact; an unrecorded or
backdated transition remains incomplete. None can veto an otherwise valid pair, erase an
executable exit, or alter its Outcome receipt.

Every `ADMITTED` Entry creates one acquisition obligation after its Entry/opportunity commit.
Every reconnect while actual exposure remains open invalidates the old-generation barrier and
creates a new-generation obligation. On an uninterrupted Entry, attempt 0 is an immediate
`platform_state`-only resubscribe, recorded at its actual elapsed value. On reconnect, the
obligation and reconnect network-open intent are immediate, but the normal full reconnect
bootstrap—including its `platform_state` subscription and correlated status request—is generation
attempt 0 only after the connection is established and only within that attempt's timely
interval. If connection succeeds later, the same bootstrap is transport recovery rather than a
catch-up probe attempt. An additional platform-only request is not required at a due time when any
eligible bootstrap already supplies a valid pair. Attempts 1 and 2 are platform-only fallbacks.
The Run contract freezes
`future_platform_probe_contract=POST_ENTRY_AND_RECONNECT_PLATFORM_RESUBSCRIBE_THEN_STATUS` and,
on the same persisted invocation-monotonic clock as the facts:

```text
probe_retry_interval_seconds = 60
probe_attempt_timeout_seconds = 60
maximum_probe_attempts_per_entry_generation = 3
attempt i due = obligation_created_elapsed_ms + i × 60,000, i = 0..2
attempt i deadline = attempt_i_due_elapsed_ms + 60,000
timely send/skip commit interval = [attempt_i_due_elapsed_ms, attempt_i_deadline_elapsed_ms)
timely pair interval = [attempt_i_due_elapsed_ms, attempt_i_deadline_elapsed_ms)
```

Each obligation, send, acknowledgement, status, generation, timeout, and exact source sequence is
durable evidence in the same causal commit chain:

1. After the triggering `OPPORTUNITY_COMMIT`, or after processing a reconnect `FACT_COMMIT` for an
   open exposure, `PLATFORM_PROBE_OBLIGATION_COMMIT` binds the deterministic obligation ID, Entry
   or reconnect trigger, `obligation_created_elapsed_ms`, generation, all attempt due/deadline
   values, and whether attempt 0 is `PLATFORM_ONLY` or `RECONNECT_BOOTSTRAP`.
2. Every eligible collector subscription send receives a monotonic
   `platform_acquisition_ordinal`. At each due time with no current valid pair, the exact
   reconnect-bootstrap or `public/subscribe {"channels":["platform_state"]}` request is bound by a
   fsynced intent commit before send and an exact local result commit before any later fact.
   `send_intent_elapsed_ms` is the actual invocation-monotonic value at that commit and is never
   backdated. The intent and send are valid only in that attempt's half-open timely interval. A
   crash with intent but no result is incomplete evidence, not an attempt. A valid pair already
   present at a due time creates a durable `SKIPPED_PAIR_ALREADY_VALID` state, committed in the
   same timely interval, instead of another request. If no connection is active at the due time,
   the runtime instead commits `FAILED_NO_ACTIVE_CONNECTION` in the same interval; this is an
   accounted failed attempt, not a fabricated send, and it does not stop the independent network
   recovery loop.
3. A request-correlated acknowledgement becomes the existing canonical `SUBSCRIPTION_START` only
   when its acquisition ordinal is not older than the current authoritative platform-start
   ordinal. Its `FACT_COMMIT` atomically supersedes lower ordinals and binds the generation,
   subscription request/result, and obligation. A lower-ordinal late acknowledgement is raw
   anomaly evidence, not a canonical fact. A higher-ordinal send intent alone does not supersede
   the current authoritative start.
4. Only after an authoritative acknowledgement fact is durable,
   `PLATFORM_STATUS_SEND_INTENT_COMMIT` binds that start sequence, a new request ID, and exact
   `public/status {}` parameters before the second RPC; its result commit precedes any later fact.
   The correlated status response becomes canonical only if that start is still the latest
   authoritative start and no reconnect intervened.
5. A delayed, superseded, unsolicited, or uncorrelated acknowledgement/status does not receive a
   canonical event kind. `PLATFORM_PROBE_RESPONSE_ANOMALY_COMMIT` preserves its raw
   digest/content, request lineage, receive elapsed, and rejection reason without entering a fact
   segment or projector. `PLATFORM_PROBE_STATE_COMMIT` records every timeout, send failure,
   satisfaction, skip, supersession, reconnect invalidation, and seal state.

A timeout or send failure is an attempt/SLA state, never a sticky Outcome conclusion. A later valid
pair from any eligible durable collector send immediately restores platform eligibility; the next
close observation is independently evaluated and may become the first executable exit. At each
fixed due time, a still-invalid barrier triggers the corresponding attempt even if an earlier
request remains outstanding. At seal, every due attempt is accounted for as sent, failed, skipped
because a valid pair already existed, or `PENDING_AT_SEAL` only when it has a send-result commit and
`seal_end_elapsed_ms < attempt_deadline_elapsed_ms`; equality processes timeout first. Missing a
due intent/result makes the Run incomplete, but does not rewrite a valid Outcome.

If the event loop, connection, or RPC path wakes at or after one or more attempt deadlines, the
runtime first accounts for elapsed attempts in ordinal order before it processes any later fact.
An attempt without a timely send-intent or timely skip commit becomes `MISSED_DEADLINE`, committed
at the actual wake elapsed value; it is never catch-up sent, backdated, or counted as timely. The
runtime may then send only the single attempt whose half-open timely interval is currently active.
If every interval has elapsed, it records every missing attempt as `MISSED_DEADLINE` without a
send. Each durably recorded missed deadline remains an operational anomaly, while a separately
valid future platform pair retains its Outcome eligibility. Tests inject one- and multi-deadline
wakeups and prove that neither backfill nor compressed catch-up traffic is fabricated.

Authoritative acquisition facts follow the unchanged projection rules and are visible to later
slots in `capture_seq` order without altering Entry or a frozen prior Decision. Control-anomaly
commits never enter Decision/Outcome projection. Tests cover uninterrupted Entry, reconnect
bootstrap recovery, timeout/send failure followed by later executable close, valid Outcome despite
a separate probe-SLA failure, old/new ACK/status reordering, raw anomaly retention, unchanged
canonical counts, and no Decision/Outcome contamination. Acquisition does not move a Decision
slot, retry admission, extend the sealed end, or authorize another run.

### Maturity

Run-level maturity is separate from `OutcomeStatus` and uses exactly:

```text
MATURE_CLOSED
MATURE_UNEXITABLE
MATURE_UNKNOWN
IMMATURE_UNKNOWN
```

- a valid executable actual exit produces `MATURE_CLOSED`, including an exit before horizon;
- a nonclosed Entry can mature only with at least one canonical observation at or after
  `entry_elapsed_ms + frozen_horizon_ms`;
- horizon arms exit but temporary `UNKNOWN` or `UNEXITABLE` remains non-terminal under the accepted
  Outcome Truth rule; the path continues to the first later executable exit or sealed data end;
- at sealed data end, the last qualifying post-horizon observation supplies
  `MATURE_UNEXITABLE` or `MATURE_UNKNOWN`;
- without a qualifying post-horizon observation, the Entry is `IMMATURE_UNKNOWN` even when wall or
  invocation time passed the target;
- `MATURE_UNKNOWN` and `IMMATURE_UNKNOWN` remain distinct counts;
- `UNEXITABLE`, `UNKNOWN`, and immature observed PnL are null.

A successful `complete=true` Run receipt requires `IMMATURE_UNKNOWN=0`. A verifiable incomplete
prefix may report immature Entries but cannot satisfy the business closure.

### `NO_TRADE=0`

Every pre-registered slot has exactly one contemporaneous, identity-bound `NO_TRADE` comparator:

- comparator count is exactly twelve;
- exposure, fee, and PnL are definitionally zero because no position exists;
- this zero never comes from missing market evidence;
- Fixed-Policy `UNKNOWN`, `UNEXITABLE`, and immature PnL remain null and may not use zero or maximum
  loss;
- aggregates may report only a `CLOSED` observed-PnL subtotal plus every null-result count; if any
  strategy result is null, no complete strategy total-return claim may be emitted;
- the comparator is descriptive only, not qualification, pass/fail, promotion evidence, or Policy
  feedback.

### Incremental durability and interruption

The closure adds no database or service. It uses a fresh run directory and closure-owned
append-only files:

- pre-network `RUN_CONTRACT.json` plus content digest and invocation witness;
- canonical fact segments on fixed maximum 300,000-millisecond invocation-monotonic windows;
- one append-only opportunity journal;
- one append-only interleaved causal commit journal;
- immutable Decision, Entry, Outcome, and final Run receipts;
- segment and final manifests plus checksums.

The segment clock uses the same persisted monotonic domain as `collector_elapsed_ms`. Starting at
invocation elapsed zero, segment `n` owns
`[n × 300,000, (n + 1) × 300,000)` milliseconds, capped by the exact normal sealed-run end or an
earlier failure-prefix cutoff such as the setup deadline. Rotation is driven by that monotonic
timer, not by arrival of a market event. Every fully elapsed window is sealed:
an event-free window has `record_count=0`, null first/last `capture_seq`, the canonical empty
payload digest, and a timer seal witness; it may not silently disappear. The final capped window
may be shorter than 300,000 milliseconds and ends exactly at its normal target or explicit
failure-prefix cutoff. Events at or after that endpoint do not enter the segment.

Every sealed segment binds its planned start/end, timer seal witness, first/last `capture_seq`,
record count, byte size, SHA-256, previous segment digest, run contract digest, and runtime
identities, plus the terminal causal-commit ordinal/digest and current opportunity-journal head.
Sequence, time-window, causal-commit, and segment-chain continuity are mandatory. The triggering
canonical fact and its opportunity record are fsynced before the runtime may process any later
canonical event or close a later slot. An active segment is explicitly partial and becomes
immutable only after normal sealing. Payload bytes without a corresponding durable causal commit
are an orphan tail: verification reports and excludes them, and they prevent `complete=true`.

On interruption, verification reports the last durable sequence, sealed segment chain, partial
segment, recorded/missing slots, open Entries, and maturity gaps. It may verify only a continuous,
parseable prefix. It may not resume the same run, fabricate an in-memory tail, issue a complete Run
receipt, or automatically retry/select another run based on any observed result, anomaly,
readiness, `UNKNOWN` rate, activity, or PnL.

The runtime may retain only the bounded current projector/Outcome state required for online
processing; it may not keep the complete event set in memory and defer durable writing until exit.
The process witness records each successful fsync/commit ordinal on the invocation monotonic
domain. Its final invocation record binds the run-contract digest, endpoint, requested setup/hard
stop, invocation elapsed, Git/source identities, terminal causal-commit digest, segment-manifest
digest, opportunity-journal head, final receipt or incomplete-prefix identity, and process result.
Standalone replay may set `collector_witness_verified=true` only after those exact bindings
reconstruct. Verification can establish the witness and chain's internal consistency, but
`online_persistence_external_attested=false` remains mandatory because no external timestamp or
storage attestor observes the physical write.

### Run receipt and replay compatibility

`SHORT_VOL_PUBLIC_SHADOW_RUN_RECEIPT` binds:

- run contract, invocation witness, exact runtime-environment fields/digest, origin, schedule,
  seal target, and completion;
- setup deadline, initial required-stream generation, origin establishment or exact failure;
- every network-attempt ordinal, purpose, pending/established generation, due and actual
  intent/result elapsed values, effective timeout, normalized result, retry-dispatch breach, and
  outage/reconnect lineage;
- Decision input, Policy, Outcome, and Run runtime-source identities/digests;
- complete causal commit/segment chains, opportunity journal, final capture seal, and checksums;
- every opportunity trigger/commit elapsed value, latency, and any 5,000-millisecond breach;
- final included event and final projected DecisionFrame sequences or exact prefix-missing reasons;
- all twelve slot/cutoff or missing identities and each corresponding Decision receipt digest or
  explicit no-Decision reason;
- every admission class/reason and Entry/Outcome receipt digest;
- strict Entry/Outcome causality and future platform barriers;
- every per-Entry and post-reconnect future-platform probe obligation, subscribe/status request
  IDs and actual send/skip commit elapsed values, intent/result commits, missed deadlines,
  acknowledgement/status correlation, timeout, generation, and source sequence;
- every superseded/uncorrelated platform response anomaly commit, raw-content digest, lineage, and
  rejection reason;
- the four maturity partitions;
- twelve `NO_TRADE=0` comparator records;
- initial/open exposure, action, candidate, admission, Entry, Outcome, and zero-activity counts
  plus every complete-run accounting identity;
- gaps, reconnects, platform state, source-time, interruption, and durability anomalies;
- descriptive `CLOSED` PnL subtotal and null-result counts;
- its own content digest, `external_source_attested=false`, and
  `attempt_selection_attested=false`;
- `online_persistence_process_witness_verified=true` only when its causal chain and process witness
  verify, while always preserving `online_persistence_external_attested=false`.

The Run contract owns
`OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_ONLINE_RUNTIME_SOURCE`, computed from sorted path/content
hashes of the four domain packages, the exact `radar_runtime` modules imported by capture,
composition, and replay, plus exact `pyproject.toml` bytes. Offline bundle/report code is excluded
from that identity and separately owns
`OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_OFFLINE_REPORT_SOURCE`. The report identity composes the
frozen online-runtime digest with the exact offline bundle/CLI and bounded `offline_audits` file
hashes and is bound by the bundle manifest, not the pre-network Run contract or Run receipt. Thus a report-only change cannot
impersonate or churn online runtime identity, while authoritative report reconstruction still
requires its exact report identity. Static bundle/hash verification under a different report
identity remains non-authoritative and does not claim report reconstruction.

The frozen Decision and Outcome source digests remain independently authoritative. Replay may
occur at a different audit Git commit only when every scoped online source digest and the frozen
runtime-environment digest are unchanged; any in-scope dirty path, source-content change,
interpreter mismatch, or runtime-dependency mismatch fails closed.
Historical Decision Truth and Outcome Truth bundles remain byte-valid under their recorded
identities; execution replay requires those exact scoped source bytes and environment, and a later
audit commit may not impersonate them with a different digest.

The mandatory historical semantic-regression anchor is the human-accepted Outcome Truth artifact
from implementation commit `62f9453503bf585a1c0aa891d40c69f90c02e83a`:

```text
archive SHA-256 =
c3099dfa62575a66854f8d66f1c5a2d0c9701bb445b7ac91a27f7db56e56bcd3
Decision runtime digest =
eed711f1c924c73a0a61b562da5154873b40713f5b5e44c482882eecf7aee29c
Outcome runtime digest =
7fbb58658c1c86157e40d58b7315f015070f8c5fe1d70c6e002aa798fd955253
Decision input contract digest =
31b2409cea15f748f37c0cc971941c548bea4f546a0234fad4f3957324d90fae
Policy digest =
4b14a4a1a091a0530c43759f02f159592932efaf49fffe43a073d7062762a1ea
Outcome contract digest =
396f01420fdee0561e5c7b1b083028c678006aacbc0f1a492fd6bc1436f3907b
```

Static verification under the new commit must validate that archive's bytes, manifest,
`SHA256SUMS`, sidecar, and canonical report. Historical execution replay must use an isolated clean
checkout of the exact old source commit/digests. Normal authoritative `replay` never crosses a
source-digest mismatch and must reject this old archive under new scoped source bytes.

Only the separate `semantic-regression` command may evaluate the accepted synthetic and
production-public sealed facts with the new source. It emits
`receipt_type=NON_AUTHORITATIVE_HISTORICAL_SEMANTIC_REGRESSION` and
`authoritative_replay=false`; it cannot set `computation_reconstructed=true`, validate or replace
the old collector witness/receipts, or satisfy current Run replay acceptance. It compares only a
frozen semantic projection: frame facts/completeness, action/reason/candidates, admission, Entry
economics/quantity/fees/maximum loss and causal sequences, Outcome status/exit reason,
actual/counterfactual path values, close economics/PnL/nulls, and exact missing reasons. Git/source
identity fields and content digests that transitively bind those identities are excluded from that
semantic projection. Both `decision_semantic_drift_count` and
`outcome_semantic_drift_count` must be type-strict integer zero; selecting a different convenient
fixture is forbidden.

Fresh replay reports type-strict:

```text
schedule_drift_count
fact_drift_count
decision_drift_count
admission_drift_count
entry_drift_count
outcome_drift_count
maturity_drift_count
no_trade_drift_count
aggregate_drift_count
run_receipt_drift_count
```

Every count must be integer zero. Replay separately reports
`computation_reconstructed=true`, `prefix_causality_verified=true`,
`collector_witness_verified=true`, `runtime_environment_match=true`, and
`external_source_attested=false`. It also preserves `attempt_selection_attested=false`; replay
cannot upgrade an unattested external-attempt history. It reports
`online_persistence_process_witness_verified=true` only after cross-chain validation and always
reports `online_persistence_external_attested=false`.

## Acceptance

### Direct behavior

1. The twelve exact slot targets and half-open selection rule are fixed before results; no event,
   reconnect, missing frame, or better later market can move or refill a slot. Setup either fixes
   origin within 60 seconds or seals an incomplete prefix and exits.
2. Every due opportunity's fact and opportunity commits precede any later fact/slot commit in the
   interleaved chain. Fresh replay verifies prefix causality and process-witness consistency; the
   shipped runtime has no successful post-run batch substitute, while external physical-write
   timing remains explicitly unattested. A positive commit latency above the frozen
   5,000-millisecond SLA is reconstructed as an anomaly without invalidating an otherwise causal,
   denominator-complete Run; a negative latency or broken ordering remains incomplete. Injected crashes after
   payload-before-commit, fact-before-opportunity, and opportunity-before-next-fact preserve only
   the valid durable prefix and cannot complete the run.
3. The four admission classes partition all twelve opportunities. Concurrency blocking preserves
   the original candidate Decision, and same-sequence exit-before-admission never overlaps
   exposures or leaks Entry facts into the new Outcome. Initial exposure is zero, Entry count
   equals admitted count, complete-run Outcome count equals Entry count, and maturity counts sum
   exactly to Entry count. Final open exposure equals all non-`CLOSED` maturity counts and is at
   most one.
4. Every admitted Entry is assigned exactly one maturity class. Mature and immature UNKNOWN remain
   distinct; a complete Run has zero immature Entries.
5. After every admission, and after every reconnect while exposure remains open, the normal
   collector actively attempts and durably records the required future platform pair.
   Uninterrupted single-Entry, sequential multi-Entry, reconnect, timeout/send-failure followed by
   later recovery, uncorrelated/delayed status rejection, omitted-probe, and probe
   pending/reset/status effects on later DecisionFrames are tested. One- and multi-deadline late
   wakeups record actual elapsed values, never backdate or catch up expired attempts, and remain
   explicit operational anomalies. Superseded raw responses remain auditable without changing
   canonical counts or projections. Repeated connect failures for
   one outage retain one pending generation, every connect call is intent/result bracketed, a late
   retry-dispatch is an explicit anomaly, and the bounded recovery loop continues
   independently of probe exhaustion through success or the hard cutoff. A late successful
   bootstrap is not a catch-up attempt but may still supply valid latest-authoritative facts and
   an Outcome barrier.
6. Only executable close observations populate strategy PnL. Only the no-position comparator is
   zero; incomplete, unexitable, or immature strategy results remain null.
7. Segment truncation, duplication, reordering, missing zero-record windows, cross-chain breaks,
   altered recorded commit order, in-memory tail substitution, receipt rehashing, and same-run-id
   substitution all fail verification. The receipt remains explicit that external timing and
   attempt selection are unattested.
8. Fresh replay reconstructs every fact, receipt, partition, aggregate, and digest with all ten
   drift counts equal to type-strict integer zero.
9. Historical semantic regression uses only the frozen accepted archive/source anchor and reports
   both semantic drift counts as type-strict integer zero in a non-authoritative receipt. It never
   relaxes normal replay: same scoped source bytes at a different Git commit still verify, while
   changed scoped bytes or runtime-environment identity fail closed.
10. Zero candidates, zero Entries, all UNKNOWN, and no observed strategy PnL remain valid when the
   complete denominator, maturity, and evidence contract are satisfied.

### Required commands

- `make UV='python3 -m uv' sync`
- focused tests: `.venv/bin/python -m pytest tests/test_public_shadow_run.py
  tests/test_public_shadow_durability.py tests/test_outcome_shadow.py`
- `make check`
- deterministic synthetic run: `.venv/bin/optimatrix-shadow-run synthetic --output
  <fresh-synthetic>`
- synthetic replay: `.venv/bin/optimatrix-shadow-run replay <fresh-synthetic> --output
  <fresh-synthetic-replay>`
- production-public run: `.venv/bin/optimatrix-shadow-run capture --output <fresh-public>`
- public replay: `.venv/bin/optimatrix-shadow-run replay <fresh-public> --output
  <fresh-public-replay>`
- historical semantic regression: `.venv/bin/optimatrix-shadow-run semantic-regression
  --accepted-outcome-bundle <accepted-outcome-bundle> --output <fresh-semantic-regression>`
- bundle and verification: `.venv/bin/optimatrix-shadow-run bundle ... --output <stable-bundle>`
  then `.venv/bin/optimatrix-shadow-run verify-bundle <stable-bundle>`

The deterministic synthetic success fixture has exactly twelve opportunities, at least two
sequential `ADMITTED → MATURE_CLOSED` Entries, at least one `CONCURRENCY_BLOCKED` opportunity while
the first exposure is open, at least one no-event `OPPORTUNITY_UNKNOWN` slot, and a same-sequence
old-exit-before-new-admission transition. At least one horizon first observes `UNKNOWN` or
`UNEXITABLE` and then uses the first later executable close; every Entry has its own strict-future
platform pair. All complete-run accounting identities hold, zero `NO_TRADE` is distinct from null
strategy PnL, and all ten replay drift counts are type-strict integer zero. Direct tests separately
cover terminal `UNKNOWN`, terminal `UNEXITABLE`, interruption, setup timeout, omitted platform
probe, one and multiple failed connection calls in one pending generation, retry-dispatch
lateness as anomaly, hard-cutoff connect cancellation, late network recovery after probe exhaustion, and
silent head/tail behavior.

### Real evidence

**Required:** YES

**Environment and minimum duration:** one fresh Deribit `production_public` run with no credentials
or private API. It must establish `origin_elapsed_ms`, record all twelve due slots, continue through
`origin + 21,900 seconds`, seal every segment, and mature every admitted Entry. Invocation elapsed
must additionally include initial setup before origin, which either succeeds within 60 seconds or
seals an incomplete prefix. No platform probe extends the fixed end. A zero-Entry run remains
valid.

**Required report:** pre-registered contract, source and runtime-environment identities;
invocation/origin/schedule/seal times; causal commit/segment chain, per-opportunity commit latency,
and fsync/journal process evidence; every network-attempt ordinal/purpose/pending generation,
due/actual elapsed value, timeout/result, retry-dispatch breach, and outage lineage; records and
actual public trades; `final_event_capture_seq` and `final_decision_frame_capture_seq`;
coverage/readiness; gap/reconnect/platform/source/durability anomalies; every slot target/cutoff or
missing reason; action/candidate/admission/Entry/Outcome counts including zero; concurrency and all
four maturity partitions plus final open exposure; every platform-probe
obligation/attempt/subscribe/status request correlation/pair/generation/timeout, actual send/skip
commit elapsed value, and missed-deadline state; twelve `NO_TRADE` comparators;
superseded/uncorrelated response-anomaly counts and digests; observed `CLOSED` PnL subtotal and
null counts; all
receipt/source/contract/capture digests; ten replay drift layers plus
the two historical semantic drift counts and
`NON_AUTHORITATIVE_HISTORICAL_SEMANTIC_REGRESSION / authoritative_replay=false`; collector
witness; external-source, online-persistence, and attempt-selection limitations; and every
non-claim.

**Private API:** FORBIDDEN.

## Artifacts and delivery report

**Capture/receipt/replay paths and hashes:** retained outside the repository in one
`OPTIMATRIX_FIXED_POLICY_PUBLIC_SHADOW_EVIDENCE_BUNDLE` with distinct deterministic-synthetic and
production-public run/replay subtrees, a distinct non-authoritative historical-semantic-regression
subtree, contract, invocation witness, sealed segments, opportunity journal, causal commit journal,
immutable receipts, `BUNDLE_MANIFEST.json`, `SHA256SUMS`, archive sidecar, and canonical
`ACCEPTANCE.zh-CN.md`. Large facts are never committed.

**Policy/contract identities:** `DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`,
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY`, `PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH`, and
`FIXED_POLICY_PUBLIC_SHADOW_RUN`; exact content digests are frozen before results.

**Commit/PR:** implement, verify, and push only `codex/fixed-policy-public-shadow`; maintain one
Draft PR to `main`; stop before readiness, merge, task archival, authority advancement, or the
queued Challenger/qualification closure.

**Unknowns and non-claims:** public quotes are not fills; a completed zero run is not failure; an
incomplete prefix is not a completed run; replay equality proves reconstruction only; descriptive
`NO_TRADE=0` is not qualification; no result proves Policy quality, profitability, account
behavior, execution, capital authority, third-party source provenance, externally witnessed
pre-network/fsync timing, or the absence of externally discarded attempts.

## Parallel bounded governance addendum — Identity and operational SLA

This branch narrows provenance and failure governance without changing market facts, Decision
behavior, Entry/Outcome meaning, or permission.

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE

The Online Runtime and offline report have separate content identities. A report-only source
change cannot alter the pre-network Run runtime digest. Bundle manifests bind the report identity,
and authoritative report reconstruction requires that identity; static verification under another
report identity proves hashes only.

Operational SLA violations are not business-truth failures when the journal preserves actual
elapsed values, causal known-at order, every due opportunity, and Outcome maturity. Positive
opportunity-commit lateness, network retry-dispatch lateness, and durably recorded probe missed
deadlines/late timer transitions remain counted anomalies. Negative latency, backdating, a missing
transition, later input processed before its required causal commit, a missing opportunity,
interruption, an unsealed/orphan segment, or immature Outcome remains a hard incomplete result.
Replay independently reconstructs the anomaly counts from causal commits and persisted elapsed
times. This governance correction does not relax denominator, causality, maturity, replay, or
attestation requirements.

## Definition of done

The pre-registered run contract, interleaved causal commit/opportunity journals, append-only sealed
facts, complete twelve-opportunity denominator, immutable Decision/Entry/Outcome/Run receipts,
mature Entries, active future-platform proof acquisition, descriptive `NO_TRADE`, nondegenerate
synthetic plus bounded public evidence, fresh replay, anchored historical semantic regression,
bundle hashes, canonical report, focused tests, full gate, and Draft PR exist; every
zero/null/incomplete result and attestation limit is honest; existing Decision and Outcome meanings
remain unchanged; no later-stage authority is claimed; and the task remains `ACTIVE` pending human
business acceptance.
