# Task — Outcome Truth

**Status:** ACTIVE

**Product/stage:**
[`PRODUCT_CONSTITUTION`](../docs/authority/PRODUCT_CONSTITUTION.md) /
[`CURRENT_STAGE`](../docs/authority/CURRENT_STAGE.md) `PUBLIC_SHADOW`

**Implementation contract:**
[`SHORT_VOL_RADAR`](../docs/contracts/SHORT_VOL_RADAR.md)

**Base commit:** `809c431e2bbe6873bc1ecec78ea24422710ca0bb`

**Target branch/PR:** `codex/outcome-truth` / Draft PR to `main`

## Business closure

**Given:** one sealed bounded canonical tape and the single Decision cutoff fixed before Outcome
evaluation at the first canonical event after the initial required subscriptions have accumulated
3,600 seconds of collector-elapsed time.

**When:** the runtime reconstructs the exact cutoff Decision receipt, applies one fail-closed
Shadow admission, and evaluates only strictly post-entry public facts under
`PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH`.

**Then:** it emits either an explicit zero/`UNKNOWN` admission with no false position, or exactly
one immutable `SHORT_VOL_SHADOW_ENTRY_RECEIPT` and one `SHORT_VOL_OUTCOME_RECEIPT` whose observed
exposure, executable close economics, PnL, counterfactual facts, identities, and lineage are
durable and independently reconstructable.

**Independent verification:** a fresh process recombines the sealed Decision prefix and strictly
future suffix, verifies the original full-capture digest, and reconstructs the Decision, admission,
Entry, Outcome, and every derivable digest without querying live state.

**Valid zero/UNKNOWN result:** an incomplete Decision is `UNKNOWN`; a complete `WATCH` or `ABSTAIN`
is `NO_ENTRY`; both produce zero Entry and Outcome receipts. An admitted entry with incomplete
future evidence produces an `UNKNOWN` Outcome with null observed executable PnL.

## Change declarations

**Market/Decision input contract change:** NONE — preserve
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`, the exact accepted Decision receipt schema and meaning,
and baseline Decision runtime source digest
`eed711f1c924c73a0a61b562da5154873b40713f5b5e44c482882eecf7aee29c`.

**Decision Policy change:** NONE — preserve
`OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY`, every horizon, structure, formula, threshold, ranking,
reserve, veto, and candidate predicate.

**Outcome/evaluation contract change:** APPROVED — add
`PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH`, `SHORT_VOL_SHADOW_ENTRY_RECEIPT`,
`SHORT_VOL_OUTCOME_RECEIPT`, and `SHORT_VOL_OUTCOME_FACT_SEAL`; require strict future causality,
entry-zero excursion, executable observed PnL, control-fact lineage, and actual/counterfactual
separation.

**Stage/authorization change:** NONE — remain inside bounded `PUBLIC_SHADOW`; do not update
`CURRENT_STAGE.md`, activate a fixed-Policy run, or grant private/account/execution authority.

## Evidence boundary

**Proves:** one bounded Decision-to-admission-to-Outcome contract, fail-closed missingness,
strictly future path isolation, visible executable-close economics, immutable receipts, and
fresh-process reconstruction from sealed facts.

**Does not prove:** a nonzero production-public entry, a real fill, strategy quality,
profitability, continuous Shadow operation, `NO_TRADE` qualification, Challenger superiority,
promotion, execution, account access, or capital authority.

**Evidence class:** `SYNTHETIC_LOGIC | BOUNDED_PUBLIC_CAPTURE | LIVE_REPLAY | SHADOW_OUTCOME`

## Scope

**In:** one fixed cutoff; exact Decision prefix; strictly future fact suffix; fail-closed admission;
Entry and Outcome receipts; actual/counterfactual split; platform-control and quote lineage;
executable close/PnL; Outcome-specific runtime identity, replay, bundle, hashes, and report.

**Out:** Decision input or Policy changes; repeated scanning; retrying after reconnect or no
candidate; cadence; Run receipt; opportunity denominator; `NO_TRADE`; generic segmented storage;
database; service; Challenger; qualification; promotion; private API; order; fill; execution;
capital; stage advancement.

**Owning module/artifact:** `shadow_engine` Outcome contract and pure evaluation;
`radar_runtime` bounded Outcome composition and evidence; immutable Entry/Outcome JSON receipts.

## Contract

**Inputs and known-at rule:** Decision uses only the standard prefix through cutoff. Entry is frozen
at that cutoff. Market and future control facts used by Outcome have `capture_seq` strictly greater
than entry; entry-generation control anchors remain separately identified by the Entry receipt.
Collector elapsed time governs warm-up, holding time, and horizon; wall and exchange clocks remain
raw audit evidence.

**Durable output and identity:** Entry binds the exact Decision receipt, frame, selected assessment,
Policy, structure, quantity, entry credit/depth/fees/max loss, entry sequence, control anchors, and
Outcome contract/runtime identities. Outcome binds the sealed full facts, Entry receipt, actual
path, optional labeled post-exit counterfactual, close assessment, observed result, full lineage,
and its content digest.

**Missing/invalid/UNKNOWN semantics:** stale/missing reference, quote side, amount, platform proof,
future lineage, malformed freshness identity, or conflicting same-source evidence is `UNKNOWN`.
Stale facts retain their point-level source lineage. Explicit platform lock/reference closure or
complete visible depth below frozen quantity is `UNEXITABLE`. Only an executable close may
populate observed close cost, fee, and PnL. No status substitutes maximum loss for observed PnL.

**Persisted contract identity/replay compatibility:** existing non-durable Shadow results remain
synthetic regression evidence only and are not comparable qualification Outcomes. Existing
Decision artifacts remain readable and unchanged. New Outcome evidence uses the semantic identities
declared above; the suffix seal is closure-specific and is not a generic capture/storage format.

## Acceptance

### Direct behavior

1. Exact Candidate admission freezes one Entry receipt; receipt/frame/assessment/Policy/sequence
   drift fails, while complete no-candidate and incomplete Decision results remain explicit zero.
2. Actual exposure selects the first executable point in causal order with same-point priority
   `PROFIT_TARGET`, `FIRST_TOUCH`, then `HORIZON`; only post-exit facts become a labeled unscored
   counterfactual. Horizon is an armed condition, not a terminal fact: temporary
   `UNKNOWN`/`UNEXITABLE` observations continue until a later executable close or data end.
3. Excursion includes entry as a zero baseline only after at least one valid future reference fact;
   no future reference remains `UNKNOWN`.
4. Entry-only platform `OPEN` cannot support a future close; future connection-scoped status can,
   and reconnect requires a new future subscription/status barrier. The Outcome-owned collector
   must create an acknowledged platform-only subscription/status pair strictly after the already
   fixed cutoff even when the production connection never drops.
5. Executable close alone yields observed PnL. Known inability is `UNEXITABLE`; missingness is
   `UNKNOWN`; both have null PnL and no executable exit sequence.
6. Fresh replay verifies prefix/suffix causality, combined full-capture digest, source identities,
   Decision/Entry/Outcome receipts, zero drift, and tamper rejection. Standalone
   production-public replay also verifies the collector process witness while explicitly leaving
   external-source attestation false. Bundle verification tolerates a different audit Git commit
   only when scoped source digests are unchanged and exactly reconstructs the canonical Chinese
   report, rejecting semantically altered text even after hashes are recomputed.

### Required commands

- `make UV='python3 -m uv' sync`
- focused tests: `.venv/bin/python -m pytest tests/test_shadow.py tests/test_outcome_shadow.py
  tests/test_outcome_runtime.py`
- `make check`
- synthetic: `.venv/bin/optimatrix-outcome synthetic --output <fresh-synthetic>`
- synthetic replay: `.venv/bin/optimatrix-outcome replay <fresh-synthetic> --output
  <fresh-synthetic-replay>`
- production capture: `.venv/bin/optimatrix-outcome capture --duration-seconds 3665 --output
  <fresh-public>`
- public replay: `.venv/bin/optimatrix-outcome replay <fresh-public> --output
  <fresh-public-replay>`
- bundle and verification: `.venv/bin/optimatrix-outcome bundle ... --output <stable-bundle>` then
  `.venv/bin/optimatrix-outcome verify-bundle <stable-bundle>`

### Real evidence

**Required:** YES

**Environment and minimum duration:** fresh Deribit `production_public`, 3,665 seconds; no
credentials or private API. A zero entry/Outcome or admitted `UNKNOWN` is valid. The bounded
collector invocation's persisted monotonic elapsed time proves this duration; first-to-last event
span is reported for audit but is not a duration gate because both first-event startup delay and a
silent tail can shorten it.

**Required report:** records and actual public trades; coverage/readiness; gap/reconnect/platform/
source anomalies; cutoff and prefix/suffix sequences; action/admission/Entry/Outcome counts and
reasons including zero; capture/Decision/Entry/Outcome/runtime/contract digests; fresh-process
drift; bundle hashes; synthetic versus public evidence class; and explicit limitations.

**Private API:** FORBIDDEN.

## Artifacts and delivery report

**Capture/receipt/replay paths and hashes:** retained outside the repository in one
`OPTIMATRIX_OUTCOME_TRUTH_EVIDENCE_BUNDLE` containing synthetic and production-public subtrees,
`BUNDLE_MANIFEST.json`, `SHA256SUMS`, and `ACCEPTANCE.zh-CN.md`. The production subtree also keeps
the collector invocation witness and its exact collector-file/capture/runtime bindings. Large
facts are never committed.

**Policy/contract identities:** `OBSERVED_PATH_STRESS_FIXED_PRIOR_POLICY`,
`DERIBIT_PUBLIC_SHORT_VOL_DECISION_INPUT`, and
`PUBLIC_SHADOW_SHORT_VOL_OUTCOME_TRUTH`; exact content digests are receipt fields.

**Commit/PR:** commit and push only `codex/outcome-truth`, then open a Draft PR to `main`; stop
before readiness, merge, task archival, ref deletion, or authority advancement.

**Unknowns and non-claims:** synthetic success is not production Outcome evidence; public zero is
not failure and not profitability; visible quotes are not fills; replay equality proves
reconstruction only.

## Definition of done

The contracts, receipts, sealed facts, dual evidence, independent replay, focused tests, full gate,
hash verification, and Draft PR exist; every zero/UNKNOWN and limitation is honest; Decision source
and Policy remain unchanged; repository and remote scope contain only this closure; and no later
stage is claimed or activated.
