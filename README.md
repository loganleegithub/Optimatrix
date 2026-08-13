# Optimatrix BTC 0DTE

Optimatrix currently implements one public, read-only Shadow product: a same-Deribit-Session,
two-sided, four-leg, defined-risk BTC premium sale. It contains no order, fill, account, capital, or
qualified-Edge claim.

This README is package guidance, not product Authority. Agents start at `AGENTS.md`; current
permission is in `docs/authority/CURRENT_STAGE.md`.

## Local setup and checks

```bash
make sync
make check
.venv/bin/python -m optimatrix --help
```

`make check` runs the offline quality and business-scenario suite. It does not establish live
reachability, Policy qualification, or profitability.

Network commands are not ordinary local validation. Run one only when the active task and
`CURRENT_STAGE` both authorize the exact command and bounds. CLI help and source own current command
syntax; documentation does not duplicate it.
