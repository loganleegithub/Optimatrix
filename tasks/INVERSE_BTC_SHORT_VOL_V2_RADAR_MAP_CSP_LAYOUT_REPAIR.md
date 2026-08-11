# Task — V2 Radar map CSP layout repair

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** REQUIRED

**Base commit:** `bfcf876ef443db109f5bec47579cad123b51dcf5`

**Target branch/PR:** direct `main` delivery, per the user's explicit no-branch instruction

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** trader-visible `ANOMALY_ACTIVE` discovery map

**Baseline:** the sampled schema-v7 Workbench has 128 Radar rows and a changing nonzero strong-signal
subset. In the browser, all 10 inspected current signal nodes compute `left=0px` despite distinct
server strike coordinates, and both inspected score meters render at full width instead of their
server values.

**Primary blocker:** `CSP_REJECTED_INLINE_STYLE`; the declared `style-src 'self'` policy rejects the
browser's four inline CSS-variable emitters, collapsing every signal to the track origin and making
both detail meters falsely look like 100%.

**Expected user-visible delta:** every current strong signal appears at its exact expiry/strike
coordinate, same-strike signals remain readable, Premium/Risk meters match server values, and the
header, runtime strip, product navigation, Radar filters/map/detail, Shadow queue/detail, footer,
theme, and responsive drawer are browser-verified after deployment.

**Durable-data effect:** no new record or schema. The authorized clean stop closes every active
admitted Entry's current Segment; the one restart restores every compatible non-terminal Entry and
opens one truthful `GAPPED` Segment after fresh facts settle. It creates no admitted Outcome.

**Complexity added:** one CSP-safe SVG coordinate plane for the existing HTML signal buttons and
native progress elements for the existing server metrics; no dependency or second business schema.

**Complexity deleted:** all Workbench inline `style=` generation and the broken CSS-variable
coordinate/fill path.

## Business closure

**Given:** one current schema-v7 snapshot containing clue-eligible HIGH bucket leaders in
`CONFIRMING | ACTIVE`, served with `style-src 'self'`.

**When:** the browser renders the existing server-owned strong-signal subset without inline styles.

**Then:** marker horizontal positions differ according to their server Strike values, each marker
remains inside its lane, metric fills equal their native progress values, and every declared page
module remains usable in the in-app browser at `127.0.0.1:8765`.

**Valid zero/UNKNOWN:** zero current strong signals remains valid only when no current row matches
the exact server-owned subset. It does not visually falsify this closure; direct layout fixtures and
the bounded live browser review own the positive-path check.

**Cheapest falsification:** direct CSP-safe markup tests plus one post-restart in-app-browser layout
measurement and screenshot at the current 1:1 viewport.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** authorize this bounded browser repair, one clean stop, one clean
start of the sole 8765 runtime on the unchanged stable repository, and one bounded browser/route/
official-reader verification. A consumed or failed start grants no retry.

## Scope

**In:** `workbench_static/app.js`, `workbench_static/styles.css`, direct frontend/HTTP/Authority
tests, this task, `CURRENT_STAGE`, exact runtime-checkout synchronization, and the one authorized
clean restart.

**Out:** Radar/Underwriting/Position Policy, scoring, strong-signal selection, Workbench or Case
schema, server projection, product identity, state-root content, data migration, private execution,
commissioning, supervision, or a second runtime.

**Owning module:** `radar_runtime.workbench_frontend`

## Validation

- focused tests: `PYTHONPATH=apps/radar_runtime/src .venv/bin/pytest -q tests/test_workbench_frontend_v1.py tests/test_trader_workbench.py tests/test_authority_and_architecture.py`;
- repository gate: `PYTHONPATH=apps/radar_runtime/src make check` in the delivery and exact runtime checkouts;
- public observation: after the one clean restart, GET/HEAD route matrix, exact served-asset hash,
  official Case-reader inventory, and in-app-browser review of every declared page module;
- no manifest, receipt, commissioning, host inspection, or broad evidence package.

## Definition of done

The live 8765 map uses correct Strike geometry and metric values under the declared CSP; every
declared module is browser-usable; active admitted Entries are restored exactly once without a
new Outcome; focused/full/CI checks pass; the task is removed from the final tree; and main/remote
state is reported accurately.
