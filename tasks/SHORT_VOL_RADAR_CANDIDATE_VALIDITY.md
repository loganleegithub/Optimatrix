# Task — Short Vol Radar candidate validity

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** NONE — the one authorized 43,200-second observation was consumed and rejected

**Base commit:** `42973ad66c348025a0d9ec38239311e8ac0dae64`

**Target branch/PR:** `codex/short-vol-radar-candidate-validity` / Draft PR `#20`

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE`

**Baseline:** the accepted A1 observation produced `146` distinct anomaly Episodes in `900`
seconds, but the operational Policy used one one-minute index return and two changed observations
separated by only one second. The number of economically credible candidate Episodes is therefore
`NOT_YET_MEASURED`.

**Primary blocker:** `POST_WARMUP_APPLICABLE_SCOPE_NOT_REACHED`; denominator `0`. The consumed A2
observation left every Policy band unwarmed for its full fixed boundary, so downstream candidate,
combo, and Underwriting zeros are not conversion results.

**Expected user-visible delta:** an active Radar row means target-size executable bid IV remains at
least `1.20x` a conservative, causally sampled multi-horizon BTC realized-volatility baseline for
at least ten minutes. The Workbench names the result a Radar candidate and shows the five-minute
sampling interval, selected trailing horizon, baseline volatility, richness, activation state,
and exact invalidation condition. Observation output distinguishes instrument Episodes from
candidate activation batches, where all same-direction/same-band instrument activations at one
causal boundary count as one correlated volatility clue rather than many independent opportunities.

**Durable-data effect:** `NONE`; no Radar candidate, funnel diagnostic, or run result is persisted.
When no Shadow Case opens, durable Shadow Case file count remains zero.

**Complexity added:** one bounded in-memory validator/reducer for the official BTC-USDC index-chart
response, one Policy-owned refresh/stale schedule, one conservative maximum selector across three
declared horizons, two explanatory baseline fields, and one scalar activation-batch counter in the
existing transient scope owner.

**Complexity deleted:** Policy weights for an untrained linear combination, the one-minute
operational-probe benchmark, one-second activation persistence, and the `0.90` clear boundary that
could retain a candidate after the IV/RV premium disappeared; the economic baseline no longer
depends on one uninterrupted six-hour WebSocket session, and the consumed observation runner was
removed.

## Business closure

**Given:** a bounded chronological official BTC-USDC index-chart response, current streaming index
truth, target-size executable option bids, trusted remaining life, and the fixed public-only
0–3DTE option universe.

**When:** the owning Radar calculator forms non-overlapping five-minute returns over trailing
30-minute, 120-minute, and 360-minute windows, selects the highest annualized realized volatility
or the declared floor, and applies the fixed time-persistent candidate Policy.

**Then:** every `ANOMALY_ACTIVE` state is an explainable Short Vol Radar candidate backed by the
selected conservative horizon, at least `1.20x` IV/RV richness, three qualifying observations at
least five minutes apart, and a precise clear/unknown/ineligibility condition. A fixed 43,200-second
public-only observation reports post-warmup applicable/known counts, candidate Episode counts,
durations, end reasons, and naturally reached downstream state without treating it as Policy edge.

**Valid zero/UNKNOWN:** zero candidate Episodes is a valid selective Radar result and satisfies the
implementation closure when post-warmup applicable scope is positive. Any required-source loss
remains bounded `UNKNOWN`. Zero post-warmup applicable scope does not satisfy the observation.

**Cheapest falsification:** direct formula tests prove five-minute non-overlapping returns, maximum
selection, floor selection, and causal warmup; detector tests prove the ten-minute activation and
five-minute clear persistence; a deterministic reducer fixture proves Workbench explanation.

## Change declarations

**Market/Decision input contract change:** Deribit's production-public
`public/get_index_chart_data` method (`btc_usdc`, `1d`) is the sole source for the economic history
baseline. One bounded `IndexHistoryReducer` validates chronological `[timestamp, average_price]`
points and selects an exact completed five-minute suffix; it never interpolates gaps, persists
history, or drives live-index reconnect. The existing streaming index remains the sole current
price/currentness owner. The option universe is unchanged.

**Decision Policy change:** Radar Policy schema `5`; one `30m–72h` band with `5`-minute return
sampling, trailing horizons `[30, 120, 360]`, conservative maximum variance selection, unchanged
`1.20` activation ratio, `1.05` clear ratio, activation count `3`, clear count `2`, and minimum
separation `300000ms`; index history refresh is `300000ms` and becomes stale after `900000ms`.
TTE, Delta, target quantity, and atomic semantics are unchanged.
Underwriting and Position numeric decision fields remain unchanged; their exact Policy bytes change
only to bind the new upstream Radar/Underwriting content identities.

**Outcome/evaluation contract change:** NONE; the public observation is current-state engineering
validation, not backtest, qualification, profitability, fill, or Shadow outcome evidence.

**Stage/authorization change:** the exactly one 43,200-second production-public read-only
observation was consumed and rejected. No further live command is authorized by this task version.

## Scope

**In:** the official index-chart input reducer, repository Radar Policy, `short_vol_radar.policy`,
`short_vol_radar.baseline`, runtime composition, direct Radar/evidence projection, trader-facing
Workbench wording, dependent Policy identity bindings, owning Authority/contract text, and focused
tests. The consumed temporary observation composition has been removed.

**Out:** TTE/Delta universe changes, target quantity, option-IV inversion, atomic combo selection,
Underwriting, admission, Position, Outcome, private API, RFQ/combo creation, execution, training,
replay, persistent diagnostics, deployment, commissioning, host inspection, or a 24-hour stability
Soak.

**Owning business calculator:** `packages/short_vol_radar/src/short_vol_radar/baseline.py`.

**Sole external-history validator:**
`packages/market_monitor/src/market_monitor/index_history.py`.

## Validation

- focused tests: `.venv/bin/pytest tests/test_policy_and_math.py tests/test_radar_engine.py tests/test_detector_and_atomic.py tests/test_trader_workbench.py tests/test_authority_and_architecture.py`;
- repository gate: `make check`;
- public observation: consumed and rejected; no rerun without new explicit Authority;
- inspect stdout/current funnel only; do not create a manifest, receipt, persisted Radar result,
  commissioning surface, or broad evidence package;
- if `SHADOW_CASE_OPENED == 0`, the fresh observation's durable Shadow Case file count must be zero.

## Definition of done

The exact Policy and calculator make a Radar activation a five-minute-sampled, multi-horizon,
conservative and time-persistent candidate; the Workbench explains the selected baseline; focused
and repository checks pass; one fixed-boundary observation reaches positive post-warmup applicable
scope and truthfully reports zero or more candidate Episodes; no pre-Shadow durable object is added;
the Task is removed from the completed final tree; and remaining combo/quote/Underwriting blockers
are reported without claiming strategy qualification or edge.
