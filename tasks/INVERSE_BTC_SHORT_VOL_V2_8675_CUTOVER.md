# Task — Inverse BTC Short Vol V2 8675 cutover

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** NOT_APPLICABLE

**Live commands:** ONE NEW-ROOT 8675 START, ONE BOUNDED READ-ONLY SMOKE, ONE 8765 CLEAN STOP

**Base commit:** `b6fb446ca608648ac4a0d872e656eaee0ddedbfb`

**Target branch/PR:** `codex/inverse-btc-short-vol-v2-8675-cutover`; one Draft PR

**Owning authority/contract:**
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `ANOMALY_ACTIVE -> SHADOW_CASE_OPENED`

**Baseline:** `0 / 1` Online Runtime instances bind the repository's causal-coherence Policy chain
on the requested loopback port `8675`; the accepted H2 process on `8765` still binds the superseded
three-Policy chain.

**Primary blocker:** `V2_COHERENCE_POLICY_CHAIN_NOT_ONLINE` (`1 / 1` required Online Runtime)

**Expected user-visible delta:** `http://127.0.0.1:8675` exposes the sole
`INVERSE_BTC_SHORT_VOL_V2` Workbench with the fixed schema-v9 Radar chain, while the superseded
`8765` surface is cleanly stopped only after the new surface passes its bounded smoke.

**Durable-data effect:** before cutover the official schema-v5 reader inventories the old H2 root.
The new process creates and exclusively owns the previously absent stable root
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. It copies, migrates, rewrites,
deletes, or recovers no Case from the old root. Clean stop closes only any open admitted-Entry
Observation Segments in the old root; every Case and non-terminal Entry remains there.

**Complexity added:** NONE. This task adds no code, Policy, service manager, retry controller,
manifest, or alternate runtime path.

**Complexity deleted:** the superseded live `8765` process after successful `8675` acceptance.

## Business closure

**Given:** `main@b6fb446ca608648ac4a0d872e656eaee0ddedbfb` contains the verified fixed V2
Policy chain and the new stable root is absent.

**When:** one clean task-branch commit starts the canonical public-only service exactly once on
`127.0.0.1:8675`, the bounded route/current-state/official-reader smoke passes, and the prior
`8765` process is then clean-stopped once.

**Then:** one Online Runtime on `8675` reports the exact product and new three-Policy identities,
`RUNNING / CURRENT / ready`, and a reader-valid fresh schema-v5 repository; `8765` no longer serves.

**Valid zero/UNKNOWN:** zero new Cases, Candidates, Entries, Controls, Positions, or mature Outcomes
is valid for this cutover. Source warmup or a current market blocker remains truthful `UNKNOWN` and
does not invalidate identity/reachability acceptance. A failed start, identity mismatch, malformed
root, or unhealthy route blocks the cutover and leaves `8765` running; no retry is authorized.

**Cheapest falsification:** exact HTTP GET/HEAD route smoke, immutable current snapshot assertions,
and one official schema-v5 reader scan of each declared root.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE; deploy only the already-merged fixed chain.

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** authorize one fresh-root start on `8675`, one bounded read-only
smoke, and—only after it passes—one clean stop of the superseded `8765` process. No retry, restart,
second root, repoint, Case migration, source-contract probe, threshold tuning, or private action.

## Scope

**In:** current 8765 snapshot and old-root official-reader inventory; absence check for the exact
new root; one canonical 8675 start; six declared GET/HEAD routes, current API, identity and official
reader smoke; one later 8765 clean stop; final Authority record.

**Out:** code or Policy changes; root copy/migration/deletion; reuse of either old V1 `/private/tmp`
root or old H2 root; retry/automatic restart; PID/log/`lsof`/launchd inspection; process supervisor;
private/account/order/fill/capital behavior; opportunity-frequency or Edge gate.

**Owning module:** external operation of the existing `radar_runtime` composition root.

## Validation

- focused tests: `.venv/bin/pytest -q tests/test_authority_and_architecture.py`;
- repository gate: `make check` before the one start;
- public observation: one bounded read-only smoke after the one 8675 start;
- no manifest, receipt, commissioning controller, host inspection, replay, or broad evidence
  package.

## Definition of done

The repository and remote checks pass from one clean commit; the old root is inventoried and
preserved; the fresh non-temporary root is reader-valid; 8675 exposes the exact new identity chain
and truthful current public state; 8765 is then clean-stopped; no unauthorized retry or extra
durable object occurs; the task is removed; CURRENT_STAGE records the resulting boundary; and one
Draft PR contains the bounded cutover closure.
