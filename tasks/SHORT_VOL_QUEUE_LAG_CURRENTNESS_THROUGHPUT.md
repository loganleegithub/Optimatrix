# Task — Queue-Lag Currentness Throughput

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** ONE_POST_MERGE_PRODUCTION_PUBLIC_PROCESS

**Base commit:** `beaed1c824e8e4522c067ae24cde0c7fc7e50718`

**Target branch/PR:** `codex/queue-lag-currentness-throughput`; one Draft PR against `main`

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `RADAR_KNOWN → ANOMALY_ACTIVE`, including the uninterrupted-currentness
precondition for the frozen three-observation persistence rule

**Baseline:** the selected-decision natural run on code `beaed1c824e8e4522c067ae24cde0c7fc7e50718`
stopped cleanly at explicit human request with zero Episode, Candidate, Case, or Outcome. Its last
captured pre-stop Workbench snapshot had `1,368,983` post-warmup applicable evaluations,
`1,368,471` known evaluations, and current `128/128` coverage. A separate 300-second 1 Hz loopback
sample observed four `QUEUE_LAG_CURRENTNESS` incidents; the longest fully observed CURRENT segment
was `165` seconds. Each incident truthfully reset an unfinished activation sequence.

**Primary blocker:** `QUEUE_LAG_CURRENTNESS` over four observed incidents in the 300-second
diagnostic denominator. Three activation observations separated by at least 300 seconds require an
uninterrupted window of at least 600 seconds, so repeated queue lag prevents a clean natural sample
even when a future market fact satisfies the frozen economic threshold.

**Measured owning cost:** a production-shaped deterministic profile with 128 option instruments
measured about `1.11 ms` per local settled fact and about `898` facts/second. Rebuilding a materialized
index-tail point-pair tuple separately for every instrument consumed about 68% of profiled reducer
time. Reusing the already-frozen `IndexHistoryState.points` tuple measured about `0.36 ms` and
about `2,746` facts/second in the same A/B fixture. Workbench review construction and 609 KB JSON
encoding measured about `2.7 ms` and `1.3 ms` respectively and are not the owning repair.

**Expected user-visible delta:** the same frozen market and Decision semantics remain visible, but
the single reducer no longer creates one full index-tail tuple per instrument for every local book
or ticker fact. The post-merge public Shadow process must sustain an externally observed CURRENT
window of at least 600 seconds without `QUEUE_LAG_CURRENTNESS`; an Episode remains market-dependent.

**Durable-data effect:** NONE. The repair changes only an in-memory comparison token. Pre-enrollment
writes remain zero; the existing admitted Candidate or selected no-trade Case contract is unchanged.

**Complexity added:** one immutable tail reference in the existing currentness token and one
structural regression test. No new timer, worker, queue, cache, metric family, schema, or service.

**Complexity deleted:** per settled fact, up to one newly allocated history tuple for every
applicable instrument.

## Business closure

**Given:** 128 production-shaped option instruments share one already-frozen causal index tail.

**When:** the reducer constructs per-instrument time-currentness tokens for a settled local fact.

**Then:** every instrument for the same lookback references the same immutable index-tail point
identity; equal tails compare equal, a changed tail still changes the token, and Radar, coverage,
funnel, Workbench, and Shadow decisions are unchanged.

After the implementation PR is merged, exactly one `serve-shadow` process may start from clean
merged `main`, the unchanged three-Policy chain, a fresh absolute state root, and loopback Workbench.
The same process first proves `RUNNING/CURRENT`, then remains under external observation until one
of these terminal boundaries:

- at least one uninterrupted CURRENT window of 600 seconds proves the repaired activation path is
  temporally reachable, after which the process continues naturally toward the first selected-
  decision Outcome;
- `QUEUE_LAG_CURRENTNESS` recurs, fatal failure occurs, or an explicit human stop ends the run
  cleanly without automatic restart.

The 600-second window proves currentness reachability only. It does not require an anomaly, Candidate,
Case, Outcome, edge, or profit.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** replace the consumed/stopped validation process with one post-merge
production-public Shadow process. This is public-only Shadow service authorization, not private
execution or supervised deployment.

## Scope

**In:** the existing reducer time-currentness token, one direct structural regression, Authority
alignment, deterministic profiling, focused tests, `make check`, one Draft PR, merge, and one
post-merge natural public Shadow process.

**Out:** Radar/Underwriting/Position Policy changes; currentness deadlines; persistence counts;
subscription cadence; second reducer; background publisher; extra queue; metrics subsystem;
database; replay; manifest; supervisor; automatic restart; private/account API; order/fill/capital.

**Owning module:** `radar_runtime`

## Validation

- red/green structural test: all same-lookback tokens reuse the exact frozen tail points
  and a changed tail changes the token;
- deterministic 128-instrument A/B profile reported outside the product path, with no timing
  threshold embedded in the test suite;
- focused reducer/currentness/Workbench tests;
- `make check`;
- one Draft PR and green repository checks;
- post-merge same-process `/healthz`, `/readyz`, `/api/workbench/current` identity and currentness
  checks;
- external 1 Hz observation sufficient to establish one uninterrupted 600-second CURRENT window;
- no second smoke/process or automatic restart.

## Definition of done

The structural regression and repository gate pass; the diff changes no Policy, business formula,
external schema, persistence, or Case semantics; the PR is merged; and one fresh public-only process
from merged `main` reaches exact identity plus `RUNNING/CURRENT`. The implementation repair is live
only after the external observation proves one uninterrupted 600-second CURRENT window. An Episode
or selected-decision Outcome remains a later natural observation, not a manufactured acceptance
condition.
