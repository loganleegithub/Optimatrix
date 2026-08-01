# Optimatrix

Optimatrix is intended to become an autonomous 0–3DTE options decision and trading system. Its
first product slice is Deribit BTC-USDC defined-risk Short Vol. The current permission is
production-public Shadow only: no private API, account, margin, order, fill, or money access.

## Current truth

The top implemented capability is `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`: one guarded
production-public Radar runtime and its `observe` command. The fixed-contract public Shadow
implementation is separately `ENGINEERING_AND_PUBLIC_INTEGRATION_ACCEPTED`. The two-layer
engineering closure is consumed and closed. The later persistent-service observation is also
consumed: it sealed complete `PROCESS_FAILURE` evidence and did not satisfy the 24-hour gate. One
service-operability and trader-workbench repair is accepted. One fresh production restart is now
authorized under a new root, new labels, exactly one public-only process, and one read-only probe;
24-hour acceptance remains pending.

The production Short Vol Radar is `ESTABLISHED` by independently accepted, exact-commit Smoke and
Soak evidence. The downstream
[`SHORT_VOL_UNDERWRITING_POSITION`](docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) and
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)
contracts are frozen. The fixed-contract implementation binds one exact three-Policy chain and
provides the pure
Underwriting, Candidate/admission, Shadow Entry, Position, close-opportunity, Outcome,
rejected-counterfactual, aligned-pair, conservation, and strict evidence path. Exact repair commit
`6207d59763e1aab7c455854169cd9dde6b0f940f` independently closed the writer/current/complete-reader
attempt-integrity gap. Exact implementation-acceptance tip
`6eaaddfecf4c59a19c8029682a80fc52b7896a64` repairs the real Radar episode-identity boundary and
preserves the existing failure terminal. The earlier exact candidate
`4b225ee1f199523fb052611d84612ec75c7abf78` exited `1` after five anomaly artifacts and a fatal
Underwriting identity error. Its downstream failure summaries are complete and conserved with zero
persisted Candidate/Entry/Position/Outcome counts, but the Radar run summary is absent; the full
forward result is `INCOMPLETE`, `NOT_ACCEPTED`, and business-`NOT_EVALUABLE`. Radar writes its run
summary only on clean stop, so partial Radar evidence is truthful on this process failure rather
than a second implementation defect. That attempt remains sealed and cannot be retried or reused.

The later activation commit `21af26c71ef625889d29c4d7e00ebeae92f8a15d`, tree
`11b8a42d920e6be9eff7a56f45fd3c02c8ef6bed`, passed the deterministic composed chain and one
result-independent production-public smoke. The process used a 14-minute enrollment cutoff and
29-minute final-stop trigger, exited `0` at `PLANNED_CLEAN_STOP`, and realized `1,739,999` ms from
runtime-start fact to terminal. Strict Radar/current/complete readers passed; both downstream
conservation summaries are `MET`. Real Deribit coverage was non-vacuous, and all 135 real anomaly
activation sequences reached the Underwriting-availability path without the historical identity
fatal. Actual RPCs were public-only, with zero RPC errors, reconnects, private/account/order/fill/
capital activity, post-terminal retries, or second evidence invocations.

The accepted result is exact:

```text
engineering_end_to_end = PASS
production_public_integration = PASS
natural_shadow_opportunity = NOT_OBSERVED
```

Candidate, Shadow Entry, admitted Outcome, and rejected Outcome counts were all zero. That natural
`NOT_OBSERVED` is not an engineering failure and does not establish opportunity frequency. The
terminal record is
`/Users/logan/Optimatrix-shadow/receipts/public-shadow-engineering-smoke-002-terminal-record.json`,
SHA-256 `a4b7a66c51133cef08a4d0420943b6fe5464a78cc10d5a8f2169c0c9d9d4db3c`.
That bounded smoke by itself authorized no private/account/order/fill/capital capability, replay,
Policy change, qualification, retry, persistent service, or further live invocation.
Establishment means the bounded public Radar met its frozen reachability and operating predicates;
it does not mean the Radar is persistently deployed, always running, indefinitely stable,
profitable, or authorized to trade. Offline Shadow implementation or evidence-integrity
acceptance does not prove a natural Candidate, Entry, Position, Outcome, forward cohort, Policy
quality, or business success.

### Consumed persistent observation and active fresh restart

The separately accepted persistent service/workbench implementation at commit
`67085248fffb1b20bae1c9512ae1191d166a6509` was later deployed under one exact observation
authority. On the user's `停止并修复`, the controller stopped the periodic probe, recorded one final
online probe, sent one label-bound `SIGINT`, and sent no retry or second signal. The service entered
`STOPPING / USER_REQUEST`, then truthfully sealed as `PROCESS_FAILURE` when an already-pending
heartbeat deadline failed 9 ms later.

The independent terminal audit records 190 contiguous probe rows, `11,909,685` ms of continuous
service, complete downstream/service evidence, `MET` Underwriting and cohort conservation, and
`INCOMPLETE_PROCESS_FAILURE` Radar evidence with no invented run summary. The 24-hour result is
`NOT_MET`. It observed 56 Radar anomaly objects and 6,442 Underwriting-availability objects, with
zero Candidate, atomic quote, Shadow Entry, close opportunity, or Outcome. Those natural zeros are
`NOT_OBSERVED`, not Policy-quality or performance evidence. The consumed state root cannot be
restarted, repaired, relabelled, or reused.

The bounded repair is independently accepted at exact commit
`d4740d6a181efebc8dad6d1091a78fa44d885957`, tree
`d5776f4f7c30763d095e36c7ea8b67209ec76448`, under service-contract digest
`sha256:4f94e8b8a8ddc1acbcd2c8eca47b4c0294f308500d21435c545346fba73971a7`.
It owns only the redundant whole-history work, revision-keyed projection cache, settled display
metadata, and truthful trader-facing version-2 presentation. It changes no Radar formula or state
machine, Policy, Underwriting/Position/Outcome economics, durable business identity, account
boundary, or execution permission.

The sole active task is the
[`SHORT_VOL_PERSISTENT_SERVICE_FRESH_PRODUCTION_RESTART`](tasks/SHORT_VOL_PERSISTENT_SERVICE_FRESH_PRODUCTION_RESTART.md).
It authorizes PR #9 activation and merge, then exactly one `serve-shadow` invocation under
`/Users/logan/Optimatrix-public-shadow-observation-002`, labels
`com.optimatrix.public-shadow.r2` and `com.optimatrix.public-shadow.r2.probe`, and loopback-only
`127.0.0.1:8765`. The service must pass exact commissioning before the fresh 60-second probe is
loaded. The consumed root remains sealed; a startup or process failure consumes the new attempt
without retry. Startup health does not establish 24-hour continuity, Policy quality, opportunity
frequency, fillability, or PnL. The task remains active throughout observation and closes only
after explicit stop or terminal failure is sealed, audited, and followed by a live-disabled stage
transition.

## Intended first business flow

```text
live Deribit BTC-USDC 0–3DTE option-chain changes
→ one exact content-identified Short Vol baseline
→ independent SHORT_VOL_ANOMALY_EVENT
→ while active, independent official atomic-combo availability
→ optional PUBLIC_ATOMIC_QUOTE_EVENT
→ fixed-contract Underwriting and deterministic Shadow admission
→ post-Entry Position, causal-first Outcome, and aligned forward-cohort evidence
```

Market ingestion, bounded in-memory chain maintenance, and Radar notification are one continuous
event-driven flow. The product does not first save the whole market and then repeatedly scan the
same facts. Ordinary no-anomaly updates and the theoretical structure universe are not persisted.

The three layers remain distinct:

- detector: `UNKNOWN | NO_ANOMALY | ANOMALY_ACTIVE`;
- existing official atomic combo:
  `NOT_EVALUATED | UNKNOWN | NO_ACTIVE_COMBO | NO_TARGET_SIZE_CREDIT_QUOTE |
  PUBLIC_ATOMIC_QUOTE_AVAILABLE`;
- maker/order/fill: not implemented or authorized.

An anomaly or public atomic quote is not Candidate, Shadow Entry, fill, Outcome, or proof of an
edge. Component-leg prices cannot substitute for an official combo.

Exact quantity, Delta/TTE bands, return lookbacks, trigger/clear ratios, and persistence live in a
content-identified Policy file rather than code. One run cannot change its Policy. A
human-approved or expressly terminal-goal-delegated successor inside the declared Policy schema
uses a new identity and forward observation interval; current Radar evidence alone cannot prove
better forecasting or profitability.

## Later position and Outcome behavior

Neither a Shadow `SHADOW_ENTRY` nor a future filled entry chooses a planned holding duration. The
implemented Underwriting/Position owner evaluates current remaining
premium, short-leg risk, path, volatility state, liquidity, executable close debit, fee reserves,
and hard boundaries before returning `HOLD | CLOSE | UNKNOWN` exactly as frozen by the contract.
It also implements Candidate invalidation and the strictly later full-quantity close opportunity.

The implemented Outcome/cohort reducer follows the frozen causal-first counterfactual exit and
terminal `MATURE_KNOWN | MATURE_UNKNOWN | CENSORED_AT_STOP | CENSORED_AT_FAILURE` semantics, one bounded
rejected counterfactual per slot, cohort-aligned `NO_TRADE`, exact public-quote PnL equations, and
honest conservation/null denominators. A public quote remains not a fill. The consumed attempt did
not establish production-public Shadow evidence. The later exact bounded smoke established only
the two engineering layers recorded above; no trading capability follows from it.

## Authority

Start with [`AGENTS.md`](AGENTS.md). The
[`PRODUCT_CONSTITUTION`](docs/authority/PRODUCT_CONSTITUTION.md) owns product meaning,
[`CURRENT_STAGE`](docs/authority/CURRENT_STAGE.md) grants permission,
[`SYSTEM_ARCHITECTURE`](docs/authority/SYSTEM_ARCHITECTURE.md) owns structure, and
[`DELIVERY_CONTRACT`](docs/authority/DELIVERY_CONTRACT.md) owns development and evidence.
[`SHORT_VOL_RADAR`](docs/contracts/SHORT_VOL_RADAR.md) defines the first Radar,
[`SHORT_VOL_UNDERWRITING_POSITION`](docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) defines the
accepted downstream Underwriting, admission, and Shadow Position semantics, and
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)
defines the accepted downstream Outcome and forward-cohort semantics. The
[`SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE`](docs/contracts/SHORT_VOL_PERSISTENT_PUBLIC_SHADOW_SERVICE.md)
contract owns the offline-repairable service evidence and immutable read-only workbench boundary.

## Repository shape

- `market_monitor`: public adapters, known-at order, continuity, and bounded current state
- `options_domain`: option facts, authorized leg relationships, and target-size public
  quote arithmetic
- `short_vol_radar`: detector episodes, official atomic availability, and minimal event
  projection
- `short_vol_underwriting`: pure fixed-contract Underwriting, admission, Position, Outcome,
  conservation, and downstream evidence owner
- `radar_runtime`: guarded composition of the continuous production-public process

There is no compatibility package or alias for the removed pipeline.

The current bounded runtime separates per-band immutable index-baseline availability from
generation-global successor publication. Normal time/watermark publication pending keeps an
already proven `N + 1` close tuple available and does not pause detector episodes, Layer 2, known
coverage, or persistence. Real window, source-stale, and continuity failures remain fail-closed.
Publication currentness invalidates exactly once independently from continuity-incident restart
de-duplication, so a stronger clock/session/index loss cannot leave a pending row or tuple alive.
Current run summaries use diagnostics schema version 6; sealed versions 5 through 2 remain
read-only and are never migrated.

## Local verification

```bash
make sync
make check
```

The `observe`, `observe-shadow`, and `serve-shadow` commands remain guarded implementation
surfaces. The active task authorizes only one exact fresh `serve-shadow` invocation after its
authority activation is merged and every deployment binding passes; `observe`, `observe-shadow`,
any second service invocation, and every private/account/order/fill/capital surface remain
forbidden. The accepted Smoke, Soak, two-layer smoke, and consumed persistent observation establish
only their exact pre-bound intervals and grant no authority to reuse them.

The failed fixed-contract attempt, accepted smoke, and failed persistent observation artifacts are
sealed and cannot be edited, deleted, completed retroactively, migrated, relabelled, retried, or
reused. The active fresh sample begins only at its own lifecycle sequence 1 and cannot carry any of
these intervals forward as evidence of Policy quality, opportunity frequency, or PnL.
