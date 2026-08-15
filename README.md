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
bounded private canary. It accepts no credential value, token, URL, host, account value, Public
Shadow snapshot, or Workbench argument. The standard machine-local call is:

```bash
.venv/bin/optimatrix-account \
  --environment mainnet \
  --credentials-file /Users/logan/.config/optimatrix/credentials.env
```

The machine-level credential and caller contract is
`/Users/logan/.config/optimatrix/README.md`. The repository contains no credential template and the
CLI never searches the project, process environment, browser, Keychain, or home directory. The
explicit file must be a same-owner, non-symlink regular file with exact mode `0600`; malformed,
duplicate, unknown, or missing selected-environment fields fail with value-free error codes.

The requested token scope is always exactly `account:read trade:read`: account summary requires the
former and Positions require the latter. The mainnet credential is user-declared read-only. The
auth-response scope text is neither parsed nor treated as an application permission gate and never
enters output or persistence. The client calls only
`public/auth`, `private/get_account_summary(currency=BTC, extended=false)`, and
`private/get_positions(currency=BTC)` against fixed mainnet. The command returns a safe JSON receipt
with component status, position count, capture boundary, blockers, and permission labels; it emits
no account values, position details, client identifier, secret, bearer token, or auth-response scope
text. `CREDENTIAL_SCOPE=USER_DECLARED_READ_ONLY` records the machine contract, while
`TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE` prevents an invented effective-token claim. C1 contains no
write method and does not modify the shared B3 Workbench.

## C2 Testnet Combo lifecycle

This entrypoint is usable only when the sole active task authorizes one bounded Testnet lifecycle:

```bash
.venv/bin/optimatrix-combo \
  --credentials-file /Users/logan/.config/optimatrix/credentials.env
```

It fixes the host to `test.deribit.com`, selects an existing active BTC Combo and minimum amount,
posts one same-side `post_only`/`reject_post_only` order, then reconciles order state, actual filled
amount, per-order trades and fee, and BTC Positions. An unfilled order is cancelled and rechecked.
Only a natural fill activates an opposite same-Combo `reduce_only` exit using the final actual
filled amount. Output is a safe `TESTNET / PRIVATE_EXECUTION / NO_REAL_CAPITAL` receipt; it contains
no credential, token, account value, or Position detail and changes no shared B3 Workbench asset.
