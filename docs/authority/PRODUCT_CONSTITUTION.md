# Optimatrix Product Constitution

**Status:** ACTIVE PRODUCT AUTHORITY

**Long-term product:** autonomous 0–3DTE options decision and trading system

**Current product slice:** Deribit `INVERSE_BTC_V1` options defined-risk
`INVERSE_BTC_SHORT_VOL_V2`, with process-independent Shadow Case Outcomes under
production-public Shadow permission

## Product roadmap (non-authorizing)

The roadmap is a 2×2 product direction, not an accepted runtime surface. Only the upper-left
channel is implemented or authorized. `INVERSE_BTC_SHORT_VOL_V2` is the sole repository
implementation identifier for that channel; the economic product remains `INVERSE_BTC_V1`.

| Channel | Implementation | Policy | Runtime authority |
| --- | --- | --- | --- |
| `INVERSE_BTC_SHORT_VOL` (`INVERSE_BTC_SHORT_VOL_V2`) | `IMPLEMENTED` | fixed V2 Inverse three-Policy chain | `PUBLIC_SHADOW` |
| `INVERSE_BTC_LONG_GAMMA` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |
| `INVERSE_ETH_SHORT_VOL` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |
| `INVERSE_ETH_LONG_GAMMA` | `UNIMPLEMENTED / UNKNOWN` | `NONE` | `NONE` |

An unimplemented roadmap cell creates no product specification, module, Policy, selector, runtime,
Case schema, task, or permission. It cannot be inferred from the implemented BTC Short Vol channel.

## North star

Optimatrix is first a continuously running opportunity-discovery and Shadow-learning product for a
trader. It must turn current public market facts into a bounded, ranked, explainable opportunity
view, decide whether an opportunity merits Shadow observation under one fixed Policy chain, and
learn only from facts observed strictly after that decision.

Market facts, Radar calculations, anomaly state, component-book counterfactuals, official combo
diagnostics, Underwriting state, Candidate state, and Workbench projections are **real-time
decision state** before Shadow enrollment. They may be known, degraded, or `UNKNOWN`; they are not
durable research records.

The first durable business object is `SHADOW_CASE_OPENED`. For an admitted trade it creates one
process-independent Shadow Entry aggregate: the frozen `shadow_entry_identity`, contracts,
quantity, entry prices, fees, entry time, economics, product, and Policies survive every process.
A runtime owns only one bounded Observation Segment over that Entry. Persistence serves online
recovery, trader review, AI research, and later qualification. It never serves process
commissioning, host monitoring, full-market reconstruction, or proof that the software did not
deceive itself.

Every admitted Entry without a mature `SHADOW_CASE_OUTCOME` is non-terminal. A later runtime using
the same stable Case repository automatically restores all compatible non-terminal admitted
Entries. It never reconstructs Candidate, Underwriting, Radar Episode, or missed market facts.
The interval between Observation Segments is explicitly `HANDOFF_GAP`; recovery data starts
`UNKNOWN` until fresh public facts settle. A gap is observation quality, not a Position predicate,
and cannot synthesize `CLOSE`.

A qualification Cohort is an offline, pre-registered view derived from completed Shadow Cases. The
Online Runtime does not own Cohort membership, windows, aligned-pair records, qualification
manifests, or promotion receipts.

## Current permission and non-claims

The current permission is `PUBLIC_SHADOW`:

- Deribit production public data only;
- no credentials, private/account API, balance, margin, order, fill, capital, settlement action, or
  actual exposure;
- a public quote is not a fill;
- a `SHADOW_CASE_OPENED` record is a simulated research enrollment, not a position;
- current Policies are unqualified and do not establish edge or profitability.

Permission comes only from [`CURRENT_STAGE`](CURRENT_STAGE.md). Code, tests, files, commits, green
CI, or historical runs grant no additional authority.

## Product identity and unit boundary

The sole Online Runtime product is `INVERSE_BTC_V1`. Startup binds its one canonical product
specification and exact matching Radar, Underwriting, and Position Policies for the full run. There
is no product selector, fallback product, compatibility profile, or in-process product switch.
Every active Policy chain and every durable Shadow Case binds the same Inverse product identity. A
foreign product, mismatched Policy chain, or non-Inverse leg fails before Candidate or Case.

The product identity declares the market family, quote and settlement currencies, `btc_usd` price
index, BTC-native option-price unit, economic-semantics version, model-normalization rule,
valuation-conversion rule, payoff convention, standard fee rule, and Inverse Case schema version.
Premium, fees, settlement cashflow, and PnL are BTC-native; the causal BTC index converts those
native amounts to an explicitly labeled current USD valuation boundary. Model-normalized premium
and current USD valuation are different quantities and may not be substituted. Defined strike
width limits USD payoff, while the corresponding BTC liability depends on settlement price. Public
facts do not establish actual account margin, which remains `UNKNOWN`.

## Product funnel

The first slice is managed as one measurable funnel:

```text
APPLICABLE_MARKET_SCOPE
→ RADAR_KNOWN
→ ANOMALY_ACTIVE
→ STRUCTURE_REVIEWABLE
→ COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE
→ UNDERWRITING_EVALUABLE
→ CANDIDATE
→ SHADOW_CASE_OPENED
→ SHADOW_CASE_OUTCOME
```

The canonical Case stages count admitted Candidates. Selected no-trade Cases use a separate
research projection and cannot change those conversion counts.

Every stage has an explicit numerator, denominator, and blocker reason. A task must move one stage,
reduce the largest measured blocker, or remove a proven non-product subsystem that blocks the
funnel. Test count, object count, evidence count, runtime duration, and document count are not
product progress.

The primary blocker is the earliest material loss in this funnel. It may be `UNKNOWN`, but it may
also be known absence such as `NO_PROTECTIVE_COMPONENT`,
`NO_TARGET_SIZE_COMPONENT_BOOK_QUOTE`, known ineligibility, WATCH thresholds, or paired
admission-refresh failure. `NO_ACTIVE_COMBO` is a parallel exchange diagnostic, not a Shadow-funnel
loss.

## Stage-specific loss functions

The product does not apply execution-stage risk preferences to every earlier stage.

### Radar and trader review

False-positive cost is lower than at admission because no order or Shadow Case follows automatically
from display, but it is not zero: an over-broad Radar makes every downstream conversion rate and
blocker economically misleading. Radar should therefore expose selective, time-persistent bounded
clues with the causal benchmark, confidence, missing facts, and upgrade/invalidation
conditions. An unrelated `UNKNOWN` must not erase a known positive witness.

### Underwriting and Shadow admission

A Candidate or Shadow admission requires its declared facts and executable economics. Missing
required facts remain `UNKNOWN` and cannot create a Candidate or Case. The trader-facing review may
still show the incomplete opportunity and the precise blocker.

### Real execution

Future private execution remains a separate fail-closed security, account, capital, and order
boundary.

## Data classes

### Transient market facts

Catalog, platform, clock, index, ticker, order-book, RPC, and continuity facts are maintained in
bounded memory. Only the rolling history consumed by a declared causal feature may remain in
memory. Normal ticks and full books are not persisted.

### Current opportunity state

Radar hard-screen calculations, diagnostic regime/surface/legged/rank context, component-book
counterfactuals, atomic diagnostics, Underwriting, Candidate, admission, current Position
assessment, health, readiness, and funnel diagnostics are current in-memory state. Workbench
snapshots are immutable bytes for readers but are not durable records.

### Shadow Case data

An enrolled `SHADOW_CASE_OPENED` freezes the origin code/runtime and exact three Policy identities,
decision boundary, frozen two-leg structure, target quantity, one strictly later paired public
option-book snapshot, conservative stressed leg prices, standard public fees, and the minimum
consumed decision facts. In schema v5 those facts include the same canonical V2 score-packet shape
at selection and entry refresh, plus the protective-leg selector-rule identity and Candidate
protective-leg count that cannot be reconstructed after option scope is released.
`enrollment_kind` discriminates an admitted Candidate trade, one selected HIGH Underwriting
decision control, and one sampled LOW/MID Radar-score control; either control has no Candidate or
`SHADOW_ENTRY` identity. Strictly future bounded transitions and one terminal Outcome may then be
stored. For a new admitted Entry, its origin `SHADOW_CASE_SEGMENT_OPENED` freezes the
`entry_position_baseline` needed after restart: the entry index and short-leg mark IV with their
exact source identities and boundaries. Missing accepted source references prevent a schema-v5
Case from opening; they are never inferred or added later.

An opened Case without a terminal record after an unclean process loss is
not silently completed. Its open Observation Segment is `INCOMPLETE_UNCLEAN_EXIT`, while the
admitted Entry remains non-terminal and is recovered into a new `HANDOFF_GAP` segment. Missing
facts across the gap remain `UNKNOWN` and the gap permanently changes observation quality. Selected
no-trade Controls are not Entry aggregates and retain their bounded terminal Case lifecycle.

### Qualification data

Qualification eligibility is determined later from persisted Shadow Cases by an offline,
pre-registered evaluator. A Case may be useful for research without being eligible for a
particular qualification denominator.

## Radar product meaning

The first Radar asks:

> Given one causal, target-size executable option snapshot, does a frozen combination of premium
> richness and observable path/liquidity quality rank this opportunity above the V2 review
> threshold, and has that state persisted long enough to merit formal structure review?

The answer is an ordinal opportunity-filter score, never an oracle, probability, expected return,
or sufficient condition for profit. It aims to raise the conditional quality of what reaches
Underwriting while retaining bounded LOW/MID no-trade Controls so future Shadow Outcomes can
falsify the ranking. A numeric `65` score does not mean `65%`.

It separately reports whether an existing official Deribit combo happens to expose the required
target-size 1:1 protective credit vertical. Detector truth and the atomic diagnostic remain
distinct:

```text
detector = UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE
atomic = NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO |
         NO_TARGET_SIZE_CREDIT_QUOTE | PUBLIC_ATOMIC_QUOTE_AVAILABLE
```

`NO_ACTIVE_COMBO` means only that the exact exchange-managed combo is not currently active. It does
not mean the two option legs lack public depth, the defined-risk structure cannot be priced, or the
Shadow counterfactual is unavailable.

The Radar must show the trader the score interval, LOW/MID/HIGH band, premium/risk decomposition,
causal UTC-epoch-aligned five-minute `average_price` baseline horizons, coverage/missing mask,
bucket leader, and upgrade/invalidation condition. A clue must be target-size, two-sided, uncrossed,
official-tick-aware, one-tick robust, time-persistent, and inside an explicit TTE/Delta risk bucket.
Local surface and adjacent-term residuals are bounded optional adjustments; adverse semivariance,
jump share, and target-book liquidity are required quality inputs. Public OI times absolute gamma
is an unsigned concentration diagnostic only: dealer sign remains `UNKNOWN` and it cannot enter the
score. The runtime persists no clue, score, quote, or review before Case opening and claims no
calendar forecast, signed dealer GEX, pin target, Policy Edge, or profitability.

Optional surface/term adjustments require their exact contributing ticker source times to be
within the fixed cross-sectional skew budget and ATM proxies to be within the fixed Delta distance.
Failure of that optional coherence test reduces score coverage rather than fabricating a neutral
value or erasing otherwise known A/D/E evidence. Every future Case binds selection to the actual
Episode-activation packet even when another HIGH member in the same batch was designated first.

## Underwriting and admission

A fixed Underwriting Policy compares the conservative full-quantity two-leg net premium with
declared path, jump, tail, liquidity, cost, and uncertainty reserves. The entry counterfactual sells
the short leg at bid stressed down one official tick, buys the frozen protective leg at ask stressed
up one official tick, and reserves both standard option fees. It returns
`CANDIDATE | WATCH | ABSTAIN` only when evaluable; unavailable Underwriting has no economic action.
Radar's Top-3 protective review is display-only. After complete positive option scope, the formal
Underwriting selector classifies every legal target-size protective quote, prefers `CANDIDATE` over
`WATCH` over `ABSTAIN`, then applies one declared deterministic predicate-margin order before
freezing the chosen long for the Episode. A potentially legal leg with unknown required input keeps
selection `UNKNOWN`; known inactive or quantity-ineligible legs are excluded.

`SHADOW_ENTRY` requires a still-valid Candidate and exactly two strictly later, causally bound public
option-book responses for the frozen short and protective long. Both legs must cover the full target
quantity under the same conservative pricing rule and satisfy the pair session, continuity, and
skew budgets frozen in the Policy chain. That transition opens the admitted Shadow Case.
Ordinary WATCH and ABSTAIN results remain current state and do not automatically create rejected
counterfactual trades. HIGH activation batches retain the one action-blind selected Underwriting
decision and ordinary Candidate admission semantics. When a causal batch contains no HIGH
activation, the Radar may designate at most one already-confirmed LOW/MID research-review Episode
using the frozen future-blind stratum and member hashes. It then uses the same formal protective-leg
selector and one strictly later paired refresh as ordinary admission. Any evaluable refresh opens
one explicitly tagged non-admitted Radar-score Control, even if refreshed Underwriting happens to
be Candidate; it never retroactively admits, consumes a slot, creates a `SHADOW_ENTRY`, or exposes
capital. Failed/unknown refresh opens no Case and has no fallback. The Case-derived research
denominator is therefore explicitly conditional on successful paired refresh and Case opening.

## Position and Outcome

After Case opening, one fixed Position Policy continuously returns `HOLD | CLOSE | UNKNOWN` from
strictly later public facts inside the current Observation Segment. `CLOSE` is an instruction, not
a closing fact. The first CLOSE and scheduling of its only paired close attempt are one durable
transition. A restart never creates a second first CLOSE or schedules a second attempt. If the one
scheduled attempt is pending when a process is lost, recovery reports that attempt `UNKNOWN` and
does not retry it.

A known Shadow Outcome requires the first eligible strictly later paired component-book close
snapshot: buy back the short at ask stressed up one tick and sell the same frozen protective long at
bid stressed down one tick, both at full quantity with both standard fees. Natural maturity without
such an exit may be `MATURE_UNKNOWN`. Clean stop, handled failure, and unclean process loss remain
distinct Observation Segment endings and do not terminate an admitted Entry. After recovery and
fresh facts, the Entry may still form a mature economic Outcome. Any Entry whose segment chain has
a gap stores `observation_quality=GAPPED` and `qualification_eligible=false`; known economics remain
truthful, but the result cannot enter a continuous-observation qualification Cohort.

## AI Researcher and qualification

The AI Researcher reads Shadow Cases, their strictly future Outcomes, and non-durable aggregate
funnel diagnostics. It may propose one declared Challenger. It may not rewrite online truth,
select outcomes after seeing them, approve itself, promote a Policy, or access execution.

Independent verification and strict receipts are reserved for future Challenger qualification,
Policy promotion, private execution, and capital/account safety. They are not public-Radar runtime
requirements.

## Hard invariants

1. Current decision facts are known at or before their causal boundary.
2. Shadow observations are strictly ordered inside one runtime Observation Segment. Cross-runtime
   order is established only by the durable segment predecessor chain; an interval between
   segments is `HANDOFF_GAP`, never imputed continuous observation.
3. Missing, stale, discontinuous, incomplete, or contaminated required facts remain `UNKNOWN` at
   the smallest consumer.
4. A known positive witness is not erased by unrelated missingness; negative absence claims require
   complete relevant scope.
5. Detector truth, diagnostic review/rank, component-book counterfactual, official atomic
   diagnostic, Underwriting action,
   admission, Position action, Shadow Outcome, future order state, and actual fill state remain
   distinct; diagnostic context cannot create downstream truth.
6. Shadow entry and close economics require full-quantity public depth on both frozen option legs,
   the declared one-tick adverse stress, both standard fees, and strictly later paired snapshots.
   They are counterfactuals, not orders, fills, atomic quotes, or liquidity reservations.
7. Pre-Shadow durable business record count is exactly zero; Shadow begins only at explicit Case
   enrollment.
8. The Online Runtime persists only bounded Shadow Entry aggregate and Observation Segment
   records; it does not persist Cohort, aligned-pair, Workbench, service, host, or full-market
   records.
9. One run binds one exact three-Policy chain and cannot hot-reload, train, promote, or tune it.
10. A runtime never owns an admitted Entry. Under the stable repository lease, every new runtime
    automatically restores all compatible non-terminal admitted Entries and opens a new segment;
    Controls and pre-Shadow state are never restored.
11. Qualification criteria are frozen before evaluating a derived Cohort.
12. Private execution remains a separate authorization and security boundary.

## Permanent non-goals for the current slice

- full-market tape, replay platform, feature store, database, generic event bus, workflow engine, or
  microservice split;
- online Cohort manager, automatic no-trade counterfactual for every rejection, or per-tick durable
  Position history;
- application commissioning, host PID/log inspection, resource acceptance controller, manifest,
  receipt chain, validator-of-validator, or duplicated business schema;
- automatic Policy training, qualification, promotion, or private execution.
- database, fencing service, generic event log, per-tick Position persistence, market replay, or
  synthesis of facts across a process gap.
