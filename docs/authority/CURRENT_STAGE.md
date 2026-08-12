# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `VALIDATION_ONLY`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_SHADOW_SCHEME_TWO_DEPLOYMENT_AUTHORIZED`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `STOPPED_8765_CODE_93B0B0C068631EF51CDDDDC211C31A87EDC03909_PENDING_ONE_CORRECTIVE_START`

**Live commands:** `ONE_CORRECTIVE_LONG_LIVED_SESSION_START_AND_BOUNDED_API_BROWSER_GATE_AUTHORIZED`

**Sole authorized closure:**
[`SHADOW_SCHEME_TWO_DEPLOYMENT`](../../tasks/SHADOW_SCHEME_TWO_DEPLOYMENT.md)

## Accepted implementation and current outage fact

PR `#53` merged the accepted scheme-two Shadow trader surface at code identity
`3e59d6fde7d2de4c50777f909eb67f100a0dc88b`. Its implementation changes presentation only: no
product, Position lifecycle, Policy, Case schema, Cohort, or durable record contract changed.

The stable address `127.0.0.1:8765` is currently unavailable. The clean deployment checkout at
`/Users/logan/Optimatrix-runtime` is synchronized to merged Authority identity
`93b0b0c068631ef51cddddc211c31a87edc03909`; imports resolve from that checkout. This authority
does not claim that the code is currently serving the stable address.

The stable Case root remains
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. The official inactive version-3
reader accepts 92 schema-v5 Cases. Its terminal-economics view contains 36/36 known Outcomes and
its strict terminal-sample view contains 15/15 known Outcomes. The Case store exposes 33
recoverable lifecycle responsibilities: 21 admitted Shadow trades, 8 Radar score-band Controls,
and 4 selected underwriting-decision Controls. Thirty-two are truthfully `GAPPED`; Gap is
observation quality and does not end Position responsibility.

## Consumed host launch and authorized correction

The first authorized detached background launch did not persist in the execution host. Direct
loopback access found no listener, and the contract-owned non-blocking service lease is unowned.
The official reader still accepts the same 92 Cases, exposes the same 33 recoverable
responsibilities, and reports the unchanged 36/36 terminal-economic and 15/15 strict
terminal-sample known Outcomes. There is no evidence of a terminal Outcome, migration, or Case
rewrite from the non-persisting launch.

This closure authorizes exactly:

1. merge this correction through Draft PR `#55` and synchronize the existing clean deployment
   checkout to that merged `main` identity;
2. start exactly one corrective runtime in a long-lived execution session against the unchanged
   stable Case root and `127.0.0.1:8765`;
3. verify import provenance, code/runtime identity, health/readiness, schema-7 API, the official
   Case reader, and recovery of every compatible lifecycle responsibility;
4. perform one bounded desktop and responsive browser gate over the merged scheme-two Radar and
   Shadow surfaces, including row/detail identity, admitted-only Shadow display, responsibility
   wording, public-read-only boundary, and application console errors.

Normal startup may append only contract-authorized Segment facts and naturally observed
market-exit or official-settlement Outcomes. No historical Case may be migrated, copied, deleted,
relabeled, rewritten, or backfilled. Qualification remains offline and window-specific.

## Product truth and non-claims

The sole Online Runtime product remains `INVERSE_BTC_V1` under the unchanged fixed Radar,
Underwriting, and Position Policy identities. The current Position Policy identity and all nine
frozen predicate thresholds remain unchanged. No product, schema family, Case root, record kind,
market source, order/fill/account boundary, or private permission changed.

Permission remains `PUBLIC_SHADOW`: production public facts and counterfactual economics only. A
public book or delivery price is not an order, fill, settlement action, actual position, account
PnL, or capital exposure. `PENDING`, `GAPPED`, a responsive Workbench, green tests, or a recovered
Case do not qualify a Policy or prove terminal economics. The current Position Policy identity and
all nine frozen predicate thresholds remain unchanged. This task authorizes no order, fill,
account, capital, private-data, second-product, second-Case-root, Policy, or qualification change.
