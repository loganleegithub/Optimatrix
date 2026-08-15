# Task — C1 mainnet request-scoped auth

**Status:** ACTIVE

**Task kind:** IMPLEMENTATION

**Target maturity stage:** `C1_PRIVATE_READ_ONLY`

**Runtime implementation:** REQUIRED only for the bounded offline C1 source, owner, Workbench, and
fake-test changes below. No deployed or continuous runtime may change.

**Live commands:** FORBIDDEN. No credential read, authentication, account, Positions, Chrome,
runtime, root, process, deployment, order, trade, fill, cancel, transfer, or capital action is
authorized.

**Owning authority/contract:** `docs/authority/PRODUCT_CONSTITUTION.md`,
`docs/authority/CURRENT_STAGE.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`,
`docs/contracts/CASE_POSITION_OUTCOME.md`, `docs/research/PRIMARY_SOURCES.md`, and
`tasks/TEMPLATE.md`

No placeholder remains. Stage links this file as the only active non-template task.

## Closure

**Given:** the explicit mainnet credential is user-declared read-only and stored only in the
owner-only machine credential file. C1 requests exactly `account:read trade:read` and its application
contains only `public/auth`, BTC `private/get_account_summary(extended=false)`, and BTC
`private/get_positions`. Nevertheless one no-retry mainnet auth closed
`MAINNET/UNKNOWN/AUTH_SCOPE_UNKNOWN`; summary and Positions were both uncalled, no order method
exists, and selected credential values are absent from all four ignored artifacts.

**When:** delete auth-response scope parsing, normalization, gating, serialization, and Workbench
display from the C1 mainnet path while retaining access-token, bearer type, expiry, environment,
JSON-RPC envelope, timing, fixed request scope, host, method, currency, and parameter validation

**Then:** any auth response scope or metadata text—including absent, arbitrary, or unusual text—has
no effect on whether the two fixed reads are called and cannot appear in repr, exception,
Observation, CLI, Workbench, or persistence. A successful auth records only
`CREDENTIAL_SCOPE=USER_DECLARED_READ_ONLY` and `TOKEN_SCOPE_NORMALIZATION=UNAVAILABLE`; it never
claims an exact effective scope. Missing or malformed token, bearer type, expiry, environment, or
response envelope still fails before both reads. Fake transport proves the method allowlist remains
exactly three and every write/order/cancel/trade method is unconstructable.

**Affected identity and population:** the transient C1 mainnet
`AuthenticatedAccountObservation` identity and schema-9 private-account Workbench projection only;
no MarketObservation, DecisionWindow, OpportunityEpisode, TradeCase, Position, Ledger, Journal,
risk allocation, reservation, route, Entry, order, trade, fill, or Outcome population changes

**Baseline and denominator:** live C1 mainnet observations remain `0/1`; fake scope-agnostic auth
success coverage is `0/1`

**Primary blocker and expected delta:** `C1_MAINNET_RESPONSE_SCOPE_IS_FALSE_PRODUCT_GATE` becomes a
fake proof that arbitrary response scope text reaches exactly the two reads without expanding the
method surface

**Known-at and DataHealth boundary:** only the matching mainnet response envelope, access-token
validity, and causal auth/summary/Positions boundaries become known. Response scope normalization is
explicitly `UNAVAILABLE`, not inferred or persisted.

## Effects and scope

**Risk allocation effect:** NONE

**ObservationLedger / CaseJournal effect and consumer:** NONE; only the explicit transient account
Observation, safe CLI summary, and isolated static Workbench consume the new permission-basis labels

**Legacy-data effect:** NONE; no durable C1 observation exists and no B3 root is read or migrated

**Permission effect:** NONE beyond offline implementation. A later sole `VALIDATION_ONLY` task is
required for the supplied credential file and one mainnet read chain.

**Files and behavior in scope:** `src/optimatrix/account.py`,
`src/optimatrix/deribit_private.py`, `src/optimatrix/private_cli.py`,
`src/optimatrix/workbench.py`, `src/optimatrix/workbench_static/app.js`, direct C1 owner text in
`docs/authority/PRODUCT_CONSTITUTION.md`, `docs/authority/SYSTEM_ARCHITECTURE.md`,
`docs/contracts/BTC_0DTE_TWO_SIDED_SHORT_VOL.md`, `docs/research/PRIMARY_SOURCES.md`, `README.md`,
and direct tests in `tests/test_account.py`, `tests/test_deribit_private.py`,
`tests/test_private_cli.py`, `tests/test_workbench.py`, and `tests/test_authority.py`

**Out of scope:** any new host, method, currency, parameter, credential source, retry, dependency,
or schema consumer; testnet; C2; mainnet write/order/cancel/trade/history/Combo/RFQ/wallet/transfer;
Chrome or key mutation; populated project `.env`; Public Shadow or Policy change; Candidate
manufacture; B3 root/runtime/process access; D1; deployment, merge, and push

**Complexity added / deleted:** delete the response-scope parser and all token-content projection;
add only one fixed permission-basis enum value and one fixed normalization label. No raw-scope
field, registry, compatibility path, dependency, or background behavior is added.

## Verification and closure

**Cheapest falsification:** fake HTTP auth responses with absent and arbitrary scope text both reach
exactly summary and Positions; malformed token/envelope remains fail-closed; static allowlist and
host assertions prove no mainnet write surface; fake secret and response-scope sentinel are absent
from repr, errors, serialization, CLI, Workbench, and repository artifacts

**Repository gate:** focused `pytest`, Ruff, mypy, JavaScript syntax, `git diff --check`, then
`make check`

**External evidence:** `UNVERIFIED`; the next sole `VALIDATION_ONLY` task performs at most one new
mainnet auth → summary → Positions chain using the explicit owner-only credential file

Close only after the fake delta and complete repository gate pass. Replace Stage with the post-task
snapshot, remove this file, and activate at most one separate validation task; do not append
completion history.
