# Optimatrix Product Constitution

**Status:** ACTIVE PRODUCT AUTHORITY

**Long-term product:** autonomous 0–3DTE options decision and trading system

**Current product slice:** Deribit BTC options defined-risk Short Vol — accepted Linear BTC-USDC
plus Inverse BTC product construction, production-public Shadow permission only

## North star

Optimatrix is first a continuously running opportunity-discovery and Shadow-learning product for a
trader. It must turn current public market facts into a bounded, ranked, explainable opportunity
view, decide whether an opportunity merits Shadow observation under one fixed Policy chain, and
learn only from facts observed strictly after that decision.

Market facts, Radar calculations, anomaly state, component-book counterfactuals, official combo
diagnostics, Underwriting state, Candidate state, and Workbench projections are **real-time
decision state** before Shadow enrollment. They may be known, degraded, or `UNKNOWN`; they are not
durable research records.

The first durable business object is `SHADOW_CASE_OPENED`. It exists only after one admitted
counterfactual trade, or a future explicitly selected no-trade control, is enrolled for strictly
future observation. Persistence serves trader review, AI research, and later qualification. It
never serves online UI, process commissioning, host monitoring, full-market reconstruction, or
proof that the software did not deceive itself.

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

Linear BTC-USDC and Inverse BTC share one opportunity, Underwriting, admission, Position, and
Outcome state machine, but they are separate economic products. Each runtime selects exactly one
product profile at startup and binds exactly one matching three-Policy chain for the full run. Every
active Policy chain and every durable Shadow Case binds one product identity. Existing Linear schema
v3 Cases bind `LINEAR_BTC_USDC_V1` implicitly and exclusively through their frozen Policy chain so
their bytes remain unchanged; Inverse schema v4 Cases bind `INVERSE_BTC_V1` explicitly. The product
identity declares the market family, quote and settlement currencies, price index, native
option-price unit, economic-semantics version, model-normalization rule, valuation-conversion rule,
payoff convention, standard fee rule, and Case schema version. A runtime must reject a mixed
product, mixed Policy chain, or mixed-leg structure before it can become Candidate or Case.

Linear BTC-USDC uses USDC-native premium, fees, settlement, payoff, and PnL. Inverse BTC uses BTC-
native premium, fees, settlement cashflow, and PnL; a declared BTC index converts those native
amounts to a current USD valuation boundary. The model-normalized premium and current USD valuation
are different quantities and may not be substituted. Defined strike width limits USD payoff, while
the corresponding BTC liability depends on settlement price. Public facts do not establish actual
account margin, which remains `UNKNOWN`.

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

An enrolled `SHADOW_CASE_OPENED` freezes the exact code and three Policy identities, decision
boundary, frozen two-leg structure, target quantity, one strictly later paired public option-book
snapshot, conservative stressed leg prices, standard public fees, and the minimum consumed decision
facts, including the protective-leg selector-rule identity and Candidate protective-leg count that
cannot be reconstructed after option scope is released. `enrollment_kind` discriminates an admitted
Candidate trade from one pre-outcome selected no-trade decision control; a control has no Candidate
or `SHADOW_ENTRY` identity. Strictly future bounded transitions and one terminal Outcome may then be
stored.

An opened Case without a terminal record after an unclean process loss is
`INCOMPLETE_UNCLEAN_EXIT`. It is never silently completed, resumed by a new runtime, or removed from
research denominators without an explicit offline rule.

### Qualification data

Qualification eligibility is determined later from persisted Shadow Cases by an offline,
pre-registered evaluator. A Case may be useful for research without being eligible for a
particular qualification denominator.

## Radar product meaning

The first Radar asks:

> Is target-size executable sell-side implied volatility unusually rich relative to the exact
> deployed conservative multi-horizon BTC realized-volatility baseline, and has that richness
> persisted long enough to merit structure review?

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

The Radar must show the trader what was found, which causal sampling interval and conservative
horizon produced the benchmark, why it matters, what is missing, and what would upgrade or
invalidate it. A hard-screen clue must be target-size, two-sided, uncrossed, official-tick-aware,
one-tick robust, time-persistent, and inside an explicit TTE/Delta risk bucket. Regime, surface,
legged-reference, and rank context are diagnostic only. It does not persist clue or atomic-quote
events and does not claim calendar forecasting, surface-relative edge, Policy edge, or
profitability.

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
Ordinary WATCH and ABSTAIN results remain current state and do not automatically create
rejected-counterfactual trades or durable controls. The authorized selected-decision rule freezes
one action-blind designation per Radar activation causal batch before Underwriting action or future
facts are known, with no fallback if that Episode remains `UNKNOWN` or ends. Its first evaluable
decision receives one strictly later paired refresh. A decision selected as Candidate and still
Candidate reuses ordinary admission. A refresh classified as WATCH or ABSTAIN may open one
explicitly tagged no-trade Case. A selected WATCH/ABSTAIN that refreshes to Candidate opens no
control and terminalizes as `REFRESHED_CANDIDATE_REQUIRES_CANONICAL_ADMISSION`; only a later
ordinary Candidate activation followed by its own strictly later pair may admit it. This research
branch is projected separately and never increments canonical Candidate, `SHADOW_ENTRY`, or
admitted-trade counts.

## Position and Outcome

After Case opening, one fixed Position Policy continuously returns `HOLD | CLOSE | UNKNOWN` from
strictly later public facts. `CLOSE` is an instruction, not a closing fact. The first CLOSE may
produce at most one durable `FIRST_CLOSE_LATCHED` Case transition.

A known Shadow Outcome requires the first eligible strictly later paired component-book close
snapshot: buy back the short at ask stressed up one tick and sell the same frozen protective long at
bid stressed down one tick, both at full quantity with both standard fees. Natural maturity without
such an exit may be `MATURE_UNKNOWN`. Clean stop, handled failure, and unclean process loss remain
distinct censoring/incomplete states. Unknown and censored post-enrollment results are valid
research data and must not be discarded as failed software.

## AI Researcher and qualification

The AI Researcher reads Shadow Cases, their strictly future Outcomes, and non-durable aggregate
funnel diagnostics. It may propose one declared Challenger. It may not rewrite online truth,
select outcomes after seeing them, approve itself, promote a Policy, or access execution.

Independent verification and strict receipts are reserved for future Challenger qualification,
Policy promotion, private execution, and capital/account safety. They are not public-Radar runtime
requirements.

## Hard invariants

1. Current decision facts are known at or before their causal boundary.
2. Shadow observations and Outcomes are strictly after `SHADOW_CASE_OPENED`; the enrollment
   decision and its paired witness are strictly pre-open.
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
8. The Online Runtime persists only bounded Shadow Case records; it does not persist Cohort,
   aligned-pair, Workbench, service, host, or full-market records.
9. One run binds one exact three-Policy chain and cannot hot-reload, train, promote, or tune it.
10. A new runtime never resumes an open Case from another runtime in the current slice.
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
