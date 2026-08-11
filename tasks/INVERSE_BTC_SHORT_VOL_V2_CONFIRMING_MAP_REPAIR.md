# Task — V2 confirming strong-signal map repair and clean restart

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** ONE_CLEAN_STOP_AND_ONE_CLEAN_START_8765

**Base commit:** `7f55972028073570be7774b25f40184f8cba25e1`

**Target branch/PR:** direct `main` commits; no feature branch or PR by explicit user instruction

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

## Product movement

**Current funnel node:** trader review of `RADAR_KNOWN -> ANOMALY_ACTIVE`

**Baseline:** one current schema-v7 snapshot has 128 Radar rows, 17 HIGH scores, and nine
clue-eligible HIGH bucket leaders in `CONFIRMING 1/3`, but the Workbench strong-signal numerator is
incorrectly zero.

**Primary blocker:** `BROWSER_REQUIRES_EPISODE_IDENTITY_BEFORE_CONFIRMATION_COMPLETES`

**Expected user-visible delta:** every server-owned clue-eligible HIGH leader in `CONFIRMING` appears
at its expiry and strike with the exact confirmation counter; `ACTIVE` continues to require the
server-owned Episode identity.

**Durable-data effect:** the browser change writes nothing. The authorized clean restart closes one
current Segment per active admitted Entry and the successor runtime opens one new GAPPED Segment per
compatible non-terminal Entry. It creates no mature Outcome and does not copy or migrate Cases.

**Complexity added:** NONE

**Complexity deleted:** one impossible pre-activation Episode-identity requirement and its
unrepresentative test fixture.

## Business closure

**Given:** a complete current Radar snapshot with clue-eligible HIGH leaders whose owner state is
`CONFIRMING` and whose Episode identity is correctly absent until activation.

**When:** the browser applies the contract's `HIGH + leader + clue eligible + CONFIRMING|ACTIVE`
subset with state-coherent identity validation.

**Then:** the strong-signal map shows the confirming leaders instead of a false zero, while malformed
CONFIRMING-with-identity and ACTIVE-without-identity rows remain excluded.

**Valid zero/UNKNOWN:** zero remains valid only when no current row satisfies that exact subset;
disconnected, stale, incomplete, or identity-mismatched snapshots remain UNKNOWN and hide old data.

**Cheapest falsification:** a fixture with a valid CONFIRMING row and `bucket_episode_identity=null`
must render, while the two incoherent identity/state combinations must not; the real restarted
snapshot must report the same visible numerator as the exact server predicate.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** one clean stop/start on 8765 and one bounded verification; direct
main delivery is explicitly user-authorized for this task.

## Scope

**In:** Workbench static predicate, direct frontend tests, task/Authority, exact-main runtime
checkout, unchanged stable repository, clean 8765 restart, and bounded route/API/Case verification.

**Out:** Radar formula, thresholds, leader/confirmation owner, Policy artifacts, API/Case schema,
stable-root migration, Case copying/deletion, private execution, host inspection, commissioning,
supervision, and roadmap channels.

**Owning module:** `short_vol_radar.bucket` remains the confirmation/Episode owner;
`radar_runtime.workbench_static` only selects its typed current rows.

## Validation

- focused tests: `PYTHONPATH=apps/radar_runtime/src .venv/bin/pytest -q tests/test_workbench_frontend_v1.py tests/test_trader_workbench.py tests/test_authority_and_architecture.py`;
- repository gate: `PYTHONPATH=apps/radar_runtime/src make check`;
- public observation: one post-start GET/HEAD route matrix, one schema-v7 snapshot comparison, and
  one official Case-reader inventory;
- no manifest, receipt, commissioning, broad host inspection, or second runtime.

## Definition of done

The real 8765 strong-signal map no longer reports a false zero for valid CONFIRMING leaders;
state-coherent identity checks and exact server counts remain tested; all compatible admitted
Entries survive the clean restart exactly once; focused, full, route, snapshot, and Case-reader
checks pass; Policy/schema/root/public-only boundaries remain unchanged; and final Authority removes
this completed task.
