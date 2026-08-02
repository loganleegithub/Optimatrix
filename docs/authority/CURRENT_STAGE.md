# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current implementation status:**
`LEGACY_IMPLEMENTATION_DISABLED_PENDING_SHADOW_CASE_DATA_BOUNDARY`

**Production Short Vol Radar:** `NOT_ACCEPTED_PENDING_DATA_BOUNDARY_REPLACEMENT`

**Persistent service:** `STOPPED_NO_DEPLOYMENT`

**Live commands:** `FORBIDDEN`

**Sole authorized closure:** `SHORT_VOL_SHADOW_CASE_DATA_BOUNDARY`

## Current truth

The repository contains an offline-capable public Deribit → Radar → Underwriting → admission →
Position → Outcome implementation. Its current persistence model does not conform to the active
Product Constitution because it still writes pre-Shadow Radar and decision objects. That
implementation may be edited and tested offline, but it is not accepted for a production-public
run until the data boundary is replaced.

The authority rewrite itself changes no market source, Policy number, decision formula, private
permission, or execution capability. It changes what the product considers durable data and what
counts as engineering progress.

## Authorized next closure

`SHORT_VOL_SHADOW_CASE_DATA_BOUNDARY` must:

1. keep market, Radar, atomic availability, Underwriting, Candidate, admission, and Workbench state
   in memory before Shadow enrollment;
2. make `SHADOW_CASE_OPENED` the first durable business record;
3. persist only one bounded first-CLOSE transition and one terminal Shadow Case Outcome;
4. remove automatic persisted rejected-counterfactual and online Cohort/aligned-pair records;
5. keep Workbench on in-memory current state;
6. provide one minimal reader that distinguishes complete, censored, and unclean incomplete Cases;
7. preserve the exact three Policies, public-only boundary, causality, `UNKNOWN`, and full-quantity
   official atomic entry/exit requirements.

## Allowed work

- one bounded implementation branch and Draft PR;
- offline code changes and deterministic tests;
- local `make check` and GitHub CI;
- no market command until a later explicit public-read-only smoke task.

## Forbidden work

- Deribit live invocation or deployment;
- credentials, account, balance, margin, private API, order, fill, capital, or actual position;
- Policy tuning or hot reload;
- database, replay platform, event bus, microservice split, Docker/Kubernetes requirement;
- application commissioning, host PID/log inspection, resource acceptance, manifest, receipt chain,
  or 24-hour Soak controller;
- qualification, promotion, or execution controller.

## Acceptance boundary

Green tests can accept only the offline implementation. They do not establish natural opportunity
frequency, strategy value, fillability, uptime, qualification, deployment, or execution authority.
A later public smoke may prove connectivity and current-state reachability only; it may not restore
pre-Shadow persistence or become a recurring evidence ritual.
