# Task — INVERSE BTC Short Vol V2 causal coherence repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Base commit:** `4a09be3058a9b2bd8c3b9b29c45f9af41602d242`

**Target branch/PR:** `codex/inverse-btc-short-vol-v2-coherence-repair` / one Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE -> SHADOW_CASE_OPENED`

**Baseline:** `0 / 1` declared non-designated, delayed-HIGH admission path preserves the
activation HIGH packet; `0 / 3` score-coherence rules are complete for cross-sectional ticker
skew, cross-Call/Put dependency invalidation, and score-relevant ticker countability.

**Primary blocker:** `V2_SCORE_CAUSAL_COHERENCE_INCOMPLETE` over those four directly falsifiable
paths.

**Expected user-visible delta:** every future schema-v5 Case freezes the actual Episode-activation
score packet at selection; optional S/T adjustments expose and enforce their source-coherence
boundary; E uses the declared tick ladder; the offline report separates enrollment kinds and
caller-declared active-root pending Cases.

**Durable-data effect:** no new durable record and no Case-schema change. Future schema-v5 Cases
freeze the expanded policy-recomputable S/T raw-input layout under one new fixed three-Policy
identity chain. Existing live and historical roots are neither read nor changed and are not
compatible with the new chain.

**Complexity added:** two Radar Policy score-source limits, source timestamp/skew projection, one
piecewise tick-distance function, one explicit offline active-root mode, and direct regression
tests.

**Complexity deleted:** current-score fallback for delayed HIGH admission, same-option-type-only
surface invalidation, forward-only ticker countability, mixed-enrollment report aggregation, and
the false classification of a caller-declared active Control as an unclean exit.

## Business closure

**Given:** one settled causal batch may activate multiple HIGH bucket Episodes, while S/T consume
cross-instrument ticker facts and E consumes exchange tick metadata.

**When:** a non-designated HIGH becomes an evaluable Candidate later, or a score-relevant peer
ticker/tick-regime fact changes.

**Then:** the owner opens any later Case from the frozen activation HIGH packet plus one strictly
later refresh packet, and the Radar recomputes/counts exactly the affected score with explicit
optional-feature source coherence.

**Valid zero/UNKNOWN:** missing or over-skew S/T remains a partial score with an explicit factor
reason and zero optional adjustment. It satisfies this closure; a missing A, D, E, core market
fact, or strictly-later refresh remains `UNKNOWN` and cannot open a Case.

**Cheapest falsification:** one multi-HIGH owner/Case test, pure S/T and tick-ladder tests, reducer
dependency/countability tests, and offline report active/inactive-root tests.

## Change declarations

**Market/Decision input contract change:** S/T freezes the exact contributing ticker source skew,
accepts it only within `6000 ms`, and requires each ATM proxy to be within `0.05` absolute Delta of
ATM. E measures spread across the complete native tick ladder.

**Decision Policy change:** Radar Policy schema advances from v8 to v9 with the two exact source
coherence members. Existing score weights, knots, thresholds, TTE/Delta bands, persistence, and
Underwriting/Position numeric thresholds do not change; the three content identities change.

**Outcome/evaluation contract change:** the Case-only report adds pending-open and enrollment-kind
strata without weighting, causal, probability, or profitability claims. Case schema and Outcome
arithmetic do not change.

**Stage/authorization change:** authorize repository implementation and offline tests only. The
current H2 runtime, port `8765`, and all external state roots remain untouched; deployment requires
a later explicit task and fresh compatible root boundary.

## Scope

**In:** fixed Inverse Policy artifacts/identities; Radar score, Policy, review, and native tick
owners; runtime causal dependency/countability composition; HIGH packet handoff; Case-only report
and CLI flag; Workbench factor wording; owning contracts/Authority/README; direct tests.

**Out:** live HTTP/source probes, process stop/start/restart, state-root inventory or migration,
Case schema changes, Control recovery/persistence, extra Controls, replay/database/tape, model
calibration, weight/threshold tuning, signed dealer GEX, qualification, promotion, private account,
order, fill, or capital behavior.

**Owning module:** `short_vol_radar`, with bounded composition fixes in `radar_runtime`, one
activation-packet handoff in `short_vol_underwriting`, and tick semantics in `options_domain`.

## Validation

- focused tests: Radar score/review/engine, options-domain tick ladder, reducer/fact-boundary,
  selected-decision/Case, offline report, Workbench frontend, Policy/Authority;
- repository gate: `make check`;
- public observation: `NOT_APPLICABLE` and forbidden by this task;
- no manifest, receipt, commissioning controller, host inspection, replay, or broad evidence
  package.

## Definition of done

All four baseline paths become directly green; future packets are policy-recomputable with exact
coherence inputs; trader wording and report strata match the implemented estimand; the three fixed
Policy identities are internally consistent; focused checks and `make check` pass; no live/root
operation or new durable object occurs; and the bounded branch is pushed as one Draft PR.
