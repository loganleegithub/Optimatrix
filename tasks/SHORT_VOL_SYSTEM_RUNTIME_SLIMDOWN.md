# Task — Short Vol system runtime slimdown

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Runtime implementation:** REQUIRED

**Live commands:** FORBIDDEN

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md)

**Implementation contracts:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md) /
[`SHORT_VOL_UNDERWRITING_POSITION`](../docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) /
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](../docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md) /
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](../docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)

**Base commit:** `57ed063f72780d48b70540b1f6cda944b37d8cfb`

**Target branch:** `codex/system-slimdown`

## Business closure

**Given:** `serve-shadow` is the sole complete product path and its typed Radar and downstream
owners already determine business state before persistence.

**When:** the unused Radar-only command, repository readers, duplicate persistence validators,
schema mirrors, envelope provenance mirror, and their validation-only tests are removed.

**Then:** one process still performs Deribit public ingestion → Radar → Underwriting → Shadow →
Position → Outcome → Workbench, while persistence only serializes the business objects already
produced by those owners. No second calculation or proof graph surrounds the runtime.

**Valid zero/no-hit/UNKNOWN result:** unchanged. Missing business facts remain `UNKNOWN`; no
anomaly, Candidate, Entry, Position action, close opportunity, or Outcome is manufactured.

## Change declarations

1. **Market/Decision input contract change:** `NONE`.
2. **Decision Policy change:** `NONE`.
3. **Outcome/evaluation contract change:** kind-specific business identity equations, payloads,
   arithmetic, lifecycle, and denominators are unchanged. The contract content digests change with
   the accepted contract bytes; duplicate persistence-envelope provenance and readback validation
   cease to be product requirements.
4. **Stage/authorization change:** `NONE`; deterministic offline implementation only.

## Scope

**In:** Radar and downstream persistence adapters, `radar_runtime` CLI composition, direct tests,
and exact documentation that requires the removed duplicate surfaces.

**Out:** market sources, causal order, continuity, formulas, all three Policies, business payload
fields, Workbench schema, private APIs, deployment, and live activity.

## Required behavior

- `serve-shadow` remains the only CLI command and uses one reducer and one downstream owner.
- Radar and downstream writers serialize owner-produced objects once and retain immutable
  identity-conflict behavior.
- Workbench continues to consume the writer's in-memory current object set and revision.
- No repository reader, duplicate payload-schema table, source-provenance envelope, directory
  graph validator, compatibility path, or acceptance controller remains.
- Focused business-chain tests and `make check` pass without live or replay commands.

## Evidence boundary

Passing tests prove only the offline business composition and the absence of the duplicate
persistence proof layer. They do not prove production connectivity, uptime, latency, Policy
quality, fillability, profitability, actual exposure, PnL, deployment, or execution permission.

## Definition of done

The complete public business chain is unchanged; redundant production modules and tests are
absent; authority and implementation describe one consistent system; static forbidden-surface
search, focused tests, and `make check` pass; and the final diff is committed on the target branch.
