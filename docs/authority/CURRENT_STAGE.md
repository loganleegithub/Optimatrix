# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `IMPLEMENTATION`

**Current implementation status:** `INVERSE_BTC_SHORT_VOL_V2_POSITION_LIFECYCLE_EVIDENCE_CLOSURE_IN_PROGRESS`

**Accepted online product:** `INVERSE_BTC_V1_ONLY`

**Accepted implementation boundary:** `INVERSE_BTC_SHORT_VOL_V2_PUBLIC_SHADOW`

**Persistent service:** `RUNNING_8765_CODE_6FF78068A7990584AAE630BD31DBABCD6B90DA9A`

**Live commands:** `TASK_SCOPED_ISOLATED_BUSINESS_SIMULATION_AUTHORIZED_STABLE_CUTOVER_NOT_YET_AUTHORIZED`

**Active closure:**
[`SHADOW_POSITION_LIFECYCLE_REALISM`](../../tasks/SHADOW_POSITION_LIFECYCLE_REALISM.md)

## Current business baseline

The stable repository is
`/Users/logan/OptiMatrix_DATA/Deribit/optimatrix-shadow-v2-v9`. At the repair boundary its direct
record inventory held 87 schema-v5 Cases, 65 immutable first-CLOSE records, and 36 Outcomes. Twenty
Outcomes use contract version 2 and are naturally produced admitted `EXITED_KNOWN/MARKET_EXIT`
results; no naturally produced `SETTLED_KNOWN` exists yet. Legacy history remains immutable.

Runtime code `6ff78068a7990584aae630bd31dbabcd6b90da9a` is the current loopback service at
`127.0.0.1:8765`. Its current projection held 43 non-terminal Positions at the repair boundary:
35 `EXIT_ACQUIRING` and 8 `MONITORING`. Normal public intake may increase those counts while this
task is implemented; counts are a baseline, not a cap or completion criterion.

The prior lifecycle repair correctly separated immutable first CLOSE from continuing quote
acquisition and naturally produced known market-exit economics. The remaining primary blocker is
terminal evidence closure: the durable market-exit pair lacks the complete timing/source fields
needed for independent reader reconstruction; contract settlement validates aggregate arithmetic
without recomputing product payoff and fee semantics; a delivery-history response is incorrectly
conditioned on its request owner's date; and online whole-lifecycle Booleans still act as Cohort
membership.

## Active implementation authority

This task may change only the existing Position/Outcome owner, official delivery-price source
route, schema-v5 Case follow-up version union, official reader, offline Case report, owning
contracts, and deterministic business tests. Existing Case bytes remain immutable and readable.
No new record kind, pre-Shadow persistence, per-attempt tape, database, replay path, supervisor,
order, fill, account, margin, capital, or private execution is authorized.

Future terminal Outcomes use a versioned evidence contract. A market exit must retain enough of
the accepted two-leg response pair for the one Case reader to recompute source identities, causal
ownership, session/continuity equality, skew limits, selected sample identity, quantities, fees,
and economics. Official contract settlement must retain a reconstructable response/member witness
and be recomputed by the existing Inverse product calculator. Older Outcomes remain terminal
economic history but cannot be promoted into stricter evidence Cohorts by rewriting them.

The current Position Policy identity and all nine frozen predicate thresholds remain unchanged.
This repair may bind an explicit exit-acquisition observation profile at a future first CLOSE and
separate its retry cadence from an RPC response deadline, but it cannot reinterpret an existing
first-CLOSE reason. Source-discontinuity, directional-path, liquidity, and normalized threshold
changes require a successor Position Policy after the active legacy book is no longer bound to the
current identity.

Qualification remains offline. New Outcomes do not persist Cohort membership Booleans. The
official report derives terminal economics, continuous path, market-exit evidence, and the bounded
first-CLOSE-to-terminal acquisition window as separate questions. The legacy
`qualification_eligible` Segment field remains only a strict whole-path continuity projection.

## Validation and live boundary

The authorized validation is deterministic direct and integration tests, `make check`, and one
isolated full-business-chain simulation over a consistent copy of the stable Case repository. The
simulation must cover eligible and ineligible paired books, timing/session/continuity failures,
failed and partial delivery histories, call/put settlement regimes, daily and standard delivery
fees, process recovery, Control recovery, reader tamper rejection, Segment truth, and named
offline Cohorts.

This stage does not authorize stopping, replacing, or writing through the stable runtime. Stable
cutover is withheld while the implementation and concurrent Workbench construction remain
unintegrated. A later authority update must name the tested code identity, preserve all existing
Case bytes, establish compatible-reader rollback, and explicitly authorize the one stable cutover.

Permission remains `PUBLIC_SHADOW`: production public facts and counterfactual economics only. A
public book or delivery price is not an order, fill, settlement action, actual position, account
PnL, or capital exposure. Green tests, a responsive Workbench, `PENDING`, or `GAPPED` do not qualify
a Policy or prove terminal economics.
