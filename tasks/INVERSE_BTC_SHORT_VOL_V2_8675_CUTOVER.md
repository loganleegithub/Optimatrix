# Task — Inverse BTC Short Vol V2 8675 cutover

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** NOT_APPLICABLE

**Live commands:** ONE NEW-ROOT 8675 START, ONE BOUNDED READ-ONLY SMOKE

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
on the requested loopback port `8675`; all six declared `8765` routes refused connection before the
start, so the superseded H2 process is already unavailable.

**Primary blocker:** `V2_COHERENCE_POLICY_CHAIN_NOT_ONLINE` (`1 / 1` required Online Runtime)

**Expected user-visible delta:** `http://127.0.0.1:8675` exposes the sole
`INVERSE_BTC_SHORT_VOL_V2` Workbench with the fixed schema-v9 Radar chain, replacing the already
unavailable `8765` surface.

**Durable-data effect:** before cutover the official schema-v5 reader inventories the old H2 root
as `0` Case directories.
The new process creates and exclusively owns the previously absent stable root
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. It copies, migrates, rewrites,
deletes, or recovers no Case from the old root. Because the prior process is already absent and the
old root is empty, this cutover writes no Segment close there.

**Complexity added:** NONE. This task adds no code, Policy, service manager, retry controller,
manifest, or alternate runtime path.

**Complexity deleted:** NONE; the superseded `8765` process was already absent.

## Business closure

**Given:** `main@b6fb446ca608648ac4a0d872e656eaee0ddedbfb` contains the verified fixed V2
Policy chain and the new stable root is absent.

**When:** one clean task-branch commit starts the canonical public-only service exactly once on
`127.0.0.1:8675`, the bounded route/current-state/official-reader smoke passes, and the prior
`8765` process is then clean-stopped once.

**Then:** one Online Runtime on `8675` reports the exact product and new three-Policy identities,
`RUNNING / CURRENT / ready`, and a reader-valid fresh schema-v5 repository; `8765` remains down.

**Valid zero/UNKNOWN:** zero new Cases, Candidates, Entries, Controls, Positions, or mature Outcomes
is valid for this cutover. Source warmup or a current market blocker remains truthful `UNKNOWN` and
does not invalidate identity/reachability acceptance. A failed start, identity mismatch, malformed
root, or unhealthy route blocks the cutover and leaves the product unavailable; no retry is
authorized.

**Cheapest falsification:** exact HTTP GET/HEAD route smoke, immutable current snapshot assertions,
and one official schema-v5 reader scan of each declared root.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE; deploy only the already-merged fixed chain.

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** after confirming the superseded `8765` surface is already down,
authorize one fresh-root start on `8675` and one bounded read-only smoke. No retry, restart, second
root, repoint, Case migration, source-contract probe, threshold tuning, or private action.

## Scope

**In:** the observed six-route 8765 connection refusal and old-root official-reader inventory;
absence check for the exact new root; one canonical 8675 start; six declared GET/HEAD routes,
current API, identity and official-reader smoke; final Authority record.

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
and truthful current public state; 8765 remains unavailable; no unauthorized retry or extra durable
object occurs; the task is removed; CURRENT_STAGE records the resulting boundary; and one Draft PR
contains the bounded cutover closure.
