# Task — Short Vol Radar steady-state knownness

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED — exactly one after all candidate gates

**Base commit:** `5d10a95216f057392faf70e90e301a16f17ef968`

**Target branch/PR:** `agent/short-vol-radar-steady-state-knownness` / Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN`

**Baseline:** the consumed public smoke counted applicable instrument evaluations cumulatively but
did not separate index startup/recovery warmup from post-warmup operation; therefore the exact
post-warmup numerator and denominator are `NOT_YET_MEASURED`.

**Primary blocker:** apparent `INDEX_WARMUP`, followed by `OPTION_BOOK_UNKNOWN`; the former is not a
valid steady-state blocker until phase partitioning exists.

**Expected user-visible delta:** the Workbench funnel uses post-warmup canonical counts; its JSON
projection and one stdout observation show startup/warmup and post-warmup counts separately. Every
Radar UNKNOWN has one bounded reason, and the result exposes
`post-warmup RADAR_KNOWN / APPLICABLE_MARKET_SCOPE`.

**Durable-data effect:** `NONE`; when no Shadow Case opens, durable Shadow Case file count is zero.

**Complexity added:** one in-memory per-Policy-band warmup witness set, two scalar knownness
partitions, one finite Radar-reason classifier, and one bounded public-only observation command; no
dependency, persistence schema, service, or second formula path.

**Complexity deleted:** startup `INDEX_WARMUP` is removed from the steady-state primary-blocker
calculation.

## Business closure

**Given:** the fixed Radar Policy requires a one-minute index lookback and the canonical index reducer
reports per-band `AVAILABLE | WARMUP | WINDOW_GAP | SOURCE_STALE | CONTINUITY_GAP` at each settled
causal boundary.

**When:** one applicable countable Radar evaluation is partitioned by that exact current tail state,
and one 900-second public-only observation is stopped by a deadline fixed before connection.

**Then:** post-warmup `APPLICABLE_MARKET_SCOPE > 0`; the output contains the exact post-warmup
`RADAR_KNOWN` numerator, applicable denominator, ratio, bounded UNKNOWN blocker counts, visible
startup/warmup counts, fixed stop boundary, and durable Shadow Case file count.

**Valid zero/UNKNOWN:** zero anomaly and zero Shadow admission are valid and satisfy this closure;
post-warmup applicable denominator zero does not satisfy it. Any UNKNOWN remains truthful and must
appear under one finite reason. No result authorizes extending or repeating the observation.

**Cheapest falsification:** direct tests that (1) startup `INDEX_WARMUP` cannot become the steady
primary blocker, (2) an available tail starts the post-warmup denominator, (3) later non-warmup index
loss remains steady-state UNKNOWN, (4) re-warmup leaves that denominator, and (5) arbitrary reasons
collapse to a finite category.

## Change declarations

**Market/Decision input contract change:** NONE — the same settled Radar result and canonical index
tail are projected; no market fact or calculation input changes.

**Decision Policy change:** NONE.

**Outcome/evaluation contract change:** NONE.

**Stage/authorization change:** exactly one 900-second production-public, read-only observation is
conditionally authorized after focused tests, full repository checks, and GitHub CI pass on the
exact candidate.

## Scope

**In:** `radar_runtime.funnel`, a bounded observation composition and CLI, direct funnel/observation
tests, the owning Radar contract and stage/architecture text, README current-stage text, and the
Task Template terminology correction.

**Out:** Radar thresholds, Policy bytes, TTE/Delta universe, atomic-combo behavior, Underwriting,
Position, Outcome, Shadow admission, new persistent diagnostics, replay, commissioning, deployment,
host inspection, and 24-hour Soak.

**Owning module:** `apps/radar_runtime/src/radar_runtime/funnel.py`; the observation command only
composes existing service owners and writes no diagnostic artifact.

## Validation

- focused tests:
  `.venv/bin/pytest tests/test_funnel.py tests/test_radar_knownness_observation.py tests/test_authority_and_architecture.py`;
- repository gate: `make check`;
- public observation, exactly once after the exact candidate and GitHub CI pass:

  ```bash
  .venv/bin/python -m radar_runtime observe-radar-knownness \
    --state-root /absolute/fresh/optimatrix-a1-state \
    --duration-seconds 900
  ```

- inspect stdout only; do not create a receipt, manifest, durable diagnostic, or broad evidence
  package;
- inspect the fresh run's `cases` directory: if `SHADOW_CASE_OPENED == 0`, file count must be zero.

## Definition of done

The phase partition and bounded reason vocabulary pass direct and full checks; the exact candidate
is pushed to the declared Draft PR; the one fixed-boundary public observation naturally reaches a
positive post-warmup applicable denominator; its output reports the known ratio and blocker counts;
no-anomaly is accepted; and no-admission writes zero Shadow Case files. Until that one public result
is obtained and independently reviewed, this task remains active and the candidate is not a
completed production result.
