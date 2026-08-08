# Optimatrix Current Stage

**Status:** ACTIVE PERMISSION AUTHORITY

**Current permission boundary:** `PUBLIC_SHADOW`

**Current task kind:** `VALIDATION_ONLY`

**Current implementation status:** `DUAL_PRODUCT_CONSTRUCTION_ACCEPTED`

**Accepted implementation boundary:** `INVERSE_BTC_V1_CONSTRUCTION_ACCEPTED_AT_89A6EB02`

**Production Short Vol Radar:** `LINEAR_BTC_USDC_V1_ACCEPTED`

**Persistent service:** `ONE_INVERSE_BTC_RUNTIME_AUTHORIZED`

**Live commands:** `ONE_EXACT_INVERSE_START_REQUIRED`

**Sole authorized closure:** `SHORT_VOL_INVERSE_BTC_NATURAL_SHADOW_VALIDATION`

## Current truth

The accepted production-public component-book lifecycle remains a counterfactual. It is
`NOT_AN_ORDER`, `NOT_A_FILL`, `NOT_AN_ATOMIC_QUOTE`, provides no liquidity reservation, and proves
neither fillability nor strategy edge.

The final repaired Linear BTC-USDC process used code identity
`6dee819961d76b622dbc6b77997e1f987451a096`, runtime identity
`sha256:fdb4f0b3eadfc0f892cfad210142d14c521394cfeb6fbd5c761554228c45998f`, and state root
`/private/tmp/optimatrix-natural-shadow-currentness-repair-T6MhNA`. It stopped cleanly at explicit
human request with exit status `0` and is not authorized to restart. Its terminal canonical funnel
was:

```text
APPLICABLE_MARKET_SCOPE                         5,043,177 contract evaluations
RADAR_KNOWN                                    5,040,616 contract evaluations
ANOMALY_ACTIVE                                        11 distinct Episodes
STRUCTURE_REVIEWABLE                                   6 distinct Episodes
COMPONENT_BOOK_COUNTERFACTUAL_EVALUABLE                6 distinct Episodes
UNDERWRITING_EVALUABLE                                 6 distinct Episodes
CANDIDATE                                               0 distinct Episodes
SHADOW_CASE_OPENED                                      0 admitted-Candidate Cases
SHADOW_CASE_OUTCOME                                     0 admitted-Candidate Outcomes
```

The `2,561` post-warmup Radar-knownness gap conserves as `OPTION_BOOK_UNKNOWN 1,792`,
`POST_STATUS_BOOTSTRAP_REQUIRED 768`, and `NUMERICAL_BOUNDARY_UNRESOLVED 1`. Conditional on reaching
Underwriting, all six structures stopped at `CREDIT_NOT_ABOVE_FUTURE_COST_RESERVE 6`. These are
measured Linear results; they do not predict Inverse BTC opportunity frequency or economics.

The separate selected-decision research projection made six future-blind selections, all original
`ABSTAIN`. Five received an eligible strictly later refresh and opened no-trade control Cases. One
terminalized as `UNKNOWN_CONSUMED` because its local receive skew was `7,100 ms`, above the frozen
`4,000 ms` budget. Each of the five Case directories contains `opened.json`, `first-close.json`,
and `outcome.json`; the official reader reports `COMPLETE`. Every terminal Outcome is
`CENSORED_AT_STOP`, with economic availability `UNKNOWN` and no PnL. `COMPLETE` therefore means
lifecycle-terminal, not known economics, profitability, or Policy quality.

PR [#27](https://github.com/loganleegithub/Optimatrix/pull/27) merged as
`89a6eb02ab3771c5e6d2874a98463c6100b04165`; that exact merged main passed the repository CI. It
accepted `INVERSE_BTC_V1` construction beside `LINEAR_BTC_USDC_V1`: strict startup product
selection, content-distinct Policy chains, Inverse BTC-native economics with explicit USD
valuation, schema-v4 Case bytes, cross-product rejection, and unchanged Linear schema-v3 behavior.
Construction and green checks provide no natural Inverse market, funnel, Case, or Outcome result.
Public facts do not establish actual account margin, which remains `UNKNOWN`.

## Exact authorized runtime

This Authority becomes executable only after the Authority PR containing it is merged to `main`
and that merged main passes CI. Before both conditions, the registered topology remains `NONE` and
the command below is forbidden.

After activation, exactly one clean process may be started with:

```text
implementation code identity: 89a6eb02ab3771c5e6d2874a98463c6100b04165
product:                      inverse-btc / INVERSE_BTC_V1
product spec identity:        sha256:ff90da92cefe8e530339df38505fe7726b92b45b1855b751f2633ffd4fdb2172
Radar Policy identity:        sha256:283c2a8cc5e14cbed94b0f2a41ddd18ff2410772ae45d07abfea80d04446b1af
Underwriting Policy identity: sha256:76a93725bb4923a70a2865b1e06add3b5a23ae80a831029c558ce188be6e7834
Position Policy identity:     sha256:cb3866b8efd45d5c05ed23ab56658c2cdbf0359132e39f52ce329761ad933b8e
state root:                   /private/tmp/optimatrix-inverse-btc-natural-shadow-validation-v1
Workbench:                    http://127.0.0.1:8765
```

The exact invocation, from a clean checkout of the registered implementation commit, is:

```bash
python -m radar_runtime serve-shadow \
  --state-root /private/tmp/optimatrix-inverse-btc-natural-shadow-validation-v1 \
  --workbench-host 127.0.0.1 \
  --workbench-port 8765 \
  --product inverse-btc
```

This is the natural Shadow process, not a preliminary probe or disposable smoke. No Linear process
may run concurrently. The state root must be new at first start and may be owned only by this
process. An in-process public-transport reconnect may create a new session epoch while preserving
the runtime identity and owners; it is not a process restart. Once the process exits for any
reason, this Authority is spent and does not permit another start.

## First-600-second gate

Let `T0` be the monotonic instant at which the one authorized process is invoked. The first
`600 seconds` of that process are one non-durable, read-only `CURRENT_AND_COMBO_ISOLATION` gate.
Read the existing immutable `/api/workbench/current` snapshot at bounded intervals no wider than
`30 seconds`; do not add a runtime gate, evidence store, manifest, or long-lived observer service.

Identity and isolation apply to every complete snapshot successfully read from the first Workbench
response through the terminal sample at or after `T0 + 600 seconds`:

- Workbench schema is `5`; code, runtime, product-spec, and all three Policy identities remain
  fixed, with the code/product/Policy values registered above;
- the selected product is `inverse-btc`, market family is `DERIBIT_BTC_OPTIONS`, price index is
  `btc_usd`, public/native/settlement currency is BTC, valuation is `USD_EQUIVALENT`, and Case
  schema is `4`;
- the index-history source is the Inverse `BTC_USD` source; every visible Radar, Underwriting,
  selected-decision, Shadow, Position, Outcome, leg, and Combo fact belongs to the registered
  product; every visible option or leg name matches the Inverse `BTC-...` family;
- the serialized Inverse document contains no Linear `BTC_USDC`, `LINEAR_BTC_USDC`, or `_usdc`
  field-name contamination. `NO_ACTIVE_COMBO`, `NOT_EVALUATED`, or no visible Combo is neutral and
  must not be reclassified as a liquidity, funnel, or isolation failure;
- after the first successful Workbench response, an unreadable/malformed snapshot, changed runtime
  identity, changed code/Policy/product identity, Linear fact, mixed-product leg, or second process
  fails the gate immediately.

Startup `STARTING`, `CONNECTING`, `UNKNOWN`, or `DEGRADED` before first `CURRENT` is not itself a
failure. To pass at `T0 + 600 seconds`, however, at least one sample in the window and the terminal
sample must report `service.phase=RUNNING`, `service.data_state=CURRENT`, `service.ready=true`,
`system.coverage_state=KNOWN_COMPLETE`, and a positive monitored-instrument count. Business counts
may remain zero, and Radar evaluations may truthfully remain warmup or `UNKNOWN`.

If the process exits, the terminal sample is not `CURRENT`, or any identity/isolation condition
fails, stop cleanly when possible, report the exact earliest failure, and do not restart. A failed
gate authorizes neither repair nor another process under this task. A naturally opened Case or
Outcome before the terminal gate sample does not waive the gate and is not interpreted until the
gate passes.

## Post-gate Outcome wait

Only after the gate passes may the same uninterrupted process, same runtime identity, same Policy
chain, and same state root continue waiting for the first natural Inverse schema-v4 Outcome. Passing
the gate is not permission to stop and start a fresh observation.

The first qualifying result is an official-reader `COMPLETE` schema-v4 Case whose product identity
is the registered `INVERSE_BTC_V1` identity and whose Outcome terminal state is `MATURE_KNOWN` or
`MATURE_UNKNOWN`. It may be an admitted-Candidate Case or the separately labeled future-blind
selected WATCH/ABSTAIN no-trade control; its enrollment kind must be reported and the latter cannot
change canonical Candidate conversion counts. `CENSORED_AT_STOP`, `CENSORED_AT_FAILURE`, an
incomplete Case, a Workbench row alone, or an Outcome from another product/runtime does not satisfy
the closure.

After the first qualifying Outcome is read through the official Case reader, stop the same process
cleanly once and re-read the Case. If no qualifying Outcome has formed, zero remains a truthful
nonterminal result and the same process continues. Fatal process exit ends the authorization
without restart and leaves the task incomplete.

## Allowed work

- merge this bounded Authority-only change, wait for merged-main CI, and then perform the one exact
  public-only Inverse startup;
- read the loopback immutable Workbench during the gate and subsequent wait;
- let the existing owner write only natural Inverse schema-v4 Case transitions and Outcomes under
  the registered state root;
- read a terminal Case through the existing official reader and issue one clean stop after success.

## Forbidden work

- any start before Authority merge plus merged-main CI success, any restart, a second runtime,
  concurrent Linear observation, another state root, another port, or another code/Policy/product
  identity;
- any code or Policy change, threshold/target/reserve tuning, manufactured clue/Candidate/Case,
  source replay, injected market fact, deletion or mutation of natural Case bytes, or reuse of the
  five Linear Case directories;
- any private/account API call, credential, balance, margin, order, fill, capital, settlement
  action, actual exposure, supervised deployment, or commissioning;
- treating a 600-second gate, `NO_ACTIVE_COMBO`, Candidate zero, a censored Case, green CI, or a
  Workbench display as evidence of frequency, fillability, edge, profitability, qualification, or
  execution readiness;
- a manifest, receipt chain, application-owned gate, extra schema, full-feed persistence, replay
  platform, host PID/log/`lsof` inspection, supervisor, or automatic restart.

## Acceptance boundary

The task closes only when the exact one-start topology is activated after Authority merged-main CI,
the same runtime passes the full first-600-second gate, one qualifying natural Inverse schema-v4
Outcome is verified by the official reader, and the process stops cleanly without restart. The gate
alone is an intermediate prerequisite, not business closure. If the market produces no qualifying
Outcome, the runtime keeps waiting and the task remains active; no threshold change is authorized.
