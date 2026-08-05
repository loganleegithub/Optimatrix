# Task — Short Vol Radar credible-clue freeze

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** the source-contract probe and repair smoke are accepted and consumed; exactly one
fixed 43,200-second production-public read-only observation is authorized, with no unchanged restart

**Base commit:** `a8a78bc5b35e3359864b5985f3b013b8981896b1`

**Target branch/package:** `agent/radar-credible-clue-freeze` / offline delivery package

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE`

**Baseline:** repair candidate `0dce984` passed its 540-second smoke with post-warmup
`90,689 / 91,091` known, `21,930` full-formula evaluations, terminal `134 / 134` current known, all
books usable, zero clock-gap evaluations, zero queue-lag segments, zero overflow, and a readable
terminal summary. Its `402` UNKNOWN evaluations were fixed startup edges and did not continue.

**Primary blocker:** `NATURAL_CLUE_AND_STRUCTURE_FREQUENCY_UNMEASURED`; the short smoke proved input
and formula reachability but was not long enough to measure the frozen ten-minute persistence rule
or the next conversion loss.

**Expected user-visible delta:** one fixed observation reports independent persistent volatility
clues, reviewable defined-risk structures, currently quoted official atomic structures, and whether
the largest loss is Radar breadth, structure absence, or absent target-size atomic credit.

**Durable-data effect:** pre-Shadow state remains in memory; only a legitimately admitted
`SHADOW_CASE_OPENED` may create the already-defined durable Case.

**Complexity added:** `NONE`; the observation runs the frozen product.

**Complexity deleted:** scope-wide formula recomputation for local facts, repeated history-contract
scans, the unbounded runtime ingress deque, and dual 100ms option feeds that have no five-minute
detector purpose.

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
`tick_size` and `tick_size_steps`; the detector consumes target-size bid and ask depth. Public option
ticker and book subscriptions use Deribit's aggregated `agg2` channels. No new external provider or
durable feed is added.

**Decision Policy change:** Radar Policy schema `6`; TTE bands are `30–45m` review-only,
`45m–6h`, `6h–24h`, and `24h–72h`; clue-eligible bands use `0.05 <= |Delta| <= 0.40`, the existing
`1.20 / 1.05` richness hysteresis, three/two observations, five-minute separation, and the same
30/120/360-minute conservative maximum. Activation richness is the one-tick-stressed executable
bid richness. Regime, surface, synthetic structure, and rank fields are diagnostic only.

**Outcome/evaluation contract change:** NONE. Future qualification remains pre-registered and based
on strictly future Shadow Case Outcomes.

**Stage/authorization change:** the accepted source probe and smoke are consumed; one fixed
43,200-second production-public read-only observation is authorized. Deployment and execution are
not authorized.

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
- no repeat of the accepted source probe or repair smoke;
- exactly one fixed 43,200-second production-public read-only observation;
- no threshold tuning, unchanged restart, external supervisor, or private method.

## Definition of done

The exact Policy and code satisfy every hard-screen invariant; all diagnostic context and rank are
transparent and non-gating; direct and repository checks pass; the source probe and smoke are
accepted; and the fixed long observation returns a readable terminal funnel without changing the
candidate generator or extending its boundary.
