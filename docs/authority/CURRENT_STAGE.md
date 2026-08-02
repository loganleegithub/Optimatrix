# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:**
`OFFLINE_SHADOW_CASE_DATA_BOUNDARY_IMPLEMENTED`

**Production Short Vol Radar:** `OFFLINE_READY_PENDING_FUNNEL_SMOKE`

**Persistent service:** `STOPPED_NO_DEPLOYMENT`

**Live commands:** `ONE_BOUNDED_FUNNEL_SMOKE_CONDITIONALLY_AUTHORIZED`

**Sole authorized closure:** `SHORT_VOL_FUNNEL_PRIMARY_BLOCKER`

## Current truth

The simplified offline implementation now conforms to the Shadow Case data boundary. Market,
Radar, atomic availability, Underwriting, Candidate, admission attempts, and Workbench state are
in-memory. A run with no Shadow admission writes zero business files. The first durable record is
`SHADOW_CASE_OPENED`; only first CLOSE and terminal Outcome may follow. A minimal reader marks an
opened-only Case after an unclean exit as `INCOMPLETE_UNCLEAN_EXIT`.

The exact Radar, Underwriting, and Position Policy files, public source semantics, causality,
`UNKNOWN`, and full-quantity official atomic entry/exit requirements remain unchanged. No runtime
is deployed and no private/account/order/fill/capital capability exists.

## Authorized next closure

`SHORT_VOL_FUNNEL_PRIMARY_BLOCKER` must add bounded in-memory funnel diagnostics and identify the
earliest material conversion loss. Funnel state is not durable business data. After the exact
candidate passes repository checks, the task conditionally authorizes one result-independent
production-public read-only smoke. The smoke may report a natural no-hit result; it may not tune a
Policy, extend itself after inspecting output, retry, deploy, or create an evidence ritual.

## Allowed work

- one bounded implementation branch and Draft PR;
- offline code changes, deterministic tests, local checks, and GitHub CI;
- exactly one bounded public-only smoke after checks pass, using only the loopback Workbench API;
- one SIGINT stop at the predeclared duration.

## Forbidden work

- persistent deployment or automatic restart;
- credentials, account, balance, margin, private API, order, fill, capital, or actual position;
- Policy tuning, threshold changes, hot reload, or run extension after observing results;
- durable funnel data, database, replay platform, event bus, microservice split, Docker/Kubernetes
  requirement;
- application commissioning, host PID/log inspection, manifest, receipt chain, broad artifact
  package, 24-hour Soak, or second smoke invocation;
- qualification, promotion, or execution controller.

## Acceptance boundary

Green tests establish the offline diagnostics. The one public smoke establishes only what its
covered interval naturally reached. It cannot establish strategy value, opportunity frequency,
fillability, qualification, deployment, or execution permission.
