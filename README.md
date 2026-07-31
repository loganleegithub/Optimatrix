# Optimatrix

Optimatrix is intended to become an autonomous 0–3DTE options decision and trading system. Its
first product slice is Deribit BTC-USDC defined-risk Short Vol. The current permission is
production-public Shadow only: no private API, account, margin, order, fill, or money access.

## Current truth

The top implemented capability is `PRODUCTION_PUBLIC_SHORT_VOL_RADAR`: one guarded
production-public Radar runtime and its `observe` command. The fixed-contract public Shadow
implementation is separately `LIVE_INTEGRITY_DEFECT_REPAIR_REQUIRED`. Its single authorized
production-public attempt is consumed and failed; `observe-shadow` is not currently authorized.

The production Short Vol Radar is `ESTABLISHED` by independently accepted, exact-commit Smoke and
Soak evidence. The downstream
[`SHORT_VOL_UNDERWRITING_POSITION`](docs/contracts/SHORT_VOL_UNDERWRITING_POSITION.md) and
[`SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT`](docs/contracts/SHORT_VOL_SHADOW_OUTCOME_FORWARD_COHORT.md)
contracts are frozen. The fixed-contract implementation binds one exact three-Policy chain and
provides the pure
Underwriting, Candidate/admission, Shadow Entry, Position, close-opportunity, Outcome,
rejected-counterfactual, aligned-pair, conservation, and strict evidence path. Exact repair commit
`6207d59763e1aab7c455854169cd9dde6b0f940f` independently closed the writer/current/complete-reader
attempt-integrity gap. The sole active closure is now
`SHORT_VOL_SHADOW_ATTEMPT_EVIDENCE_INTEGRITY`: an offline repair of the real Radar episode-identity
boundary while preserving the existing failure terminal. Exact candidate
`4b225ee1f199523fb052611d84612ec75c7abf78` exited `1` after five anomaly artifacts and a fatal
Underwriting identity error. Its downstream failure summaries are complete and conserved with zero
persisted Candidate/Entry/Position/Outcome counts, but the Radar run summary is absent; the full
forward result is `INCOMPLETE`, `NOT_ACCEPTED`, and business-`NOT_EVALUABLE`. Radar writes its run
summary only on clean stop, so partial Radar evidence is truthful on this process failure rather
than a second implementation defect. No second
production-public invocation is authorized. No private/account/order/fill/capital capability,
replay, Policy change, qualification, or persistent service is authorized.
Establishment means the bounded public Radar met its frozen reachability and operating predicates;
it does not mean the Radar is persistently deployed, always running, indefinitely stable,
profitable, or authorized to trade. Offline Shadow implementation or evidence-integrity
acceptance does not prove a natural Candidate, Entry, Position, Outcome, forward cohort, Policy
quality, or business success.

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
honest conservation/null denominators. A public quote remains not a fill. The runtime was
unauthorized before the consumed evidence attempt; the current active repair task authorizes
offline implementation work only, and no live invocation or trading capability follows.

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
defines the accepted downstream Outcome and forward-cohort semantics.

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

The guarded `python -m radar_runtime observe` command is the public-only runtime entry point under
`PUBLIC_SHADOW`. Each bounded observation still uses one immutable Policy identity and a fresh
evidence directory and preserves clean-stop and strict-validation behavior. The accepted Smoke and
Soak establish only their exact pre-bound observation windows; they do not authorize persistent
service deployment, private/account access, orders, fills, capital, execution, or any queued
product closure. `python -m radar_runtime observe-shadow` remains implemented, but the active
`IMPLEMENTATION` task permits only offline tests for the proven identity mismatch and regression
checks for the existing legal downstream failure terminal.

The failed manifest, evidence directories, log, and terminal record are sealed and cannot be
edited, deleted, completed retroactively, migrated, relabelled, or reused. A future live attempt
requires a new `EVIDENCE_ONLY` task, new external paths, and separate explicit authorization.
