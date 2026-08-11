# Task — V2 strong-signal Radar map and canonical Workbench cutover

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** ONE_CLEAN_START_8765

**Base commit:** `54e3b589ba5ffd7eff7f7acf018fbc0530492614`

**Target branch/PR:** `codex/v2-strong-signal-cutover-truth` / one Draft PR

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** trader review of `RADAR_KNOWN -> ANOMALY_ACTIVE`

**Baseline:** PR #47 merged the strong-signal map into `main`, but the real Workbench on
`127.0.0.1:8675` is no longer serving. The inactive official reader validates 47 schema-v5 Cases:
32 admitted Shadow Entries, 4 selected Underwriting Controls, and 11 Radar score Controls. All 47
are `INCOMPLETE_UNCLEAN_EXIT` with zero mature Outcome. The 32 admitted Entries are non-terminal
and must all be restored; the Controls remain historical and are not restored.

**Primary blocker:** `STRONG_SIGNAL_MAP_NOT_LIVE_ON_CANONICAL_WORKBENCH_PORT`; LOW, MID, member, and
review rows still compete with eligible HIGH bucket leaders on the live first screen.

**Expected user-visible delta:** `127.0.0.1:8765` becomes the sole canonical Runtime and serves the
sparse expiry-by-strike map of current eligible `HIGH` bucket leaders in `CONFIRMING | ACTIVE`,
with exact counts, filters, and a concise evidence inspector over real server data. Shadow remains
a separate view and all 32 admitted Entry aggregates appear once after recovery.

**Known-at boundary:** all score, leader, eligibility, Episode, Shadow, Position, health, and
currentness values come from one complete schema-v7 Workbench snapshot after the reducer and owner
settle. The browser only filters and lays out that typed truth.

**Durable-data effect:** no stop write remains because the prior process already ended uncleanly.
The one new runtime opens one `GAPPED` Segment per each of the 32 recoverable admitted Entries on
its first settled boundary. No mature Outcome is created and no existing Case byte is copied,
migrated, rewritten, or deleted.

**Complexity added:** no process, service, route, dependency, schema, persistence kind, time series,
or browser strategy owner. The existing monolith moves from loopback port 8675 to 8765.

**Complexity deleted:** the default flat all-Radar-row attention queue and the temporary 4174
fixture as a delivery dependency.

## Business closure

**Given:** clean `main@54e3b589ba5ffd7eff7f7acf018fbc0530492614` containing accepted PR #48
runtime repairs and PR #47 static Radar map, plus the unchanged stable Case repository with 32
compatible non-terminal admitted Entries and no active lease owner.

**When:** one exact-main process starts on 8765 with the same stable repository and three-Policy
chain.

**Then:** all six GET/HEAD routes respond on 8765, health/readiness report
`RUNNING/CURRENT/ready`, schema/product/Policy identities match, current Radar coverage is complete,
the strong-signal map renders real server rows, all 32 Entry identities are restored once, and
8675 no longer serves.

**Valid zero/UNKNOWN:** zero current strong signals is valid when no row satisfies the complete
server-owned predicate. During startup or recovery, current data may remain `UNKNOWN`; it cannot
create a score, Episode, Candidate, Entry, Position action, or Outcome.

**Cheapest falsification:** after the one start, fetch the declared routes and one stable
schema-v7 snapshot, compare product/Policy/Entry identities with the pre-stop inventory, and inspect
the actual 8765 DOM. Any missing Entry, stale/fixture payload, browser-derived score, second active
Runtime, or continued 8675 service falsifies the cutover.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** the bounded probe established that 8675 was already stopped; only
one clean start of the exact merged-main Runtime on 8765 and one bounded post-start verification
remain. No retry,
parallel Runtime, deployment supervisor, or private permission is implied.

## Scope

**In:** merged Workbench HTML/CSS/JS, current schema-v7 Radar row selection and grouping, owning
product and Radar presentation contracts, exact-main runtime
checkout, same-root clean recovery, loopback port 8765, and bounded route/API/DOM verification.

**Out:** Policy artifacts or hashes, score formula/thresholds, T/S construction, TTE/Delta rules,
Workbench API schema, server-side history, Case schema/root migration, Case copying/deletion,
private data or execution, host PID/log/`lsof` inspection, process supervision, and roadmap cells.

**Owning module:** `short_vol_radar.bucket` remains the sole score/leader/Episode owner;
`radar_runtime.workbench_static` only selects and lays out its current projection; the existing
`serve-shadow` composition remains the sole Runtime and Workbench service.

## Validation

- focused authority/Workbench/frontend tests;
- full `make check` on the exact branch and final merged main;
- the completed 8675 reachability check and inactive official Case inventory;
- one post-start 8765 GET/HEAD route matrix, schema/product/Policy/Entry comparison, and in-app
  browser DOM inspection;
- no manifest, receipt, commissioning subsystem, broad host inspection, or second runtime.

## Definition of done

The strong-signal map is served by the sole real Runtime on 8765; exact strong-signal selection,
filters, empty state, desktop and responsive dismissal remain tested; all 32 admitted Entry
aggregates survive through truthful GAPPED Segments; 8675 is no longer serving; focused, repository,
route, API, and DOM gates pass; Policy bytes, Workbench schema, Case schema, stable root, and
public-only permission remain unchanged; and the final repository retains one active task until a
separate closure commit removes it after the cutover evidence is recorded.
