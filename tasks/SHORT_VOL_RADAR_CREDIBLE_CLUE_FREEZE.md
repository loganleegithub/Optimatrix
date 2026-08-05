# Task — Short Vol Radar credible-clue freeze

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** exactly one source-contract probe and one production-public read-only integration
smoke of at most 600 seconds; no 43,200-second observation

**Base commit:** `a8a78bc5b35e3359864b5985f3b013b8981896b1`

**Target branch/package:** `agent/radar-credible-clue-freeze` / offline delivery package

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE`

**Baseline:** A1 produced 146 noisy one-minute Episodes. The first A2 43,200-second observation was
rejected with post-warmup `RADAR_KNOWN / APPLICABLE_MARKET_SCOPE = 0 / 0` because a 360-minute
economic feature was tied to one uninterrupted live session. Commit `a8a78bc` repairs bootstrap
reachability but has not frozen credible clue semantics.

**Primary blocker:** `RADAR_CREDIBLE_CLUE_SEMANTICS_INCOMPLETE`; denominator is every formula row
that could still be a false clue because target ask, official tick stress, actionable TTE/Delta,
regime context, surface context, structure reference, or transparent rank is absent.

**Expected user-visible delta:** a `RICHNESS_CLUE_ACTIVE` row is a target-size, two-sided, uncrossed,
one-legal-tick-robust executable-bid witness in an actionable TTE/Delta bucket. The row separately
shows causal RV, path/jump regime, surface-lite context, conservative non-atomic protective-vertical
references, official atomic state, rank inputs, blocker, upgrade condition, and invalidation
condition.

**Durable-data effect:** `NONE`; all pre-Shadow state remains bounded and in memory.

**Complexity added:** one history-response contract projection; official option tick metadata;
one-tick quote stress; four TTE buckets; five Delta buckets; semivariance/jump diagnostics; one
surface-lite review calculator; one conservative legged-reference calculator; one deterministic
lexicographic rank.

**Complexity deleted:** the false equivalence between a single-leg IV/RV hit and a downstream
`CANDIDATE`, the all-Delta/all-TTE candidate universe, and the need to spend 43,200 seconds after
every formula correction.

## Business closure

**Given:** official completed BTC-USDC index-chart points; current public option metadata, ticker,
and target-size books; one fixed Policy chain.

**When:** the source validator establishes cadence/age/revision truth, the detector evaluates
bid/ask depth and one-tick-stressed executable IV in an actionable bucket, and the review layer adds
non-gating regime, surface, legged-reference, and rank context.

**Then:** every active Radar clue is causally reproducible and robust to one legal tick; incomplete
context stays explicit and cannot create an official atomic quote, Underwriting Candidate, Shadow
Case, order, fill, or profitability claim.

**Valid zero/UNKNOWN:** zero active clues is valid when post-warmup scope and full-formula counts are
positive. Missing required hard-screen facts are `UNKNOWN` or known ineligibility. Missing review
context lowers explanation/rank completeness but does not erase a known hard-screen witness.

## Change declarations

**Market/Decision input contract change:** official chart history records cadence, completed-suffix
coverage, response revision, and source age; option metadata additionally consumes official
`tick_size` and `tick_size_steps`; the detector consumes target-size bid and ask depth. No new
external provider or durable feed is added.

**Decision Policy change:** Radar Policy schema `6`; TTE bands are `30–45m` review-only,
`45m–6h`, `6h–24h`, and `24h–72h`; clue-eligible bands use `0.05 <= |Delta| <= 0.40`, the existing
`1.20 / 1.05` richness hysteresis, three/two observations, five-minute separation, and the same
30/120/360-minute conservative maximum. Activation richness is the one-tick-stressed executable
bid richness. Regime, surface, synthetic structure, and rank fields are diagnostic only.

**Outcome/evaluation contract change:** NONE. Future qualification remains pre-registered and based
on strictly future Shadow Case Outcomes.

**Stage/authorization change:** one source probe and one <=600-second integration smoke are
authorized. No 43,200-second observation, deployment, or execution is authorized by this task.

## Scope

**In:** Authority/contract/task text; index-history validator; option tick metadata; Radar Policy,
baseline, detector input, review diagnostics, Workbench projection; official fee-cap arithmetic for
non-atomic legged references; dependent Policy identities; and focused tests.

**Out:** target quantity changes, fitted models, event forecasts, full surface calibration,
qualification, private combo creation, real execution, persistence, replay, deployment, or host
acceptance.

**Owning hard-screen calculator:** `packages/short_vol_radar/src/short_vol_radar/radar.py`.

**Owning diagnostic review calculator:** `packages/short_vol_radar/src/short_vol_radar/review.py`.

**Sole external-history validator:**
`packages/market_monitor/src/market_monitor/index_history.py`.

## Validation

- direct focused tests for history, policy/math, Radar, review, Workbench, fee arithmetic, and
  Authority;
- repository gate: `make check` in the exact toolchain;
- exactly one source probe; stdout only, no product persistence;
- exactly one <=600-second production-public read-only integration smoke after direct gates;
- no threshold tuning from either short validation.

## Definition of done

The exact Policy and code satisfy every hard-screen invariant; all diagnostic context and rank are
transparent and non-gating; direct and repository checks pass; the bounded source probe and short
smoke report their exact limitations; no pre-Shadow durable object is added; the delivery package
contains the full source, exact-base patch, checksums, and import instructions; no
43,200-second observation is authorized by implementation presence.
