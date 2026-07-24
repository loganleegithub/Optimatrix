# Optimatrix

Optimatrix is being built as an evidence-driven autonomous 0–3DTE options decision and trading
system. Its first product slice under construction is Deribit BTC-USDC defined-risk Short Vol. The
current permission boundary is production-public Shadow only: no private API, account, margin,
order, fill, or money access exists.

The current system asks one finite-horizon underwriting question:

> For a BTC 0–3DTE defined-risk option structure and a finite holding horizon, is the visible
> executable premium sufficient for observed path, touch, tail, liquidity, cost, and uncertainty?

It returns `RESEARCH_CANDIDATE`, `WATCH`, or `ABSTAIN`. A research candidate is not a qualified
strategy and grants no trading authority.

## Authority and current status

Start with [`AGENTS.md`](AGENTS.md). The
[`PRODUCT_CONSTITUTION`](docs/authority/PRODUCT_CONSTITUTION.md) governs three orthogonal
authorities: [`CURRENT_STAGE`](docs/authority/CURRENT_STAGE.md) grants permission,
[`SYSTEM_ARCHITECTURE`](docs/authority/SYSTEM_ARCHITECTURE.md) owns structure, and
[`DELIVERY_CONTRACT`](docs/authority/DELIVERY_CONTRACT.md) owns development and evidence. The
active task and implementation contract must satisfy all four.

Repository-owned contracts, tasks, and receipts use semantic identities and content digests—not
ordinal product generations. External protocols, dependencies, and build tools retain the exact
versions required for compatibility; those versions grant no product authority.

The bounded Deribit capture/replay foundation plus the accepted Decision Truth and Outcome Truth
semantics are implemented. Production Radar reachability is not established: current evidence has
not shown repeated real scans with nonzero completed- and Policy-evaluable-assessment denominators.
The sole authorized next closure is `RADAR_ESTABLISHMENT`, which establishes one continuously
captured public fact stream, rolling state, repeated scans, and localized per-structure
availability. Qualification, Challenger research, promotion, private/account access, and execution
remain unauthorized.

## Repository shape

- `market_tape`: canonical public facts, causal order, gap/reconnect, capture, and replay
- `options_domain`: observed option facts and visible defined-risk structure economics
- `short_vol_radar`: current frames, finite-horizon risk, insurance assessment, and decision
- `shadow_engine`: entry-frozen future-only Shadow position and Outcome primitives
- `radar_runtime`: Deribit public adapter and deterministic CLI composition

The repository remains a modular monolith. Later-stage services and platforms are intentionally
absent.

## Local verification

```bash
make sync
make check
.venv/bin/python -m radar_runtime demo --output /tmp/optimatrix-demo
.venv/bin/python -m radar_runtime inspect /tmp/optimatrix-demo/capture
.venv/bin/python -m radar_runtime replay /tmp/optimatrix-demo/capture --output /tmp/replay
```

If the installed `uv` is available only as a Python module, use:

```bash
make UV='python3 -m uv' sync
```

## Legacy bounded capture and Decision Truth tools

The commands below remain useful for the accepted bounded artifact contracts. They do not define
the Online Runtime lifecycle or the acceptance criteria for `RADAR_ESTABLISHMENT`.
**Do not run them for the current authority realignment or Radar establishment unless a later task
marks that exact historical evidence class `REQUIRED`.** They document how accepted compatibility
artifacts were created.

The Deribit collector requires no credentials:

```bash
.venv/bin/python -m radar_runtime capture \
  --duration-seconds 15 \
  --output /tmp/optimatrix-bounded
.venv/bin/python -m radar_runtime inspect \
  /tmp/optimatrix-bounded/capture \
  --output /tmp/optimatrix-inspect.json
.venv/bin/python -m radar_runtime replay \
  /tmp/optimatrix-bounded/capture \
  --live /tmp/optimatrix-bounded/live.json \
  --decision /tmp/optimatrix-bounded/decision.json \
  --output /tmp/optimatrix-bounded-replay
```

Historical Decision Truth compatibility packaged a greater-than-one-hour bounded artifact with
independently generated inspect/replay results outside the repository:

```bash
.venv/bin/python -m radar_runtime bundle \
  --capture-output /tmp/optimatrix-bounded \
  --inspect /tmp/optimatrix-inspect.json \
  --replay /tmp/optimatrix-bounded-replay/replay.json \
  --output /tmp/optimatrix-decision-truth-bundle
.venv/bin/python -m radar_runtime verify-bundle \
  /tmp/optimatrix-decision-truth-bundle \
  --archive /tmp/optimatrix-decision-truth-bundle.tar.gz
```

The bundle contains the sealed capture, manifest, Decision/live/inspect/replay artifacts,
`SHA256SUMS`, a bundle manifest, and an automatically generated Chinese report that remains
explicitly pending human business acceptance.

This creates one bounded capture receipt and one Decision receipt, not continuous acquisition.
The 3,600-second duration belongs to that historical harness; in the product, 60 minutes is a
rolling feature lookback that is warmed once or restored from covered persisted facts.

A numeric zero-Candidate count requires a nonzero Policy-evaluable-assessment denominator and
describes only that evaluated window or subset. Matching live/replay digests prove deterministic
reconstruction of the sealed tape, not Radar reachability, Policy value, data completeness,
strategy quality, fills, or trading authority.

## Historical bounded Outcome Truth evidence

`optimatrix-outcome` is the bounded evidence CLI for the accepted Outcome Truth closure. Every
output or archive path must be fresh and previously nonexistent. It fixes one Decision cutoff at
the first canonical event after the initial required subscriptions have accumulated 3,600 seconds
of collector-elapsed time; an incomplete Decision, `WATCH`, `ABSTAIN`, or reconnect does not move
the cutoff or trigger a retry.

This cutoff and the commands below preserve historical artifact compatibility. They do not stop a
continuous scanner, require each reconnect to wait another hour when covered history is available,
or make a long evidence run the product processing unit.
**Do not run these commands for `RADAR_ESTABLISHMENT`; they are not current-stage acceptance
steps.**

First generate and independently replay the deterministic nonzero synthetic evidence:

```bash
.venv/bin/optimatrix-outcome synthetic \
  --output /tmp/optimatrix-outcome-synthetic
.venv/bin/optimatrix-outcome replay \
  /tmp/optimatrix-outcome-synthetic \
  --output /tmp/optimatrix-outcome-synthetic-replay
```

The historical acceptance then collected and independently replayed one fresh production-public
run. It required no credentials or private API:

```bash
.venv/bin/optimatrix-outcome capture \
  --duration-seconds 3665 \
  --output /tmp/optimatrix-outcome-public
.venv/bin/optimatrix-outcome replay \
  /tmp/optimatrix-outcome-public \
  --output /tmp/optimatrix-outcome-public-replay
```

Keep the synthetic and production-public evidence classes distinct while packaging both into one
hash-verifiable bundle:

```bash
.venv/bin/optimatrix-outcome bundle \
  --synthetic-run /tmp/optimatrix-outcome-synthetic \
  --synthetic-replay /tmp/optimatrix-outcome-synthetic-replay \
  --public-run /tmp/optimatrix-outcome-public \
  --public-replay /tmp/optimatrix-outcome-public-replay \
  --output /tmp/optimatrix-outcome-truth-bundle
.venv/bin/optimatrix-outcome verify-bundle \
  /tmp/optimatrix-outcome-truth-bundle \
  --archive /tmp/optimatrix-outcome-truth-bundle.tar.gz
```

A complete `WATCH` or `ABSTAIN` produces `NO_ENTRY`; an incomplete cutoff Decision produces an
admission `UNKNOWN`. Both valid zero results create no Entry or Outcome receipt. An admitted entry
with incomplete future evidence creates an `UNKNOWN` Outcome with null observed executable PnL.
Only `CLOSED` records an executable close and observed PnL; `UNEXITABLE` and `UNKNOWN` keep them
null. A complete but immature bounded suffix is still `UNKNOWN`, never an invented zero or close.
The durable enum is `shadow_engine.truth.OutcomeStatus`; the package-root legacy enum and its
`OPEN` value remain unchanged for legacy regression compatibility. Production runs also persist a
collector invocation witness binding the 3,665-second command to its Deribit public endpoint,
collector files, capture, Git identity, and Decision runtime identity.
Synthetic success is not production Outcome evidence, public quotes are not fills, and matching
replay digests do not prove strategy quality, profitability, qualification, continuous Shadow
operation, or trading authority.
