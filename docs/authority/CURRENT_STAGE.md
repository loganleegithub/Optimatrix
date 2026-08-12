# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY — STANDALONE LOCAL REBUILD

**Implemented Channel:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

**Permission:** deterministic offline Shadow simulation and at most one active-task-authorized,
bounded, read-only public Deribit current-Session snapshot after offline gates pass

**Continuous runtime:** `NONE`

**Stable Decision Case root:** `NONE_AUTHORIZED`

**Private/account/order permission:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current business baseline

The Radar MarketContext evidence denominator moved from `0 / 1` to `1 / 1` deterministic
`SessionDecisionUnit`s correctly distinguishing evidence-qualified context from `UNKNOWN`. Numeric
context without complete method, history coverage, public-book coverage, causal timing, and event
source evidence now stops before structure construction at `MARKET_CONTEXT_KNOWN = UNKNOWN`.

The Position-risk causal-boundary denominator moved from `0 / 1` to `1 / 1` deterministic
`FULL_ENTRY` Positions. A risk observation now freezes a recoverable two-sided exit duty without
using that observation as an exit price; only a strictly later, fresh, coherent, full-quantity
public-book observation can change short-risk state.

At base `13902c53e972f12721d2ef9d17de866fbda288a7`, `0 / 1` canonical repository product paths
selected one current-Session four-leg Iron Condor; `1 / 1` selected one single-side Credit Vertical.
The completed rebuild moved that product-path denominator to `1 / 1` four-leg paths and `0 / 1`
selectable legacy single-side paths.

The canonical live-market `SessionDecisionUnit` denominator remains `NOT_YET_MEASURED`. Offline
fixtures and one bounded public snapshot may falsify formulas, source translation, and current
reachability; they cannot estimate opportunity frequency, qualify the Policy, or prove Edge.

The measured `WRONG_CANONICAL_STRATEGY_OBJECT` blocker is closed for the repository product-path
denominator. The current product includes one four-leg decision object, one canonical funnel,
coherent four-leg attempt truth, fail-closed partial remediation, and eligibility-separated Outcomes.

## Accepted closure result

The measured `MARKET_CONTEXT_EVIDENCE_NOT_BOUND` false pass moved from `1 / 1` to `0 / 1`. The same
canonical unit remains in the denominator, but incomplete evidence now produces `UNKNOWN 0 / 1`,
all later stages remain `NOT_REACHED`, structure counts are unknown rather than zero, and no score,
structure, or Decision Case is created. A complete deterministic context still reaches the original
risk evaluation without changing Policy thresholds.

Market-context qualification is derived at the decision boundary from supported method identities,
matched historical coverage and cadence, complete requested public books, source/receive age and
causality, and event source/known-at facts. Workbench shows the exact evidence state and names the
current variance measures as unqualified proxies. This transient pre-Case evidence adds no database,
runtime, durable record, private method, or capital permission.

The measured `EXIT_INTENT_AND_EXECUTABLE_SAMPLE_SHARE_BOUNDARY` blocker moved from `1 / 1` to `0 / 1`.
Reusing the trigger books produces an exact `NOT_STRICTLY_FUTURE` blocker and leaves both shorts open.
A later eligible observation can project both shorts flat even when the long wings have no bid;
`SHORT_RISK_FLAT` then remains distinct from residual-wing duty and `PORTFOLIO_TERMINAL`. Missing or
stale required Position quotes create `RISK_CONTEXT_UNKNOWN`, not a zero Delta or calm state.

The Base normal-carry responsibility remains the four-leg product: any risk trigger freezes one
`BOTH_SIDES` exit duty. Side-specific duty is reserved for remediation of an already partial entry.
The intent boundary, material exit attempt/blockers, and public-book price projection survive local
test/simulation recovery through the existing `POSITION_CHECKPOINT`; no new event kind, stable root,
continuous runtime, private API, order, fill, hedge instrument, or capital permission was added.

The working branch now has `1 / 1` canonical product paths selecting and presenting the current-
Session four-leg Iron Condor and `0 / 1` selectable legacy single-side product paths. The measured
`WRONG_CANONICAL_STRATEGY_OBJECT` blocker moved from `1 / 1` to `0 / 1`.

The completed task's single authorized public snapshot attempt ended before a Decision with
`http.client.IncompleteRead(677343 bytes read)` while reading the Deribit instrument response. That
transport exception is now mapped to a truthful `DeribitSourceError` under deterministic
validation, but live reachability remains `UNVERIFIED`; no retry is authorized without a new task.

## Authorized acceptance boundary

The repository product boundary establishes:

- exact Deribit `08:00 UTC` Session and phase classification;
- one canonical `SessionDecisionUnit` and stage numerator/denominator/blocker projection;
- inverse BTC product, amount grid, target depth, legal tick, fee, payoff, valuation, and official
  settlement arithmetic;
- one joint asymmetric Iron Condor selected from legal Put and Call Credit Vertical components;
- high-VRP/calm review and high-VRP/Gamma/jump/breakout rejection without profitability claims;
- one causally coherent four-leg entry attempt;
- `FULL_ENTRY` as the only normal-carry and primary-strategy Outcome path;
- immediate bounded remediation for `PUT_SIDE_ONLY`, `CALL_SIDE_ONLY`, and
  `TWO_SIDES_INCOHERENT`;
- truthful `WINGS_ONLY` and `NO_ENTRY` Decision outcomes;
- separate `SHORT_RISK_FLAT`, residual-wing duty, and `PORTFOLIO_TERMINAL`;
- cross-process recovery of new-product test journals without adopting legacy responsibilities;
- public snapshot translation into the same product/funnel types with zero durable writes;
- reservation, but non-implementation, of the other three Channels.

## Legacy isolation boundary

The legacy V2 product implementation preserved in Git history at base `13902c5`, deployment
checkout at `/Users/logan/Optimatrix-runtime`, and Case root at
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9` are historical external assets for
this product boundary. New-product code may not read, write, import, translate, migrate, relabel,
recover, or count the legacy root or its 92 Cases. No compatibility translator, fallback product,
or shared stable root is authorized.

Local journals require an explicitly supplied non-legacy test/simulation directory. Authorizing a
stable new-product root, continuous process, or deployment requires a later task and permission
change.

## Non-claims

The current candidate has no continuous service, private API, account, margin, order, fill, RFQ,
combo creation, capital, actual execution, or settlement-action authority. Public prices are not
fills; Decision Cases are not positions; partial acquisition is not a full Condor; `UNKNOWN` is not
calm; a Gap is not an exit; a green test suite or responsive UI is not product progress. Offline
green tests and a single snapshot do not establish live-market acceptance, Policy qualification,
Edge, Alpha, win probability, or profitability.
