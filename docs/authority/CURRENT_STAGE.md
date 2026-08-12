# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `NONE`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_SHADOW_SCHEME_TWO_AND_CONTROL_OUTCOME_LIVE_CURRENT`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_CODE_6F286BF16444EBBE7B698F3ADA215F6F9BEE9CEC`

**Live commands:** `NONE_CONSUMED`

**Sole authorized closure:** `NONE`

## Current online boundary

The sole Online Runtime serves `127.0.0.1:8765` from the clean deployment checkout at
`/Users/logan/Optimatrix-runtime`, code identity
`6f286bf16444ebbe7b698f3ada215f6f9bee9cec`, and runtime identity
`sha256:e6092a3a99c2b8f286a428dc74f601ce268ca71133153ee94cc29935aed7104c`.
Its imports resolve `radar_runtime`, `short_vol_underwriting`, and `options_domain` from that exact
checkout.

PR `#53` merged the selected scheme-two Shadow trader surface together with the previously
uncommitted `design-qa.md`. PRs `#54` and `#55` recorded the outage fact and authorized the stable
launch. Live business acceptance then exposed one Control Outcome read-model contradiction; PR
`#56` fixed it by making Position and Outcome projections consume the same three already-owned
terminal Outcome kinds. All four PRs are merged and their topic branches are deleted.

The accepted live API is schema 7, `RUNNING / CURRENT / ready`, `KNOWN_COMPLETE 130 / 130`, zero
reconnects, and zero session gaps. All six declared GET and HEAD routes return 200. The Radar,
Underwriting, and Position Policy identities remain
`sha256:fd604c22b6f4a111955f432fe09647e93c38e914e81c4045905ca79b935bdc9d`,
`sha256:933dce3e4d9736b465aaca95a352ef8c3196592bfef04cf1f958442afe0f5e7d`, and
`sha256:8a00bacc13f5f3f2407ea3ff5060464e12d93c3f336f9d1f9d750a0621fa0ffe`.

## Accepted lifecycle result

The stable Case root remains
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The official active reader accepts
all 92 schema-v5 Cases. Terminal economics contain 44/44 known Outcomes: 37 `MARKET_EXIT` and 7
`CONTRACT_SETTLEMENT`. Strict terminal-sample integrity contains 23/23 known Outcomes: 16 market
exits and all 7 contract settlements. Twenty-five Cases remain pending; the separate descriptive
views retain 8 inherited incomplete-unclean Cases and 15 censored observation-unavailable Cases.
Qualification remains offline and window-specific.

The first stable recovery resumed 33 compatible responsibilities and naturally completed eight:
one market exit and seven official settlements. This moved the accepted known terminal count from
36 to 44 without replay, backfill, migration, relabeling, or historical rewrite. After the clean
projection-fix cutover, the current bounded state contains exactly 25 pending Positions and 25
pending Outcome observations: 20 admitted Shadow trades, 4 selected underwriting-decision
Controls, and 1 Radar score-band Control.

The naturally settled Radar Control Case
`sha256:977ba2a873a374dc779b209db190067cf2d6caf4361c9ba5150e6a0b260e17b5` exposed the defect before
the final cutover: its Position said `TERMINAL / SETTLED_KNOWN` while its Outcome projection said
`PENDING`. The deployed `6f286bf` reader reprojected that exact accepted Case as
`SETTLED_KNOWN / KNOWN_TERMINAL / CONTRACT_SETTLEMENT`, with official delivery price `63666.99`,
native net PnL `0.0000125 BTC`, and boundary-valued net PnL `0.79418275 USD_EQUIVALENT`. This check
was read-only and did not reinsert terminal history into the bounded current state.

## Accepted trader surface

The live scheme-two Shadow view renders 20/20 admitted positions and zero Controls. Every current
row is an expiry-grouped trader structure with frozen legs, current strike distance, TTE, immutable
first-CLOSE context, exit-working status, public close-price availability, and the next continuing
responsibility. The selected detail preserves `持仓责任持续`, the five trader sections, and
`PUBLIC SHADOW · READ ONLY`; it does not imply an order, fill, account position, or actual PnL.

Desktop selection, search, Both/Put/Call filters, the lifecycle/expiry filter popover, day/night
state, exact row/detail association, and the 800 x 1058 responsive drawer passed. At 800px the
document had no horizontal overflow, the 1000px risk book stayed inside its own scroller, and the
drawer began below the product chrome. PR `#56` changed no HTML, JavaScript, or CSS; the final live
desktop reload retained the same layout, 20 admitted rows, no Control label, no document-level
horizontal overflow, and no application console warning or error.

The selected design and `design-qa.md` were reviewed together before merge. `make check` passed
with 779 tests on the final implementation, and the GitHub repository gate passed on PR `#56`.
Tests and screen health are supporting evidence; the accepted business result is the recovered
responsibility chain, eight natural known Outcomes, truthful Control projection, and current
admitted-only trader book.

## Product truth and non-claims

The sole Online Runtime product remains `INVERSE_BTC_V1` under the unchanged fixed Radar,
Underwriting, and Position Policies. The current Position Policy identity and all nine frozen
predicate thresholds remain unchanged. No product, Case schema, durable record kind, Case root,
market source, order/fill/account boundary, or private permission changed.

Permission remains `PUBLIC_SHADOW`: production public facts and counterfactual economics only. A
public book or delivery price is not an order, fill, settlement action, actual position, account
PnL, or capital exposure. `PENDING`, `GAPPED`, a responsive Workbench, green tests, or a recovered
Case do not qualify a Policy or prove terminal economics. All task-scoped implementation, stop,
start, reader, API, and browser commands are consumed. A future restart, live probe, Policy change,
or new roadmap channel requires a new active task and explicit permission update.
