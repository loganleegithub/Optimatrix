# Task — Decision Truth

**Status:** ACTIVE

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md) `PUBLIC_SHADOW`

**Implementation contract:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `abaf84409768e93ed302c47c5e270ec582993f5a`

**Target branch/PR:** `codex/decision-truth` / Draft PR to `main`

## Business closure

**Given:** one sealed bounded Deribit production-public tape whose latest catalog snapshot and
strict as-of market facts are evaluated under the immutable deployed input contract and Policy.

**When:** the runtime projects the final `DecisionFrame`, scans the complete authorized 0–72h
vertical universe, evaluates every configured horizon, and makes one decision.

**Then:** one durable `SHORT_VOL_DECISION_RECEIPT` freezes the exact action, code revision,
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT` identity/digest,
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY` identity/digest, frame and lineage identities, complete
scanned-universe and assessment-set identities/counts, failure summaries, and the full selected
assessment when one exists.

**Independent verification:** a fresh process reads the sealed capture, reconstructs the final
frame, universe, assessment set, decision, and receipt, and verifies every derivable identity and
digest against the live receipt.

**Valid zero/UNKNOWN result:** zero executable structures, zero assessments, zero research
candidates, or an `ABSTAIN`/`WATCH` caused by incomplete windows, missing depth, stale catalog, or
unobserved scheduled-block evidence is valid and remains explicit; it is never coerced to zero,
clear, or executable.

## Change declarations

**Market/Decision input contract change:** APPROVED —
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`; freeze
`BTC_USDC-PERPETUAL.ticker.index_price` as the only reference path, require every configured price
and flow window, preserve missing four-sided option depth and scheduled-block evidence as
`UNKNOWN`, refresh the bounded public catalog every 300 seconds and require its complete snapshot
to be no older than 360 seconds at the decision, and persist complete Decision lineage/identity.

**Decision Policy change:** NONE — preserve every value and formula under
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY`; relocating readiness fields out of `RadarPolicy` does not
change horizon, structure scope, ranking, reserve, veto, threshold, or candidate eligibility.

**Outcome/evaluation contract change:** NONE

**Stage/authorization change:** NONE

## Evidence boundary

**Proves:** strict as-of Decision input truth, deterministic complete-universe evaluation, durable
Decision evidence, and fresh-process reconstruction from the same sealed public tape.

**Does not prove:** continuous acquisition, a Shadow entry or Outcome, Policy quality,
qualification, profitability, `NO_TRADE` comparison, a real fill, private/account access,
promotion, execution, or any advancement of `CURRENT_STAGE`.

**Evidence class:** `SYNTHETIC_LOGIC | BOUNDED_PUBLIC_CAPTURE | LIVE_REPLAY`

## Scope

**In:** input/readiness and Policy identity separation; reference-path source and continuity;
all-window enforcement; explicit depth and scheduled-block missingness; bounded decision-as-of
catalog snapshot refresh/validity; deterministic universe/assessment summaries; one durable
Decision receipt; actual parsed trade count; inspect and independent replay equality/drift report.

**Out:** RadarPolicy numeric changes; risk/insurance formulas; thresholds; horizons; option
structure range; new data sources; Outcome runtime; long-running Shadow; Challenger; Promotion;
database; service; private API; account; order; fill; execution; capital; `CURRENT_STAGE` change.

**Owning module/artifact:** `market_tape` canonical catalog facts, `short_vol_radar` projection and
decision evidence, and `radar_runtime` bounded public composition plus
`SHORT_VOL_DECISION_RECEIPT` JSON.

## Contract

**Inputs and known-at rule:** every source sequence is positive and no greater than the final
decision `capture_seq`; path samples come only from accepted `index_price` ticker facts; trade
prices affect flow only; the latest complete catalog snapshot determines the active decision-as-of
0–72h universe and must satisfy the persisted elapsed-age limit.

**Durable output and identity:** the receipt binds capture content, final event/frame, source
lineage, code revision, input contract, Policy, scanned universe, deterministic assessment set,
selected full assessment, decision, and receipt digest.

**Missing/invalid/UNKNOWN semantics:** missing path/flow coverage, depth amount, catalog snapshot,
catalog freshness, scheduled-block observation, platform proof, quote freshness, or lineage fails
closed and is named. Empty observed trade flow remains zero only after complete flow coverage.

**Persisted contract identity/replay compatibility:** new evidence uses semantic identity
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`; existing sealed captures without a catalog snapshot
remain readable replay-regression inputs but are not Decision Truth evidence. Absent
scheduled-block observation remains valid Decision Truth only as explicit `UNKNOWN`.

## Acceptance

### Direct behavior

1. Mixed last/mark/trade prices cannot enter the reference path; every active path and flow window
   must be complete before risk is complete.
2. Missing depth, scheduled-block observation, or a complete fresh catalog snapshot fails closed as
   named `UNKNOWN`; observed empty flow remains zero and is distinguishable from missing flow.
3. A decision-as-of catalog refresh captures additions/removals and proves the 0–72h universe;
   the receipt freezes all required identities/counts and rejects future lineage or digest drift.
4. A fresh-process replay reconstructs the exact frame, universe, assessment set, selected
   assessment, decision, and receipt from the sealed capture and reports zero or nonzero drift.

### Required commands

- `make UV='python3 -m uv' sync`
- focused tests: `.venv/bin/python -m pytest tests/test_window_semantics.py tests/test_radar.py
  tests/test_deribit_public.py`
- `make check`
- production capture: `.venv/bin/python -m radar_runtime capture --duration-seconds 3665 --output
  <fresh-output>`
- artifact inspect: `.venv/bin/python -m radar_runtime inspect <fresh-output>/capture`
- fresh-process replay: `.venv/bin/python -m radar_runtime replay <fresh-output>/capture --live
  <fresh-output>/live.json --decision <fresh-output>/decision.json --output <fresh-replay-output>`

### Real evidence

**Required:** YES

**Environment and minimum duration:** fresh Deribit `production_public`, strictly greater than
3,600 seconds; no credentials or private API.

**Required report:** total records and actual parsed trades; every required window's
coverage/readiness; trade/book gap and reconnect counts; platform and source-time anomalies;
`UNKNOWN` reasons; action and candidate/entry/Outcome counts including zero; final event/frame
sequences; capture/frame/input-contract/Policy/universe/assessment/decision/receipt digests;
identity equality; fresh-process decision drift; and all evidence limitations.

**Private API:** FORBIDDEN.

## Artifacts and delivery report

**Capture/receipt/replay paths and hashes:** retained outside the repository under the fresh
evidence output paths and recorded in the Draft PR plus final delivery report.

**Policy/contract identities:** `OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY` and
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`; exact content digests are receipt fields.

**Commit/PR:** recorded by Git and the final delivery report; the task stops at Draft PR pending
human business acceptance.

**Unknowns and non-claims:** zero activity is valid; public quotes are not fills; live/replay
equality proves reconstruction only; scheduled-block evidence remains `UNKNOWN` unless explicitly
observed from an authorized input; this task does not claim Outcome, qualification, profit, or
execution capability.

## Definition of done

The durable closure exists; direct tests, repository gates, fresh greater-than-one-hour public
evidence, artifact inspection, and independent replay pass; all four declarations are satisfied;
limits and zero activity are explicit; `CURRENT_STAGE` is unchanged; committed and remote scope
contain only this closure; and a Draft PR awaits human business acceptance without merge.
