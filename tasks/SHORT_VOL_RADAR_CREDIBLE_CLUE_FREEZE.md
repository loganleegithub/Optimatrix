# Task — Short Vol Radar credible-clue freeze

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** the accepted source-contract probe is consumed; one post-repair
production-public read-only smoke of at most 600 seconds is authorized for each new exact candidate
that passes offline gates; no unchanged rerun and no 43,200-second observation before smoke
acceptance and an Authority amendment

**Base commit:** `a8a78bc5b35e3359864b5985f3b013b8981896b1`

**Target branch/package:** `agent/radar-credible-clue-freeze` / offline delivery package

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** candidate `cbea7a3` passed its source contract but failed the first 540-second smoke.
The last readable post-warmup partition was `12,384 / 28,128` known; `OPTION_BOOK_UNKNOWN 11,836`
was the largest visible loss, nine current samples had zero full-formula instruments, and the
terminal cumulative result was unreadable.

**Primary blocker:** `RADAR_CURRENT_INPUT_BACKLOG`; denominator is every post-warmup applicable
instrument fact that should retain a current option book, ticker, clock, and history tail. Whole
scope formula fan-out and a second unbounded pending owner caused the visible
`OPTION_BOOK_UNKNOWN`; close lifecycle separately withheld the terminal summary.

**Expected user-visible delta:** the Radar maintains positive full-formula current state under the
real public option universe, exposes the current book owner's exact bounded reason when unavailable,
and returns a readable cumulative terminal summary. Zero natural clues remains valid.

**Durable-data effect:** `NONE`; all pre-Shadow state remains bounded and in memory.

**Complexity added:** no new subsystem; one per-transaction history-tail cache, one bounded transport
close budget, and exact current book reason in the existing Workbench row.

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
- no repeat of the accepted source probe;
- one <=600-second production-public read-only integration smoke per new offline-gated repair
  candidate, with no unchanged rerun;
- no threshold tuning from either short validation.

## Definition of done

The exact Policy and code satisfy every hard-screen invariant; all diagnostic context and rank are
transparent and non-gating; direct and repository checks pass; the bounded source probe and short
smoke report their exact limitations; no pre-Shadow durable object is added; the delivery package
contains the full source, exact-base patch, checksums, and import instructions; no
43,200-second observation is authorized by implementation presence.
