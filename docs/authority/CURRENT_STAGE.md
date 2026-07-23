# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Implemented capability:** `OUTCOME_TRUTH`

**Sole authorized next product-capability closure:** `FIXED_POLICY_PUBLIC_SHADOW`

## Authority

This document grants current permission under
[`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md). It does not define product purpose,
architecture, or delivery evidence, and it cannot widen the Product Constitution. Code presence,
green tests, historical receipts, or roadmap order do not grant a stage.

## Implemented baseline

The repository currently implements:

- bounded Deribit production-public BTC-USDC 0–72h catalog, ticker, and trade capture;
- platform, heartbeat, subscription, gap, and reconnect canonical facts;
- canonical JSONL capture with causal sequence and persisted elapsed time;
- current-frame projection and deterministic inspect/replay;
- visible 1:1 same-expiry same-side vertical enumeration;
- fixed transparent `OBSERVED_PATH_STRESS_FIXED_PRIOR` assessment;
- `RESEARCH_CANDIDATE | WATCH | ABSTAIN` decisions;
- strict Decision input truth for the index-price reference path, every required path/flow window,
  missing depth, scheduled-block validity, and connection-scoped platform state;
- refreshed decision-as-of 0–72h catalog generations bound to exact same-generation metadata;
- durable `SHORT_VOL_DECISION_RECEIPT` evidence with readiness, complete opportunity accounting,
  Git provenance, authoritative runtime-source identity, and deterministic fresh-process replay;
- immutable `SHORT_VOL_SHADOW_ENTRY_RECEIPT`, `SHORT_VOL_OUTCOME_FACT_SEAL`, and
  `SHORT_VOL_OUTCOME_RECEIPT` evidence;
- strict post-entry causality, entry-zero excursion, actual-exposure versus counterfactual
  separation, executable visible-quote close economics, and complete market/control lineage;
- Outcome-specific runtime identity, byte-exact prefix/suffix sealing, fresh-process reconstruction,
  and hash-verifiable synthetic plus production-public evidence bundles.

This baseline proves the accepted bounded Decision Truth and Outcome Truth closures. It does not
prove continuous acquisition, a complete final frame in every market run, a nonzero
production-public Entry or matured Outcome, Policy quality or qualification, ML, promotion,
execution, or profitability. Accepted production evidence remains outside the repository; no
production capture is committed as current source.

## Acceptance blockers

These are product-truth gaps, not permission for broad refactoring:

1. Runtime has no predeclared bounded run interval, decision cadence, admission/concurrency rule,
   or deterministic accounting for every due opportunity.
2. The bounded collector retains the full event set in memory before final capture writing; it has
   no incremental, interruption-evident durability suitable for a multi-decision bounded run and
   its maximum Outcome horizon.
3. There is no immutable Run receipt binding the fixed Policy, schedule, opportunity denominator,
   Decision/Entry/Outcome maturity partitions, `NO_TRADE=0` comparison, sealed facts, and
   independent replay.

## Sole authorized product-capability closure: Fixed-Policy public Shadow

The next product-capability task may only close one bounded, multi-decision production-public
Shadow run on top of the accepted Decision Truth and Outcome Truth contracts:

- freeze the run boundary, declared decision cadence, admission/concurrency rule, deployed Decision
  input, Policy, Outcome contract, initial-origin acquisition deadline, invocation hard stop, and
  all runtime-source identities before observing run results;
- durably record every due decision opportunity, including incomplete `UNKNOWN`, complete
  `WATCH`/`ABSTAIN`, admitted Entry, immature Outcome, and mature `CLOSED`/`UNEXITABLE`/`UNKNOWN`;
- after each slot cutoff or no-event close, persist that opportunity before processing any later
  canonical event or closing a later slot; a post-run batch replay cannot impersonate a Policy
  decision that was durably made online; freeze a bounded monotonic commit-latency gate rather than
  claim an event arriving immediately before a cadence boundary was already durable before it;
  later facts and segment seals must cross-bind the latest due opportunity and platform-probe
  control state through one interleaved causal commit chain, while process-witness verification
  remains distinct from unavailable external fsync-time attestation;
- after every admitted Entry, and after reconnect while exposure remains open, actively request
  and durably bind the accepted strictly future platform subscription/status proof; a failed
  attempt remains `UNKNOWN` but cannot veto later valid latest-authoritative same-generation proof
  from a dedicated probe, reconnect bootstrap, or other eligible durable acquisition; superseded
  late control responses remain noncanonical control-anomaly evidence and cannot overwrite
  authoritative platform state; only authoritative acquisition facts enter later DecisionFrames
  in causal order without changing a frozen prior Decision, while an omitted due SLA attempt may
  make the Run incomplete but cannot rewrite a valid Outcome;
- keep the run open through the last possible admission's full maximum Policy horizon plus one
  declared observation tail so that a completed run cannot hide all late Entries as immature;
- preserve a complete opportunity denominator and contemporaneous `NO_TRADE=0` comparator without
  changing thresholds, retrying to manufacture activity, or calling the run qualification; only
  the no-position comparator has defined zero PnL, while `UNKNOWN`, `UNEXITABLE`, and immature
  strategy results retain null PnL;
- add only the incremental or segmented append-only durability required for this bounded run,
  making interruption and incomplete maturity explicit rather than silently dropping records; an
  interrupted prefix is independently verifiable but is not a completed Run receipt and the
  runtime cannot resume or automatically retry it; operators may not choose a replacement based
  on activity or results, but without an external attempt registry the evidence must report
  `attempt_selection_attested=false` rather than claim it proves that no attempt was discarded;
- emit one immutable Run receipt binding the run contract, schedule, sealed facts, every
  Decision/Entry/Outcome receipt, maturity partition, zero activity, anomalies, and aggregate
  descriptive results, including final nonclosed exposure rather than treating
  `UNKNOWN`/`UNEXITABLE` as an executable exit;
- independently replay the sealed run in a fresh process and reconstruct every due opportunity,
  receipt, maturity classification, aggregate, and digest.

This permission authorizes only one bounded fixed-Policy production-public Shadow run and the
minimum durability it consumes. It does not authorize an unbounded daemon or service, Policy
tuning, qualification, Challenger work, promotion, private/account access, execution, or capital.
Create a semantic active task before implementing it.

Bounded maintenance, security, dependency, or authority work may proceed on explicit request when
its declarations show that it does not implement or advance a queued product capability.

## Queued sequence — not authorized

After the Fixed-Policy public Shadow closure is accepted and this document is explicitly advanced,
the intended sequence is:

1. **Challenger research and qualification:** only after a usable fixed-Policy baseline and a
   separately approved qualification contract.
2. **Promotion:** only after a valid independently verified Qualification receipt and a separately
   approved promotion envelope. Execution and capital authority remain separate after promotion.

A queued closure is not an active task. Activate exactly one by updating this authority in an
explicitly approved change after the preceding closure is accepted.

## Forbidden under the current boundary

- learned models, research automation, automatic promotion, or evolution;
- unbounded or service-operated Shadow, undeclared cadence/admission, or qualification;
- databases, feature stores, model registries, workflow engines, or services;
- generic multi-market or multi-strategy architecture;
- private/test/account APIs, credentials, balances, margin, positions, orders, fills, settlement,
  execution gateways, or money;
- account/portfolio risk and production capital authority.

Zero candidates and zero entries remain valid evidence. Never change thresholds to manufacture
activity. Update this document in the same merge that changes permission, implemented capability,
blockers, or the sole authorized next closure.
