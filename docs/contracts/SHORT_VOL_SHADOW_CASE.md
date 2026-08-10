# Short Vol Shadow Case Contract

**Status:** ACTIVE IMPLEMENTATION CONTRACT

**Owning capability:** `SHORT_VOL_SHADOW_CASE`

## Purpose

Define the only durable business boundary in the current public-only product. An admitted Shadow
Case begins
when one counterfactual is explicitly enrolled before its future path is known: either an admitted
HIGH Candidate trade, one action-blind HIGH selected decision, or one future-blind LOW/MID
Radar-score Control for its causal batch.
For an admitted trade it is a process-independent Entry aggregate. It preserves minimum enrollment
context, a chain of runtime Observation Segments, one combined first-CLOSE/attempt-schedule
transition, and one mature terminal result for online recovery, trader review, AI research, and
later offline qualification. A selected no-trade Control remains a bounded non-recoverable Case.

The Online Runtime does not persist qualification Cohorts, aligned pairs, comparison tables,
Challenger features, Radar events, Underwriting events, or unselected/automatic no-trade
counterfactuals.

## Record set

Exactly five record kinds are authorized:

```text
SHADOW_CASE_OPENED               exactly one per Case
SHADOW_CASE_SEGMENT_OPENED       one per runtime Observation Segment
SHADOW_CASE_SEGMENT_CLOSED       zero or one per Segment
SHADOW_CASE_FIRST_CLOSE          zero or one per admitted Entry; also schedules its one attempt
SHADOW_CASE_OUTCOME              zero or one mature Outcome per Case
```

Each Case directory is:

```text
cases/<case-id>/opened.json
cases/<case-id>/first-close.json    # optional
cases/<case-id>/outcome.json        # optional
cases/<case-id>/segments/<segment-sequence>/opened.json
cases/<case-id>/segments/<segment-sequence>/closed.json   # optional
```

No other durable file belongs to the product runtime.

## Case identity

The accepted Inverse schema-v5 `case_id` is the canonical SHA-256 identity derived from:

```text
"ShadowCaseIdentity"
code_identity
runtime_identity
Radar Policy identity
Underwriting Policy identity
Position Policy identity
"schema-v5"
INVERSE_BTC_V1 product identity
enrollment identity
opened FactBoundary
```

Policy identities are exact content digests. The code identity is the exact Git commit. Markdown
contract bytes, file paths, host identity, PID, manifest, receipt, directory inventory, and
Workbench publication sequence do not enter the Case identity.

Every record binds the same Case, `INVERSE_BTC_V1` product, and frozen Policy semantics.
`SHADOW_CASE_OPENED` binds the origin code/runtime. Each Segment and any later first-close or
Outcome record binds the exact code/runtime that emitted it plus its Segment identity.
FactBoundaries must increase strictly inside one Segment. Cross-runtime ordering comes only from an
acyclic, single-predecessor Segment chain; runtimes' monotonic clocks are never compared directly.

## `SHADOW_CASE_OPENED`

The opened record contains:

- `record_kind`, `schema_version`, and `case_id`;
- exact code/runtime/three-Policy identities;
- `enrollment_kind`, generic enrollment identity, opened/entry and Underwriting decision boundaries;
- Candidate/`SHADOW_ENTRY` identities for admitted trades, or explicit nulls for no-trade controls;
- execution model and two frozen canonical option-leg identities;
- display instrument names, expiry, option type, strikes, entry direction, and full BTC quantity;
- paired component-book source identity, session/continuity epochs, measured source/receive skew,
  consumed Policy skew limits, and exact raw/stressed full-quantity levels for both legs;
- gross credit, entry fee reserve, net credit, payoff cap, future-cost reserve, and reserved loss;
- the canonical V2 `selection_score_packet` and same-shape
  `entry_refresh_score_packet`, including Policy/fact boundary, bucket/leader, score interval/band,
  coverage/missing mask, five decision factors with raw inputs and normalized contributions,
  unsigned OI/gamma diagnostic, and any bounded sampling metadata;
- the consumed Radar component state and official atomic diagnostic;
- the Underwriting action, complete failed-predicate/margin vector, and thresholds actually consumed;
- the protective-leg selector-rule identity and Candidate protective-leg count frozen with the
  selected structure;
- when pre-outcome selected, the selection rule/batch identities plus original and refreshed actions,
  complete predicate-margin vectors, and their strictly ordered boundaries;
- exact non-claims: `NOT_AN_ORDER`, `NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`,
  `NO_LIQUIDITY_RESERVATION`, and `ATOMIC_EXECUTABILITY_UNPROVEN`. A no-trade control additionally
  states `NOT_A_CANDIDATE_ACTIVATION`, `NOT_A_SHADOW_ENTRY`, `NOT_AN_ADMITTED_TRADE`, and
  `NO_CAPITAL_EXPOSURE`.

The exact economic shape is the accepted Inverse schema-v5 record. It contains one exact product
object with native premium/settlement currency, price index, strike and valuation currencies,
economic-semantics identity, and the declared valuation basis. Entry legs retain BTC-native
consumed levels, VWAPs, and fees. Entry economics retain BTC-native gross/fee/net values and
separately named USD boundary valuations at the causal entry index. USD-defined strike
width/payoff/reserve values remain distinct from native BTC cashflow and from actual account
margin, which is `UNKNOWN`.

Process-independent recovery does not add a key to the accepted `opened.json` shape and does not
change its product schema identity. Entry Position baselines belong only to the origin Segment.

Each entry leg's consumed amounts must sum exactly to the full quantity. Pair session and continuity
epochs must match, measured receive skew must agree with the two receipt boundaries, and both skews
must remain within the stored limits bound to the Underwriting Policy. Stored gross credit, both fee
reserves, net credit, width, payoff cap, loss values, canonical six-predicate margin vector, failed
predicates, and resulting action must conserve against the stored stressed legs and Policy
thresholds in their declared units. For v4, native arithmetic and each native-to-USD valuation must
also conserve independently. The record may not contain the full option chain or unrelated market
state.

For every new admitted Entry Case, the writer constructs `opened.json` and the origin
`segments/0/opened.json` inside the same staging Case directory and validates the complete pair
before either is visible. One no-replace atomic directory publication makes both visible together.
A crash before that publication leaves no visible Case, never an `opened.json` without its origin
Segment. For an ordinary online enrollment, both records use the origin runtime and Entry boundary;
the origin Segment has sequence zero, no predecessor, and `observation_quality=CONTINUOUS`. For a
new admitted Entry its `entry_position_baseline` is `KNOWN` and freezes the causal entry index and
short-leg mark IV with their exact source identities and FactBoundaries. Only a later Segment opened
by a new runtime records an intervening `HANDOFF_GAP`, becomes `GAPPED`, increments `gap_count`, and
makes qualification ineligible.

## Observation Segment records

`SHADOW_CASE_SEGMENT_OPENED` contains:

- Case and `shadow_entry_identity`;
- exact segment identity, emitting code/runtime, product, and frozen Policies;
- adoption FactBoundary and zero or one predecessor Segment identity;
- predecessor close state when available;
- `observation_quality=CONTINUOUS | GAPPED`, gap reason, and cumulative gap count;
- `qualification_eligible`, which is permanently false after the first gap;

The origin Segment alone contains `entry_position_baseline`. A new admitted Entry requires its
`KNOWN` entry index and short-leg mark-IV values, source identities, and source FactBoundaries.
Recovery may not infer, widen, rewrite, or copy the baseline into later Segments.

An origin Segment is `CONTINUOUS`. Every process-recovery Segment is `GAPPED`, including a clean
handoff, because the service did not observe the interval between segment boundaries. Its current
data state begins `UNKNOWN`; the gap does not imply `HOLD` or `CLOSE`.

`SHADOW_CASE_SEGMENT_CLOSED` contains the same Segment binding, exact stop/failure FactBoundary,
and one terminal segment state:

```text
CENSORED_AT_STOP
CENSORED_AT_FAILURE
```

It contains no Entry PnL and is not `SHADOW_CASE_OUTCOME`. If an uncatchable crash prevents this
record, the Segment is `INCOMPLETE_UNCLEAN_EXIT`; the next Segment truthfully references that state
and remains gapped.

## `SHADOW_CASE_FIRST_CLOSE`

The optional first-close record is written only when the Position owner first latches CLOSE. It is
the atomic `FIRST_CLOSE_AND_ATTEMPT_SCHEDULED` transition and contains:

- same Case/product/Policy identities plus the emitting Segment/code/runtime;
- the exact first Position action identity and boundary;
- primary and ordered latched close reasons;
- the predicate truth vector consumed at that boundary.
- the one post-CLOSE attempt identity, its two frozen leg request identities, quantity, and schedule
  boundary.

The writer publishes this record before releasing either request intent. Later Position evaluations
and runtimes cannot rewrite it, create another first-close record, or schedule another attempt. If
the attempt lacks a terminal mature Outcome when its process is lost, recovery reports
`ATTEMPT_STATE_UNKNOWN_AFTER_PROCESS_LOSS` and does not retry.

## `SHADOW_CASE_OUTCOME`

An admitted Entry's terminal record has one immutable mature state:

```text
MATURE_KNOWN
MATURE_UNKNOWN
```

`MATURE_KNOWN` requires the first eligible strictly post-CLOSE paired component-book exit for the
same frozen legs. It stores the pair/source identities, raw/stressed full-quantity levels for both
legs, gross close cashflow, both close fee reserves, net close cashflow, gross PnL, total public fee
reserve, net PnL after reserve, and net loss.

The Outcome stores BTC-native close cashflow, fees, gross/net PnL, the causal close valuation index,
the net PnL formed from entry- and close-boundary USD valuations, and the distinct view that values
total native BTC PnL at the close index. Both views are predeclared and conserved; neither is chosen
after the Outcome. They are counterfactual valuations, not fills, settlement actions, or
account-margin facts.

`MATURE_UNKNOWN` means the Case reached its natural terminal condition without an eligible paired
component-book exit under the frozen contract. Component close facts and economic exit/PnL fields
are absent or null.

Every mature admitted Outcome records its producing Segment plus
`observation_quality=CONTINUOUS | GAPPED`, cumulative gap count, and
`qualification_eligible`. `GAPPED` always makes qualification eligibility false, even when public
exit economics are fully known. Lifecycle completeness, economic knownness, and qualification
eligibility remain distinct.

A handled clean stop or failure ends only the admitted Entry's current Segment. Selected no-trade
Controls are not recoverable aggregates and may retain `CENSORED_AT_STOP | CENSORED_AT_FAILURE`
with null economics under their bounded lifecycle. A stable
owner that emits a censored admitted aggregate Outcome is rejected; stop/failure must use the
Segment-close boundary directly.

## Unclean process loss

The writer cannot guarantee `SHADOW_CASE_SEGMENT_CLOSED` after power loss or an uncatchable process
crash. A reader finding a valid Segment open and no close reports:

```text
INCOMPLETE_UNCLEAN_EXIT
```

It does not synthesize a close record or Outcome and does not delete the Case. The Entry remains
non-terminal. The next runtime restores it, opens a new Segment whose predecessor state is
`INCOMPLETE_UNCLEAN_EXIT`, marks observation quality `GAPPED`, and begins current facts at
`UNKNOWN`. A durable first-CLOSE attempt already scheduled in the incomplete Segment is never
retried.

## Minimal writer

The Case writer:

- creates a same-filesystem staging Case directory without following symlinks;
- for an admitted Entry, writes canonical UTF-8 `opened.json` and `segments/0/opened.json`, flushes
  and `fsync`s both files and their staging directories, then validates the complete initial pair;
- publishes that initial admitted Entry Case exactly once by a no-replace atomic directory
  operation and `fsync`s the `cases/` parent; neither initial record is individually visible first;
- publishes later Segment-close, recovery-Segment, first-close, and Outcome records by
  the existing same-directory no-overwrite atomic file operation and parent `fsync`;
- accepts an identical duplicate as idempotent and rejects a conflicting duplicate;
- never scans or validates another Case as part of the write.

The initial staging directory is bounded to one Case and is removed or ignored after an interrupted
pre-publication attempt. It is not a manifest, receipt chain, fencing protocol, general evidence,
or commissioning framework; the existing single-instance repository lease remains the only local
writer exclusion.

## Minimal reader

The startup scanner enumerates direct Case-directory names under the one stable repository; the
Inverse product reader then validates each requested Case independently:

- exact record key/type shape;
- identity format and same Case/product/frozen-Policy binding;
- opened pair identity/timing/Policy limits, per-leg quantity, stress direction, fee, and economic
  conservation;
- canonical predicate order/unit/sign truth, failed predicates, action, and Policy-bound margins;
- one acyclic Segment predecessor chain, per-Segment runtime binding and strictly increasing local
  boundaries;
- origin-only `entry_position_baseline` knownness and exact index/mark-IV source binding, without an
  `opened.json` shape or product schema identity change;
- zero/one combined first-close/attempt schedule across the aggregate;
- mature Outcome producing-Segment binding, observation quality, gap count, and qualification truth;
- state-specific null/economic requirements;
- recomputable paired component-book PnL arithmetic in the schema's declared native and valuation
  units;
- no conflicting duplicate files.

It returns active/terminal Entry status, current Segment status, `CONTINUOUS | GAPPED`, and Control
status separately. The runtime restores every compatible active admitted Inverse Entry and no
Control. The reader does not validate Git trees, inspect host state, migrate, reconstruct market
state, or form a qualification Cohort. It reads only the exact Inverse schema-v5 family and
its process-independent aggregate/segment extension; unsupported product or schema input fails.

## No-trade controls and Cohorts

The current implementation may enroll one HIGH selected-decision Control under the existing
activation-batch rule, or one `RADAR_SCORE_BAND_NO_TRADE_CONTROL` when a no-HIGH causal batch
future-blindly designates one confirmed LOW/MID research-review Episode. If both strata exist, one
hash chooses the stratum and one chooses the member; if one exists, only the member hash applies.
The Case freezes exact eligible counts and rational inclusion probability. A LOW/MID selected
review uses the same formal Underwriting protective-leg selector and one strictly later paired
refresh. Any evaluable refreshed action opens the non-admitted Control, including Candidate;
`UNKNOWN` and invalid pairs write no Case, and there is no fallback. A Control never creates a
Candidate, `SHADOW_ENTRY`, admitted trade, order, fill, capital exposure, or causal-effect estimate.
An ordinary HIGH Candidate is never duplicated as a Control.

The read-only `report-v2-cases` projection keeps the three enrollment kinds in separate strata and
does not weight them into a market-population or causal-alpha estimate. It reports an opened Case
without an Outcome as `PENDING_OPEN` only when the official reader returns `OPEN`; callers reading
a currently owned Control root must opt in with `--runtime-active`. The default is
inactive-or-unknown runtime status, under which an abandoned non-recoverable Control remains an
explicit incomplete unclean exit. The report stores nothing and cannot alter Case truth.

Qualification Cohorts are later offline views over completed Cases under a pre-registered
evaluator. A `GAPPED` admitted Outcome is valid research data but is never eligible for a
continuous-observation Cohort. The Online Runtime never writes Cohort or aligned-pair objects.

## Required verification

Direct tests prove zero pre-enrollment files, exact one-open/one-first-close/one-outcome cardinality,
atomic initial admitted Entry `opened.json + segments/0/opened.json` directory publication with no
visible half-Case across a crash boundary, explicit Inverse schema-v5 product binding and
native/boundary/exit valuation conservation, rejection of schema/product/Policy mixing,
original/refreshed selection boundary ordering, zero Candidate/`SHADOW_ENTRY` for controls,
atomic file publication, duplicate handling, pair/source identity and boundary binding, both-leg
arithmetic, repeated process recovery, Segment close/incomplete/gap truth, recovery-first UNKNOWN,
combined first-close/attempt durability, no retry after uncertain loss, and gapped mature Outcome
classification. Tests also prove one shared selection/entry score-packet schema, deterministic
LOW/MID inclusion probability, HIGH precedence, and no pre-Case score persistence.
No database, manifest, receipt, generic graph, per-tick checkpoint, or replay is required. Live
commands remain governed only by `CURRENT_STAGE`.
