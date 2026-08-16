# Optimatrix BTC 0DTE

Optimatrix is the local package for the product defined in
[Product Authority](docs/authority/PRODUCT_CONSTITUTION.md).

This README is package guidance, not product Authority. Agents start at `AGENTS.md`; current
permission and maturity are in `docs/authority/CURRENT_STAGE.md`.

## Local setup and checks

```bash
make sync
make check
.venv/bin/python -m optimatrix --help
```

`make check` is offline evidence only. A network command requires exact authorization in the active
task and Stage; CLI help and source own its syntax.

## AI Lab

The integrated offline Lab is available as `optimatrix-ai-lab` and lives beside the main program in
`src/optimatrix/ai_lab/`. Its default append-only research root is
`/Users/logan/Library/Application Support/Optimatrix/ai-lab`. See
[`docs/AI_LAB.md`](docs/AI_LAB.md) for the Session-first review command, report locations, memory,
Codex CLI boundary, and Base-versus-Challenger gate.

## Deployed B3 public runtime

Current permission and the sole active task come only from `CURRENT_STAGE`. When that Stage
authorizes the existing deployment, launchd label
`com.optimatrix.b3-public-shadow` executes the merged `main` console script with exactly:

```bash
/Users/logan/Optimatrix/.venv/bin/optimatrix-shadow runtime \
  --event-state NONE \
  --root "/Users/logan/Library/Application Support/Optimatrix/b3-natural-forward-chain-v2" \
  --workbench-port 8765
```

The loopback Workbench is available at `http://127.0.0.1:8765/`. launchd keeps the process alive;
restarting the same job preserves the root manifest's first-enrollment provenance and accepted
Ledger or Journal prefixes. A new empty root starts with the currently active Session and current
Window; earlier Windows remain absent and are never backfilled. While the command remains running,
the same stable root and Workbench roll to each new Session at `08:00 UTC`; unresolved older Cases
continue to later valuation or official settlement, and both Ledger and Journal append across
Sessions. A complete 24-hour sample or `96/96` live population is not a startup gate. The active
validation task may read an immutable DecisionRecord snapshot without operating the runtime or
writing the root. A natural Candidate-to-Outcome chain remains stronger evidence to collect; its
absence does not invalidate accepted pipeline capability or qualify the Policy.

The runtime establishes Deribit UTC before it creates or mutates the stable root. Deribit time owns
Session, Window, lifecycle, expiry, and settlement boundaries; the host wall clock is not a business
input. The Workbench receives UTC facts and lets the browser render marked timestamps in the
trader's local timezone without changing backend identities or calculations.
