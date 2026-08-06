# Task — Short Vol Radar credible-clue freeze

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** `NONE_AUTHORIZED`; the prior fixed observation is consumed and
`REJECTED_CENSORED_AT_FAILURE`

**Base commit:** `a8a78bc5b35e3359864b5985f3b013b8981896b1`

**Target branch/package:** `agent/radar-credible-clue-freeze` / offline delivery package

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** the failed long observation's last readable slice had post-warmup
`1,291,464 / 1,294,841` known (`99.7392%`), terminal `134 / 134` current known, all books usable,
`28` current full-formula evaluations, zero queue lag/overflow/pending RPC, zero anomalies, and zero
durable Case files. It then terminated before the fixed boundary.

**Primary blocker:** `NUMERICAL_BOUNDARY_OWNERSHIP_GAP`; a legitimate richness interval spanning the
activation or clear threshold escaped the Tracker, was mislabeled as source-protocol failure, and
fatally censored the observation.

**Expected user-visible delta:** a threshold-spanning interval becomes one bounded
`NUMERICAL_BOUNDARY_UNRESOLVED` Radar UNKNOWN without activation, clear, reconnect, or process exit;
the next valid market fact remains processable.

**Durable-data effect:** pre-Shadow state remains in memory; only a legitimately admitted
`SHADOW_CASE_OPENED` may create the already-defined durable Case.

**Complexity added:** one already-classified detector signal field; no module, exception hierarchy,
validator, persistence, retry policy, or diagnostic subsystem.

**Complexity deleted:** Tracker-side duplicate threshold classification and transport-wide generic
business-`ValueError` relabeling.

## Business closure

**Given:** official completed BTC-USDC index-chart points; current public option metadata, ticker,
and target-size books; one fixed Policy chain.

**When:** the hard-screen calculator derives a conservative one-tick-stressed richness interval and
that interval spans activation or clear.

**Then:** the calculator owns the one threshold classification, returns bounded UNKNOWN when
unresolved, and the Tracker consumes only a resolved signal. No Episode, downstream object,
reconnect, or process exit is created by the unresolved boundary.

**Valid zero/UNKNOWN:** zero active clues is valid when post-warmup scope and full-formula counts are
positive. Missing required hard-screen facts are `UNKNOWN` or known ineligibility. Missing review
context lowers explanation/rank completeness but does not erase a known hard-screen witness.

## Change declarations

**Market/Decision input contract change:** NONE.

**Decision Policy change:** NONE. The exact `1.20 / 1.05`, TTE/Delta buckets, persistence,
benchmark, target quantity, and downstream semantics remain frozen.

**Outcome/evaluation contract change:** NONE. Future qualification remains pre-registered and based
on strictly future Shadow Case Outcomes.

**Stage/authorization change:** the failed observation is consumed; offline repair only. No live
command, deployment, or execution is authorized until a fresh post-gate Authority change.

## Scope

**In:** Authority/task text; hard-screen detector classification; Episode Tracker consumption;
subscription exception boundary; direct pricing-path and source-boundary tests.

**Out:** target quantity changes, fitted models, event forecasts, full surface calibration,
qualification, private combo creation, real execution, persistence, replay, deployment, or host
acceptance.

**Owning hard-screen calculator:** `packages/short_vol_radar/src/short_vol_radar/radar.py`.

**Owning diagnostic review calculator:** `packages/short_vol_radar/src/short_vol_radar/review.py`.

**Sole external-history validator:**
`packages/market_monitor/src/market_monitor/index_history.py`.

## Validation

- direct real-pricing-path tests for activation and clear boundary spans, source/business error
  identity, funnel reason, and episode behavior;
- repository gate: `make check` in the exact toolchain;
- no public probe, smoke, or long observation during the repair gate;
- no threshold tuning, transport diagnostic expansion, external supervisor, or private method.

## Definition of done

Real pricing paths project activation/clear boundary spans to exactly one bounded UNKNOWN; no
business uncertainty is renamed as source-protocol incompatibility; active Episodes end as UNKNOWN
rather than CLEAR; direct and repository checks pass; and pre-Shadow durable business files remain
zero. Green checks do not authorize a live run.
