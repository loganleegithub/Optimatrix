# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:**
`RADAR_CANDIDATE_GENERATOR_IMPLEMENTED_PENDING_OBSERVATION`

**Production Short Vol Radar:** `A2_CANDIDATE_VALIDITY_OBSERVATION_PENDING`

**Persistent service:** `STOPPED_NO_DEPLOYMENT`

**Live commands:** `ONE_CONDITIONAL_43200_SECOND_A2_OBSERVATION`

**Sole authorized closure:** `SHORT_VOL_RADAR_CANDIDATE_VALIDITY`

## Current truth

The simplified implementation conforms to the Shadow Case data boundary. Market, Radar, atomic
availability, Underwriting, Candidate, admission attempts, and Workbench state are in memory. A run
with no Shadow admission writes zero Shadow Case business files. The first durable record is
`SHADOW_CASE_OPENED`; only first CLOSE and terminal Outcome may follow. A minimal reader marks an
opened-only Case after an unclean exit as `INCOMPLETE_UNCLEAN_EXIT`.

The one authorized 900-second public-only A1 observation was consumed and stopped cleanly. After
the fixed Radar Policy's real index baseline became available, it counted `1,556,097`
`APPLICABLE_MARKET_SCOPE` evaluations and `1,556,097` `RADAR_KNOWN` evaluations: `100%`, with zero
post-warmup Radar UNKNOWN.

Startup and recovery remained separately visible: `322,817` applicable evaluations, `179,021`
known evaluations, and `143,796` UNKNOWN evaluations. Their bounded reasons were `INDEX_WARMUP`
`64,283` and `POST_STATUS_BOOTSTRAP_REQUIRED` `79,513`; neither was counted as a steady-state
blocker.

The observation naturally reached `146` distinct anomaly Episodes and `146` reviewable structures.
None reached an available official atomic quote because all `146` were blocked by
`NO_ACTIVE_COMBO`. The earliest material funnel loss therefore moved from apparent Radar warmup to
`PUBLIC_ATOMIC_QUOTE_AVAILABLE / NO_ACTIVE_COMBO`. No Shadow Case opened and the durable Shadow Case
file count remained zero.

The A1 observation used the then-current exact Radar, Underwriting, and Position Policy chain. A2
may replace only the Radar benchmark and activation/clear persistence declared below; the dependent
Underwriting and Position Policy bytes may change only to bind the new upstream content identities.
Public source semantics, the TTE/Delta universe, target quantity, option inversion, atomic-combo
semantics, causality, `UNKNOWN`, and full-quantity official atomic entry/exit requirements remain
unchanged. No runtime is deployed and no private/account/order/fill/capital capability exists.

## Active closure

A1 measured `NO_ACTIVE_COMBO` after `146` anomaly Episodes, but its operational-probe Policy used
one one-minute index return and two changed observations separated by only one second. Before combo
conversion can carry opportunity meaning, A2 must establish `RADAR_CANDIDATE_VALIDITY` at the
`ANOMALY_ACTIVE` funnel node.

The authorized implementation keeps the BTC-USDC `30m < TTE <= 72h` OTM call/put universe, target
quantity, executable-bid IV inversion, activation ratio, and atomic semantics fixed. It replaces
the operational benchmark with non-overlapping five-minute returns over declared 30-minute,
120-minute, and 360-minute causal windows, selects the highest realized-variance rate or fixed
floor, and requires time-persistent activation and clear observations. Exact Policy bytes remain
content-identified.

## Allowed work

- read-only repository and Workbench review;
- the active A2 implementation and deterministic local/GitHub checks on its bounded branch;
- exactly one 43,200-second production-public read-only observation after focused tests,
  `make check`, and exact-candidate review pass.

## Forbidden work

- changing the Radar TTE/Delta universe, target quantity, IV inversion, or atomic-combo semantics;
- any Radar Policy or benchmark change outside the exact active A2 task;
- persistent deployment, automatic restart, or more than the one authorized A2 observation;
- credentials, account, balance, margin, private API, order, fill, capital, or actual position;
- durable funnel data, a new persistent diagnostic, database, replay platform, event bus,
  microservice split, or Docker/Kubernetes requirement;
- application commissioning, host PID/log inspection, manifest, receipt chain, broad evidence
  package, 24-hour stability Soak, or anomaly-generation requirement;
- qualification, promotion, or execution controller.

## Acceptance boundary

The A2 implementation may establish that each emitted Radar candidate follows the declared causal,
multi-horizon and time-persistent screen. Its one public observation may establish current
post-warmup reachability, natural candidate frequency during that fixed interval, and the naturally
reached next blocker. It does not establish future frequency, expected return, strategy edge,
general official-combo availability, fillability, qualification, deployment, uptime, or execution
permission.
