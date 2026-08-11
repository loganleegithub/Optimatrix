# Task — Restore 40 admitted Entries on 8765

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** FORBIDDEN

**Live commands:** REQUIRED

**Base commit:** `b0d4ef7042e400f839f3f2a7bb8aebd6103e399a`

**Target branch/PR:** direct `main`, continuing the user's explicit no-branch delivery instruction

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `SHADOW_CASE_OPENED -> SHADOW_CASE_OUTCOME`

**Baseline:** 62 official schema-v5 Cases contain 40 non-terminal admitted Entries; 8765 is
unreachable, all 40 latest Observation Segments are `INCOMPLETE_UNCLEAN_EXIT`, and admitted Outcome
count is zero.

**Primary blocker:** `RUNTIME_PROCESS_NOT_RUNNING`; the prior manually launched process was tied to
a temporary execution session and disappeared without a Segment close.

**Expected user-visible delta:** 8765 reports `RUNNING / CURRENT / ready`, and Workbench shows each
of the same 40 admitted Entry identities exactly once for continued public Shadow observation.

**Durable-data effect:** the existing reader preserves every incomplete Segment and opens one new
`HANDOFF_GAP` Segment for each of the 40 compatible non-terminal admitted Entries after a fresh
settled boundary. No admitted Outcome is created by recovery.

**Complexity added:** `NONE`; use the existing external-operator startup and existing recovery path.

**Complexity deleted:** `NONE`.

## Business closure

**Given:** the stable repository is valid, unowned, and contains exactly 40 compatible non-terminal
admitted Entries under the fixed product and Policy identities.

**When:** an external operator starts the existing clean runtime checkout once in a user-owned
foreground Terminal process against the unchanged stable root.

**Then:** all 40 Entries are restored, each current Segment binds the new runtime and is `GAPPED`,
all declared GET/HEAD routes return 200, and no admitted Outcome is fabricated.

**Valid zero/UNKNOWN:** current Position/Outcome economics may remain `UNKNOWN` until strictly future
paired public facts arrive; zero restored Entries does not satisfy this closure.

**Cheapest falsification:** one official-reader inventory plus the six-route HTTP matrix and one
schema-v7 snapshot after readiness.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** authorize exactly one external-operator start of the sole 8765
runtime from `/Users/logan/Optimatrix-runtime@9002b6e` against
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. No retry, stop, migration, alternate
root, second runtime, or process-persistence implementation is authorized.

## Scope

**In:** this task, `CURRENT_STAGE`, direct Authority tests, one foreground Terminal start, official
Case-reader verification, and bounded HTTP/snapshot validation.

**Out:** runtime code, Policy, schema, Case rewrite, data migration, gap reconstruction, process
supervision, automatic restart, launchd, host logs/PID inspection, private execution, and Runtime
persistence design.

**Owning module:** `radar_runtime.service`

## Validation

- focused tests: `PYTHONPATH=apps/radar_runtime/src .venv/bin/pytest -q tests/test_authority_and_architecture.py`;
- repository gate: `PYTHONPATH=apps/radar_runtime/src make check`;
- public observation: official reader, six GET/HEAD routes, and one schema-v7 snapshot;
- no manifest, receipt, commissioning controller, or broad evidence package.

## Definition of done

The sole 8765 runtime stays in a user-owned foreground Terminal process, reports current/ready,
restores the exact 40 Entry set once with new truthful GAPPED Segments, creates no admitted Outcome,
passes the bounded verification, and the final Authority reports the consumed start accurately.
