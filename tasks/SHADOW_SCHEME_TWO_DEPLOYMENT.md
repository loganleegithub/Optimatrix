# Task — Shadow scheme-two Control Outcome closure

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED — correct the existing Workbench Outcome projection

**Live commands:** REQUIRED — one clean corrective cutover and one bounded API/browser gate

**Base commit:** `deb20e4f2922c823cdd96ea9b4150a6a2883ffaf`

**Target branch/PR:** `codex/control-outcome-projection-fix` / Draft PR `#56`

**Owning authority/contract:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md),
[`SYSTEM_ARCHITECTURE`](../docs/authority/SYSTEM_ARCHITECTURE.md),
[`DELIVERY_CONTRACT`](../docs/authority/DELIVERY_CONTRACT.md), and
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

## Product movement

**Current funnel node:** `SHADOW_CASE_OPENED -> TRADER_REVIEW -> SHADOW_CASE_OUTCOME`

**Baseline:** The stable runtime at `deb20e4` is `RUNNING / CURRENT / ready` with runtime identity
`sha256:9ef0082cf3f860247ea8409416cebe3a04f8ba13a9d91b9693258e8fd5ce22af`, 130/130
current instruments, zero reconnects, and zero session gaps. It recovered 33 responsibilities and
naturally completed eight: one `MARKET_EXIT` and seven `CONTRACT_SETTLEMENT` Outcomes. The official
reader now accepts 44/44 terminal-economic and 23/23 strict terminal-sample Cases, with 25 Cases
still pending. The trader surface correctly shows 20 admitted Shadow positions and excludes all
Controls.

**Primary blocker:** The bounded current-state projection retains the latest terminal Case beside
the 25 active Cases. That latest terminal Case is a Radar score-band Control. Its Position row says
`TERMINAL / SETTLED_KNOWN`, but its Outcome row incorrectly says `PENDING` because `_outcome_rows`
joins only `SHADOW_OUTCOME` and ignores both existing Control Outcome kinds.

**Expected user-visible delta:** The read-only API gives the same known terminal state, method, and
economics for admitted and Control Cases. The admitted-only Shadow risk book remains visually and
behaviorally unchanged.

**Durable-data effect:** NONE from the implementation. The corrective cutover may append only
normal Segment boundaries and naturally observed market-exit or official-settlement Outcomes; it
may not migrate, relabel, backfill, or rewrite any historical Case.

**Complexity added:** NONE — one shared terminal-Outcome source removes the divergent projection.

**Complexity deleted:** Duplicate terminal-Outcome-kind selection in the Position projection.

## Business closure

**Given:** One retained `SHADOW_OUTCOME_OBSERVATION` belongs to an admitted Shadow, selected
underwriting Control, or Radar score-band Control and its matching terminal Outcome already exists.

**When:** The Workbench builds Position and Outcome projections from the same bounded current-state
objects.

**Then:** Both projections resolve the same terminal fact. A Control `SETTLED_KNOWN` Outcome is
never displayed as `PENDING`, while a genuinely outcome-less observation remains `PENDING`.

**Valid zero/UNKNOWN:** No terminal Outcome is valid only before a matching terminal record exists.
It must remain pending and cannot claim known economics. That does not satisfy terminal closure.

**Cheapest falsification:** Direct parameterized projection tests for both Control Outcome kinds,
followed by the official reader and one stable API observation of the naturally terminal Radar
Control.

## Change declarations

**Market/Decision input contract change:** NONE

**Decision Policy change:** NONE

**Outcome/evaluation contract change:** NONE — consume the two already-owned Control Outcome kinds
in the Workbench read model.

**Stage/authorization change:** Authorize one clean stop of runtime
`sha256:9ef0082cf3f860247ea8409416cebe3a04f8ba13a9d91b9693258e8fd5ce22af`, one
replacement start from merged PR `#56`, and one bounded API/browser gate. No product, Policy, Case
root, or private permission change is authorized.

## Scope

**In:** `radar_runtime.workbench` terminal Outcome selection, direct regression tests, Authority,
one clean stable cutover, official reader/API checks, and a bounded admitted-only trader-view gate.

**Out:** Position or Outcome domain changes; Policy or threshold changes; Case migration or replay;
database, supervisor, commissioning, host-resource gates; orders, fills, accounts, or capital.

**Owning module:** `radar_runtime` read model; durable terminal truth remains owned by
`short_vol_underwriting`.

## Validation

- focused tests: `.venv/bin/pytest tests/test_trader_workbench.py tests/test_authority_and_architecture.py -q`;
- repository gate: `make check`;
- public observation: official schema-v3 report plus one stable schema-7 API/browser gate;
- no manifest, receipt chain, process inventory, host-log acceptance, or second Case root.

## Definition of done

Both Control Outcome kinds join their observation exactly like an admitted Outcome; the naturally
terminal Radar Control projects `SETTLED_KNOWN / CONTRACT_SETTLEMENT` with known economics; the
official reader still reports 92 valid Cases, 44 known terminal economics, 23 strict terminal
samples, and 25 pending responsibilities; the Shadow book still contains only 20 admitted
positions; focused and repository gates pass; live commands are consumed; this task is removed;
and `CURRENT_STAGE` records the accepted runtime identity and business result.
