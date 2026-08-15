# Task — B3 reconnect index-history recovery

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** REQUIRED

**Live commands:** the existing launchd label `com.optimatrix.b3-public-shadow` may continue its
exact EventState `NONE` public Shadow command against
`/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2`. After `make check`
passes and the reviewed commit is pushed to `origin/main`, exactly one replacement via
`launchctl kickstart -k gui/501/com.optimatrix.b3-public-shadow` is authorized. The replacement may
make the existing public calls plus at most one unauthenticated
`public/get_index_chart_data(index_name=btc_usd, range=2d)` recovery call for each newly established
WebSocket connection epoch. No retry within that epoch is authorized; failure remains a typed Gap.

The runtime and change retain Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, the exact stable root,
loopback Workbench port `8765`, and launchd label `com.optimatrix.b3-public-shadow`.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`, `docs/contracts/CASE_POSITION_OUTCOME.md`, and
`docs/research/PRIMARY_SOURCES.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** in the completed Session ending `2026-08-15T08:00:00Z`, the corrected runtime produced
`61/69` evaluable Decisions after its `14:45 UTC` deployment. A WebSocket disconnect at `04:30 UTC`
failed that Window, and the retained discontinuous index history then caused five consecutive
`index history contains a material risk-horizon gap` failures through `05:45 UTC`. Current source
seeds historical index points only at initial feed startup; reconnect starts a new connection epoch
without reseeding that causal history.

**When:** the existing public WebSocket feed obtains exactly one validated two-day BTC index-history
seed for each new connection epoch after the initial epoch, then accepts a cut only after a strictly
later BTC index notification and all required option books and tickers belong to that same epoch

**Then:** a deterministic mid-horizon disconnect keeps the affected Window `UNKNOWN`, but the next
eligible Window can recover from a validated historical seed plus later same-epoch WebSocket
continuation; malformed, unavailable, late, identity-incoherent, or discontinuous recovery data
fails closed with an exact Gap and cannot create a Decision

**Affected identity and population:** future in-memory BTC public WebSocket connection epochs and
their not-yet-finalized DecisionWindows only; every existing DecisionRecord, WindowOutcome,
MarketObservation, TradeCase, Position, settlement, and prior Session identity is immutable

**Baseline and denominator:** one directly observed disconnect amplified into six unavailable
DecisionWindows, five of them caused by the retained history gap; post-correction evaluability is
`61/69`. This is reliability evidence, not Policy or market-opportunity evidence.

**Primary blocker and expected delta:** `RECONNECT_INDEX_HISTORY_GAP_AMPLIFICATION` becomes one
bounded epoch-local recovery path; a disconnect does not become a successful cut, and later cuts
recover only from independently validated REST history plus a later WebSocket continuation

**Known-at and DataHealth boundary:** the REST response receipt owns the history seed's known-at
boundary; history points may not follow receipt, regress, duplicate timestamps, use a foreign index,
or violate cadence. The current index, book, and ticker cut remains owned by the later WebSocket
epoch and unchanged freshness/source-span/receive-span limits.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** no backfill or schema change; only a future
healthy not-yet-finalized Window may consume the recovered in-memory history through the existing
snapshot evaluator. The Ledger and Journal remain unchanged owners.

**Legacy-data effect:** NONE; v1 and all completed v2 facts remain excluded from mutation

**Permission effect:** add only one unauthenticated `public/get_index_chart_data` recovery call per
new WebSocket connection epoch. Preserve the existing public method allowlist, endpoint, launchd
job, stable root, EventState, and every private/order/capital prohibition.

**Files and behavior in scope:** `src/optimatrix/deribit_websocket.py`, the minimum runtime-source
wiring in `src/optimatrix/runtime.py`, their direct tests, this task, matching Stage facts, and only
owner text that must distinguish initial from reconnect index-history recovery

**Out of scope:** retry loops within an epoch, continuous REST polling, Decision or Outcome backfill,
generic replay, databases, queues, durable index history, new dependencies, raw/authenticated feeds,
Combo observation, historical Workbench UI, Policy, `7%`, `$10`, sizing, ranking, Candidate
manufacture, private facts, orders, fills, capital, Policy qualification, Edge, remote deployment,
and B4

**Complexity added / deleted:** reuse the existing history parser, cache seed validator, public-call
audit, and connection epoch. Add only one epoch-scoped recovery callback/state transition and its
current runtime consumer; add no scheduler, persistence, retry framework, or alternate feed.

## Verification and closure

**Cheapest falsification:** a focused transport test proves that reconnect without a valid seed
remains unavailable, while one valid seed alone is insufficient until a later same-epoch WebSocket
index notification arrives; a second seed request in the same epoch is rejected or absent

**Repository gate:** `make check`

**External evidence:** after the one authorized replacement, `launchctl print` must show one running
PID under the exact label and root, loopback Workbench must return HTTP `200`, and one later healthy
public cut must retain WebSocket market-source identity. A natural disconnect, Candidate, private
account fact, execution, profitability, Policy qualification, and Edge remain `UNVERIFIED`.

Close only after directly observing the declared implementation and deployment delta. Replace Stage
with the post-task snapshot and remove this file; do not append completion history.
