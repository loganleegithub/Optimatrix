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

## C1 private read-only account capture

This entrypoint is usable only when both `CURRENT_STAGE` and its sole active task authorize a
bounded private canary. It accepts no credential, token, URL, or host argument. Run it from an
interactive terminal; it prompts without echo for the Deribit client identifier and secret:

```bash
.venv/bin/optimatrix-account \
  --environment mainnet \
  --snapshot /absolute/path/to/public-snapshot.json \
  --output-dir /absolute/path/to/private-read-only-workbench
```

For an explicitly supplied local credential file, copy `.env.example`, populate only the
environment-specific pair, set mode `0600`, and add `--credentials-file /absolute/path/to/.env`.
The CLI never searches for `.env`, reads process environment variables, follows a symlink, or
accepts shell syntax. It rejects non-regular files, a different owner, any mode other than `0600`,
duplicate or unknown keys, and a missing selected-environment pair with credential-free error
codes. Root `.env` and `.env.*` are ignored; `.env.example` is the only tracked exception and
contains no values.

The requested token scope is always exactly `account:read trade:read`: account summary requires the
former and Positions require the latter. Mainnet also requires the returned effective functional
scope to be exactly those two reads; a missing or additional functional scope and every
`read_write` or `write` scope fail before both private methods. Testnet accepts any finite,
unambiguous, ASCII-safe functional scope token set when it still grants both required read
capabilities; unknown safe functional tokens do not expand the application method surface or block
the two reads. Known metadata, restriction, and `none` tokens are strictly validated then discarded
instead of entering the account projection. The client calls only
`public/auth`, `private/get_account_summary(currency=BTC, extended=false)`, and
`private/get_positions(currency=BTC)` against the fixed selected environment. The resulting static
Workbench labels `ENVIRONMENT`, effective `CREDENTIAL_SCOPE`,
`APPLICATION_METHOD_PERMISSION=READ_ONLY_FIXED_ALLOWLIST`, `ORDERS_EXECUTED=NONE`, one-shot
freshness, requested token scope, token-scope-normalization availability, and completeness
beside—but outside—the Public Shadow Ledger/Case/Risk/Lifecycle. It stores no client identifier,
secret, token, or auth-response scope text. `CREDENTIAL_SCOPE=USER_DECLARED_READ_ONLY` records the
machine credential contract, not a parsed effective-token claim;
`TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE` makes that limitation explicit. The C1 command accepts only
mainnet and contains no write method.
