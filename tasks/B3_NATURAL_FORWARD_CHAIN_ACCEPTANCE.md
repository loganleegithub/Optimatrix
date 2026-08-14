# Task — B3 natural forward chain acceptance

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `B3_ATOMIC_PUBLIC_SHADOW`

**Runtime implementation:** REQUIRED, limited to defects directly falsified by the authorized
natural feed and the exact runtime authorization required by the persistent successor deployment

**Live commands:** the user explicitly authorizes one persistent replacement deployment under
launchd label `com.optimatrix.b3-public-shadow`. It must execute only the merged and pushed
`origin/main` console script from `/Users/logan/Optimatrix`, with exactly:

```bash
/Users/logan/Optimatrix/.venv/bin/optimatrix-shadow runtime \
  --event-state NONE \
  --root "/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2" \
  --workbench-port 8765
```

The existing validation PID may be operator-interrupted once to release v2. The old launchd job may
be booted out, its plist updated in place, and the same label bootstrapped once with `RunAtLoad` and
`KeepAlive`. Read-only `launchctl`, `ps`, `lsof`, loopback HTTP, root-recovery, and log checks are
authorized. The registered detached worktree `/Users/logan/Optimatrix-live` may be removed only
after the replacement job is healthy. No other runtime, root, port, label, deployment target, or
private method is authorized.

**Superseded validation command:** the three bounded launches below are exhausted historical
evidence and are no longer authorized:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import json
import time
from pathlib import Path

import optimatrix.runtime as runtime_module
from optimatrix.deribit_snapshot import DeribitSourceError
from optimatrix.market import EventState
from optimatrix.policy import DEFAULT_BTC_SHORT_VOL_POLICY_PATH, load_btc_short_vol_policy
from optimatrix.runtime import BtcPublicShadowRuntime, DeribitPublicRuntimeSource

ROOT = Path("/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2")
MAX_SECONDS = 604800
policy = load_btc_short_vol_policy(DEFAULT_BTC_SHORT_VOL_POLICY_PATH)
runtime_module.AUTHORIZED_RUNTIME_POLICY_IDENTITY = policy.identity
source = DeribitPublicRuntimeSource(policy=policy, event_state=EventState.NONE)
runtime = BtcPublicShadowRuntime(
    root=ROOT,
    policy=policy,
    source=source,
    event_state=EventState.NONE,
)
started = time.monotonic()
result = 3
try:
    while time.monotonic() - started < MAX_SECONDS:
        runtime.tick()
        for case in runtime.cases.values():
            snapshots = runtime.journal.read(case.identity)
            position_observations = {
                snapshot.last_observation_id
                for snapshot in snapshots
                if snapshot.position_id is not None
                and snapshot.last_observation_id is not None
                and snapshot.outcome is None
            }
            complete = (
                case.outcome is not None
                and case.position_id is not None
                and case.entry_observed_at is not None
                and case.exit_intent is not None
                and case.outcome.terminal_at > case.entry_observed_at
                and len(position_observations) >= 3
            )
            if complete:
                print(json.dumps({
                    "acceptance": "B3_NATURAL_FORWARD_CHAIN_ACCEPTED",
                    "policy_id": policy.identity,
                    "case_id": case.identity,
                    "decision_record_id": case.decision_record_id,
                    "entry_status": case.entry_status.value if case.entry_status else None,
                    "position_id": case.position_id,
                    "position_observation_count": len(position_observations),
                    "path_observation_count": case.explanation_path.observation_count,
                    "exit_reason": case.exit_intent.reason,
                    "terminal_method": case.outcome.terminal_method.value,
                    "terminal_at": case.outcome.terminal_at.isoformat(),
                    "outcome_id": case.outcome.identity,
                }, sort_keys=True), flush=True)
                result = 0
                break
        if result == 0:
            break
        time.sleep(1.0)
    if result != 0:
        print(json.dumps({
            "acceptance": "B3_NATURAL_FORWARD_CHAIN_NOT_OBSERVED_WITHIN_BOUND",
            "policy_id": policy.identity,
            "root": str(ROOT),
        }, sort_keys=True), flush=True)
finally:
    runtime.close()
raise SystemExit(result)
PY
```

**Exhausted diagnostics:** the prior schema diagnostic was bounded to `30` seconds and stdout only,
using the existing
public WebSocket dependency to inspect the `timestamp`, `state`, Greeks/IV, and book-action shape of
the already selected `BTC-15AUG26-62500-P` and `BTC-15AUG26-63000-C` aggregated `100ms` channels.
It called only `public/subscribe`, did not authenticate, and did not write any root or raw tape.
The prior composition diagnostic was bounded to `60` seconds and stdout only, using the
production source preflight/bootstrap/subscription and the same current bounded shortlist. It
printed only per-instrument option side and quote-validation success/failure summaries, closed the
feed, and did not create a Ledger, Journal, root, or raw tape.
The prior final fresh-cache diagnostic used the same `60`-second, stdout-only, public-call and
no-root bounds. It inspected only the first coherent cut and printed per-side counts plus exact
quote-validation error classes/reasons needed to distinguish a transient state, crossed book, or
missing field. No further diagnostic launch is authorized.

**Owning authority/contract:** `docs/authority/CURRENT_STAGE.md`,
`docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`, and
`docs/contracts/CASE_POSITION_OUTCOME.md`

No placeholder may remain when this task becomes `ACTIVE`. Stage must link this file as the only
active non-template task.

## Closure

**Given:** the corrected current Policy and WebSocket-forward Runtime pass `225` tests and `8`
deterministic business scenarios; the isolated v2 root began absent, now preserves only its exact
launch-2 natural evidence, and the lost v1 root is excluded for the reason recorded below

**When:** the exact persistent launchd command resumes that isolated root and naturally observes
public BTC data without modifying Policy values or manufacturing a Candidate

**Then:** one causally complete chain is recovered from durable evidence:
Candidate → strictly later Entry reunderwriting → Shadow Position → at least two later monitoring
cuts → trigger → strictly later whole-product exit or official settlement → explanatory Outcome

**Affected identity and population:** every current-Policy DecisionWindow encountered after the
new root's natural enrollment, its immutable WebSocket `MarketObservationV3`, and any naturally
created DecisionRecord, TradeCase, Shadow Position, Gap, and Outcome; no prior population is copied

**Baseline and denominator:** `0` enrolled Windows and `0` Cases in the absent v2 root before launch;
only naturally encountered current-Policy Windows durably persisted in v2 may enter the denominator

**Primary blocker and expected delta:** `NATURAL_FORWARD_CHAIN_UNVERIFIED` becomes absent only if
the exact accepted chain exists; otherwise the earliest measured natural blocker and denominator
remain the result and this task does not claim completion

**Known-at and DataHealth boundary:** the validated Deribit clock, WebSocket source/receive
watermarks, per-instrument continuity, current connection epoch, exact Window input deadline, and
existing DataHealth Policy own every accepted cut. Missing, stale, discontinuous, incoherent, late,
or unavailable data remains `UNKNOWN` or an exact Gap and cannot be relabelled to complete the chain

## Effects and scope

**Risk allocation effect:** only a naturally admitted current-Policy `ShadowRiskAllocation` may
reserve its exact stress reserve; it is released only by the existing terminal rule

**ObservationLedger / CaseJournal effect and consumer:** authorize only the Ledger, Journal,
runtime audit, settlement, future-path, and Workbench files owned by the exact v2 isolated root; the
acceptance command reads the append-only Journal to count distinct post-Entry Position observations

**Legacy-data effect:** NONE; the frozen prior root is neither read as current evidence nor written,
copied, migrated, or deleted

**Permission effect:** authorize unauthenticated production public market calls and one persistent
local launchd public Shadow process only for the exact command, current Policy identity
`sha256:b282de121a676da13c16d73d41ac19c4b5a17366bd89b7036ef07d0bd05e9888`, exact isolated root, label,
port, source checkout, and loopback surface above. No other permission changes

**Files and behavior in scope:** the ignored isolated runtime root, exact public observations and
derived B3 records, this task and matching Stage snapshot, runtime authorization constants, direct
tests and README, `/Users/logan/Library/LaunchAgents/com.optimatrix.b3-public-shadow.plist`, merge and
push to `main`, local remediation-branch deletion, and registered-worktree removal. Policy,
thresholds, ranking, lifecycle, route, risk, and Outcome behavior remain read-only

**Out of scope:** deleting or resetting the root, deterministic fixtures as acceptance, threshold
changes, forced EventState, backfill, old-root evidence, private/authenticated facts, `raw` channel,
accounts, orders, fills, capital, remote deployment, Edge or profitability claims, and B4

**Complexity added / deleted:** add no abstraction or option; delete only the disproven strict
ticker-timestamp assumption, source-state coercion that caused the first-cut side loss, and the
conflation of retained book content-change time with its verified continuity watermark; require the
existing cut wait to reach its owning Window's source boundary before consuming the one attempt

## Verification and closure

**Cheapest falsification:** public clock preflight plus first naturally enrolled Window must produce
either one strict current-Policy DecisionRecord or an exact `UNKNOWN`/Gap without HTTP market polling

**Repository gate:** `make check` passes `225` tests and all `8` deterministic business scenarios;
rerun it after the live process stops and before closure

**External evidence:** REQUIRED — deployment first requires the launchd PID to execute from current
`main`, exclusively lock v2, expose HTTP `200` on `127.0.0.1:8765`, and append one healthy public
market cut without a startup error. Task closure still requires recovery of the complete natural
chain from the durable root; absence remains unverified and cannot close

## Observed falsification

- Launch `1/3` used the exact command and new root; preflight, metadata/history bootstrap, heartbeat,
  and the unauthenticated public subscription all succeeded.
- The Window attempted at `2026-08-14T11:40:58.922610Z` first raised
  `ATM implied variance requires both Call and Put quotes` twice, then recorded
  `WEBSOCKET_CUT_SOURCE_STALE`; no Decision or Case was invented.
- The Window attempted at `2026-08-14T11:45:00.951984Z` recorded the exact disconnect Gap
  `WEBSOCKET_TICKER_TIMESTAMP_NOT_ADVANCING:BTC-15AUG26-63000-C`. Repeated public heartbeat and
  subscription audit records show that the strict timestamp check caused connection churn.
- The process was operator-interrupted after the second falsification and closed its feed/root lock.
  The root must be resumed in place. These are current public observations, not acceptance evidence.
- The authorized 30-second schema diagnostic then observed `20–22` valid book messages and `28–37`
  valid ticker messages for one near-index Put and Call. Both tickers were `open` with complete
  Greeks, IV, OI, and underlying fields; book snapshots/changes used only the documented actions.
  That sample contained no repeated timestamps, proving only that timestamp equality is intermittent,
  not that ticker timestamps are sequence identities. Book change IDs remain the sole continuity
  proof. No raw message was retained.
- The first composition diagnostic reproduced
  `DeribitSourceError:ATM implied variance requires both Call and Put quotes` from the production
  source, then immediately parsed the next immutable cut from the same `21`-instrument universe as
  `8` valid Puts and `13` valid Calls with zero quote failures. Metadata and steady-state quote
  translation are therefore not the side-loss cause; the defect is bounded to initial cut readiness.
- The final fresh-cache diagnostic proved the first immutable cut itself contained `8` valid Puts
  and `13` valid Calls with no quote failure and a stable shortlist, while evaluating that same cut
  still raised the dual-side error. Inspection then identified a double-normalization defect:
  validated Session metadata dropped the original product-validation fields, so the evaluator's
  second validation filtered every instrument. The correction must retain the already validated
  exact fields and make normalization idempotent; it must not bypass validation or synthesize values.
- The required post-fix `make check` passed `223` tests and all `8` business scenarios, but its
  documented `clean-build` prerequisite recursively deleted the ignored
  `/Users/logan/Optimatrix/build/b3-natural-forward-chain-v1` root. This was an operator error: v1's
  two attempted Windows and audit files are not recoverable, must not be reconstructed, and are
  excluded from acceptance. The replacement v2 root is outside repository build cleanup, begins at
  denominator zero, and is now the only authorized evidence root.
- Launch `2/3` enrolled that exact v2 root and maintained one stable public WebSocket connection.
  Its first complete cut retained all `21/21` usable books and evaluated `48` legal priceable
  structures for Window
  `sha256:76a4fd7a05ca0a3e16fe2284f21ced8bc5cbd026f19342ca4c4219d7c12fad32` at
  `2026-08-14T11:56:05.822000Z`. The immutable observation is
  `sha256:341515730c286581807f7a59a9b2339a5859997a5c66392389df6bc9f70799d3`.
- At the next Window boundary the feed recorded
  `ForwardObservationGap:WEBSOCKET_CUT_SOURCE_STALE` at `2026-08-14T12:00:00.425962Z` even though
  public heartbeat/test traffic and the subscription remained connected. At the prior Window's
  input deadline the complete observation correctly became one natural `ABSTAIN` Decision at
  `2026-08-14T12:01:00Z`; no Case was created.
- The Gap proved that the cache treated an unchanged illiquid book's last content-change timestamp
  as its continuity watermark. That assumption is false for an incremental state stream: after an
  accepted snapshot, the retained depth remains current through silence while its connection epoch
  and `change_id` chain remain intact. Freshness must use the latest effective book/ticker member
  boundary, not require every book to change within eight seconds.
- Launch `2/3` was operator-interrupted after this falsification; it closed normally, released the
  root lock, and left the v2 append-only evidence intact. Only launch `3/3` remains authorized.
- The effective-member correction passes its focused WebSocket tests and the complete repository
  gate: `224` tests and all `8` deterministic business scenarios. The v2 root still contains its one
  Decision and `57` runtime audit events, is unlocked, and was not touched by clean-build.
- Launch `3/3` resumed v2 without migration, recorded the interrupted `12:00–12:15` Window as
  `UNKNOWN/NO_OBSERVATION`, then obtained a complete in-Window cut and recorded a natural `ABSTAIN`
  for `12:15–12:30`. The prior live ticker and effective-watermark failures did not recur.
- Its steady-state `12:30–12:45` attempt completed a cut at `2026-08-14T12:30:01.486000Z`, but that
  retained cut's source watermark still preceded the Window start. At finalization the Window
  correctly failed closed as `UNKNOWN/OBSERVATION_OUTSIDE_WINDOW`; no Case was created.
- This directly falsifies the one-shot scheduling assumption: after marking a Window attempted, the
  Runtime must use the existing bounded wait to require a source watermark at or after the Window
  start. It may not consume a pre-Window cache state and then leave the full input grace unused.
  Launch `3/3` remains running on commit `9a065cd`; it is not restarted and no fourth launch is
  authorized.
- The Window-source lower bound passes its focused cache/source tests and the complete repository
  gate: `225` tests and all `8` deterministic business scenarios. The already running launch cannot
  load this correction. Its next `12:45–13:00` cut happened naturally to fall inside the Window at
  `2026-08-14T12:45:00.389000Z`; this confirms the old behavior is a boundary race, not that the
  `12:30` falsification was harmless.
- At `2026-08-14T13:01:01.087798Z`, launch `3/3` had durably recorded `5` natural Windows:
  `3 ABSTAIN`, `2 UNKNOWN`, and `0 Cases`. The valid `12:45–13:00` Window was `ABSTAIN`; the next
  running-process cut again exposed the old race with `observed_at=2026-08-14T12:59:59.315000Z`
  for a `13:00` Window. The process remains live on its original loaded commit and this is not
  evidence that the committed lower-bound correction ran in production.

Close only after directly observing the declared delta. Replace Stage with the post-task snapshot
and remove this file; do not append completion history.
