# Task — Inverse BTC Short Vol V2 closed loop

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** ONE V1 CLEAN STOP, ONE FRESH-ROOT V2 START, ONE BOUNDED READ-ONLY SMOKE

**Base commit:** `04ff60f1b7763e00b6f4d1f1f2b5e7981b307278`

**Target branch/PR:** `codex/inverse-btc-short-vol-v2-direct-replacement`; one Draft PR

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION.md`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE.md`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR.md`](../docs/contracts/SHORT_VOL_RADAR.md),
[`SHORT_VOL_UNDERWRITING_POSITION.md`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md), and
[`SHORT_VOL_SHADOW_CASE.md`](../docs/contracts/SHORT_VOL_SHADOW_CASE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN -> ANOMALY_ACTIVE -> SHADOW_CASE_OUTCOME`

**Baseline:** `0 / 1` online Radar Policies emit a V2 market-structure score whose exact
selection-time inputs can be compared with one strictly later canonical Shadow Outcome.

**Primary blocker:** `V2_SCORE_TO_FUTURE_OUTCOME_LINK_ABSENT` (`1 / 1` active online Radar Policy)

**Expected user-visible delta:** Workbench exposes the sole
`INVERSE_BTC_SHORT_VOL_V2` ordinal score, score interval/band, premium-versus-risk decomposition,
feature coverage, bucket leader, selection-to-entry drift, and Case-derived score-band Outcome
research without calling the score a probability, oracle, Edge, or profit forecast.

**Durable-data effect:** the first durable boundary remains `SHADOW_CASE_OPENED`. New schema-v5
Cases freeze one minimal V2 score packet at selection and one at the strictly later paired entry
refresh. No score, review, rejected opportunity, refresh attempt, Workbench snapshot, or run summary
is written before a Case opens. Existing V1 roots and records are not read, migrated, rewritten, or
deleted by this task.

**Complexity added:** one pure V2 score calculator, one canonical score-packet value schema reused
at selection and entry refresh, one bounded Radar-score Control enrollment path, and one Case-only
offline report command.

**Complexity deleted:** V1 ratio-only admission semantics, identical TTE-band baselines, and the V1
Workbench channel identity from the new V2 code path. No V1 compatibility runtime is added.

## Business closure

**Given:** one causal Inverse BTC option evaluation with current target-size public books, exact
five-minute index-history suffix, known core path/liquidity factors, and any available optional
surface/term/OI diagnostics.

**When:** the sole V2 Radar computes the frozen score interval, applies band-specific persistence,
and a HIGH admission or deterministically sampled LOW/MID Control obtains its one strictly later
paired entry witness.

**Then:** the trader sees the exact score and blocker now, and any opened schema-v5 Case contains
the selection and entry-refresh packets needed to relate the decision to its future canonical
stressed Outcome without reconstructing market history.

**Valid zero/UNKNOWN:** no HIGH clue or no mature Outcome is truthful but does not by itself satisfy
the closure. Missing core score inputs yield `UNKNOWN`; missing optional surface/term/OI facts lower
coverage and remain explicit without fabricated neutral values. Failed or unknown paired refresh
opens no Case and therefore contributes no offline Case denominator.

**Cheapest falsification:** pure score/state-machine tests plus one deterministic reducer fixture
that opens each authorized schema-v5 enrollment kind and round-trips it through the official Case
reader and offline report.

## Change declarations

**Market/Decision input contract change:** index-chart request range becomes `2d`; the Radar uses
the existing validated five-minute `average_price` history, band-specific horizons and persistence,
current target-size book facts, surface/term diagnostics when available, core path/liquidity
quality, and unsigned OI/gamma concentration only as a non-decision diagnostic.

**Decision Policy change:** V1 stressed IV/RV ratio hysteresis is replaced by the frozen V2 ordinal
score, `lower >= 65` activation, `upper <= 50` clear, band-specific observation cadence, one bucket
leader, and bounded deterministic LOW/MID Control sampling. V2 is the sole online Radar Policy;
there is no parallel V1 detector or admission path.

The launch score is one content-identified expert prior, not a fitted probability:

```text
A = piecewise stressed executable IV / V2 reference RV: 1.00 -> 0, 1.20 -> 0.80, 1.30 -> 1
S = clip((stressed executable-bid IV midpoint - local mark IV) / 0.10, -1, 1)
T = clip((current-expiry ATM mark IV - immediate next-longer-expiry ATM mark IV) / 0.10, -1, 1)
D = clip(1 - 0.5 * adverse semivariance share - 0.5 * jump share, 0, 1)
E = 0.7 * spread quality + 0.3 * consumed-depth quality
PremiumEvidence = clip(A + 0.10 * S + 0.05 * T, 0, 1)
RiskQuality = 0.60 * D + 0.40 * E
Score = 100 * PremiumEvidence * (0.40 + 0.60 * RiskQuality)
```

Spread quality is one at one target-spread tick and zero at ten ticks, linearly clipped between;
consumed-depth quality is one at two total bid-plus-ask levels and zero at ten, likewise clipped.
Missing S or T contributes no adjustment but remains explicitly missing. D and E are required for a
known score. Every mapping, weight, knot, and threshold belongs to the Radar Policy identity.

The V2 reference variance is
`max(floor, 0.5 * max(window variance rates) + 0.5 * mean(window variance rates))`. Bands use exact
five-minute index-chart `average_price` returns: `30/120/360` minutes with `60 s` observation
separation for 45m–6h; `120/360/720` with `150 s` for 6h–24h; and `360/720/1440` with `300 s` for
24h–72h. The 30m–45m band is review-only. Each score band requires three distinct observations;
clear requires two under the same band separation.

**Outcome/evaluation contract change:** Case schema changes from v4 to v5 and stores two instances
of the same minimal V2 score packet. The canonical one-tick-stressed two-leg Outcome remains
primary; raw-book sensitivity is derived offline with fees recomputed from raw VWAP. The report is
conditional on successful paired refresh and Case opening and keeps continuous and gapped views
separate.

**Stage/authorization change:** H1 authorized repository implementation and offline verification.
H2 now authorizes one exact clean handoff: official-reader inventory of the current V1 root, one
clean stop, in-place preservation of that root, creation of the previously absent stable V2 root at
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2`, one canonical V2 start on loopback port
8765 from a clean task-branch commit, and one bounded read-only smoke. It authorizes no retry,
second root, V1 Case copy/migration/recovery, threshold change, source-contract probe, process
supervision, host inspection, or private action.

LOW is `[0, 50)`, MID is `[50, 65)`, and HIGH is `[65, 100]`. The leader key is
`(TTE band, expiry, option type, Delta bucket)`. Before activation, a leader change resets
confirmation; after confirmation, that leader is frozen until its HIGH or research-review Episode
ends. If a causal batch contains any new HIGH activation, no LOW/MID Control is selected. Otherwise
the batch chooses at most one confirmed LOW/MID research Episode: when both strata exist a
future-blind hash chooses the stratum with probability `1/2`, then a second canonical hash chooses
one member; with one stratum it chooses one member directly. The opened Case records exact stratum
counts and the reduced rational inclusion probability. There is no fallback after the chosen
refresh becomes unavailable or `UNKNOWN`.

## Scope

**In:** V2 Policy chain and identities; pure score/features; existing Radar reducer/state machine;
existing formal protective-leg selector and paired refresh; schema-v5 Case writer/reader; Workbench
server projection/rendering; Case-only offline score report; Authority/contracts/tests required by
those changes; one official-reader V1 inventory; one V1 clean stop; in-place V1-root preservation;
one fresh non-temporary V2 root; one V2 start; one bounded read-only smoke.

**Out:** retry or automatic restart; V1 Case copy, migration, rewrite, deletion, or V2 recovery;
second V2 root; process supervision or host inspection; private/account/order/fill/capital behavior;
second runtime; database; replay/tape; pre-Case persistence; full-surface model; signed dealer GEX;
auto-training; V2 probability or Edge claims; Long Gamma or ETH roadmap cells.

**Owning module:** `short_vol_radar` owns score/features/state; `short_vol_underwriting` consumes the
packet for enrollment and owns schema-v5 Case/Outcome; `radar_runtime` composes and projects without
recalculating strategy truth.

## Validation

- focused tests: authority, Radar Policy/score/engine/reducer, Underwriting Control, Case store,
  Workbench/frontend, and offline report suites;
- repository gate: `make check`;
- public observation: one H2 bounded read-only smoke after the only V2 start;
- no direct source-contract probe, market-frequency gate, Policy tuning, repeated start, or
  runtime-duration acceptance.

## Definition of done

The V2 score drives the only repository Radar path; trader-visible score truth and Case-derived
future-Outcome linkage exist; LOW/MID sampling is bounded, future-blind, and never becomes a
Candidate or admitted Entry; schema-v5 conserves the product/Policy/economic chain; zero pre-Case
files is proven; direct and full checks pass; one Draft PR contains the bounded H1+H2 closure; the
V1 process is clean-stopped with its root preserved in place; the sole V2 process runs from a clean
commit on the fresh stable non-temporary root; and the one bounded smoke confirms exact V2
product/Policy/schema identity and truthful public currentness without claiming an Outcome or Edge.
