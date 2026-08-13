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

## Active B3 public runtime

While `B3_PUBLIC_SHADOW_RUNTIME` remains the sole active task, its exact command is:

```bash
.venv/bin/optimatrix-shadow runtime \
  --event-state NONE \
  --root "/Users/logan/Library/Application Support/Optimatrix/b3-public-shadow-v1" \
  --workbench-port 8765
```

The loopback Workbench is then available at `http://127.0.0.1:8765/`. `Ctrl-C` stops the process
without deleting its accepted Ledger or Journal prefixes; invoking the same command resumes the
Session bound by the root manifest. The active task remains open until one full production Session,
an observed restart, and explicit trader acceptance are all directly verified.
