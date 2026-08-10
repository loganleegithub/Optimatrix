# Task — Restore the Inverse BTC loopback Workbench

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Base commit:** `7093c9e4630da041ea8b68e650bdce3406606c90`

**Target branch/PR:** `codex/8765-outage-recovery` / one Draft PR after closure

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `APPLICABLE_MARKET_SCOPE` is unreachable because the sole Online Runtime
and its loopback Workbench are absent.

**Baseline:** `0 / 6` declared loopback GET routes return an HTTP response; all return connection
refused. The official reader validates `51 / 51` durable Cases and identifies `14` compatible,
non-terminal admitted Entries whose latest Observation Segments are
`INCOMPLETE_UNCLEAN_EXIT`.

**Primary blocker:** `SERVE_SHADOW_PROCESS_UNCLEAN_EXIT_WITH_NO_EXTERNAL_RESTART`; denominator is
the one canonical Online Runtime, currently `0 / 1` running.

**Expected user-visible delta:** the six declared Workbench routes return their contract status,
`/healthz` reports healthy, `/readyz` reaches ready/current after public-source warmup, and the UI
shows the fixed `INVERSE_BTC_V1` product and exact Policy chain.

**Durable-data effect:** reuse
`/private/tmp/optimatrix-inverse-btc-stable-97AYba` without migration, copying, deletion, or
rewriting existing records. On the first newly settled public boundary, the runtime may append one
new `GAPPED` Observation Segment for each of the `14` recovered admitted Entries, as required by
the accepted recovery contract. It creates no pre-Shadow record and does not restore the `37`
historical selected no-trade Controls.

**Complexity added:** `NONE`

**Complexity deleted:** `NONE`

## Business closure

**Given:** the current repository is clean, its fixed Inverse product and three Policy identities
match all `51` durable Cases, the official reader stages all `14` active admitted Entries, and no
other owner holds the stable repository lease.

**When:** an external operator performs exactly one canonical `serve-shadow` start from the clean
task commit against the existing stable root and leaves that process running.

**Then:** the loopback Workbench and current public-Shadow decision path are reachable again, while
the recovered Entries remain explicitly `GAPPED` and no continuity or qualification is inferred
across the outage.

**Valid zero/UNKNOWN:** zero current Candidates, clues, or mature Outcomes is truthful but does not
affect this closure. `ready=false`, stale/unknown product identity, any partial durable recovery,
or any route remaining unreachable does not satisfy it.

**Cheapest falsification:** focused offline service/Workbench/recovery tests followed by the one
authorized start and direct same-process checks of all six declared loopback routes and the current
Workbench product/Policy/runtime identities.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** authorize exactly one long-lived public-only `serve-shadow` start
using the existing stable root, plus one bounded loopback reachability/currentness check. No retry,
second root, migration, process supervisor, or private input is authorized.

## Scope

**In:** this task, `CURRENT_STAGE`, direct authority tests, one clean canonical start on
`127.0.0.1:8765`, stable Entry recovery, and read-only HTTP/UI verification.

**Out:** Radar/Underwriting/Position Policy changes; product/schema changes; Case migration,
copying, deletion, or rewriting; private/account/order/fill behavior; host PID/log/`lsof`/launchd
inspection; supervisor or automatic-restart implementation; and any second live start.

**Owning module:** `radar_runtime.service` composition and the existing external launch boundary

## Validation

- focused tests: `.venv/bin/pytest -q tests/test_persistent_service.py tests/test_workbench_frontend_v1.py tests/test_trader_workbench.py tests/test_inverse_product.py`;
- repository gate: `make check`;
- public observation: exactly one clean
  `.venv/bin/python -m radar_runtime serve-shadow --state-root /private/tmp/optimatrix-inverse-btc-stable-97AYba --workbench-host 127.0.0.1 --workbench-port 8765`, followed by a bounded read-only six-route and current-snapshot check;
- no manifest, receipt, commissioning subsystem, host inspection, Policy tuning, or broad evidence
  package.

## Definition of done

The six routes are reachable from the one running clean Inverse-only process; current snapshot
identity and units are exact; all compatible Entries are recovered through a truthful new GAPPED
Segment; focused and repository checks pass; no unrelated code, Policy, schema, or durable history
changed; and the final tree removes this completed task while recording the exact live boundary in
`CURRENT_STAGE`.
