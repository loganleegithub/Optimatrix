# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY — STANDALONE LOCAL REBUILD

**Implemented Channel:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `IMPLEMENTATION`

**Sole authorized closure:** `BTC_0DTE_POSITION_RISK_CAUSAL_EXIT_V1`

**Permission:** deterministic offline Shadow simulation and at most one active-task-authorized,
bounded, read-only public Deribit current-Session snapshot after offline gates pass

**Continuous runtime:** `NONE`

**Stable Decision Case root:** `NONE_AUTHORIZED`

**Private/account/order permission:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current business baseline

The active Position-risk closure starts from `0 / 1` deterministic `FULL_ENTRY` Positions that keep
a risk-trigger intent and the first executable exit observation on separate causal boundaries. The
current owner can create an instruction and consume the same observation as its counterfactual exit;
the earliest blocker is `EXIT_INTENT_AND_EXECUTABLE_SAMPLE_SHARE_BOUNDARY`.

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

The working branch now has `1 / 1` canonical product paths selecting and presenting the current-
Session four-leg Iron Condor and `0 / 1` selectable legacy single-side product paths. The measured
`WRONG_CANONICAL_STRATEGY_OBJECT` blocker moved from `1 / 1` to `0 / 1`.

The completed task's single authorized public snapshot attempt ended before a Decision with
`http.client.IncompleteRead(677343 bytes read)` while reading the Deribit instrument response. That
transport exception is now mapped to a truthful `DeribitSourceError` under deterministic
validation, but live reachability remains `UNVERIFIED`; no retry is authorized without a new task.

## Authorized acceptance boundary

The active closure must establish:

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
