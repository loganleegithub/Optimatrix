# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:**
`RADAR_CURRENT_INPUT_STABILITY_REPAIR`

**Production Short Vol Radar:** `CANDIDATE_SEMANTICS_FROZEN_INPUT_STABILITY_REPAIR`

**Persistent service:** `STOPPED_NO_DEPLOYMENT`

**Live commands:** `ONE_POST_REPAIR_MAX_600_SECOND_SMOKE_PER_OFFLINE_GATED_CANDIDATE`

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

## Active closure

The candidate semantics are frozen, but production-public current-input stability is not yet
established. The active repair must make one local option fact local, share one causal history tail
within a transaction, retain one bounded ingress owner with cooperative scheduling, preserve the
book owner's exact current continuity reason, and return the terminal summary before transport
shutdown can consume the acceptance window. The five-minute-persistence Radar consumes aggregated
`agg2` option ticker and book channels rather than every option's dual 100ms feeds. No detector
formula, target quantity, TTE/Delta universe, or official atomic meaning changes.

A hard-screen clue requires: official completed average-price history with explicit cadence, age,
gap and revision truth; target-size bid and ask depth; an uncrossed spread; official price-tick
metadata; a bid that remains above the activation threshold after every consumed level is moved
down one legal tick; an actionable TTE band; `0.05 <= |Delta| <= 0.40`; and the existing causal
multi-horizon persistence rule.

Regime, surface-lite, conservative legged vertical references, and transparent rank are diagnostic
review context. They may explain and order a known clue but cannot create detector truth, official
atomic availability, Underwriting action, admission, or edge.

## Allowed work

- authority, Radar contract, Policy, pure calculators, current-state projection, and direct tests for
  the exact credible-clue freeze;
- the accepted index-history source-contract probe is not repeated;
- after all direct checks pass, one production-public read-only integration smoke of at most
  `600` seconds for each new exact offline-gated repair candidate; an unchanged candidate cannot be
  rerun, and a rejected smoke returns to offline diagnosis before any further authorization;
- rebind dependent Underwriting and Position Policy identities only where upstream content identity
  changes require it.

## Forbidden work

- any 43,200-second observation before one post-repair smoke is accepted and Authority is amended;
- tuning thresholds to manufacture a natural clue during either short validation command;
- changing target quantity, official atomic admission, Shadow Case, Position, or Outcome semantics;
- fitted forecasting, SVI/SABR/Heston calibration, machine-learning ranking, event-calendar edge,
  GEX, private RFQ/combo creation, credentials, account, order, fill, capital, or actual exposure;
- persistent diagnostics, full-feed capture/replay, database, feature store, event bus,
  microservice split, deployment, commissioning, host inspection, or a stability Soak.

## Acceptance boundary

Direct checks may establish formula correctness, source fail-closed behavior, quote robustness,
risk-bucket classification, diagnostic context, ranking determinism, fee arithmetic, and strict
separation between legged references and official atomic availability. The one source probe may
establish only the current API cadence/revision facts it observes. The one short smoke may establish
current end-to-end reachability only.

An accepted post-repair smoke must return a readable terminal summary, positive post-warmup scope,
positive cumulative full-formula evaluations, bounded ingress without queue-lag currentness, and
zero post-bootstrap clock gaps. It does not require a natural clue. After those gates pass,
authority may be amended once to permit one fixed 43,200-second production-public read-only
observation. Neither the short validations nor that later observation
establish future frequency, expected return, edge, fillability, qualification, deployment, uptime,
or execution permission.
