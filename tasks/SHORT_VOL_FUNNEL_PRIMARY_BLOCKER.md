# Task — Identify the primary Short Vol funnel blocker

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED — exactly one bounded production-public read-only smoke after the exact
candidate passes repository checks; no retry or extension based on the observed result.

**Base commit:** `e7e6380`

**Target branch/PR:** `agent/shadow-case-data-boundary` / Draft PR #18

**Owning authority/contract:**
`docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/SYSTEM_ARCHITECTURE.md`, and
`docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md`

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE → PUBLIC_ATOMIC_QUOTE_AVAILABLE → UNDERWRITING_EVALUABLE`

**Baseline:** historical accepted runs observed nonzero Radar anomalies but zero atomic-quote,
Candidate, Shadow Case, and Outcome units; the simplified runtime does not yet expose a current
stage-by-stage denominator or primary blocker.

**Primary blocker:** `NOT_YET_MEASURED` in the simplified runtime.

**Expected user-visible delta:** Workbench shows non-durable funnel stage counts, conversion
blockers, and one deterministic primary blocker instead of treating test success or `UNKNOWN` as
product progress.

**Durable-data effect:** `NONE`; funnel diagnostics reset with the process and create no Case file.

**Complexity added:** one bounded in-memory `FunnelTracker` and one Workbench projection.

**Complexity deleted:** `NONE` in this closure; no evidence/acceptance framework is introduced.

## Business closure

**Given:** one settled public-only Radar → Underwriting → Shadow owner transaction.

**When:** the runtime observes countable Radar evaluations and downstream state transitions.

**Then:** it attributes each material funnel loss to the earliest owning stage and exposes the
largest reason; one bounded public smoke reports the actual observed primary blocker or a truthful
`NOT_OBSERVED_BEYOND_<STAGE>` result.

**Valid zero/UNKNOWN:** a smoke with no natural anomaly is a valid observation but reports
`NO_ANOMALY_ACTIVATION_OBSERVED`; it does not prove the later blocker. Source `UNKNOWN` is counted
by exact reason and is never accepted as completion.

**Cheapest falsification:** deterministic stage/blocker fixtures, full repository checks, then one
bounded production-public read-only smoke.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** APPROVED — authorize exactly one result-independent bounded public
smoke for funnel reachability after the exact candidate passes checks; deployment remains forbidden.

## Scope

**In:** in-memory funnel tracker, owner current-state blocker labels, Workbench JSON/UI, direct
fixtures, one temporary GitHub Actions smoke harness removed from the final tree.

**Out:** Policy tuning, new strategy inputs, private/account/order/fill/capital, durable funnel
records, database, event bus, replay, commissioning, manifest, receipt, Soak, automatic retry, or
runtime extension after inspecting results.

## Validation

- focused funnel/Workbench tests;
- repository gate: `make check`;
- public observation: exactly one bounded production-public `serve-shadow` process, sampled only
  through `/api/workbench/current`, stopped once with `SIGINT` at the predeclared duration;
- no evidence directory, manifest, receipt, host probe, or second invocation.

## Definition of done

The Workbench exposes truthful non-durable funnel counts and exact blocker reasons; deterministic
fixtures identify known `UNKNOWN`, no-active-combo, no-target-quote, WATCH/ABSTAIN, admission, and
pending-Outcome losses; one bounded smoke reports the actual observed earliest blocker without
changing thresholds or extending the run; the temporary smoke harness is absent from the final
tree.
