# Task — One business closure

**Status:** DRAFT | ACTIVE

**Task kind:** AUTHORITY_ONLY | IMPLEMENTATION | VALIDATION_ONLY

**Target maturity stage:** exact `CURRENT_STAGE` identifier

**Runtime implementation:** REQUIRED | FORBIDDEN

**Live commands:** FORBIDDEN | exact command, bounds, attempts, output, and retry rule

**Owning authority/contract:** exact link

No placeholder may remain when this task becomes `ACTIVE`. Stage must link this file as the only
active non-template task.

## Closure

**Given:** observable prerequisite

**When:** one bounded change or observation

**Then:** observable result

**Affected identity and population:** exact MarketObservation, DecisionWindow, OpportunityEpisode,
TradeCase, Position, or `NOT_APPLICABLE`

**Baseline and denominator:** exact values or `NOT_YET_MEASURED` with reason

**Primary blocker and expected delta:** earliest measured reason and exact change

**Known-at and DataHealth boundary:** causal input and valid `UNKNOWN`

## Effects and scope

**Risk allocation effect:** NONE or exact Shadow/account fact and release rule

**ObservationLedger / CaseJournal effect and consumer:** NONE or exact owned record

**Legacy-data effect:** NONE unless Product Authority changes isolation

**Permission effect:** NONE or exact Stage change

**Files and behavior in scope:** exact bounded list

**Out of scope:** exact boundary

**Complexity added / deleted:** exact surfaces and current consumers

## Verification and closure

**Cheapest falsification:** exact focused check or bounded observation

**Repository gate:** `make check` or exact applicable gate

**External evidence:** exact authorized check or `UNVERIFIED`

Close only after directly observing the declared delta. Replace Stage with the post-task snapshot
and remove this file; do not append completion history.
