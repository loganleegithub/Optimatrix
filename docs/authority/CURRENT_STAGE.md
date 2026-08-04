# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:**
`RADAR_STEADY_STATE_KNOWNNESS_CANDIDATE_AWAITING_PUBLIC_OBSERVATION`

**Production Short Vol Radar:** `OFFLINE_READY_BOUNDED_PUBLIC_REACHABILITY_OBSERVED`

**Persistent service:** `STOPPED_NO_DEPLOYMENT`

**Live commands:** `ONE_BOUNDED_RADAR_KNOWNNESS_OBSERVATION_CONDITIONALLY_AUTHORIZED`

**Sole authorized closure:** `SHORT_VOL_RADAR_STEADY_STATE_KNOWNNESS`

## Current truth

The simplified implementation conforms to the Shadow Case data boundary. Market, Radar, atomic
availability, Underwriting, Candidate, admission attempts, and Workbench state are in memory. A run
with no Shadow admission writes zero Shadow Case business files. The first durable record is
`SHADOW_CASE_OPENED`; only first CLOSE and terminal Outcome may follow. A minimal reader marks an
opened-only Case after an unclean exit as `INCOMPLETE_UNCLEAN_EXIT`.

The previously consumed bounded public smoke reached `APPLICABLE_MARKET_SCOPE` and `RADAR_KNOWN`,
but its cumulative denominator mixed normal index startup warmup with later operation. Its apparent
earliest loss was `RADAR_KNOWN / INDEX_WARMUP`, with `OPTION_BOOK_UNKNOWN` also counted. It did not
establish the post-warmup known proportion or a steady-state primary blocker. No natural anomaly
occurred.

The A1 candidate preserves the same Radar calculation and adds a non-durable phase partition at the
funnel projection: a Policy TTE band enters post-warmup only when the canonical index tail is first
`AVAILABLE`; any current `WARMUP` stays in the startup/recovery bucket, while a later source-stale,
window-gap, or continuity-gap state after that band has warmed remains a steady-state UNKNOWN. The
canonical `APPLICABLE_MARKET_SCOPE` and `RADAR_KNOWN` funnel counts therefore use only the
post-warmup denominator. Every Radar UNKNOWN aggregate reason is bounded.

The exact Radar, Underwriting, and Position Policy files, public source semantics, TTE/Delta
universe, atomic-combo semantics, causality, `UNKNOWN`, and full-quantity official atomic entry/exit
requirements remain unchanged. No runtime is deployed and no private/account/order/fill/capital
capability exists.

## Authorized observation

After the exact candidate passes its focused tests, full `make check`, and GitHub CI, one fresh
public-only observation is authorized with a stop deadline fixed before connection:

```bash
.venv/bin/python -m radar_runtime observe-radar-knownness \
  --state-root /absolute/fresh/optimatrix-a1-state \
  --duration-seconds 900
```

The command prints one non-durable JSON result to stdout. It must report startup/warmup and
post-warmup counts, bounded UNKNOWN reasons, `post-warmup RADAR_KNOWN / APPLICABLE`, the
precommitted deadline and actual terminal offset, and the Shadow Case durable-file count. The result
is accepted for this closure only when
post-warmup `APPLICABLE_MARKET_SCOPE > 0`; a natural anomaly and Shadow admission are not required.
If no Shadow Case opens, durable Shadow Case files must equal zero.

The observation may not be extended, retried, or repeated because of its result. A transport or
candidate failure is reported as a failed observation and requires a new human decision; it does
not authorize another invocation.

## Allowed work

- bounded implementation and direct tests for the A1 phase partition and finite reason mapping;
- deterministic local checks and GitHub CI for the exact candidate;
- exactly the one public command above after all candidate gates pass;
- read-only repository and Workbench review.

## Forbidden work

- changing Radar thresholds, Policy bytes, TTE/Delta universe, or atomic-combo semantics;
- persistent deployment, automatic restart, or a second/extended public observation;
- credentials, account, balance, margin, private API, order, fill, capital, or actual position;
- durable funnel data, a new persistent diagnostic, database, replay platform, event bus,
  microservice split, or Docker/Kubernetes requirement;
- application commissioning, host PID/log inspection, manifest, receipt chain, broad evidence
  package, 24-hour Soak, or anomaly-generation requirement;
- qualification, promotion, or execution controller.

## Acceptance boundary

Green tests and CI establish only offline behavior. The one public observation may establish the
post-warmup known proportion and the naturally observed steady blocker during its fixed interval.
It cannot establish strategy value, opportunity frequency outside that interval, fillability,
qualification, deployment, uptime, or execution permission.
