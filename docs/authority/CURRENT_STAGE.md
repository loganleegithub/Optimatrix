# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:**
`RADAR_LONG_OBSERVATION_AUTHORIZED`

**Production Short Vol Radar:** `CANDIDATE_GENERATOR_FROZEN_FOR_OBSERVATION`

**Persistent service:** `BOUNDED_OBSERVATION_ONLY_NO_DEPLOYMENT`

**Live commands:** `ONE_FIXED_43200_SECOND_PRODUCTION_PUBLIC_READ_ONLY_OBSERVATION`

**Sole authorized closure:** `SHORT_VOL_RADAR_CREDIBLE_CLUE_FREEZE`

## Current truth

The simplified implementation conforms to the Shadow Case data boundary. Market, Radar, atomic
availability, Underwriting, Candidate, admission attempts, and Workbench state are in memory. A run
with no Shadow admission writes zero Shadow Case business files. The first durable record is
`SHADOW_CASE_OPENED`; only first CLOSE and terminal Outcome may follow. A minimal reader marks an
opened-only Case after an unclean exit as `INCOMPLETE_UNCLEAN_EXIT`.

The one authorized 900-second public-only A1 observation was consumed and stopped cleanly. After
the fixed Radar Policy's real index baseline became available, it counted `1,556,097`
`APPLICABLE_MARKET_SCOPE` evaluations and `1,556,097` `RADAR_KNOWN` evaluations: `100%`, with zero
post-warmup Radar UNKNOWN.

Startup and recovery remained separately visible: `322,817` applicable evaluations, `179,021`
known evaluations, and `143,796` UNKNOWN evaluations. Their bounded reasons were `INDEX_WARMUP`
`64,283` and `POST_STATUS_BOOTSTRAP_REQUIRED` `79,513`; neither was counted as a steady-state
blocker.

The observation naturally reached `146` distinct anomaly Episodes and `146` reviewable structures.
None reached an available official atomic quote because all `146` were blocked by
`NO_ACTIVE_COMBO`. The earliest material funnel loss therefore moved from apparent Radar warmup to
`PUBLIC_ATOMIC_QUOTE_AVAILABLE / NO_ACTIVE_COMBO`. No Shadow Case opened and the durable Shadow Case
file count remained zero.

The A1 observation used the then-current exact Radar, Underwriting, and Position Policy chain. The
rejected first A2 candidate changed only its benchmark and persistence while holding the broad
TTE/Delta universe fixed; the current explicitly authorized credible-clue closure supersedes that
restriction only for Radar risk buckets and hard-screen facts. Target quantity, option inversion,
official atomic semantics, causality, `UNKNOWN`, and full-quantity official atomic entry/exit
requirements remain unchanged. No runtime is deployed and no private/account/order/fill/capital
capability exists.

The one authorized 43,200-second A2 observation was consumed at code commit `bf0475982950e860f06bf7dc645e84991fc47e93` and stopped cleanly at the precommitted boundary with a
`343ms` stop-request offset. It did **not** satisfy A2: no Policy band ever reached the post-warmup
partition, so `RADAR_KNOWN / APPLICABLE_MARKET_SCOPE` was `0 / 0` (`UNKNOWN`) and no candidate or
downstream conversion count has opportunity meaning.

All `58,773,561` applicable evaluations remained in startup/recovery. `45,566,652` were known
ineligible or otherwise known before requiring the full formula; `13,206,909` were UNKNOWN:
`INDEX_WARMUP 13,184,589`, `OPTION_BOOK_UNKNOWN 16,504`, and
`POST_STATUS_BOOTSTRAP_REQUIRED 5,816`. The run produced zero full-formula evaluations, zero
instrument candidate Episodes, and zero temporal activation batches. No Shadow Case opened and the
durable Shadow Case file count was zero. The observation therefore falsified the assumption that a
six-hour session-local index tail is a usable startup boundary for this candidate generator.

The credible-clue source-contract probe was accepted at commit `cbea7a3`. Its first 540-second
integration smoke was rejected. Every readable heartbeat reported zero current full-formula
instruments; the last readable partition was `12,384 / 28,128` post-warmup known, with
`OPTION_BOOK_UNKNOWN 11,836`, `CLOCK_GAP 3,372`, and `POST_STATUS_BOOTSTRAP_REQUIRED 536` UNKNOWN
evaluations. The terminal cumulative count remained `UNKNOWN` because the completed business
summary did not cross the transport close boundary. Offline tracing proved that a local book fact
recomputed its whole expiry/type scope, history diagnostics repeated per instrument, an unbounded
runtime deque bypassed the bounded ingress owner, and WebSocket close shared the outer acceptance
timeout. This is an input-stability failure, not evidence that the market lacks active combos or
that Radar thresholds are too strict.

Repair candidate `0dce98481a4facef54112faa5953def2220f6927` then passed the authorized
540-second production-public smoke. Its readable terminal summary reported post-warmup
`RADAR_KNOWN / APPLICABLE_MARKET_SCOPE = 90,689 / 91,091` (`99.5587%`) and `21,930` full-formula
evaluations. All `134` terminal instruments were known, all `134` option books were usable, and
`30` instruments had current full-formula evaluations. Queue-lag segments, clock-gap post-warmup
evaluations, transport overflows, reconnects, and durable Shadow Case files were all zero. The
remaining `402` UNKNOWN evaluations were the fixed startup edge—`OPTION_BOOK_UNKNOWN 268` plus
`POST_STATUS_BOOTSTRAP_REQUIRED 134`—and did not increase after bootstrap.

## Active closure

Candidate semantics and production-public current-input stability are now frozen for one business
observation. The active closure is to measure, over one fixed 43,200-second boundary, how many
independent volatility clues persist, how many have a reviewable defined-risk structure, how many
have a current official atomic target-size quote, and where the largest observed funnel loss occurs.
The observation cannot change detector formula, target quantity, TTE/Delta universe, official
atomic meaning, or any threshold.

A hard-screen clue requires: official completed average-price history with explicit cadence, age,
gap and revision truth; target-size bid and ask depth; an uncrossed spread; official price-tick
metadata; a bid that remains above the activation threshold after every consumed level is moved
down one legal tick; an actionable TTE band; `0.05 <= |Delta| <= 0.40`; and the existing causal
multi-horizon persistence rule.

Regime, surface-lite, conservative legged vertical references, and transparent rank are diagnostic
review context. They may explain and order a known clue but cannot create detector truth, official
atomic availability, Underwriting action, admission, or edge.

## Allowed work

- exactly one fixed `43,200`-second production-public read-only observation on one clean commit and
  the accepted fixed Policy chain;
- existing in-process reconnect behavior may preserve the same business owner and fixed terminal
  boundary; no external supervisor or automatic restart may extend or replace the observation;
- terminal adjudication may report the frozen funnel and any legitimately admitted Shadow Cases;
- the accepted source probe and accepted repair smoke are consumed and cannot be repeated.

## Forbidden work

- any second short smoke, second 43,200-second observation, or unchanged restart;
- tuning thresholds or inputs during or from the observation to manufacture a natural clue;
- changing target quantity, official atomic admission, Shadow Case, Position, or Outcome semantics;
- fitted forecasting, SVI/SABR/Heston calibration, machine-learning ranking, event-calendar edge,
  GEX, private RFQ/combo creation, credentials, account, order, fill, capital, or actual exposure;
- persistent diagnostics, full-feed capture/replay, database, feature store, event bus,
  microservice split, deployment, commissioning, host inspection, or a stability Soak.

## Acceptance boundary

The long observation has one precommitted terminal boundary and returns one readable terminal
summary plus the frozen funnel. It measures observed independent clue Episodes, reviewable
structures, official atomic target-size quote availability, Underwriting evaluability, Candidate
and Shadow conversion, and the earliest largest loss. Zero natural clues is a valid result when
post-warmup scope and full-formula counts are positive. The observation does not establish future
frequency, expected return, edge, fillability, qualification, deployment, uptime, or execution
permission.
