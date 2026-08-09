# Task — Process-Independent Shadow Entry Recovery

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** one clean migration and recovery cutover only after implementation acceptance

**Base commit:** `0f937475ee92a6fa9c280a24c4f74759e39222f4`

**Implementation commit:** `00277fe6ec7e234286a7ab3cb2735650765e695d`

**Draft PR:** [#32](https://github.com/loganleegithub/Optimatrix/pull/32) from
`codex/shadow-entry-recovery` to `main`

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md),
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `SHADOW_CASE_OPENED`

**Baseline:** at task opening, the verified Inverse process had `6 / 6` real schema-v4 admitted
Entries with durable contracts, quantities, entry prices, fees, times, economics, product/Policy
bindings, and Entry identities; `0 / 6` could be restored by a later process. The live set may grow
while the task is implemented (and had already reached nine in a later read-only snapshot), so six
is only the task-opening denominator, never a runtime, count, or Case-ID allowlist. Every future
admitted Entry has the same ownership defect.

**Primary blocker:** `RUNTIME_OWNED_ENTRY_LIFECYCLE`, affecting every current admitted Entry and all
future non-terminal admitted Entries at process restart.

**Expected user-visible delta:** after any externally initiated restart, the Workbench automatically
shows every compatible non-terminal admitted Entry once under the same `shadow_entry_identity`,
with origin runtime, current Observation Segment, truthful gap/currentness, first-CLOSE/attempt
state, Outcome quality, and qualification eligibility. No Entry disappears or becomes a fabricated
new admission.

**Durable-data effect:** replace per-runtime Case ownership with one stable `state-root/cases`
repository. A Case may add Segment-open/close records, one atomic first-CLOSE/attempt schedule, one
mature Outcome, and one optional legacy-migration mapping. Segment records are consumed directly by
the runtime owner, trader Workbench, and AI Researcher; their later runtime/adoption/stop/gap facts
cannot be derived from the original opened record. The migration mapping is consumed by the
restored Entry reader and AI Researcher and cannot be derived from legacy bytes because their old
schema treated process censoring as terminal. The origin Segment, not `opened.json`, stores the
entry index and short-leg mark-IV source references needed by recovery. The accepted v3/v4 opened
shapes and product schema identities remain unchanged; a missing legacy baseline is `UNKNOWN`. No
pre-Shadow or per-tick durable write is added.

Every new admitted Entry Case stages and validates `opened.json + segments/0/opened.json` together,
then makes the complete Case visible with one no-replace atomic directory publication. A crash
before publication leaves no visible Entry Case. This uses the existing single-instance lease and
adds no manifest or fencing protocol.

**Complexity added:** one file-backed stable Case repository, one bounded per-runtime Observation
Segment family, automatic active-Entry scan/rehydration, one combined first-close/attempt transition,
and one offline legacy migration command.

**Complexity deleted:** fresh-root/runtime-owned Entry lifecycle, clean-stop admitted Outcome
censoring, exact predecessor/Entry carry special cases, and any need for an Entry allowlist.

## Given / When / Then

**Given:** one admitted Entry is durably open under runtime A, its product and frozen Policy chain
remain supported, and no mature `SHADOW_CASE_OUTCOME` exists.

**When:** runtime A cleanly stops, fails, or exits uncleanly and an external operator starts runtime
B and later runtime C on the same stable state root.

**Then:** each runtime validates the full Case repository before public intake, restores that Entry
without reconstructing pre-Shadow state, and opens a new Segment at its first settled boundary.
Clean stop/failure closes only the Segment. Every cross-process Segment is `GAPPED`, data begins
`UNKNOWN`, and the gap never synthesizes `HOLD` or `CLOSE`. Fresh facts resume Position evaluation.
A stable admitted censored aggregate Outcome is invalid; the runtime invokes the Segment-close
boundary directly.

If first CLOSE later occurs, its record atomically freezes the only close-attempt schedule before
requests are released. A previously scheduled attempt that becomes uncertain across process loss is
not retried. A mature known or unknown economic Outcome may be formed after recovery, but any gap
forces `observation_quality=GAPPED` and `qualification_eligible=false`.

## Exact source / known-at boundary

- immutable enrollment, structure, and entry-economic facts come only from validated
  `SHADOW_CASE_OPENED` and optional legacy mapping;
- immutable entry index/mark-IV source baselines come only from the origin Segment's
  `entry_position_baseline`; a missing legacy baseline remains `UNKNOWN`;
- cross-runtime order comes only from the single-predecessor Segment chain;
- FactBoundary ordering is strict only inside one Segment;
- restored current market/Position facts are `UNKNOWN` until accepted after the new Segment open;
- no stopped interval is replayed, backfilled, or inferred;
- durable first-CLOSE/attempt presence is the only authority for retry prohibition.

## Legacy migration

One offline command accepts a user-specified stopped legacy run and a fresh destination repository.
It scans every source Case and migrates all compatible `ADMITTED_SHADOW_TRADE` records; no count,
runtime, Entry, or Case-ID allowlist exists. Legacy mature Entries remain terminal. Legacy admitted
`CENSORED_AT_STOP`, `CENSORED_AT_FAILURE`, and `INCOMPLETE_UNCLEAN_EXIT` records become active
process-independent aggregates whose origin Segment preserves the source record's observation
quality. The first later-runtime Segment records the cross-process gap as `GAPPED`. Controls are
excluded.

The migration validates the full compatible set into staging before atomic publication, preserves
source bytes, is idempotent for identical input, and fails on conflict. It is not a `serve-shadow`
option, restart mechanism, manifest, or general migration framework. It does not widen accepted
v3/v4 opened records or change their product schema identities.

The migration record is minimal provenance only: version, Case/Entry identity, source opened,
optional first-close and Outcome record identities, raw optional legacy first-close, source Outcome
state, and mapped legacy Segment state. Product, Policy, runtime, destination identity, restored
latch/attempt state, and source-immutability non-claims are validated or derived elsewhere and are
not duplicated durably.

## Change declarations

**Market/Decision input contract change:** normal startup gains one official-reader scan of the
stable Case repository; public market inputs and pre-Shadow decisions do not change.

**Decision Policy change:** process gap is observation quality and never a Position predicate;
recovery starts `UNKNOWN` and fresh facts use the frozen Position Policy.

**Outcome/evaluation contract change:** admitted stop/failure ends a Segment rather than Entry
Outcome; first CLOSE and attempt schedule become one durable transition; mature gapped Outcomes are
permitted but qualification-ineligible.

**Stage/authorization change:** authorize process-independent recovery, one offline legacy
migration, and reuse of one stable state root. Process supervision, private execution, and Policy
tuning remain unauthorized.

## Scope

**In:** Shadow Case record/store/reader, restored owner state, Segment lifecycle, first-close attempt
publication order, service startup/stop composition, Workbench server/browser projection, funnel
deduplication, one offline migration command, Authority/contracts/task, and direct tests.

**Out:** database, manifest, receipt chain, distributed fencing, generic event log, full-feed replay,
per-tick checkpoint, gap reconstruction, pre-Shadow recovery, Control recovery, hard-coded Entry
selection, private APIs/orders/fills/capital, Policy tuning, supervisor, deployment, or host
inspection.

**Owning modules:** `short_vol_underwriting` owns aggregate/Segment/transition/Outcome validation and
rehydration. `radar_runtime` owns repository startup composition, one selected-product runtime,
Workbench projection, and the offline migration CLI wiring. Browser code only renders typed truth.

## Direct verification and non-claims

- deterministic runtime A → B → C fixture over one stable repository;
- full active admitted scan, product/Policy mismatch failure, terminal/Control exclusion, and no
  partial active book;
- same Entry identity and frozen economics, no duplicate Candidate/admission/opened funnel count;
- Segment chain ordering, clean/failure/incomplete states, recovery-first UNKNOWN, no synthetic
  CLOSE, and fresh-fact continuation;
- crash-before/crash-after fixtures proving initial Case directory publication exposes either none
  or both of `opened.json + segments/0/opened.json`, never a half-published Entry;
- byte-exact accepted v3/v4 opened shapes plus origin-only `entry_position_baseline`, including
  truthful legacy `UNKNOWN` when exact index/mark-IV source references are absent;
- atomic first-close/attempt schedule, zero request before publication, and no retry after uncertain
  loss;
- one mature gapped Outcome with correct economics and qualification false;
- migration all-compatible selection, immutable source, Control exclusion, all-or-nothing staging,
  idempotency, and conflict rejection;
- Workbench one-row-per-Entry plus separate Runtime health;
- focused tests, `make check`, Draft PR CI, and one accepted live migration/cutover.

Success does not establish fillability, strategy edge, profitability, continuous-observation
qualification, account margin, actual exposure, order/fill truth, deployment health, or automatic
restart permission.

## Definition of done

The task is complete only when the repository and reader make every compatible non-terminal admitted
Entry process-independent; A → B → C tests, migration tests, focused checks, `make check`, and Draft
PR CI pass; the current stopped legacy run migrates without source mutation; and one real Inverse
runtime starts on the stable destination repository with all active Entries visible exactly once and
truthfully gapped. Green tests or a healthy empty runtime alone are insufficient.
