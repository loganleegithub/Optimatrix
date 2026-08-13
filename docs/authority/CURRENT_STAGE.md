# Optimatrix Current Stage

**Status:** CURRENT IDLE PERMISSION SNAPSHOT

**Implemented Channel:** `INVERSE_BTC_SHORT_VOL`

**Implementation:** `BTC_0DTE_TWO_SIDED_PREMIUM_SALE_V1`

**Current task kind:** `NONE`

**Sole authorized closure:** `NONE`

## Current permissions

This Stage is the permission ceiling; an active task may only narrow it.

**Offline simulation:** authorized

**Public snapshot:** `NONE_AUTHORIZED`

**Continuous runtime:** `NONE`

**Stable Decision Case root:** `NONE_AUTHORIZED`

**Private/account/order permission:** `NONE`

**Policy qualification / Edge claim:** `NONE`

## Current unresolved truth

Offline checks cover the implemented path, but they do not prove full contract conformance:

- Entry Authority permits unresolved acquisition truth to remain `UNKNOWN`; the current
  `EntryStatus` has no `UNKNOWN` member and some missing-input paths emit `NO_ENTRY`.
- The engine emits the four authorized journal event kinds, but `CaseJournal.append/read` do not
  themselves enforce that allowlist or the complete lifecycle order and conflict rules.
- Source exposes `strategy_outcome_eligible`; the other independent lifecycle eligibility
  dimensions are not yet represented as current implementation facts.

**Primary blocker:** `ENTRY_UNKNOWN_NOT_REPRESENTABLE` — required missing Entry facts can collapse
into a known acquisition result.

The live-market `SessionDecisionUnit` denominator is also `NOT_YET_MEASURED`, and live source
reachability is `UNVERIFIED`. Offline fixtures establish neither opportunity frequency nor Policy
qualification, Edge, Alpha, win rate, or profitability.

**Upgrade condition:** later `IMPLEMENTATION` tasks must close the Authority/source gaps without
weakening the contracts. A later task and matching Stage may separately authorize the smallest
bounded public observation needed to falsify its declared delta. Repeated observation, stable
persistence, continuous runtime, private methods, account access, orders, fills, capital, and
deployment require their own authority.
