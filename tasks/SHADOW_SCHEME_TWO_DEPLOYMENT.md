# Task — Shadow scheme-two stable deployment

**Status:** ACTIVE

**Task kind:** VALIDATION_ONLY

**Runtime implementation:** NOT_APPLICABLE — the accepted implementation is already merged

**Live commands:** REQUIRED — one corrective long-lived-session start and one bounded API/browser
gate

**Base commit:** `3e59d6fde7d2de4c50777f909eb67f100a0dc88b`

**Target branch/PR:** `codex/shadow-deployment-corrective-start` / Draft PR `#55`

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `SHADOW_CASE_OPENED -> TRADER_REVIEW -> SHADOW_CASE_OUTCOME`

**Baseline:** Scheme-two Shadow and the first deployment Authority are merged at `93b0b0c`, and the
clean deployment checkout is synchronized to that identity. The authorized detached background
launch did not persist in the execution host: no stable listener or service lease remains. The
post-attempt official inactive reader still accepts 92 schema-v5 Cases; terminal economics remain
36/36 known Outcomes, strict terminal-sample integrity remains 15/15 known Outcomes, and the store
still exposes the same 33 recoverable lifecycle responsibilities comprising 21 admitted Shadow
trades, 8 Radar score-band Controls, and 4 selected underwriting-decision Controls.

**Primary blocker:** The accepted trader surface and its cross-process Position responsibility are
not running at the stable product address.

**Expected user-visible delta:** `127.0.0.1:8765` serves the merged scheme-two expiry risk book,
showing only admitted Shadow positions while the runtime resumes all 33 compatible admitted and
Control responsibilities behind the read-only surface.

**Durable-data effect:** No migration, copy, relabel, deletion, or historical rewrite. Normal
startup may append only contract-authorized Segment facts and naturally observed market-exit or
official-settlement Outcomes to the existing stable Case root.

**Complexity added:** NONE

**Complexity deleted:** NONE

## Business closure

**Given:** The merged implementation is accepted, the first detached host launch did not persist,
the stable listener and service lease are absent, the deployment checkout is clean, and the same
33 compatible Cases still carry lifecycle responsibility.

**When:** Exactly one corrective runtime is started in a long-lived execution session against the
unchanged stable Case root.

**Then:** The runtime restores every compatible responsibility, serves the scheme-two trader view
at the stable URL, keeps Controls out of the Shadow book, and truthfully exposes any naturally
completed terminal Outcome without converting a Gap into a CLOSE or terminal claim.

**Valid zero/UNKNOWN:** Zero current admitted rows is valid only if the official reader proves all
admitted responsibilities terminal. UNKNOWN market or settlement facts remain pending and do not
satisfy a known terminal-economics claim.

**Cheapest falsification:** A focused authority test, `make check`, one stable API snapshot, the
official Case reader, and one desktop/responsive browser observation.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** Record that the detached host launch did not persist and authorize
exactly one corrective long-lived-session start plus the existing bounded API/browser gate. No
second product, Policy, Case root, or private permission is authorized.

## Scope

**In:** corrective deployment authority, the existing clean deployment checkout, stable service
start, official reader/API checks, and desktop/responsive trader-view validation.

**Out:** runtime implementation edits; Policy or threshold changes; Case migration or replay;
database, supervisor, commissioning, host-resource gates; orders, fills, accounts, or capital.

**Owning module:** `radar_runtime`, with lifecycle truth owned by `short_vol_underwriting`.

## Validation

- focused tests: `.venv/bin/pytest tests/test_authority_and_architecture.py -q`;
- repository gate: `make check`;
- public observation: one stable start followed by the official Case reader and one bounded
  schema-7 API/browser gate;
- no manifest, receipt chain, process inventory, host-log acceptance, or second Case root.

## Definition of done

The clean deployment checkout runs the merged code at `127.0.0.1:8765`; every compatible admitted
and Control Case resumes; the scheme-two Shadow book contains only admitted positions and preserves
the public-read-only boundary; official terminal counts remain reader-valid after any natural
append; focused and repository gates pass; live commands are consumed; this task is removed and
`CURRENT_STAGE` records the exact accepted runtime identity and business result.
